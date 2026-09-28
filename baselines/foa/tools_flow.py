"""
SOP-flow tools for the FoA reproduction (paper Table 1):

    match_sop(query)            -> matched SOPs (retrieval, no LLM)
    generate_sop(fault_info)    -> new SOP (LLM, existing SOPs as few-shot)
    generate_sop_code(sop)      -> executable Python code (LLM / CodeAgent)
    run_sop(code)               -> observation text (executes code)
    match_observation(obs)      -> similar historical incidents (retrieval)

The paper computes embedding similarity over SOP names / incident
manifestations; here we use TF-IDF cosine similarity (scikit-learn), a
documented substitution since the knowledge bases are small.
"""

import io
import re
from contextlib import redirect_stdout

from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.metrics.pairwise import cosine_similarity

import tools_data
from knowledge import INCIDENTS, SOPS
from llm import llm_chat
from settings import (FOA_INCIDENT_THRESHOLD, FOA_INCIDENT_TOP_K,
                      FOA_SOP_THRESHOLD, FOA_SOP_TOP_K)

# SOPs generated at runtime are appended here so later match_sop can find them.
RUNTIME_SOPS = []


def _retrieve(query: str, docs: list, top_k: int, threshold: float):
    corpus = docs + [query]
    vec = TfidfVectorizer().fit_transform(corpus)
    sims = cosine_similarity(vec[-1], vec[:-1])[0]
    order = sims.argsort()[::-1]
    return [(i, float(sims[i])) for i in order[:top_k] if sims[i] >= threshold]


def _fmt_sop(sop) -> str:
    steps = "\n".join(f"{i + 1}. {s}" for i, s in enumerate(sop["steps"]))
    return f"Name: {sop['name']}\n{steps}"


def match_sop(query: str) -> str:
    all_sops = SOPS + RUNTIME_SOPS
    hits = _retrieve(query, [s["name"] for s in all_sops], FOA_SOP_TOP_K, FOA_SOP_THRESHOLD)
    if not hits:
        return "Matched SOPs:\n(None matched the query; consider generate_sop)"
    lines = ["Matched SOPs:"]
    for rank, (i, score) in enumerate(hits):
        lines.append(f"## SOP Score = {score:.2f}\n{_fmt_sop(all_sops[i])}")
    return "\n\n".join(lines)


GENERATE_SOP_PROMPT = """You are an SRE expert writing a Standard Operating Procedure (SOP) for root cause analysis.
An SOP has a Name and a numbered list of steps. Steps reference the available tools:
- whether_is_abnormal_metric(start_time, end_time, metric): check if a metric group (cpu/memory/disk/network/database/jvm/latency) is anomalous.
- collect_trace(start_time, end_time, entity): collect trace statistics of an entity.
- collect_logs(start_time, end_time, entity): collect anomalous logs of an entity.
By convention the last step states that the answer is the observations obtained from former steps.

Here are example SOPs:
{examples}

Write ONE new SOP for the following fault information. Output only the SOP.
Fault information: {fault_info}
"""


def generate_sop(fault_info: str) -> str:
    examples = "\n\n".join(_fmt_sop(s) for s in SOPS[:3])
    answer = llm_chat([{"role": "user", "content": GENERATE_SOP_PROMPT.format(
        examples=examples, fault_info=fault_info)}])
    # register the generated SOP for later retrieval
    name_m = re.search(r"Name:\s*(.+)", answer or "")
    steps = [ln.strip() for ln in (answer or "").splitlines()
             if re.match(r"^\d+[\.\)]", ln.strip())]
    steps = [re.sub(r"^\d+[\.\)]\s*", "", s) for s in steps]
    if name_m and steps:
        name = name_m.group(1).strip()
        known = {s["name"] for s in SOPS + RUNTIME_SOPS}
        if name not in known:
            RUNTIME_SOPS.append({"name": name, "steps": steps})
    return answer


GENERATE_SOP_CODE_PROMPT = """You are the Code Agent. Convert the given SOP into ONE self-contained Python snippet.
Available functions (already imported, do NOT redefine or import anything):
- whether_is_abnormal_metric(start_time, end_time, metric) -> str
- collect_trace(start_time, end_time, entity) -> str
- collect_logs(start_time, end_time, entity) -> str
- get_relevant_metric(query) -> str
- pod_analyze(start_time, end_time) -> str
- node_analyze(start_time, end_time) -> str
- service_analyze(start_time, end_time) -> str
- deployment_analyze(start_time, end_time) / statefulset_analyze(start_time, end_time) -> str (offline stubs)
- get_all_namespace() -> str
Times are strings "YYYY-MM-DD HH:MM:SS" (UTC+8) or unix seconds.
The incident window is: start_time={start}, end_time={end}.
Rules:
- Call the tools in the order given by the SOP steps.
- Collect every tool's textual result.
- The snippet MUST end by assigning the combined text to a variable named `answer`, e.g.
  answer = rtt_status + "\\n" + trace_status
- No printing, no plotting, no file I/O, no imports.
SOP:
{sop}
"""


def generate_sop_code(sop: str, start: str = None, end: str = None) -> str:
    prompt = GENERATE_SOP_CODE_PROMPT.format(sop=sop, start=start, end=end)
    answer = llm_chat([{"role": "user", "content": prompt}])
    m = re.search(r"```(?:python)?\s*(.*?)```", answer or "", re.DOTALL)
    return (m.group(1) if m else answer or "").strip()


def run_sop(code: str) -> str:
    """Execute SOP code with the data tools in scope; return the observation text."""
    env = {
        "whether_is_abnormal_metric": tools_data.whether_is_abnormal_metric,
        "collect_trace": tools_data.collect_trace,
        "collect_logs": tools_data.collect_logs,
        "get_relevant_metric": tools_data.get_relevant_metric,
        "pod_analyze": tools_data.pod_analyze,
        "node_analyze": tools_data.node_analyze,
        "service_analyze": tools_data.service_analyze,
        "deployment_analyze": tools_data.deployment_analyze,
        "statefulset_analyze": tools_data.statefulset_analyze,
        "run_kubectl_command": tools_data.run_kubectl_command,
        "get_all_namespace": tools_data.get_all_namespace,
    }
    buf = io.StringIO()
    try:
        with redirect_stdout(buf):
            exec(code, env)  # noqa: S102 - trusted LLM-generated SOP code
        result = env.get("answer", None)
        if result is None:
            result = buf.getvalue().strip() or "(code ran without producing an `answer`)"
        return str(result)[:4000]
    except Exception as e:
        return f"ERROR while running SOP code: {type(e).__name__}: {e}"


def match_observation(observation: str) -> str:
    hits = _retrieve(observation[:2000], [i["manifestation"] for i in INCIDENTS],
                     FOA_INCIDENT_TOP_K, FOA_INCIDENT_THRESHOLD)
    if not hits:
        return "Similar historical incidents:\n(None matched above threshold)"
    lines = ["Similar historical incidents:"]
    for i, score in hits:
        lines.append(f"- score={score:.2f}  type: {INCIDENTS[i]['type']}  "
                     f"(manifestation: {INCIDENTS[i]['manifestation']})")
    return "\n".join(lines)
