# Classical & LLM-based RCA Baselines for OpenRCA

This directory contains the reproduction of three baseline methods on the
three OpenRCA benchmark datasets (**Bank**, **Telecom**, **Market**
cloudbed-1/2), used for the comparison against ClusTopoRCA in the revised
paper.

- **MicroCause** (Meng et al., ISSRE 2020): PCMCI (PCTS) causal graph over KPI
  time series + partial-correlation weighted transition matrix + random walk
  from the SLI node. (classical, metric-based)
- **CIRCA** (Li et al., KDD 2022): PC causal discovery + regression-based
  hypothesis testing (RHT) of each node against its parents. (classical,
  metric-based)
- **mABC** (Zhang et al., EMNLP 2024 Findings): multi-agent LLM system with
  blockchain-inspired voting; a ProcessScheduler orchestrates expert agents
  (Data Detective, Dependency Explorer, ...) over endpoint statistics and
  call topology. (LLM-based, trace-based)

Both algorithm cores are extracted from the RCAEval implementations
(`/root/shared-nvme/work/code/RCA/RCAEval`, files `RCAEval/e2e/microcause.py`,
`RCAEval/e2e/circa.py`, `RCAEval/graph_construction/pc.py`,
`RCAEval/graph_heads/rht.py`, `RCAEval/classes/*`) and live in `core/`, with
attribution headers. Only the code paths the two methods actually use were
kept (e.g. the ~2000 lines of disabled SPOT anomaly-detection code in the
original `microcause.py` are omitted).

## Layout

```
baselines/
├── core/
│   ├── microcause.py      # extracted MicroCause core (PCMCI + PCTS walk)
│   └── circa.py           # extracted CIRCA core (PC + RHT + support classes)
├── openrca_data.py        # OpenRCA -> wide-KPI-frame adapter (3 datasets)
├── run_baseline.py        # per-query runner (resumable JSONL output)
├── summarize.py           # top-1/3/5 accuracy & MRR per dataset/level
├── docs/                  # raw KPI-name inventories used to design the KPI maps
├── mabc/                  # mABC reproduction (LLM multi-agent, see below)
│   ├── agents/ utils/     # copied from the official mABC release (+ repairs)
│   ├── settings.py        # LLM endpoint & run control (env-overridable)
│   ├── build_data.py      # OpenRCA traces -> mABC input JSONs
│   ├── run_mabc.py        # batch driver, JSONL output like run_baseline.py
│   └── data_files/        # generated per-dataset inputs
└── results/               # runner output (created at runtime)
```

## Environment

Use the existing conda env (all dependencies already installed):
`/root/shared-nvme/.conda/envs/RCAEval_py3.12/bin/python`
(tigramite 5.2, pingouin 0.5.3, causal-learn 0.1.3.3, networkx 2.5, pandas,
scikit-learn, scipy).

Data root defaults to `/root/shared-nvme/data_set/OpenRCA` (override with the
`OPENRCA_DATA` environment variable).

## Usage

```bash
PY=/root/shared-nvme/.conda/envs/RCAEval_py3.12/bin/python

# CIRCA on all Telecom queries
$PY run_baseline.py --method circa --dataset Telecom

# MicroCause on the first 10 Bank queries
$PY run_baseline.py --method microcause --dataset Bank --start 0 --end 10

# summarize
$PY summarize.py results/circa_Telecom.jsonl results/microcause_Bank.jsonl
```

Datasets: `Bank`, `Telecom`, `Market-1`, `Market-2` (the two Market
cloudbeds). The runner is resumable (re-running skips completed query ids)
and shardable via `--start/--end` for parallel execution, e.g.:

```bash
for s in 0 34 68 102; do
  $PY run_baseline.py --method microcause --dataset Bank \
      --start $s --end $((s+34)) --out results/microcause_Bank_$s.jsonl &
done
```

Runtime: CIRCA ≈ 1–2 s/query; MicroCause ≈ 1–2 min/query (PCMCI-dominated),
so shard MicroCause across cores.

## Adaptation decisions (OpenRCA -> RCAEval input format)

Both methods consume a wide DataFrame: a `time` column plus one
`{entity}_{metric}` column per KPI series. Building it from OpenRCA telemetry
required the following choices (see `openrca_data.py` for details):

1. **Window**: the 30-min analysis window is parsed from each `query.csv`
   instruction (UTC+8); 30 min of preceding context is added as the
   normal-behaviour baseline (`--pre-minutes`).
2. **KPI selection**: raw telemetry has hundreds of KPIs per entity
   (inventories in `docs/`). We select a small canonical set per dataset and
   entity type (CPU / memory / disk / network / JVM / DB-session /
   response-time...), e.g. Bank `OSLinux-CPU_CPU_CPUCpuUtil` -> `cpu`;
   Telecom db `Session_pct` -> `sess`; Market `system.cpu.pct_usage` -> `cpu`.
   Cumulative counters (Market container CPU/network) are differenced.
3. **Entity normalization**: Market container ids `node-6.adservice2-0` map to
   the pod entity `adservice2-0`; Market service ids `adservice-grpc` map to
   `adservice`; Telecom entities `os_001`/`docker_003`/`db_007` are sanitized
   to `os-001`/... inside frames (CIRCA's RHT requires exactly one `_` per
   column name) and mapped back to the original ground-truth names for
   scoring.
4. **Anomalous-entity prefilter**: per query, entities are scored by the max
   robust z-score of their KPIs in the fault window vs the preceding context;
   only the top-20 (`--max-entities`) plus the SLI column are kept. This
   mirrors the anomaly-detection-first design of the original MicroCause
   paper and keeps PCMCI/PC tractable.
5. **SLI**: MicroCause needs a starting node for the random walk. Per dataset
   the SLI is the most anomalous application-level response-time column in
   the window (Bank: `ServiceTest*_mrt`; Telecom: `osb-001_avgt`; Market:
   `frontend_mrt`).
6. **Alert time (`inject_time`)**: `--inject-mode gt` (default) passes the
   ground-truth fault timestamp as the alert time, following the RCAEval
   protocol where `inject_time.txt` is provided. `detect` derives it from the
   SLI series. Only CIRCA consumes it (MicroCause ignores it upstream too).
7. **CIRCA windowing on minute-level data**: the RCAEval hardcoded
   second-level windows (`interval=1s, lookup=120, detect=10`) are
   re-parameterized to `interval=60s, lookup=30 min, detect=5 min`, i.e.
   train on [inject-30min, inject-5min], test on the 5 points ending at
   inject+5min.
8. **Numerical robustness**: constant/collinear KPI columns are dropped
   before PC (fisher-z aborts on singular correlation matrices); tigramite
   5.x API change (`return_significant_links` removed) is replicated by
   thresholding `p_matrix` at `alpha_level=0.001` as in the original.

## Output & evaluation

Each query yields one JSON line: ranked candidate entities (filtered to the
candidate component set = union of `record.csv` components), top-1, ground
truth rank, hit@{1,3,5}, runtime. `summarize.py` aggregates top-k accuracy
and MRR overall and per root-cause level (pod/node/service).

These classical methods only localize the root-cause **component**; they do
not predict the fault reason or occurrence time, so comparison with
ClusTopoRCA should use component-localization accuracy (e.g. restricted to
the OpenRCA tasks that require the component element).

## mABC reproduction (LLM-based baseline)

`mabc/` contains the official mABC code with minimal repairs plus an OpenRCA
adapter:

1. **Build the inputs** (offline, once per dataset):
   ```bash
   $PY mabc/build_data.py --dataset Bank    # also Telecom / Market-1 / Market-2
   ```
   This scans the raw trace spans and materializes `endpoint_stats.json`
   (per-endpoint per-minute calls / success_rate / error_rate /
   average_duration / timeout_rate), `endpoint_maps.json` (per-minute
   downstream topology) and `label.json` + `label_index.json` (per-query alert
   minute and alerting endpoint) under `mabc/data_files/{dataset}/`, in
   exactly the formats mABC's `simple_sample/` documents.

2. **Run** (LLM endpoint via env; defaults to the active GLM block of the
   repo's `rca/api_config.yaml` — glm-4.5 on the coding endpoint):
   ```bash
   MABC_MODEL=glm-4.5 $PY mabc/run_mabc.py --dataset Bank --start 0 --end 5
   ```
   Output JSONL matches `run_baseline.py` (`method="mabc"`, per-query tokens
   and runtime included), so `summarize.py` works on it directly.

Adaptation decisions specific to mABC:

1. **Endpoint universe = trace-visible entities** (mABC is trace/metric
   endpoint-centric): Bank trace `cmdb_id` (Tomcat01-04, MG01/02, IG01/02 +
   docker hosts — apache/Mysql/Redis pods never appear in traces and are
   therefore unreachable for mABC); Telecom span `cmdb_id` (docker_*) plus
   `dsName` (db_*) for JDBC spans (os_* nodes are trace-invisible); Market
   pods (all trace-visible; node-* invisible). Predictions are evaluated
   against `record.csv` components with exact/fuzzy string matching; the
   coverage limitation is inherent to mABC's design and is reported as such.
2. **Timeout rule**: span duration >= per-entity p95 of the day (the original
   code hardcoded 100 ms).
3. **Alert synthesis**: per query, the alerting endpoint is the trace-root
   entity (maps["None"]) with >= 5 calls and the worst timeout_rate at the
   ground-truth fault minute; the alert text follows the original template.
4. **Repairs to the released code** (all documented in file docstrings):
   DependencyExplorer tool-path typo; unbounded ReAct recursion (now
   `MABC_MAX_STEPS`, default 15); `Final Answer` parsing crash; voting-weight
   initialization and the no-poll `NameError` (voting remains **off** by
   default, matching the released code where it is commented out; enable with
   `MABC_VOTING=1`); the broken `get_endpoint_upstream` /
   `get_call_chain_for_endpoint` tools are implemented.
5. **LLM layer**: `base_url` support, token-usage accounting per query,
   temperature omitted for reasoning models.

## Flow-of-Action reproduction (LLM-based baseline)

`foa/` re-implements Flow-of-Action (Pei et al., WWW 2025 Companion) from the
paper — no official code is released — following the RCA-agent scaffold
conventions of this repository. All paper-specified elements are reproduced:

- **Main loop**: Thought -> **ActionSet** -> Action -> Observation with a
  MainAgent as the only decision maker and four auxiliary agents
  (ActionAgent proposes the candidate set with reasons; JudgeAgent assesses
  termination after `match_observation`; ObAgent denoises observations and
  judges the anomaly class; CodeAgent powers `generate_sop_code`).
- **SOP flow rules**: the paper's Fig. 5 rules are included verbatim
  (`agents.FLOW_RULES`) and also enforced as code (`foa_loop.mandated_next`).
- **Flow tools**: `match_sop` / `generate_sop` / `generate_sop_code` /
  `run_sop` / `match_observation`, plus terminal `Speak`.
- **Hyper-parameters**: action set size 5, max 20 steps, at most 3 reported
  root causes.
- **Tool-layer denoising**: `whether_is_abnormal_metric` (rule-based robust
  z-scores, as in the paper's appendix), `collect_trace` (anomalous-span
  statistics), `collect_logs` (keyword extraction), `get_relevant_metric`.

Adaptation decisions (documented since the paper leaves them open):

1. **Knowledge bases**: `knowledge.py` authors 8 SOPs and 19 incidents
   covering the OpenRCA fault-type vocabulary, in the paper's name/steps and
   manifestation/type formats.
2. **Retrieval**: TF-IDF cosine similarity (scikit-learn) replaces embedding
   similarity for `match_sop` / `match_observation` — the KBs are small
   (<=20 entries) and no embedding model is bundled with the paper.
3. **Data tools** operate on the raw OpenRCA telemetry (metrics/traces/logs)
   of the current query window (+30 min baseline context); Telecom has no
   logs and `collect_logs` reports that honestly.
4. **LLM**: same GLM-4.5 endpoint defaults as mABC (`settings.py`, env
   `FOA_*` overrides); final report follows the OpenRCA JSON answer contract
   (up to 3 root causes with candidate components restricted to the
   record.csv vocabulary).

Run:
```bash
$PY foa/run_foa.py --dataset Bank --start 0 --end 5
```
Output JSONL is schema-compatible with the other baselines (`summarize.py`).

## Results (component localization, full runs completed 2026-08-11)

Final consolidated table: `results/FINAL_baselines_component_accuracy.csv`
(ClusTopoRCA's own component-level numbers, mined from its experiment logs:
`results/clustoporca_component_accuracy.csv` / `..._predictions.csv`).
All 335 queries per method completed with zero errors; candidate answer space
is the official `basic_prompt` inventory; `circa-gt` uses the ground-truth
fault time as inject_time (RCAEval protocol), `circa-detect` derives it from
the SLI. Component top-1:

| method | Bank | Telecom | Market-1 | Market-2 | avg tokens/query |
|---|---|---|---|---|---|
| MicroCause | 0.037 | 0.020 | 0.014 | 0.026 | 0 |
| CIRCA (inject=gt) | 0.463 | 0.176 | 0.329 | 0.462 | 0 |
| CIRCA (inject=detect) | 0.243 | 0.157 | 0.114 | 0.179 | 0 |
| mABC (glm-4.5) | 0.088 | 0.000 | 0.014 | 0.013 | ~32k |
| FoA (glm-4.5) | 0.265 | 0.039 | 0.086 | 0.179 | ~42k |
| ClusTopoRCA strict (5 LLMs) | 0.074–0.125 | 0.137–0.255 | 0–0.014 | 0.077–0.103 | — |
| ClusTopoRCA any-candidate | 0.213–0.235 | 0.392–0.431 | 0.014–0.029 | 0.154–0.231 | — |
