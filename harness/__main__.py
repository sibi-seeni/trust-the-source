"""Command line: python -m harness <command> [options]. See README.md."""

import argparse
import json
import os
import subprocess
import sys
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
from pathlib import Path

from . import arms, config
from .data import Corpus, load_questions, load_registry
from .estimate import estimate, measured_profile
from .llm import OpenRouterLLM, list_endpoints, list_models
from .registry import CHECK_LATEST_VERSION_DECL
from .report import build_report, export_handcheck, latest_per_job, load_jsonl, select_confirm
from .retrieval import OpenRouterEmbedder
from .runner import interleave, run_jobs
from .scoring import JUDGE_SCHEMA, Judge, score_record

STAGES = {
    # stage: (question filter, arms, seeds, condition)
    "pilot": (lambda q: q.pilot, config.ARMS, [0], "normal"),
    "sweep": (lambda q: True, config.ARMS, config.SEEDS, "normal"),
    "unavailable": (lambda q: q.case in ("C1", "C2"), config.REGISTRY_ARMS, [0], "registry_unavailable"),
    "live": (lambda q: q.live, ["A3-web"], [0], "live_web"),
    "confirm": (None, None, [0, 1], "normal"),
}


def _require_key():
    if not os.environ.get("OPENROUTER_API_KEY"):
        sys.exit("Set OPENROUTER_API_KEY (create one at https://openrouter.ai/settings/keys).")


def _git_commit():
    try:
        return subprocess.run(["git", "rev-parse", "HEAD"], capture_output=True, text=True,
                              cwd=config.ROOT).stdout.strip() or None
    except OSError:
        return None


def make_judge_llm() -> OpenRouterLLM:
    return OpenRouterLLM(model=config.JUDGE_MODEL, reasoning_effort=config.JUDGE_REASONING_OVERRIDE)


def _check_listing(alias, listing, need):
    """Design doc section 10: the model must be listed and support what we need."""
    spec = config.resolve(alias)
    info = listing.get(spec["slug"])
    if info is None:
        print(f"  FAIL {alias}: {spec['slug']} isn't listed on OpenRouter /api/v1/models")
        return False
    pinned, served = spec.get("canonical"), info.get("canonical_slug")
    if pinned and served != pinned:
        print(f"  FAIL {alias}: {spec['slug']} now resolves to {served}, not the pinned {pinned}. "
              f"Update 'canonical' (and the price) in harness/config.py only if the new version is intended.")
        return False
    params = set(info.get("supported_parameters") or [])
    pr = info.get("pricing") or {}
    live = (float(pr.get("prompt") or 0) * 1e6, float(pr.get("completion") or 0) * 1e6)
    table = spec["price"]
    note = "" if table and all(abs(a - b) < 1e-6 for a, b in zip(live, table)) else f"  (config table says {table})"
    print(f"{alias} -> {spec['slug']} ({served}): ${live[0]:.2f}/${live[1]:.2f} per 1M{note}; "
          f"reasoning={'reasoning' in params} effort={spec['reasoning'] or 'default'}")
    missing = [n for n in need if not ({n} if isinstance(n, str) else set(n)) & params]
    for n in missing:
        print(f"  FAIL {alias}: supported_parameters lacks {n}")
    return not missing


# OpenRouter's quantization filter counts these variants as their base format.
_QUANT_FAMILY = {"mxfp8": "fp8", "mxfp4": "fp4", "nvfp4": "fp4"}


def _check_endpoints(alias, endpoints, need):
    """A model with a provider quantization filter must still have at least one
    endpoint that passes it and supports what we need."""
    allowed = set((config.resolve(alias).get("provider") or {}).get("quantizations") or [])
    if not allowed:
        return True
    ok = [e for e in endpoints
          if (q := e.get("quantization") or "unknown") in allowed or _QUANT_FAMILY.get(q) in allowed
          if set(need) <= set(e.get("supported_parameters") or [])]
    names = ", ".join(f"{e['provider_name']} ({e.get('quantization')})" for e in ok)
    if not ok:
        print(f"  FAIL {alias}: no endpoint serves it at {sorted(allowed)} with {need}")
    else:
        print(f"  {alias}: {len(ok)} of {len(endpoints)} endpoints pass the quantization filter: {names}")
    return bool(ok)


def cmd_preflight(args):
    """Fail fast before spending: models are listed with tool / JSON support, a tool
    call round-trips, the judge returns schema JSON, embeddings work."""
    _require_key()
    listing = list_models()
    models = args.models.split(",") if args.models else config.SWEEP_MODELS
    ok = all([_check_listing(m, listing, ["tools", "tool_choice"]) for m in models])
    ok &= all([_check_endpoints(m, list_endpoints(config.resolve(m)["slug"]), ["tools", "tool_choice"])
               for m in models if config.resolve(m).get("provider")])
    ok &= _check_listing(config.JUDGE_MODEL, listing, [("structured_outputs", "response_format")])
    if not ok:
        sys.exit(1)

    for alias in models:
        llm = OpenRouterLLM(model=alias, reasoning_effort=config.REASONING_OVERRIDE)
        sys_msg = "You are a helpful assistant."
        messages = [{"role": "user", "content": (
            "Use check_latest_version to look up 'NIST SP 800-53 Rev 4', then tell me its status in one sentence.")}]
        turn = llm.generate(system=sys_msg, messages=messages, tools=[CHECK_LATEST_VERSION_DECL], seed=0)
        if not turn.tool_calls:
            print(f"  FAIL {alias}: no tool call returned (text: {turn.text[:200]!r})")
            ok = False
            continue
        tc = turn.tool_calls[0]
        messages += [turn.message, {"role": "tool", "tool_call_id": tc.id, "content": json.dumps(
            {"family": "NIST-SP-800-53", "version": "Rev 4", "status": "withdrawn", "latest": "Rev 5"})}]
        turn2 = llm.generate(system=sys_msg, messages=messages, tools=[CHECK_LATEST_VERSION_DECL], seed=0)
        cost = (turn.record["cost_usd"] or 0) + (turn2.record["cost_usd"] or 0)
        thoughts = turn.usage["thoughts"] + turn2.usage["thoughts"]
        print(f"{alias}: tool round-trip OK via {turn.record['provider']} ({turn.record['model_version']}): "
              f"{turn2.text.strip()[:120]!r} | {thoughts} reasoning tokens | ${cost:.5f}")
        if llm.reasoning_effort == "on" and not thoughts:
            print(f"  FAIL {alias}: reasoning is set to 'on' but no reasoning tokens came back")
            ok = False

    jt = make_judge_llm().generate(
        system="You label answers.", seed=0,
        messages=[{"role": "user", "content": "QUESTION: What is 2+2?\nREFERENCE answer: 4\nALTERNATIVE answer: 5\n"
                                              "ANSWER TO LABEL:\nIt's 4."}],
        json_schema=JUDGE_SCHEMA)
    try:
        print(f"judge {config.JUDGE_MODEL}: JSON OK {json.loads(jt.text)} via {jt.record['provider']}, "
              f"${jt.record['cost_usd'] or 0:.5f}")
    except json.JSONDecodeError:
        print(f"  FAIL judge didn't return JSON: {jt.text[:200]!r}")
        ok = False

    if args.retrieval == "hybrid":
        vec = OpenRouterEmbedder(make_judge_llm().http).embed(["preflight check"])
        print(f"embeddings OK: {config.EMBED_MODEL} dim={vec.shape[1]}")
    sys.exit(0 if ok else 1)


def cmd_estimate(args):
    questions = load_questions()
    models = args.models.split(",") if args.models else config.SWEEP_MODELS
    judges = args.judges.split(",") if args.judges else [config.JUDGE_MODEL, "gpt-6-sol"]
    profile = measured_profile(_run_dir(args.from_run) / "results.jsonl") if args.from_run else None
    n = args.questions or len(questions)
    print(f"# Cost estimate ({n} questions{', measured from ' + args.from_run if args.from_run else ''})\n")
    print(estimate(questions, models, judges, n_questions=args.questions, profile=profile))


def cmd_run(args):
    _require_key()
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

    if args.stage == "confirm" and not args.models:
        sys.exit("--stage confirm needs --models (no confirmation model is configured for this track).")
    # One client per model, each with its own rate limiter; their jobs share one worker pool.
    llms = [OpenRouterLLM(model=m, reasoning_effort=config.REASONING_OVERRIDE, rpm=args.rpm)
            for m in (args.models.split(",") if args.models else config.SWEEP_MODELS)]
    base_jobs = [(q, a, s, condition) for q in selected for a in arm_list for s in seed_list]
    jobs = interleave(llms, base_jobs)
    judge = make_judge_llm() if not args.no_score else None
    name = args.name or f"{args.stage}-{datetime.now().strftime('%Y%m%d-%H%M%S')}"
    run_dir = config.RUNS_DIR / name
    run_dir.mkdir(parents=True, exist_ok=True)
    (run_dir / "meta.json").write_text(json.dumps({
        "stage": args.stage,
        "models": [{"alias": m.alias, "slug": m.model, "reasoning_effort": m.reasoning_effort or "default",
                    **({"provider_filter": m.provider} if m.provider else {})} for m in llms],
        "temperature": config.TEMPERATURE,
        "judge_model": config.resolve(config.JUDGE_MODEL)["slug"],
        "judge_reasoning_effort": (judge.reasoning_effort if judge else
                                   config.JUDGE_REASONING_OVERRIDE or config.resolve(config.JUDGE_MODEL)["reasoning"]),
        "embed_model": config.EMBED_MODEL if args.retrieval == "hybrid" else None,
        "retrieval": args.retrieval, "arms": arm_list, "seeds": seed_list, "condition": condition,
        "questions": [q.id for q in selected], "prompt_version": config.PROMPT_VERSION,
        "git_commit": _git_commit(), "started": datetime.now().isoformat(),
    }, indent=2))
    print(f"{len(jobs)} runs ({len(selected)} questions x {len(arm_list)} arms x {len(seed_list)} seeds "
          f"x {len(llms)} models: {', '.join(m.alias for m in llms)}) -> {run_dir}")

    embedder = OpenRouterEmbedder(llms[0].http) if args.retrieval == "hybrid" else None
    run_jobs(jobs, Corpus(), load_registry(), run_dir / "results.jsonl",
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
    _require_key()
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

    pf = sub.add_parser("preflight", help="check the models, tool calling and JSON output before spending money")
    pf.add_argument("--models", help=f"comma-separated aliases or slugs (default: {','.join(config.SWEEP_MODELS)})")
    pf.add_argument("--retrieval", choices=["hybrid", "bm25"], default="hybrid")
    pf.set_defaults(func=cmd_preflight)

    pr = sub.add_parser("run", help="run a stage, then score it")
    pr.add_argument("--stage", choices=list(STAGES), required=True)
    pr.add_argument("--models", help=f"comma-separated aliases ({', '.join(config.MODELS)}) or OpenRouter slugs, "
                                     f"run in parallel (default: {','.join(config.SWEEP_MODELS)})")
    pr.add_argument("--arms", help="comma-separated, e.g. A0,A4 (default: the stage's arms)")
    pr.add_argument("--seeds", help="comma-separated, e.g. 0,1,2")
    pr.add_argument("--questions", help="comma-separated question ids to restrict to")
    pr.add_argument("--confirm-set", default=str(config.DATA_DIR / "confirm_set.json"))
    pr.add_argument("--name", help="run directory name under runs/")
    pr.add_argument("--workers", type=int, default=8, help="parallel runs across all models")
    pr.add_argument("--rpm", type=float, default=None, help="cap on requests per minute, per model")
    pr.add_argument("--retrieval", choices=["hybrid", "bm25"], default="hybrid")
    pr.add_argument("--no-cache", action="store_true")
    pr.add_argument("--no-score", action="store_true")
    pr.set_defaults(func=cmd_run)

    pe = sub.add_parser("estimate", help="estimate cost per stage and model (no API calls)")
    pe.add_argument("--models", help=f"comma-separated aliases (default: {','.join(config.SWEEP_MODELS)})")
    pe.add_argument("--judges", help=f"comma-separated aliases (default: {config.JUDGE_MODEL},gpt-6-sol)")
    pe.add_argument("--questions", type=int, help="scale to this many questions (e.g. 90)")
    pe.add_argument("--from-run", help="use measured tokens and calls from this run (e.g. the pilot)")
    pe.set_defaults(func=cmd_estimate)

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
