"""
Build the three mABC input files from raw OpenRCA trace telemetry:

    data_files/{dataset}/endpoint_stats.json   {endpoint: {minute: {calls, success_rate,
                                                error_rate, average_duration, timeout_rate}}}
    data_files/{dataset}/endpoint_maps.json    {endpoint: {minute: [downstream endpoints]}}
    data_files/{dataset}/label.json            {fault_minute: {alert_endpoint: [timeout paths]}}
    data_files/{dataset}/label_index.json      [{idx, time, alert_endpoint, gt_component}]

Entity universe (trace-visible entities only, see baselines/README):
  * Bank    : trace cmdb_id            (Tomcat01-04, MG01/02, IG01/02, dockerA/B hosts)
  * Telecom : span cmdb_id (docker_*) plus dsName (db_*) for JDBC spans
  * Market  : trace cmdb_id            (all pods)

Only minutes covered by some query window (+ margin) are materialized, so the
multi-GB daily trace files are scanned in chunks and filtered early.

Timeout rule: a span counts as timeout when its duration >= the entity's p95
duration over the processed spans of that day (the original code hardcoded
100 ms, which is meaningless across these datasets).
"""

import argparse
import json
import os
import sys
from collections import defaultdict

import numpy as np
import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import openrca_data as od  # noqa: E402

HERE = os.path.dirname(os.path.abspath(__file__))
TZ = od.TZ8
MIN_CALLS_FOR_ALERT = 5

# minutes of context around each query window that must be materialized
PRE_S, POST_S = 20 * 60, 10 * 60


# ---------------------------------------------------------------------------
# per-dataset span normalization
# ---------------------------------------------------------------------------
def normalize_spans(kind: str, raw: pd.DataFrame) -> pd.DataFrame:
    """Return a DataFrame with columns [ts(s), entity, parent_key, key, trace, dur(ms), error]."""
    if kind == "bank":
        df = pd.DataFrame({
            "ts": raw["timestamp"].astype(np.int64) // 1000,
            "entity": raw["cmdb_id"].fillna("").astype(str),
            "parent_key": raw["parent_id"].fillna("").astype(str),
            "key": raw["span_id"].fillna("").astype(str),
            "trace": raw["trace_id"].fillna("").astype(str),
            "dur": pd.to_numeric(raw["duration"], errors="coerce"),
            "error": False,
        })
    elif kind == "telecom":
        # pandas>=3 str dtype keeps NaN as missing (not "nan"): fill first
        ds = raw["dsName"].fillna("").astype(str)
        is_jdbc = raw["callType"].astype(str).eq("JDBC") & ds.ne("")
        entity = pd.Series(np.where(is_jdbc, ds, raw["cmdb_id"].fillna("").astype(str)),
                           index=raw.index).fillna("").astype(str)
        df = pd.DataFrame({
            "ts": raw["startTime"].astype(np.int64) // 1000,
            "entity": entity,
            "parent_key": raw["pid"].fillna("").astype(str),
            "key": raw["id"].fillna("").astype(str),
            "trace": raw["traceId"].fillna("").astype(str),
            "dur": pd.to_numeric(raw["elapsedTime"], errors="coerce"),
            "error": raw["success"].astype(str).str.lower() != "true",
        })
    elif kind == "market":
        ok_status = {"0", "Ok", "OK", "200"}
        df = pd.DataFrame({
            "ts": raw["timestamp"].astype(np.int64) // 1000,
            "entity": raw["cmdb_id"].fillna("").astype(str),
            "parent_key": raw["parent_span"].fillna("").astype(str),
            "key": raw["span_id"].fillna("").astype(str),
            "trace": raw["trace_id"].fillna("").astype(str),
            "dur": pd.to_numeric(raw["duration"], errors="coerce"),
            "error": ~raw["status_code"].astype(str).isin(ok_status),
        })
    else:
        raise ValueError(kind)
    return df.dropna(subset=["dur"]).query("entity != ''")


def load_spans(dataset: str, intervals_by_date, cache_dir=None) -> pd.DataFrame:
    """Scan the daily trace CSVs in chunks, keep only spans inside needed intervals."""
    cfg = od.DATASETS[dataset]
    kind = cfg["kind"]
    frames = []
    for date_str, intervals in intervals_by_date.items():
        path = os.path.join(od.DATA_ROOT, cfg["root"], "telemetry", date_str, "trace", "trace_span.csv")
        if not os.path.exists(path):
            print(f"[warn] missing trace file: {path}")
            continue
        for chunk in pd.read_csv(path, chunksize=2_000_000):
            norm = normalize_spans(kind, chunk)
            if norm.empty:
                continue
            mask = np.zeros(len(norm), dtype=bool)
            ts = norm["ts"].to_numpy()
            for a, b in intervals:
                mask |= (ts >= a) & (ts <= b)
            if mask.any():
                frames.append(norm[mask])
        print(f"  {dataset} {date_str}: collected {sum(len(f) for f in frames)} spans so far")
    if not frames:
        raise ValueError(f"no spans collected for {dataset}")
    return pd.concat(frames, ignore_index=True)


# ---------------------------------------------------------------------------
# aggregation
# ---------------------------------------------------------------------------
def minute_str(ts_s) -> str:
    return pd.to_datetime(np.int64(ts_s), unit="s", utc=True).tz_convert("Asia/Shanghai").strftime("%Y-%m-%d %H:%M:00")


def build_stats_and_maps(spans: pd.DataFrame):
    thresholds = spans.groupby("entity")["dur"].quantile(0.95).to_dict()
    spans = spans.assign(
        timeout=[d >= thresholds.get(e, np.inf) for e, d in zip(spans["entity"], spans["dur"])],
        minute=[minute_str(t) for t in spans["ts"]],
    )

    # endpoint_stats.json
    stats = defaultdict(dict)
    for (entity, minute), g in spans.groupby(["entity", "minute"]):
        calls = len(g)
        errors = int(g["error"].sum())
        timeouts = int(g["timeout"].sum())
        stats[entity][minute] = {
            "calls": calls,
            "success_rate": round((1 - errors / calls) * 100, 2),
            "error_rate": round(errors / calls * 100, 2),
            "average_duration": round(float(g["dur"].mean()), 2),
            "timeout_rate": round(timeouts / calls * 100, 2),
        }

    # endpoint_maps.json (child entity = downstream of parent span's entity)
    maps = defaultdict(lambda: defaultdict(set))
    for trace, g in spans.groupby("trace"):
        key2entity = dict(zip(g["key"], g["entity"]))
        for parent_key, entity, minute in zip(g["parent_key"], g["entity"], g["minute"]):
            parent_entity = key2entity.get(parent_key, "None")
            maps[str(parent_entity)][minute].add(str(entity))
    maps = {e: {m: sorted(v) for m, v in minutes.items()} for e, minutes in maps.items()}
    return stats, maps, thresholds


def build_label(dataset: str, spans: pd.DataFrame, stats, thresholds, maps=None):
    """One label entry per OpenRCA query; aligned to record.csv row order."""
    records = od.load_records(dataset)
    queries = od.load_queries(dataset)
    label, index = {}, []
    spans = spans.assign(minute=[minute_str(t) for t in spans["ts"]])

    for idx in range(len(records)):
        ws, we = od.parse_window(queries.iloc[idx]["instruction"])
        gt = records.iloc[idx]
        fault_minute = minute_str(int(gt["timestamp"]) // 60 * 60)

        win = spans[(spans["ts"] >= ws) & (spans["ts"] <= we)]
        # alert endpoint: prefer trace-root entities (maps["None"], i.e. the
        # system entries, as in mABC where alerts fire on the top endpoint);
        # among entities with enough traffic pick the worst timeout_rate.
        root_entities = set()
        if maps:
            for mm, ents in maps.get("None", {}).items():
                root_entities.update(ents)
        cand_stats = []
        for entity, minutes in stats.items():
            st = minutes.get(fault_minute) or minutes.get(minute_str(ws)) or {}
            if st.get("calls", 0) >= MIN_CALLS_FOR_ALERT:
                cand_stats.append((entity, st["timeout_rate"], st["calls"], st["average_duration"]))
        root_cands = [c for c in cand_stats if c[0] in root_entities]
        pool = root_cands if root_cands else cand_stats
        if pool:
            pool.sort(key=lambda x: (x[1], x[2]), reverse=True)
            alert_endpoint = pool[0][0]
        elif not win.empty:
            alert_endpoint = win.groupby("entity")["dur"].count().idxmax()
        else:
            alert_endpoint = "unknown"

        # timeout paths (unused by the agent, kept for faithfulness/debug)
        paths = set()
        for trace, g in win.groupby("trace"):
            g = g.sort_values("ts")
            seq = [e for e, d in zip(g["entity"], g["dur"])
                   if d >= thresholds.get(e, np.inf)]
            if len(seq) >= 1:
                dedup = [seq[0]] + [e for e, p in zip(seq[1:], seq) if e != p]
                paths.add(tuple(dedup[:8]))
        by_head = defaultdict(list)
        for p in sorted(paths):
            by_head[p[0]].append(list(p))
        if alert_endpoint not in by_head:
            by_head[alert_endpoint] = []
        label.setdefault(fault_minute, {})
        # merge if the same minute hosts several queries
        label[fault_minute].setdefault(alert_endpoint, [])
        for p in paths:
            if list(p) not in label[fault_minute][alert_endpoint]:
                label[fault_minute][alert_endpoint].append(list(p))
        label[fault_minute][alert_endpoint] = label[fault_minute][alert_endpoint][:50]

        index.append({"idx": int(idx), "time": fault_minute,
                      "alert_endpoint": alert_endpoint,
                      "gt_component": gt["component"], "gt_level": gt["level"],
                      "gt_reason": gt["reason"], "gt_time": int(gt["timestamp"]),
                      "window": [ws, we]})
    return label, index


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--dataset", required=True, choices=list(od.DATASETS))
    args = ap.parse_args()
    dataset = args.dataset
    out_dir = os.path.join(HERE, "data_files", dataset)
    os.makedirs(out_dir, exist_ok=True)

    records, queries = od.load_records(dataset), od.load_queries(dataset)
    intervals_by_date = defaultdict(list)
    for idx in range(len(records)):
        ws, we = od.parse_window(queries.iloc[idx]["instruction"])
        date_str = od.datetime.fromtimestamp(ws, tz=TZ).strftime("%Y_%m_%d")
        intervals_by_date[date_str].append((ws - PRE_S, we + POST_S))
        # cross-midnight windows also need the next day
        end_date = od.datetime.fromtimestamp(we + POST_S, tz=TZ).strftime("%Y_%m_%d")
        if end_date != date_str:
            intervals_by_date[end_date].append((ws - PRE_S, we + POST_S))

    print(f"[build_data] {dataset}: scanning traces for {len(intervals_by_date)} date(s)...")
    spans = load_spans(dataset, intervals_by_date)
    print(f"[build_data] {dataset}: {len(spans)} spans, aggregating...")
    stats, maps, thresholds = build_stats_and_maps(spans)
    label, index = build_label(dataset, spans, stats, thresholds, maps)

    for name, obj in [("endpoint_stats.json", stats), ("endpoint_maps.json", maps),
                      ("label.json", label), ("label_index.json", index)]:
        with open(os.path.join(out_dir, name), "w") as f:
            json.dump(obj, f)
        print(f"[build_data] wrote {out_dir}/{name}")


if __name__ == "__main__":
    main()
