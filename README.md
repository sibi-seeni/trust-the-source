# trust-the-source

**Track 2 closure experiment:** does a harness-level freshness check make stale documents a non-issue?

This repo is the harness for the experiment in *Track 2 Closure Experiment: Freshness Check Harness Comparison* (Oct 23, 2026, Team Signet). Dr. Gasbarro's position is that stale or superseded documents (H6, Track 2) are handled once the harness checks whether a document is the latest version. The experiment is meant to confirm that cheaply and close the track, not to reopen it. It answers three questions:

1. **Does a freshness check eliminate stale answers?** We look at this both when the newer version is in the corpus and when it exists only outside it.
2. **Which way of wiring the check in works best for its cost?** The options are a system prompt, metadata, a tool call, a forced pre-check, a skill or a sub-agent.
3. **Where does a date-based check stop working?** That means undated documents, in-place amendments, and cases where the older version is actually the right one.

**How it all works under the hood**, with diagrams of every arm, the scoring logic, caching and the parallel runner, is in **[docs.md](docs.md)**.

## Models

Every model is called through **OpenRouter** (`https://openrouter.ai/api/v1`) with one API key. The current budget setup is:

| Role | Alias → OpenRouter slug | Reasoning effort | $ / 1M tokens in / out |
|---|---|---|---|
| Main sweep | `deepseek-flash` → `deepseek/deepseek-v4.1-flash-20260910` | model default | $0.07 / $0.50 |
| Main sweep | `nemotron-3.5-super-vl` → `nvidia/nemotron-3.5-super-vl-20261015` | model default (reasons by default) | $0.10 / $0.40 |
| Judge | `gpt-6-luna` → `openai/gpt-6-luna-20260922` | `low` | $0.10 / $0.50 |

**Both main-sweep models run in parallel.** Each stage sends every question × arm × seed to both models through one shared worker pool. The jobs alternate between models, so neither finishes far ahead of the other. Results go into the same run folder, and the report gives each model its own table and its own closure-rule check. No confirmation model is configured, since this track is being wrapped up.

The other models are kept in [`harness/config.py`](harness/config.py), so switching to them is one flag or environment variable:

| Alias | OpenRouter slug | Tier | Reasoning effort | $ / 1M in / out | Intended use |
|---|---|---|---|---|---|
| `glm-5.3` | `z-ai/glm-5.3-20260816` | budget | `low` (its default is `max`) | $1.40 / $4.40 | optional extra model under test |
| `gpt-6-sol` | `openai/gpt-6-sol-20260922` | funded | `low` | $2.00 / $10.00 | judge once there's funding |
| `gemini-4-argon` | `google/gemini-4-argon` | funded | default | $2.00 / $10.00 | confirmation model from the design doc |
| `gemini-3.8-flash` | `google/gemini-3.8-flash-20260902` | funded | default | $0.75 / $3.75 | the model this harness was first built for |

For example: `--models deepseek-flash,gemini-3.8-flash`, `TTS_JUDGE_MODEL=gpt-6-sol`. Any other OpenRouter slug also works in `--models`; the price table is only needed for estimates, because the logged cost comes from OpenRouter itself. Prices are from the OpenRouter model pages in Oct 2026. `preflight` prints the live prices next to the table so you can spot drift.

## What it does

Every question goes through the same retrieval: hybrid BM25 + dense, top‑5, with the version passages always included, because retrieval isn't what's being tested. It's then answered by one of eight **arms**, which differ only in how the freshness check is wired in:

| Arm | What the model gets | Who decides to check | Model calls per question |
|---|---|---|---|
| A0 Plain RAG | passages only | nobody | 1 |
| A1 System prompt | passages + "Check document dates or versions; prefer the most current; say if a source may be outdated" | model, from text only | 1 |
| A2 Metadata | passages tagged with ingestion date / version / status, + the A1 line | model, using labels | 1 |
| A3 Tool call | passages + `check_latest_version` tool | model, optionally | 1–5 |
| A4 Forced harness check | code looks every retrieved doc up in the registry *before* generation and annotates it ("SUPERSEDED by Rev 5") | code, always | 1 + lookups |
| A5 Skill | a `load_skill("version-check")` tool returns [`skills/version-check/SKILL.md`](skills/version-check/SKILL.md) and unlocks the registry tool | model decides to load it | 1–5 |
| A6 Sub-agent | the model calls `verify_sources()`; a separate verifier call that only sees the passages + registry returns JSON `{doc, status, latest_value, confidence, note}` | model delegates, verifier decides | 2+ |
| A7 Forced sub-agent | same verifier, always run by code before the answer | code, always | 2+ |

**Why A4 and A7 matter:** they test Gasbarro's exact claim that *the harness* does the check. A3, A5 and A6 test whether the model remembers to check when it's left to decide. The gap between those two groups is the most quotable result in the report.

### The "online check": a mock version registry

The live web as ground truth would drift and couldn't be scored, so the main experiment uses a **mock version registry**, [`data/registry.json`](data/registry.json). The model reaches it as the tool `check_latest_version(title_or_id)`. Each entry looks like this:

```json
{"family": "NIST-SP-800-53", "version": "Rev 4", "effective": "2013-04-30",
 "status": "withdrawn", "withdrawn": "2021-09-23", "superseded_by": "Rev 5", "latest": "Rev 5"}
```

There are two extra conditions:

- **Registry unavailable:** the tool returns a timeout. Correct behaviour is to answer with an "unable to verify freshness" warning.
- **Live web:** A3 with OpenRouter's `openrouter:web_search` server tool in place of the registry, on a 20-question subset. It's reported separately and not scored against the closure rule.

### Document families

The corpus has 19 documents across 7 families. Each family has at least two versions, so both dated and undated version signals can be tested.

| # | Family | Docs in corpus | Version signal | Why it's included |
|---|---|---|---|---|
| D1 | IRS Form 1040 Instructions, 2024 vs 2025 | `irs-2024`, `irs-2025` | tax year in the title | continuity with the MVP; annual numeric changes |
| D2 | NIST SP 800-53 Rev 4 vs Rev 5 | `nist-r4`, `nist-r5` | revision number; Rev 4 withdrawn | standards and controls; closest to DoD security documentation |
| D3 | GSA per diem rates, FY2024 vs FY2025 | `gsa-fy24`, `gsa-fy25` | fiscal year, table-heavy | numeric tables |
| D4 | Army FM 3-0, 2017 vs 2022 | `fm30-2017`, `fm30-2022` | "supersedes" statement in front matter | military terminology; a version signal in prose |
| D5 | DoD 5220.22-M (NISPOM), base text with in-place Changes 1 and 2 | `nispom-base` | same base date, amended in place | the case where checking a date isn't enough |
| D6 | pandas 1.5 vs 2.0, NumPy 1.26 vs 2.0 | `pandas-1.5`, `pandas-2.0`, `numpy-1.26`, `numpy-2.0` | version number, no date | the version matters, not the date |
| D7 | undated variants of D1, D2, D6, plus filename/header mismatches | `irs-undated`, `nist-undated`, `pandas-undated`, `irs-c7`, `nist-c7`, `fm30-c7` | none, or contradictory | what happens when there's nothing (or the wrong thing) to check |

### Case types

Each question gets exactly one case type:

| Case | Situation | Correct behaviour | Questions now |
|---|---|---|---|
| C1 | old and new versions both retrieved | answer from the newer version | 10 |
| C2 | only the old version is in the corpus; the newer one is only in the registry | flag that it's outdated, or give the newer value | 8 |
| C3 | the retrieved document has no date or version | flag it as unverifiable; don't answer confidently | 4 |
| C4 | change notice / errata: same base date, a value was amended | use the amended value, or flag a possible amendment | 3 |
| C5 | the question asks for the older version ("for tax year 2024…") | answer from the older version. Flagging it or "correcting" it is a **false flag** | 7 |
| C6 | the value didn't change between versions | answer normally. Any warning is a **false flag** | 7 |
| C7 | the filename date and the header date disagree | flag the inconsistency | 3 |

C5 and C6 are what stop a check that just says "always pick newest" from looking good.

### Outcomes and headline numbers

Every run is labelled with one outcome:

| Outcome | Meaning |
|---|---|
| `correct` | gave the right version's value without an unwarranted warning |
| `flagged_correctly` | raised the right kind of warning (outdated / unverifiable / inconsistent / unable to verify) where one was needed |
| `stale` | presented the outdated value as the answer, with no warning |
| `false_flag` | warned or "corrected" when the question asked for the old version (C5) or the value hadn't changed (C6) |
| `missed_flag` | answered without the warning that C3 / C7 / registry-unavailable require |
| `wrong` | anything else |

The report gives these per model and arm, always together:

- **Stale-answer rate** on C1–C2
- **Unverifiable handling** on C3–C4 (correct or flagged correctly)
- **False-flag rate** on C5–C6
- **Cost per 100 questions** (from OpenRouter's reported cost)
- plus the C7 flag rate, the overall OK rate, the registry-check rate on C2–C4 for A3–A7, average calls and latency.

**Closure rule** (decided before running): Track 2 is closed as *"mitigated by a harness freshness check"* if the best low-cost arm reaches **stale ≤ 5% on C1–C2** and **false flags ≤ 5% on C5–C6**. The report checks this for each model and names the cheapest arm that meets it. Whatever fails after that (expected: undated documents and in-place edits) becomes a short residual-limits paragraph handed to Track 1.

**Scoring:** a rule-based regex match is used wherever the answer is numeric or a short identifier. The LLM judge (GPT-6 Luna) labels freshness flags, and labels answers the rules can't settle. Every rule/judge disagreement is exported for a hand-check, along with a random 10% sample.

## Layout

```
data/docs.json          corpus: 19 documents across 7 families (D1–D7), passage text + ingestion metadata
data/questions.json     question set: case type, gold / alternative answers, gold passages, regexes
data/registry.json      mock version registry
data/confirm_set.json   written by select-confirm (only if a confirmation round is ever run)
skills/version-check/   the skill loaded by arm A5
harness/
  __main__.py           command line: preflight, estimate, run, score, report, handcheck, select-confirm
  config.py             model table, defaults, environment variables
  llm.py                OpenRouter client: tool calls, reasoning, retries, rate limiting, cost
  arms.py               the eight arms (+ A3-web) and the tool loop
  registry.py           mock registry lookup and the check_latest_version tool
  retrieval.py          BM25 + dense (OpenRouter embeddings), reciprocal rank fusion, gold passages forced in
  runner.py             parallel job runner across models, caching, JSONL logging
  scoring.py            rule matching, LLM judge, case → outcome mapping
  report.py             headline tables, closure rule, hand-check export, confirmation-set selection
  estimate.py           cost estimates from assumptions or from a finished run
  data.py, prompts.py   loading the data; prompt text shared by all arms
tests/                  offline tests with a scripted fake model (no API key needed)
runs/<name>/            per-run output (see below)
cache/                  response, judge and embedding caches (git-ignored)
docs.md                 how it all works, with diagrams
```

## Setup

```bash
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
export OPENROUTER_API_KEY=...    # from https://openrouter.ai/settings/keys
python -m pytest -q              # offline sanity check, no key needed
python -m harness estimate       # cost per stage and model, no API calls
python -m harness preflight      # checks the models, a tool-call round-trip, judge JSON output and embeddings
```

**Preflight** costs a fraction of a cent. It does the check the design doc's section 10 asks for. It fetches `/api/v1/models`, and it fails if a model isn't listed, if a model under test doesn't list `tools` / `tool_choice` in `supported_parameters`, or if the judge doesn't list structured outputs. It prints each model's live price next to the price in the config table. It then runs a real tool-call round-trip on each model under test and a schema-JSON call on the judge, and finally an embedding call. By default it checks both sweep models; check others with `--models gemini-4-argon,glm-5.3`.

To keep spending under control, **set a credit limit on the API key** in the OpenRouter dashboard.

## Run order (design doc section 8)

```bash
# 1. Pilot: 11 questions x 8 arms x 1 seed, on both models. Check tool calls, parsing and the scorer.
python -m harness run --stage pilot --name pilot

# Re-estimate from what the pilot actually used, before committing to the sweep
python -m harness estimate --from-run pilot

# -- before step 2: verify the data and freeze it (see "Before the main sweep") --

# 2. Main sweep: all questions x 8 arms x 3 seeds, on both models
python -m harness run --stage sweep --name sweep

# 2b. Registry unavailable: C1–C2 questions x registry arms (A3–A7)
python -m harness run --stage unavailable --name unavailable

# 3. Live web subset: 20 questions x A3 with OpenRouter web search
python -m harness run --stage live --name live

# Hand-check: 10% random sample + every rule/judge disagreement -> runs/<name>/handcheck.csv
python -m harness handcheck --run sweep

# Not planned for this track, but still available: confirmation set + confirm stage on a named model
python -m harness select-confirm --run sweep          # writes data/confirm_set.json
python -m harness run --stage confirm --models gemini-4-argon --name confirm-argon
```

What each stage runs:

| Stage | Questions | Arms | Seeds | Condition | Runs per model (42 Qs) |
|---|---|---|---|---|---|
| `pilot` | the 11 with `pilot: true` | A0–A7 | 0 | normal | 88 |
| `sweep` | all | A0–A7 | 0, 1, 2 | normal | 1,008 |
| `unavailable` | C1–C2 | A3–A7 | 0 | registry times out | 90 |
| `live` | the 20 with `live: true` | A3-web | 0 | web search instead of registry | 20 |
| `confirm` | from `data/confirm_set.json` | from the file (A1, A4, best model-driven arm) | 0, 1 | normal | depends |

All commands:

| Command | What it does | Needs the API key? |
|---|---|---|
| `preflight [--models ...] [--retrieval bm25]` | checks models, tool round-trip, judge JSON, embeddings | yes |
| `estimate [--models ...] [--judges ...] [--questions 90] [--from-run pilot]` | prints a cost table | no |
| `run --stage S [flags]` | runs a stage on all models in parallel, then scores it | yes |
| `score --run NAME` | re-scores a run from its `results.jsonl` (judge calls are cached) | yes |
| `report --run NAME` | rebuilds `report.md` from `scored.jsonl` | no |
| `handcheck --run NAME` | writes `handcheck.csv`: 10% sample + all rule/judge disagreements | no |
| `select-confirm --run NAME` | picks the confirmation set from a scored sweep | no |

Useful flags for `run`:

- `--arms A0,A4` and `--questions irs-01,nist-03` narrow a run.
- `--seeds 0` sets the seeds.
- `--models deepseek-flash` runs a single model; any comma-separated list of aliases or slugs runs those models in parallel.
- `--workers 8` is the total number of runs in flight across all models (the default).
- `--rpm 10` caps requests per minute, per model. Use it if a provider starts rate-limiting.
- `--retrieval bm25` skips the embedding calls (`openai/text-embedding-3-small` by default, a few cents' worth at most).
- `--no-cache` forces fresh calls.
- `--no-score` skips scoring.
- `--name sweep` names the run folder; otherwise it's `<stage>-<timestamp>`.

**Caching:** results are cached by (model, reasoning effort, arm, question, seed, condition, prompt version, retrieved passages), so reruns only pay for new prompts. An interrupted stage can simply be re-run with the same command. Failed runs aren't cached, so a rerun retries them. Judge labels are cached by (judge model, effort, prompt, answer). `score` re-scores without re-running the arms, and `report` rebuilds the tables with no API calls at all.

### Environment variables

| Variable | Default | Effect |
|---|---|---|
| `OPENROUTER_API_KEY` | — | required for preflight, run and score |
| `TTS_MODELS` | `deepseek-flash,nemotron-3.5-super-vl` | models under test (same as `--models`) |
| `TTS_JUDGE_MODEL` | `gpt-6-luna` | judge model, alias or slug |
| `TTS_REASONING_EFFORT` | unset (table value) | overrides reasoning effort for the models under test |
| `TTS_JUDGE_REASONING_EFFORT` | unset (`low` from the table) | overrides the judge's reasoning effort |
| `TTS_EMBED_MODEL` | `openai/text-embedding-3-small` | embedding model for the dense half of retrieval |

## Output of a run

Everything for a run lands in `runs/<name>/`:

| File | Contents |
|---|---|
| `meta.json` | stage, models with slug and reasoning effort, judge, temperature, arms, seeds, questions, prompt version, git commit, start time |
| `results.jsonl` | one line per run: model, arm, question, case, seed, condition, retrieved passage ids, answer, `check_invoked`, number of calls, token usage, cost, latency, served model versions, and the **full trace**: every request and response, tool call and registry lookup |
| `scored.jsonl` | one line per run: rule match, judge match, disagreement flag, flags, outcome, judge rationale, cost |
| `report.md` | the headline tables per model and condition, the closure-rule result, outcomes by case |
| `handcheck.csv` | rows for the hand-check, with empty `human_outcome` / `human_note` columns to fill in |

Because every request and response is logged, any result can be re-scored or audited later without rerunning it. That also covers Avital's "log what was retrieved" point. `results.jsonl` is append-only; the report keeps the latest row per job.

## Before the main sweep

The data here is a **draft**, meant to be checked before anyone quotes a number from it.

- **Passages are paraphrased stand-ins.** The source PDFs couldn't be pulled from the environment this was built in, so each passage in `docs.json` is a short paraphrase of the relevant section, with a `source_url` and `locator` to find it. Swap in verbatim text from the real documents.
- **Every question is `verified: false`.** The gold answers are figures we're confident about, for example the 2025 standard deduction of $15,750 after the 2025 tax law change, Rev 5's 20 control families, and FY2025 per diem of $110 / $68. Someone should still check each one against the source and flip it to `true`. `run --stage sweep` warns while any are unverified.
- **42 of the ~90 targeted questions are written.** By family: IRS 9, NIST 11, GSA 6, FM 3-0 5, NISPOM 2, pandas 6, NumPy 3. The case mix is about 43% C1–C2, 17% C3–C4, 33% C5–C6 and 7% C7, against the doc's 40 / 20 / 30 / 10. Add more questions in the same format (see below).
- **D5 is a stand-in.** It uses the NISPOM (DoD 5220.22-M, Feb 28 2006, amended in place by Changes 1 and 2) for the "same base date, amended in place" case. In reality, the NISPOM was replaced by 32 CFR Part 117 in 2021, and the mock registry leaves that out on purpose. A currently active DoDI with a Change notice would be a better D5 if the team has one in mind.
- **The registry is a frozen universe.** "Latest" means latest *among the versions in this experiment*. FY2026 per diem rates and newer pandas releases are left out on purpose.
- **Freeze `data/` in Git** before the sweep. Each run's `meta.json` records the commit it ran on.

### Adding a question

Add an entry to `data/questions.json`:

```json
{"id": "irs-10", "family": "IRS-1040-INSTR", "case": "C1", "pilot": false, "live": false, "verified": false,
 "question": "What is the standard deduction for a qualifying surviving spouse?",
 "corpus": ["irs-2024", "irs-2025"], "gold_passages": ["irs-2024-p1", "irs-2025-p1"],
 "gold_answer": "$31,500 (2025 instructions)", "alt_answer": "$29,200 (2024 instructions)",
 "accept": ["\\b31500\\b"], "alt": ["\\b29200\\b"]}
```

- `corpus` is the docs "in the corpus" for this question. The latest docs of the other families are added automatically as distractors.
- `gold_passages` must belong to those docs; they're always retrieved.
- `accept` / `alt` are regexes over the lower-cased answer with `$` and thousands separators removed. Leave both empty for free-text answers, and the judge decides.
- For C5, `alt_answer` is the newer version's value, i.e. the wrong "correction".

`python -m pytest` checks that every question's corpus, gold passages and regexes hold together. New documents go in `data/docs.json`, and their families must exist in `data/registry.json`.

## Where this differs from the design doc

- **Models:** the main sweep runs on two models in parallel: DeepSeek V4.1 Flash (as in the design doc) and Nemotron 3.5 Super VL. The doc instead had DeepSeek followed by a GPT-6 Luna / Gemini 4 Argon confirmation round, and there's no confirmation round here. The judge is GPT-6 Luna rather than DeepSeek: it's cheap, it's from a different model family from both models under test, and it supports strict JSON-schema output. For a funded run, switch the judge to GPT-6 Sol and add Gemini 4 Argon / Gemini 3.8 Flash with `--models`.
- **Reasoning effort:** both models under test run at their default effort, as the design doc asks, and Nemotron reasons by default. The judge runs Luna at `low` to keep scoring cheap. `TTS_REASONING_EFFORT` overrides the models under test and `TTS_JUDGE_REASONING_EFFORT` overrides the judge. Whatever is used is logged on every call. GLM 5.3, if used, is set to `low`, because its default is `max`.
- **Nemotron and tools:** OpenRouter routes requests that include tools only to the Nemotron providers that support tool calling, which is 3 of the 4. Preflight confirms the tool round-trip actually works before you spend anything.
- **Temperature and seeds:** temperature 0 and a seed are sent on every call and logged. Some models ignore them, notably reasoning models and Gemini 3.8 Flash, which Google says ignores sampling settings. Treat the three seeds as repeated samples for measuring variance, not as a determinism guarantee. The design doc's fixed top‑k isn't sent, because not all of these models support it.
- **Pinning and providers:** dated slugs are pinned where OpenRouter lists one, so results don't shift mid-run. OpenRouter may still route a model to different providers, so the provider and the exact model version served are logged per call (`provider`, `model_version` in the trace).
- **Judge:** a rule-based regex match takes precedence wherever the answer is numeric or a short identifier. Luna labels the freshness flags, and the hand-check of 10% + all disagreements still applies, for each model's runs.
- **Skill (A5):** OpenRouter has no native skill primitive. A skill is simulated as an on-demand instruction load through a tool call that also unlocks the registry tool, which is how skills work in agent harnesses. Say so in the write-up.
- **Reasoning across tool turns:** tool calling is handled manually. The assistant message is appended to the history exactly as returned, including `reasoning_details`, which OpenRouter needs back for reasoning models (for example, Gemini's thought signatures).
- **Live web:** OpenRouter's `openrouter:web_search` server tool, which replaced the deprecated `:online` suffix the doc mentions.
- **Cost:** the cost logged per call is what OpenRouter reports, so it includes web search fees. The price table in `config.py` is only used for estimates and as a fallback.

## Cost estimate

`python -m harness estimate` prints this table. The token assumptions are about 1,100–1,600 input tokens per call (the base prompt measures about 670) and 400–1,500 output tokens per call. Reasoning tokens are the big unknown. On the current 42 questions, the plan per model is 88 pilot runs, 1,008 sweep runs, 90 registry-unavailable runs and 20 live runs: 1,206 runs per model, 2,412 across both, with one judge call each.

| | Pilot | Sweep | Unavailable | Live | Total |
|---|---|---|---|---|---|
| DeepSeek V4.1 Flash | $0.05–0.15 | $0.56–1.74 | $0.06–0.20 | $0.01–0.03 | **$0.68–2.13** |
| Nemotron 3.5 Super VL | $0.05–0.13 | $0.54–1.53 | $0.06–0.18 | $0.01–0.03 | **$0.67–1.87** |
| Judge: GPT-6 Luna, low effort (~250–600 output tokens per label) | | | | | **$0.52–0.94** |
| **Everything** | | | | | **≈ $1.90–4.95** |

Add a few cents for embeddings and the live stage's web search fees. At the doc's ~90 questions, everything comes to **≈ $3.80–10.10** (`estimate --questions 90`). For comparison, GPT-6 Sol as the judge would cost about $10–19 on its own at 42 questions.

After the pilot, `estimate --from-run pilot` redoes the table from the tokens that were actually used, per arm. That's the number to trust before committing to the sweep.

## Tests

```bash
python -m pytest -q
```

The tests run offline against a scripted fake model and a mocked OpenRouter transport. They cover data integrity (every question's corpus, gold passages and regexes), registry lookups, every arm's tool loop (including the skill unlock and the verifier), the outcome mapping for every case, the OpenRouter request format and usage parsing, the parallel two-model runner with caching, and the report.
