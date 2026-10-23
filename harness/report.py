"""Headline numbers, closure-rule check, confirmation-set selection and
hand-check export, all computed from a run's scored.jsonl."""

import csv
import json
import random
from collections import Counter, defaultdict

from . import config
from .scoring import GOOD, OUTCOMES

STALE_MAX = 0.05
FALSE_FLAG_MAX = 0.05


def load_jsonl(path):
    with open(path) as f:
        return [json.loads(line) for line in f if line.strip()]


def latest_per_job(rows):
    """results.jsonl is append-only; keep the last row per job."""
    out = {}
    for r in rows:
        out[(r["model"], r["arm"], r["qid"], r["seed"], r["condition"])] = r
    return list(out.values())


def _rate(rows, pred):
    return (sum(1 for r in rows if pred(r)) / len(rows), len(rows)) if rows else (None, 0)


def _fmt(rate_n):
    rate, n = rate_n
    return "n/a" if rate is None else f"{rate:.0%} (n={n})"


def arm_summary(rows):
    by_case = defaultdict(list)
    for r in rows:
        by_case[r["case"]].append(r)
    c12 = by_case["C1"] + by_case["C2"]
    c34 = by_case["C3"] + by_case["C4"]
    c56 = by_case["C5"] + by_case["C6"]
    needs_check = by_case["C2"] + by_case["C3"] + by_case["C4"]
    costs = [r["cost_usd"] for r in rows if r["cost_usd"] is not None]
    return {
        "n": len(rows),
        "stale_c1c2": _rate(c12, lambda r: r["outcome"] == "stale"),
        "unverifiable_ok_c3c4": _rate(c34, lambda r: r["outcome"] in GOOD),
        "false_flag_c5c6": _rate(c56, lambda r: r["outcome"] == "false_flag"),
        "c7_flagged": _rate(by_case["C7"], lambda r: r["outcome"] == "flagged_correctly"),
        "overall_ok": _rate(rows, lambda r: r["outcome"] in GOOD),
        "check_invoked_c2c4": _rate(needs_check, lambda r: r["check_invoked"]),
        "cost_per_100": 100 * sum(costs) / len(costs) if costs else None,
        "avg_calls": sum(r["n_calls"] for r in rows) / len(rows) if rows else None,
        "avg_latency_s": sum(r["latency_s"] for r in rows) / len(rows) if rows else None,
    }


def build_report(scored_path) -> str:
    rows = latest_per_job(load_jsonl(scored_path))
    groups = defaultdict(list)
    for r in rows:
        groups[(r["model"], r["condition"], r["arm"])].append(r)

    lines = [f"# Results: `{scored_path.parent.name}`", ""]
    for (model, condition) in sorted({(m, c) for m, c, _ in groups}):
        lines += [f"## {model}, condition: {condition}", "",
                  "| Arm | Runs | Stale C1–C2 ↓ | Unverifiable handled C3–C4 ↑ | False flag C5–C6 ↓ | C7 flagged ↑ "
                  "| Overall OK | Registry checked (C2–C4) | Cost / 100 Qs | Calls | Latency (s) |",
                  "|---|---|---|---|---|---|---|---|---|---|---|"]
        summaries = {}
        for arm in sorted(a for m, c, a in groups if (m, c) == (model, condition)):
            s = summaries[arm] = arm_summary(groups[(model, condition, arm)])
            cost = "n/a" if s["cost_per_100"] is None else f"${s['cost_per_100']:.3f}"
            check = _fmt(s["check_invoked_c2c4"]) if arm in config.MODEL_DRIVEN_ARMS + ["A4", "A7"] else "–"
            lines.append(f"| {arm} | {s['n']} | {_fmt(s['stale_c1c2'])} | {_fmt(s['unverifiable_ok_c3c4'])} "
                         f"| {_fmt(s['false_flag_c5c6'])} | {_fmt(s['c7_flagged'])} | {_fmt(s['overall_ok'])} "
                         f"| {check} | {cost} | {s['avg_calls']:.2f} | {s['avg_latency_s']:.1f} |")
        lines.append("")
        if condition == "normal":
            lines += closure_lines(summaries)
        lines += case_breakdown(groups, model, condition)

    disagreements = sum(1 for r in rows if r["disagreement"])
    errors = sum(1 for r in rows if r.get("answer") in (None, ""))
    lines += ["## Scoring notes", "",
              f"- Rule-based vs judge disagreements: {disagreements} (export with `python -m harness handcheck`).",
              f"- Runs with an empty answer or error: {errors}.",
              f"- Judge cost: ${sum(r['judge_cost_usd'] or 0 for r in rows):.4f} (not included in arm cost).", ""]
    return "\n".join(lines)


def closure_lines(summaries) -> list[str]:
    passing = []
    for arm, s in summaries.items():
        stale, ff = s["stale_c1c2"][0], s["false_flag_c5c6"][0]
        if stale is not None and ff is not None and stale <= STALE_MAX and ff <= FALSE_FLAG_MAX:
            passing.append((s["cost_per_100"] if s["cost_per_100"] is not None else float("inf"), arm))
    lines = [f"**Closure rule** (stale ≤ {STALE_MAX:.0%} on C1–C2 and false flags ≤ {FALSE_FLAG_MAX:.0%} on C5–C6):"]
    if passing:
        passing.sort()
        lines.append(f"met by {', '.join(a for _, a in passing)}. Cheapest arm that meets it: **{passing[0][1]}**.")
    else:
        lines.append("not met by any arm.")
    return lines + [""]


def case_breakdown(groups, model, condition) -> list[str]:
    lines = ["<details><summary>Outcomes by case</summary>", "",
             "| Arm | Case | " + " | ".join(OUTCOMES) + " |", "|---|---|" + "---|" * len(OUTCOMES)]
    for arm in sorted(a for m, c, a in groups if (m, c) == (model, condition)):
        by_case = defaultdict(Counter)
        for r in groups[(model, condition, arm)]:
            by_case[r["case"]][r["outcome"]] += 1
        for case in sorted(by_case):
            lines.append(f"| {arm} | {case} | " + " | ".join(str(by_case[case][o]) for o in OUTCOMES) + " |")
    return lines + ["", "</details>", ""]


def select_confirm(scored_path, sample_n=25, seed=0) -> dict:
    """Design doc step 3: every question where any arm disagreed with gold, plus a
    stratified random sample across case types; arms A1, A4 and the best model-driven arm."""
    rows = [r for r in latest_per_job(load_jsonl(scored_path)) if r["condition"] == "normal"]
    failed = sorted({r["qid"] for r in rows if r["outcome"] not in GOOD})
    by_case = defaultdict(set)
    for r in rows:
        by_case[r["case"]].add(r["qid"])
    rng = random.Random(seed)
    cases = sorted(by_case)
    sample = set()
    while len(sample) < sample_n and any(by_case[c] - sample for c in cases):
        for c in cases:
            left = sorted(by_case[c] - sample)
            if left and len(sample) < sample_n:
                sample.add(rng.choice(left))

    def badness(arm):
        s = arm_summary([r for r in rows if r["arm"] == arm])
        return (s["stale_c1c2"][0] or 0) + (s["false_flag_c5c6"][0] or 0)

    model_driven = [a for a in config.MODEL_DRIVEN_ARMS if any(r["arm"] == a for r in rows)]
    best = min(model_driven, key=badness) if model_driven else None
    return {"source_run": str(scored_path.parent.name),
            "questions": sorted(set(failed) | sample),
            "from_failures": failed, "from_sample": sorted(sample),
            "arms": ["A1", "A4"] + ([best] if best else [])}


def export_handcheck(scored_path, out_csv, frac=0.10, seed=0) -> int:
    rows = latest_per_job(load_jsonl(scored_path))
    rng = random.Random(seed)
    sample = rng.sample(rows, max(1, round(frac * len(rows)))) if rows else []
    picked = {id(r): "sample" for r in sample}
    for r in rows:
        if r["disagreement"]:
            picked[id(r)] = "disagreement" if id(r) not in picked else "sample+disagreement"
    chosen = [r for r in rows if id(r) in picked]
    fields = ["why", "model", "arm", "qid", "case", "seed", "condition", "answer", "rule_match", "judge_match",
              "flags", "outcome", "judge_rationale", "human_outcome", "human_note"]
    with open(out_csv, "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=fields, extrasaction="ignore")
        w.writeheader()
        for r in chosen:
            w.writerow({**r, "why": picked[id(r)], "flags": ";".join(r["flags"]),
                        "human_outcome": "", "human_note": ""})
    return len(chosen)
