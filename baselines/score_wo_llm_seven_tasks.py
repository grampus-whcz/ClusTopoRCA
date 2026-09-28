"""
Score the w/o-LLM variant on OpenRCA's official 7-task metric (Correct /
Partial / Total per dataset) using the repo's own main/evaluate.py against
query.csv scoring_points — directly comparable to the paper's main table
(single-candidate answer, stricter than the multi-candidate protocol).

Output: results/wo_llm_seven_task_scores.csv
"""

import json
import os
import sys

import pandas as pd

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(HERE)
sys.path.insert(0, REPO)

from main.evaluate import evaluate  # noqa: E402

import openrca_data as od  # noqa: E402

DATASETS = ["Bank", "Telecom", "Market-1", "Market-2"]


def build_prediction(rec):
    """Format a wo_llm record as the prediction JSON the evaluator expects."""
    time_str = ""
    if rec.get("pred_time"):
        time_str = pd.to_datetime(int(rec["pred_time"]), unit="s", utc=True) \
            .tz_convert("Asia/Shanghai").strftime("%Y-%m-%d %H:%M:%S")
    fields = {}
    if time_str:
        fields["root cause occurrence datetime"] = time_str
    if rec.get("top1"):
        fields["root cause component"] = rec["top1"]
    if rec.get("pred_reason"):
        fields["root cause reason"] = rec["pred_reason"]
    return json.dumps(fields, ensure_ascii=False)


def main():
    rows = []
    for ds in DATASETS:
        queries = od.load_queries(ds)
        path = os.path.join(HERE, "results", f"wo_llm_{ds}.jsonl")
        per_task = {}
        for line in open(path):
            r = json.loads(line)
            if r.get("status") != "ok":
                continue
            sp = queries.iloc[r["idx"]]["scoring_points"]
            prediction = build_prediction(r)
            try:
                _, _, score = evaluate(prediction, sp)
            except Exception:
                score = 0.0
            per_task[r["idx"]] = (r["task_index"], score)
        n = len(per_task)
        correct = sum(1 for _, s in per_task.values() if s == 1.0) / n
        partial = sum(1 for _, s in per_task.values() if 0 < s < 1.0) / n
        rows.append({"dataset": ds, "n": n,
                     "correct": round(correct, 4), "partial": round(partial, 4),
                     "total": round(correct + partial, 4)})
        # per difficulty (easy task_1-3, mid task_4-6, hard task_7)
        for label, tasks in [("easy", {"task_1", "task_2", "task_3"}),
                             ("mid", {"task_4", "task_5", "task_6"}),
                             ("hard", {"task_7"})]:
            sub = [s for t, s in per_task.values() if t in tasks]
            if sub:
                c = sum(1 for s in sub if s == 1.0) / len(sub)
                p = sum(1 for s in sub if 0 < s < 1.0) / len(sub)
                rows.append({"dataset": f"{ds}-{label}", "n": len(sub),
                             "correct": round(c, 4), "partial": round(p, 4),
                             "total": round(c + p, 4)})
    df = pd.DataFrame(rows)
    df.to_csv(os.path.join(HERE, "results", "wo_llm_seven_task_scores.csv"), index=False)
    print(df.to_string(index=False))


if __name__ == "__main__":
    main()
