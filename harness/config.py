"""Experiment-wide settings. Override the model choices with environment variables."""

import os
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = ROOT / "data"
SKILLS_DIR = ROOT / "skills"
RUNS_DIR = ROOT / "runs"
CACHE_DIR = ROOT / "cache"

# Every model is called through OpenRouter (https://openrouter.ai/api/v1).
#
# alias -> OpenRouter model id (what requests send), the canonical slug that id
# pointed to when the table was written, USD per 1M tokens (input, output),
# reasoning effort to request (None = the model's default, "on" = switch reasoning
# on for models that have no effort levels), tier, and optionally "provider": an
# OpenRouter provider-routing object sent with every request. OpenRouter
# only accepts the id in requests; the canonical slug is its permanent dated name.
# Preflight fails if an id now resolves to a different canonical slug, so results
# don't shift mid-run without anyone noticing; the served model is logged on every
# call either way. Reasoning tokens are billed as output. Prices are from
# OpenRouter's /api/v1/models on Oct 27, 2026: preflight prints the live price, and
# OpenRouter's reported cost is what gets logged. This table is only for estimates
# and as a fallback.
MODELS = {
    # Budget tier: what the team is paying for now.
    "deepseek-flash": {"slug": "deepseek/deepseek-v4.1-flash", "canonical": "deepseek/deepseek-v4.1-flash-20260910",
                       "price": (0.14, 0.42), "reasoning": None, "tier": "budget"},
    # The US open-weight model under test (swapped in for Nemotron at the project
    # sponsor's request, Oct 28, 2026). Thinking is an on/off switch with no effort
    # levels and an unclear default, so it's switched on explicitly, matching
    # Nemotron, which reasons by default. Many providers serve it at fp4; the provider
    # filter keeps requests on fp8 or better (endpoints reporting "unknown" are left out).
    "gemma-4-31b": {"slug": "google/gemma-4-31b-it", "canonical": "google/gemma-4-31b-it-20260402",
                    "price": (0.20, 0.40), "reasoning": "on", "tier": "budget",
                    "provider": {"quantizations": ["fp8", "bf16", "fp16", "fp32"]}},
    # The previous US open-weight model, used in runs/pilot. Reasoning is on by
    # default; OpenRouter routes tool-calling requests to the providers that support tools.
    "nemotron-3.5-super-vl": {"slug": "nvidia/nemotron-3.5-super-vl", "canonical": "nvidia/nemotron-3.5-super-vl-20261015",
                              "price": (0.15, 0.50), "reasoning": None, "tier": "budget"},
    # GLM 5.3 always reasons and defaults to effort "max", which multiplies output
    # tokens; "low" keeps it inside the budget. Set TTS_REASONING_EFFORT to override.
    "glm-5.3": {"slug": "z-ai/glm-5.3", "canonical": "z-ai/glm-5.3-20260816",
                "price": (0.0699, 1.40), "reasoning": "low", "tier": "budget"},
    # The judge, at low effort to keep scoring cheap.
    "gpt-6-luna": {"slug": "openai/gpt-6-luna", "canonical": "openai/gpt-6-luna-20260922",
                   "price": (0.10, 0.50), "reasoning": "low", "tier": "budget"},
    # Funded tier: the design doc's confirmation / judge models, kept for later.
    # (A confirmation round isn't planned for this track, but `run --stage confirm
    # --model <alias>` still works.)
    "gpt-6-sol": {"slug": "openai/gpt-6-sol", "canonical": "openai/gpt-6-sol-20260922",
                  "price": (2.00, 10.00), "reasoning": "low", "tier": "funded"},
    "gemini-4-argon": {"slug": "google/gemini-4-argon", "canonical": "google/gemini-4-argon-20261013",
                       "price": (2.00, 10.00), "reasoning": None, "tier": "funded"},
    "gemini-3.8-flash": {"slug": "google/gemini-3.8-flash", "canonical": "google/gemini-3.8-flash-20260902",
                         "price": (0.825, 4.125), "reasoning": None, "tier": "funded"},
}

# Models under test. Every stage runs all of them in parallel, and the report
# gives each its own table. Comma-separated aliases or slugs.
SWEEP_MODELS = os.environ.get("TTS_MODELS", "deepseek-flash,gemma-4-31b").split(",")
# The judge is GPT-6 Luna at low reasoning effort: cheap, and a different model
# family from both models under test. Switch to gpt-6-sol once there's funding
# (TTS_JUDGE_MODEL=gpt-6-sol).
JUDGE_MODEL = os.environ.get("TTS_JUDGE_MODEL", "gpt-6-luna")
# Dense half of hybrid retrieval, via OpenRouter's embeddings endpoint.
EMBED_MODEL = os.environ.get("TTS_EMBED_MODEL", "openai/text-embedding-3-small")
# Override the reasoning setting from the table (e.g. "low", "high"): the first for
# every model under test, the second for the judge only.
REASONING_OVERRIDE = os.environ.get("TTS_REASONING_EFFORT") or None
JUDGE_REASONING_OVERRIDE = os.environ.get("TTS_JUDGE_REASONING_EFFORT") or None


def resolve(model: str) -> dict:
    """Alias, OpenRouter id or canonical slug -> {"alias", "slug", "price", "reasoning", "tier", "provider"?}.
    "slug" is always the id that requests send."""
    if model in MODELS:
        m = {"alias": model, **MODELS[model]}
    else:
        known = next((a for a, m in MODELS.items() if model in (m["slug"], m.get("canonical"))), None)
        m = {"alias": known or model, **(MODELS[known] if known else
                                         {"slug": model, "price": None, "reasoning": None, "tier": "custom"})}
    return m


def price_for(slug: str):
    return next((m["price"] for m in MODELS.values() if m["slug"] == slug), None)


TOP_K = 5
SEEDS = [0, 1, 2]
MAX_TOOL_STEPS = 4          # model turns allowed before a final answer is forced
REGISTRY_TIMEOUT_S = 10     # what the simulated 'registry unavailable' error reports
TEMPERATURE = 0.0           # the design doc's setting; logged with every call

# Bump when prompts or arm logic change, so cached results aren't reused by mistake.
PROMPT_VERSION = "v2"

ARMS = ["A0", "A1", "A2", "A3", "A4", "A5", "A6", "A7"]
REGISTRY_ARMS = ["A3", "A4", "A5", "A6", "A7"]
MODEL_DRIVEN_ARMS = ["A3", "A5", "A6"]
