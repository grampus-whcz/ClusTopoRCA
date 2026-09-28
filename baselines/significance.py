"""
Statistical significance for the component-localization comparison.

Per-query hit@1 vectors -> bootstrap 95% CIs per method per dataset, and
McNemar exact tests for the key method pairs. ClusTopoRCA full-pipeline rows
are read from the mined predictions CSV (per LLM backbone).

Outputs:
  results/significance_ci.csv      (dataset, method, n, top1, ci_lo, ci_hi)
  results/significance_mcnemar.csv (dataset, method_a, method_b, b, c, p)
"""

import glob
import json
import os

import numpy as np
import pandas as pd
from scipy.stats import binomtest

HERE = os.path.dirname(os.path.abspath(__file__))
RESULTS = os.path.join(HERE, "results")
DATASETS = ["Bank", "Telecom", "Market-1", "Market-2"]

METHOD_FILES = {
    "MicroCause_gt": "microcause_{ds}.jsonl",
    "CIRCA_gt": "circa_{ds}.jsonl",
    "CIRCA_det": "circa_detect_{ds}.jsonl",
    "mABC": "mabc_{ds}.jsonl",
    "FoA": "foa_{ds}.jsonl",
    "ClusTopoRCA wo LLM": "wo_llm_{ds}.jsonl",
    "ClusTopoRCA+causal(0.3)": "rht_fused_{ds}.jsonl",
}

MCNEMAR_PAIRS = [
    ("ClusTopoRCA+causal(0.3)", "ClusTopoRCA wo LLM"),   # fusion gain
    ("ClusTopoRCA+causal(0.3)", "CIRCA_gt"),             # vs strongest baseline
    ("ClusTopoRCA+causal(0.3)", "CIRCA_det"),            # vs fair-alert baseline
    ("CIRCA_gt", "CIRCA_det"),                           # alert-time effect
    ("FoA", "CIRCA_det"),                                # LLM-agent vs classical
]


def load_hits(pattern, ds):
    hits = {}
    for f in glob.glob(os.path.join(RESULTS, pattern.format(ds=ds))):
        for line in open(f):
            r = json.loads(line)
            if r.get("status") == "ok":
                hits[r["idx"]] = int(r.get("hit@1", 0))
    return hits


def load_clustoporca_hits(ds):
    """Full-pipeline strict hit@1 per backbone from the mined predictions."""
    df = pd.read_csv(os.path.join(RESULTS, "clustoporca_component_predictions.csv"))
    df = df[(df["dataset"] == ds) & (df["method"] == "clustoporca")]
    out = {}
    for model, g in df.groupby("model"):
        out[f"ClusTopoRCA full ({model})"] = {
            int(r["query_idx"]): int(r["predicted_component"] == r["gt_component"])
            for _, r in g.iterrows()
        }
    return out


def bootstrap_ci(hits, n_boot=10000, seed=0):
    rng = np.random.default_rng(seed)
    x = np.array(sorted(hits.items()), dtype=object)
    vals = np.array([v for _, v in x], dtype=float)
    n = len(vals)
    boots = rng.choice(vals, size=(n_boot, n), replace=True).mean(axis=1)
    return float(np.percentile(boots, 2.5)), float(np.percentile(boots, 97.5))


def mcnemar(ha, hb):
    common = sorted(set(ha) & set(hb))
    b = sum(1 for i in common if ha[i] == 1 and hb[i] == 0)
    c = sum(1 for i in common if ha[i] == 0 and hb[i] == 1)
    p = float(binomtest(min(b, c), b + c, 0.5).pvalue) if (b + c) > 0 else 1.0
    return b, c, p


def main():
    ci_rows, mc_rows = [], []
    for ds in DATASETS:
        hits_by_method = {}
        for m, pat in METHOD_FILES.items():
            hits_by_method[m] = load_hits(pat, ds)
        hits_by_method.update(load_clustoporca_hits(ds))

        for m, hits in hits_by_method.items():
            if not hits:
                continue
            lo, hi = bootstrap_ci(hits)
            ci_rows.append({"dataset": ds, "method": m, "n": len(hits),
                            "top1": round(float(np.mean(list(hits.values()))), 4),
                            "ci_lo": round(lo, 4), "ci_hi": round(hi, 4)})

        for a, b_ in MCNEMAR_PAIRS:
            if hits_by_method.get(a) and hits_by_method.get(b_):
                bb, cc, p = mcnemar(hits_by_method[a], hits_by_method[b_])
                mc_rows.append({"dataset": ds, "method_a": a, "method_b": b_,
                                "wins_a_only": bb, "wins_b_only": cc, "p_value": p})

    ci_df = pd.DataFrame(ci_rows)
    mc_df = pd.DataFrame(mc_rows)
    ci_df.to_csv(os.path.join(RESULTS, "significance_ci.csv"), index=False)
    mc_df.to_csv(os.path.join(RESULTS, "significance_mcnemar.csv"), index=False)
    print("=== Bootstrap 95% CI (component hit@1) ===")
    print(ci_df.to_string(index=False))
    print("\n=== McNemar exact tests ===")
    print(mc_df.to_string(index=False))


if __name__ == "__main__":
    main()
