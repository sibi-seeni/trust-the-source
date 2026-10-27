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

The corpus has 15 documents across 5 families. Each family has at least two versions, so both dated and undated version signals can be tested. D4 (Army FM 3-0) and D5 (NISPOM) were dropped because no primary copy of them could be fetched to verify against (see [Data verification](#data-verification)); the labels are kept so older notes still line up.

| # | Family | Docs in corpus | Version signal | Why it's included |
|---|---|---|---|---|
| D1 | IRS Form 1040 Instructions, 2024 vs 2025 | `irs-2024`, `irs-2025` | tax year in the title | continuity with the MVP; annual numeric changes |
| D2 | NIST SP 800-53 Rev 4 vs Rev 5 | `nist-r4`, `nist-r5` | revision number; Rev 4 withdrawn; Rev 5 amended in place by Releases 5.1.1 and 5.2.0 | standards and controls; closest to DoD security documentation; also carries the "same designation, amended in place" case |
| D3 | GSA per diem rates, FY2024 vs FY2025 | `gsa-fy24`, `gsa-fy25` | fiscal year, table-heavy | numeric tables |
| D6 | pandas 1.5 vs 2.0, NumPy 1.26 vs 2.0 | `pandas-1.5`, `pandas-2.0`, `numpy-1.26`, `numpy-2.0` | version number, no date | the version matters, not the date |
| D7 | undated variants of D1, D2, D6, plus filename/header mismatches | `irs-undated`, `nist-undated`, `pandas-undated`, `irs-c7`, `nist-c7` | none, or contradictory | what happens when there's nothing (or the wrong thing) to check |

### Case types

Each question gets exactly one case type:

| Case | Situation | Correct behaviour | Questions now |
|---|---|---|---|
| C1 | old and new versions both retrieved | answer from the newer version | 9 |
| C2 | only the old version is in the corpus; the newer one is only in the registry | flag that it's outdated, or give the newer value | 7 |
| C3 | the retrieved document has no date or version | flag it as unverifiable; don't answer confidently | 4 |
| C4 | change notice / errata: same designation, a later release added or amended content | use the amended content, or flag a possible amendment | 4 |
| C5 | the question asks for the older version ("for tax year 2024…") | answer from the older version. Flagging it or "correcting" it is a **false flag** | 6 |
| C6 | the value didn't change between versions | answer normally. Any warning is a **false flag** | 6 |
| C7 | the filename date and the header date disagree | flag the inconsistency | 2 |

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
data/docs.json          corpus: 15 documents across 5 families (D1–D3, D6, D7), verbatim passage text + ingestion metadata
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

# -- before step 2: freeze data/ in Git (see "Data verification") --

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

| Stage | Questions | Arms | Seeds | Condition | Runs per model (38 Qs) |
|---|---|---|---|---|---|
| `pilot` | the 11 with `pilot: true` | A0–A7 | 0 | normal | 88 |
| `sweep` | all | A0–A7 | 0, 1, 2 | normal | 912 |
| `unavailable` | C1–C2 | A3–A7 | 0 | registry times out | 80 |
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

## Data verification

Every passage in `data/docs.json` is now verbatim text from the official source, and every question is `verified: true`. This was checked on Oct 27, 2026, against these copies:

| Family | What it was checked against |
|---|---|
| D1 IRS | the 2024 and 2025 Instructions for Form 1040 PDFs on irs.gov |
| D2 NIST | the Rev 4 and Rev 5 PDFs on nvlpubs.nist.gov (Rev 5 as published Sept 2020 with updates to 12-10-2020), NIST's OSCAL Rev 5 catalog for IA-13 / SA-24 / SA-15(13) / SI-02(07) and the 5.1.1 date, and NIST's *Summary of Changes: SP 800-53 Release 5.2.0* (Aug 27, 2025) |
| D3 GSA | GSA's FY2024 and FY2025 per diem highlights, FTR Bulletin 25-01 and the M&IE breakdown files |
| D6 pandas / NumPy | the pandas 1.5.3 and 2.0.3 docs, and the NumPy 1.26 and 2.0 docs |

How the passages were built:

- **Excerpts are copied word for word.** Separate excerpts from the same section are joined with a space. Table rows are rendered from the table cells, as `ID Name;` for NIST and `header: value | ...` for GSA. Each passage's `locator` says where it comes from. Every excerpt was checked against the downloaded text (case-sensitive, ignoring whitespace and punctuation).
- **`variant_of` documents are deliberate edits.** These are the undated and filename-mismatch (`*-c7`) docs. Each is built from a verified passage, and its `source_url` describes the edit: dropping the tax year, the "Revision 4" running header, or the "since version 1.4.0".
- **C4 now comes from NIST's in-place releases.** The registry lists Release 5.1.1 (IA-13) and Release 5.2.0 (SA-24, SA-15(13), SI-02(07)). The corpus has Rev 5 as published in 2020, which has none of these.

A few things were deliberately changed or left out:

- **D4 (FM 3-0) and D5 (NISPOM) were dropped**, along with their seven questions.
  - FM 3-0: the 2022 PDF has been removed from armypubs.army.mil, the 2017 edition isn't hosted there, and the Army now lists a 21 March 2025 edition as active.
  - NISPOM: esd.whs.mil refuses automated downloads, and the 2006 manual was replaced by 32 CFR Part 117 in 2021. Its Change 2 details could only be confirmed from secondary sources.
  - Either family can come back if someone supplies the PDFs.
- **irs-04 was reworded.** It now asks about the age/blindness amount per box checked. That's because the 2025 instructions also add a separate $6,000 senior deduction (Schedule 1-A), which made the old wording ambiguous.
- **The NumPy 2.0 `numpy.nan` passage leaves out one sentence.** That page still says "NaN and NAN are aliases of nan", which is stale after 2.0 removed `np.NaN`.
- **38 of the ~90 targeted questions are written.** By family: IRS 9, NIST 14, GSA 6, pandas 6, NumPy 3. The case mix is about 42% C1–C2, 21% C3–C4, 32% C5–C6 and 5% C7, against the doc's 40 / 20 / 30 / 10. Add more questions in the same format (see below), and verify them the same way.
- **The registry is a frozen universe.** "Latest" means latest *among the versions in this experiment*. FY2026/FY2027 per diem rates, pandas 3.x and newer NumPy releases are left out on purpose.
- **Freeze `data/` in Git** before the sweep. Each run's `meta.json` records the commit it ran on.

## Cost estimate

`python -m harness estimate` prints this table. The token assumptions are about 1,100–1,600 input tokens per call (the base prompt measures about 670) and 400–1,500 output tokens per call. Reasoning tokens are the big unknown. On the current 38 questions, the plan per model is 88 pilot runs, 912 sweep runs, 80 registry-unavailable runs and 20 live runs: 1,100 runs per model, 2,200 across both, with one judge call each.

| | Pilot | Sweep | Unavailable | Live | Total |
|---|---|---|---|---|---|
| DeepSeek V4.1 Flash | $0.05–0.15 | $0.51–1.57 | $0.06–0.18 | $0.01–0.03 | **$0.62–1.94** |
| Nemotron 3.5 Super VL | $0.05–0.13 | $0.49–1.39 | $0.06–0.16 | $0.01–0.03 | **$0.61–1.71** |
| Judge: GPT-6 Luna, low effort (~250–600 output tokens per label) | | | | | **$0.47–0.86** |
| **Everything** | | | | | **≈ $1.70–4.50** |

Add a few cents for embeddings and the live stage's web search fees. At the doc's ~90 questions, everything comes to **≈ $3.80–10.10** (`estimate --questions 90`). For comparison, GPT-6 Sol as the judge would cost about $9–17 on its own at 38 questions.

After the pilot, `estimate --from-run pilot` redoes the table from the tokens that were actually used, per arm. That's the number to trust before committing to the sweep.

## Tests

```bash
python -m pytest -q
```

The tests run offline against a scripted fake model and a mocked OpenRouter transport. They cover data integrity (every question's corpus, gold passages and regexes), registry lookups, every arm's tool loop (including the skill unlock and the verifier), the outcome mapping for every case, the OpenRouter request format and usage parsing, the parallel two-model runner with caching, and the report.
