"""
Batch driver: run mABC over OpenRCA queries and emit JSONL results aligned
with run_baseline.py (same fields, method="mabc").

Faithful to the original main/main.py two-stage flow:
  stage 1 — ProcessScheduler ReAct loop orchestrating the expert agents;
  stage 2 — SolutionEngineer condenses the analysis into
            "Root Cause Endpoint: XXX, Root Cause Reason: XXX".

Usage (run from anywhere; CWD is switched to this file's directory):
    MABC_MODEL=deepseek-r1-0528 python run_mabc.py --dataset Bank --start 0 --end 5

The predicted component is extracted from the final answer and fuzzy-matched
to the candidate component set of the dataset (exact -> case-insensitive ->
containment), since the LLM may echo entity names imperfectly.
"""

import argparse
import json
import os
import re
import sys
import time
import traceback

HERE = os.path.dirname(os.path.abspath(__file__))
os.chdir(HERE)  # tool paths in agents/base/profile.py are relative to CWD
sys.path.insert(0, os.path.dirname(HERE))  # for openrca_data


def parse_args():
    ap = argparse.ArgumentParser()
    ap.add_argument("--dataset", required=True, choices=["Bank", "Telecom", "Market-1", "Market-2"])
    ap.add_argument("--start", type=int, default=0)
    ap.add_argument("--end", type=int, default=None)
    ap.add_argument("--out", default=None)
    return ap.parse_args()


ARGS = parse_args()
os.environ["MABC_DATASET"] = ARGS.dataset  # must precede agent/tool imports

import openrca_data as od  # noqa: E402

sys.path.insert(0, HERE)
from agents.base.profile import (DataDetective, DependencyExplorer,  # noqa: E402
                                 FaultMapper, ProbabilityOracle,
                                 ProcessScheduler, SolutionEngineer)
from agents.base.run import ReActTotRun, ThreeHotCotRun  # noqa: E402
from agents.tools import process_scheduler_tools, solution_engineer_tools  # noqa: E402
from utils.llm import TOKEN_USAGE, reset_token_usage  # noqa: E402

QUESTION_TEMPLATE = """Backgroud: In a distributed microservices system, there is a lot of traces across endpoints which represent the dependency relationship between endpoints. A trace consists of a sequence of spans, each representing a call from one endpoint to another when ignore the service level.

Alert generally occurs on the top endpoint at time T for a significant anomaly when the root cause endpoint at time T' is the downstream endpoint of the alerting endpoint. Endpoint A(TA) -> Endpoint B(TB) -> Endpoint C(TC) -> Endpoint D(TD), if the alert occurs on the Endpoint A at time TA, the root cause endpoint is the Endpoint C at time TC when the metric of Endpoint C is abnormal but the metric of Endpoint D at time TD is normal.

Alert: Endpoint {endpoint} experiencing a significant increase in response time {t}.
Task: Please find the root cause endpoint behind the alerting endpoint {endpoint} by analyzing the metric of endpoint and the call trace.
Format: Root Cause Endpoint: XXX, Root Cause Reason: XXX
"""

STAGE2_TEMPLATE = ("Base on the analysis, what is the root cause endpoint?\n\n"
                   " Format: Root Cause Endpoint: XXX, Root Cause Reason: XXX\n\n")


def match_component(answer: str, candidates):
    """Extract the root-cause entity from the answer and map it to a candidate."""
    m = re.findall(r"Root Cause Endpoint\s*[:：]\s*([A-Za-z0-9_\-\.]+)", answer or "")
    raw = m[-1] if m else None
    if raw is None:
        # fallback: any candidate name literally mentioned in the answer
        hits = [c for c in candidates if c in (answer or "")]
        return max(hits, key=len) if hits else None, None
    raw_clean = raw.strip().strip(".,;")
    for c in candidates:
        if raw_clean == c:
            return c, raw_clean
    for c in candidates:
        if raw_clean.lower() == c.lower():
            return c, raw_clean
    # containment (e.g. answer says "db_003 (database)" or "pod shippingservice-1")
    hits = [c for c in candidates if c in raw_clean or raw_clean in c]
    if hits:
        return max(hits, key=len), raw_clean
    hits = [c for c in candidates if c.lower() in (answer or "").lower()]
    return (max(hits, key=len) if hits else None), raw_clean


def run_one(idx, entry, candidates):
    """Run the two-stage mABC flow for one query; return the result record."""
    t, endpoint = entry["time"], entry["alert_endpoint"]
    question = QUESTION_TEMPLATE.format(endpoint=endpoint, t=t)

    agent = ProcessScheduler()
    agents = [DataDetective(), DependencyExplorer(), ProbabilityOracle(),
              FaultMapper(), ProcessScheduler(), SolutionEngineer()]
    answer1 = ReActTotRun().run(
        agent=agent, question=question,
        agent_tool_env=vars(process_scheduler_tools),
        eval_run=ThreeHotCotRun(0, 0), agents=agents)

    answer2 = ReActTotRun().run(
        agent=SolutionEngineer(), question=STAGE2_TEMPLATE + answer1,
        agent_tool_env=vars(solution_engineer_tools),
        eval_run=ThreeHotCotRun(), agents=[SolutionEngineer()])

    pred, raw = match_component(answer2, candidates)
    if pred is None:  # second chance: parse the stage-1 answer
        pred, raw = match_component(answer1, candidates)
    return answer1, answer2, pred, raw


def main():
    index_path = os.path.join(HERE, "data_files", ARGS.dataset, "label_index.json")
    with open(index_path) as f:
        label_index = json.load(f)
    candidates = set(od.candidate_inventory(ARGS.dataset))
    end = len(label_index) if ARGS.end is None else min(ARGS.end, len(label_index))
    out = ARGS.out or os.path.join(os.path.dirname(HERE), "results",
                                   f"mabc_{ARGS.dataset}.jsonl")
    os.makedirs(os.path.dirname(out), exist_ok=True)

    done = set()
    if os.path.exists(out):
        with open(out) as f:
            for line in f:
                try:
                    done.add(json.loads(line)["idx"])
                except Exception:
                    pass

    with open(out, "a") as fout:
        for idx in range(ARGS.start, end):
            if idx in done:
                print(f"[skip] idx={idx}", flush=True)
                continue
            entry = label_index[idx]
            reset_token_usage()
            t0 = time.time()
            try:
                answer1, answer2, pred, raw = run_one(idx, entry, candidates)
                rec = {
                    "idx": idx, "dataset": ARGS.dataset, "method": "mabc",
                    "task_index": od.load_queries(ARGS.dataset).iloc[idx]["task_index"],
                    "gt_component": entry["gt_component"], "gt_level": entry["gt_level"],
                    "gt_reason": entry["gt_reason"], "gt_time": entry["gt_time"],
                    "window": entry["window"], "alert_endpoint": entry["alert_endpoint"],
                    "top1": pred, "raw_answer_endpoint": raw,
                    "ranked_entities": [pred] if pred else [],
                    "gt_rank": 1 if pred == entry["gt_component"] else None,
                    "hit@1": int(pred == entry["gt_component"]),
                    "hit@3": int(pred == entry["gt_component"]),
                    "hit@5": int(pred == entry["gt_component"]),
                    "tokens": dict(TOKEN_USAGE),
                    "runtime_s": round(time.time() - t0, 2),
                    "status": "ok",
                }
                log_dir = os.path.join(HERE, "logs", ARGS.dataset)
                os.makedirs(log_dir, exist_ok=True)
                with open(os.path.join(log_dir, f"query_{idx}.log"), "w") as lf:
                    lf.write(f"=== stage1 ===\n{answer1}\n\n=== stage2 ===\n{answer2}\n")
            except Exception as e:
                rec = {"idx": idx, "dataset": ARGS.dataset, "method": "mabc",
                       "gt_component": entry["gt_component"], "gt_level": entry["gt_level"],
                       "gt_reason": entry["gt_reason"], "gt_time": entry["gt_time"],
                       "status": "error", "error": f"{type(e).__name__}: {e}",
                       "trace": traceback.format_exc()[-2000:],
                       "tokens": dict(TOKEN_USAGE),
                       "runtime_s": round(time.time() - t0, 2)}
            fout.write(json.dumps(rec) + "\n")
            fout.flush()
            print(f"[done] idx={idx} status={rec['status']} pred={rec.get('top1')} "
                  f"gt={rec['gt_component']} tokens={rec['tokens']['total_tokens']} "
                  f"rt={rec['runtime_s']}s", flush=True)


if __name__ == "__main__":
    main()
