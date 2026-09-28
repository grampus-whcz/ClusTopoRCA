#!/usr/bin/env python
"""Regenerate all 335 cluster-window reports with the four-dimension scorer.

Invokes the *_causal.py scripts (faiss-env) per query:
  Bank    -> OmniTransfer_new/1204_causal/
  Telecom -> OmniTransfer_new/1216_causal/
  Market  -> OmniTransfer_new/1215_causal/{c1,c2}/
Idempotent: skips queries whose report already exists.
"""
import os
import subprocess
import sys
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import openrca_data as od

OMNI = "/root/shared-nvme/work/timeSeries/OmniTransfer_new"
PY = "/root/shared-nvme/.conda/envs/faiss-env/bin/python"

SPECS = {
    "Bank": ("Bank_utils/Bank_cluster_window_analyze_anomalies_2.7_causal.py", "1204_causal", None, 4),
    "Telecom": ("Telecom_utils/14.Telecom_cluster_window_analyze_anomalies.3.3_causal.py", "1216_causal", None, 3),
    "Market-1": ("Market_utils/15.Market_cluster_window_analyze_anomalies_3.3_causal.py", "1215_causal", "c1", 3),
    "Market-2": ("Market_utils/15.Market_cluster_window_analyze_anomalies_3.3_causal.py", "1215_causal", "c2", 3),
}
PREFIX = {"Bank": "Bank", "Telecom": "Telecom", "Market-1": "Market", "Market-2": "Market"}


def report_path(dataset, out_dir, cloudbed, date_online, suffix):
    name = PREFIX[dataset]
    if cloudbed:
        return f"{OMNI}/{out_dir}/{cloudbed}/{name}_cluster_window_anomaly_report_{date_online}_{suffix}.txt"
    return f"{OMNI}/{out_dir}/{name}_cluster_window_anomaly_report_{date_online}_{suffix}.txt"


def jobs_for(dataset):
    script, out_dir, cloudbed, min_samples = SPECS[dataset]
    qs = od.load_queries(dataset)
    jobs = []
    for idx in range(len(qs)):
        ws, we = od.parse_window(qs.iloc[idx]["instruction"])
        d = datetime.fromtimestamp(ws, od.TZ8).strftime("%Y_%m_%d")
        suffix = datetime.fromtimestamp(ws, od.TZ8).strftime("%H%M") + "_" + \
                 datetime.fromtimestamp(we, od.TZ8).strftime("%H%M")
        rp = report_path(dataset, out_dir, cloudbed, d, suffix)
        cmd = [PY, os.path.join(OMNI, script), "--date_online", d,
               "--output_suffix", suffix, "--output_folder_name", out_dir,
               "--min_samples", str(min_samples)]
        if cloudbed:
            cmd += ["--cloudbed", cloudbed]
        jobs.append((idx, rp, cmd))
    return jobs


def run_one(job):
    idx, rp, cmd = job
    if os.path.exists(rp) and os.path.getsize(rp) > 0:
        return (idx, "skip", "")
    p = subprocess.run(cmd, cwd=OMNI, capture_output=True, text=True, timeout=900)
    if os.path.exists(rp) and os.path.getsize(rp) > 0:
        return (idx, "ok", "")
    return (idx, "fail", (p.stdout[-500:] + "\n" + p.stderr[-1000:]))


def main():
    datasets = sys.argv[1:] or list(SPECS)
    all_jobs = []
    for ds in datasets:
        all_jobs += jobs_for(ds)
    print(f"total jobs: {len(all_jobs)}", flush=True)
    ok = skip = 0
    fails = []
    with ThreadPoolExecutor(max_workers=8) as ex:
        for idx, status, err in ex.map(run_one, all_jobs):
            if status == "ok":
                ok += 1
            elif status == "skip":
                skip += 1
            else:
                fails.append((idx, err))
            if (ok + skip + len(fails)) % 20 == 0:
                print(f"progress: ok={ok} skip={skip} fail={len(fails)}", flush=True)
    print(f"DONE: ok={ok} skip={skip} fail={len(fails)}", flush=True)
    for idx, err in fails[:10]:
        print(f"--- FAIL idx={idx}\n{err}\n", flush=True)


if __name__ == "__main__":
    main()
