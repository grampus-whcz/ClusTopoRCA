#!/usr/bin/env python
"""Plan A smoke: propose-verify. Scorer proposes top-3 (causal-fused),
LLM verifies each candidate against its evidence and picks the top-1 root
cause (with occurrence time and reason). Compared against:
  * plain pipeline top-1 (v2 logs, same query subset);
  * scorer-fused top-1 (component only).
Usage: python verify_smoke.py [--n 30] [--dataset Bank]
"""
import argparse
import json
import os
import re
import sys
import time

import pandas as pd
from openai import OpenAI

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import offline_scorer as osf
import openrca_data as od

API_KEY = "cf20faf4ad594579889da7384ee285fb.7W3HPHtLNdntOyqg"
API_BASE = "https://open.bigmodel.cn/api/coding/paas/v4"
MODEL = "glm-4.7"
W_CAUSAL = 0.7

NEED = {"task_1": ["time"], "task_2": ["reason"], "task_3": ["component"],
        "task_4": ["time", "reason"], "task_5": ["time", "component"],
        "task_6": ["component", "reason"], "task_7": ["time", "component", "reason"]}
REASONS = {"Bank": ["high CPU usage", "high memory usage", "network latency",
                    "network packet loss", "high disk I/O read usage",
                    "high disk space usage", "high JVM CPU load",
                    "JVM Out of Memory (OOM) Heap"]}

_SCORE_CACHE = {}


def load_rht_scores(dataset, idx):
    if dataset not in _SCORE_CACHE:
        _SCORE_CACHE[dataset] = {}
        path = f"results/score_cache/{dataset}.jsonl"
        for line in open(path):
            r = json.loads(line)
            _SCORE_CACHE[dataset][r["idx"]] = r.get("rht_scores") or {}
    return _SCORE_CACHE[dataset].get(idx, {})


def topk_candidates(dataset, idx, ws, we, inventory, k=3):
    """Fuse base scorer rows with cached RHT scores -> top-k fused candidates."""
    res = osf.rank_candidates(dataset, ws, we, inventory)
    rht = load_rht_scores(dataset, idx)
    ents = list(res["candidate_rows"].keys())
    if not ents:
        return [], res
    vals = [float(rht.get(e, 0.0)) for e in ents]
    v_min, v_max = (min(vals), max(vals)) if vals else (0, 0)
    norm = {e: ((float(rht.get(e, 0.0)) - v_min) / (v_max - v_min) if v_max > v_min else 0.0)
            for e in ents}
    w = {"Bank": (0.3, 0.4, 0.3), "Telecom": (0.025, 0.025, 0.95),
         "Market-1": (0.1, 0.8, 0.1), "Market-2": (0.1, 0.8, 0.1)}[dataset]
    fused = []
    for e in ents:
        row = res["candidate_rows"][e]
        base = (w[0] * row["time_score"] + w[1] * row["topology_score"]
                + w[2] * row["count_score"])
        cw = row.get("component_weight", 1.0)
        fused.append((e, (base + W_CAUSAL * norm[e]) / (1 + W_CAUSAL) * cw, row))
    fused.sort(key=lambda x: -x[1])
    return fused[:k], res


def verify_call(client, dataset, qrow, fused, res, reasons, start_str, end_str):
    lines = [f"Dataset fault window: {start_str} to {end_str} (UTC+8).",
             "Candidates (ranked by a quantitative scorer; scores in [0,1] where higher is more suspicious):"]
    for rank, (e, fs, row) in enumerate(fused, 1):
        attrs = res["candidate_attrs"].get(e, {})
        top_attrs = sorted(attrs.items(), key=lambda kv: -kv[1])[:4]
        attr_s = ", ".join(f"{a}(x{c})" for a, c in top_attrs) or "none"
        lines.append(
            f"{rank}. {e}: fused={fs:.2f}, time={row['time_score']:.2f}, "
            f"topology={row['topology_score']:.2f}, count={row['count_score']:.2f}, "
            f"anomalies={row.get('count', '?')}, earliest={pd.to_datetime(int(row['earliest_ts']), unit='s', utc=True).tz_convert('Asia/Shanghai'):%Y-%m-%d %H:%M:%S}, "
            f"top attributes: {attr_s}")
    evidence = "\n".join(lines)
    vocab = ", ".join(reasons)
    prompt = f"""{evidence}

You are verifying root cause candidates for a microservice failure. Using ONLY the evidence above:
1. Pick the SINGLE most likely root cause component among the {len(fused)} candidates. Prefer the entity whose anomalies start earliest and cannot be explained by an upstream dependency; treat the fused score as a prior, not a verdict.
2. Give the root cause occurrence time (within the fault window, format YYYY-MM-DD HH:MM:SS), anchored to the picked entity's earliest anomaly when consistent.
3. Give the root cause reason, which MUST be one of: {vocab}.
Respond with a JSON object only: {{"component": "...", "occurrence_time": "...", "reason": "...", "justification": "one sentence"}}"""
    r = client.chat.completions.create(
        model=MODEL,
        messages=[{"role": "system", "content": "You are a careful SRE verifying root-cause candidates."},
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
    args = ap.parse_args()
    dataset = args.dataset
    queries, records = od.load_queries(dataset), od.load_records(dataset)
    inventory = od.candidate_inventory(dataset)
    reasons = REASONS[dataset]
    client = OpenAI(api_key=API_KEY, base_url=API_BASE, timeout=180, max_retries=3)

    n = min(args.start + args.n, len(records))
    c = p = cov = 0
    details = []
    for idx in range(args.start, n):
        ws, we = od.parse_window(queries.iloc[idx]["instruction"])
        fused, res = topk_candidates(dataset, idx, ws, we, inventory)
        if not fused:
            continue
        start_str = od.datetime.fromtimestamp(ws, od.TZ8).strftime("%Y-%m-%d %H:%M:%S")
        end_str = od.datetime.fromtimestamp(we, od.TZ8).strftime("%Y-%m-%d %H:%M:%S")
        try:
            ans, raw = verify_call(client, dataset, queries.iloc[idx], fused, res,
                                   reasons, start_str, end_str)
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
    print(f"\n=== verify-smoke {dataset} idx {args.start}-{n - 1} ===")
    print(f"top1 C/P/T = {c / denom * 100:.2f}/{p / denom * 100:.2f}/{(c + p) / denom * 100:.2f}")
    n_follow = sum(d["match"] for d in details)
    print(f"LLM 采纳打分器 top-1 比例: {n_follow}/{len(details)}")
    out = os.path.join(os.path.dirname(os.path.abspath(__file__)), "results",
                       f"verify_smoke_{dataset}_{args.start}_{n}.jsonl")
    with open(out, "w") as f:
        for d in details:
            f.write(json.dumps(d, ensure_ascii=False) + "\n")
    print("written:", out)


if __name__ == "__main__":
    main()
