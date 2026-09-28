#!/bin/bash
# ============================================================================
# ClusTopoRCA 主表刷新：新打分器（四维，含因果一致性）× GLM-4.7 全量重跑
# 一站式执行：等待报告重生成 -> 补丁 -> 冒烟门禁 -> 全量 -> 汇总对比
# 断点：各阶段有 sentinel/计数检查，重跑本脚本会跳过已完成阶段。
# 用法:  bash baselines/run_causal_rerun_all.sh  [并发数，默认5]
# ============================================================================
set -u
cd /root/shared-nvme/work/agent/OpenRCA
PY_FAISS=/root/shared-nvme/.conda/envs/faiss-env/bin/python
PY_RCA=/root/shared-nvme/.conda/envs/RCAEval_py3.12/bin/python
OMNI=/root/shared-nvme/work/timeSeries/OmniTransfer_new
BASE=/root/shared-nvme/work/agent/OpenRCA/baselines
LOGD=$BASE/logs/causal_rerun
mkdir -p "$LOGD"
JOBS=${1:-5}
TAG=causal47

log(){ echo "[$(date '+%F %T')] $*" | tee -a "$LOGD/master.log"; }

# ---------------------------------------------------------------------------
log "STAGE A: 等待新打分器报告重生成完成（按去重窗口计数：Bank 127 / Telecom 51 / Market-1 57 / Market-2 63）..."
# 期望报告数（去重窗口）：Bank 127 / Telecom 51 / Market-1 57 / Market-2 63
wait_dir_count(){ # dir pattern expected
  local dir="$1" pat="$2" exp="$3" waited=0
  while true; do
    local n=$(ls "$dir"/$pat 2>/dev/null | wc -l)
    if [ "$n" -ge "$exp" ]; then log "  OK: $dir 已有 $n 份 ($pat)"; return 0; fi
    waited=$((waited+120))
    if [ $waited -gt 14400 ]; then log "  TIMEOUT: $dir 只有 $n/$exp 份"; return 1; fi
    sleep 120
  done
}
A_OK=1
wait_dir_count "$OMNI/1204_causal"        "Bank_cluster_window_anomaly_report_*.txt"    127 || A_OK=0
wait_dir_count "$OMNI/1216_causal"        "Telecom_cluster_window_anomaly_report_*.txt" 51  || A_OK=0
# Market：c1/c2 分离布局（去重窗口 57/63）
wait_dir_count "$OMNI/1215_causal/c1"     "Market_cluster_window_anomaly_report_*.txt"  57 || A_OK=0
wait_dir_count "$OMNI/1215_causal/c2"     "Market_cluster_window_anomaly_report_*.txt"  63 || A_OK=0
[ $A_OK -eq 1 ] || { log "STAGE A 失败：报告未齐，终止。"; exit 1; }
log "STAGE A 完成：新报告全部就绪。"

# ---------------------------------------------------------------------------
log "STAGE B: 切换 tool agent 到新报告目录（幂等，先备份）..."
BANK_TA=camel/agents/tool_agents/local_script_tool_agent_5tools_fast.py
TEL_TA=camel/agents/tool_agents/Telecom_local_script_tool_agent_5tools_fast.py
MKT_TA=camel/agents/tool_agents/Market_local_script_tool_agent_5tools_fast_new.py
for f in "$BANK_TA" "$TEL_TA" "$MKT_TA"; do [ -f "$f.bak_causal" ] || cp "$f" "$f.bak_causal"; done
sed -i 's/output_folder_name = "1204"/output_folder_name = "1204_causal"/' "$BANK_TA"
sed -i 's/output_folder_name = "1216"/output_folder_name = "1216_causal"/' "$TEL_TA"
sed -i 's/output_folder_name = "1215"/output_folder_name = "1215_causal"/' "$MKT_TA"
grep -n 'output_folder_name = "1204_causal"' "$BANK_TA" >/dev/null && \
grep -n 'output_folder_name = "1216_causal"' "$TEL_TA" >/dev/null && \
grep -n 'output_folder_name = "1215_causal"' "$MKT_TA" >/dev/null \
  && log "STAGE B 完成（Market 的 cloudbed 传参补丁由脚本生成侧处理）" \
  || { log "STAGE B 失败：sed 未生效"; exit 1; }

# ---------------------------------------------------------------------------
log "STAGE C: Bank 冒烟（2 条查询，GLM-4.7）..."
if [ ! -s "$LOGD/smoke.ok" ]; then
  $PY_FAISS -m rca.run_agent_standard_multi_candidate --dataset Bank \
      --controller_max_step 1 --start_idx 0 --end_idx 1 --tag ${TAG}_smoke \
      >> "$LOGD/smoke_bank.log" 2>&1
  rows=$($PY_RCA -c "
import pandas as pd, sys
try:
    df = pd.read_csv('test/result/Bank/agent-${TAG}_smoke-glm-4.7.csv')
    ok = df['prediction'].notna().sum()
    print(ok)
except Exception:
    print(0)")
  if [ "${rows:-0}" -ge 1 ]; then touch "$LOGD/smoke.ok"; log "STAGE C 通过（$rows 条预测）";
  else log "STAGE C 失败：冒烟无预测输出，终止。日志见 $LOGD/smoke_bank.log"; exit 1; fi
else
  log "STAGE C 跳过（smoke.ok 已存在）"
fi

# ---------------------------------------------------------------------------
log "STAGE D: 三数据集全量重跑（GLM-4.7，${JOBS} 并发分片）..."
run_shards(){ # dataset n
  local ds="$1"
  local n="$2"
  local step=$(( (n + JOBS - 1) / JOBS ))
  for ((s=0; s<n; s+=step)); do
    local e=$((s+step)); [ $e -gt $n ] && e=$n
    local marker="$LOGD/done_${ds//\//_}_${s}_${e}"
    if [ -f "$marker" ]; then continue; fi
    (
      $PY_FAISS -m rca.run_agent_standard_multi_candidate --dataset "$ds" \
          --controller_max_step 1 --start_idx $s --end_idx $e --tag $TAG \
          >> "$LOGD/run_${ds//\//_}_${s}_${e}.log" 2>&1 && touch "$marker"
    ) &
    while [ "$(jobs -rp | wc -l)" -ge "$JOBS" ]; do sleep 20; done
  done
  wait
}
for spec in "Bank 136" "Telecom 51" "Market/cloudbed-1 70" "Market/cloudbed-2 78"; do
  set -- $spec
  log "  开始 $1（$2 条）..."
  run_shards "$1" "$2"
  log "  $1 完成。"
done
log "STAGE D 完成。"

# ---------------------------------------------------------------------------
log "STAGE E: 汇总新主表并与旧主表对比..."
$PY_RCA - <<'EOF' | tee -a "$LOGD/master.log"
import glob, json
import pandas as pd

rows = []
for ds_dir, ds_name in [("Bank","Bank"), ("Telecom","Telecom"),
                        ("Market/cloudbed-1","Market-1"), ("Market/cloudbed-2","Market-2")]:
    f = f"test/result/{ds_dir}/agent-causal47-glm-4.7.csv"
    try:
        df = pd.read_csv(f)
    except Exception:
        rows.append((ds_name, 0, 0, 0, 0)); continue
    df = df.dropna(subset=["score"])
    df = df[df["score"].astype(str).str.replace(".","",regex=False).str.replace("0","",regex=False).str.strip().ne("") | (df["score"]==0)]
    s = pd.to_numeric(df["score"], errors="coerce").dropna()
    n = len(s)
    correct = (s >= 0.999).mean() if n else 0
    partial = ((s > 0) & (s < 0.999)).mean() if n else 0
    rows.append((ds_name, n, round(correct*100,2), round(partial*100,2), round((correct+partial)*100,2)))

print("\n===== 新主表（新打分器 × GLM-4.7）Correct/Partial/Total % =====")
print(f"{'dataset':10s} {'n':>4s} {'Correct':>8s} {'Partial':>8s} {'Total':>8s}")
for r in rows:
    print(f"{r[0]:10s} {r[1]:>4d} {r[2]:>8.2f} {r[3]:>8.2f} {r[4]:>8.2f}")

old = {"Bank": (20.59, 27.94, 48.53), "Telecom": (29.42, 37.25, 66.67),
       "Market-1": None, "Market-2": None}  # glm-4.7 旧主表（论文 Table 1）
print("\n旧主表 glm-4.7（论文值，Market 为两个 cloudbed 合计 6.92/20.65/27.57）：")
print(f"  Bank    20.59/27.94/48.53   Telecom    29.42/37.25/66.67   Market  6.92/20.65/27.57")
with open("baselines/results/causal_rerun_summary.csv", "w") as fo:
    fo.write("dataset,n,correct,partial,total\n")
    for r in rows:
        fo.write(",".join(map(str, r)) + "\n")
EOF
log "全部阶段完成。结果: baselines/results/causal_rerun_summary.csv"
