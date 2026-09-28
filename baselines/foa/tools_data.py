"""
Data-collection tools for the FoA reproduction (the paper's "tool layer"
denoising: telemetry is converted to focused text before reaching the LLM).

Implemented over raw OpenRCA telemetry, following the paper's tool
contracts (Table 5 / Appendix B: rule-based anomaly detection, keyword-based
log extraction, anomalous-span collection):

    whether_is_abnormal_metric(start_time, end_time, metric) -> str
    collect_trace(start_time, end_time, entity)              -> str
    collect_logs(start_time, end_time, entity)               -> str
    get_relevant_metric(query)                               -> str

Times may be unix seconds or "YYYY-MM-DD HH:MM[:SS]" (UTC+8). The dataset
context of the current query is held in the module-level CURRENT dict set by
the runner (the paper's tools likewise assume the current incident context).
"""

import os
import re
from datetime import datetime

import numpy as np
import pandas as pd

import openrca_data as od

CURRENT = {"dataset": None}
_CACHE = {}

METRIC_KEYWORDS = {
    "cpu": {"cpu"},
    "memory": {"mem"},
    "mem": {"mem"},
    "disk": {"diskbusy", "diskio", "disk", "iowait"},
    "io": {"diskbusy", "diskio", "disk", "iowait"},
    "network": {"netinerr", "netouterr", "netutil", "netin", "netout", "netdrop", "ping"},
    "net": {"netinerr", "netouterr", "netutil", "netin", "netout", "netdrop", "ping"},
    "database": {"sess", "tps", "dbtime"},
    "db": {"sess", "tps", "dbtime"},
    "jvm": {"jvmheap", "jvmcpu"},
    "latency": {"mrt", "avgt", "sr", "rr"},
    "response": {"mrt", "avgt", "sr", "rr"},
}

METRIC_DESCRIPTIONS = {
    "cpu": "CPU utilization / usage percentage of an entity",
    "mem": "memory usage percentage of an entity",
    "diskbusy": "disk busy percentage (Bank)",
    "diskio": "disk IO utilization (Telecom node)",
    "disk": "disk space usage percentage (Market node)",
    "iowait": "CPU iowait percentage (Market node)",
    "netinerr": "network inbound error percentage (Bank)",
    "netouterr": "network outbound error percentage (Bank)",
    "netutil": "network bandwidth utilization (Bank)",
    "netin": "incoming network traffic (Telecom node)",
    "netout": "outgoing network traffic (Telecom node)",
    "netdrop": "dropped network packets (Market container)",
    "ping": "node connectivity check (Market node)",
    "sess": "database session usage percentage (Telecom db)",
    "tps": "database transactions per second (Telecom db)",
    "dbtime": "database response time (Telecom db)",
    "jvmheap": "JVM heap memory used (Bank Tomcat)",
    "jvmcpu": "JVM CPU load (Bank Tomcat)",
    "mrt": "mean response time of a service",
    "avgt": "average response time (Telecom osb entry)",
    "sr": "success rate of a service",
    "rr": "request rate of a service",
}

LOG_KEYWORDS = re.compile(
    r"error|exception|fail|timeout|timed out|refused|unavailable|panic|OOM|"
    r"out of memory|denied|unreachable|reset|broken pipe", re.I)


def _to_ts(t) -> int:
    if isinstance(t, (int, float, np.integer, np.floating)):
        return int(t)
    t = str(t).strip()
    for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%d %H:%M"):
        try:
            return int(datetime.strptime(t, fmt).replace(tzinfo=od.TZ8).timestamp())
        except ValueError:
            continue
    raise ValueError(f"cannot parse time: {t!r}")


def _dataset():
    ds = CURRENT.get("dataset")
    if ds is None:
        raise RuntimeError("CURRENT['dataset'] is not set")
    return ds


def _frame(start: int, end: int):
    return od.build_frame(_dataset(), start, end, pre_minutes=30,
                          post_minutes=0, cache=_CACHE)


def whether_is_abnormal_metric(start_time, end_time, metric) -> str:
    """Rule-based (robust z-score) anomaly check on the selected metric group."""
    start, end = _to_ts(start_time), _to_ts(end_time)
    codes = METRIC_KEYWORDS.get(str(metric).strip().lower())
    if codes is None:
        return (f"Unknown metric group '{metric}'. Available groups: "
                + ", ".join(sorted(METRIC_KEYWORDS)))
    try:
        df, col2entity = _frame(start, end)
    except Exception as e:
        return f"metric data unavailable: {e}"
    cols = [c for c in df.columns if c != "time" and c.rsplit("_", 1)[-1] in codes]
    if not cols:
        return f"no metric columns of group '{metric}' found in this dataset"
    baseline = df[df["time"] < start]
    window = df[(df["time"] >= start) & (df["time"] <= end)]
    if len(baseline) < 5 or len(window) == 0:
        return "insufficient metric data in the requested range"
    med = baseline[cols].median()
    mad = (baseline[cols] - med).abs().median() * 1.4826
    scale = mad.replace(0, np.nan).fillna(baseline[cols].std()).fillna(1.0)
    # magnitude-aware floor: avoids astronomical z-scores on near-constant baselines
    scale = pd.Series(np.maximum(scale.to_numpy(), np.abs(med.to_numpy()) * 0.01 + 1e-6),
                      index=cols)
    z = ((window[cols] - med) / scale).abs().max(axis=0).sort_values(ascending=False)
    top = z.head(10)
    lines = [f"Metric group '{metric}' anomaly check between "
             f"{datetime.fromtimestamp(start, od.TZ8):%H:%M} and {datetime.fromtimestamp(end, od.TZ8):%H:%M}:"]
    n_abn = 0
    for col, zi in top.items():
        ent = col2entity[col]
        status = "ANOMALOUS" if zi >= 5 else "normal"
        n_abn += zi >= 5
        wmax = window[col].max()
        lines.append(f"- {ent} ({col.rsplit('_', 1)[-1]}): {status}, max z-score={zi:.1f}, "
                     f"baseline median={med[col]:.3g}, window max={wmax:.3g}")
    lines.append(f"Summary: {n_abn} of the top-{len(top)} most deviated series are anomalous "
                 f"(z>=5). The most anomalous entity is {col2entity[top.index[0]]}.")
    return "\n".join(lines)


def _trace_path(start: int) -> str:
    cfg = od.DATASETS[_dataset()]
    date_str = datetime.fromtimestamp(start, od.TZ8).strftime("%Y_%m_%d")
    return os.path.join(od.DATA_ROOT, cfg["root"], "telemetry", date_str, "trace", "trace_span.csv")


def _spans_of(entity: str, start: int, end: int) -> pd.DataFrame:
    kind = od.DATASETS[_dataset()]["kind"]
    path = _trace_path(start)
    key_col = {"bank": "cmdb_id", "telecom": "cmdb_id", "market": "cmdb_id"}[kind]
    frames = []
    for chunk in pd.read_csv(path, chunksize=2_000_000):
        sub = chunk[chunk[key_col].astype(str) == entity]
        if sub.empty:
            continue
        if kind == "telecom":
            ts = sub["startTime"].astype(np.int64) // 1000
            dur = pd.to_numeric(sub["elapsedTime"], errors="coerce")
            err = sub["success"].astype(str).str.lower() != "true"
            info = sub["callType"].astype(str) + "/" + sub["dsName"].fillna("").astype(str) \
                + "/" + sub["serviceName"].fillna("").astype(str)
        elif kind == "market":
            ts = sub["timestamp"].astype(np.int64) // 1000
            dur = pd.to_numeric(sub["duration"], errors="coerce")
            err = ~sub["status_code"].astype(str).isin({"0", "Ok", "OK", "200"})
            info = sub["type"].astype(str) + "/" + sub["operation_name"].fillna("").astype(str)
        else:
            ts = sub["timestamp"].astype(np.int64) // 1000
            dur = pd.to_numeric(sub["duration"], errors="coerce")
            err = pd.Series(False, index=sub.index)
            info = sub["span_id"].astype(str)
        keep = (ts >= start) & (ts <= end)
        if keep.any():
            frames.append(pd.DataFrame({"ts": ts[keep], "dur": dur[keep],
                                        "err": err[keep], "info": info[keep]}))
    return pd.concat(frames, ignore_index=True) if frames else pd.DataFrame(columns=["ts", "dur", "err", "info"])


def collect_trace(start_time, end_time, entity) -> str:
    """Collect anomalous-span statistics for one entity as text."""
    start, end = _to_ts(start_time), _to_ts(end_time)
    entity = str(entity)
    try:
        win = _spans_of(entity, start, end)
        base = _spans_of(entity, start - 1800, start)
    except Exception as e:
        return f"trace data unavailable: {e}"
    if win.empty:
        return f"no trace spans found for entity '{entity}' in the requested range"
    calls = len(win)
    err_rate = float(win["err"].mean() * 100)
    p95 = float(win["dur"].quantile(0.95))
    mean = float(win["dur"].mean())
    lines = [f"Trace report of {entity}: {calls} spans, error rate {err_rate:.1f}%, "
             f"mean duration {mean:.1f} ms, p95 duration {p95:.1f} ms."]
    if not base.empty:
        lines.append(f"Baseline (preceding 30 min): {len(base)} spans, mean duration "
                     f"{float(base['dur'].mean()):.1f} ms, p95 {float(base['dur'].quantile(0.95)):.1f} ms, "
                     f"error rate {float(base['err'].mean() * 100):.1f}%.")
        ratio = mean / max(float(base["dur"].mean()), 1e-9)
        lines.append(f"Mean duration is {ratio:.1f}x the baseline "
                     f"({'ANOMALOUS' if ratio >= 2 or err_rate >= 5 else 'not clearly anomalous'}).")
    slow = win.nlargest(5, "dur")
    lines.append("Slowest spans (duration ms / info):")
    for _, r in slow.iterrows():
        lines.append(f"- {r['dur']:.0f} ms  {str(r['info'])[:100]}")
    return "\n".join(lines)


def collect_logs(start_time, end_time, entity) -> str:
    """Keyword-based anomalous-log extraction for one entity."""
    start, end = _to_ts(start_time), _to_ts(end_time)
    entity = str(entity)
    kind = od.DATASETS[_dataset()]["kind"]
    if kind == "telecom":
        return "No log data available for this dataset (Telecom has metrics and traces only)."
    cfg = od.DATASETS[_dataset()]
    date_str = datetime.fromtimestamp(start, od.TZ8).strftime("%Y_%m_%d")
    log_dir = os.path.join(od.DATA_ROOT, cfg["root"], "telemetry", date_str, "log")
    files = ["log_service.csv"] + (["log_proxy.csv"] if kind == "market" else [])
    hits, total = [], 0
    for fname in files:
        path = os.path.join(log_dir, fname)
        if not os.path.exists(path):
            continue
        for chunk in pd.read_csv(path, chunksize=500_000):
            sub = chunk[chunk["cmdb_id"].astype(str) == entity]
            if sub.empty:
                continue
            ts = sub["timestamp"].astype(np.int64)
            if ts.max() > 10**12:  # milliseconds
                ts = ts // 1000
            sub = sub.assign(ts=ts)
            sub = sub[(sub["ts"] >= start) & (sub["ts"] <= end)]
            if sub.empty:
                continue
            match = sub[sub["value"].astype(str).str.contains(LOG_KEYWORDS, regex=True)]
            total += len(sub)
            hits.extend(match["value"].astype(str).str.slice(0, 200).tolist()[:5])
    if total == 0:
        return f"no logs found for entity '{entity}' in the requested range"
    if not hits:
        return f"{entity}: {total} log lines in range, none matching error keywords."
    out = [f"{entity}: {total} log lines in range, {len(hits)} anomalous samples:"]
    out.extend(f"- {h}" for h in hits[:5])
    return "\n".join(out)


def get_relevant_metric(query) -> str:
    """Return canonical metric groups/codes relevant to a free-text query."""
    q = str(query).lower()
    groups = [g for g in METRIC_KEYWORDS if g in q]
    codes = [c for c, d in METRIC_DESCRIPTIONS.items()
             if any(tok in c or tok in d.lower() for tok in re.findall(r"[a-z]+", q))]
    lines = ["Relevant metric groups: " + (", ".join(sorted(set(groups))) or "(none matched; use one of: "
             + ", ".join(sorted(METRIC_KEYWORDS)) + ")")]
    for g in sorted(set(groups)) or list(METRIC_KEYWORDS)[:3]:
        lines.append(f"- group '{g}': codes {sorted(METRIC_KEYWORDS[g])}")
    if codes:
        lines.append("Related concrete metrics:")
        for c in codes[:10]:
            lines.append(f"- {c}: {METRIC_DESCRIPTIONS[c]}")
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# FoA paper Table 5 tools, offline equivalents over OpenRCA telemetry
# ---------------------------------------------------------------------------
def _classify_entities(col2entity) -> dict:
    """Map level -> entity list using the per-dataset naming conventions
    (frame columns carry sanitized names, e.g. os-001 / docker-003 / db-007)."""
    kind = od.DATASETS[_dataset()]["kind"]
    levels = {"node": set(), "pod": set(), "service": set(), "host": set()}
    for ent in set(col2entity.values()):
        if kind == "market":
            if re.fullmatch(r"node-\d+", ent):
                levels["node"].add(ent)
            elif re.search(r"-\d+$", ent):
                levels["pod"].add(ent)
            else:
                levels["service"].add(ent)
        elif kind == "telecom":
            if re.fullmatch(r"os-\d+", ent):
                levels["node"].add(ent)
            elif re.fullmatch(r"docker-\d+", ent):
                levels["pod"].add(ent)
            else:
                levels["service"].add(ent)  # db-*, redis-*
        else:  # bank
            if re.fullmatch(r"ServiceTest\d+", ent):
                levels["service"].add(ent)
            elif ent.startswith("docker"):
                levels["host"].add(ent)
            else:
                levels["pod"].add(ent)
    return {k: sorted(v) for k, v in levels.items()}


def _entity_status_report(start_time, end_time, level: str) -> str:
    """Shared implementation: rank the entities of one level by anomaly."""
    start, end = _to_ts(start_time), _to_ts(end_time)
    try:
        df, col2entity = _frame(start, end)
    except Exception as e:
        return f"metric data unavailable: {e}"
    levels = _classify_entities(col2entity)
    ents = set(levels.get(level, []))
    if level == "pod":  # pods run on hosts; include hosts' resource view too
        ents |= set(levels.get("host", []))
    cols = [c for c in df.columns if c != "time" and col2entity[c] in ents]
    if not cols:
        return f"no {level}-level metric entities found in this dataset"
    baseline = df[df["time"] < start]
    window = df[(df["time"] >= start) & (df["time"] <= end)]
    if len(baseline) < 5 or len(window) == 0:
        return "insufficient metric data in the requested range"
    med = baseline[cols].median()
    mad = (baseline[cols] - med).abs().median() * 1.4826
    scale = mad.replace(0, np.nan).fillna(baseline[cols].std()).fillna(1.0)
    # magnitude-aware floor: a near-constant baseline must not produce
    # astronomical z-scores for an ordinary step change
    scale = pd.Series(np.maximum(scale.to_numpy(), np.abs(med.to_numpy()) * 0.01 + 1e-6),
                      index=cols)
    z = ((window[cols] - med) / scale).abs().max(axis=0)
    per_ent = {}
    for c in cols:
        per_ent[col2entity[c]] = max(per_ent.get(col2entity[c], 0.0), float(z[c]))
    ranked = sorted(per_ent.items(), key=lambda kv: kv[1], reverse=True)
    lines = [f"Status of all {level}s (anomaly ranking, window "
             f"{datetime.fromtimestamp(start, od.TZ8):%H:%M}-{datetime.fromtimestamp(end, od.TZ8):%H:%M}):"]
    for ent, zi in ranked[:10]:
        worst = max((c for c in cols if col2entity[c] == ent), key=lambda c: z[c])
        lines.append(f"- {ent}: max z-score={zi:.1f} ({worst.rsplit('_', 1)[-1]}) "
                     f"{'ANOMALOUS' if zi >= 5 else 'normal'}")
    normal = sum(1 for _, zi in ranked if zi < 5)
    lines.append(f"Summary: {len(ranked) - normal} anomalous, {normal} normal out of {len(ranked)} {level}s. "
                 f"Most anomalous {level}: {ranked[0][0]}.")
    return "\n".join(lines)


def pod_analyze(start_time, end_time) -> str:
    """Analyzing all pods' status (paper Table 5)."""
    return _entity_status_report(start_time, end_time, "pod")


def node_analyze(start_time, end_time) -> str:
    """Analyzing all nodes' status (paper Table 5)."""
    return _entity_status_report(start_time, end_time, "node")


def service_analyze(start_time, end_time) -> str:
    """Analyzing all services' status (paper Table 5)."""
    return _entity_status_report(start_time, end_time, "service")


def deployment_analyze(start_time, end_time) -> str:
    return ("deployment objects are not available in the offline OpenRCA telemetry "
            "(no live Kubernetes cluster); use service_analyze instead.")


def statefulset_analyze(start_time, end_time) -> str:
    return ("statefulset objects are not available in the offline OpenRCA telemetry "
            "(no live Kubernetes cluster); use pod_analyze instead.")


def run_kubectl_command(command) -> str:
    return (f"kubectl is not available: OpenRCA provides static telemetry files, "
            f"not a live cluster (command was: {str(command)[:100]}).")


def get_all_namespace() -> str:
    return f"Namespaces: ['{_dataset()}']  (single offline dataset namespace)"
