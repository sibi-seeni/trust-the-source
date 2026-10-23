# trust-the-source

**Track 2 closure experiment:** does a harness-level freshness check make stale documents a non-issue?

This is a harness for the experiment in *Track 2 Closure Experiment: Freshness Check Harness Comparison* (Oct 23, 2026). The design doc names DeepSeek, GPT-6 Luna and Gemini 4 Argon on OpenRouter. This first round runs on **`gemini-3.8-flash` through Google AI Studio** (the Gemini API) instead. Everything is set up so another model can be added later for the confirmation stage.

## What it does

Every question goes through the same retrieval (hybrid BM25 + dense, top‑5, with the version passages always included). Then it's answered by one of eight arms, which differ only in how the freshness check is wired in:

| Arm | What the model gets | Who decides to check |
|---|---|---|
| A0 Plain RAG | passages only | nobody |
| A1 System prompt | passages + "Check document dates or versions; prefer the most current; say if a source may be outdated" | model, text only |
| A2 Metadata | passages tagged with ingestion date / version / status, + A1 line | model, using labels |
| A3 Tool call | passages + `check_latest_version` tool | model, optionally |
| A4 Forced harness check | code looks every retrieved doc up in the registry first and annotates it ("SUPERSEDED by Rev 5") | code, always |
| A5 Skill | `load_skill("version-check")` returns [`skills/version-check/SKILL.md`](skills/version-check/SKILL.md) and unlocks the registry tool | model decides to load it |
| A6 Sub-agent | `verify_sources()` runs a separate verifier call that only sees the passages + registry and returns JSON | model delegates |
| A7 Forced sub-agent | same verifier, always run by code before answering | code, always |

The "online check" is a **mock version registry** ([`data/registry.json`](data/registry.json)). There are two extra conditions:

- **Registry unavailable:** the tool times out, and the correct behaviour is to answer with an "unable to verify" warning.
- **Live web:** A3 with Gemini's Google Search grounding in place of the registry, on a 20-question subset. It's reported separately and not scored against the closure rule.

Each question has exactly one case type (C1–C7, as in the design doc). Outcomes are scored as `correct / flagged_correctly / stale / false_flag / missed_flag / wrong`. The report gives, per arm:

- stale rate on C1–C2
- unverifiable handling on C3–C4
- false-flag rate on C5–C6
- cost per 100 questions
- registry-check rate for the model-driven arms

It also checks the **closure rule** (stale ≤ 5% and false flags ≤ 5%).

## Layout

```
data/docs.json         corpus: 19 documents across 7 families (D1–D7), passage text + ingestion metadata
data/questions.json    question set with case type, gold / alternative answers, gold passages
data/registry.json     mock version registry
skills/version-check/  the skill loaded by arm A5
harness/               the experiment code (python -m harness ...)
tests/                 offline tests with a scripted fake model (no API key needed)
runs/<name>/           per-run output: meta.json, results.jsonl, scored.jsonl, report.md, handcheck.csv
cache/                 response, judge and embedding caches (git-ignored)
```

## Setup

```bash
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
export GEMINI_API_KEY=...        # from https://aistudio.google.com/apikey
python -m pytest -q              # offline sanity check
python -m harness preflight      # checks the model, a tool-call round-trip, JSON output and embeddings
```

Preflight costs a fraction of a cent. It exits non-zero if function calling or JSON output doesn't work, so you find out before spending anything.

## Run order (design doc section 8)

```bash
# 1. Pilot: ~10 questions x 8 arms x 1 seed. Check tool calls, parsing and the scorer.
python -m harness run --stage pilot --name pilot

# -- before step 2: verify the data and freeze it (see "Before the main sweep") --

# 2. Main sweep: all questions x 8 arms x 3 seeds
python -m harness run --stage sweep --name sweep

# 2b. Registry unavailable: C1–C2 x registry arms (A3–A7)
python -m harness run --stage unavailable --name unavailable

# 3. Pick the confirmation set (questions any arm got wrong + 25 stratified), arms A1, A4 + best model-driven arm
python -m harness select-confirm --run sweep          # writes data/confirm_set.json

# 4. Confirmation on another model, when you get to it
python -m harness run --stage confirm --model <other-gemini-model> --name confirm-<model>

# 5. Live web subset: 20 questions x A3 with Google Search grounding
python -m harness run --stage live --name live

# Hand-check: 10% random sample + every rule/judge disagreement -> runs/<name>/handcheck.csv
python -m harness handcheck --run sweep
```

Useful flags for `run`:

- `--arms A0,A4` and `--questions irs-01,nist-03` narrow a run.
- `--seeds 0` sets the seeds.
- `--workers 4` sets parallelism.
- `--rpm 10` caps requests per minute to fit your AI Studio rate-limit tier.
- `--retrieval bm25` skips the embedding calls.
- `--no-cache` forces fresh calls.
- `--no-score` skips scoring.

Results are cached by (model, thinking level, arm, question, seed, condition, prompt version, retrieved passages), so reruns only pay for new prompts. `python -m harness score --run <name>` re-scores from `results.jsonl` without rerunning the arms. `report` rebuilds the table with no API calls at all.

## Before the main sweep

The data here is a **draft** that's meant to be checked before anyone quotes a number from it.

- **Passages are paraphrased stand-ins.** I couldn't pull the source PDFs from this environment, so each passage in `docs.json` is a short paraphrase of the relevant section. Each one has a `source_url` and `locator`. Swap in verbatim text from the real documents.
- **Every question is `verified: false`.** The gold answers are figures I'm confident about (for example, the 2025 standard deduction of $15,750 after the 2025 tax law change, Rev 5's 20 control families, and FY2025 per diem of $110 / $68), but someone should check each one against the source and flip it to `true`. `run --stage sweep` warns while any are unverified.
- **42 of the ~90 targeted questions are written.** The case mix is about 43% C1–C2, 17% C3–C4, 33% C5–C6 and 7% C7. Add more in the same format; the tests check that every new question's corpus, gold passages and regexes hold together.
- **D5 is a stand-in.** It uses the NISPOM (DoD 5220.22-M, Feb 28 2006, amended in place by Changes 1 and 2) for the "same base date, amended in place" case. In reality, the NISPOM was replaced by 32 CFR Part 117 in 2021, and the mock registry deliberately leaves that out. A currently active DoDI with a Change notice would be a better D5 if the team has one in mind.
- **The registry is a frozen universe.** "Latest" means latest *among the versions in this experiment*. FY2026 per diem rates and newer pandas releases are left out on purpose.
- **Freeze `data/` in Git** before the sweep. Each run's `meta.json` records the commit it ran on.

## Where this differs from the design doc (Gemini on AI Studio)

- **No temperature 0 or fixed top‑k.** Google's docs for Gemini 3.8 Flash say temperature, top_k and top_p are ignored by the backend. They aren't sent. Reasoning effort is the default `thinking_level` (MEDIUM), and it's logged on every call. Set `TTS_THINKING_LEVEL=LOW|MEDIUM|HIGH` to change it.
- **Seeds:** a `seed` is passed and logged, and each condition still runs 3 times. Treat the seeds as repeated samples for measuring variance, not as a determinism guarantee.
- **Judge:** the LLM judge that labels flags runs on `gemini-3.8-flash` too, at `thinking_level=LOW`. Using the same model for both answering and judging is a possible bias, so the hand-check of 10% + all disagreements matters more. Override it with `TTS_JUDGE_MODEL`. Rule-based regex matching takes precedence wherever the answer is numeric or a short identifier.
- **Skill (A5):** there's no native skill primitive in the Gemini API. A skill is simulated as an on-demand instruction load through a tool call that also unlocks the registry tool. Say so in the write-up.
- **Live web:** uses Gemini's Google Search grounding tool instead of OpenRouter's web search. Grounded requests may be billed separately from tokens. Check the AI Studio pricing page.
- **Model check:** the "assert `tools` in `supported_parameters`" check is replaced by `preflight`, which confirms the model exists and actually round-trips a function call.
- **Thought signatures:** function calling is handled manually, and the model's turn is appended to the history as returned, which keeps Gemini 3 thought signatures intact.
- **Cost:** computed at $0.75 / $3.75 per 1M input/output tokens (introductory pricing through 2026). Thinking tokens count as output. Verify against your AI Studio usage page; prices live in `harness/config.py`.

## Rough cost

Each call is short (five short passages), but thinking tokens dominate output. Expect a few tenths of a cent per call. That puts the full 42-question sweep (~1,000 runs, ~2,000 calls) roughly in the **$5–15** range, plus a smaller amount for the judge. The pilot report's "Cost / 100 Qs" column gives you the real figure before you commit to the sweep.
