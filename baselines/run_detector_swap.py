#!/usr/bin/env python
"""B-3: detector-swap robustness of the ClusTopoRCA scorer.

Replaces the OmniTransfer (learned) metric-side anomaly detection with a
simple rule-based detector — per (entity, attribute) robust z-score against
the 30-minute pre-window baseline (|z| >= 5 marks an anomaly minute) — while
keeping the trace/log anomaly records (already rule-based in the pipeline).
The scorer (clustering + topological scoring) is unchanged; component
hit@1/3/5 is compared against the OmniTransfer-based w/o-LLM numbers.

Outputs: results/detector_swap.csv
"""
import os
import sys
from collections import defaultdict
from datetime import datetime

import numpy as np
import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import offline_scorer as osf
import openrca_data as od

OMNI = "/root/shared-nvme/work/timeSeries/OmniTransfer_new"
Z_THRESH = 5.0
DAY_CACHE = {}


def _minute_grid(ts):
    return (ts // 60) * 60


def load_metric_series(dataset, date_str):
    """-> {(entity, attr, typ): pd.Series(minute -> value)} for one day."""
    key = (dataset, date_str)
    if key in DAY_CACHE:
        return DAY_CACHE[key]
    cfg = od.DATASETS[dataset]
    kind = cfg["kind"]
    root = os.path.join(od.DATA_ROOT, cfg["root"], "telemetry", date_str, "metric")
    out = {}

    def add_long(path, typ, ts_unit="s"):
        if not os.path.exists(path):
            return
        for chunk in pd.read_csv(path, chunksize=1_500_000):
            ts = chunk["timestamp"].astype(np.int64)
            if ts_unit == "ms":
                ts = ts // 1000
            sub = pd.DataFrame({
                "ts": _minute_grid(ts).values,
                "entity": chunk["cmdb_id"].astype(str).values,
                "attr": chunk["kpi_name" if "kpi_name" in chunk else "name"].astype(str).values,
                "val": pd.to_numeric(chunk["value"], errors="coerce").values,
            }).dropna(subset=["val"])
            for (ent, attr), g in sub.groupby(["entity", "attr"]):
                s = g.groupby("ts")["val"].mean()
                k = (ent, attr, typ)
                out[k] = s if k not in out else pd.concat([out[k], s]).groupby(level=0).mean()

    if kind == "bank":
        add_long(os.path.join(root, "metric_container.csv"), "metric_container")
        app = os.path.join(root, "metric_app.csv")
        if os.path.exists(app):
            df = pd.read_csv(app)
            for col in ["rr", "sr", "cnt", "mrt"]:
                for ent, g in df.groupby(df["tc"].astype(str)):
                    out[(ent, col, "metric_app")] = g.groupby(_minute_grid(g["timestamp"].astype(np.int64)))[col].mean()
    elif kind == "telecom":
        for f in ["metric_container.csv", "metric_middleware.csv", "metric_node.csv", "metric_service.csv"]:
            add_long(os.path.join(root, f), "metric_A", ts_unit="ms")
        app = os.path.join(root, "metric_app.csv")
        if os.path.exists(app):
            df = pd.read_csv(app)
            for col in ["avg_time", "num", "succee_rate"]:
                if col in df:
                    for ent, g in df.groupby(df["serviceName"].astype(str)):
                        out[(ent, col, "metric_A")] = g.groupby(_minute_grid(g["startTime"].astype(np.int64) // 1000))[col].mean()
    else:  # market
        for f, typ in [("metric_container.csv", "metric_container"), ("metric_node.csv", "metric_node"),
                       ("metric_mesh.csv", "metric_mesh"), ("metric_runtime.csv", "metric_runtime")]:
            path = os.path.join(root, f)
            if not os.path.exists(path):
                continue
            for chunk in pd.read_csv(path, chunksize=1_500_000):
                ts = _minute_grid(chunk["timestamp"].astype(np.int64))
                ent = chunk["cmdb_id"].astype(str)
                if typ == "metric_container":  # node-x.pod -> pod
                    ent = ent.str.split(".", n=1).str[-1]
                sub = pd.DataFrame({"ts": ts.values, "entity": ent.values,
                                    "attr": chunk["kpi_name"].astype(str).values,
                                    "val": pd.to_numeric(chunk["value"], errors="coerce").values}).dropna(subset=["val"])
                for (e, a), g in sub.groupby(["entity", "attr"]):
                    s = g.groupby("ts")["val"].mean()
                    k = (e, a, typ)
                    out[k] = s if k not in out else pd.concat([out[k], s]).groupby(level=0).mean()
        svc = os.path.join(root, "metric_service.csv")
        if os.path.exists(svc):
            df = pd.read_csv(svc)
            df["service"] = df["service"].astype(str).str.replace(r"-(grpc|http|external)$", "", regex=True)
            for col in ["rr", "sr", "mrt", "count"]:
                for ent, g in df.groupby("service"):
                    out[(ent, col, "metric_service")] = g.groupby(_minute_grid(g["timestamp"].astype(np.int64)))[col].mean()

    DAY_CACHE[key] = out
    return out


def simple_detector_records(dataset, ws, we):
    """Robust-z per (entity, attr) minute series -> anomaly records."""
    date_str = datetime.fromtimestamp(ws, od.TZ8).strftime("%Y_%m_%d")
    series = load_metric_series(dataset, date_str)
    records = []
    for (ent, attr, typ), s in series.items():
        base = s[(s.index >= ws - 1800) & (s.index < ws)]
        win = s[(s.index >= ws) & (s.index <= we)]
        if len(base) < 5 or win.empty:
            continue
        med = base.median()
        mad = (base - med).abs().median() * 1.4826
        scale = mad if mad > 0 else (base.std() or 0.0)
        if not np.isfinite(scale) or scale <= max(abs(med) * 1e-4, 1e-9):
            continue
        z = (win - med).abs() / scale
        for t in z[z >= Z_THRESH].index:
            records.append({"ts": int(t), "type": typ, "entity": ent,
                            "attribute": attr, "raw": ""})
    return records


def cached_trace_log_records(dataset, ws, we):
    """Trace/log records from the existing pipeline caches (rule-based there)."""
    date_str = datetime.fromtimestamp(ws, od.TZ8).strftime("%Y_%m_%d")
    suffix = datetime.fromtimestamp(ws, od.TZ8).strftime("%H%M") + "_" + \
             datetime.fromtimestamp(we, od.TZ8).strftime("%H%M")
    recs = []
    def load(base, typ, fname):
        path = os.path.join(base, fname)
        if not os.path.exists(path):
            return
        data = np.load(path, allow_pickle=True)
        for item in data:
            if typ == "log":
                pod, pattern_id, template, ts = item
                recs.append({"ts": int(ts), "type": "log", "entity": str(pod),
                             "attribute": f"PatternID_{pattern_id}", "raw": str(template)})
            else:
                entity, attr, ts = str(item[0]), str(item[1]), int(item[2])
                if "->" in entity:
                    s, t = entity.split("->")
                    recs.append({"ts": ts, "type": "trace", "entity": s,
                                 "attribute": f"trace_{attr}", "raw": entity})
                    recs.append({"ts": ts, "type": "trace", "entity": t,
                                 "attribute": f"trace_{attr}", "raw": entity})
                else:
                    recs.append({"ts": ts, "type": typ, "entity": entity,
                                 "attribute": attr if typ != "trace" else f"trace_{attr}",
                                 "raw": entity if typ == "trace" else ""})
    if dataset == "Bank":
        base = os.path.join(OMNI, osf.ARTIFACT_DIR["Bank"])
        load(base, "trace", f"Bank_trace_anomalies_{date_str}_{suffix}.npy")
        load(base, "log", f"Bank_log_anomalies_{date_str}_{suffix}.npy")
    elif dataset == "Telecom":
        base = os.path.join(OMNI, osf.ARTIFACT_DIR["Telecom"])
        load(base, "trace", f"Telecom_trace_anomalies_{date_str}_{suffix}.npy")
    else:  # market: full-day caches
        day = osf._market_day_anomalies(date_str)
        recs = [a for a in day if a["type"] in ("trace", "log") and ws <= a["ts"] < we]
    return recs


def main():
    import csv
    rows = []
    for dataset in ["Bank", "Telecom", "Market-1", "Market-2"]:
        queries, records = od.load_queries(dataset), od.load_records(dataset)
        inventory = od.candidate_inventory(dataset)
        n = len(records)
        h1 = h3 = h5 = 0
        for idx in range(n):
            ws, we = od.parse_window(queries.iloc[idx]["instruction"])
            gt = records.iloc[idx]["component"]
            recs = simple_detector_records(dataset, ws, we) + cached_trace_log_records(dataset, ws, we)
            try:
                res = osf.score_anomalies(dataset, recs)
                ranked_raw = res["ranked_raw"]
                seen, ranked = set(), []
                for raw in ranked_raw:
                    c = osf.map_to_inventory(raw, inventory)
                    if c and c not in seen:
                        seen.add(c)
                        ranked.append(c)
            except Exception as e:
                ranked = []
            r = ranked.index(gt) + 1 if gt in ranked else None
            h1 += int(r == 1); h3 += int(r is not None and r <= 3); h5 += int(r is not None and r <= 5)
            if (idx + 1) % 20 == 0:
                print(f"{dataset} {idx + 1}/{n} hit@1={h1 / (idx + 1):.3f}", flush=True)
        rows.append({"dataset": dataset, "n": n,
                     "hit@1_simple": round(h1 / n, 4), "hit@3_simple": round(h3 / n, 4),
                     "hit@5_simple": round(h5 / n, 4)})
        print(dataset, rows[-1], flush=True)
    ref = {"Bank": (0.0956, 0.2794, 0.5368), "Telecom": (0.2157, 0.2745, 0.4118),
           "Market-1": (0.0, 0.0286, 0.0571), "Market-2": (0.1282, 0.1923, 0.2308)}
    print("\n=== 对比（simple vs OmniTransfer-based wo_llm）===")
    for r in rows:
        rf = ref[r["dataset"]]
        print(f"{r['dataset']:9s} simple {r['hit@1_simple']}/{r['hit@3_simple']}/{r['hit@5_simple']}  vs  omnitransfer {rf[0]}/{rf[1]}/{rf[2]}")
    out = os.path.join(os.path.dirname(os.path.abspath(__file__)), "results", "detector_swap.csv")
    with open(out, "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0].keys()))
        w.writeheader()
        w.writerows(rows)
    print("written:", out)


if __name__ == "__main__":
    main()
