"""Minimal OpenRouter chat-completions client, used for the LLM judge.

It exposes the same generate(...) -> LLMTurn interface as GeminiLLM (text only,
no tools), so the Judge doesn't care which provider it's talking to.
"""

import os
import time

import httpx

from . import config
from .llm import LLMTurn, cost_usd

BASE_URL = "https://openrouter.ai/api/v1"
RETRY_STATUS = {408, 429, 500, 502, 503, 504}


def _api_key() -> str:
    key = os.environ.get("OPENROUTER_API_KEY")
    if not key:
        raise RuntimeError("Set OPENROUTER_API_KEY (create one at https://openrouter.ai/settings/keys).")
    return key


def get_model_info(model: str) -> dict | None:
    """The model's entry from /api/v1/models, or None if the slug isn't listed."""
    resp = httpx.get(f"{BASE_URL}/models", timeout=60)
    resp.raise_for_status()
    return next((m for m in resp.json()["data"] if m["id"] == model), None)


class OpenRouterLLM:
    def __init__(self, model: str, reasoning_effort: str | None = None, attempts: int = 6,
                 transport: httpx.BaseTransport | None = None):
        self.model = model
        self.reasoning_effort = reasoning_effort
        # Read by the Judge's cache key, alongside the model id.
        self.thinking_level = reasoning_effort
        self.attempts = attempts
        self.http = httpx.Client(base_url=BASE_URL, timeout=180, transport=transport, headers={
            "Authorization": f"Bearer {_api_key()}",
            "X-Title": "trust-the-source",
        })

    def generate(self, *, system: str, contents: list, seed: int | None = None,
                 json_schema: dict | None = None, **_unused) -> LLMTurn:
        messages = [{"role": "system", "content": system}]
        for c in contents:
            text = "".join(p.text for p in c.parts or [] if p.text)
            messages.append({"role": "assistant" if c.role == "model" else "user", "content": text})
        body = {"model": self.model, "messages": messages, "seed": seed}
        if self.reasoning_effort:
            body["reasoning"] = {"effort": self.reasoning_effort}
        if json_schema:
            body["response_format"] = {"type": "json_schema", "json_schema": {
                "name": "labels", "strict": True, "schema": json_schema}}

        t0 = time.monotonic()
        data = self._post(body)
        latency = time.monotonic() - t0

        choice = data["choices"][0]
        text = choice["message"].get("content") or ""
        u = data.get("usage") or {}
        details = u.get("completion_tokens_details") or {}
        reasoning = details.get("reasoning_tokens") or 0
        usage = {
            "prompt": u.get("prompt_tokens", 0),
            # completion_tokens includes reasoning tokens; split them out to match the Gemini usage dict.
            "output": max(u.get("completion_tokens", 0) - reasoning, 0),
            "thoughts": reasoning,
            "tool_use_prompt": 0,
            "cached": (u.get("prompt_tokens_details") or {}).get("cached_tokens", 0),
        }
        # Prefer the cost OpenRouter reports; fall back to the price table.
        cost = u.get("cost") if u.get("cost") is not None else cost_usd(usage, self.model)
        record = {
            "model": self.model,
            "model_version": data.get("model"),
            "provider": data.get("provider"),
            "config": {"seed": seed, "reasoning_effort": self.reasoning_effort or "default",
                       "json_schema": bool(json_schema)},
            "system": system,
            "request_messages": messages,
            "response_text": text,
            "finish_reason": choice.get("finish_reason"),
            "usage": usage,
            "cost_usd": cost,
            "latency_s": round(latency, 3),
        }
        return LLMTurn(content=None, text=text, function_calls=[], usage=usage,
                       latency_s=latency, record=record)

    def _post(self, body: dict) -> dict:
        delay = 2.0
        for attempt in range(self.attempts):
            resp = self.http.post("/chat/completions", json=body)
            if resp.status_code in RETRY_STATUS and attempt < self.attempts - 1:
                time.sleep(delay)
                delay = min(delay * 2, 60)
                continue
            resp.raise_for_status()
            data = resp.json()
            # OpenRouter can return 200 with an error object (e.g. upstream provider failure).
            if "error" in data and not data.get("choices"):
                if attempt < self.attempts - 1:
                    time.sleep(delay)
                    delay = min(delay * 2, 60)
                    continue
                raise RuntimeError(f"OpenRouter error: {data['error']}")
            return data
        raise RuntimeError("unreachable")
