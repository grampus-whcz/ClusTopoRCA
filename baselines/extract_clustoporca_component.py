#!/usr/bin/env python
"""Extract per-query root-cause *component* predictions from ClusTopoRCA
experiment logs (and RCA-agent baseline logs, for sanity comparison) and
compute component-level top-1 accuracy, on the same footing as the
classical/LLM baselines in this directory (MicroCause / CIRCA / mABC / FoA).

Sources
-------
ClusTopoRCA (paper method) logs live in
``{OPENRCA}/experiments/{Bank,Market,Telecom}/{model}/{prefix}_{config}_{model}.log``
and follow the pattern produced by ``rca/run_agent_standard_multi_candidate.py``:

    2026-04-07_20-46-14_#0-0: task_1            <- task header (#<query_idx>-0: task_<k>)
    ... Prediction: {"1": {"Suspicious score": 0.95,
                           "root cause component": "MG02", ...}, ...}
    ... groundtruth: level: podcomponent: Mysql02timestamp: ...
    ... Candidate 1: Score: 0.0

The config that reproduces the paper's main table (tab:dataset_accuracy_
comparison_separated in tex/sn-article.tex, "全量数据" rows of the companion
*_global_summary.csv files) is, per dataset x model:

    Bank:    no_RAG_c3_knowledge_graph_advanced_merged
             (glm-4.7: no_RAG_c4_knowledge_graph_advanced_merged)
    Telecom: no_RAG_c3_knowledge_graph_advanced_merged
    Market:  no_RAG_c3_knowledge_graph_advanced_merged_hyperpara_config2

RCA-agent (paper baseline) logs live in ``{OPENRCA}/result/*.log`` (Nov-2025
runs, ANSI-coloured, fragmented per date; mostly Qwen3).  They share the same
task-header / Prediction format, so they are parsed with the same machinery.
Coverage is partial and reported as-is.

Metrics
-------
top1_strict : component of the best candidate (highest "Suspicious score",
              ties broken by candidate order) equals the GT component.
top1_any    : any candidate's component equals the GT component (component-
              level analogue of the paper's multi-candidate Correct rule,
              main/evaluate_multi_candidate.py).
Both are reported on subset=all (every parsed query) and subset=heldout
(EXCLUDED_TASK_IDS of experiments/8.get_all_result_from_tasks_info_all_task_
type.py removed — the tuning split used in the paper pipeline).

Matching is exact string equality, as in the OpenRCA evaluator.  Near-misses
(case/whitespace) are counted and printed, never silently normalised.

Outputs
-------
baselines/results/clustoporca_component_predictions.csv  (per-query records)
baselines/results/clustoporca_component_accuracy.csv     (long summary table)

Usage:
    /root/shared-nvme/.conda/envs/RCAEval_py3.12/bin/python \
        extract_clustoporca_component.py [--no-rca-agent]
"""

import argparse
import glob
import json
import os
import re
import sys
from collections import defaultdict

import pandas as pd

OPENRCA_ROOT = os.environ.get("OPENRCA_ROOT", "/root/shared-nvme/work/agent/OpenRCA")
DATA_ROOT = os.environ.get("OPENRCA_DATA", "/root/shared-nvme/data_set/OpenRCA")
EXP_DIR = os.path.join(OPENRCA_ROOT, "experiments")
RESULT_DIR = os.path.join(OPENRCA_ROOT, "result")
OUT_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "results")

# ---------------------------------------------------------------------------
# Dataset registry (dataset naming matches baselines/run_baseline.py)
# ---------------------------------------------------------------------------
#          dataset   experiments subdir   log file prefix     record.csv (relative to DATA_ROOT)
DATASETS = {
    "Bank":    ("Bank",    "Bank",             "Bank/record.csv"),
    "Telecom": ("Telecom", "Telecom",          "Telecom/record.csv"),
    "Market-1": ("Market", "Market_cloudbed-1", "Market/cloudbed-1/record.csv"),
    "Market-2": ("Market", "Market_cloudbed-2", "Market/cloudbed-2/record.csv"),
}

# Tuning split excluded in the paper pipeline
# (experiments/8.get_all_result_from_tasks_info_all_task_type.py)
EXCLUDED_TASK_IDS = {
    "Bank": [51, 48, 112, 71, 88, 70, 68, 72, 86, 47, 45, 65, 53, 52, 57,
             54, 62, 60, 133, 0, 1, 2, 107, 8, 3, 13, 16, 9, 12, 6],
    "Market-1": [0, 2, 4, 5, 6, 7, 8, 9, 12, 13, 14, 16, 20, 21, 23, 27,
                 29, 30, 31, 33, 49, 56],
    "Market-2": [],
    "Telecom": [2, 5, 8, 12, 17],
}

# ClusTopoRCA paper-table models and the log config that reproduces the
# published numbers (verified against *_global_summary.csv, 全量数据 rows).
PAPER_MODELS = [
    "gpt-4o",
    "gemini-2.5-pro-preview-p",
    "deepseek-r1-0528",
    "qwen3-235b-a22b-instruct-2507",
    "glm-4.7",
]
# extra models whose main-config logs also exist (not in the paper table)
EXTRA_MODELS = ["glm-4.5", "glm-4.6"]

C3 = "no_RAG_c3_knowledge_graph_advanced_merged"
C4 = "no_RAG_c4_knowledge_graph_advanced_merged"
MKT_CFG2 = "no_RAG_c3_knowledge_graph_advanced_merged_hyperpara_config2"

CLUSTOPO_RUNS = []  # (dataset, model, config)
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
COMP_FALLBACK_RE = re.compile(r'"root cause component":\s*"((?:[^"\\]|\\.)*)"')


def strip_ansi(text):
    return ANSI_RE.sub("", text)


def extract_json_after_marker(text, markers):
    """Find the last occurrence of any marker in text and JSON-decode the
    object starting at the first '{' after it.  Returns (dict, error)."""
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
    """Prediction dict -> ordered candidate list [(key, component, score)].

    Ordered by suspicious score desc, ties keep candidate order (the runner
    already emits candidates sorted best-first)."""
    cands = []
    if not isinstance(pred, dict):
        return cands
    for order, (k, v) in enumerate(pred.items()):
        if not isinstance(v, dict):
            continue
        comp = v.get("root cause component")
        if comp is not None and not isinstance(comp, str):
            comp = str(comp)
        try:
            score = float(v.get("Suspicious score", 0.0))
        except (TypeError, ValueError):
            score = 0.0
        cands.append((order, k, comp, score))
    cands.sort(key=lambda t: (-t[3], t[0]))
    return [(k, comp, score) for _, k, comp, score in cands]


def passed_criteria_union(text):
    """Union of all 'Passed Criteria' lists in a task block (cross-check of
    the evaluator's own per-candidate verdicts).  Handles both the
    multi-candidate ('Candidate N: Passed Criteria: ...') and the
    single-candidate RCA-agent ('Passed Criteria: ...') line shape."""
    import ast
    union = set()
    for m in re.finditer(r"Passed Criteria:\s*(\[[^\n]*?\])", text):
        try:
            union.update(ast.literal_eval(m.group(1)))
        except (ValueError, SyntaxError):
            pass
    return union


def parse_log_tasks(path):
    """Parse one experiment log.  Yields per task header a dict with
    query_idx, task_index, candidates, gt_component_logged, n_score_lines."""
    with open(path, "r", encoding="utf-8", errors="replace") as f:
        lines = [strip_ansi(l).rstrip("\n") for l in f]

    # split into blocks on task headers
    blocks = []  # (header_match, [line, ...])
    cur = None
    for line in lines:
        m = TASK_HEADER_RE.match(line.strip())
        if m:
            cur = (m, [])
            blocks.append(cur)
        elif cur is not None:
            cur[1].append(line)

    for m, blk in blocks:
        text = "\n".join(blk)
        pred, err = extract_json_after_marker(text, ["Prediction:", "Result: {"])
        cands = candidates_from_prediction(pred) if pred else []
        if pred is None and err and err.startswith("json-error"):
            # fallback: scrape components directly from the Prediction region
            region = text[text.rfind("Prediction:"):]
            comps = COMP_FALLBACK_RE.findall(region)
            cands = [(str(i + 1), c, 0.0) for i, c in enumerate(comps)]
            err = err + " (regex fallback used)"
        gt_logged = None
        gtm = GT_LINE_RE.search(text)
        if gtm:
            cm = GT_COMPONENT_RE.search(gtm.group(1))
            if cm:
                gt_logged = cm.group(1)
        rec = {
            "query_idx": int(m.group(2)),
            "task_index": f"task_{m.group(4)}",
            "task_ts": m.group(1),
            "candidates": cands,
            "gt_component_logged": gt_logged,
            "passed_union": passed_criteria_union(text),
            "has_component_criterion": "predicted root cause component is" in text,
            "n_score_lines": len(re.findall(r"Candidate \d+:\s*Score:", text)),
            "parse_error": err if pred is None else None,
        }
        yield rec


# ---------------------------------------------------------------------------
# Ground truth
# ---------------------------------------------------------------------------
SCORING_COMP_RE = re.compile(r"predicted root cause component is ([^\n]+)")


def load_gt():
    """dataset -> DataFrame[idx, component, reason, level, datetime,
    scoring_components]  (record.csv rows are 1:1 with query.csv rows; the
    scoring_components column lists every component criterion of the query —
    relevant for the ~40 multi-fault queries)."""
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
# ClusTopoRCA log discovery
# ---------------------------------------------------------------------------
def find_clustopo_logs(dataset, model, config):
    """Return (primary_log, [gap_fill_logs]) for one run.

    Primary is the exact {prefix}_{config}_{model}.log; gap-fill logs are
    same-config files with an extra infix (e.g. ..._0-50_glm-4.7.log) used to
    cover query indices missing from the primary."""
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
            coverage.append((dataset, model, config, 0, len(gt[dataset]),
                             "NO LOG FOUND"))
            warnings.append(f"missing logs: {dataset}/{model}/{config}")
            continue
        seen = {}          # query_idx -> row
        dup = 0
        for path in [primary] + extras:
            for rec in parse_log_tasks(path):
                q = rec["query_idx"]
                if q in seen:
                    dup += 1
                    continue  # primary log / first occurrence wins
                gt_df = gt[dataset]
                grow = gt_df[gt_df["idx"] == q]
                gt_comp = grow["component"].iloc[0] if len(grow) else None
                if gt_comp is None:
                    warnings.append(
                        f"{dataset}/{model}: query_idx {q} not in record.csv, skipped")
                    continue
                if (rec["gt_component_logged"] is not None
                        and rec["gt_component_logged"] != gt_comp):
                    warnings.append(
                        f"{dataset}/{model} idx={q}: log GT "
                        f"'{rec['gt_component_logged']}' != record.csv '{gt_comp}'")
                cands = rec["candidates"]
                seen[q] = {
                    "method": "clustoporca",
                    "dataset": dataset,
                    "model": model,
                    "config": config,
                    "query_idx": q,
                    "task_index": rec["task_index"],
                    "predicted_component": cands[0][1] if cands else None,
                    "n_candidates": len(cands),
                    "candidate_components": "|".join(
                        str(c[1]) for c in cands),
                    "candidate_scores": "|".join(
                        f"{c[2]:g}" for c in cands),
                    "gt_component": gt_comp,
                    "gt_reason": grow["reason"].iloc[0],
                    "scoring_components": grow["scoring_components"].iloc[0],
                    "status": "ok" if cands else "no_prediction",
                    "passed_has_gt": gt_comp in rec["passed_union"],
                    "has_component_criterion": rec["has_component_criterion"],
                    "parse_error": rec["parse_error"] or "",
                    "source_log": os.path.relpath(path, OPENRCA_ROOT),
                }
        coverage.append((dataset, model, config, len(seen),
                         len(gt[dataset]),
                         f"dup_skipped={dup}" + (" +gapfill" if extras else "")))
        rows.extend(seen.values())
    return rows, coverage


# ---------------------------------------------------------------------------
# RCA-agent logs (result/, partial Nov-2025 runs)
# ---------------------------------------------------------------------------
def collect_rca_agent(gt, warnings):
    rows_by_key = {}   # (dataset, model, query_idx) -> (sort_key, row)
    files = sorted(
        (p for p in glob.glob(os.path.join(RESULT_DIR, "*.log"))
         if "rag_tool" not in os.path.basename(p)),
        key=os.path.getmtime)  # oldest first -> latest re-run wins
    for path in files:
        cur_ds, cur_model, cur_rca = None, None, False
        with open(path, "r", encoding="utf-8", errors="replace") as f:
            text = strip_ansi(f.read())
        # split into run blocks on 'Using dataset:'; only keep blocks whose
        # agent module is rca.baseline.rca_agent (excludes rag_tool_* agents)
        for chunk in re.split(r"(?=Using dataset:)", text):
            mds = DATASET_LINE_RE.search(chunk)
            mm = MODEL_LINE_RE.search(chunk)
            if mds:
                cur_ds = mds.group(1)
                cur_model = mm.group(1) if mm else cur_model
                cur_rca = bool(RCA_AGENT_MODULE_RE.search(chunk))
            if not (cur_ds and cur_model and cur_rca):
                continue
            ds = {"Market/cloudbed-1": "Market-1",
                  "Market/cloudbed-2": "Market-2"}.get(cur_ds, cur_ds)
            if ds not in DATASETS:
                continue
            for rec in parse_log_tasks_from_text(chunk):
                q = rec["query_idx"]
                gt_df = gt[ds]
                grow = gt_df[gt_df["idx"] == q]
                if not len(grow):
                    continue
                cands = rec["candidates"]
                key = (ds, cur_model, q)
                rows_by_key[key] = {
                    "method": "rca-agent",
                    "dataset": ds,
                    "model": cur_model,
                    "config": "rca-agent",
                    "query_idx": q,
                    "task_index": rec["task_index"],
                    "predicted_component": cands[0][1] if cands else None,
                    "n_candidates": len(cands),
                    "candidate_components": "|".join(str(c[1]) for c in cands),
                    "candidate_scores": "|".join(f"{c[2]:g}" for c in cands),
                    "gt_component": grow["component"].iloc[0],
                    "gt_reason": grow["reason"].iloc[0],
                    "scoring_components": grow["scoring_components"].iloc[0],
                    "status": "ok" if cands else "no_prediction",
                    "passed_has_gt": grow["component"].iloc[0] in rec["passed_union"],
                    "has_component_criterion": rec["has_component_criterion"],
                    "parse_error": rec["parse_error"] or "",
                    "source_log": os.path.relpath(path, OPENRCA_ROOT),
                }
    return list(rows_by_key.values())


def parse_log_tasks_from_text(text):
    """Same task-block parsing as parse_log_tasks but on an in-memory string."""
    lines = text.split("\n")
    blocks = []
    cur = None
    for line in lines:
        m = TASK_HEADER_RE.match(line.strip())
        if m:
            cur = (m, [])
            blocks.append(cur)
        elif cur is not None:
            cur[1].append(line)
    for m, blk in blocks:
        btext = "\n".join(blk)
        pred, err = extract_json_after_marker(btext, ["Prediction:", "Result: {"])
        cands = candidates_from_prediction(pred) if pred else []
        if pred is None and err and err.startswith("json-error"):
            region = btext[btext.rfind("Prediction:"):]
            comps = COMP_FALLBACK_RE.findall(region)
            cands = [(str(i + 1), c, 0.0) for i, c in enumerate(comps)]
            err = err + " (regex fallback used)"
        yield {
            "query_idx": int(m.group(2)),
            "task_index": f"task_{m.group(4)}",
            "candidates": cands,
            "passed_union": passed_criteria_union(btext),
            "has_component_criterion": "predicted root cause component is" in btext,
            "parse_error": err if pred is None else None,
        }


# ---------------------------------------------------------------------------
# Metrics
# ---------------------------------------------------------------------------
def near_miss(pred, gt):
    """Same modulo case/whitespace — reported, never silently matched."""
    if not isinstance(pred, str) or not isinstance(gt, str):
        return False
    return pred != gt and pred.strip().casefold() == gt.strip().casefold()


def compute_accuracy(df):
    out = []
    for (method, dataset, model), g in df.groupby(["method", "dataset", "model"]):
        g = g.copy()
        g["hit_strict"] = g["predicted_component"] == g["gt_component"]
        g["hit_any"] = g.apply(
            lambda r: r["gt_component"] in str(r["candidate_components"]).split("|"),
            axis=1)
        for subset, gg in [("all", g),
                           ("heldout", g[~g["query_idx"].isin(
                               EXCLUDED_TASK_IDS.get(dataset, []))])]:
            n = len(gg)
            if n == 0:
                continue
            out.append({"method": method, "dataset": dataset, "model": model,
                        "subset": subset, "metric": "top1_strict", "n": n,
                        "value": round(float(gg["hit_strict"].mean()), 6)})
            out.append({"method": method, "dataset": dataset, "model": model,
                        "subset": subset, "metric": "top1_any", "n": n,
                        "value": round(float(gg["hit_any"].mean()), 6)})
    return pd.DataFrame(out)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--no-rca-agent", action="store_true",
                    help="skip the partial RCA-agent logs in result/")
    args = ap.parse_args()

    warnings = []
    gt = load_gt()

    rows, coverage = collect_clustoporca(gt, warnings)
    if not args.no_rca_agent:
        rows += collect_rca_agent(gt, warnings)

    df = pd.DataFrame(rows).sort_values(
        ["method", "dataset", "model", "query_idx"]).reset_index(drop=True)

    os.makedirs(OUT_DIR, exist_ok=True)
    pred_path = os.path.join(OUT_DIR, "clustoporca_component_predictions.csv")
    acc_path = os.path.join(OUT_DIR, "clustoporca_component_accuracy.csv")
    df.to_csv(pred_path, index=False)

    acc = compute_accuracy(df)
    acc.to_csv(acc_path, index=False)

    # ---------------- report ----------------
    print("=" * 78)
    print("COVERAGE (parsed task headers with GT / queries in record.csv)")
    print("=" * 78)
    for dataset, model, config, n_have, n_total, note in coverage:
        flag = "OK " if n_have == n_total else "!!!"
        print(f"[{flag}] {dataset:9s} {model:32s} n={n_have:3d}/{n_total:<3d} {note}")
    rca = df[df["method"] == "rca-agent"]
    if len(rca):
        print("-" * 78)
        print("RCA-agent (result/ logs, partial runs — sanity comparison only):")
        for (ds, m), g in rca.groupby(["dataset", "model"]):
            n_tot = len(gt[ds])
            print(f"[!!!] {ds:9s} {m:32s} n={len(g):3d}/{n_tot:<3d} (partial)")

    print()
    print("=" * 78)
    print("COMPONENT-LEVEL ACCURACY (fraction; n = queries in subset)")
    print("=" * 78)
    for (method, dataset, model), g in acc.groupby(["method", "dataset", "model"]):
        piv = { (r["subset"], r["metric"]): (r["n"], r["value"])
                for _, r in g.iterrows() }
        a_s = piv.get(("all", "top1_strict"), (0, float("nan")))
        a_a = piv.get(("all", "top1_any"), (0, float("nan")))
        h_s = piv.get(("heldout", "top1_strict"), (0, float("nan")))
        h_a = piv.get(("heldout", "top1_any"), (0, float("nan")))
        print(f"{method:11s} {dataset:9s} {model:32s} "
              f"all(n={a_s[0]:3d}): strict={a_s[1]:.3f} any={a_a[1]:.3f} | "
              f"heldout(n={h_s[0]:3d}): strict={h_s[1]:.3f} any={h_a[1]:.3f}")

    # near-miss audit (exact-match rule kept; these are only reported)
    nm = df[df.apply(lambda r: near_miss(r["predicted_component"],
                                         r["gt_component"]), axis=1)]
    print()
    print(f"near-miss (case/whitespace only, NOT counted as hit): {len(nm)} rows")
    for _, r in nm.iterrows():
        print(f"  {r['method']}/{r['dataset']}/{r['model']} idx={r['query_idx']}: "
              f"pred={r['predicted_component']!r} vs gt={r['gt_component']!r}")

    # cross-validate top1_any against the evaluator's own Passed Criteria:
    # on tasks whose scoring points include a component criterion, 'hit_any'
    # (from the Prediction JSON) must equal 'passed_has_gt' (the run's own
    # evaluation of that criterion).
    sub = df[df["has_component_criterion"]]
    hit_any = sub.apply(
        lambda r: r["gt_component"] in str(r["candidate_components"]).split("|"),
        axis=1)
    mismatch = sub[hit_any != sub["passed_has_gt"]]
    n_multi = int((mismatch["scoring_components"].str.contains(
        "|", regex=False)).sum()) if len(mismatch) else 0
    print(f"\ncross-check hit_any vs evaluator Passed Criteria "
          f"(tasks with component criterion, n={len(sub)}): "
          f"{len(mismatch)} rows disagree (of which {n_multi} are "
          f"multi-component-criterion queries, where the official evaluator "
          f"can only credit the 1st scoring component per candidate)")
    for _, r in mismatch.head(20).iterrows():
        print(f"  {r['method']}/{r['dataset']}/{r['model']} idx={r['query_idx']}: "
              f"cands={r['candidate_components']!r} gt={r['gt_component']!r} "
              f"passed_has_gt={r['passed_has_gt']}")

    n_nopred = int((df["status"] != "ok").sum())
    if n_nopred:
        print(f"\nrows without parseable prediction (counted as miss): {n_nopred}")
        for _, r in df[df["status"] != "ok"].iterrows():
            print(f"  {r['method']}/{r['dataset']}/{r['model']} idx={r['query_idx']} "
                  f"({r['parse_error']})")
    if warnings:
        print(f"\nwarnings: {len(warnings)}")
        for w in warnings[:50]:
            print(f"  - {w}")
    print(f"\nwrote {pred_path}")
    print(f"wrote {acc_path}")


if __name__ == "__main__":
    main()
