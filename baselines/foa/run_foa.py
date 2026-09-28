"""
Batch driver: run the FoA reproduction over OpenRCA queries.

Output JSONL is aligned with run_baseline.py / run_mabc.py (method="foa"),
including per-query token usage and runtime.

Usage:
    python run_foa.py --dataset Bank --start 0 --end 3
"""

import argparse
import json
import os
import re
import sys
import time
import traceback
from datetime import datetime

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)                       # foa package modules
sys.path.insert(0, os.path.dirname(HERE))      # openrca_data

import openrca_data as od  # noqa: E402


def parse_answer_components(answer: str, candidates: list):
    """Extract ranked root-cause entries from the final JSON answer."""
    entries = []
    try:
        obj = json.loads(answer)
        for k in sorted(obj, key=lambda x: int(x) if str(x).isdigit() else 99):
            if isinstance(obj[k], dict):
                entries.append(obj[k])
    except Exception:
        # fallback: single-object regex (field order as in OpenRCA evaluate.py)
        for m in re.finditer(
                r'"root cause component":\s*"(.*?)".*?"root cause reason":\s*"(.*?)"',
                answer or "", re.DOTALL):
            entries.append({"root cause component": m.group(1),
                            "root cause reason": m.group(2)})
    ranked, seen = [], set()
    for e in entries:
        raw = str(e.get("root cause component", "")).strip()
        hit = next((c for c in candidates if c == raw), None) or \
            next((c for c in candidates if c.lower() == raw.lower()), None) or \
            next((c for c in sorted(candidates, key=len, reverse=True)
                  if c in raw or (raw and raw in c)), None)
        if hit and hit not in seen:
            seen.add(hit)
            ranked.append({"component": hit,
                           "reason": e.get("root cause reason"),
                           "time": e.get("root cause occurrence datetime")})
    return ranked


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--dataset", required=True, choices=list(od.DATASETS))
    ap.add_argument("--start", type=int, default=0)
    ap.add_argument("--end", type=int, default=None)
    ap.add_argument("--out", default=None)
    args = ap.parse_args()

    import tools_data
    from foa_loop import run_foa
    from llm import TOKEN_USAGE, reset_token_usage

    records, queries = od.load_records(args.dataset), od.load_queries(args.dataset)
    candidates = od.candidate_inventory(args.dataset)
    reasons = sorted(records["reason"].unique().tolist())
    end = len(records) if args.end is None else min(args.end, len(records))
    out = args.out or os.path.join(os.path.dirname(HERE), "results",
                                   f"foa_{args.dataset}.jsonl")
    os.makedirs(os.path.dirname(out), exist_ok=True)
    os.makedirs(os.path.join(HERE, "logs", args.dataset), exist_ok=True)

    done = set()
    if os.path.exists(out):
        with open(out) as f:
            for line in f:
                try:
                    done.add(json.loads(line)["idx"])
                except Exception:
                    pass

    tools_data.CURRENT["dataset"] = args.dataset

    with open(out, "a") as fout:
        for idx in range(args.start, end):
            if idx in done:
                print(f"[skip] idx={idx}", flush=True)
                continue
            qrow, rrow = queries.iloc[idx], records.iloc[idx]
            ws, we = od.parse_window(qrow["instruction"])
            start_str = datetime.fromtimestamp(ws, od.TZ8).strftime("%Y-%m-%d %H:%M:%S")
            end_str = datetime.fromtimestamp(we, od.TZ8).strftime("%Y-%m-%d %H:%M:%S")
            task = (qrow["instruction"]
                    + f"\nThe analysis data window is from {start_str} to {end_str} (UTC+8).")
            reset_token_usage()
            t0 = time.time()
            try:
                answer, history = run_foa(task, start_str, end_str, candidates, reasons)
                ranked = parse_answer_components(answer, candidates)
                ents = [r["component"] for r in ranked]
                gt = rrow["component"]
                gt_rank = ents.index(gt) + 1 if gt in ents else None
                rec = {"idx": idx, "dataset": args.dataset, "method": "foa",
                       "task_index": qrow["task_index"], "gt_component": gt,
                       "gt_level": rrow["level"], "gt_reason": rrow["reason"],
                       "gt_time": int(rrow["timestamp"]), "window": [ws, we],
                       "ranked_entities": ents, "top1": ents[0] if ents else None,
                       "gt_rank": gt_rank,
                       "hit@1": int(gt_rank == 1),
                       "hit@3": int(gt_rank is not None and gt_rank <= 3),
                       "hit@5": int(gt_rank is not None and gt_rank <= 5),
                       "n_steps": len(history),
                       "tokens": dict(TOKEN_USAGE),
                       "runtime_s": round(time.time() - t0, 2), "status": "ok"}
                with open(os.path.join(HERE, "logs", args.dataset, f"query_{idx}.log"), "w") as lf:
                    lf.write(json.dumps(history, ensure_ascii=False, indent=2))
                    lf.write("\n\n=== final answer ===\n" + answer)
            except Exception as e:
                rec = {"idx": idx, "dataset": args.dataset, "method": "foa",
                       "gt_component": rrow["component"], "gt_level": rrow["level"],
                       "gt_reason": rrow["reason"], "gt_time": int(rrow["timestamp"]),
                       "status": "error", "error": f"{type(e).__name__}: {e}",
                       "trace": traceback.format_exc()[-2000:],
                       "tokens": dict(TOKEN_USAGE),
                       "runtime_s": round(time.time() - t0, 2)}
            fout.write(json.dumps(rec, ensure_ascii=False) + "\n")
            fout.flush()
            print(f"[done] idx={idx} status={rec['status']} pred={rec.get('top1')} "
                  f"gt={rec['gt_component']} gt_rank={rec.get('gt_rank')} "
                  f"tokens={rec['tokens']['total_tokens']} rt={rec['runtime_s']}s",
                  flush=True)


if __name__ == "__main__":
    main()
