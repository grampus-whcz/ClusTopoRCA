"""OpenAI-compatible LLM call layer for the FoA reproduction (with token accounting)."""

import time

from openai import OpenAI

from settings import (FOA_API_BASE, FOA_API_KEY, FOA_MAX_RETRIES, FOA_MODEL,
                      FOA_RETRY_SLEEP, FOA_TEMPERATURE, FOA_THINKING)

TOKEN_USAGE = {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0, "calls": 0}


def reset_token_usage():
    for k in TOKEN_USAGE:
        TOKEN_USAGE[k] = 0


def llm_chat(messages, stop_words=None):
    last_err = None
    for i in range(FOA_MAX_RETRIES):
        try:
            client = OpenAI(api_key=FOA_API_KEY, base_url=FOA_API_BASE, timeout=120)
            kwargs = {"model": FOA_MODEL, "messages": messages,
                      "temperature": FOA_TEMPERATURE}
            if not FOA_THINKING:
                kwargs["extra_body"] = {"thinking": {"type": "disabled"}}
            if stop_words:
                # the GLM endpoint requires stop as a JSON array, not a string
                kwargs["stop"] = [stop_words] if isinstance(stop_words, str) else stop_words
            completion = client.chat.completions.create(**kwargs)
            usage = getattr(completion, "usage", None)
            if usage is not None:
                TOKEN_USAGE["prompt_tokens"] += getattr(usage, "prompt_tokens", 0) or 0
                TOKEN_USAGE["completion_tokens"] += getattr(usage, "completion_tokens", 0) or 0
                TOKEN_USAGE["total_tokens"] += getattr(usage, "total_tokens", 0) or 0
            TOKEN_USAGE["calls"] += 1
            return completion.choices[0].message.content
        except Exception as e:
            last_err = e
            print(f"[llm_chat] attempt {i + 1}/{FOA_MAX_RETRIES} failed: {str(e)[:150]}")
            time.sleep(FOA_RETRY_SLEEP)
    return f"Connection error: {last_err}"
