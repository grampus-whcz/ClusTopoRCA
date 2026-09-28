"""
OpenRCA dataset adapter for classical metric-based RCA baselines.

Builds the wide ``{entity}_{metric}`` KPI DataFrames that MicroCause and CIRCA
expect out of the raw OpenRCA telemetry (Bank / Telecom / Market cloudbed-1,2).

Per RCA query (a 30-minute fault window), the adapter:
  1. parses the analysis window from the OpenRCA ``query.csv`` instruction
     (all datetime strings are UTC+8);
  2. slices the minute-level metric telemetry of that day
     (default: window + 30 min of preceding context + 10 min trailing);
  3. selects a small set of canonical KPIs per entity (see the *_KPIS maps;
     raw KPI inventories are kept in docs/*_kpi_names.txt);
  4. pivots the long-format telemetry into a wide frame on a regular 60 s grid
     (interpolated, constant columns dropped); cumulative counters are
     differenced (e.g. Market container CPU/network);
  5. sanitizes names so every column contains exactly one ``_``
     (``{entity}_{metric}`` — a hard requirement of CIRCA's RHT scorer):
     entity ``_``/illegal chars become ``-``;
  6. optionally keeps only the top-N most anomalous entities (robust z-score
     of the fault window w.r.t. the preceding context), which mirrors the
     anomalous-KPI selection step of the original MicroCause paper and keeps
     PCMCI/PC tractable.

Column naming note: Telecom entities (``os_001``, ``docker_003`` ...) contain
underscores and are sanitized to ``os-001`` etc.; the ``col2entity`` mapping
returned by ``build_frame`` maps every column back to the *original* entity
name used by ``record.csv`` ground truth.
"""

import os
import re
from datetime import datetime, timedelta, timezone

import numpy as np
import pandas as pd

DATA_ROOT = os.environ.get("OPENRCA_DATA", "/root/shared-nvme/data_set/OpenRCA")

TZ8 = timezone(timedelta(hours=8))

_MONTHS = {
    m.lower(): i
    for i, m in enumerate(
        ["January", "February", "March", "April", "May", "June", "July",
         "August", "September", "October", "November", "December"], start=1)
}

# ---------------------------------------------------------------------------
# Dataset registry
# ---------------------------------------------------------------------------
# KPI maps: canonical metric code -> regex on the raw kpi_name / column.
# ``diff=True`` marks cumulative counters that must be differenced.

BANK_CONTAINER_KPIS = {
    "cpu": r"^OSLinux-CPU_CPU_CPUCpuUtil$",
    "mem": r"^OSLinux-OSLinux_MEMORY_MEMORY_MEMUsedMemPerc$",
    "netinerr": r"^OSLinux-OSLinux_NETWORK_ens160_NETInErrPrc$",
    "netouterr": r"^OSLinux-OSLinux_NETWORK_ens160_NETOutErrPrcc$",
    "netutil": r"^OSLinux-OSLinux_NETWORK_ens160_NETBandwidthUtil$",
    "diskbusy": r"^OSLinux-OSLinux_LOCALDISK_LOCALDISK-sda_DSKPercentBusy$",
    "jvmheap": r"^JVM-Memory_\d+_JVM_Memory_HeapMemoryUsed$",
    "jvmcpu": r"^JVM-Operating System_\d+_JVM_JVM_CPULoad$",
}

TELECOM_NODE_KPIS = {
    "cpu": r"^CPU_util_pct$",
    "mem": r"^Memory_used_pct$",
    "diskio": r"^Disk_io_util$",
    "netin": r"^Incoming_network_traffic$",
    "netout": r"^Outgoing_network_traffic$",
}
TELECOM_CONTAINER_KPIS = {
    "cpu": r"^container_cpu_used$",
    "mem": r"^container_mem_used$",
    "thread": r"^container_thread_used_pct$",
}
TELECOM_SERVICE_KPIS = {
    "cpu": r"^CPU_Used_Pct$",
    "mem": r"^MEM_Used_Pct$",
    "sess": r"^Session_pct$",
    "tps": r"^TPS_Per_Sec$",
    "dbtime": r"^DbTime$",
}

MARKET_CONTAINER_KPIS = {
    "cpu": r"^container_cpu_usage_seconds$",          # counter -> diff
    "mem": r"^container_memory_working_set_MB$",
    "netdrop": r"^container_network_receive_packets_dropped.eth0$",  # counter -> diff
}
MARKET_NODE_KPIS = {
    "cpu": r"^system.cpu.pct_usage$",
    "mem": r"^system.mem.pct_usage$",
    "disk": r"^system.disk.pct_usage$",
    "iowait": r"^system.cpu.iowait$",
    "ping": r"^ping.can_connect$",
}

DATASETS = {
    "Bank": {
        "root": "Bank",
        "kind": "bank",
        "sli_pattern": r"^ServiceTest\d+_mrt$",   # auto-pick the most anomalous one
    },
    "Telecom": {
        "root": "Telecom",
        "kind": "telecom",
        "sli_pattern": r"^osb-001_avgt$",
    },
    "Market-1": {
        "root": "Market/cloudbed-1",
        "kind": "market",
        "sli_pattern": r"^frontend_mrt$",
    },
    "Market-2": {
        "root": "Market/cloudbed-2",
        "kind": "market",
        "sli_pattern": r"^frontend_mrt$",
    },
}


# ---------------------------------------------------------------------------
# record / query loading
# ---------------------------------------------------------------------------
def load_records(dataset: str) -> pd.DataFrame:
    """Load record.csv normalized to [idx, level, component, reason, timestamp, datetime]."""
    cfg = DATASETS[dataset]
    path = os.path.join(DATA_ROOT, cfg["root"], "record.csv")
    raw = pd.read_csv(path).dropna(how="all")
    kind = cfg["kind"]
    if kind == "bank":      # level,component,timestamp,datetime,reason
        df = raw.rename(columns=str.lower)[["level", "component", "timestamp", "datetime", "reason"]]
    elif kind == "telecom":  # level,reason,component,timestamp,datetime
        df = raw[["level", "reason", "component", "timestamp", "datetime"]]
    else:                    # market: timestamp,level,component,reason,datetime
        df = raw[["timestamp", "level", "component", "reason", "datetime"]]
    df = df.reset_index(drop=True)
    df.insert(0, "idx", df.index)
    df["timestamp"] = df["timestamp"].astype(float).astype(np.int64)
    return df


def load_queries(dataset: str) -> pd.DataFrame:
    cfg = DATASETS[dataset]
    path = os.path.join(DATA_ROOT, cfg["root"], "query.csv")
    df = pd.read_csv(path)
    df.insert(0, "idx", df.index)
    return df


def candidate_components(dataset: str) -> list:
    """The set of entities that may be a root cause (union of ground truth)."""
    return sorted(load_records(dataset)["component"].unique().tolist())


_REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def candidate_inventory(dataset: str) -> list:
    """Official candidate component list used by ClusTopoRCA/RCA-agent, parsed
    from the repo's basic_prompt files (``cand`` block). This is the answer
    space every compared method is evaluated on."""
    kind = DATASETS[dataset]["kind"]
    fname = {"bank": "basic_prompt_Bank.py", "telecom": "basic_prompt_Telecom.py",
             "market": "basic_prompt_Market.py"}[kind]
    path = os.path.join(_REPO_ROOT, "rca", "baseline", "rca_agent", "prompt", fname)
    text = open(path).read()
    m = re.search(r'cand\s*=\s*f?"""(.*?)"""', text, re.DOTALL)
    if not m:
        raise ValueError(f"cand block not found in {path}")
    items = re.findall(r"^-\s+([A-Za-z0-9_][A-Za-z0-9_\-\.]*)\s*$", m.group(1), re.M)
    if not items:
        raise ValueError(f"no candidates parsed from {path}")
    return sorted(set(items))


def parse_window(instruction: str):
    """Parse the analysis window (unix seconds, UTC+8 source) from an instruction.

    Handles all observed phrasings, e.g.
      Bank:   "On March 4, 2021, within the time range of 14:30 to 15:00, ..."
              "On March 6, 2021, between 18:30 and 19:00, ..."
      Telecom: "... time range of April 11, 2020, from 00:00 to 00:30, ..."
      Market:  "... time range of March 20, 2022, from 09:00 to 09:30. ..."
    """
    m = re.search(r"([A-Z][a-z]+)\s+(\d{1,2}),\s+(\d{4})", instruction)
    if not m:
        raise ValueError(f"no date found in instruction: {instruction[:120]}")
    month, day, year = _MONTHS[m.group(1).lower()], int(m.group(2)), int(m.group(3))
    times = re.findall(r"\b(\d{1,2}):(\d{2})\b", instruction[m.end():])
    if len(times) < 2:
        raise ValueError(f"no time range found in instruction: {instruction[:120]}")
    (h1, m1), (h2, m2) = (int(times[0][0]), int(times[0][1])), (int(times[1][0]), int(times[1][1]))
    ws = datetime(year, month, day, h1, m1, tzinfo=TZ8).timestamp()
    we = datetime(year, month, day, h2, m2, tzinfo=TZ8).timestamp()
    if we <= ws:  # window crosses midnight ("from 23:30 to March 7 ... at 00:00")
        we += 86400
    return int(ws), int(we)


# ---------------------------------------------------------------------------
# telemetry loading / pivoting
# ---------------------------------------------------------------------------
def sanitize_entity(name: str) -> str:
    return re.sub(r"[^A-Za-z0-9-]", "-", str(name).replace("_", "-"))


def _grid_floor(ts: pd.Series, grid_s: int = 60) -> pd.Series:
    return (ts // grid_s) * grid_s


def _pivot_long(raw: pd.DataFrame, ts_col, entity_col, kpi_col, value_col,
                ts_unit, kpi_map, diff_codes, start, end,
                entity_transform=None, san2orig=None):
    """long-format telemetry -> dict of wide series columns on a 60 s grid."""
    raw = raw[raw[kpi_col].isin([k for k in raw[kpi_col].unique()
                                 if any(re.match(p, k) for p in kpi_map.values())])]
    if raw.empty:
        return {}
    # assign canonical code
    code = pd.Series(index=raw.index, dtype=object)
    for c, pattern in kpi_map.items():
        code.loc[raw[kpi_col].str.match(pattern)] = c
    raw = raw.assign(code=code).dropna(subset=["code"])
    ts = raw[ts_col].astype(np.int64)
    if ts_unit == "ms":
        ts = ts // 1000
    raw = raw.assign(ts=_grid_floor(ts), val=pd.to_numeric(raw[value_col], errors="coerce"))
    raw = raw[(raw["ts"] >= start) & (raw["ts"] <= end)].dropna(subset=["val"])
    if raw.empty:
        return {}
    raw["entity"] = raw[entity_col].astype(str)
    if entity_transform:
        raw["entity"] = raw["entity"].map(entity_transform)
    grouped = raw.groupby(["entity", "code", "ts"])["val"].mean().reset_index()
    out = {}
    for (entity, c), sub in grouped.groupby(["entity", "code"]):
        series = sub.set_index("ts")["val"].sort_index()
        if c in diff_codes:
            series = series.diff()
        san = sanitize_entity(entity)
        if san2orig is not None:
            san2orig.setdefault(san, entity)
        out[(san, c)] = series
    return out


def _melt_wide(raw: pd.DataFrame, ts_col, entity_col, codes, ts_unit, start, end,
               entity_transform=None, san2orig=None):
    """wide-format per-row-entity telemetry (e.g. Bank metric_app) -> series dict."""
    ts = raw[ts_col].astype(np.int64)
    if ts_unit == "ms":
        ts = ts // 1000
    raw = raw.assign(ts=_grid_floor(ts))
    raw = raw[(raw["ts"] >= start) & (raw["ts"] <= end)]
    if raw.empty:
        return {}
    pieces = {}
    for entity, sub in raw.groupby(raw[entity_col].astype(str)):
        if entity_transform:
            entity = entity_transform(entity)
        san = sanitize_entity(entity)
        if san2orig is not None:
            san2orig.setdefault(san, entity)
        for src, dst in codes.items():
            if src not in sub.columns:
                continue
            series = pd.to_numeric(sub.set_index("ts")[src], errors="coerce")
            series = series.groupby(level=0).mean().sort_index()
            # several raw entities may map to the same transformed entity
            # (e.g. Market adservice-grpc / adservice-http): average them.
            pieces.setdefault((san, dst), []).append(series)
    return {k: pd.concat(v).groupby(level=0).mean() for k, v in pieces.items()}


def _read_csv_cached(cache, path, **kw):
    if path not in cache:
        cache[path] = pd.read_csv(path, **kw)
    return cache[path]


def collect_series(kind: str, telemetry_dir: str, start: int, end: int, cache: dict):
    """Collect minute-indexed KPI series for one day slice.

    Returns (series, san2orig): series maps (sanitized_entity, code) -> Series;
    san2orig maps sanitized entity names back to the original record.csv names.
    """
    series, san2orig = {}, {}
    mdir = os.path.join(telemetry_dir, "metric")

    if kind == "bank":
        raw = _read_csv_cached(cache, os.path.join(mdir, "metric_container.csv"))
        series.update(_pivot_long(raw, "timestamp", "cmdb_id", "kpi_name", "value",
                                  "s", BANK_CONTAINER_KPIS, set(), start, end,
                                  san2orig=san2orig))
        app = _read_csv_cached(cache, os.path.join(mdir, "metric_app.csv"))
        series.update(_melt_wide(app, "timestamp", "tc",
                                 {"rr": "rr", "sr": "sr", "mrt": "mrt"}, "s", start, end,
                                 san2orig=san2orig))

    elif kind == "telecom":
        for fname, kmap in [("metric_node.csv", TELECOM_NODE_KPIS),
                            ("metric_container.csv", TELECOM_CONTAINER_KPIS),
                            ("metric_service.csv", TELECOM_SERVICE_KPIS)]:
            raw = _read_csv_cached(cache, os.path.join(mdir, fname))
            series.update(_pivot_long(raw, "timestamp", "cmdb_id", "name", "value",
                                      "ms", kmap, set(), start, end, san2orig=san2orig))
        app = _read_csv_cached(cache, os.path.join(mdir, "metric_app.csv"))
        series.update(_melt_wide(app, "startTime", "serviceName",
                                 {"avg_time": "avgt", "succee_rate": "sr"}, "ms", start, end,
                                 san2orig=san2orig))

    elif kind == "market":
        # container cmdb_id is "node-x.<pod>" -> keep the pod part as entity
        raw = _read_csv_cached(cache, os.path.join(mdir, "metric_container.csv"))
        series.update(_pivot_long(raw, "timestamp", "cmdb_id", "kpi_name", "value",
                                  "s", MARKET_CONTAINER_KPIS, {"cpu", "netdrop"}, start, end,
                                  entity_transform=lambda s: s.split(".", 1)[-1],
                                  san2orig=san2orig))
        raw = _read_csv_cached(cache, os.path.join(mdir, "metric_node.csv"))
        series.update(_pivot_long(raw, "timestamp", "cmdb_id", "kpi_name", "value",
                                  "s", MARKET_NODE_KPIS, set(), start, end,
                                  san2orig=san2orig))
        svc = _read_csv_cached(cache, os.path.join(mdir, "metric_service.csv"))
        series.update(_melt_wide(
            svc, "timestamp", "service", {"rr": "rr", "sr": "sr", "mrt": "mrt"}, "s", start, end,
            entity_transform=lambda s: re.sub(r"-(grpc|http|external)$", "", s),
            san2orig=san2orig))
    else:
        raise ValueError(f"unknown dataset kind: {kind}")

    return series, san2orig


def build_frame(dataset: str, ws: int, we: int, pre_minutes: int = 30,
                post_minutes: int = 10, grid_s: int = 60, cache: dict = None):
    """Build the wide KPI frame for one RCA query window.

    Returns (df, col2entity):
      df         — DataFrame with a ``time`` column (unix s, regular grid) and
                   one ``{entity}_{metric}`` column per KPI series; numeric,
                   interpolated, no NaN rows, no constant columns.
      col2entity — column name -> original entity name (record.csv naming).
    """
    cfg = DATASETS[dataset]
    kind = cfg["kind"]
    cache = cache if cache is not None else {}
    start, end = ws - pre_minutes * 60, we + post_minutes * 60
    date_str = datetime.fromtimestamp(ws, tz=TZ8).strftime("%Y_%m_%d")
    telemetry_dir = os.path.join(DATA_ROOT, cfg["root"], "telemetry", date_str)
    if not os.path.isdir(telemetry_dir):
        raise FileNotFoundError(f"telemetry dir not found: {telemetry_dir}")

    series, san2orig = collect_series(kind, telemetry_dir, start - grid_s, end + grid_s, cache)
    if not series:
        raise ValueError(f"no metric series collected for {dataset} {date_str} [{start},{end}]")

    col2entity = {}
    frame = {}
    for (entity, code), s in series.items():
        col = f"{entity}_{code}"
        col2entity[col] = san2orig.get(entity, entity)
        frame[col] = s
    df = pd.DataFrame(frame)
    df.index.name = "time"
    df = df.sort_index()
    # regular minute grid over the slice
    full_index = np.arange(_grid_floor(pd.Series([start]))[0], end + grid_s, grid_s)
    df = df.reindex(full_index)
    df = df.interpolate(method="index", limit_direction="both").ffill().bfill()
    df = df.dropna(axis=1, how="all")
    # drop constant / near-empty columns
    df = df.loc[:, df.columns[df.nunique() > 1]]
    df = df.reset_index()
    df["time"] = df["time"].astype(np.int64)
    return df, col2entity


# ---------------------------------------------------------------------------
# anomaly prefilter / SLI / inject time
# ---------------------------------------------------------------------------
def _robust_z(df: pd.DataFrame, cols, ws, we):
    baseline = df[df["time"] < ws]
    if len(baseline) < 5:
        baseline = df
    window = df[(df["time"] >= ws) & (df["time"] <= we)]
    if len(window) == 0:
        window = df
    med = baseline[cols].median()
    mad = (baseline[cols] - med).abs().median() * 1.4826
    scale = mad.replace(0, np.nan).fillna(baseline[cols].std()).fillna(1.0) + 1e-9
    z = (window[cols] - med).abs() / scale
    return z.max(axis=0)


def select_sli(df: pd.DataFrame, dataset: str, ws: int, we: int):
    """Pick the SLI column: the most anomalous column matching the dataset's SLI pattern."""
    pattern = DATASETS[dataset]["sli_pattern"]
    cands = [c for c in df.columns if c != "time" and re.match(pattern, c)]
    if not cands:
        return None
    z = _robust_z(df, cands, ws, we)
    return z.idxmax()


def prefilter_entities(df: pd.DataFrame, col2entity: dict, ws: int, we: int,
                       max_entities: int = 20, force_cols: list = None):
    """Keep only the top-N most anomalous entities (plus forced columns)."""
    cols = [c for c in df.columns if c != "time"]
    z = _robust_z(df, cols, ws, we)
    ent_score = {}
    for c in cols:
        ent_score[col2entity[c]] = max(ent_score.get(col2entity[c], 0.0), float(z[c]))
    ranked_entities = sorted(ent_score, key=ent_score.get, reverse=True)
    keep_entities = set(ranked_entities[:max_entities])
    keep = [c for c in cols if col2entity[c] in keep_entities]
    for c in (force_cols or []):
        if c in df.columns and c not in keep:
            keep.append(c)
    return df[["time"] + keep]


def detect_inject_time(df: pd.DataFrame, sli_col: str, ws: int, we: int) -> int:
    """Data-driven alert time: first minute in the window with SLI robust-z >= 3."""
    if sli_col is None or sli_col not in df.columns:
        return ws + (we - ws) // 2
    baseline = df[df["time"] < ws]
    if len(baseline) < 5:
        baseline = df
    med = baseline[sli_col].median()
    mad = (baseline[sli_col] - med).abs().median() * 1.4826
    scale = (mad if mad > 0 else baseline[sli_col].std() or 1.0) + 1e-9
    window = df[(df["time"] >= ws) & (df["time"] <= we)]
    z = (window[sli_col] - med).abs() / scale
    hits = window[z >= 3]
    return int(hits["time"].iloc[0]) if len(hits) else ws + (we - ws) // 2
