"""
Sweep the RHT fusion weight W_rht from the per-query score cache
(results/score_cache/{dataset}.jsonl, built by build_score_cache.py).

No RHT/PC recomputation happens here: for each query the cached scorer
components (time/topology/count, component weight) and RHT entity scores are
replayed through the same fusion rule as run_offline_variants.py:

    fused = (W_t·time + W_topo·topo + W_c·count + W_rht·rht_norm)
            / (W_t + W_topo + W_c + W_rht) · component_weight

with rht_norm min-max over the query's fused entity set and the dataset's
native (W_t, W_topo, W_c).  W_rht = 0.0 disables the RHT dimension (RHT-only
entities fall to the deterministic tail); W_rht = 1.0 is RHT-dominated.

Grid: {0.0, 0.1, 0.2, 0.3, 0.4, 0.5, 0.7, 1.0}.
Metrics per (dataset, w_rht): component hit@1/3/5 + MRR on all queries
(exact match vs record.csv, official candidate inventory) — same protocol as
the wo_llm/rht_fused runs.

Outputs:
  results/w_rht_sweep.csv  (long table: dataset, w_rht, hit@1, hit@3, hit@5, MRR)
  printed pivot tables (hit@1 and MRR) + plateau analysis.

Usage:
    python sweep_w_rht.py
"""

import json
import os
import sys

import numpy as np
import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from run_offline_variants import fuse_scores  # identical fusion semantics

RESULTS_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "results")
CACHE_DIR = os.path.join(RESULTS_DIR, "score_cache")

DATASETS = ["Bank", "Telecom", "Market-1", "Market-2"]
W_GRID = [0.0, 0.1, 0.2, 0.3, 0.4, 0.5, 0.7, 1.0]


def load_cache(dataset):
    rows = []
    with open(os.path.join(CACHE_DIR, f"{dataset}.jsonl")) as f:
        for line in f:
            r = json.loads(line)
            if r.get("status") == "ok":
                rows.append(r)
    return rows


def metrics_for(dataset, rows, w_rht, inventory):
    hits = {1: 0, 3: 0, 5: 0}
    rr = []
    for r in rows:
        if w_rht == 0:
            # W_rht=0 means "no causal evidence": the ranking is exactly the
            # wo_llm base-scorer ranking (cand_rows insertion order = the
            # dominant-cluster-first merged ranking), no RHT-only entities.
            ranked = list(r["cand_rows"])
        else:
            fused = fuse_scores(dataset, r["cand_rows"], r["rht_scores"], w_rht,
                                inventory=inventory)
            ranked = [e for e, _ in fused]
        gt = r["gt_component"]
        try:
            rank = ranked.index(gt) + 1
        except ValueError:
            rank = None
        rr.append(1.0 / rank if rank else 0.0)
        for k in hits:
            hits[k] += int(rank is not None and rank <= k)
    n = len(rows)
    return {"n": n,
            "hit@1": round(hits[1] / n, 4),
            "hit@3": round(hits[3] / n, 4),
            "hit@5": round(hits[5] / n, 4),
            "MRR": round(float(np.mean(rr)), 4)}


def main():
    import openrca_data as od
    caches = {ds: load_cache(ds) for ds in DATASETS}
    inventories = {ds: od.candidate_inventory(ds) for ds in DATASETS}
    for ds, rows in caches.items():
        print(f"{ds}: {len(rows)} cached queries "
                  f"(rht_error: {sum(1 for r in rows if r.get('rht_error'))})")

    records = []
    for ds in DATASETS:
        for w in W_GRID:
            m = metrics_for(ds, caches[ds], w, inventories[ds])
            records.append({"dataset": ds, "w_rht": w, **m})
    df = pd.DataFrame(records)
    out = os.path.join(RESULTS_DIR, "w_rht_sweep.csv")
    df.to_csv(out, index=False)

    pd.set_option("display.width", 160)
    for metric in ["hit@1", "MRR", "hit@3", "hit@5"]:
        piv = df.pivot_table(index="dataset", columns="w_rht", values=metric)
        piv["macro_row_mean"] = piv.mean(axis=1)
        print(f"\n=== {metric} (rows=dataset, cols=w_rht) ===")
        print(piv.to_string(float_format=lambda x: f"{x:.4f}"))
    macro = df.groupby("w_rht")[["hit@1", "MRR"]].mean().round(4)
    print("\n=== macro average over 4 datasets ===")
    print(macro.to_string())

    # plateau analysis: per dataset, widest W range within 95% of best hit@1
    print("\n=== plateau analysis (hit@1 within 95% of dataset best) ===")
    for ds in DATASETS:
        sub = df[df.dataset == ds].set_index("w_rht")["hit@1"]
        best = sub.max()
        if best <= 0:
            print(f"{ds}: best=0 everywhere except {sub[sub > 0].to_dict()} — no plateau")
            continue
        plateau = [w for w in W_GRID if sub[w] >= 0.95 * best]
        best_w = sub.idxmax()
        print(f"{ds}: best={best:.4f} at W={best_w}; plateau W∈{plateau}")
    print(f"\nwrote {out}")


if __name__ == "__main__":
    main()
