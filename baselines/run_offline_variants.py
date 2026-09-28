"""
Run the offline ClusTopoRCA variants (no LLM) over OpenRCA queries.

Variants
--------
* ``wo_llm``    : stage-3 topology scorer reproduced in ``offline_scorer.py``;
                  the deterministic cross-cluster merge (dominant cluster
                  first) replaces the LLM synthesis.  The rule-based answer is
                  top-1 entity + dominant fault type mapped to the record.csv
                  reason vocabulary + the primary cluster's first anomaly time.
* ``rht_fused`` : adds CIRCA-style regression hypothesis testing as a fourth
                  evidence dimension.  Per query the KPI frame is built with
                  the exact CIRCA-baseline protocol (``run_baseline.py``:
                  build_frame(pre=30, post=10), prefilter to the top-20 most
                  anomalous entities, inject_time = GT timestamp), PC learns
                  the causal graph and ``rht`` scores every KPI column; entity
                  RHT score = max over its columns.  Fusion per entity:
                      fused = (W_t·time + W_topo·topo + W_c·count
                               + W_rht·rht_norm) / (W_t+W_topo+W_c+W_rht) · cw
                  with the dataset's native W (Bank .3/.4/.3, Telecom
                  .025/.025/.95, Market .1/.8/.1), W_rht=0.3 (default),
                  rht_norm min-max over the query's fused entity set, and cw
                  the Telecom component weight (db 1.0/os 0.9/docker 0.85,
                  1.0 elsewhere).  Entities surfaced only by RHT enter with
                  zero time/topo/count.  The fused ranking is restricted to
                  the official candidate inventory (the answer space of every
                  compared method).

Usage:
    python run_offline_variants.py --variant wo_llm --dataset Bank
    python run_offline_variants.py --variant rht_fused --dataset Bank --start 0 --end 3
    python run_offline_variants.py --summary

Outputs (baselines/results/):
    wo_llm_{dataset}.jsonl, rht_fused_{dataset}.jsonl,
    offline_variants_summary.csv
"""

import argparse
import json
import os
import sys
import time
import traceback

import numpy as np
import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import openrca_data as od
import offline_scorer as osf

RESULTS_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "results")

# CIRCA component top-1 from FINAL_baselines_component_accuracy.csv (reference
# for the gap analysis)
CIRCA_TOP1 = {"Bank": 0.463, "Telecom": 0.176, "Market-1": 0.329, "Market-2": 0.462}

BASE_WEIGHTS = {"Bank": (0.3, 0.4, 0.3), "Telecom": (0.025, 0.025, 0.95),
                "Market-1": (0.1, 0.8, 0.1), "Market-2": (0.1, 0.8, 0.1)}


def _telecom_cw(entity):
    import re as _re
    m = _re.match(r"^(os|docker|db)_\d+$", entity)
    return osf.TELECOM_COMPONENT_WEIGHTS.get(m.group(1), 0.5) if m else 0.5


def component_weight_of(dataset, entity):
    if dataset == "Telecom":
        return _telecom_cw(entity)
    return 1.0


# ---------------------------------------------------------------------------
# RHT (CIRCA) per-query entity scores
# ---------------------------------------------------------------------------
def rht_entity_scores(dataset, ws, we, gt_ts, cache):
    """-> (entity -> rht score, sli_col, n_columns).  Mirrors run_baseline's
    circa invocation exactly (same frame, prefilter, inject_time, rht defaults)."""
    from core.circa import _drop_degenerate, pc_default, rht

    df, col2entity = od.build_frame(dataset, ws, we, pre_minutes=30,
                                    post_minutes=10, cache=cache)
    sli_col = od.select_sli(df, dataset, ws, we)
    df = od.prefilter_entities(df, col2entity, ws, we, max_entities=20,
                               force_cols=[sli_col] if sli_col else [])
    inject_time = int(gt_ts)

    time_col = df["time"]
    pc_input = df.drop(columns=["time"])
    pc_input = _drop_degenerate(pc_input)
    pc_input = pc_input.dropna(axis=0)
    np.random.seed(0)
    adj = pc_default(pc_input)
    frame = pc_input.copy()
    frame["time"] = time_col
    ranks = rht(adj, inject_time, frame)  # [(column, score)], score desc

    ent_score = {}
    for col, score in ranks:
        ent = col2entity.get(col)
        if ent is None:
            continue
        ent_score[ent] = max(ent_score.get(ent, 0.0), float(score))
    return ent_score, sli_col, int(df.shape[1] - 1), inject_time


def fuse_scores(dataset, cand_rows, rht_scores, w_rht, inventory=None):
    """Fuse scorer component scores with RHT entity scores.

    cand_rows: {candidate: score-record dict from offline_scorer}
    rht_scores: {entity: rht score}
    inventory: official candidate list; when given, the fused ranking is
        restricted to it (the answer space of every compared method).
    Returns ranked list of (entity, fused_score).
    """
    w_t, w_topo, w_c = BASE_WEIGHTS[dataset]
    entities = set(cand_rows) | set(rht_scores)
    if inventory is not None:
        entities &= set(inventory)
    if not entities:
        return []
    vals = [rht_scores.get(e, 0.0) for e in entities]
    v_min, v_max = min(vals), max(vals)
    if v_max > v_min:
        rht_norm = {e: (rht_scores.get(e, 0.0) - v_min) / (v_max - v_min)
                    for e in entities}
    else:
        rht_norm = {e: (1.0 if v_max > 0 else 0.0) for e in entities}
    denom = w_t + w_topo + w_c + w_rht
    scored = []
    for e in entities:
        row = cand_rows.get(e)
        t = row["time_score"] if row else 0.0
        topo = row["topology_score"] if row else 0.0
        cnt = row["count_score"] if row else 0.0
        cw = component_weight_of(dataset, e)
        fused = (w_t * t + w_topo * topo + w_c * cnt
                 + w_rht * rht_norm[e]) / denom * cw
        # stable tie-break: scorer candidates first (by their rank), then rht-only
        scorer_rank = list(cand_rows).index(e) if e in cand_rows else len(cand_rows)
        scored.append((e, fused, scorer_rank))
    scored.sort(key=lambda x: (-x[1], x[2], x[0]))
    return [(e, s) for e, s, _ in scored]


# ---------------------------------------------------------------------------
# per-query runner
# ---------------------------------------------------------------------------
def run_one(variant, dataset, qrow, rrow, args, cache, modal_reason):
    ws, we = od.parse_window(qrow["instruction"])
    inventory = od.candidate_inventory(dataset)

    t0 = time.time()
    res = osf.rank_candidates(dataset, ws, we, inventory)
    cand_rows = res["candidate_rows"]

    rec = {
        "idx": int(rrow["idx"]),
        "dataset": dataset,
        "method": variant,
        "task_index": qrow["task_index"],
        "gt_component": rrow["component"],
        "gt_level": rrow["level"],
        "gt_reason": rrow["reason"],
        "gt_time": int(rrow["timestamp"]),
        "window": [ws, we],
        "n_anomalies": res["n_anomalies"],
        "clusters": res["clusters"],
        "pred_time": res["first_anomaly_ts"],
    }

    if variant == "rht_fused":
        try:
            rht_cache_row = getattr(args, "_rht_cache_row", None)
            if rht_cache_row is not None:
                # replay mode: RHT scores from the prebuilt score cache
                # (results/score_cache/{dataset}.jsonl); the offline scorer
                # part above is recomputed (cheap, no PC/RHT).
                rht_scores = rht_cache_row.get("rht_scores") or {}
                if rht_cache_row.get("rht_error"):
                    raise RuntimeError(f"cached rht_error: {rht_cache_row['rht_error']}")
                rec.update({"sli": rht_cache_row.get("sli"),
                            "n_columns": rht_cache_row.get("n_columns"),
                            "inject_time": rht_cache_row.get("inject_time")})
            else:
                rht_scores, sli_col, n_cols, inject_time = rht_entity_scores(
                    dataset, ws, we, rrow["timestamp"], cache)
                rec.update({"sli": sli_col, "n_columns": n_cols,
                            "inject_time": inject_time})
            fused = fuse_scores(dataset, cand_rows, rht_scores, args.w_rht,
                                inventory=inventory)
            ranked = [e for e, _ in fused]
            rec["rht_top1"] = max(rht_scores, key=rht_scores.get) if rht_scores else None
        except Exception as e:
            ranked = res["ranked_entities"]
            rec["rht_error"] = f"{type(e).__name__}: {e}"
            rec["status_note"] = "fallback_wo_llm"
    else:
        ranked = res["ranked_entities"]

    # rule-based fault type for the top-1 entity
    if ranked:
        top1 = ranked[0]
        rec["pred_reason"] = osf.predict_reason(
            dataset, res["candidate_attrs"].get(top1, {}), top1, modal_reason)
    else:
        rec["pred_reason"] = None

    gt = rrow["component"]
    try:
        gt_rank = ranked.index(gt) + 1
    except ValueError:
        gt_rank = None
    rec.update({
        "ranked_entities": ranked[:10],
        "top1": ranked[0] if ranked else None,
        "gt_rank": gt_rank,
        "hit@1": int(gt_rank == 1),
        "hit@3": int(gt_rank is not None and gt_rank <= 3),
        "hit@5": int(gt_rank is not None and gt_rank <= 5),
        "runtime_s": round(time.time() - t0, 2),
        "status": "ok",
    })
    return rec


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--variant", choices=["wo_llm", "rht_fused"])
    ap.add_argument("--dataset", choices=list(od.DATASETS))
    ap.add_argument("--start", type=int, default=0)
    ap.add_argument("--end", type=int, default=None)
    ap.add_argument("--w-rht", type=float, default=0.3)
    ap.add_argument("--out", default=None)
    ap.add_argument("--summary", action="store_true")
    ap.add_argument("--replay-cache", action="store_true",
                    help="rht_fused only: read RHT entity scores from "
                         "results/score_cache/{dataset}.jsonl instead of "
                         "recomputing PC/RHT (offline scorer part still runs).")
    args = ap.parse_args()

    if args.summary:
        summarize()
        return

    if args.out is None:
        args.out = os.path.join(RESULTS_DIR, f"{args.variant}_{args.dataset}.jsonl")
    os.makedirs(os.path.dirname(args.out), exist_ok=True)

    records = od.load_records(args.dataset)
    queries = od.load_queries(args.dataset)
    modal_reason = records["reason"].mode().iloc[0]
    end = len(records) if args.end is None else min(args.end, len(records))

    rht_cache = None
    if args.replay_cache:
        cache_path = os.path.join(RESULTS_DIR, "score_cache", f"{args.dataset}.jsonl")
        rht_cache = {}
        with open(cache_path) as f:
            for line in f:
                r = json.loads(line)
                rht_cache[r["idx"]] = r

    done = set()
    if os.path.exists(args.out):
        with open(args.out) as f:
            for line in f:
                try:
                    done.add(json.loads(line)["idx"])
                except Exception:
                    pass

    cache = {}
    with open(args.out, "a") as fout:
        for idx in range(args.start, end):
            if idx in done:
                print(f"[skip] idx={idx}", flush=True)
                continue
            rrow, qrow = records.iloc[idx], queries.iloc[idx]
            if rht_cache is not None:
                args._rht_cache_row = rht_cache.get(idx)
            try:
                rec = run_one(args.variant, args.dataset, qrow, rrow, args,
                              cache, modal_reason)
            except Exception as e:
                rec = {"idx": idx, "dataset": args.dataset, "method": args.variant,
                       "gt_component": rrow["component"], "gt_level": rrow["level"],
                       "gt_reason": rrow["reason"], "gt_time": int(rrow["timestamp"]),
                       "status": "error", "error": f"{type(e).__name__}: {e}",
                       "trace": traceback.format_exc()[-2000:]}
            fout.write(json.dumps(rec) + "\n")
            fout.flush()
            flag = "" if rec["status"] == "ok" else f" ERROR: {rec.get('error', '')}"
            print(f"[done] idx={idx} status={rec['status']} top1={rec.get('top1')} "
                  f"gt={rec['gt_component']} gt_rank={rec.get('gt_rank')} "
                  f"rt={rec.get('runtime_s')}s{flag}", flush=True)


# ---------------------------------------------------------------------------
# summary
# ---------------------------------------------------------------------------
def summarize():
    rows = []
    for variant in ["wo_llm", "rht_fused"]:
        for ds in ["Bank", "Telecom", "Market-1", "Market-2"]:
            path = os.path.join(RESULTS_DIR, f"{variant}_{ds}.jsonl")
            if not os.path.exists(path):
                continue
            df = pd.read_json(path, lines=True)
            ok = df[df["status"] == "ok"]
            n = len(ok)
            mrr = float(np.mean([1.0 / r if isinstance(r, (int, float)) and r and r >= 1
                                 else 0.0 for r in ok["gt_rank"]])) if n else 0.0
            rows.append({
                "variant": variant, "dataset": ds, "n": n,
                "hit@1": round(float(ok["hit@1"].mean()), 4) if n else None,
                "hit@3": round(float(ok["hit@3"].mean()), 4) if n else None,
                "hit@5": round(float(ok["hit@5"].mean()), 4) if n else None,
                "MRR": round(mrr, 4),
                "n_error": int((df["status"] != "ok").sum()),
                "circa_top1": CIRCA_TOP1[ds],
            })
    out = pd.DataFrame(rows)
    out["delta_vs_circa_top1"] = (out["hit@1"] - out["circa_top1"]).round(4)
    path = os.path.join(RESULTS_DIR, "offline_variants_summary.csv")
    out.to_csv(path, index=False)
    print(out.to_string(index=False))
    print(f"\nwrote {path}")


if __name__ == "__main__":
    main()
