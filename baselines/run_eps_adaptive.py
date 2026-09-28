#!/usr/bin/env python
"""Adaptive DBSCAN eps (k-distance elbow) vs fixed 60s, offline validation.

For each query window, the eps is chosen at the knee of the k-distance curve
(k = DBSCAN min_samples) of the window's anomaly timestamps, clamped to
[15s, 300s]; fall back to 60s when the curve is degenerate (too few points
or a flat curve). The scorer then runs with the adaptive eps and we compare
component hit@1/3/5 against the fixed 60s configuration.

Outputs: results/eps_adaptive.csv
"""
import os
import sys

import numpy as np

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import offline_scorer as osf
import openrca_data as od

K = 3  # = DBSCAN min_samples used in the pipeline
EPS_MIN, EPS_MAX = 15, 300
DATASETS = ["Bank", "Telecom", "Market-1", "Market-2"]


def knee_eps(timestamps):
    """Kneedle over the k-distance curve; returns (eps, is_fallback)."""
    ts = np.sort(np.unique(np.asarray(timestamps, dtype=float)))
    n = len(ts)
    if n < K + 2:
        return 60.0, True
    # distance to the K-th nearest neighbor for each point
    d = np.abs(ts[:, None] - ts[None, :])
    d.sort(axis=1)
    kdist = d[:, min(K, n - 1)]
    kdist = np.sort(kdist)
    if kdist[-1] <= kdist[0]:
        return 60.0, True
    # normalize curve to [0,1]x[0,1] and find max distance to the diagonal
    x = np.linspace(0, 1, n)
    y = (kdist - kdist[0]) / (kdist[-1] - kdist[0])
    knee_idx = int(np.argmax(y - x))
    eps = float(kdist[knee_idx])
    if eps <= 0:
        return 60.0, True
    return min(max(eps, EPS_MIN), EPS_MAX), False


def run_dataset(dataset):
    queries, records = od.load_queries(dataset), od.load_records(dataset)
    inventory = od.candidate_inventory(dataset)
    n = len(records)
    hits = {"fixed": [0, 0, 0], "adaptive": [0, 0, 0]}
    eps_list = []
    for idx in range(n):
        ws, we = od.parse_window(queries.iloc[idx]["instruction"])
        gt = records.iloc[idx]["component"]
        anomalies = osf.LOADERS[dataset](ws, we)
        eps, fb = knee_eps([a["ts"] for a in anomalies])
        eps_list.append(eps)
        for mode in ("fixed", "adaptive"):
            e = 60.0 if mode == "fixed" else eps
            try:
                res = osf.score_anomalies(dataset, anomalies, eps=e)
                seen, ranked = set(), []
                for raw in res["ranked_raw"]:
                    c = osf.map_to_inventory(raw, inventory)
                    if c and c not in seen:
                        seen.add(c)
                        ranked.append(c)
            except Exception:
                ranked = []
            r = ranked.index(gt) + 1 if gt in ranked else None
            hits[mode][0] += int(r == 1)
            hits[mode][1] += int(r is not None and r <= 3)
            hits[mode][2] += int(r is not None and r <= 5)
    return {
        "dataset": dataset, "n": n,
        "eps_median": float(np.median(eps_list)),
        "eps_p25": float(np.percentile(eps_list, 25)),
        "eps_p75": float(np.percentile(eps_list, 75)),
        "hit@1_fixed60": round(hits["fixed"][0] / n, 4),
        "hit@1_adaptive": round(hits["adaptive"][0] / n, 4),
        "hit@3_fixed60": round(hits["fixed"][1] / n, 4),
        "hit@3_adaptive": round(hits["adaptive"][1] / n, 4),
        "hit@5_fixed60": round(hits["fixed"][2] / n, 4),
        "hit@5_adaptive": round(hits["adaptive"][2] / n, 4),
    }


def main():
    import csv
    rows = [run_dataset(ds) for ds in DATASETS]
    out = os.path.join(os.path.dirname(os.path.abspath(__file__)), "results",
                       "eps_adaptive.csv")
    with open(out, "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0].keys()))
        w.writeheader()
        w.writerows(rows)
    for r in rows:
        print(r)
    print("written:", out)


if __name__ == "__main__":
    main()
