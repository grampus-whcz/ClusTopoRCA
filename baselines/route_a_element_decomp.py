#!/usr/bin/env python
"""Route-a element-wise decomposition (time / component / reason), per model.

Parses the per-query lines of logs/route_a_{ds}_{model}.log
    [idx] gt=<comp> top1=<comp> reason=<pred reason> s=<score>
and reconstructs per-element hits:
  component : top1 == record.component
  reason    : predicted reason == record.reason (both truncated to the 28
              chars printed in the log)
  time      : round(s * |need|) - comp_hit - reason_hit   (only when the task
              requires the time element; sanity-checked to be 0/1)

Also recomputes the rule-based w/o-LLM variant (same causal-fused top-1
component; time = entity's first anomaly; reason = osf.predict_reason) per
element, reusing run_route_ab's offline logic, and cross-checks its totals
against results/route_ab_offline.csv.

Accuracy convention: an element's accuracy is averaged over the queries whose
task requires that element (NEED map of verify_smoke).

Output: results/route_a_element_decomp.csv
"""
import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

import openrca_data as od  # noqa: E402
import offline_scorer as osf  # noqa: E402
import run_route_ab as rab  # noqa: E402
from verify_smoke import NEED  # noqa: E402

LOGS = {
    ("Bank", "gpt-4o"): "route_a_Bank_gpt-4o.log",
    ("Bank", "qwen3-235b"): "route_a_Bank_qwen3-235b-a22b-instruct-2507.log",
    ("Bank", "glm-4.7"): "route_a_bank_full.log",
    ("Telecom", "gpt-4o"): "route_a_Telecom_gpt-4o.log",
    ("Telecom", "qwen3-235b"): "route_a_Telecom_qwen3-235b-a22b-instruct-2507.log",
    ("Telecom", "glm-4.7"): "route_a_Telecom_full.log",
    ("Market-1", "gpt-4o"): "route_a_Market-1_gpt-4o.log",
    ("Market-1", "qwen3-235b"): "route_a_Market-1_qwen3-235b-a22b-instruct-2507.log",
    ("Market-1", "glm-4.7"): "route_a_Market-1_full.log",
    ("Market-2", "gpt-4o"): "route_a_Market-2_gpt-4o.log",
    ("Market-2", "qwen3-235b"): "route_a_Market-2_qwen3-235b-a22b-instruct-2507.log",
    ("Market-2", "glm-4.7"): "route_a_Market-2_full.log",
}

LINE = re.compile(r"\[(\d+)\]\s+gt=(\S+)\s+top1=(\S+)\s+reason=(.*?)\s+s=([\d.]+)")


def parse_log(path):
    out = {}
    for line in open(path):
        m = LINE.search(line)
        if m:
            out[int(m.group(1))] = {"top1": m.group(3),
                                    "reason": m.group(4).strip(),
                                    "s": float(m.group(5))}
    return out


def rule_variant(dataset, idx, ws, we, inventory, anomalies):
    """w/o-LLM answer per query (mirrors run_route_ab.run_dataset)."""
    fused = rab.fused_rank(dataset, idx, ws, we, inventory, anomalies)
    if not fused:
        return None, None, None
    top1 = fused[0][0]
    ent_ts = [a["ts"] for a in anomalies if a["entity"] == top1 or
              (isinstance(a["entity"], str) and top1 in a["entity"].split("->"))]
    pred_time = min(ent_ts) if ent_ts else None
    attrs = {}
    for a in anomalies:
        if a["entity"] == top1 or (isinstance(a["entity"], str) and top1 in a["entity"].split("->")):
            attrs[a["attribute"]] = attrs.get(a["attribute"], 0) + 1
    pred_reason = osf.predict_reason(dataset, attrs, top1, {})
    return top1, pred_time, pred_reason


def main():
    rows = []
    for dataset in ["Bank", "Telecom", "Market-1", "Market-2"]:
        queries, records = od.load_queries(dataset), od.load_records(dataset)
        inventory = od.candidate_inventory(dataset)
        # per-query rule variant (shared across models)
        rule = {}
        for idx in range(len(records)):
            ws, we = od.parse_window(queries.iloc[idx]["instruction"])
            anomalies = rab.load_relaxed(dataset, ws, we)
            rule[idx] = rule_variant(dataset, idx, ws, we, inventory, anomalies)
        models = [m for (d, m) in LOGS if d == dataset] + ["rule"]
        llm_logs = {m: parse_log(os.path.join(HERE, "logs", LOGS[(dataset, m)]))
                    for (d, m) in LOGS if d == dataset}
        per = {m: {"time": [], "component": [], "reason": []} for m in models}
        cpt_check = {m: [0, 0] for m in models}  # correct, partial
        for m in models:
            if m != "rule":
                cpt_check[m + "+hybrid"] = [0, 0]
        DIFF = {"task_1": "easy", "task_2": "easy", "task_3": "easy",
                "task_4": "mid", "task_5": "mid", "task_6": "mid", "task_7": "hard"}
        diff_check = {m: {"easy": [0, 0, 0], "mid": [0, 0, 0], "hard": [0, 0, 0]}
                      for m in cpt_check}
        for idx in range(len(records)):
            gt = records.iloc[idx]
            need = NEED[queries.iloc[idx]["task_index"]]
            # rule variant scoring
            rt, rtime, rreason = rule[idx]
            rhits = {"component": int(rt == gt["component"]),
                     "reason": int(rreason is not None and rreason == gt["reason"]),
                     "time": int(rtime is not None and abs(rtime - float(gt["timestamp"])) <= 60)}
            s = sum(rhits[el] for el in need) / len(need)
            cpt_check["rule"][0] += int(s >= 0.999)
            cpt_check["rule"][1] += int(0 < s < 0.999)
            dlabel = DIFF[queries.iloc[idx]["task_index"]]
            dc = diff_check["rule"][dlabel]
            dc[0] += int(s >= 0.999); dc[1] += int(0 < s < 0.999); dc[2] += 1
            for el in need:
                per["rule"][el].append(rhits[el])
            # LLM variants
            for model in models:
                if model == "rule":
                    continue
                logs = llm_logs[model]
                if idx not in logs:
                    continue
                rec = logs[idx]
                comp_hit = int(rec["top1"] == gt["component"])
                gt_reason28 = str(gt["reason"]).strip()[:28]
                reason_hit = int(rec["reason"] == gt_reason28)
                total_hits = round(rec["s"] * len(need))
                scored = {el: h for el, h in
                          (("component", comp_hit), ("reason", reason_hit))
                          if el in need}
                time_hit = (total_hits - sum(scored.values())) if "time" in need else 0
                assert time_hit in (0, 1), f"{dataset}[{idx}] {model}: bad time_hit {time_hit}"
                if "time" not in need:
                    assert total_hits == sum(scored.values()), \
                        f"{dataset}[{idx}] {model}: hits mismatch"
                hits = {"component": comp_hit, "reason": reason_hit, "time": time_hit}
                cpt_check[model][0] += int(rec["s"] >= 0.999)
                cpt_check[model][1] += int(0 < rec["s"] < 0.999)
                dc = diff_check[model][dlabel]
                dc[0] += int(rec["s"] >= 0.999); dc[1] += int(0 < rec["s"] < 0.999); dc[2] += 1
                for el in need:
                    per[model][el].append(hits[el])
                # hybrid: component=scorer, time=rule first-anomaly, reason=LLM
                hyb = {"component": comp_hit, "reason": reason_hit, "time": rhits["time"]}
                hs = sum(hyb[el] for el in need) / len(need)
                cpt_check[model + "+hybrid"][0] += int(hs >= 0.999)
                cpt_check[model + "+hybrid"][1] += int(0 < hs < 0.999)
                dc = diff_check[model + "+hybrid"][dlabel]
                dc[0] += int(hs >= 0.999); dc[1] += int(0 < hs < 0.999); dc[2] += 1
        n = len(records)
        for model in models:
            for el in ("time", "component", "reason"):
                vals = per[model][el]
                if vals:
                    rows.append({"dataset": dataset, "model": model, "element": el,
                                 "n_requiring": len(vals),
                                 "accuracy": round(sum(vals) / len(vals), 4)})
        for model, (c, p) in cpt_check.items():
            rows.append({"dataset": dataset, "model": model, "element": "TOTAL(C/P/T)",
                         "n_requiring": n,
                         "accuracy": f"{c / n * 100:.2f}/{p / n * 100:.2f}/{(c + p) / n * 100:.2f}"})
        # per-difficulty split
        for model, drows in diff_check.items():
            for label in ("easy", "mid", "hard"):
                c, p, nn = drows[label]
                if nn:
                    rows.append({"dataset": dataset, "model": model,
                                 "element": f"{label}(C/P/T)", "n_requiring": nn,
                                 "accuracy": f"{c / nn * 100:.2f}/{p / nn * 100:.2f}/{(c + p) / nn * 100:.2f}"})
    import csv
    out = os.path.join(HERE, "results", "route_a_element_decomp.csv")
    with open(out, "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=["dataset", "model", "element", "n_requiring", "accuracy"])
        w.writeheader()
        w.writerows(rows)
    for r in rows:
        print(r)
    print("written:", out)


if __name__ == "__main__":
    main()
