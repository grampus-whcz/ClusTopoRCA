#!/usr/bin/env python
"""Route-a end-to-end smoke: component hard-constrained to the scorer's
causal-fused top-1; the occurrence time is deterministically anchored to that
entity's first anomaly; the LLM only produces the fault reason (constrained to
the dataset vocabulary), a one-sentence propagation note, and a confidence
estimate. One LLM call/query.

Usage: python route_a_smoke.py [--n 30] [--dataset Bank] [--start 0]
"""
import argparse
import json
import os
import re
import sys

import pandas as pd
from openai import OpenAI

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import offline_scorer as osf
import openrca_data as od
import verify_smoke as vs
import verify_smoke_plus as vsp
import run_route_ab as rab

API_KEY = "cf20faf4ad594579889da7384ee285fb.7W3HPHtLNdntOyqg"
API_BASE = "https://open.bigmodel.cn/api/coding/paas/v4"
MODEL = "glm-4.7"
NEED = vs.NEED


def semantic_call(client, model, dataset, entity, reasons, ws, we, anomalies, attrs, earliest_ts):
    start_str = od.datetime.fromtimestamp(ws, od.TZ8).strftime("%Y-%m-%d %H:%M:%S")
    end_str = od.datetime.fromtimestamp(we, od.TZ8).strftime("%Y-%m-%d %H:%M:%S")
    prof = vsp.data_profile(dataset, ws, we, entity) or "    (无可用 KPI 序列)"
    ups = vsp.upstream_timing(dataset, ws, we, entity, anomalies)
    top_attrs = sorted(attrs.items(), key=lambda kv: -kv[1])[:4]
    attr_s = ", ".join(f"{a}(x{c})" for a, c in top_attrs) or "none"
    first_str = pd.to_datetime(int(earliest_ts), unit="s", utc=True) \
        .tz_convert("Asia/Shanghai").strftime("%Y-%m-%d %H:%M:%S") if earliest_ts else "未知"
    vocab = ", ".join(reasons)
    prompt = f"""Dataset fault window: {start_str} to {end_str} (UTC+8).
Root-cause component (fixed by the scorer): {entity}.
Estimated occurrence time (first anomaly of {entity}): {first_str}.
Its evidence:
- anomalies(xN): {attr_s}
- KPI 数据画像:
{prof}
- 上游邻居: {ups}

Tasks:
1. State the fault reason, which MUST be exactly one of: {vocab}.
2. Describe the likely propagation path in one sentence.
3. Rate your confidence (high / medium / low).
Respond with a JSON object only: {{"reason": "...", "propagation": "...", "confidence": "..."}}"""
    kwargs = {"model": model,
              "messages": [{"role": "system", "content": "You are a precise SRE describing a confirmed root cause."},
                           {"role": "user", "content": prompt}],
              "temperature": 0.0}
    if "glm" in str(model).lower():
        kwargs["extra_body"] = {"thinking": {"type": "disabled"}}
    r = client.chat.completions.create(**kwargs)
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
    ap.add_argument("--model", default=MODEL)
    ap.add_argument("--api-base", default=API_BASE)
    ap.add_argument("--api-key", default=API_KEY)
    args = ap.parse_args()
    dataset = args.dataset
    queries, records = od.load_queries(dataset), od.load_records(dataset)
    inventory = od.candidate_inventory(dataset)
    reasons = sorted(records["reason"].unique().tolist())
    client = OpenAI(api_key=args.api_key, base_url=args.api_base, timeout=180, max_retries=3)

    n = min(args.start + args.n, len(records))
    c = p = cov = comp_hit = 0
    details = []
    for idx in range(args.start, n):
        ws, we = od.parse_window(queries.iloc[idx]["instruction"])
        anomalies = rab.load_relaxed(dataset, ws, we)
        fused = rab.fused_rank(dataset, idx, ws, we, inventory, anomalies)
        if not fused:
            continue
        top1 = fused[0][0]
        ent_ts = [a["ts"] for a in anomalies if a["entity"] == top1 or
                  (isinstance(a["entity"], str) and top1 in a["entity"].split("->"))]
        earliest = min(ent_ts) if ent_ts else None
        attrs = {}
        for a in anomalies:
            if a["entity"] == top1 or (isinstance(a["entity"], str) and top1 in a["entity"].split("->")):
                attrs[a["attribute"]] = attrs.get(a["attribute"], 0) + 1
        try:
            ans, raw = semantic_call(client, args.model, dataset, top1, reasons, ws, we,
                                     anomalies, attrs, earliest)
        except Exception as e:
            ans, raw = None, f"ERR {e}"
        cov += 1
        gt = records.iloc[idx]
        need = NEED[queries.iloc[idx]["task_index"]]
        hits = 0
        for el in need:
            if el == "component":
                hits += int(top1 == gt["component"])
            elif el == "reason":
                hits += int((ans or {}).get("reason") == gt["reason"])
            elif el == "time":
                # deterministic first-anomaly anchor (hybrid protocol)
                if earliest:
                    hits += int(abs(earliest - float(gt["timestamp"])) <= 60)
        s = hits / len(need)
        c += int(s >= 0.999)
        p += int(0 < s < 0.999)
        comp_hit += int(top1 == gt["component"])
        details.append({"idx": idx, "gt": gt["component"], "top1": top1,
                        "reason_pred": (ans or {}).get("reason"), "score": s})
        print(f"[{idx}] gt={gt['component']:12s} top1={top1:12s} "
              f"reason={str((ans or {}).get('reason'))[:28]:28s} s={s:.2f}", flush=True)

    denom = max(n - args.start, 1)
    print(f"\n=== route-a {dataset} idx {args.start}-{n - 1} ===")
    print(f"component hit@1 = {comp_hit / denom * 100:.2f}")
    print(f"top1 C/P/T = {c / denom * 100:.2f}/{p / denom * 100:.2f}/{(c + p) / denom * 100:.2f}")
    out = os.path.join(os.path.dirname(os.path.abspath(__file__)), "results",
                       f"route_a_smoke_{dataset}_{args.start}_{n}.jsonl")
    with open(out, "w") as f:
        for d in details:
            f.write(json.dumps(d, ensure_ascii=False) + "\n")
    print("written:", out)


if __name__ == "__main__":
    main()
