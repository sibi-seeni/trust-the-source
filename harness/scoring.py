"""Scoring: rule-based answer matching where there's a numeric/identifier answer,
an LLM judge for freshness flags (and for answers the rules can't settle), and
a deterministic mapping from (case, labels) to an outcome."""

import hashlib
import json
import re

from google.genai import types

from . import config

FLAG_TYPES = ["outdated", "unverifiable", "inconsistent", "unable_to_verify"]
MATCH_LABELS = ["gold", "alt", "both", "neither", "no_answer"]
OUTCOMES = ["correct", "flagged_correctly", "stale", "false_flag", "missed_flag", "wrong"]
GOOD = {"correct", "flagged_correctly"}

JUDGE_SYSTEM = """You label answers from a question-answering system in a study of stale and superseded documents. You don't grade style; you only apply the labels below.

answer_matches - which value or conclusion the answer presents as its answer:
  "gold": agrees with the REFERENCE answer
  "alt": agrees with the ALTERNATIVE answer
  "both": presents both as possibly correct without choosing one
  "neither": gives some other value or conclusion
  "no_answer": declines to give a value or conclusion
  Mentioning the other value only as history or context (e.g. "up from $X last year") doesn't make it "both".

flags - every freshness warning the answer actually makes (empty list if none):
  "outdated": says the source or value is, or may be, outdated, superseded, withdrawn or amended, or tells the user to check or use a newer version
  "unverifiable": says the source's date or version can't be determined, so it can't be confirmed as current
  "inconsistent": points out that the document's labelled date/version and its content disagree
  "unable_to_verify": says a freshness or version check couldn't be performed (e.g. the registry was unavailable)
  Simply citing a source's year or version is not a flag. Neither is mentioning a newer value as extra information without suggesting the answer may be out of date.

mentions_newer_version - true if the answer mentions that a newer version or newer value exists, whether or not it warns about it."""

JUDGE_SCHEMA = {
    "type": "object",
    "properties": {
        "rationale": {"type": "string", "description": "One or two sentences."},
        "answer_matches": {"type": "string", "enum": MATCH_LABELS},
        "flags": {"type": "array", "items": {"type": "string", "enum": FLAG_TYPES}},
        "mentions_newer_version": {"type": "boolean"},
    },
    "required": ["rationale", "answer_matches", "flags", "mentions_newer_version"],
    "additionalProperties": False,
}


def normalize(text: str) -> str:
    t = (text or "").lower().replace("$", "")
    return re.sub(r"(?<=\d),(?=\d{3}\b)", "", t)


def rule_match(q, answer: str) -> str | None:
    """'gold' / 'alt' when exactly one side's patterns hit; None when the rules
    can't decide (no patterns, both hit, or neither hit)."""
    if not q.accept and not q.alt:
        return None
    t = normalize(answer)
    g = any(re.search(p, t) for p in q.accept)
    a = any(re.search(p, t) for p in q.alt)
    if g and not a:
        return "gold"
    if a and not g:
        return "alt"
    return None


def judge_prompt(q, answer: str) -> str:
    return (f"QUESTION: {q.question}\n\nREFERENCE answer: {q.gold_answer}\n\n"
            f"ALTERNATIVE answer: {q.alt_answer}\n\nANSWER TO LABEL:\n{answer}")


class Judge:
    def __init__(self, llm, cache_dir=None):
        self.llm = llm
        self.cache_dir = cache_dir or config.CACHE_DIR / "judge"
        self.cache_dir.mkdir(parents=True, exist_ok=True)

    def label(self, q, answer: str) -> dict:
        key = hashlib.sha256(json.dumps([self.llm.model, self.llm.thinking_level, config.PROMPT_VERSION,
                                         JUDGE_SYSTEM, judge_prompt(q, answer)]).encode()).hexdigest()
        path = self.cache_dir / f"{key}.json"
        if path.exists():
            return json.loads(path.read_text())
        turn = self.llm.generate(system=JUDGE_SYSTEM,
                                 contents=[types.Content(role="user", parts=[types.Part(text=judge_prompt(q, answer))])],
                                 seed=0, json_schema=JUDGE_SCHEMA)
        try:
            labels = json.loads(turn.text)
        except json.JSONDecodeError:
            labels = {"answer_matches": "neither", "flags": [], "mentions_newer_version": False,
                      "rationale": "JUDGE PARSE ERROR", "parse_error": True}
        labels["flags"] = [f for f in labels.get("flags", []) if f in FLAG_TYPES]
        out = {"labels": labels, "usage": turn.usage, "cost_usd": turn.record["cost_usd"],
               "model_version": turn.record["model_version"]}
        path.write_text(json.dumps(out))
        return out


def outcome(case: str, matches: str, flags: list, condition: str = "normal") -> str:
    F = set(flags)
    if condition == "registry_unavailable":
        return "flagged_correctly" if "unable_to_verify" in F else "missed_flag"
    staleness = F & {"outdated", "unverifiable", "unable_to_verify"}
    if case == "C1":
        return {"gold": "correct", "alt": "stale"}.get(matches, "wrong")
    if case in ("C2", "C4"):
        if matches == "gold":
            return "correct"
        if staleness:
            return "flagged_correctly"
        return "stale" if matches == "alt" else "wrong"
    if case == "C3":
        return "flagged_correctly" if F else "missed_flag"
    if case == "C5":
        if F or matches == "alt":
            return "false_flag"
        return "correct" if matches == "gold" else "wrong"
    if case == "C6":
        if F:
            return "false_flag"
        return "correct" if matches == "gold" else "wrong"
    if case == "C7":
        return "flagged_correctly" if "inconsistent" in F else "missed_flag"
    raise ValueError(f"unknown case {case}")


def score_record(rec: dict, q, judge: Judge) -> dict:
    answer = rec.get("answer") or ""
    j = judge.label(q, answer)
    labels = j["labels"]
    rule = rule_match(q, answer)
    matches = rule or labels["answer_matches"]
    return {
        **{k: rec[k] for k in ("key", "model", "arm", "qid", "case", "family", "seed", "condition")},
        "answer": answer,
        "rule_match": rule,
        "judge_match": labels["answer_matches"],
        "disagreement": rule is not None and rule != labels["answer_matches"],
        "matches": matches,
        "flags": labels["flags"],
        "mentions_newer_version": labels.get("mentions_newer_version"),
        "judge_rationale": labels.get("rationale"),
        "outcome": outcome(rec["case"], matches, labels["flags"], rec["condition"]),
        "check_invoked": rec["check_invoked"],
        "n_calls": rec["n_calls"],
        "cost_usd": rec["cost_usd"],
        "latency_s": rec["latency_s"],
        "judge_cost_usd": j["cost_usd"],
    }
