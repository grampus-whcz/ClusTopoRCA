#!/usr/bin/env python
"""Recovery + completion for the causal-scorer main-table rerun (GLM-4.7).

Phase 1: salvage completed queries from the existing shard logs
         (logs/causal_rerun/run_*.log) — per-query Prediction + best candidate score.
Phase 2: re-run missing (dataset, idx) with per-shard unique tags (no CSV clobbering).
Phase 3: aggregate salvaged + new results -> final table vs the old glm-4.7 main table.

Idempotent: salvaged/already-present eval rows are not re-run.
"""
import glob
import json
import os
import re
import subprocess
import sys
from concurrent.futures import ThreadPoolExecutor

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import openrca_data as od

REPO = "/root/shared-nvme/work/agent/OpenRCA"
LOGD = os.path.join(REPO, "baselines/logs/causal_rerun")
PY = "/root/shared-nvme/.conda/envs/faiss-env/bin/python"
DATASETS = {"Bank": 136, "Telecom": 51, "Market/cloudbed-1": 70, "Market/cloudbed-2": 78}
OLD_GLM47 = {"Bank": (20.59, 27.94, 48.53), "Telecom": (29.42, 37.25, 66.67),
             "Market/cloudbed-1": None, "Market/cloudbed-2": None}

TASK_RE = re.compile(r"_#(\d+)-\d+:\s*(task_\d+)")
SCORE_RE = re.compile(r"Candidate\s+\d+:\s*Score:\s*([0-9.]+)")


def salvage_from_logs():
    """dataset -> {idx: best_score} parsed from shard logs."""
    salvaged = {}
    for logf in glob.glob(os.path.join(LOGD, "run_*.log")):
        name = os.path.basename(logf)
        m = re.match(r"run_(Bank|Telecom|Market_cloudbed-1|Market_cloudbed-2)_\d+_\d+\.log", name)
        if not m:
            continue
        ds = m.group(1).replace("_", "/")
        cur_idx, cur_scores = None, []
        for line in open(logf, errors="ignore"):
            tm = TASK_RE.search(line)
            if tm:
                if cur_idx is not None and cur_scores is not None:
                    salvaged.setdefault(ds, {})[cur_idx] = max(cur_scores) if cur_scores else 0.0
                cur_idx, cur_scores = int(tm.group(1)), []
                continue
            sm = SCORE_RE.search(line)
            if sm and cur_idx is not None:
                cur_scores.append(float(sm.group(1)))
        if cur_idx is not None and cur_scores is not None:
            salvaged.setdefault(ds, {})[cur_idx] = max(cur_scores) if cur_scores else 0.0
    return salvaged


def existing_eval_rows():
    """dataset -> set(idx) already present in any per-shard eval CSV."""
    done = {}
    for ds in DATASETS:
        done[ds] = set()
        for f in glob.glob(os.path.join(REPO, "test/result", ds, "agent-causal47v2*-glm-4.7.csv")):
            try:
                import pandas as pd
                df = pd.read_csv(f)
                if "row_id" in df:
                    done[ds] |= {int(x) for x in df["row_id"].dropna()}
            except Exception:
                pass
    return done


def ranges_of(idxs):
    idxs = sorted(idxs)
    if not idxs:
        return []
    out, s, prev = [], idxs[0], idxs[0]
    for x in idxs[1:]:
        if x == prev + 1:
            prev = x
        else:
            out.append((s, prev + 1))  # runner end_idx is inclusive -> use prev+1 minus 1 below
            s = prev = x
    out.append((s, prev + 1))
    return [(a, b - 1) for a, b in out]  # convert to inclusive end


def rerun_missing(ds, missing):
    """Run missing idx in small contiguous ranges (crash-isolated), unique tags."""
    MAX_RANGE = 12
    jobs = []
    for k, (s, e) in enumerate(ranges_of(missing)):
        for j, (s2, e2) in enumerate([(x, min(x + MAX_RANGE - 1, e)) for x in range(s, e + 1, MAX_RANGE)]):
            tag = f"causal47v2{ds.split('/')[0][:2]}{ds[-1]}{k}_{j}"
            logf = os.path.join(LOGD, f"rerun_{ds.replace('/', '_')}_{s2}_{e2}.log")
            cmd = [PY, "-m", "rca.run_agent_standard_multi_candidate", "--dataset", ds,
                   "--controller_max_step", "1", "--start_idx", str(s2), "--end_idx", str(e2),
                   "--timeout", "900", "--tag", tag]
            jobs.append((ds, s2, e2, tag, logf, cmd))

    def run(job):
        ds, s, e, tag, logf, cmd = job
        with open(logf, "w") as lf:
            subprocess.run(cmd, cwd=REPO, stdout=lf, stderr=subprocess.STDOUT, timeout=6 * 3600)
        return tag

    with ThreadPoolExecutor(max_workers=3) as ex:
        list(ex.map(run, jobs))


def aggregate(salvaged):
    import pandas as pd
    print("\n===== 新主表（新打分器 × GLM-4.7）=====")
    summary = {}
    for ds, n in DATASETS.items():
        best = dict(salvaged.get(ds, {}))
        for f in glob.glob(os.path.join(REPO, "test/result", ds, "agent-causal47v2*-glm-4.7.csv")):
            try:
                df = pd.read_csv(f)
                for _, r in df.iterrows():
                    if pd.notna(r.get("row_id")) and pd.notna(r.get("score")):
                        idx = int(r["row_id"])
                        best[idx] = max(best.get(idx, 0.0), float(r["score"]))
            except Exception:
                pass
        vals = list(best.values())
        c = sum(1 for v in vals if v >= 0.999) / n * 100
        p = sum(1 for v in vals if 0 < v < 0.999) / n * 100
        summary[ds] = (len(vals), round(c, 2), round(p, 2), round(c + p, 2))
        old = OLD_GLM47.get(ds)
        old_s = f"{old[0]}/{old[1]}/{old[2]}" if old else "6.92/20.65/27.57 (两 cloudbed 合计)"
        print(f"{ds:18s} 覆盖 {len(vals):3d}/{n}  Correct/Partial/Total = {c:5.2f}/{p:5.2f}/{c+p:5.2f}   旧表: {old_s}")
    with open(os.path.join(REPO, "baselines/results/causal_rerun_summary.csv"), "w") as fo:
        fo.write("dataset,covered,n,correct,partial,total\n")
        for ds, (cov, c, p, t) in summary.items():
            fo.write(f"{ds},{cov},{DATASETS[ds]},{c},{p},{t}\n")
    print("写入 baselines/results/causal_rerun_summary.csv")


def main():
    salvaged = salvage_from_logs()
    done_eval = existing_eval_rows()
    for ds, n in DATASETS.items():
        salv = set(salvaged.get(ds, {})) | done_eval.get(ds, set())
        missing = sorted(set(range(n)) - salv)
        print(f"{ds}: 已挽救 {len(salvaged.get(ds, {}))} + eval {len(done_eval.get(ds, set()))}，缺 {len(missing)}", flush=True)
        if missing:
            rerun_missing(ds, missing)
            print(f"{ds}: 补跑完成", flush=True)
    # 覆盖率门禁：任何数据集不完整则以非零退出，让看门狗继续重试
    final_cov = {}
    for ds, n in DATASETS.items():
        done = set(salvage_from_logs().get(ds, {})) | existing_eval_rows().get(ds, set())
        final_cov[ds] = len(done)
        print(f"[coverage] {ds}: {len(done)}/{n}", flush=True)
    if any(final_cov[ds] < n for ds, n in DATASETS.items()):
        print("[coverage] 不完整，非零退出以触发看门狗重试", flush=True)
        sys.exit(1)
    aggregate(salvage_from_logs())


if __name__ == "__main__":
    main()
