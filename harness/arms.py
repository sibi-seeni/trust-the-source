"""The eight ways of wiring in the freshness check (design doc section 6), plus
the live web-search variant of A3. Each arm takes a RunContext and returns the
final answer text; everything it does is appended to ctx.trace."""

import json
import re
from dataclasses import dataclass, field

from google.genai import types

from . import config, prompts
from .data import Passage, Question
from .registry import CHECK_LATEST_VERSION_DECL, MockRegistry


@dataclass
class RunContext:
    question: Question
    passages: list[Passage]
    registry: MockRegistry
    llm: object
    seed: int
    trace: list = field(default_factory=list)

    def log_llm(self, role: str, turn):
        self.trace.append({"type": "llm_call", "role": role, **turn.record})

    def log_tool(self, role: str, name: str, args: dict, result):
        self.trace.append({"type": "tool_call", "role": role, "name": name, "args": args, "result": result})


def _system(*extra: str) -> str:
    return " ".join([prompts.BASE_SYSTEM, *extra])


def tool_loop(ctx: RunContext, system: str, user_text: str, decls: list, handlers: dict,
              role: str = "main", google_search: bool = False) -> str:
    """Run model turns, executing function calls, until the model answers in text.
    On the last allowed step function calling is switched off to force an answer.
    `decls` may be extended by a handler (that's how a skill unlocks a tool)."""
    contents = [types.Content(role="user", parts=[types.Part(text=user_text)])]
    for step in range(config.MAX_TOOL_STEPS + 1):
        final = step == config.MAX_TOOL_STEPS
        turn = ctx.llm.generate(system=system, contents=contents, function_decls=list(decls) or None,
                                google_search=google_search, seed=ctx.seed,
                                tool_mode="NONE" if final and decls else None)
        ctx.log_llm(role, turn)
        if not turn.function_calls or final:
            return turn.text
        contents.append(turn.content)
        replies = []
        for fc in turn.function_calls:
            args = dict(fc.args or {})
            handler = handlers.get(fc.name)
            result = handler(args) if handler else {"error": f"Unknown tool '{fc.name}'."}
            ctx.log_tool(role, fc.name, args, result)
            replies.append(types.Part(function_response=types.FunctionResponse(
                id=fc.id, name=fc.name, response=result if isinstance(result, dict) else {"result": result})))
        contents.append(types.Content(role="user", parts=replies))
    return ""


def single_call(ctx: RunContext, system: str, user_text: str, role: str = "main") -> str:
    return tool_loop(ctx, system, user_text, [], {}, role=role)


def registry_handler(ctx: RunContext):
    return lambda args: ctx.registry.lookup(str(args.get("title_or_id", "")))


def summarize_lookup(result: dict) -> str:
    """One-line annotation for the forced harness check (A4)."""
    if "error" in result:
        return "REGISTRY UNAVAILABLE (timeout). Freshness not verified."
    if not result.get("found", True):
        return "No registry entry found for this document."
    if "results" in result:
        return " / ".join(summarize_lookup(r) for r in result["results"])
    if result.get("version") == "unknown":
        known = ", ".join(v["version"] for v in result.get("versions", []))
        return (f"Version of this document could not be identified (family {result['family']}; "
                f"known versions: {known}; latest: {result['latest']}).")
    if "versions" in result:
        return " / ".join(_entry_line(v) for v in result["versions"])
    return _entry_line(result)


def _entry_line(e: dict) -> str:
    line = f"{e['family']} {e['version']}: {e['status'].upper()}"
    if e.get("superseded_by"):
        line += f", SUPERSEDED by {e['superseded_by']}"
    if e.get("withdrawn"):
        line += f" (withdrawn {e['withdrawn']})"
    line += f"; latest: {e['latest']}"
    for c in e.get("changes", []):
        label = f"Change {c['change']}" if "change" in c else f"release {c.get('release')}"
        line += f"; in-place {label} dated {c['date']}"
    return line + "."


def run_verifier(ctx: RunContext) -> dict:
    """Separate verifier LLM call(s): sees only the passages and the registry."""
    decls = [CHECK_LATEST_VERSION_DECL]
    handlers = {"check_latest_version": registry_handler(ctx)}
    raw = tool_loop(ctx, prompts.VERIFIER_SYSTEM,
                    "Retrieved passages:\n\n" + prompts.format_passages(ctx.passages),
                    decls, handlers, role="verifier")
    report = parse_json_array(raw)
    return {"report": report} if report is not None else {"report_text": raw, "parse_error": True}


def parse_json_array(text: str):
    m = re.search(r"\[.*\]", text or "", re.S)
    if not m:
        return None
    try:
        out = json.loads(m.group(0))
        return out if isinstance(out, list) else None
    except json.JSONDecodeError:
        return None


# ---- arms -----------------------------------------------------------------

def a0_plain(ctx):
    return single_call(ctx, _system(), prompts.user_message(ctx.question.question, prompts.format_passages(ctx.passages)))


def a1_system_prompt(ctx):
    return single_call(ctx, _system(prompts.FRESHNESS_LINE),
                       prompts.user_message(ctx.question.question, prompts.format_passages(ctx.passages)))


def a2_metadata(ctx):
    return single_call(ctx, _system(prompts.FRESHNESS_LINE),
                       prompts.user_message(ctx.question.question, prompts.format_passages(ctx.passages, metadata=True)))


def a3_tool(ctx):
    return tool_loop(ctx, _system(prompts.FRESHNESS_LINE),
                     prompts.user_message(ctx.question.question, prompts.format_passages(ctx.passages)),
                     [CHECK_LATEST_VERSION_DECL], {"check_latest_version": registry_handler(ctx)})


def a3_web(ctx):
    """Live condition: A3 with Google Search grounding in place of the mock registry."""
    return tool_loop(ctx, _system(prompts.FRESHNESS_LINE),
                     prompts.user_message(ctx.question.question, prompts.format_passages(ctx.passages)),
                     [], {}, google_search=True)


def a4_forced_check(ctx):
    annotations, seen = {}, {}
    for p in ctx.passages:
        if p.doc_id not in seen:
            query = f"{p.title} ({p.filename})"
            result = ctx.registry.lookup(query)
            ctx.log_tool("harness", "check_latest_version", {"title_or_id": query}, result)
            seen[p.doc_id] = summarize_lookup(result)
        annotations[p.pid] = seen[p.doc_id]
    return single_call(ctx, _system(prompts.FRESHNESS_LINE, prompts.A4_NOTE),
                       prompts.user_message(ctx.question.question,
                                            prompts.format_passages(ctx.passages, annotations=annotations)))


def a5_skill(ctx):
    skill_text = (config.SKILLS_DIR / "version-check" / "SKILL.md").read_text()
    decls = [prompts.LOAD_SKILL_DECL]
    handlers = {"check_latest_version": registry_handler(ctx)}

    def load_skill(args):
        if str(args.get("name", "")).strip().lower() != "version-check":
            return {"error": f"Unknown skill '{args.get('name')}'. Available: version-check."}
        if CHECK_LATEST_VERSION_DECL not in decls:
            decls.append(CHECK_LATEST_VERSION_DECL)
        return {"skill": skill_text, "unlocked_tools": ["check_latest_version"]}

    handlers["load_skill"] = load_skill
    return tool_loop(ctx, _system(prompts.FRESHNESS_LINE),
                     prompts.user_message(ctx.question.question, prompts.format_passages(ctx.passages)),
                     decls, handlers)


def a6_subagent(ctx):
    return tool_loop(ctx, _system(prompts.FRESHNESS_LINE),
                     prompts.user_message(ctx.question.question, prompts.format_passages(ctx.passages)),
                     [prompts.VERIFY_SOURCES_DECL], {"verify_sources": lambda args: run_verifier(ctx)})


def a7_forced_subagent(ctx):
    result = run_verifier(ctx)
    ctx.log_tool("harness", "verify_sources", {}, result)
    report = json.dumps(result.get("report", result.get("report_text")), indent=1)
    return single_call(ctx, _system(prompts.FRESHNESS_LINE, prompts.A7_NOTE),
                       prompts.user_message(ctx.question.question, prompts.format_passages(ctx.passages),
                                            extra=f"Source verification report:\n{report}"))


ARM_FUNCS = {
    "A0": a0_plain, "A1": a1_system_prompt, "A2": a2_metadata, "A3": a3_tool,
    "A4": a4_forced_check, "A5": a5_skill, "A6": a6_subagent, "A7": a7_forced_subagent,
    "A3-web": a3_web,
}


def registry_was_checked(trace: list) -> bool:
    """Did anyone actually query the registry during this run?"""
    return any(e["type"] == "tool_call" and e["name"] == "check_latest_version" for e in trace)
