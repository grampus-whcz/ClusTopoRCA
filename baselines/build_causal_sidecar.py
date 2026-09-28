#!/usr/bin/env python
"""Build the causal-score sidecars injected into the *_causal.py cluster
report generators.

Source: results/score_cache/{dataset}.jsonl — the PC-based (CIRCA) RHT entity
scores computed under RCAEval_py3.12 (causal-learn), one entry per query.
Target: /root/shared-nvme/work/timeSeries/OmniTransfer_new/causal_sidecar/{dataset}.json
with keys f"{date_online}|{output_suffix}" (CST), matching the report
filenames: {Bank,Telecom}_cluster_window_anomaly_report_{date_online}_{suffix}.txt
and Market_cluster_window_anomaly_report_{date_online}_{suffix}.txt.

Also validates the key set against the original report directories
(1204/ and 1216/ root, 1215/c3/) and prints any mismatches.

Usage:
    /root/shared-nvme/.conda/envs/RCAEval_py3.12/bin/python build_causal_sidecar.py
"""

import json
import os
import sys
from datetime import datetime, timedelta, timezone

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import openrca_data as od

RESULTS = os.path.join(os.path.dirname(os.path.abspath(__file__)), "results")
OUT_DIR = "/root/shared-nvme/work/timeSeries/OmniTransfer_new/causal_sidecar"
OMNI = "/root/shared-nvme/work/timeSeries/OmniTransfer_new"

TZ8 = timezone(timedelta(hours=8))

DATASETS = ["Bank", "Telecom", "Market-1", "Market-2"]
# original report dirs for the cross-check (Market shares 1215/c3)
REPORT_DIR = {"Bank": f"{OMNI}/1204", "Telecom": f"{OMNI}/1216",
              "Market-1": f"{OMNI}/1215/c3", "Market-2": f"{OMNI}/1215/c3"}
REPORT_PREFIX = {"Bank": "Bank_cluster_window_anomaly_report_",
                 "Telecom": "Telecom_cluster_window_anomaly_report_",
                 "Market-1": "Market_cluster_window_anomaly_report_",
                 "Market-2": "Market_cluster_window_anomaly_report_"}


def key_of(ws, we):
    s = datetime.fromtimestamp(ws, tz=TZ8)
    e = datetime.fromtimestamp(we, tz=TZ8)
    return s.strftime("%Y_%m_%d"), f"{s.strftime('%H%M')}_{e.strftime('%H%M')}"


def main():
    os.makedirs(OUT_DIR, exist_ok=True)
    for ds in DATASETS:
        queries = od.load_queries(ds)
        cache = [json.loads(l) for l in open(os.path.join(RESULTS, "score_cache", f"{ds}.jsonl"))]
        by_idx = {r["idx"]: r for r in cache}

        table = {}
        n_missing_scores = 0
        for i in range(len(queries)):
            r = by_idx.get(i)
            if r is None or r.get("status") != "ok":
                print(f"  ⚠️  {ds} idx={i}: no ok cache row")
                continue
            ws, we = r["window"]
            d, s = key_of(ws, we)
            scores = r.get("rht_scores") or {}
            if not scores:
                n_missing_scores += 1
            table[f"{d}|{s}"] = scores
        out_path = os.path.join(OUT_DIR, f"{ds}.json")
        with open(out_path, "w", encoding="utf-8") as f:
            json.dump(table, f)

        # ---- cross-check: query keys vs original report filenames ----
        # (filename stem is f"{date_online}_{suffix}")
        query_keys = {k.replace("|", "_") for k in table}
        prefix = REPORT_PREFIX[ds]
        files = {fn[len(prefix):-4] for fn in os.listdir(REPORT_DIR[ds])
                 if fn.startswith(prefix) and fn.endswith(".txt")
                 and "short_report" not in fn and "multi_grain" not in fn
                 and "causal_scores" not in fn}
        missing_report = sorted(k for k in query_keys if k not in files)
        extra_report = sorted(k for k in files if k not in query_keys)
        print(f"{ds}: {len(queries)} queries -> {len(table)} distinct window keys; "
              f"empty-score keys: {n_missing_scores}")
        print(f"   report dir {REPORT_DIR[ds]}: {len(files)} report files; "
              f"keys without report: {len(missing_report)}, reports without query: {len(extra_report)}")
        for k in missing_report[:10]:
            print(f"     no-report: {k}")
        for k in extra_report[:10]:
            print(f"     no-query : {k}")
        print(f"   wrote {out_path}")


if __name__ == "__main__":
    main()
