#!/usr/bin/env python
"""Offline quantification of routes a/b for lifting top-1.

Route a: pipeline #1 hard-constrained to the scorer's causal-fused top-1;
         time = that entity's first anomaly minute; reason = rule-mapped from
         its dominant anomaly attributes. End-to-end Total estimated offline.
Route b: relax the Market anomaly prefilter (which currently keeps only the
         single most frequent (entity, attribute) group per modality) to
         top-3 groups per modality, and measure scorer hit@k change.

No LLM anywhere. Outputs: results/route_ab_offline.csv
"""
import os
import sys
from collections import Counter

import numpy as np
import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import offline_scorer as osf
import openrca_data as od
import verify_smoke as vs

NEED = vs.NEED
DATASETS = ["Bank", "Telecom", "Market-1", "Market-2"]
DAY_CACHE = {}


def load_market_anomalies_relaxed(ws, we, top_n=3, min_freq=2):
    """Relaxed Market loader: keep top-N (entity, attribute) groups per
    modality with frequency >= min_freq (stock loader keeps top-1, freq>=4)."""
    date_str = osf.window_names(ws, we)[0]
    day = osf._market_day_anomalies(date_str)
    anomalies = [a for a in day if ws <= a["ts"] < we]
    final = []
    for typ in sorted(set(a["type"] for a in anomalies)):
        type_an = [a for a in anomalies if a["type"] == typ]
        counter = Counter((a["entity"], a["attribute"]) for a in type_an)
        group_map = {}
        for a in type_an:
            group_map.setdefault((a["entity"], a["attribute"]), []).append(a)
        frequent = sorted(((k, c) for k, c in counter.items() if c >= min_freq),
                          key=lambda x: x[1], reverse=True)
        for (entity, attr), freq in frequent[:top_n]:
            final.extend(group_map[(entity, attr)])
    return osf._dedup_sort(final)


def load_relaxed(dataset, ws, we):
    if dataset in ("Market-1", "Market-2"):
        return load_market_anomalies_relaxed(ws, we)
    return osf.LOADERS[dataset](ws, we)


def fused_rank(dataset, idx, ws, we, inventory, anomalies):
    """Causal-fused ranking over relaxed-input candidates -> [(entity, fused)]."""
    res = osf.score_anomalies(dataset, anomalies)
    rht = vs.load_rht_scores(dataset, idx)
    ents_raw = res["ranked_raw"]
    ents = []
    seen = set()
    for raw in ents_raw:
        c = osf.map_to_inventory(raw, inventory)
        if c and c not in seen:
            seen.add(c)
            ents.append(c)
    if not ents:
        return []
    vals = [float(rht.get(e, 0.0)) for e in ents]
    v_min, v_max = min(vals), max(vals)
    w = {"Bank": (0.3, 0.4, 0.3), "Telecom": (0.025, 0.025, 0.95),
         "Market-1": (0.1, 0.8, 0.1), "Market-2": (0.1, 0.8, 0.1)}[dataset]
    fused = []
    for e in ents:
        row = res["entity_rows"][[r for r in ents_raw
                                  if osf.map_to_inventory(r, inventory) == e][0]]
        base = (w[0] * row["time_score"] + w[1] * row["topology_score"]
                + w[2] * row["count_score"])
        norm = ((float(rht.get(e, 0.0)) - v_min) / (v_max - v_min)) if v_max > v_min else 0.0
        fused.append((e, (base + vs.W_CAUSAL * norm) / (1 + vs.W_CAUSAL) * row.get("component_weight", 1.0)))
    fused.sort(key=lambda x: -x[1])
    return fused


def run_dataset(dataset):
    queries, records = od.load_queries(dataset), od.load_records(dataset)
    inventory = od.candidate_inventory(dataset)
    n = len(records)
    comp_hit1 = comp_hit3 = 0
    c = p = 0
    for idx in range(n):
        ws, we = od.parse_window(queries.iloc[idx]["instruction"])
        gt = records.iloc[idx]
        anomalies = load_relaxed(dataset, ws, we)
        fused = fused_rank(dataset, idx, ws, we, inventory, anomalies)
        if not fused:
            continue
        top1 = fused[0][0]
        comp_hit1 += int(top1 == gt["component"])
        comp_hit3 += int(gt["component"] in [e for e, _ in fused[:3]])
        # route-a answer: time = top1's first anomaly, reason = rule map
        ent_ts = [a["ts"] for a in anomalies if a["entity"] == top1 or
                  (isinstance(a["entity"], str) and top1 in a["entity"].split("->"))]
        pred_time = min(ent_ts) if ent_ts else None
        attrs = {}
        for a in anomalies:
            if a["entity"] == top1 or (isinstance(a["entity"], str) and top1 in a["entity"].split("->")):
                attrs[a["attribute"]] = attrs.get(a["attribute"], 0) + 1
        pred_reason = osf.predict_reason(dataset, attrs, top1, {})
        need = NEED[queries.iloc[idx]["task_index"]]
        hits = 0
        for el in need:
            if el == "component":
                hits += int(top1 == gt["component"])
            elif el == "reason":
                hits += int(pred_reason == gt["reason"])
            elif el == "time":
                if pred_time:
                    hits += int(abs(pred_time - float(gt["timestamp"])) <= 60)
        s = hits / len(need)
        c += int(s >= 0.999)
        p += int(0 < s < 0.999)
    return {"dataset": dataset, "n": n,
            "scorer_hit@1": round(comp_hit1 / n, 4),
            "scorer_hit@3": round(comp_hit3 / n, 4),
            "routeA_correct": round(c / n * 100, 2),
            "routeA_partial": round(p / n * 100, 2),
            "routeA_total": round((c + p) / n * 100, 2)}


def market_prefilter_comparison():
    """Strict vs relaxed prefilter, base scorer hit@k on Market."""
    rows = []
    for dataset in ("Market-1", "Market-2"):
        queries, records = od.load_queries(dataset), od.load_records(dataset)
        inventory = od.candidate_inventory(dataset)
        n = len(records)
        out = {}
        for mode in ("strict", "relaxed"):
            h1 = h3 = h5 = 0
            for idx in range(n):
                ws, we = od.parse_window(queries.iloc[idx]["instruction"])
                gt = records.iloc[idx]["component"]
                an = (osf.LOADERS[dataset](ws, we) if mode == "strict"
                      else load_relaxed(dataset, ws, we))
                fused = fused_rank(dataset, idx, ws, we, inventory, an)
                ents = [e for e, _ in fused]
                r = ents.index(gt) + 1 if gt in ents else None
                h1 += int(r == 1); h3 += int(r is not None and r <= 3); h5 += int(r is not None and r <= 5)
            out[mode] = (h1 / n, h3 / n, h5 / n)
        rows.append({"dataset": dataset,
                     "strict_h1": round(out["strict"][0], 4), "relaxed_h1": round(out["relaxed"][0], 4),
                     "strict_h3": round(out["strict"][1], 4), "relaxed_h3": round(out["relaxed"][1], 4),
                     "strict_h5": round(out["strict"][2], 4), "relaxed_h5": round(out["relaxed"][2], 4)})
    return rows


def main():
    import csv
    print("=== Route b: Market 预过滤 strict vs relaxed ===")
    rb = market_prefilter_comparison()
    for r in rb:
        print(r)
    print("\n=== Route a: component=打分器top-1 的端到端估计 ===")
    ra = [run_dataset(ds) for ds in DATASETS]
    for r in ra:
        print(r)
    out = os.path.join(os.path.dirname(os.path.abspath(__file__)), "results",
                       "route_ab_offline.csv")
    with open(out, "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(ra[0].keys()))
        w.writeheader(); w.writerows(ra)
    with open(os.path.join(os.path.dirname(out), "route_b_market_prefilter.csv"), "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(rb[0].keys()))
        w.writeheader(); w.writerows(rb)
    print("written:", out)


if __name__ == "__main__":
    main()
