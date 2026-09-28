"""
Build the per-query, per-entity score cache used by the W_rht sweep.

For every query we store, once:
  * cand_rows  — ordered dict candidate -> {time_score, topology_score,
                 count_score, component_weight, final_score, count,
                 earliest_ts} from the offline ClusTopoRCA stage-3 scorer
                 (insertion order = the wo_llm merged ranking);
  * rht_scores — entity -> topology-parents RHT (causal consistency) score
                 from OmniTransfer_new/causal_score_helper.py
                 (``causal_def = topo_parent_rht_v1``): parents = the
                 dataset's global topology graph (the scoring scripts' own
                 construction), LinearRegression trained on the 30 min
                 preceding context, max |z| of residuals over the first 5 min
                 of the fault window, max over the entity's KPI columns.

Both are independent of W_rht, so the sweep (sweep_w_rht.py) replays the
fusion from this cache without recomputing anything.

Output: results/score_cache/{dataset}.jsonl

Usage:
    python build_score_cache.py --dataset Bank [--start 0 --end 5]
"""

import argparse
import json
import os
import sys
import time
import traceback

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, "/root/shared-nvme/work/timeSeries/OmniTransfer_new")

import openrca_data as od
import offline_scorer as osf
import causal_score_helper as csh


def _json_default(o):
    import numpy as np
    if isinstance(o, np.integer):
        return int(o)
    if isinstance(o, np.floating):
        return float(o)
    raise TypeError(f"not serializable: {type(o)}")

CACHE_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                         "results", "score_cache")


def cache_one(dataset, qrow, rrow, cache):
    ws, we = od.parse_window(qrow["instruction"])
    inventory = od.candidate_inventory(dataset)
    kind = od.DATASETS[dataset]["kind"]

    anomalies = osf.LOADERS[dataset](ws, we)
    res = osf.rank_candidates(dataset, ws, we, inventory, anomalies=anomalies)
    rec = {
        "idx": int(rrow["idx"]),
        "dataset": dataset,
        "task_index": qrow["task_index"],
        "gt_component": rrow["component"],
        "gt_level": rrow["level"],
        "gt_reason": rrow["reason"],
        "gt_time": int(rrow["timestamp"]),
        "window": [ws, we],
        "n_anomalies": res["n_anomalies"],
        "clusters": res["clusters"],
        "first_anomaly_ts": res["first_anomaly_ts"],
        "cand_rows": res["candidate_rows"],   # insertion-ordered
        "causal_def": "topo_parent_rht_v1",   # topology-parents RHT (no PC)
        "status": "ok",
    }
    try:
        # causal dimension: RHT on topology parents (causal_score_helper);
        # stored under the "rht_scores" key for fusion/sweep compatibility.
        causal = csh.compute_causal_scores(kind, ws, we, inventory,
                                           anomalies=anomalies, cache=cache)
        rec.update({"rht_scores": causal})
    except Exception as e:
        rec.update({"rht_scores": {},
                    "rht_error": f"{type(e).__name__}: {e}"})
    return rec


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--dataset", required=True, choices=list(od.DATASETS))
    ap.add_argument("--start", type=int, default=0)
    ap.add_argument("--end", type=int, default=None)
    args = ap.parse_args()

    os.makedirs(CACHE_DIR, exist_ok=True)
    out = os.path.join(CACHE_DIR, f"{args.dataset}.jsonl")

    records = od.load_records(args.dataset)
    queries = od.load_queries(args.dataset)
    end = len(records) if args.end is None else min(args.end, len(records))

    done = set()
    if os.path.exists(out):
        with open(out) as f:
            for line in f:
                try:
                    done.add(json.loads(line)["idx"])
                except Exception:
                    pass

    cache = {}
    with open(out, "a") as fout:
        for idx in range(args.start, end):
            if idx in done:
                print(f"[skip] idx={idx}", flush=True)
                continue
            rrow, qrow = records.iloc[idx], queries.iloc[idx]
            t0 = time.time()
            try:
                rec = cache_one(args.dataset, qrow, rrow, cache)
            except Exception as e:
                rec = {"idx": idx, "dataset": args.dataset,
                       "gt_component": rrow["component"],
                       "gt_time": int(rrow["timestamp"]),
                       "status": "error", "error": f"{type(e).__name__}: {e}",
                       "trace": traceback.format_exc()[-2000:]}
            rec["cache_runtime_s"] = round(time.time() - t0, 2)
            fout.write(json.dumps(rec, default=_json_default) + "\n")
            fout.flush()
            err = "" if rec["status"] == "ok" and not rec.get("rht_error") else \
                f" NOTE: {rec.get('error') or rec.get('rht_error')}"
            print(f"[done] idx={idx} n_cand={len(rec.get('cand_rows') or {})} "
                  f"n_rht={len(rec.get('rht_scores') or {})} "
                  f"rt={rec['cache_runtime_s']}s{err}", flush=True)


if __name__ == "__main__":
    main()
