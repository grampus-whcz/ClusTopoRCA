"""
Summarize baseline results (JSONL from run_baseline.py).

Usage:
    python summarize.py results/microcause_Bank.jsonl [more.jsonl ...]

Prints overall and per-level top-1/3/5 accuracy and MRR on the root-cause
*component* (classical metric-based methods localize the component only).
"""

import argparse
import json
import os
import sys


def load(path):
    rows = []
    with open(path) as f:
        for line in f:
            try:
                r = json.loads(line)
            except Exception:
                continue
            if r.get("status") == "ok":
                rows.append(r)
    return rows


def report(name, rows):
    n = len(rows)
    if n == 0:
        print(f"{name}: no successful rows")
        return
    h1 = sum(r["hit@1"] for r in rows) / n
    h3 = sum(r["hit@3"] for r in rows) / n
    h5 = sum(r["hit@5"] for r in rows) / n
    mrr = sum(1.0 / r["gt_rank"] for r in rows if r.get("gt_rank")) / n
    print(f"{name}: n={n}  top1={h1:.3f}  top3={h3:.3f}  top5={h5:.3f}  MRR={mrr:.3f}")
    levels = sorted(set(r.get("gt_level", "?") for r in rows))
    for lv in levels:
        sub = [r for r in rows if r.get("gt_level") == lv]
        m = len(sub)
        sh1 = sum(r["hit@1"] for r in sub) / m
        sh3 = sum(r["hit@3"] for r in sub) / m
        sh5 = sum(r["hit@5"] for r in sub) / m
        smrr = sum(1.0 / r["gt_rank"] for r in sub if r.get("gt_rank")) / m
        print(f"    level={lv:8s} n={m:3d}  top1={sh1:.3f}  top3={sh3:.3f}  top5={sh5:.3f}  MRR={smrr:.3f}")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("files", nargs="+")
    args = ap.parse_args()
    for path in args.files:
        rows = load(path)
        n_err = sum(1 for _ in open(path)) - len(rows)
        name = os.path.basename(path)
        report(name, rows)
        if n_err:
            print(f"    ({n_err} rows with status != ok)")


if __name__ == "__main__":
    main()
