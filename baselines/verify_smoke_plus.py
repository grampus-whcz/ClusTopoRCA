#!/usr/bin/env python
"""Plan A+ smoke: propose top-5 (causal-fused) -> data-grounded verification.

Difference from the naive verify_smoke: each candidate is verified against
its ACTUAL KPI data in the fault window (baseline vs fault-window values,
robust-z, first-anomaly minute) plus upstream-neighbor timing evidence
("can the anomaly be explained by an upstream dependency?"), instead of only
the scorer's scores.

Usage: python verify_smoke_plus.py [--n 30] [--dataset Bank] [--start 0]
"""
import argparse
import json
import os
import re
import sys

import numpy as np
import pandas as pd
from openai import OpenAI

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import offline_scorer as osf
import openrca_data as od
import verify_smoke as vs

API_KEY = "cf20faf4ad594579889da7384ee285fb.7W3HPHtLNdntOyqg"
API_BASE = "https://open.bigmodel.cn/api/coding/paas/v4"
MODEL = "glm-4.7"
W_CAUSAL = 0.7
NEED = vs.NEED
_FRAME_CACHE = {}
_TOPO = {}


def data_profile(dataset, ws, we, entity):
    """Real KPI evidence for one entity: top anomalous KPIs with baseline vs
    window stats, first-anomaly minute, overall earliest anomaly minute."""
    if dataset not in _FRAME_CACHE:
        _FRAME_CACHE[dataset] = {}
    key = (ws, we)
    if key not in _FRAME_CACHE[dataset]:
        _FRAME_CACHE[dataset][key] = od.build_frame(dataset, ws, we, pre_minutes=30, post_minutes=0)
    df, col2entity = _FRAME_CACHE[dataset][key]
    cols = [c for c in df.columns if c != "time" and col2entity.get(c) == entity]
    if not cols:
        return None
    base = df[df["time"] < ws]
    win = df[(df["time"] >= ws) & (df["time"] <= we)]
    stats = []
    for c in cols:
        b = base[c]
        med = b.median()
        mad = (b - med).abs().median() * 1.4826
        scale = mad if mad > 0 else (b.std() or 1.0)
        scale = max(scale, abs(med) * 0.01 + 1e-9)
        zmax = float((win[c] - med).abs().max() / scale) if len(win) else 0.0
        if zmax < 2:
            continue
        first_t = None
        if len(win):
            zser = (win[c] - med).abs() / scale
            hot = zser[zser >= 5]
            if len(hot):
                first_t = pd.to_datetime(int(win.loc[hot.index[0], "time"]), unit="s", utc=True) \
                    .tz_convert("Asia/Shanghai").strftime("%H:%M")
        stats.append((zmax, c, med, float(win[c].max()) if len(win) else None, first_t))
    stats.sort(reverse=True)
    lines = []
    for z, c, med, wmax, ft in stats[:3]:
        unit = f"baseline={med:.3g}, window_max={wmax:.3g}, z={z:.1f}"
        lines.append(f"    - {c.rsplit('_', 1)[-1]}: {unit}" + (f", first≥5σ at {ft}" if ft else ""))
    return "\n".join(lines) if lines else None


def upstream_timing(dataset, ws, we, entity, anomalies):
    """Earliest anomaly minute of the entity's upstream neighbors (for the
    'explained by upstream' check) using the scorer's topology graph."""
    try:
        an = anomalies
        ent_an = min((a["ts"] for a in an if a["entity"] == entity), default=None)
        ups = {}
        for a in an:
            e = a["entity"]
            if "->" in e:
                s, t = e.split("->")
                if t == entity:
                    ups[s] = min(ups.get(s, np.inf), a["ts"])
        items = []
        for u, ts in sorted(ups.items(), key=lambda kv: kv[1])[:3]:
            rel = (ts - ent_an) / 60.0 if ent_an else None
            items.append(f"{u}(首个异常 {pd.to_datetime(int(ts), unit='s', utc=True).tz_convert('Asia/Shanghai'):%H:%M}"
                         + (f", 比 {entity} 早 {rel:.1f} 分钟" if rel is not None else "") + ")")
        return "; ".join(items) if items else "无上游异常邻居"
    except Exception:
        return "上游信息不可用"


def verify_call(client, dataset, fused, res, reasons, ws, we, anomalies, inventory):
    start_str = od.datetime.fromtimestamp(ws, od.TZ8).strftime("%Y-%m-%d %H:%M:%S")
    end_str = od.datetime.fromtimestamp(we, od.TZ8).strftime("%Y-%m-%d %H:%M:%S")
    lines = [f"Dataset fault window: {start_str} to {end_str} (UTC+8).",
             "Candidates with scorer priors and raw KPI evidence:"]
    for rank, (e, fs, row) in enumerate(fused, 1):
        attrs = res["candidate_attrs"].get(e, {})
        top_attrs = sorted(attrs.items(), key=lambda kv: -kv[1])[:3]
        attr_s = ", ".join(f"{a}(x{c})" for a, c in top_attrs) or "none"
        prof = data_profile(dataset, ws, we, e) or "    (无可用 KPI 序列)"
        ups = upstream_timing(dataset, ws, we, e, anomalies)
        lines.append(f"{rank}. {e} [prior fused={fs:.2f}] earliest="
                     f"{pd.to_datetime(int(row['earliest_ts']), unit='s', utc=True).tz_convert('Asia/Shanghai'):%H:%M:%S}\n"
                     f"   anomalies(xN): {attr_s}\n"
                     f"   KPI 数据画像:\n{prof}\n"
                     f"   上游邻居: {ups}")
    vocab = ", ".join(reasons)
    prompt = "\n".join(lines) + f"""

You are verifying root cause candidates for a microservice failure. The scorer's fused value is only a prior.
Using the KPI data profiles and upstream-neighbor timing above:
1. Pick the SINGLE most likely root cause component among the {len(fused)} candidates. A true root cause typically
   (a) deviates strongly in its own KPIs, (b) starts anomalous EARLIER than its downstream dependents, and
   (c) is NOT fully explained by an upstream neighbor that turned anomalous earlier.
2. Give the root cause occurrence time (format YYYY-MM-DD HH:MM:SS), anchored to the picked entity's earliest strong anomaly.
3. Give the root cause reason, which MUST be one of: {vocab}.
Respond with a JSON object only: {{"component": "...", "occurrence_time": "...", "reason": "...", "justification": "one sentence"}}"""
    r = client.chat.completions.create(
        model=MODEL,
        messages=[{"role": "system", "content": "You are a careful SRE verifying root-cause candidates with raw monitoring data."},
                  {"role": "user", "content": prompt}],
        temperature=0.0, extra_body={"thinking": {"type": "disabled"}})
    text = r.choices[0].message.content
    m = re.search(r"\{.*\}", text or "", re.DOTALL)
    if not m:
        return None, text
    try:
        return json.loads(m.group(0)), text
    except Exception:
        return None, text


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--n", type=int, default=30)
    ap.add_argument("--dataset", default="Bank")
    ap.add_argument("--start", type=int, default=0)
    ap.add_argument("--k", type=int, default=5)
    args = ap.parse_args()
    dataset = args.dataset
    queries, records = od.load_queries(dataset), od.load_records(dataset)
    inventory = od.candidate_inventory(dataset)
    reasons = vs.REASONS[dataset]
    client = OpenAI(api_key=API_KEY, base_url=API_BASE, timeout=180, max_retries=3)

    n = min(args.start + args.n, len(records))
    c = p = cov = 0
    details = []
    for idx in range(args.start, n):
        ws, we = od.parse_window(queries.iloc[idx]["instruction"])
        fused, res = vs.topk_candidates(dataset, idx, ws, we, inventory, k=args.k)
        if not fused:
            continue
        anomalies = res.get("anomalies") or osf.LOADERS[dataset](ws, we)
        try:
            ans, raw = verify_call(client, dataset, fused, res, reasons, ws, we,
                                   anomalies, inventory)
        except Exception as e:
            ans, raw = None, f"ERR {e}"
        cov += 1
        gt = records.iloc[idx]
        need = NEED[queries.iloc[idx]["task_index"]]
        hits = 0
        comp = (ans or {}).get("component")
        for el in need:
            if el == "component":
                hits += int(comp == gt["component"])
            elif el == "reason":
                hits += int((ans or {}).get("reason") == gt["reason"])
            elif el == "time":
                try:
                    pt = pd.to_datetime(str((ans or {}).get("occurrence_time"))).timestamp()
                    hits += int(abs(pt - float(gt["timestamp"])) <= 60)
                except Exception:
                    pass
        s = hits / len(need)
        c += int(s >= 0.999)
        p += int(0 < s < 0.999)
        details.append({"idx": idx, "gt": gt["component"], "pred": comp,
                        "reason_pred": (ans or {}).get("reason"), "score": s,
                        "scorer_top1": fused[0][0], "match": int(comp == fused[0][0])})
        print(f"[{idx}] gt={gt['component']:12s} pred={str(comp):12s} s={s:.2f} "
              f"scorer_top1={fused[0][0]:12s} follow={int(comp == fused[0][0])}", flush=True)

    denom = max(n - args.start, 1)
    print(f"\n=== verify+ {dataset} idx {args.start}-{n - 1} (top-{args.k}) ===")
    print(f"top1 C/P/T = {c / denom * 100:.2f}/{p / denom * 100:.2f}/{(c + p) / denom * 100:.2f}")
    n_follow = sum(d["match"] for d in details)
    print(f"LLM 采纳打分器 top-1 比例: {n_follow}/{len(details)}")
    out = os.path.join(os.path.dirname(os.path.abspath(__file__)), "results",
                       f"verify_plus_{dataset}_{args.start}_{n}.jsonl")
    with open(out, "w") as f:
        for d in details:
            f.write(json.dumps(d, ensure_ascii=False) + "\n")
    print("written:", out)


if __name__ == "__main__":
    main()
