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
# alias -> OpenRouter slug, USD per 1M tokens (input, output), reasoning effort to
# request (None = the model's default), and tier. Dated slugs are pinned where
# OpenRouter lists one, so results don't shift mid-run; the served model is logged
# on every call either way. Reasoning tokens are billed as output. Prices are from
# the OpenRouter model pages in Oct 2026: preflight prints the live price, and
# OpenRouter's reported cost is what gets logged. This table is only for estimates
# and as a fallback.
MODELS = {
    # Budget tier: what the team is paying for now.
    "deepseek-flash": {"slug": "deepseek/deepseek-v4.1-flash-20260910", "price": (0.07, 0.50),
                       "reasoning": None, "tier": "budget"},
    # GLM 5.3 always reasons and defaults to effort "max", which multiplies output
    # tokens; "low" keeps it inside the budget. Set TTS_REASONING_EFFORT to override.
    "glm-5.3": {"slug": "z-ai/glm-5.3-20260816", "price": (1.40, 4.40),
                "reasoning": "low", "tier": "budget"},
    "gpt-6-luna": {"slug": "openai/gpt-6-luna", "price": (0.10, 0.50),
                   "reasoning": "low", "tier": "budget"},
    # Funded tier: the design doc's confirmation / judge models, kept for later.
    "gpt-6-sol": {"slug": "openai/gpt-6-sol-20260922", "price": (2.00, 10.00),
                  "reasoning": "low", "tier": "funded"},
    "gemini-4-argon": {"slug": "google/gemini-4-argon", "price": (2.00, 10.00),
                       "reasoning": None, "tier": "funded"},
    "gemini-3.8-flash": {"slug": "google/gemini-3.8-flash-20260902", "price": (0.75, 3.75),
                         "reasoning": None, "tier": "funded"},
}

# Model under test, and the second budget model for the confirmation stage.
MODEL = os.environ.get("TTS_MODEL", "deepseek-flash")
CONFIRM_MODEL = os.environ.get("TTS_CONFIRM_MODEL", "glm-5.3")
# The judge is GPT-6 Luna: cheap, and a different model family from both models
# under test. Switch to gpt-6-sol once there's funding (TTS_JUDGE_MODEL=gpt-6-sol).
JUDGE_MODEL = os.environ.get("TTS_JUDGE_MODEL", "gpt-6-luna")
# Dense half of hybrid retrieval, via OpenRouter's embeddings endpoint.
EMBED_MODEL = os.environ.get("TTS_EMBED_MODEL", "openai/text-embedding-3-small")
# Overrides every model's reasoning setting when set (e.g. "low", "high").
REASONING_OVERRIDE = os.environ.get("TTS_REASONING_EFFORT") or None


def resolve(model: str) -> dict:
    """Alias or raw OpenRouter slug -> {"alias", "slug", "price", "reasoning", "tier"}."""
    if model in MODELS:
        m = {"alias": model, **MODELS[model]}
    else:
        known = next((a for a, m in MODELS.items() if m["slug"] == model), None)
        m = {"alias": known or model, **(MODELS[known] if known else
                                         {"slug": model, "price": None, "reasoning": None, "tier": "custom"})}
    if REASONING_OVERRIDE:
        m["reasoning"] = REASONING_OVERRIDE
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
