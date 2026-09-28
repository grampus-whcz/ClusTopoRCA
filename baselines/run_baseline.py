"""
Run a classical RCA baseline (MicroCause / CIRCA) over OpenRCA queries.

Example:
    python run_baseline.py --method microcause --dataset Bank --start 0 --end 5
    python run_baseline.py --method circa --dataset Market-1 --out results/circa_M1.jsonl

Each query produces one JSON line with the ranked candidate components and
hit@k against the ground truth. The output file is resumable: already
completed (idx, method) pairs are skipped on re-run.

Protocol notes
--------------
* The analysis window is parsed from the OpenRCA query instruction (30 min).
  Metric context of ``--pre-minutes`` before the window is added so that the
  methods have a normal-behaviour baseline.
* ``--inject-mode gt`` (default) uses the ground-truth fault timestamp from
  record.csv as the alert time, following the RCAEval evaluation protocol
  (where inject_time.txt is given). ``detect`` derives the alert time from
  the SLI series instead. Only CIRCA consumes inject_time; MicroCause
  ignores it (as in RCAEval).
* Predictions are ranked KPI columns mapped back to entities; the ranking is
  filtered to the candidate component set (union of record.csv components).
"""

import argparse
import json
import os
import sys
import time
import traceback

import numpy as np
import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import openrca_data as od


def run_one(method, dataset, qrow, rrow, args, cache):
    ws, we = od.parse_window(qrow["instruction"])
    df, col2entity = od.build_frame(dataset, ws, we,
                                    pre_minutes=args.pre_minutes,
                                    post_minutes=args.post_minutes,
                                    cache=cache)
    sli_col = od.select_sli(df, dataset, ws, we)
    df = od.prefilter_entities(df, col2entity, ws, we,
                               max_entities=args.max_entities,
                               force_cols=[sli_col] if sli_col else [])

    if args.inject_mode == "gt":
        inject_time = int(rrow["timestamp"])
    else:
        inject_time = od.detect_inject_time(df, sli_col, ws, we)

    candidates = set(od.candidate_inventory(dataset))

    if method == "microcause":
        from core.microcause import microcause
        sli = sli_col if sli_col in df.columns else None
        if sli is None:
            # fall back to the most anomalous column overall
            z = od._robust_z(df, [c for c in df.columns if c != "time"], ws, we)
            sli = z.idxmax()
        t0 = time.time()
        out = microcause(df.drop(columns=["time"]), sli=sli,
                         tau_max=args.tau_max, seed=args.seed)
        ranks = out["ranks"]
    elif method == "circa":
        from core.circa import circa
        t0 = time.time()
        out = circa(df, inject_time=inject_time)
        ranks = out["ranks"]
    else:
        raise ValueError(method)
    elapsed = time.time() - t0

    # ranked KPI columns -> ranked candidate entities (dedup, candidates only)
    ranked_entities, seen = [], set()
    for col in ranks:
        ent = col2entity.get(col)
        if ent is None or ent not in candidates or ent in seen:
            continue
        seen.add(ent)
        ranked_entities.append(ent)

    gt = rrow["component"]
    try:
        gt_rank = ranked_entities.index(gt) + 1
    except ValueError:
        gt_rank = None
    return {
        "idx": int(rrow["idx"]),
        "dataset": dataset,
        "method": method,
        "task_index": qrow["task_index"],
        "gt_component": gt,
        "gt_level": rrow["level"],
        "gt_reason": rrow["reason"],
        "gt_time": int(rrow["timestamp"]),
        "window": [ws, we],
        "inject_time": inject_time,
        "sli": sli_col,
        "n_columns": int(df.shape[1] - 1),
        "ranked_entities": ranked_entities[:10],
        "top1": ranked_entities[0] if ranked_entities else None,
        "gt_rank": gt_rank,
        "hit@1": int(gt_rank == 1),
        "hit@3": int(gt_rank is not None and gt_rank <= 3),
        "hit@5": int(gt_rank is not None and gt_rank <= 5),
        "runtime_s": round(elapsed, 2),
        "status": "ok",
    }


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--method", required=True, choices=["microcause", "circa"])
    ap.add_argument("--dataset", required=True, choices=list(od.DATASETS))
    ap.add_argument("--start", type=int, default=0)
    ap.add_argument("--end", type=int, default=None, help="exclusive; default all")
    ap.add_argument("--out", default=None)
    ap.add_argument("--pre-minutes", type=int, default=30)
    ap.add_argument("--post-minutes", type=int, default=10)
    ap.add_argument("--max-entities", type=int, default=20)
    ap.add_argument("--inject-mode", choices=["gt", "detect"], default="gt")
    ap.add_argument("--tau-max", type=int, default=10)
    ap.add_argument("--seed", type=int, default=0)
    args = ap.parse_args()

    if args.out is None:
        args.out = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                                "results", f"{args.method}_{args.dataset}.jsonl")
    os.makedirs(os.path.dirname(args.out), exist_ok=True)

    records = od.load_records(args.dataset)
    queries = od.load_queries(args.dataset)
    end = len(records) if args.end is None else min(args.end, len(records))

    done = set()
    if os.path.exists(args.out):
        with open(args.out) as f:
            for line in f:
                try:
                    done.add(json.loads(line)["idx"])
                except Exception:
                    pass

    cache = {}
    with open(args.out, "a") as fout:
        for idx in range(args.start, end):
            if idx in done:
                print(f"[skip] idx={idx} already done", flush=True)
                continue
            rrow, qrow = records.iloc[idx], queries.iloc[idx]
            try:
                rec = run_one(args.method, args.dataset, qrow, rrow, args, cache)
            except Exception as e:
                rec = {"idx": idx, "dataset": args.dataset, "method": args.method,
                       "gt_component": rrow["component"], "gt_level": rrow["level"],
                       "gt_reason": rrow["reason"], "gt_time": int(rrow["timestamp"]),
                       "status": "error", "error": f"{type(e).__name__}: {e}",
                       "trace": traceback.format_exc()[-2000:]}
            fout.write(json.dumps(rec) + "\n")
            fout.flush()
            flag = "" if rec["status"] == "ok" else f" ERROR: {rec.get('error', '')}"
            print(f"[done] idx={idx} status={rec['status']} "
                  f"top1={rec.get('top1')} gt={rec['gt_component']} "
                  f"gt_rank={rec.get('gt_rank')} rt={rec.get('runtime_s')}s{flag}",
                  flush=True)


if __name__ == "__main__":
    main()
