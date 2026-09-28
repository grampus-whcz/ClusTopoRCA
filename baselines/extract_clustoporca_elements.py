#!/usr/bin/env python
"""Per-element (time / component / reason) accuracy of ClusTopoRCA (and the
partial RCA-agent baseline logs), decomposed from the same experiment logs
parsed by extract_clustoporca_component.py.

Motivation: answer the reviewer concern that the LLM contribution is unclear.
ClusTopoRCA's topological stage ranks *components*; the "root cause occurrence
datetime" and "root cause reason" fields of every candidate are produced
solely by the LLM synthesis stage.  This script therefore scores each of the
three elements separately.

Per query x model, every candidate of the Prediction JSON contributes
    ("root cause occurrence datetime", "root cause component",
     "root cause reason", "Suspicious score").
Candidates are ordered by suspicious score desc, ties by candidate order
(identical to extract_clustoporca_component.py, which was validated against
the runs' own Passed/Failed Criteria lines).

Hit rules (mirroring main/evaluate_multi_candidate.py + the OpenRCA scorer):
  time      : |predicted - GT datetime| <= 60 s; both parsed as
              "%Y-%m-%d %H:%M:%S"; unparseable prediction = miss (same as the
              official time_difference(), which returns False on parse error)
  component : exact string match
  reason    : exact string match (GT from record.csv; near-misses that differ
              only by case/whitespace are counted and reported, never matched)
  all_three : one candidate hits time+component+reason simultaneously — the
              counterpart of OpenRCA "Correct" for fully-specified tasks.

For each element two metrics are reported:
  strict    : the best (top-ranked) candidate hits
  any       : any candidate hits (multi-candidate analogue of the paper's
              Correct rule)
on subsets all / heldout (EXCLUDED_TASK_IDS of
experiments/8.get_all_result_from_tasks_info_all_task_type.py removed).

GT: record.csv rows are 1:1 with query.csv rows (query_idx = row number).
Telecom/Market column orders differ and are normalised via pandas column
names (record.csv always has level/component/reason/timestamp/datetime).

Outputs
-------
baselines/results/clustoporca_element_predictions.csv  (per-query records)
baselines/results/clustoporca_element_accuracy.csv     (long summary:
    method, dataset, model, subset, element, metric, n, value)

Usage:
    /root/shared-nvme/.conda/envs/RCAEval_py3.12/bin/python \
        extract_clustoporca_elements.py [--no-rca-agent]
"""

import argparse
import glob
import json
import os
import re
from datetime import datetime

import pandas as pd

OPENRCA_ROOT = os.environ.get("OPENRCA_ROOT", "/root/shared-nvme/work/agent/OpenRCA")
DATA_ROOT = os.environ.get("OPENRCA_DATA", "/root/shared-nvme/data_set/OpenRCA")
EXP_DIR = os.path.join(OPENRCA_ROOT, "experiments")
RESULT_DIR = os.path.join(OPENRCA_ROOT, "result")
OUT_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "results")

# ---------------------------------------------------------------------------
# Dataset registry (identical to extract_clustoporca_component.py)
# ---------------------------------------------------------------------------
DATASETS = {
    "Bank":    ("Bank",    "Bank",             "Bank/record.csv"),
    "Telecom": ("Telecom", "Telecom",          "Telecom/record.csv"),
    "Market-1": ("Market", "Market_cloudbed-1", "Market/cloudbed-1/record.csv"),
    "Market-2": ("Market", "Market_cloudbed-2", "Market/cloudbed-2/record.csv"),
}

EXCLUDED_TASK_IDS = {
    "Bank": [51, 48, 112, 71, 88, 70, 68, 72, 86, 47, 45, 65, 53, 52, 57,
             54, 62, 60, 133, 0, 1, 2, 107, 8, 3, 13, 16, 9, 12, 6],
    "Market-1": [0, 2, 4, 5, 6, 7, 8, 9, 12, 13, 14, 16, 20, 21, 23, 27,
                 29, 30, 31, 33, 49, 56],
    "Market-2": [],
    "Telecom": [2, 5, 8, 12, 17],
}

PAPER_MODELS = [
    "gpt-4o",
    "gemini-2.5-pro-preview-p",
    "deepseek-r1-0528",
    "qwen3-235b-a22b-instruct-2507",
    "glm-4.7",
]
EXTRA_MODELS = ["glm-4.5", "glm-4.6"]

C3 = "no_RAG_c3_knowledge_graph_advanced_merged"
C4 = "no_RAG_c4_knowledge_graph_advanced_merged"
MKT_CFG2 = "no_RAG_c3_knowledge_graph_advanced_merged_hyperpara_config2"

CLUSTOPO_RUNS = []
for _m in PAPER_MODELS + EXTRA_MODELS:
    CLUSTOPO_RUNS.append(("Bank", _m, C4 if _m == "glm-4.7" else C3))
    CLUSTOPO_RUNS.append(("Telecom", _m, C3))
    CLUSTOPO_RUNS.append(("Market-1", _m, MKT_CFG2))
    CLUSTOPO_RUNS.append(("Market-2", _m, MKT_CFG2))

# ---------------------------------------------------------------------------
# Log parsing
# ---------------------------------------------------------------------------
ANSI_RE = re.compile(r"\x1b\[[0-9;]*m|\033\[[0-9;]*m")
TASK_HEADER_RE = re.compile(
    r"^(\d{4}-\d{2}-\d{2}_\d{2}-\d{2}-\d{2})_#(\d+)-(\d+):\s*task_(\d+)\s*$")
GT_LINE_RE = re.compile(r"groundtruth:\s*(.*)$")
GT_COMPONENT_RE = re.compile(
    r"component:\s*(.*?)\s*(?=(?:timestamp|reason|datetime|level):|$)")
DATASET_LINE_RE = re.compile(r"Using dataset:\s*(\S+)")
MODEL_LINE_RE = re.compile(r"Using model:\s*(.+)")
RCA_AGENT_MODULE_RE = re.compile(r"rca\.baseline\.rca_agent\.")
TIME_FMT = "%Y-%m-%d %H:%M:%S"


def strip_ansi(text):
    return ANSI_RE.sub("", text)


def extract_json_after_marker(text, markers):
    pos = -1
    for mk in markers:
        p = text.rfind(mk)
        if p > pos:
            pos = p
    if pos < 0:
        return None, "no-marker"
    brace = text.find("{", pos)
    if brace < 0:
        return None, "no-json-brace"
    try:
        obj, _ = json.JSONDecoder().raw_decode(text[brace:])
        return obj, None
    except json.JSONDecodeError as e:
        return None, f"json-error: {e}"


def candidates_from_prediction(pred):
    """Prediction dict -> ordered candidate list of dicts with
    key/component/time/reason/score.  Ordered by suspicious score desc,
    ties keep candidate order (runner emits candidates best-first)."""
    cands = []
    if not isinstance(pred, dict):
        return cands
    for order, (k, v) in enumerate(pred.items()):
        if not isinstance(v, dict):
            continue
        def _s(field):
            val = v.get(field)
            if val is not None and not isinstance(val, str):
                val = str(val)
            return val
        try:
            score = float(v.get("Suspicious score", 0.0))
        except (TypeError, ValueError):
            score = 0.0
        cands.append({
            "order": order,
            "key": k,
            "component": _s("root cause component"),
            "time": _s("root cause occurrence datetime"),
            "reason": _s("root cause reason"),
            "score": score,
        })
    cands.sort(key=lambda c: (-c["score"], c["order"]))
    return cands


def passed_criteria_union(text):
    """Union of all 'Passed Criteria' lists in a task block (for
    cross-validating our hit flags against the run's own evaluation)."""
    import ast
    union = set()
    for m in re.finditer(r"Passed Criteria:\s*(\[[^\n]*?\])", text):
        try:
            union.update(ast.literal_eval(m.group(1)))
        except (ValueError, SyntaxError):
            pass
    return union


def task_record(header_m, block_text):
    pred, err = extract_json_after_marker(
        block_text, ["Prediction:", "Result: {"])
    cands = candidates_from_prediction(pred) if pred else []
    if pred is None and err and err.startswith("json-error"):
        # fallback: scrape the three fields pairwise from the Prediction region
        region = block_text[block_text.rfind("Prediction:"):]
        comps = re.findall(r'"root cause component":\s*"((?:[^"\\]|\\.)*)"', region)
        cands = [{"order": i, "key": str(i + 1), "component": c,
                  "time": None, "reason": None, "score": 0.0}
                 for i, c in enumerate(comps)]
        err = err + " (regex fallback used)"
    gt_logged = None
    gtm = GT_LINE_RE.search(block_text)
    if gtm:
        cm = GT_COMPONENT_RE.search(gtm.group(1))
        if cm:
            gt_logged = cm.group(1)
    return {
        "query_idx": int(header_m.group(2)),
        "task_index": f"task_{header_m.group(4)}",
        "candidates": cands,
        "gt_component_logged": gt_logged,
        "passed_union": passed_criteria_union(block_text),
        "has_time_criterion": "root cause occurrence time is within" in block_text,
        "has_component_criterion": "predicted root cause component is" in block_text,
        "has_reason_criterion": "predicted root cause reason is" in block_text,
        "has_multi_criteria": "The 2-th" in block_text,
        "parse_error": err if pred is None else None,
    }


def split_blocks(lines):
    blocks = []
    cur = None
    for line in lines:
        m = TASK_HEADER_RE.match(line.strip())
        if m:
            cur = (m, [])
            blocks.append(cur)
        elif cur is not None:
            cur[1].append(line)
    return blocks


def parse_log_tasks(path):
    with open(path, "r", encoding="utf-8", errors="replace") as f:
        lines = [strip_ansi(l).rstrip("\n") for l in f]
    for m, blk in split_blocks(lines):
        yield task_record(m, "\n".join(blk))


def parse_log_tasks_from_text(text):
    for m, blk in split_blocks(text.split("\n")):
        yield task_record(m, "\n".join(blk))


# ---------------------------------------------------------------------------
# Ground truth
# ---------------------------------------------------------------------------
SCORING_COMP_RE = re.compile(r"predicted root cause component is ([^\n]+)")


def load_gt():
    """dataset -> DataFrame[idx, component, reason, level, datetime,
    scoring_components].  record.csv row i == query.csv row i."""
    gt = {}
    for ds, (_, _, rel) in DATASETS.items():
        df = pd.read_csv(os.path.join(DATA_ROOT, rel))
        df.columns = [c.strip() for c in df.columns]
        df = df.reset_index().rename(columns={"index": "idx"})
        qdf = pd.read_csv(os.path.join(DATA_ROOT, rel.replace(
            "record.csv", "query.csv")))
        assert len(qdf) == len(df), f"{ds}: query.csv/record.csv row mismatch"
        df["scoring_components"] = [
            "|".join(SCORING_COMP_RE.findall(str(sp)))
            for sp in qdf["scoring_points"]]
        gt[ds] = df[["idx", "level", "component", "reason", "datetime",
                     "scoring_components"]]
    return gt


# ---------------------------------------------------------------------------
# Hit rules
# ---------------------------------------------------------------------------
def time_hit(pred_time, gt_datetime):
    """Official rule: both sides "%Y-%m-%d %H:%M:%S", <=60 s apart; any parse
    failure = miss (mirrors evaluate_multi_candidate.time_difference)."""
    try:
        t1 = datetime.strptime(pred_time, TIME_FMT)
        t2 = datetime.strptime(gt_datetime, TIME_FMT)
    except (TypeError, ValueError):
        return False
    return abs((t1 - t2).total_seconds()) <= 60


def element_hits(cand, gt_comp, gt_reason, gt_datetime):
    return {
        "time": time_hit(cand["time"], gt_datetime),
        "component": cand["component"] is not None and cand["component"] == gt_comp,
        "reason": cand["reason"] is not None and cand["reason"] == gt_reason,
    }


def build_row(method, dataset, model, config, rec, grow, source_log):
    gt_comp = grow["component"].iloc[0]
    gt_reason = grow["reason"].iloc[0]
    gt_dt = grow["datetime"].iloc[0]
    cands = rec["candidates"]
    hits = [element_hits(c, gt_comp, gt_reason, gt_dt) for c in cands]
    best = hits[0] if hits else None
    row = {
        "method": method,
        "dataset": dataset,
        "model": model,
        "config": config,
        "query_idx": rec["query_idx"],
        "task_index": rec["task_index"],
        "predicted_time": cands[0]["time"] if cands else None,
        "predicted_component": cands[0]["component"] if cands else None,
        "predicted_reason": cands[0]["reason"] if cands else None,
        "n_candidates": len(cands),
        "candidate_components": "|".join(str(c["component"]) for c in cands),
        "candidate_reasons": "|".join(str(c["reason"]) for c in cands),
        "candidate_times": "|".join(str(c["time"]) for c in cands),
        "candidate_scores": "|".join(f"{c['score']:g}" for c in cands),
        "gt_time": gt_dt,
        "gt_component": gt_comp,
        "gt_reason": gt_reason,
        "scoring_components": grow["scoring_components"].iloc[0],
        # strict = best candidate; any = any candidate; all3 = same candidate
        "hit_time_strict": best["time"] if best else False,
        "hit_component_strict": best["component"] if best else False,
        "hit_reason_strict": best["reason"] if best else False,
        "hit_time_any": any(h["time"] for h in hits),
        "hit_component_any": any(h["component"] for h in hits),
        "hit_reason_any": any(h["reason"] for h in hits),
        "hit_all3_strict": bool(best) and all(best.values()),
        "hit_all3_any": any(all(h.values()) for h in hits),
        "status": "ok" if cands else "no_prediction",
        "passed_union": rec["passed_union"],
        "has_time_criterion": rec["has_time_criterion"],
        "has_component_criterion": rec["has_component_criterion"],
        "has_reason_criterion": rec["has_reason_criterion"],
        "has_multi_criteria": rec["has_multi_criteria"],
        "parse_error": rec["parse_error"] or "",
        "source_log": source_log,
    }
    return row


# ---------------------------------------------------------------------------
# Collectors
# ---------------------------------------------------------------------------
def find_clustopo_logs(dataset, model, config):
    exp_subdir, prefix, _ = DATASETS[dataset]
    d = os.path.join(EXP_DIR, exp_subdir, model)
    primary = os.path.join(d, f"{prefix}_{config}_{model}.log")
    variants = sorted(
        p for p in glob.glob(os.path.join(d, f"{prefix}_{config}_*_{model}.log")))
    if os.path.exists(primary):
        return primary, variants
    if variants:
        return variants[0], variants[1:]
    return None, []


def collect_clustoporca(gt, warnings):
    rows = []
    coverage = []
    for dataset, model, config in CLUSTOPO_RUNS:
        primary, extras = find_clustopo_logs(dataset, model, config)
        if primary is None:
            coverage.append((dataset, model, 0, len(gt[dataset]), "NO LOG FOUND"))
            warnings.append(f"missing logs: {dataset}/{model}/{config}")
            continue
        seen = {}
        dup = 0
        for path in [primary] + extras:
            for rec in parse_log_tasks(path):
                q = rec["query_idx"]
                if q in seen:
                    dup += 1
                    continue
                gt_df = gt[dataset]
                grow = gt_df[gt_df["idx"] == q]
                if not len(grow):
                    warnings.append(
                        f"{dataset}/{model}: query_idx {q} not in record.csv, skipped")
                    continue
                gt_comp = grow["component"].iloc[0]
                if (rec["gt_component_logged"] is not None
                        and rec["gt_component_logged"] != gt_comp):
                    warnings.append(
                        f"{dataset}/{model} idx={q}: log GT "
                        f"'{rec['gt_component_logged']}' != record.csv '{gt_comp}'")
                seen[q] = build_row("clustoporca", dataset, model, config, rec,
                                    grow, os.path.relpath(path, OPENRCA_ROOT))
        coverage.append((dataset, model, len(seen), len(gt[dataset]),
                         f"dup_skipped={dup}" + (" +gapfill" if extras else "")))
        rows.extend(seen.values())
    return rows, coverage


def collect_rca_agent(gt, warnings):
    rows_by_key = {}
    files = sorted(
        (p for p in glob.glob(os.path.join(RESULT_DIR, "*.log"))
         if "rag_tool" not in os.path.basename(p)),
        key=os.path.getmtime)
    for path in files:
        cur_ds, cur_model = None, None
        with open(path, "r", encoding="utf-8", errors="replace") as f:
            text = strip_ansi(f.read())
        for chunk in re.split(r"(?=Using dataset:)", text):
            mds = DATASET_LINE_RE.search(chunk)
            mm = MODEL_LINE_RE.search(chunk)
            if mds:
                cur_ds = mds.group(1)
                cur_model = mm.group(1).strip() if mm else cur_model
                cur_rca = bool(RCA_AGENT_MODULE_RE.search(chunk))
            else:
                cur_rca = False
            if not (cur_ds and cur_model and cur_rca):
                continue
            ds = {"Market/cloudbed-1": "Market-1",
                  "Market/cloudbed-2": "Market-2"}.get(cur_ds, cur_ds)
            if ds not in DATASETS:
                continue
            for rec in parse_log_tasks_from_text(chunk):
                gt_df = gt[ds]
                grow = gt_df[gt_df["idx"] == rec["query_idx"]]
                if not len(grow):
                    continue
                rows_by_key[(ds, cur_model, rec["query_idx"])] = build_row(
                    "rca-agent", ds, cur_model, "rca-agent", rec, grow,
                    os.path.relpath(path, OPENRCA_ROOT))
    return list(rows_by_key.values())


# ---------------------------------------------------------------------------
# Metrics
# ---------------------------------------------------------------------------
ELEMENTS = ["time", "component", "reason", "all_three"]


def compute_accuracy(df):
    out = []
    for (method, dataset, model), g in df.groupby(["method", "dataset", "model"]):
        for subset, gg in [("all", g),
                           ("heldout", g[~g["query_idx"].isin(
                               EXCLUDED_TASK_IDS.get(dataset, []))])]:
            n = len(gg)
            if n == 0:
                continue
            for el in ELEMENTS:
                for metric in ["strict", "any"]:
                    col = f"hit_{'all3' if el == 'all_three' else el}_{metric}"
                    out.append({"method": method, "dataset": dataset,
                                "model": model, "subset": subset, "element": el,
                                "metric": metric, "n": n,
                                "value": round(float(gg[col].mean()), 6)})
    return pd.DataFrame(out)


def near_miss_reason(pred, gt):
    if not isinstance(pred, str) or not isinstance(gt, str):
        return False
    return pred != gt and pred.strip().casefold() == gt.strip().casefold()


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--no-rca-agent", action="store_true")
    args = ap.parse_args()

    warnings = []
    gt = load_gt()
    rows, coverage = collect_clustoporca(gt, warnings)
    if not args.no_rca_agent:
        rows += collect_rca_agent(gt, warnings)

    df = pd.DataFrame(rows).sort_values(
        ["method", "dataset", "model", "query_idx"]).reset_index(drop=True)

    os.makedirs(OUT_DIR, exist_ok=True)
    pred_path = os.path.join(OUT_DIR, "clustoporca_element_predictions.csv")
    acc_path = os.path.join(OUT_DIR, "clustoporca_element_accuracy.csv")
    df.drop(columns=["passed_union"]).to_csv(pred_path, index=False)
    acc = compute_accuracy(df)
    acc.to_csv(acc_path, index=False)

    # ---------------- report ----------------
    print("=" * 92)
    print("COVERAGE (parsed task headers with GT / queries in record.csv)")
    print("=" * 92)
    for dataset, model, n_have, n_total, note in coverage:
        flag = "OK " if n_have == n_total else "!!!"
        print(f"[{flag}] {dataset:9s} {model:32s} n={n_have:3d}/{n_total:<3d} {note}")
    rca = df[df["method"] == "rca-agent"]
    if len(rca):
        print("-" * 92)
        print("RCA-agent (result/ logs, partial runs — sanity comparison only):")
        for (ds, m), g in rca.groupby(["dataset", "model"]):
            print(f"[!!!] {ds:9s} {m:32s} n={len(g):3d}/{len(gt[ds]):<3d} (partial)")

    print()
    print("=" * 92)
    print("PER-ELEMENT ACCURACY, subset=all (strict = best candidate / any = any candidate)")
    print("=" * 92)
    header = (f"{'method':11s} {'dataset':9s} {'model':32s} "
              + " ".join(f"{el:>18s}" for el in ELEMENTS))
    print(header)
    for (method, dataset, model), g in acc[acc["subset"] == "all"].groupby(
            ["method", "dataset", "model"]):
        cells = []
        for el in ELEMENTS:
            s = g[(g["element"] == el) & (g["metric"] == "strict")]["value"]
            a = g[(g["element"] == el) & (g["metric"] == "any")]["value"]
            cells.append(f"{float(s.iloc[0]):.3f}/{float(a.iloc[0]):.3f}")
        print(f"{method:11s} {dataset:9s} {model:32s} "
              + " ".join(f"{c:>18s}" for c in cells))

    print()
    print("=" * 92)
    print("PER-ELEMENT ACCURACY, subset=heldout (tuning split excluded)")
    print("=" * 92)
    print(header)
    for (method, dataset, model), g in acc[acc["subset"] == "heldout"].groupby(
            ["method", "dataset", "model"]):
        cells = []
        for el in ELEMENTS:
            s = g[(g["element"] == el) & (g["metric"] == "strict")]["value"]
            a = g[(g["element"] == el) & (g["metric"] == "any")]["value"]
            n = g[(g["element"] == el) & (g["metric"] == "strict")]["n"]
            cells.append(f"{float(s.iloc[0]):.3f}/{float(a.iloc[0]):.3f}")
        print(f"{method:11s} {dataset:9s} {model:32s} "
              + " ".join(f"{c:>18s}" for c in cells))

    # cross-validate our hit_any flags against the runs' own Passed Criteria
    print()
    print("=" * 92)
    print("CROSS-CHECK vs evaluator Passed Criteria (single-criterion tasks only;")
    print("multi-criterion tasks are affected by the official evaluator's")
    print("first-component-only quirk and excluded here)")
    print("=" * 92)
    for el, crit_col, gtcol in [("time", "has_time_criterion", "gt_time"),
                                ("component", "has_component_criterion", "gt_component"),
                                ("reason", "has_reason_criterion", "gt_reason")]:
        sub = df[df[crit_col] & ~df["has_multi_criteria"]]
        our = sub[f"hit_{el}_any"]
        theirs = sub.apply(lambda r: str(r[gtcol]) in r["passed_union"], axis=1)
        n_mm = int((our != theirs).sum())
        print(f"  {el:9s}: n={len(sub):4d} single-criterion tasks, "
              f"disagreements={n_mm}")
        if n_mm:
            for _, r in sub[our != theirs].head(5).iterrows():
                print(f"    {r['method']}/{r['dataset']}/{r['model']} "
                      f"idx={r['query_idx']} gt={r[gtcol]!r} "
                      f"cand={r[f'candidate_{el}s']!r} ours={r[f'hit_{el}_any']}")

    # near-miss audit for reason (and component, for completeness)
    print()
    for el in ["reason", "component"]:
        nm = df[df.apply(lambda r: (r[f"hit_{el}_strict"] is False or True)
                         and near_miss_reason(r[f"predicted_{el}"],
                                              r[f"gt_{el}"]), axis=1)]
        nm = nm[~nm[f"hit_{el}_strict"]]
        print(f"near-miss {el} (case/whitespace only, NOT counted as hit): "
              f"{len(nm)} rows")
        for _, r in nm.head(20).iterrows():
            print(f"  {r['method']}/{r['dataset']}/{r['model']} idx={r['query_idx']}: "
                  f"pred={r[f'predicted_{el}']!r} vs gt={r[f'gt_{el}']!r}")

    n_nopred = int((df["status"] != "ok").sum())
    if n_nopred:
        print(f"\nrows without parseable prediction (counted as miss): {n_nopred}")
    if warnings:
        print(f"\nwarnings: {len(warnings)}")
        for w in warnings[:50]:
            print(f"  - {w}")
    print(f"\nwrote {pred_path}")
    print(f"wrote {acc_path}")


if __name__ == "__main__":
    main()
