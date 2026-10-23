"""Thin wrapper around the Google Gen AI SDK (Gemini API / AI Studio).

Function calling is handled manually (automatic function calling is off) so
every request, tool call and response can be logged. The model's returned
Content is appended to the history as-is, which keeps Gemini 3 thought
signatures intact across tool-calling turns.
"""

import threading
import time
from dataclasses import dataclass

from google import genai
from google.genai import types

from . import config


def make_client() -> genai.Client:
    # Reads GEMINI_API_KEY (or GOOGLE_API_KEY) from the environment.
    retry = types.HttpRetryOptions(attempts=6, initial_delay=2.0, max_delay=60.0,
                                   http_status_codes=[408, 429, 500, 502, 503, 504])
    return genai.Client(http_options=types.HttpOptions(retry_options=retry, timeout=180_000))


def dump(obj) -> dict | None:
    return obj.model_dump(mode="json", exclude_none=True) if obj is not None else None


def cost_usd(usage: dict, model: str) -> float | None:
    if model not in config.PRICES:
        return None
    p_in, p_out = config.PRICES[model]
    tokens_in = usage.get("prompt", 0) + usage.get("tool_use_prompt", 0)
    tokens_out = usage.get("output", 0) + usage.get("thoughts", 0)
    return (tokens_in * p_in + tokens_out * p_out) / 1e6


@dataclass
class LLMTurn:
    content: types.Content
    text: str
    function_calls: list
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


class GeminiLLM:
    def __init__(self, model: str = config.MODEL, thinking_level: str | None = config.THINKING_LEVEL,
                 client: genai.Client | None = None, rpm: float | None = None):
        self.model = model
        self.thinking_level = thinking_level
        self.client = client or make_client()
        self.limiter = _RateLimiter(rpm)

    def generate(self, *, system: str, contents: list, function_decls: list | None = None,
                 google_search: bool = False, seed: int | None = None,
                 json_schema: dict | None = None, tool_mode: str | None = None) -> LLMTurn:
        tools = []
        if function_decls:
            tools.append(types.Tool(function_declarations=[types.FunctionDeclaration(
                name=d["name"], description=d["description"], parameters_json_schema=d.get("parameters"))
                for d in function_decls]))
        if google_search:
            tools.append(types.Tool(google_search=types.GoogleSearch()))
        cfg = types.GenerateContentConfig(
            system_instruction=system,
            seed=seed,
            tools=tools or None,
            automatic_function_calling=types.AutomaticFunctionCallingConfig(disable=True) if tools else None,
            tool_config=(types.ToolConfig(function_calling_config=types.FunctionCallingConfig(mode=tool_mode))
                         if tool_mode and function_decls else None),
            thinking_config=types.ThinkingConfig(thinking_level=self.thinking_level) if self.thinking_level else None,
            response_mime_type="application/json" if json_schema else None,
            response_json_schema=json_schema,
        )
        self.limiter.wait()
        t0 = time.monotonic()
        resp = self.client.models.generate_content(model=self.model, contents=contents, config=cfg)
        latency = time.monotonic() - t0

        cand = resp.candidates[0] if resp.candidates else None
        content = cand.content if cand is not None and cand.content is not None else types.Content(role="model", parts=[])
        content.role = content.role or "model"
        parts = content.parts or []
        text = "".join(p.text for p in parts if p.text and not p.thought)
        calls = [p.function_call for p in parts if p.function_call]
        um = resp.usage_metadata
        usage = {
            "prompt": (um.prompt_token_count or 0) if um else 0,
            "output": (um.candidates_token_count or 0) if um else 0,
            "thoughts": (um.thoughts_token_count or 0) if um else 0,
            "tool_use_prompt": (um.tool_use_prompt_token_count or 0) if um else 0,
            "cached": (um.cached_content_token_count or 0) if um else 0,
        }
        record = {
            "model": self.model,
            "model_version": resp.model_version,
            "config": {"seed": seed, "thinking_level": self.thinking_level or "default",
                       "tools": [d["name"] for d in function_decls or []] + (["google_search"] if google_search else []),
                       "tool_mode": tool_mode, "json_schema": bool(json_schema)},
            "system": system,
            "request_contents": [dump(c) for c in contents],
            "response_content": dump(content),
            "finish_reason": str(cand.finish_reason) if cand is not None and cand.finish_reason else None,
            "grounding_metadata": dump(cand.grounding_metadata) if cand is not None else None,
            "prompt_feedback": dump(resp.prompt_feedback),
            "usage": usage,
            "cost_usd": cost_usd(usage, self.model),
            "latency_s": round(latency, 3),
        }
        return LLMTurn(content=content, text=text, function_calls=calls, usage=usage,
                       latency_s=latency, record=record)
