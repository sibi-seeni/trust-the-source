"""OpenRouter chat-completions client (OpenAI-compatible), used for every model:
the model under test, the A6/A7 verifier and the judge.

Tool calling is handled manually so every request, tool call and response can be
logged. The assistant message is appended to the history exactly as returned,
including `reasoning_details`, which OpenRouter needs back to keep reasoning
models (e.g. Gemini's thought signatures) consistent across tool-calling turns.
"""

import json
import os
import threading
import time
from dataclasses import dataclass

import httpx

from . import config

BASE_URL = "https://openrouter.ai/api/v1"
RETRY_STATUS = {408, 429, 500, 502, 503, 504}


def api_key() -> str:
    key = os.environ.get("OPENROUTER_API_KEY")
    if not key:
        raise RuntimeError("Set OPENROUTER_API_KEY (create one at https://openrouter.ai/settings/keys).")
    return key


def list_models() -> dict:
    """slug -> entry from /api/v1/models (public, no key needed)."""
    resp = httpx.get(f"{BASE_URL}/models", timeout=60)
    resp.raise_for_status()
    return {m["id"]: m for m in resp.json()["data"]}


def list_endpoints(slug: str) -> list:
    """The provider endpoints serving `slug`, with quantization and supported parameters."""
    resp = httpx.get(f"{BASE_URL}/models/{slug}/endpoints", timeout=60)
    resp.raise_for_status()
    return resp.json()["data"]["endpoints"]


def cost_usd(usage: dict, slug: str) -> float | None:
    price = config.price_for(slug)
    if price is None:
        return None
    tokens_in = usage.get("prompt", 0)
    tokens_out = usage.get("output", 0) + usage.get("thoughts", 0)
    return (tokens_in * price[0] + tokens_out * price[1]) / 1e6


@dataclass
class ToolCall:
    id: str
    name: str
    args: dict


@dataclass
class LLMTurn:
    message: dict          # assistant message as returned, ready to append to the history
    text: str
    tool_calls: list
    usage: dict
    latency_s: float
    record: dict


class _RateLimiter:
    def __init__(self, rpm: float | None):
        self.interval = 60.0 / rpm if rpm else 0.0
        self.lock = threading.Lock()
        self.next_at = 0.0

    def wait(self):
        if not self.interval:
            return
        with self.lock:
            now = time.monotonic()
            delay = self.next_at - now
            self.next_at = max(now, self.next_at) + self.interval
        if delay > 0:
            time.sleep(delay)


def _parse_args(raw) -> dict:
    if isinstance(raw, dict):
        return raw
    try:
        out = json.loads(raw or "{}")
        return out if isinstance(out, dict) else {"_raw": raw}
    except json.JSONDecodeError:
        return {"_raw": raw, "_parse_error": True}


class OpenRouterLLM:
    def __init__(self, model: str, reasoning_effort: str | None = None, rpm: float | None = None,
                 attempts: int = 6, transport: httpx.BaseTransport | None = None):
        """`model` is an alias from config.MODELS or any OpenRouter slug. The reasoning
        effort comes from the model table unless `reasoning_effort` overrides it."""
        spec = config.resolve(model)
        self.alias, self.model = spec["alias"], spec["slug"]
        self.reasoning_effort = reasoning_effort or spec["reasoning"]
        self.provider = spec.get("provider")
        self.attempts = attempts
        self.limiter = _RateLimiter(rpm)
        self.http = httpx.Client(base_url=BASE_URL, timeout=300, transport=transport, headers={
            "Authorization": f"Bearer {api_key()}",
            "X-Title": "trust-the-source",
        })

    def generate(self, *, system: str, messages: list, tools: list | None = None,
                 web_search: bool = False, seed: int | None = None,
                 json_schema: dict | None = None, tool_choice: str | None = None) -> LLMTurn:
        """`tools` are {"name", "description", "parameters"?} declarations."""
        body = {"model": self.model, "messages": [{"role": "system", "content": system}, *messages],
                "temperature": config.TEMPERATURE, "seed": seed}
        tool_list = [{"type": "function", "function": {
            "name": d["name"], "description": d["description"],
            "parameters": d.get("parameters", {"type": "object", "properties": {}})}} for d in tools or []]
        if web_search:
            tool_list.append({"type": "openrouter:web_search"})
        if tool_list:
            body["tools"] = tool_list
            if tool_choice:
                body["tool_choice"] = tool_choice
        if self.reasoning_effort == "on":
            body["reasoning"] = {"enabled": True}
        elif self.reasoning_effort:
            body["reasoning"] = {"effort": self.reasoning_effort}
        if self.provider:
            body["provider"] = self.provider
        if json_schema:
            body["response_format"] = {"type": "json_schema", "json_schema": {
                "name": "output", "strict": True, "schema": json_schema}}

        self.limiter.wait()
        t0 = time.monotonic()
        data = self._post(body)
        latency = time.monotonic() - t0

        choice = data["choices"][0]
        msg = dict(choice.get("message") or {})
        msg["role"] = "assistant"
        text = msg.get("content") or ""
        calls = [ToolCall(id=tc.get("id") or f"call_{i}", name=tc["function"]["name"],
                          args=_parse_args(tc["function"].get("arguments")))
                 for i, tc in enumerate(msg.get("tool_calls") or []) if tc.get("type", "function") == "function"]
        u = data.get("usage") or {}
        reasoning = (u.get("completion_tokens_details") or {}).get("reasoning_tokens") or 0
        usage = {
            "prompt": u.get("prompt_tokens", 0),
            # completion_tokens includes reasoning tokens; split them out.
            "output": max(u.get("completion_tokens", 0) - reasoning, 0),
            "thoughts": reasoning,
            "cached": (u.get("prompt_tokens_details") or {}).get("cached_tokens", 0),
        }
        # OpenRouter's reported cost includes things the token table can't see (web search fees).
        cost = u.get("cost") if u.get("cost") is not None else cost_usd(usage, self.model)
        record = {
            "model": self.model,
            "model_version": data.get("model"),
            "provider": data.get("provider"),
            "config": {"seed": seed, "temperature": config.TEMPERATURE,
                       "reasoning_effort": self.reasoning_effort or "default",
                       "provider_filter": self.provider,
                       "tools": [d["name"] for d in tools or []] + (["openrouter:web_search"] if web_search else []),
                       "tool_choice": tool_choice, "json_schema": bool(json_schema)},
            "request_messages": body["messages"],
            "response_message": msg,
            "finish_reason": choice.get("finish_reason"),
            "usage": usage,
            "cost_usd": cost,
            "latency_s": round(latency, 3),
        }
        return LLMTurn(message=msg, text=text, tool_calls=calls, usage=usage, latency_s=latency, record=record)

    def _post(self, body: dict) -> dict:
        delay = 2.0
        for attempt in range(self.attempts):
            last = attempt == self.attempts - 1
            try:
                resp = self.http.post("/chat/completions", json=body)
            except httpx.TransportError:
                if last:
                    raise
                time.sleep(delay)
                delay = min(delay * 2, 60)
                continue
            if resp.status_code in RETRY_STATUS and not last:
                time.sleep(float(resp.headers.get("retry-after") or delay))
                delay = min(delay * 2, 60)
                continue
            if resp.status_code >= 400:
                raise RuntimeError(f"OpenRouter {resp.status_code}: {resp.text[:500]}")
            data = resp.json()
            # OpenRouter can return 200 with an error object (e.g. an upstream provider failed).
            if "error" in data and not data.get("choices"):
                if last:
                    raise RuntimeError(f"OpenRouter error: {data['error']}")
                time.sleep(delay)
                delay = min(delay * 2, 60)
                continue
            return data
        raise RuntimeError("unreachable")
