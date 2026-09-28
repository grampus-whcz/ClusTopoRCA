#!/usr/bin/env python
"""Top-1 vs Top-1 fair comparison: ClusTopoRCA vs RCA-agent.

Both methods are scored with a single best answer per query:
  * ClusTopoRCA: its highest-suspicious-score candidate (from the mined
    clustoporca_element_predictions.csv);
  * RCA-agent: its first-run single prediction per query (first occurrence of
    row_id in test/result/{dataset}/agent-rca-{model}.csv), which is the run
    the paper's main table reports.

Outputs: results/top1_vs_top1_comparison.csv (+ printed table).
"""
import os
import sys

import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import openrca_data as od  # noqa: E402

REPO = "/root/shared-nvme/work/agent/OpenRCA"
HERE = os.path.dirname(os.path.abspath(__file__))
MODELS = ["gpt-4o", "gemini-2.5-pro-preview-p", "deepseek-r1-0528",
          "qwen3-235b-a22b-instruct-2507", "glm-4.7"]
DATASETS = ["Bank", "Telecom", "Market-1", "Market-2"]
RCA_CSV = {"Bank": "Bank", "Telecom": "Telecom",
           "Market-1": "Market/cloudbed-1", "Market-2": "Market/cloudbed-2"}

NEED = {"task_1": ["time"], "task_2": ["reason"], "task_3": ["component"],
        "task_4": ["time", "reason"], "task_5": ["time", "component"],
        "task_6": ["component", "reason"], "task_7": ["time", "component", "reason"]}


def clustoporca_top1():
    df = pd.read_csv(os.path.join(HERE, "results", "clustoporca_element_predictions.csv"))
    df = df[df["method"] == "clustoporca"]

    def hit_time(r):
        try:
            return abs(pd.to_datetime(str(r["predicted_time"])).timestamp()
                       - float(r["gt_time"])) <= 60
        except Exception:
            return False

    def score(r):
        need = NEED.get(r["task_index"], [])
        if not need:
            return 0.0
        hits = sum(int(hit_time(r)) if el == "time"
                   else int(str(r["predicted_component"]) == str(r["gt_component"])) if el == "component"
                   else int(str(r["predicted_reason"]) == str(r["gt_reason"]))
                   for el in need)
        return hits / len(need)

    df["top1_score"] = df.apply(score, axis=1)
    return df[["dataset", "model", "query_idx", "top1_score"]].rename(
        columns={"query_idx": "idx"})


def rca_agent_top1():
    rows = []
    for ds in DATASETS:
        for m in MODELS:
            path = os.path.join(REPO, "test/result", RCA_CSV[ds], f"agent-rca-{m}.csv")
            if not os.path.exists(path):
                continue
            df = pd.read_csv(path)
            df = df.dropna(subset=["row_id"])
            first = df.drop_duplicates(subset=["row_id"], keep="first")
            for _, r in first.iterrows():
                rows.append({"dataset": ds, "model": m,
                             "idx": int(r["row_id"]),
                             "top1_score": float(r["score"])})
    return pd.DataFrame(rows)


def summarize(scores, label, ds, n):
    vals = scores
    c = sum(1 for v in vals if v >= 0.999) / n * 100
    p = sum(1 for v in vals if 0 < v < 0.999) / n * 100
    return round(c, 2), round(p, 2), round(c + p, 2)


def main():
    ct = clustoporca_top1()
    ra = rca_agent_top1()
    out = []
    print(f"{'dataset':10s} {'model':30s} {'ours Top1 (C/P/T)':>18s} {'RCA-agent Top1 (C/P/T)':>22s}")
    for ds in DATASETS:
        n = len(od.load_records(ds))
        for m in MODELS:
            o = ct[(ct.dataset == ds) & (ct.model == m)]["top1_score"].tolist()
            a = ra[(ra.dataset == ds) & (ra.model == m)]["top1_score"].tolist()
            oc, op, ot = summarize(o, "ours", ds, n)
            ac, ap, at = summarize(a, "rca", ds, n)
            print(f"{ds:10s} {m:30s} {oc:>6.2f}/{op:>6.2f}/{ot:>6.2f}     {ac:>6.2f}/{ap:>6.2f}/{at:>6.2f}")
            out.append({"dataset": ds, "model": m,
                        "ours_correct": oc, "ours_partial": op, "ours_total": ot,
                        "rca_correct": ac, "rca_partial": ap, "rca_total": at,
                        "delta_total": round(ot - at, 2)})
        # per-dataset average over 5 models
        o5 = ct[ct.dataset == ds]["top1_score"].tolist()
        a5 = ra[ra.dataset == ds]["top1_score"].tolist()
        oc, op, ot = summarize(o5, "ours", ds, n)
        ac, ap, at = summarize(a5, "rca", ds, n)
        print(f"{ds:10s} {'** 5-model average **':30s} {oc:>6.2f}/{op:>6.2f}/{ot:>6.2f}     {ac:>6.2f}/{ap:>6.2f}/{at:>6.2f}")
        out.append({"dataset": ds, "model": "__avg5__",
                    "ours_correct": oc, "ours_partial": op, "ours_total": ot,
                    "rca_correct": ac, "rca_partial": ap, "rca_total": at,
                    "delta_total": round(ot - at, 2)})
    pd.DataFrame(out).to_csv(os.path.join(HERE, "results", "top1_vs_top1_comparison.csv"),
                             index=False)
    print("written: results/top1_vs_top1_comparison.csv")


if __name__ == "__main__":
    main()
