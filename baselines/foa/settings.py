"""
Flow-of-Action (FoA) reproduction settings.

LLM endpoint defaults follow the active block of rca/api_config.yaml
(GLM coding endpoint, glm-4.5), overridable via environment variables.
Hyper-parameters follow the FoA paper (WWW 2025 Companion): action set
size 5, max 20 steps, at most 3 reported root causes.
"""

import os

FOA_API_KEY = os.environ.get("FOA_API_KEY", "cf20faf4ad594579889da7384ee285fb.7W3HPHtLNdntOyqg")
FOA_API_BASE = os.environ.get("FOA_API_BASE", "https://open.bigmodel.cn/api/coding/paas/v4")
FOA_MODEL = os.environ.get("FOA_MODEL", "glm-4.5")
FOA_TEMPERATURE = float(os.environ.get("FOA_TEMPERATURE", "0.0"))
FOA_MAX_RETRIES = 8
FOA_RETRY_SLEEP = 20

# paper hyper-parameters
FOA_MAX_STEPS = int(os.environ.get("FOA_MAX_STEPS", "20"))
FOA_ACTION_SET_SIZE = int(os.environ.get("FOA_ACTION_SET_SIZE", "5"))
FOA_MAX_ROOT_CAUSES = int(os.environ.get("FOA_MAX_ROOT_CAUSES", "3"))
# match_sop / match_observation retrieval: top-k and similarity threshold
# (the paper does not disclose values; these are our documented choices)
FOA_SOP_TOP_K = int(os.environ.get("FOA_SOP_TOP_K", "3"))
FOA_SOP_THRESHOLD = float(os.environ.get("FOA_SOP_THRESHOLD", "0.08"))
FOA_INCIDENT_TOP_K = int(os.environ.get("FOA_INCIDENT_TOP_K", "3"))
FOA_INCIDENT_THRESHOLD = float(os.environ.get("FOA_INCIDENT_THRESHOLD", "0.05"))
# GLM-4.5 thinking mode: disabled by default for cost/latency (10-25x cheaper);
# set FOA_THINKING=1 to enable.
FOA_THINKING = os.environ.get("FOA_THINKING", "0") == "1"
