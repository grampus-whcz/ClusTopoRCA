"""
mABC runtime settings (adapted).

LLM endpoint is configurable via environment variables so the same code runs
with any OpenAI-compatible API. Defaults reproduce the api_config.yaml entry
that is active in the ClusTopoRCA repository (aliyun bailian deepseek-r1-0528).

MABC_DATASET selects which preprocessed OpenRCA dataset the data-layer
explorers serve (see build_data.py).
"""

import os

# --- LLM endpoint (OpenAI-compatible) ---------------------------------------
# Defaults follow the active block of rca/api_config.yaml (GLM coding
# endpoint, glm-4.5); the OpenAI-compatible API of the same endpoint is used
# instead of the zhipuai SDK (equivalent, cf. rca/api_router.py).
OPENAI_API_KEY = os.environ.get("MABC_API_KEY", "cf20faf4ad594579889da7384ee285fb.7W3HPHtLNdntOyqg")
OPENAI_BASE_URL = os.environ.get("MABC_API_BASE", "https://open.bigmodel.cn/api/coding/paas/v4")
OPENAI_MODEL = os.environ.get("MABC_MODEL", "glm-4.5")

OPENAI_MAX_RETRIES = 10
OPENAI_RETRY_SLEEP = 30
# Project convention (rca/api_router.py get_chat_completion) is temperature=0.
OPENAI_TEMPERATURE = float(os.environ.get("MABC_TEMPERATURE", "0.0"))

# --- run control -------------------------------------------------------------
# Maximum ReAct recursion depth per agent run (the original code recurses
# without a bound until the LLM emits "Final Answer").
MABC_MAX_STEPS = int(os.environ.get("MABC_MAX_STEPS", "15"))
# Blockchain-inspired voting: disabled by default, matching the released code
# (eval_run.run(...) is commented out upstream). Set MABC_VOTING=1 plus
# MABC_ALPHA/MABC_BETA to enable the repaired implementation.
MABC_VOTING = os.environ.get("MABC_VOTING", "0") == "1"
MABC_ALPHA = float(os.environ.get("MABC_ALPHA", "0.5"))
MABC_BETA = float(os.environ.get("MABC_BETA", "0.5"))

# --- data layer ---------------------------------------------------------------
MABC_DATASET = os.environ.get("MABC_DATASET", "Bank")
_HERE = os.path.dirname(os.path.abspath(__file__))
MABC_DATA_DIR = os.path.join(_HERE, "data_files", MABC_DATASET)
# GLM-4.5 thinking mode: disabled by default for cost/latency; MABC_THINKING=1 to enable.
MABC_THINKING = os.environ.get("MABC_THINKING", "0") == "1"
