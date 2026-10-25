"""Running jobs (question x arm x seed x condition), with caching and JSONL logs."""

import hashlib
import json
import threading
import time
import traceback
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone

from . import arms, config
from .registry import MockRegistry
from .retrieval import retrieve


def job_key(model, reasoning, arm, qid, seed, condition, retrieved) -> str:
    blob = json.dumps([model, reasoning or "default", arm, qid, seed, condition, config.PROMPT_VERSION, retrieved])
    return hashlib.sha256(blob.encode()).hexdigest()[:24]


def run_one(llm, q, arm, seed, condition, passages, registry_data) -> dict:
    registry = MockRegistry(registry_data, unavailable=condition == "registry_unavailable")
    ctx = arms.RunContext(question=q, passages=passages, registry=registry, llm=llm, seed=seed)
    t0 = time.monotonic()
    error = None
    answer = None
    try:
        answer = arms.ARM_FUNCS[arm](ctx)
    except Exception as e:  # logged and left out of the cache, so a rerun retries it
        error = f"{type(e).__name__}: {e}\n{traceback.format_exc(limit=3)}"
    llm_calls = [e for e in ctx.trace if e["type"] == "llm_call"]
    usage = {k: sum(c["usage"].get(k, 0) for c in llm_calls)
             for k in ("prompt", "output", "thoughts", "cached")}
    costs = [c["cost_usd"] for c in llm_calls]
    return {
        "model": llm.model, "model_alias": llm.alias, "reasoning_effort": llm.reasoning_effort or "default",
        "arm": arm, "qid": q.id, "case": q.case, "family": q.family, "seed": seed, "condition": condition,
        "prompt_version": config.PROMPT_VERSION,
        "retrieved": [p.pid for p in passages],
        "answer": answer, "error": error,
        "check_invoked": arms.registry_was_checked(ctx.trace),
        "n_calls": len(llm_calls),
        "usage": usage,
        "cost_usd": None if any(c is None for c in costs) else sum(costs),
        "latency_s": round(time.monotonic() - t0, 3),
        "model_versions": sorted({c["model_version"] for c in llm_calls if c.get("model_version")}),
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "trace": ctx.trace,
    }


def run_jobs(llm, jobs, corpus, registry_data, out_path, embedder=None, workers=4, use_cache=True) -> list[dict]:
    """jobs: list of (question, arm, seed, condition). Appends one JSON line per run to out_path."""
    retrieved = {}
    for q, *_ in jobs:
        if q.id not in retrieved:
            retrieved[q.id] = retrieve(q, corpus.pool_for(q), embedder=embedder)

    cache_dir = config.CACHE_DIR / "runs"
    cache_dir.mkdir(parents=True, exist_ok=True)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    lock = threading.Lock()
    results = []

    def work(job):
        q, arm, seed, condition = job
        passages = retrieved[q.id]
        key = job_key(llm.model, llm.reasoning_effort, arm, q.id, seed, condition, [p.pid for p in passages])
        cpath = cache_dir / f"{key}.json"
        if use_cache and cpath.exists():
            rec = json.loads(cpath.read_text())
            rec["from_cache"] = True
        else:
            rec = run_one(llm, q, arm, seed, condition, passages, registry_data)
            rec["key"] = key
            if rec["error"] is None:
                cpath.write_text(json.dumps(rec))
            rec["from_cache"] = False
        with lock:
            with out_path.open("a") as f:
                f.write(json.dumps(rec) + "\n")
            results.append(rec)
        return rec

    done = 0
    with ThreadPoolExecutor(max_workers=workers) as pool:
        futures = [pool.submit(work, j) for j in jobs]
        for fut in as_completed(futures):
            rec = fut.result()
            done += 1
            status = "ERROR" if rec["error"] else ("cached" if rec["from_cache"] else f"${rec['cost_usd'] or 0:.4f}")
            print(f"[{done}/{len(jobs)}] {rec['arm']:6} {rec['qid']:10} seed={rec['seed']} "
                  f"{rec['condition']:20} calls={rec['n_calls']} {status}", flush=True)
            if rec["error"]:
                print("   " + rec["error"].splitlines()[0], flush=True)
    return results
