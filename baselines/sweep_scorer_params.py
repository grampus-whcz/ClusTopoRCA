"""
Parameter sensitivity sweeps for the offline ClusTopoRCA stage-3 scorer
(the wo_llm variant; no RHT involved), plus the anomaly-gap statistics for
the "fault-induced anomalies cluster within a bounded time window" assumption
(R1 question).

Single-variable protocol — everything except the swept parameter stays at the
values verified against the paper's runtime scripts (offline_scorer.py):
  * DBSCAN min_samples = 3; analysis-start timestamp index = 3rd distinct
    anomaly ts (Bank/Telecom) / 1st (Market); candidate thresholds and weights
    unchanged; ranking = dominant-cluster-first merge + candidate-inventory
    alignment (identical to the delivered wo_llm variant).
  * eps sweep:   eps_seconds in {15, 30, 60, 120, 300}   (default 60)
  * num sweep:   concentration window in {1, 3, 5, 10} min
                 (dataset defaults: Bank 4, Telecom 5, Market 5 — note Bank's
                 default 4 is not a grid point, by design of the review grid)

Gap statistics (per dataset, pooled over all queries):
  consecutive-anomaly timestamp gaps of the exact anomaly records that enter
  DBSCAN (i.e. after each dataset's loading filters), plus the fraction of
  gaps covered by eps=60s, plus the mean per-query noise ratio (DBSCAN label
  -1 anomalies dropped before scoring, at eps=60s).

Outputs (baselines/results/):
  eps_sweep.csv          (dataset, eps, n, hit@1, hit@3, hit@5, MRR)
  num_sweep.csv          (dataset, num, n, hit@1, hit@3, hit@5, MRR)
  anomaly_gap_stats.csv  (dataset, n_queries, n_anomalies, n_gaps,
                          frac_gap_le_60s, P50..P99, max, noise_ratio_mean)

Usage:
    python sweep_scorer_params.py [--datasets Bank Telecom Market-1 Market-2]
"""

import argparse
import os
import sys
import time

import numpy as np

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import openrca_data as od
import offline_scorer as osf

RESULTS_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "results")

EPS_GRID = [15, 30, 60, 120, 300]
NUM_GRID = [1, 3, 5, 10]
DEFAULT_EPS = osf.DBSCAN_EPS_SECONDS          # 60
DEFAULT_MIN_SAMPLES = osf.DBSCAN_MIN_SAMPLES  # 3


def eval_ranked(ranked, gt):
    try:
        rank = ranked.index(gt) + 1
    except ValueError:
        rank = None
    return rank


def aggregate(rows):
    """rows: list of gt_rank (or None) -> metric dict."""
    n = len(rows)
    hits = {k: sum(1 for r in rows if r is not None and r <= k) for k in (1, 3, 5)}
    mrr = float(np.mean([1.0 / r if r else 0.0 for r in rows])) if n else 0.0
    return {"n": n, "hit@1": round(hits[1] / n, 4), "hit@3": round(hits[3] / n, 4),
            "hit@5": round(hits[5] / n, 4), "MRR": round(mrr, 4)}


def run_dataset(dataset):
    records = od.load_records(dataset)
    queries = od.load_queries(dataset)
    inventory = od.candidate_inventory(dataset)

    eps_ranks = {e: [] for e in EPS_GRID}
    num_ranks = {m: [] for m in NUM_GRID}
    all_gaps = []
    noise_ratios = []
    n_anom_total = 0
    n_used = 0

    for idx in range(len(records)):
        rrow, qrow = records.iloc[idx], queries.iloc[idx]
        ws, we = od.parse_window(qrow["instruction"])
        gt = rrow["component"]
        anomalies = osf.LOADERS[dataset](ws, we)
        n_anom_total += len(anomalies)

        if anomalies:
            n_used += 1
            ts_sorted = sorted(a["ts"] for a in anomalies)
            all_gaps.extend(np.diff(ts_sorted).tolist())
            # noise ratio at the default eps
            _cl, noise = osf.dbscan_clusters(
                anomalies, eps=DEFAULT_EPS, min_samples=DEFAULT_MIN_SAMPLES)
            noise_ratios.append(len(noise) / len(anomalies))

        # eps sweep (num fixed at dataset default)
        for eps in EPS_GRID:
            res = osf.rank_candidates(dataset, ws, we, inventory,
                                      anomalies=anomalies, eps=eps)
            eps_ranks[eps].append(eval_ranked(res["ranked_entities"], gt))
        # num sweep (eps fixed at 60)
        for m in NUM_GRID:
            res = osf.rank_candidates(dataset, ws, we, inventory,
                                      anomalies=anomalies, conc_minutes=m)
            num_ranks[m].append(eval_ranked(res["ranked_entities"], gt))
        if (idx + 1) % 20 == 0:
            print(f"  [{dataset}] {idx + 1}/{len(records)}", flush=True)

    eps_rows = [{"dataset": dataset, "eps": e, **aggregate(eps_ranks[e])}
                for e in EPS_GRID]
    num_rows = [{"dataset": dataset, "num": m, **aggregate(num_ranks[m])}
                for m in NUM_GRID]

    gaps = np.array(all_gaps, dtype=float) if all_gaps else np.array([np.nan])
    gap_row = {
        "dataset": dataset,
        "n_queries": len(records),
        "n_queries_with_anomalies": n_used,
        "n_anomalies": n_anom_total,
        "n_gaps": int(len(all_gaps)),
        "frac_gap_le_60s": round(float(np.mean(gaps <= 60)), 4),
        "frac_gap_le_300s": round(float(np.mean(gaps <= 300)), 4),
        "P50": round(float(np.percentile(gaps, 50)), 1),
        "P75": round(float(np.percentile(gaps, 75)), 1),
        "P90": round(float(np.percentile(gaps, 90)), 1),
        "P95": round(float(np.percentile(gaps, 95)), 1),
        "P99": round(float(np.percentile(gaps, 99)), 1),
        "max": float(np.max(gaps)),
        "noise_ratio_mean": round(float(np.mean(noise_ratios)), 4) if noise_ratios else None,
    }
    return eps_rows, num_rows, gap_row


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--datasets", nargs="+",
                    default=["Bank", "Telecom", "Market-1", "Market-2"])
    args = ap.parse_args()

    import pandas as pd
    eps_all, num_all, gap_all = [], [], []
    for ds in args.datasets:
        t0 = time.time()
        eps_rows, num_rows, gap_row = run_dataset(ds)
        eps_all.extend(eps_rows)
        num_all.extend(num_rows)
        gap_all.append(gap_row)
        print(f"[{ds}] done in {time.time() - t0:.0f}s", flush=True)
        # incremental save
        pd.DataFrame(eps_all).to_csv(os.path.join(RESULTS_DIR, "eps_sweep.csv"), index=False)
        pd.DataFrame(num_all).to_csv(os.path.join(RESULTS_DIR, "num_sweep.csv"), index=False)
        pd.DataFrame(gap_all).to_csv(os.path.join(RESULTS_DIR, "anomaly_gap_stats.csv"), index=False)

    print("\n=== eps sweep (hit@1) ===")
    print(pd.DataFrame(eps_all).pivot_table(index="dataset", columns="eps", values="hit@1").to_string())
    print("\n=== eps sweep (MRR) ===")
    print(pd.DataFrame(eps_all).pivot_table(index="dataset", columns="eps", values="MRR").to_string())
    print("\n=== num sweep (hit@1) ===")
    print(pd.DataFrame(num_all).pivot_table(index="dataset", columns="num", values="hit@1").to_string())
    print("\n=== num sweep (MRR) ===")
    print(pd.DataFrame(num_all).pivot_table(index="dataset", columns="num", values="MRR").to_string())
    print("\n=== anomaly gap stats ===")
    print(pd.DataFrame(gap_all).to_string(index=False))
    print(f"\nwrote {os.path.join(RESULTS_DIR, 'eps_sweep.csv')}, num_sweep.csv, anomaly_gap_stats.csv")


if __name__ == "__main__":
    main()
