#!/bin/bash
# Full baseline benchmark: MicroCause + CIRCA over all four OpenRCA datasets.
# CIRCA is fast (sequential per dataset). MicroCause is sharded in parallel.
# Usage: bash run_all.sh [JOBS]        (default JOBS=8)
set -u
cd "$(dirname "$0")"
PY=/root/shared-nvme/.conda/envs/RCAEval_py3.12/bin/python
JOBS=${1:-8}
mkdir -p results logs

DATASETS=(Bank Telecom Market-1 Market-2)
declare -A NQ=( [Bank]=136 [Telecom]=51 [Market-1]=70 [Market-2]=78 )

echo "=== CIRCA (sequential) ==="
for ds in "${DATASETS[@]}"; do
    $PY run_baseline.py --method circa --dataset "$ds" \
        --out "results/circa_${ds}.jsonl" > "logs/circa_${ds}.log" 2>&1
    echo "circa $ds done"
done

echo "=== MicroCause (sharded, $JOBS parallel) ==="
pids=()
for ds in "${DATASETS[@]}"; do
    n=${NQ[$ds]}
    # ~10 queries per shard
    step=$(( (n + 9) / 10 ))
    for ((s=0; s<n; s+=step)); do
        e=$((s+step)); [ $e -gt $n ] && e=$n
        $PY run_baseline.py --method microcause --dataset "$ds" \
            --start $s --end $e \
            --out "results/microcause_${ds}_${s}_${e}.jsonl" \
            > "logs/microcause_${ds}_${s}_${e}.log" 2>&1 &
        pids+=($!)
        # throttle to JOBS concurrent processes
        while [ "$(jobs -rp | wc -l)" -ge "$JOBS" ]; do sleep 5; done
    done
done
wait
echo "=== all done; merging shards ==="
for ds in "${DATASETS[@]}"; do
    cat results/microcause_${ds}_*_*.jsonl > "results/microcause_${ds}.jsonl" 2>/dev/null
done
$PY summarize.py results/circa_*.jsonl results/microcause_Bank.jsonl \
    results/microcause_Telecom.jsonl results/microcause_Market-1.jsonl \
    results/microcause_Market-2.jsonl
