"""
Agent prompts and call wrappers for the FoA reproduction.

The paper specifies the agents' roles and the exact SOP-flow rules (its
Fig. 5), but does not disclose the agents' full prompts; the prompts below
are authored to the paper's role descriptions and the utterance style of its
Fig. 4 examples. MainAgent / ActionAgent both receive the verbatim flow rules.
"""

import json
import re

from llm import llm_chat

# Verbatim SOP-flow rules from the FoA paper (Fig. 5), with the note that
# `Speak` is the terminal action reporting the root cause.
FLOW_RULES = """Rules and Format Instructions for Tool Using

If at the beginning and last action doesn't exist:
    next action should be match_sop
elif last action == match_sop:
    last observations are all matched SOPs
    next action should be generate_sop_code  # Parameters: cause_name of the SOP document should be the unexecuted SOP with higher score, you shouldn't execute one SOP twice. If one SOP has been executed already, choose another one.
    If no SOPs matched or the SOPs are not relevant:
        next action should be generate_sop
elif last action == generate_sop_code:
    last observations are code
    next action should be run_sop
elif last action == run_sop:
    last observations are result after running code
    if some error happend:
        next action should be generate_sop_code  # regenerate the right code
    else:
        next action should be match_observation  # Parameters: the query should be the whole original observation without any delete
elif last action == match_observation:
    last observations are possible anomaly class
    next action should be match_sop  # match SOP of the possible anomaly class
elif last action == generate_sop:
    last observation is the new SOPs you got.
    next action should be generate_sop_code to generate the code

Additionally: if the Judge Agent has confirmed the root cause, `Speak` (report the final root cause) may be selected as the next action.
"""

TOOL_DOC = """Available flow actions:
- match_sop(query): retrieve relevant SOPs by fault type/information.
- generate_sop(fault_info): generate a new SOP when none is relevant.
- generate_sop_code(sop): convert an SOP (paste its full text) into executable code.
- run_sop(code): execute the SOP code and obtain the observation.
- match_observation(observation): retrieve similar historical incidents for an observation.
- Speak: report the final root cause (terminal action).
"""


def action_agent(task: str, history_text: str, last_action: str, last_obs: str,
                 mandated: str, n: int) -> list:
    """ActionAgent: suggest up to n candidate actions, each with a reason."""
    prompt = f"""You are the Action Agent in a root cause analysis team. Suggest the most reasonable next actions.
{FLOW_RULES}
{TOOL_DOC}
The incident under analysis: {task}
Progress so far:
{history_text}
Last action: {last_action or "(none, at the beginning)"}
Last observation: {last_obs[:800]}
A rule-based mandatory candidate is: {mandated}
Suggest up to {n} next actions as a JSON object mapping action name to a short reason, e.g.
{{"match_sop": "When you got the information of the anomaly, suggesting use this to get SOP.", "run_sop": "Suggesting use this to get the result."}}
Output only the JSON object."""
    answer = llm_chat([{"role": "user", "content": prompt}])
    m = re.search(r"\{.*\}", answer or "", re.DOTALL)
    suggestions = []
    if m:
        try:
            obj = json.loads(m.group(0))
            suggestions = [(k, str(v)) for k, v in obj.items()]
        except Exception:
            pass
    return suggestions


def main_agent_select(task: str, history_text: str, action_set: list,
                      judge_note: str, ob_note: str) -> tuple:
    """MainAgent: produce a Thought and select one action from the action set."""
    names = [a for a, _ in action_set]
    prompt = f"""You are the Main Agent of a root cause analysis team, the only decision maker.
{FLOW_RULES}
{TOOL_DOC}
The incident under analysis: {task}
Progress so far:
{history_text}
Advice from other experts:
{judge_note}
{ob_note}
Candidate action set (with the experts' reasons): {json.dumps(action_set, ensure_ascii=False)}
Think step by step about the current situation, then choose ONE action from the candidate set.
Answer in the format:
Thought: <your reasoning>
Action: <one of {names}>
Action Input: <the input to the action, e.g. the query text, the SOP text, or the code>"""
    answer = llm_chat([{"role": "user", "content": prompt}])
    thought, action, action_input = "", None, ""
    m = re.search(r"Thought:\s*(.*?)(?:\nAction:|$)", answer or "", re.DOTALL)
    if m:
        thought = m.group(1).strip()
    m = re.search(r"\nAction:\s*([A-Za-z_]+)", answer or "")
    if m:
        action = m.group(1).strip()
    m = re.search(r"Action Input:\s*(.*)", answer or "", re.DOTALL)
    if m:
        action_input = m.group(1).strip()
    if action not in names:  # fall back to the first (mandated) candidate
        action = names[0] if names else "match_sop"
    return thought, action, action_input


def ob_agent(observation: str, similar_incidents: str) -> str:
    """ObAgent: filter noise, judge the potential anomaly class."""
    prompt = f"""You are the Observation Agent. Examine the observation and the similar historical incidents,
remove useless noise, and state the potential anomaly class (fault type) in one line, then a short justification.
Observation:
{observation[:2000]}
{similar_incidents}
Answer in the format:
Anomaly class: <concise fault type>
Key information: <the essential evidence, <=3 bullet points>"""
    return llm_chat([{"role": "user", "content": prompt}]) or ""


def judge_agent(task: str, history_text: str) -> tuple:
    """JudgeAgent: decide whether the root cause has been pinpointed."""
    prompt = f"""You are the Judge Agent in a root cause analysis team. Decide whether the root cause has been pinpointed.
The incident under analysis: {task}
Progress so far:
{history_text}
Answer in the format:
Found: Yes/No
Analysis: <if Yes, state the root cause entity, the fault type, and the estimated occurrence time; if No, what is missing>"""
    answer = llm_chat([{"role": "user", "content": prompt}]) or ""
    found = bool(re.search(r"Found:\s*Yes", answer, re.I))
    return found, answer
