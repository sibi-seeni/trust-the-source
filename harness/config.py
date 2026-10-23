"""Experiment-wide settings. Override the model ids with environment variables."""

import os
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = ROOT / "data"
SKILLS_DIR = ROOT / "skills"
RUNS_DIR = ROOT / "runs"
CACHE_DIR = ROOT / "cache"

# Main model under test, served through Google AI Studio (Gemini API).
MODEL = os.environ.get("TTS_MODEL", "gemini-3.8-flash")
# The LLM judge that labels flags runs on GPT-6 Sol through OpenRouter, so it's a
# different model family from the one being judged. The dated slug is pinned so
# labels don't shift mid-run; the run log records the version OpenRouter served.
JUDGE_MODEL = os.environ.get("TTS_JUDGE_MODEL", "openai/gpt-6-sol-20260922")
JUDGE_REASONING_EFFORT = os.environ.get("TTS_JUDGE_REASONING_EFFORT", "low")
EMBED_MODEL = os.environ.get("TTS_EMBED_MODEL", "gemini-embedding-2")

# Gemini 3.8 Flash ignores temperature/top_k/top_p on the backend, so they're not sent.
# Reasoning effort is controlled with thinking_level. None = model default (MEDIUM),
# which is what the design doc asks for. Whatever is used gets logged with every call.
THINKING_LEVEL = os.environ.get("TTS_THINKING_LEVEL") or None

# USD per 1M tokens (input, output). Thinking/reasoning tokens are billed as output.
# gemini-3.8-flash: introductory pricing through 2026-12-31. Check it against the
# AI Studio billing page before quoting costs. For OpenRouter calls the cost
# OpenRouter reports is used, and this table is only a fallback.
PRICES = {
    "gemini-3.8-flash": (0.75, 3.75),
    "openai/gpt-6-sol": (2.00, 10.00),
    "openai/gpt-6-sol-20260922": (2.00, 10.00),
}

TOP_K = 5
SEEDS = [0, 1, 2]
MAX_TOOL_STEPS = 4          # model turns allowed before a final answer is forced
REGISTRY_TIMEOUT_S = 10     # what the simulated 'registry unavailable' error reports

# Bump when prompts or arm logic change, so cached results aren't reused by mistake.
PROMPT_VERSION = "v1"

ARMS = ["A0", "A1", "A2", "A3", "A4", "A5", "A6", "A7"]
REGISTRY_ARMS = ["A3", "A4", "A5", "A6", "A7"]
MODEL_DRIVEN_ARMS = ["A3", "A5", "A6"]
