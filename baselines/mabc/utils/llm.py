"""
LLM call layer for mABC (adapted from the original utils/llm.py).

Changes versus the original:
  * OpenAI-compatible ``base_url`` support (settings.OPENAI_BASE_URL);
  * optional temperature (skipped for reasoning models such as deepseek-r1);
  * empty stop-word strings are not forwarded (some providers reject them);
  * token usage is accumulated in the module-level TOKEN_USAGE dict so the
    batch driver can report per-query cost;
  * the per-call full-completion print is removed (logged compactly instead).
"""

import time

from openai import OpenAI

from settings import (MABC_THINKING, OPENAI_API_KEY, OPENAI_BASE_URL,
                      OPENAI_MAX_RETRIES, OPENAI_MODEL, OPENAI_RETRY_SLEEP,
                      OPENAI_TEMPERATURE)

TOKEN_USAGE = {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0, "calls": 0}


def reset_token_usage():
    for k in TOKEN_USAGE:
        TOKEN_USAGE[k] = 0


def llm_chat(shared_messages, stop_words):
    for i in range(OPENAI_MAX_RETRIES):
        try:
            client = OpenAI(api_key=OPENAI_API_KEY, base_url=OPENAI_BASE_URL)
            kwargs = {"model": OPENAI_MODEL, "messages": shared_messages}
            if not MABC_THINKING:
                kwargs["extra_body"] = {"thinking": {"type": "disabled"}}
            if stop_words:
                # the GLM endpoint requires stop as a JSON array, not a string
                kwargs["stop"] = [stop_words] if isinstance(stop_words, str) else stop_words
            if OPENAI_TEMPERATURE is not None:
                kwargs["temperature"] = OPENAI_TEMPERATURE
            completion = client.chat.completions.create(**kwargs)
            usage = getattr(completion, "usage", None)
            if usage is not None:
                TOKEN_USAGE["prompt_tokens"] += getattr(usage, "prompt_tokens", 0) or 0
                TOKEN_USAGE["completion_tokens"] += getattr(usage, "completion_tokens", 0) or 0
                TOKEN_USAGE["total_tokens"] += getattr(usage, "total_tokens", 0) or 0
            TOKEN_USAGE["calls"] += 1
            return completion.choices[0].message.content
        except Exception as e:
            print(f"[llm_chat] attempt {i + 1}/{OPENAI_MAX_RETRIES} failed: {e}")
            time.sleep(OPENAI_RETRY_SLEEP)
            continue
    return "Connection error."
