#!/bin/bash
# Detached watchdog for the causal-rerun recovery: keeps re-running the
# idempotent recovery script until it completes (exit 0), regardless of
# whether the interactive CLI session is alive.
LOGD=/root/shared-nvme/work/agent/OpenRCA/baselines/logs/causal_rerun
mkdir -p "$LOGD"
while true; do
    /root/shared-nvme/.conda/envs/RCAEval_py3.12/bin/python -u \
        /root/shared-nvme/work/agent/OpenRCA/baselines/recover_causal_rerun.py \
        >> "$LOGD/recover_watchdog.log" 2>&1
    code=$?
    echo "[$(date '+%F %T')] recover_causal_rerun exited with $code" >> "$LOGD/recover_watchdog.log"
    if [ $code -eq 0 ]; then
        break
    fi
    sleep 60
done
echo "[$(date '+%F %T')] WATCHDOG DONE" >> "$LOGD/recover_watchdog.log"
