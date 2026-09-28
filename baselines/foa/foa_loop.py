"""
The FoA main loop: Thought -> ActionSet -> Action -> Observation, with the
paper's SOP-flow rules (Fig. 5) enforced as code, JudgeAgent/ObAgent triggered
after match_observation, Speak as the terminal action, and a hard step cap.
"""

import json
import re

import agents
import tools_flow
from settings import FOA_ACTION_SET_SIZE, FOA_MAX_ROOT_CAUSES, FOA_MAX_STEPS

FLOW_ACTIONS = {"match_sop", "generate_sop", "generate_sop_code", "run_sop",
                "match_observation", "Speak"}


def mandated_next(last_action: str, last_obs: str):
    """The paper's Fig. 5 rules as a function: the mandatory next action."""
    if last_action is None:
        return "match_sop"
    if last_action == "match_sop":
        return "generate_sop" if "(None matched" in last_obs else "generate_sop_code"
    if last_action == "generate_sop_code":
        return "run_sop"
    if last_action == "run_sop":
        return "generate_sop_code" if last_obs.startswith("ERROR") else "match_observation"
    if last_action == "match_observation":
        return "match_sop"
    if last_action == "generate_sop":
        return "generate_sop_code"
    return None


def _pick_sop(action_input, last_matched, executed, last_obs):
    """Resolve which SOP generate_sop_code should convert, honoring the
    paper's rule "you shouldn't execute one SOP twice"."""
    all_sops = {s["name"]: s for s in tools_flow.SOPS + tools_flow.RUNTIME_SOPS}
    # the LLM pasted a full SOP text
    if action_input and "1." in action_input:
        name_m = re.search(r"Name:\s*(.+)", action_input)
        name = name_m.group(1).strip() if name_m else action_input[:60]
        return action_input, name, None
    name = (action_input or "").strip()
    if name in executed:
        name = ""
    if not name or name not in all_sops:
        remaining = [n for n in last_matched if n not in executed]
        name = remaining[0] if remaining else ""
    if not name and "Name:" in last_obs and "1." in last_obs:
        # the last observation is itself a freshly generated SOP
        name_m = re.search(r"Name:\s*(.+)", last_obs)
        name = name_m.group(1).strip() if name_m else "generated SOP"
        return last_obs, name, None
    if not name:
        return None, None, ("No unexecuted SOP available; per the rules, "
                            "use generate_sop to create a new SOP.")
    sop = all_sops.get(name)
    if sop is None:
        return None, None, f"SOP '{name}' not found."
    return tools_flow._fmt_sop(sop), name, None


def run_foa(task: str, start_str: str, end_str: str, candidates: list,
            reasons: list, max_steps: int = FOA_MAX_STEPS, verbose: bool = True):
    """Run one FoA diagnosis. Returns (final_answer_text, trajectory list)."""
    history = []          # list of dicts: thought/action/action_input/observation
    last_action, last_obs = None, ""
    judge_found, judge_note, ob_note = False, "", ""
    executed_sops = set()
    last_matched = []     # SOP names from the most recent match_sop
    final_answer = ""

    for step in range(max_steps):
        history_text = "\n".join(
            f"[{i}] Thought: {h['thought'][:200]}\n    Action: {h['action']} -> Observation: {h['observation'][:300]}"
            for i, h in enumerate(history[-6:])) or "(no actions yet)"
        mandated = mandated_next(last_action, last_obs)

        # ---- ActionSet: ActionAgent suggestions + flow-rule enforcement ----
        suggestions = agents.action_agent(task, history_text, last_action,
                                          last_obs[:400], mandated,
                                          FOA_ACTION_SET_SIZE)
        action_set, seen = [], set()
        if mandated:
            action_set.append((mandated, "mandated by the SOP flow rules"))
            seen.add(mandated)
        for name, reason in suggestions:
            if name in FLOW_ACTIONS and name not in seen:
                action_set.append((name, reason))
                seen.add(name)
        if judge_found and "Speak" not in seen:
            action_set.append(("Speak", "the Judge Agent confirmed the root cause"))
            seen.add("Speak")
        action_set = action_set[:FOA_ACTION_SET_SIZE]

        # ---- MainAgent: Thought + final action selection ----
        thought, action, action_input = agents.main_agent_select(
            task, history_text, action_set, judge_note, ob_note)

        # ---- execute the action ----
        if action == "match_sop":
            # per the rules the query is the current fault information; once
            # the ObAgent has judged an anomaly class, match its SOP
            query = (action_input or "").strip()
            if not query or query == task:
                m = re.search(r"Anomaly class:\s*(.+)", ob_note or "")
                query = m.group(1).strip() if m else (query or task)
            obs = tools_flow.match_sop(query)
            last_matched = re.findall(r"Name:\s*(.+)", obs)
        elif action == "generate_sop":
            obs = tools_flow.generate_sop(action_input or ob_note or task)
            last_matched = []  # the fresh SOP is picked up via last_obs
        elif action == "generate_sop_code":
            sop_text, sop_name, guidance = _pick_sop(
                action_input, last_matched, executed_sops, last_obs)
            if guidance:
                obs = guidance
            elif sop_name in executed_sops:
                obs = (f"SOP '{sop_name}' was already executed; per the rules, "
                       f"choose another one or use generate_sop.")
            else:
                executed_sops.add(sop_name)
                obs = tools_flow.generate_sop_code(sop_text, start_str, end_str)
        elif action == "run_sop":
            code = action_input if "answer" in (action_input or "") else last_obs
            obs = tools_flow.run_sop(code)
        elif action == "match_observation":
            obs = tools_flow.match_observation(action_input or last_obs)
        elif action == "Speak":
            final_answer = _finalize(task, history, candidates, reasons)
            history.append({"thought": thought, "action": "Speak",
                            "action_input": "", "observation": final_answer})
            break
        else:
            obs = f"unknown action '{action}'"

        history.append({"thought": thought, "action": action,
                        "action_input": (action_input or "")[:500],
                        "observation": obs})
        if verbose:
            print(f"[foa step {step}] action={action} obs={obs[:120]!r}", flush=True)

        # ---- JudgeAgent / ObAgent after match_observation (paper Fig. 3) ----
        if action == "match_observation":
            # last_obs still holds the run_sop observation being matched
            ob_note = agents.ob_agent(last_obs, obs)
            judge_found, judge_note = agents.judge_agent(task, history_text + "\n" + ob_note)
            if judge_found:
                judge_note = "Judge Agent: root cause identified. " + judge_note
        last_action, last_obs = action, obs
    else:
        final_answer = _finalize(task, history, candidates, reasons)

    return final_answer, history


def _finalize(task: str, history: list, candidates: list, reasons: list) -> str:
    """Produce the final root-cause report in the OpenRCA answer format."""
    history_text = "\n".join(
        f"[{i}] Action: {h['action']} -> Observation: {h['observation'][:400]}"
        for i, h in enumerate(history))
    prompt = f"""You are the Main Agent. Based on the whole diagnosis, report the final root cause(s).
The incident under analysis: {task}
Diagnosis history:
{history_text}
Candidate root cause components (choose only from this list): {json.dumps(candidates, ensure_ascii=False)}
Known root cause reason vocabulary (choose the closest): {json.dumps(reasons, ensure_ascii=False)}
Report at most {FOA_MAX_ROOT_CAUSES} root causes, ordered by likelihood. Output ONLY a JSON object of the form:
{{"1": {{"root cause occurrence datetime": "YYYY-MM-DD HH:MM:SS", "root cause component": "<from candidate list>", "root cause reason": "<from vocabulary>"}}, "2": {{...}}}}"""
    answer = agents.llm_chat([{"role": "user", "content": prompt}]) or ""
    m = re.search(r"\{.*\}", answer, re.DOTALL)
    return m.group(0) if m else answer
