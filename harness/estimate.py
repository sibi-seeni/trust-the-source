"""Cost estimates per stage and model, from assumed token counts or from a run's
measured usage (e.g. the pilot)."""

from collections import defaultdict

from . import config
from .report import latest_per_job, load_jsonl

# Model calls per run, by arm (main model + verifier), from how each arm works.
CALLS_PER_RUN = {"A0": 1, "A1": 1, "A2": 1, "A3": 2, "A4": 1, "A5": 3, "A6": 4, "A7": 3, "A3-web": 2}

# Tokens per call. The base prompt (system + 5 passages) measures ~670 tokens;
# tool declarations and tool results push later turns higher. Output includes
# reasoning tokens, which is what really swings the cost.
SCENARIOS = {
    "low": {"in": 1100, "out": 400, "judge_in": 900, "judge_out": 250},
    "high": {"in": 1600, "out": 1500, "judge_in": 900, "judge_out": 600},
}

CONFIRM_QUESTIONS = 40   # design doc step 3: failures + 25 stratified, ~40
CONFIRM_ARMS = ["A1", "A4", "A3"]


def stage_runs(questions, n_questions=None) -> dict:
    """{stage: [(arm, n_runs)]} for the run plan in the design doc."""
    scale = (n_questions / len(questions)) if n_questions else 1.0
    n = lambda k: round(k * scale)  # noqa: E731
    n_pilot = sum(q.pilot for q in questions)
    n_c12 = n(sum(q.case in ("C1", "C2") for q in questions))
    n_live = sum(q.live for q in questions)
    return {
        "pilot": [(a, n_pilot) for a in config.ARMS],
        "sweep": [(a, n(len(questions)) * len(config.SEEDS)) for a in config.ARMS],
        "unavailable": [(a, n_c12) for a in config.REGISTRY_ARMS],
        "live": [("A3-web", n_live)],
        "confirm": [(a, CONFIRM_QUESTIONS * 2) for a in CONFIRM_ARMS],
    }


def measured_profile(results_path) -> dict:
    """Per-arm average calls per run and tokens per call, from a results.jsonl."""
    rows = [r for r in latest_per_job(load_jsonl(results_path)) if not r.get("error")]
    by_arm = defaultdict(list)
    for r in rows:
        by_arm[r["arm"]].append(r)
    profile = {}
    for arm, rs in by_arm.items():
        calls = sum(r["n_calls"] for r in rs)
        profile[arm] = {
            "calls": calls / len(rs),
            "in": sum(r["usage"]["prompt"] for r in rs) / max(calls, 1),
            "out": sum(r["usage"]["output"] + r["usage"]["thoughts"] for r in rs) / max(calls, 1),
        }
    return profile


def estimate(questions, models, judges, n_questions=None, profile=None) -> str:
    plan = stage_runs(questions, n_questions)
    stages = list(plan)
    lines = []
    scenarios = {"measured": None} if profile else SCENARIOS
    for scen_name, scen in scenarios.items():
        lines += [f"### {scen_name} scenario" + ("" if profile else
                  f" ({scen['in']} in / {scen['out']} out tokens per call)"), "",
                  "| Model | $/1M in/out | " + " | ".join(stages) + " | Total (excl. confirm) |",
                  "|---|---|" + "---|" * len(stages) + "---|"]
        for alias in models:
            p_in, p_out = config.resolve(alias)["price"]
            costs = []
            for stage in stages:
                c = 0.0
                for arm, runs in plan[stage]:
                    prof = (profile or {}).get(arm) or {"calls": CALLS_PER_RUN[arm], **(scen or SCENARIOS["low"])}
                    calls = runs * prof["calls"]
                    c += calls * (prof["in"] * p_in + prof["out"] * p_out) / 1e6
                costs.append(c)
            total = sum(c for s, c in zip(stages, costs) if s != "confirm")
            lines.append(f"| {alias} | ${p_in}/${p_out} | " + " | ".join(f"${c:.2f}" for c in costs)
                         + f" | **${total:.2f}** |")
        lines.append("")

        judged_runs = sum(runs for s in stages for _, runs in plan[s])
        lines += [f"Judge, one call per run ({judged_runs} runs incl. confirm):", ""]
        js = scen or SCENARIOS["low"]
        for alias in judges:
            p_in, p_out = config.resolve(alias)["price"]
            c = judged_runs * (js["judge_in"] * p_in + js["judge_out"] * p_out) / 1e6
            lines.append(f"- {alias}: ${c:.2f}")
        lines.append("")
    total_runs = {s: sum(r for _, r in plan[s]) for s in stages}
    lines.append("Runs per stage: " + ", ".join(f"{s} {n}" for s, n in total_runs.items())
                 + ". The live stage also pays OpenRouter's web search fee per search, which isn't in the token math.")
    return "\n".join(lines)
