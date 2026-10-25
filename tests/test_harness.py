"""Offline tests: data integrity, registry, arms (with a scripted fake model),
scoring and the report. No API key needed."""

import json
import re

import pytest

from harness import arms, config, report, runner, scoring
from harness.data import Corpus, load_questions, load_registry
from harness.llm import LLMTurn, ToolCall
from harness.registry import MockRegistry
from harness.retrieval import retrieve

QUESTIONS = load_questions()
CORPUS = Corpus()
REGISTRY = load_registry()


class FakeLLM:
    """Calls `script(system, messages, tool_names, kwargs)` -> (text, [(name, args), ...])."""

    def __init__(self, script, model="fake-model"):
        self.script, self.model, self.alias, self.reasoning_effort = script, model, model, None
        self.calls = []

    def generate(self, *, system, messages, tools=None, **kw):
        names = [d["name"] for d in tools or []]
        self.calls.append({"system": system, "messages": list(messages), "decls": names, **kw})
        text, fcalls = self.script(system, messages, names, kw)
        calls = [ToolCall(id=f"call-{i}", name=n, args=a) for i, (n, a) in enumerate(fcalls)]
        message = {"role": "assistant", "content": text or None,
                   "tool_calls": [{"id": c.id, "type": "function",
                                   "function": {"name": c.name, "arguments": json.dumps(c.args)}} for c in calls] or None}
        usage = {"prompt": 100, "output": 10, "thoughts": 5, "cached": 0}
        record = {"model": self.model, "model_version": "fake-1", "provider": "fake", "usage": usage,
                  "cost_usd": 0.001, "latency_s": 0.0, "response_message": message}
        return LLMTurn(message=message, text=text, tool_calls=calls, usage=usage, latency_s=0.0, record=record)


def q_by_id(qid):
    return next(q for q in QUESTIONS if q.id == qid)


def ctx_for(q, llm, unavailable=False):
    return arms.RunContext(question=q, passages=retrieve(q, CORPUS.pool_for(q)),
                           registry=MockRegistry(REGISTRY, unavailable=unavailable), llm=llm, seed=0)


# ---- data integrity -------------------------------------------------------

def test_question_ids_unique_and_cases_valid():
    ids = [q.id for q in QUESTIONS]
    assert len(ids) == len(set(ids))
    assert {q.case for q in QUESTIONS} <= {"C1", "C2", "C3", "C4", "C5", "C6", "C7"}


@pytest.mark.parametrize("q", QUESTIONS, ids=lambda q: q.id)
def test_question_corpus_and_gold_passages(q):
    for d in q.corpus:
        assert d in CORPUS.docs, d
        assert CORPUS.docs[d]["family"] == q.family
    for pid in q.gold_passages:
        assert CORPUS.passages[pid].doc_id in q.corpus
    got = retrieve(q, CORPUS.pool_for(q))
    assert set(q.gold_passages) <= {p.pid for p in got}
    assert len(got) == max(config.TOP_K, len(q.gold_passages))
    for pattern in q.accept + q.alt:
        re.compile(pattern)


def test_c2_corpus_excludes_newer_version():
    for q in QUESTIONS:
        if q.case == "C2":
            pool_docs = {p.doc_id for p in CORPUS.pool_for(q)}
            newest = [d for d in CORPUS.docs.values() if d["family"] == q.family and d.get("default_pool")]
            assert not any(d["doc_id"] in pool_docs for d in newest), q.id


def test_every_doc_family_is_in_registry():
    for d in CORPUS.docs.values():
        assert d["family"] in REGISTRY["families"]


# ---- registry -------------------------------------------------------------

@pytest.mark.parametrize("query,version,status", [
    ("NIST SP 800-53 Revision 4 (NIST.SP.800-53r4.pdf)", "Rev 4", "withdrawn"),
    ("2024 Instructions for Form 1040 (i1040gi_2024.pdf)", "Tax Year 2024", "superseded"),
    ("pandas 2.0 API reference (pandas-docs-2.0.pdf)", "2.0", "current"),
    ("FM 3-0 Operations (October 2017) (FM3-0_2017.pdf)", "2017", "superseded"),
    ("GSA Per Diem Rates, Fiscal Year 2025 (FY2025_PerDiem_Rates.pdf)", "FY2025", "current"),
])
def test_registry_lookup_by_title_and_filename(query, version, status):
    r = MockRegistry(REGISTRY).lookup(query)
    assert r["version"] == version and r["status"] == status


def test_registry_undated_doc_returns_unknown_version():
    r = MockRegistry(REGISTRY).lookup("Instructions for Form 1040 (i1040gi.pdf)")
    assert r["version"] == "unknown" and r["latest"] == "Tax Year 2025"


def test_registry_unavailable_and_unknown():
    assert "error" in MockRegistry(REGISTRY, unavailable=True).lookup("NIST SP 800-53 Rev 4")
    assert MockRegistry(REGISTRY).lookup("Some unrelated manual")["found"] is False


def test_forced_check_annotation_mentions_supersession():
    r = MockRegistry(REGISTRY).lookup("NIST SP 800-53 Revision 4 (NIST.SP.800-53r4.pdf)")
    line = arms.summarize_lookup(r)
    assert "WITHDRAWN" in line and "SUPERSEDED by Rev 5" in line


# ---- arms -----------------------------------------------------------------

def test_a0_has_no_freshness_line_and_a1_does():
    q = q_by_id("irs-01")
    for arm, expected in (("A0", False), ("A1", True)):
        llm = FakeLLM(lambda *a: ("$15,750 [1]", []))
        arms.ARM_FUNCS[arm](ctx_for(q, llm))
        assert (arms.prompts.FRESHNESS_LINE in llm.calls[0]["system"]) == expected


def test_a2_shows_metadata():
    llm = FakeLLM(lambda *a: ("answer", []))
    arms.a2_metadata(ctx_for(q_by_id("nist-03"), llm))
    user_text = llm.calls[0]["messages"][0]["content"]
    assert "status=withdrawn" in user_text


def test_a3_tool_loop_returns_matching_function_response():
    def script(system, contents, decls, kw):
        if len(contents) == 1:
            return "", [("check_latest_version", {"title_or_id": "NIST SP 800-53 Rev 4"})]
        return "Rev 4 is withdrawn; Rev 5 has 20 families.", []
    llm = FakeLLM(script)
    ctx = ctx_for(q_by_id("nist-03"), llm)
    answer = arms.a3_tool(ctx)
    assert answer.startswith("Rev 4 is withdrawn")
    tool_msg = llm.calls[1]["messages"][-1]
    assert tool_msg["role"] == "tool" and tool_msg["tool_call_id"] == "call-0"
    assert json.loads(tool_msg["content"])["status"] == "withdrawn"
    assert llm.calls[1]["messages"][1]["tool_calls"][0]["id"] == "call-0"   # assistant turn echoed back
    assert arms.registry_was_checked(ctx.trace)


def test_a3_forces_final_answer_after_max_steps():
    llm = FakeLLM(lambda s, c, d, kw: ("final" if kw.get("tool_choice") == "none" else "",
                                       [] if kw.get("tool_choice") == "none" else [("check_latest_version", {"title_or_id": "x"})]))
    assert arms.a3_tool(ctx_for(q_by_id("irs-01"), llm)) == "final"
    assert len(llm.calls) == config.MAX_TOOL_STEPS + 1


def test_a4_annotates_every_passage_without_model_tools():
    llm = FakeLLM(lambda *a: ("answer", []))
    ctx = ctx_for(q_by_id("irs-03"), llm)
    arms.a4_forced_check(ctx)
    assert llm.calls[0]["decls"] == []
    assert llm.calls[0]["messages"][0]["content"].count("Registry check:") == len(ctx.passages)
    assert arms.registry_was_checked(ctx.trace)


def test_a5_skill_unlocks_registry_tool():
    def script(system, contents, decls, kw):
        n = len(contents)
        if n == 1:
            return "", [("load_skill", {"name": "version-check"})]
        if n == 3:
            return "", [("check_latest_version", {"title_or_id": "2024 Instructions for Form 1040"})]
        return "Superseded; 2025 value is $23,625.", []
    llm = FakeLLM(script)
    ctx = ctx_for(q_by_id("irs-03"), llm)
    arms.a5_skill(ctx)
    assert llm.calls[0]["decls"] == ["load_skill"]
    assert "check_latest_version" in llm.calls[1]["decls"]
    skill_reply = json.loads(llm.calls[1]["messages"][-1]["content"])
    assert "Version check" in skill_reply["skill"]
    assert arms.registry_was_checked(ctx.trace)


def test_a6_and_a7_run_verifier():
    def script(system, contents, decls, kw):
        if system == arms.prompts.VERIFIER_SYSTEM:
            if len(contents) == 1:
                return "", [("check_latest_version", {"title_or_id": "NIST.SP.800-53r4.pdf"})]
            return '[{"doc": "NIST.SP.800-53r4.pdf", "status": "withdrawn", "latest_value": "Rev 5", "confidence": "high"}]', []
        if "verify_sources" in decls and len(contents) == 1:
            return "", [("verify_sources", {})]
        return "Rev 4 is withdrawn.", []
    for arm in ("A6", "A7"):
        llm = FakeLLM(script)
        ctx = ctx_for(q_by_id("nist-03"), llm)
        assert arms.ARM_FUNCS[arm](ctx) == "Rev 4 is withdrawn."
        roles = [e["role"] for e in ctx.trace if e["type"] == "llm_call"]
        assert "verifier" in roles and "main" in roles
        assert arms.registry_was_checked(ctx.trace)
    final_prompt = llm.calls[-1]["messages"][0]["content"]
    assert "Source verification report" in final_prompt and "withdrawn" in final_prompt


# ---- scoring --------------------------------------------------------------

def test_rule_match_normalises_currency():
    q = q_by_id("irs-01")
    assert scoring.rule_match(q, "It is $15,750 for 2025.") == "gold"
    assert scoring.rule_match(q, "It is $14,600.") == "alt"
    assert scoring.rule_match(q, "Now $15,750, up from $14,600.") is None


@pytest.mark.parametrize("case,matches,flags,expected", [
    ("C1", "gold", [], "correct"),
    ("C1", "alt", [], "stale"),
    ("C2", "alt", [], "stale"),
    ("C2", "alt", ["outdated"], "flagged_correctly"),
    ("C2", "gold", [], "correct"),
    ("C3", "alt", [], "missed_flag"),
    ("C3", "alt", ["unverifiable"], "flagged_correctly"),
    ("C4", "alt", [], "stale"),
    ("C5", "gold", [], "correct"),
    ("C5", "gold", ["outdated"], "false_flag"),
    ("C5", "alt", [], "false_flag"),
    ("C6", "gold", ["outdated"], "false_flag"),
    ("C6", "gold", [], "correct"),
    ("C7", "alt", ["outdated"], "missed_flag"),
    ("C7", "alt", ["inconsistent"], "flagged_correctly"),
])
def test_outcome_mapping(case, matches, flags, expected):
    assert scoring.outcome(case, matches, flags) == expected


def test_registry_unavailable_outcome():
    assert scoring.outcome("C1", "gold", ["unable_to_verify"], "registry_unavailable") == "flagged_correctly"
    assert scoring.outcome("C1", "gold", [], "registry_unavailable") == "missed_flag"


# ---- end to end (fake model and judge) ------------------------------------

def test_pipeline_end_to_end(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "CACHE_DIR", tmp_path / "cache")
    qs = [q for q in QUESTIONS if q.pilot]
    models = [FakeLLM(lambda *a: ("The answer is $15,750 [1].", []), model="fake-a"),
              FakeLLM(lambda *a: ("It is $14,600 [2].", []), model="fake-b")]
    jobs = runner.interleave(models, [(q, a, 0, "normal") for q in qs for a in config.ARMS])
    assert [j[0].model for j in jobs[:4]] == ["fake-a", "fake-b", "fake-a", "fake-b"]
    out = tmp_path / "run" / "results.jsonl"
    results = runner.run_jobs(jobs, CORPUS, REGISTRY, out, workers=2)
    assert len(results) == len(jobs) == 2 * len(qs) * len(config.ARMS)
    assert not any(r["error"] for r in results)
    assert {r["model"] for r in results} == {"fake-a", "fake-b"}

    # second pass is served from cache
    again = runner.run_jobs(jobs, CORPUS, REGISTRY, tmp_path / "run" / "again.jsonl", workers=2)
    assert all(r["from_cache"] for r in again)

    judge_llm = FakeLLM(lambda *a: (json.dumps({"rationale": "x", "answer_matches": "gold", "flags": [],
                                                  "mentions_newer_version": False}), []), model="fake-judge")
    judge = scoring.Judge(judge_llm, cache_dir=tmp_path / "judge")
    qmap = {q.id: q for q in QUESTIONS}
    scored = [scoring.score_record(r, qmap[r["qid"]], judge) for r in report.latest_per_job(results)]
    scored_path = tmp_path / "run" / "scored.jsonl"
    scored_path.write_text("\n".join(json.dumps(s) for s in scored) + "\n")
    md = report.build_report(scored_path)
    assert "| A4 |" in md and "Closure rule" in md
    assert "## fake-a" in md and "## fake-b" in md  # one table per model
    cs = report.select_confirm(scored_path)
    assert cs["arms"][:2] == ["A1", "A4"] and cs["questions"]
    assert report.export_handcheck(scored_path, tmp_path / "hc.csv") >= 1


def test_openrouter_judge_request_and_usage(monkeypatch, tmp_path):
    """OpenRouter judge client against a mocked HTTP transport (no network)."""
    import httpx

    from harness.llm import OpenRouterLLM

    monkeypatch.setenv("OPENROUTER_API_KEY", "test-key")
    sent, replies = [], [httpx.Response(429, json={"error": "rate limited"})]
    labels = {"rationale": "r", "answer_matches": "alt", "flags": ["outdated"], "mentions_newer_version": True}

    def handler(request):
        sent.append(request)
        if replies:
            return replies.pop(0)
        return httpx.Response(200, json={
            "model": "openai/gpt-6-sol-20260922", "provider": "OpenAI",
            "choices": [{"message": {"role": "assistant", "content": json.dumps(labels)}, "finish_reason": "stop"}],
            "usage": {"prompt_tokens": 500, "completion_tokens": 120, "cost": 0.0022,
                      "completion_tokens_details": {"reasoning_tokens": 80}}})

    monkeypatch.setattr("harness.llm.time.sleep", lambda s: None)
    llm = OpenRouterLLM(model="gpt-6-sol", transport=httpx.MockTransport(handler))
    judge = scoring.Judge(llm, cache_dir=tmp_path)
    out = judge.label(q_by_id("irs-03"), "The 2024 figure is $21,900, but these instructions may be outdated.")

    assert out["labels"]["flags"] == ["outdated"] and out["cost_usd"] == 0.0022
    assert out["usage"]["thoughts"] == 80 and out["usage"]["output"] == 40
    body = json.loads(sent[-1].content)
    assert len(sent) == 2  # retried after the 429
    assert sent[-1].headers["authorization"] == "Bearer test-key"
    assert body["model"] == "openai/gpt-6-sol-20260922" and body["reasoning"] == {"effort": "low"}
    assert body["response_format"]["json_schema"]["strict"] is True
    assert [m["role"] for m in body["messages"]] == ["system", "user"]
    assert "ANSWER TO LABEL" in body["messages"][1]["content"]
    # cached: no second request
    judge.label(q_by_id("irs-03"), "The 2024 figure is $21,900, but these instructions may be outdated.")
    assert len(sent) == 2


def test_openrouter_tool_call_round_trip(monkeypatch):
    """Tool declarations go out in OpenAI format; the assistant message (with
    reasoning_details) comes back intact for the next turn."""
    import httpx

    from harness.llm import OpenRouterLLM
    from harness.prompts import VERIFY_SOURCES_DECL
    from harness.registry import CHECK_LATEST_VERSION_DECL

    monkeypatch.setenv("OPENROUTER_API_KEY", "k")
    sent = []
    reasoning_details = [{"type": "reasoning.encrypted", "data": "sig"}]

    def handler(request):
        sent.append(json.loads(request.content))
        return httpx.Response(200, json={"model": "deepseek/deepseek-v4.1-flash-20260910", "provider": "DeepSeek",
            "choices": [{"finish_reason": "tool_calls", "message": {
                "role": "assistant", "content": None, "reasoning_details": reasoning_details,
                "tool_calls": [{"id": "tc1", "type": "function", "function": {
                    "name": "check_latest_version", "arguments": '{"title_or_id": "Rev 4"}'}}]}}],
            "usage": {"prompt_tokens": 1000, "completion_tokens": 300,
                      "completion_tokens_details": {"reasoning_tokens": 200}}})

    llm = OpenRouterLLM(model="deepseek-flash", transport=httpx.MockTransport(handler))
    turn = llm.generate(system="s", messages=[{"role": "user", "content": "q"}],
                        tools=[CHECK_LATEST_VERSION_DECL, VERIFY_SOURCES_DECL], web_search=True,
                        seed=2, tool_choice="none")
    body = sent[0]
    assert body["model"] == "deepseek/deepseek-v4.1-flash-20260910"
    assert body["messages"][0] == {"role": "system", "content": "s"}
    assert body["temperature"] == 0.0 and body["seed"] == 2 and body["tool_choice"] == "none"
    assert body["tools"][0]["function"]["name"] == "check_latest_version"
    assert body["tools"][1]["function"]["parameters"] == {"type": "object", "properties": {}}
    assert body["tools"][2] == {"type": "openrouter:web_search"}
    assert "reasoning" not in body  # deepseek-flash uses the model default
    assert turn.tool_calls[0].id == "tc1" and turn.tool_calls[0].args == {"title_or_id": "Rev 4"}
    assert turn.message["reasoning_details"] == reasoning_details
    # no OpenRouter cost reported -> price table: 1000*0.07 + 300*0.50 per 1M
    assert turn.record["cost_usd"] == pytest.approx((1000 * 0.07 + 300 * 0.50) / 1e6)
    json.dumps(turn.record)


def test_model_aliases_resolve():
    assert config.resolve("glm-5.3")["slug"] == "z-ai/glm-5.3-20260816"
    assert config.resolve("glm-5.3")["reasoning"] == "low"
    assert config.resolve("google/gemini-4-argon")["alias"] == "gemini-4-argon"
    assert config.resolve(config.JUDGE_MODEL)["slug"] == "openai/gpt-6-luna-20260922"
    assert config.resolve(config.JUDGE_MODEL)["reasoning"] == "high"
    assert config.SWEEP_MODELS == ["deepseek-flash", "nemotron-3.5-super-vl"]
    assert config.resolve("nemotron-3.5-super-vl")["slug"] == "nvidia/nemotron-3.5-super-vl-20261015"
    custom = config.resolve("someone/new-model")
    assert custom["slug"] == "someone/new-model" and custom["price"] is None
    for alias in ("deepseek-flash", "nemotron-3.5-super-vl", "glm-5.3", "gpt-6-luna", "gpt-6-sol", "gemini-4-argon", "gemini-3.8-flash"):
        assert alias in config.MODELS


def test_openrouter_embedder(tmp_path):
    import httpx

    from harness.retrieval import OpenRouterEmbedder

    def handler(request):
        inp = json.loads(request.content)["input"]
        return httpx.Response(200, json={"data": [{"index": i, "embedding": [float(len(t)), 1.0]}
                                                  for i, t in reversed(list(enumerate(inp)))]})

    http = httpx.Client(base_url="https://openrouter.ai/api/v1", transport=httpx.MockTransport(handler))
    vecs = OpenRouterEmbedder(http, cache_path=tmp_path / "e.json").embed(["ab", "abcd", "ab"])
    assert vecs[:, 0].tolist() == [2.0, 4.0, 2.0]


def test_estimate_table():
    from harness.estimate import estimate, stage_runs

    plan = stage_runs(QUESTIONS)
    assert sum(r for _, r in plan["sweep"]) == len(QUESTIONS) * 8 * 3
    md = estimate(QUESTIONS, config.SWEEP_MODELS, ["gpt-6-luna"], n_questions=90)
    assert "| nemotron-3.5-super-vl |" in md and "gpt-6-luna (effort high" in md
