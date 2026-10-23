"""Command line: python -m harness <command> [options]. See README.md."""

import argparse
import json
import os
import subprocess
import sys
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
from pathlib import Path

from google.genai import types

from . import arms, config
from .data import Corpus, load_questions, load_registry
from .llm import GeminiLLM, make_client
from .openrouter import OpenRouterLLM, get_model_info
from .registry import CHECK_LATEST_VERSION_DECL
from .report import build_report, export_handcheck, latest_per_job, load_jsonl, select_confirm
from .retrieval import GeminiEmbedder
from .runner import run_jobs
from .scoring import Judge, score_record

STAGES = {
    # stage: (question filter, arms, seeds, condition)
    "pilot": (lambda q: q.pilot, config.ARMS, [0], "normal"),
    "sweep": (lambda q: True, config.ARMS, config.SEEDS, "normal"),
    "unavailable": (lambda q: q.case in ("C1", "C2"), config.REGISTRY_ARMS, [0], "registry_unavailable"),
    "live": (lambda q: q.live, ["A3-web"], [0], "live_web"),
    "confirm": (None, None, [0, 1], "normal"),
}


def _require_key(judge: bool = False):
    if not (os.environ.get("GEMINI_API_KEY") or os.environ.get("GOOGLE_API_KEY")):
        sys.exit("Set GEMINI_API_KEY (create one at https://aistudio.google.com/apikey).")
    if judge and not os.environ.get("OPENROUTER_API_KEY"):
        sys.exit("Set OPENROUTER_API_KEY for the judge (create one at https://openrouter.ai/settings/keys), "
                 "or pass --no-score.")


def make_judge_llm() -> OpenRouterLLM:
    return OpenRouterLLM(model=config.JUDGE_MODEL, reasoning_effort=config.JUDGE_REASONING_EFFORT)


def _git_commit():
    try:
        return subprocess.run(["git", "rev-parse", "HEAD"], capture_output=True, text=True,
                              cwd=config.ROOT).stdout.strip() or None
    except OSError:
        return None


def cmd_preflight(args):
    """Fail fast: models exist, function calling round-trips, the judge returns schema JSON."""
    _require_key(judge=True)
    client = make_client()
    ok = True
    m = client.models.get(model=args.model)
    actions = m.supported_actions or []
    print(f"{args.model}: version={m.version} input_limit={m.input_token_limit} thinking={m.thinking} actions={actions}")
    if "generateContent" not in actions:
        print(f"  FAIL: {args.model} doesn't list generateContent")
        ok = False

    llm = GeminiLLM(model=args.model, client=client)
    contents = [types.Content(role="user", parts=[types.Part(text=(
        "Use check_latest_version to look up 'NIST SP 800-53 Rev 4', then tell me its status in one sentence."))])]
    turn = llm.generate(system="You are a helpful assistant.", contents=contents,
                        function_decls=[CHECK_LATEST_VERSION_DECL], seed=0)
    if not turn.function_calls:
        print(f"  FAIL: no function call returned (text: {turn.text[:200]!r})")
        ok = False
    else:
        fc = turn.function_calls[0]
        print(f"tool call OK: {fc.name}({dict(fc.args or {})}) id={fc.id}")
        contents += [turn.content, types.Content(role="user", parts=[types.Part(function_response=types.FunctionResponse(
            id=fc.id, name=fc.name,
            response={"family": "NIST-SP-800-53", "version": "Rev 4", "status": "withdrawn", "latest": "Rev 5"}))])]
        turn2 = llm.generate(system="You are a helpful assistant.", contents=contents,
                             function_decls=[CHECK_LATEST_VERSION_DECL], seed=0)
        print(f"tool round-trip OK: {turn2.text.strip()[:160]!r}")
        print(f"usage: {turn.usage} / {turn2.usage}; cost ${(turn.record['cost_usd'] or 0) + (turn2.record['cost_usd'] or 0):.5f}")

    info = get_model_info(config.JUDGE_MODEL)
    if info is None:
        print(f"  FAIL: judge model {config.JUDGE_MODEL} isn't listed on OpenRouter /api/v1/models")
        ok = False
    else:
        params = info.get("supported_parameters") or []
        print(f"judge {config.JUDGE_MODEL}: pricing={info.get('pricing', {}).get('prompt')}/"
              f"{info.get('pricing', {}).get('completion')} per token; structured outputs="
              f"{'structured_outputs' in params}; reasoning={'reasoning' in params}")
        if "structured_outputs" not in params and "response_format" not in params:
            print("  FAIL: judge model doesn't list structured_outputs / response_format")
            ok = False
    jt = make_judge_llm().generate(
        system="Reply in JSON.", seed=0,
        contents=[types.Content(role="user", parts=[types.Part(text="Is 2+2 equal to 4?")])],
        json_schema={"type": "object", "properties": {"yes": {"type": "boolean"}}, "required": ["yes"],
                     "additionalProperties": False})
    try:
        print(f"judge JSON OK: {json.loads(jt.text)} (served by {jt.record['model_version']}, "
              f"${jt.record['cost_usd'] or 0:.5f})")
    except json.JSONDecodeError:
        print(f"  FAIL: judge didn't return JSON: {jt.text[:200]!r}")
        ok = False

    if args.retrieval == "hybrid":
        vec = GeminiEmbedder(client).embed(["preflight check"])
        print(f"embeddings OK: {config.EMBED_MODEL} dim={vec.shape[1]}")
    sys.exit(0 if ok else 1)


def cmd_run(args):
    _require_key(judge=not args.no_score)
    questions = load_questions()
    qfilter, stage_arms, seeds, condition = STAGES[args.stage]
    if args.stage == "confirm":
        cs = json.loads(open(args.confirm_set).read())
        wanted, stage_arms = set(cs["questions"]), cs["arms"]
        qfilter = lambda q: q.id in wanted  # noqa: E731
    selected = [q for q in questions if qfilter(q)]
    if args.questions:
        ids = set(args.questions.split(","))
        selected = [q for q in selected if q.id in ids]
    arm_list = args.arms.split(",") if args.arms else stage_arms
    seed_list = [int(s) for s in args.seeds.split(",")] if args.seeds else seeds
    unknown = [a for a in arm_list if a not in arms.ARM_FUNCS]
    if unknown:
        sys.exit(f"Unknown arms: {unknown}")
    unverified = [q.id for q in selected if not q.verified]
    if unverified and args.stage in ("sweep", "confirm"):
        print(f"WARNING: {len(unverified)} questions still have verified=false. Verify gold answers "
              "and freeze data/ in Git before the main sweep.")

    jobs = [(q, a, s, condition) for q in selected for a in arm_list for s in seed_list]
    name = args.name or f"{args.stage}-{datetime.now().strftime('%Y%m%d-%H%M%S')}"
    run_dir = config.RUNS_DIR / name
    run_dir.mkdir(parents=True, exist_ok=True)
    (run_dir / "meta.json").write_text(json.dumps({
        "stage": args.stage, "model": args.model, "thinking_level": config.THINKING_LEVEL or "default",
        "judge_model": config.JUDGE_MODEL, "judge_reasoning_effort": config.JUDGE_REASONING_EFFORT,
        "embed_model": config.EMBED_MODEL if args.retrieval == "hybrid" else None,
        "retrieval": args.retrieval, "arms": arm_list, "seeds": seed_list, "condition": condition,
        "questions": [q.id for q in selected], "prompt_version": config.PROMPT_VERSION,
        "git_commit": _git_commit(), "started": datetime.now().isoformat(),
    }, indent=2))
    print(f"{len(jobs)} runs ({len(selected)} questions x {len(arm_list)} arms x {len(seed_list)} seeds) -> {run_dir}")

    client = make_client()
    llm = GeminiLLM(model=args.model, client=client, rpm=args.rpm)
    embedder = GeminiEmbedder(client) if args.retrieval == "hybrid" else None
    run_jobs(llm, jobs, Corpus(), load_registry(), run_dir / "results.jsonl",
             embedder=embedder, workers=args.workers, use_cache=not args.no_cache)
    if not args.no_score:
        score(run_dir, args.workers)


def score(run_dir, workers=4):
    qs = {q.id: q for q in load_questions()}
    rows = [r for r in latest_per_job(load_jsonl(run_dir / "results.jsonl")) if not r.get("error")]
    judge = Judge(make_judge_llm())
    with ThreadPoolExecutor(max_workers=workers) as pool:
        scored = list(pool.map(lambda r: score_record(r, qs[r["qid"]], judge), rows))
    with open(run_dir / "scored.jsonl", "w") as f:
        for s in scored:
            f.write(json.dumps(s) + "\n")
    report = build_report(run_dir / "scored.jsonl")
    (run_dir / "report.md").write_text(report)
    print("\n" + report)


def cmd_score(args):
    if not os.environ.get("OPENROUTER_API_KEY"):
        sys.exit("Set OPENROUTER_API_KEY for the judge (create one at https://openrouter.ai/settings/keys).")
    score(_run_dir(args.run), workers=args.workers)


def _run_dir(arg):
    p = Path(arg)
    return p if p.is_dir() else config.RUNS_DIR / arg


def cmd_report(args):
    run_dir = _run_dir(args.run)
    report = build_report(run_dir / "scored.jsonl")
    (run_dir / "report.md").write_text(report)
    print(report)


def cmd_select_confirm(args):
    cs = select_confirm(_run_dir(args.run) / "scored.jsonl", sample_n=args.sample)
    with open(args.out, "w") as f:
        json.dump(cs, f, indent=2)
    print(f"{len(cs['questions'])} questions ({len(cs['from_failures'])} from failures), arms {cs['arms']} -> {args.out}")


def cmd_handcheck(args):
    run_dir = _run_dir(args.run)
    out = run_dir / "handcheck.csv"
    n = export_handcheck(run_dir / "scored.jsonl", out)
    print(f"{n} rows -> {out}")


def main(argv=None):
    p = argparse.ArgumentParser(prog="python -m harness")
    sub = p.add_subparsers(dest="cmd", required=True)

    pf = sub.add_parser("preflight", help="check the model, tool calling and JSON output before spending money")
    pf.add_argument("--model", default=config.MODEL)
    pf.add_argument("--retrieval", choices=["hybrid", "bm25"], default="hybrid")
    pf.set_defaults(func=cmd_preflight)

    pr = sub.add_parser("run", help="run a stage, then score it")
    pr.add_argument("--stage", choices=list(STAGES), required=True)
    pr.add_argument("--model", default=config.MODEL)
    pr.add_argument("--arms", help="comma-separated, e.g. A0,A4 (default: the stage's arms)")
    pr.add_argument("--seeds", help="comma-separated, e.g. 0,1,2")
    pr.add_argument("--questions", help="comma-separated question ids to restrict to")
    pr.add_argument("--confirm-set", default=str(config.DATA_DIR / "confirm_set.json"))
    pr.add_argument("--name", help="run directory name under runs/")
    pr.add_argument("--workers", type=int, default=4)
    pr.add_argument("--rpm", type=float, default=None, help="cap on requests per minute (match your AI Studio tier)")
    pr.add_argument("--retrieval", choices=["hybrid", "bm25"], default="hybrid")
    pr.add_argument("--no-cache", action="store_true")
    pr.add_argument("--no-score", action="store_true")
    pr.set_defaults(func=cmd_run)

    ps = sub.add_parser("score", help="(re)score a run from its results.jsonl")
    ps.add_argument("--run", required=True)
    ps.add_argument("--workers", type=int, default=4)
    ps.set_defaults(func=cmd_score)

    prp = sub.add_parser("report", help="rebuild report.md from scored.jsonl (no API calls)")
    prp.add_argument("--run", required=True)
    prp.set_defaults(func=cmd_report)

    pc = sub.add_parser("select-confirm", help="pick the confirmation set from a scored sweep")
    pc.add_argument("--run", required=True)
    pc.add_argument("--sample", type=int, default=25)
    pc.add_argument("--out", default=str(config.DATA_DIR / "confirm_set.json"))
    pc.set_defaults(func=cmd_select_confirm)

    ph = sub.add_parser("handcheck", help="export a 10%% sample plus all rule/judge disagreements to CSV")
    ph.add_argument("--run", required=True)
    ph.set_defaults(func=cmd_handcheck)

    args = p.parse_args(argv)
    args.func(args)


if __name__ == "__main__":
    main()
