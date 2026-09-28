#!/usr/bin/env python
"""B-4: validate the "more upstream = more suspicious" in-degree assumption.

Two analyses per dataset:
  1. GT in-degree distribution: per query, the ground-truth component's
     in-degree percentile among the scorer's candidate pool (low in-degree =
     upstream). If the assumption holds, GT components should sit on the
     upstream side (low in-degree percentile).
  2. Reversed in-degree ablation: rerun the w/o-LLM scorer with the in-degree
     direction flipped (IN_DEGREE_FLIP) and compare hit@1/3/5.

Outputs: results/indegree_assumption.csv  (dataset-level stats + ablation)
"""
import os
import sys

import numpy as np

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import offline_scorer as osf
import openrca_data as od

DATASETS = ["Bank", "Telecom", "Market-1", "Market-2"]


def run_dataset(dataset):
    queries, records = od.load_queries(dataset), od.load_records(dataset)
    inventory = od.candidate_inventory(dataset)
    pct_list, missing = [], 0
    hit = {False: [0, 0, 0], True: [0, 0, 0]}  # flip -> [h1, h3, h5]
    n = len(records)
    for idx in range(n):
        ws, we = od.parse_window(queries.iloc[idx]["instruction"])
        gt = records.iloc[idx]["component"]
        per_flip = {}
        for flip in (False, True):
            osf.IN_DEGREE_FLIP = flip
            try:
                res = osf.rank_candidates(dataset, ws, we, inventory)
                ranked = res["ranked_entities"]
            except Exception:
                ranked = []
            per_flip[flip] = ranked
        osf.IN_DEGREE_FLIP = False
        # GT in-degree percentile among cluster candidates (use the scorer's
        # own per-cluster DataFrame, which retains in_degree)
        try:
            anomalies = osf.LOADERS[dataset](ws, we)
            clusters, _noise = osf.dbscan_clusters(anomalies)
            scorer = osf.get_scorer(dataset)
            for cl in clusters:
                df = scorer.score_cluster(cl)
                if df is None or df.empty or "in_degree" not in df.columns:
                    continue
                if gt in set(df["entity"]):
                    gt_in = float(df.loc[df["entity"] == gt, "in_degree"].iloc[0])
                    indeg = df["in_degree"].astype(float).tolist()
                    if len(indeg) > 1:
                        pct = sum(1 for v in indeg if v <= gt_in) / len(indeg)
                        pct_list.append(pct)
                        break  # count once per query (first cluster containing GT)
            else:
                missing += 1
        except Exception:
            missing += 1
        for flip in (False, True):
            ranked = per_flip[flip]
            r = ranked.index(gt) + 1 if gt in ranked else None
            hit[flip][0] += int(r == 1)
            hit[flip][1] += int(r is not None and r <= 3)
            hit[flip][2] += int(r is not None and r <= 5)
    osf.IN_DEGREE_FLIP = False
    return {
        "dataset": dataset, "n": n, "gt_in_pool": len(pct_list),
        "gt_indeg_pct_mean": round(float(np.mean(pct_list)), 3) if pct_list else None,
        "gt_indeg_pct_median": round(float(np.median(pct_list)), 3) if pct_list else None,
        "frac_gt_below_median": round(float(np.mean([p <= 0.5 for p in pct_list])), 3) if pct_list else None,
        "hit@1_normal": round(hit[False][0] / n, 4),
        "hit@1_flipped": round(hit[True][0] / n, 4),
        "hit@3_normal": round(hit[False][1] / n, 4),
        "hit@3_flipped": round(hit[True][1] / n, 4),
        "hit@5_normal": round(hit[False][2] / n, 4),
        "hit@5_flipped": round(hit[True][2] / n, 4),
    }


def main():
    import csv
    rows = [run_dataset(ds) for ds in DATASETS]
    osf.IN_DEGREE_FLIP = False
    out = os.path.join(os.path.dirname(os.path.abspath(__file__)), "results",
                       "indegree_assumption.csv")
    with open(out, "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0].keys()))
        w.writeheader()
        w.writerows(rows)
    for r in rows:
        print(r)
    print("written:", out)


if __name__ == "__main__":
    main()
