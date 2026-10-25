# trust-the-source

**Track 2 closure experiment:** does a harness-level freshness check make stale documents a non-issue?

This is a harness for the experiment in *Track 2 Closure Experiment: Freshness Check Harness Comparison* (Oct 23, 2026). Every model is called through **OpenRouter**. The current budget setup is:

| Role | Model (alias → OpenRouter slug) | $ / 1M tokens in / out |
|---|---|---|
| Main sweep | `deepseek-flash` → `deepseek/deepseek-v4.1-flash-20260910` | $0.07 / $0.50 |
| Confirmation | `glm-5.3` → `z-ai/glm-5.3-20260816` (reasoning effort `low`) | $1.40 / $4.40 |
| Judge | `gpt-6-luna` → `openai/gpt-6-luna` | $0.10 / $0.50 |

The funded-tier models are still in [`harness/config.py`](harness/config.py), so switching to them is a single flag: `gpt-6-sol`, `gemini-4-argon` and `gemini-3.8-flash`. For example, `--model gemini-3.8-flash` or `TTS_JUDGE_MODEL=gpt-6-sol`. Any other OpenRouter slug also works with `--model`.

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
- **Live web:** A3 with OpenRouter's `openrouter:web_search` server tool in place of the registry, on a 20-question subset. It's reported separately and not scored against the closure rule.

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
export OPENROUTER_API_KEY=...    # from https://openrouter.ai/settings/keys
python -m pytest -q              # offline sanity check
python -m harness estimate       # cost per stage and model (no API calls)
python -m harness preflight      # checks the models, a tool-call round-trip, judge JSON output and embeddings
```

Preflight costs a fraction of a cent. It does what the design doc's section 10 asks: it fetches `/api/v1/models`, and fails if a model isn't listed, if a model under test doesn't list `tools` in `supported_parameters`, or if the judge doesn't list structured outputs. It also prints each model's live price next to the price in the config table. Then it runs a real tool-call round-trip on each model under test and a schema-JSON call on the judge. Check another model with `--models gemini-4-argon,gpt-6-sol`.

To keep spending under control, set a credit limit on the API key in the OpenRouter dashboard.

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

# 4. Confirmation on the second model (glm-5.3 by default; --model gemini-4-argon once funded)
python -m harness run --stage confirm --name confirm-glm

# Re-estimate from what the pilot actually used, before committing to the sweep
python -m harness estimate --from-run pilot --questions 90

# 5. Live web subset: 20 questions x A3 with OpenRouter web search
python -m harness run --stage live --name live

# Hand-check: 10% random sample + every rule/judge disagreement -> runs/<name>/handcheck.csv
python -m harness handcheck --run sweep
```

Useful flags for `run`:

- `--arms A0,A4` and `--questions irs-01,nist-03` narrow a run.
- `--seeds 0` sets the seeds.
- `--workers 4` sets parallelism.
- `--model glm-5.3` (or any alias / slug) picks the model.
- `--rpm 10` caps requests per minute.
- `--retrieval bm25` skips the embedding calls (`openai/text-embedding-3-small` by default, a few cents' worth at most).
- `--no-cache` forces fresh calls.
- `--no-score` skips scoring.

Results are cached by (model, reasoning effort, arm, question, seed, condition, prompt version, retrieved passages), so reruns only pay for new prompts. `python -m harness score --run <name>` re-scores from `results.jsonl` without rerunning the arms. `report` rebuilds the table with no API calls at all.

## Before the main sweep

The data here is a **draft** that's meant to be checked before anyone quotes a number from it.

- **Passages are paraphrased stand-ins.** I couldn't pull the source PDFs from this environment, so each passage in `docs.json` is a short paraphrase of the relevant section. Each one has a `source_url` and `locator`. Swap in verbatim text from the real documents.
- **Every question is `verified: false`.** The gold answers are figures I'm confident about (for example, the 2025 standard deduction of $15,750 after the 2025 tax law change, Rev 5's 20 control families, and FY2025 per diem of $110 / $68), but someone should check each one against the source and flip it to `true`. `run --stage sweep` warns while any are unverified.
- **42 of the ~90 targeted questions are written.** The case mix is about 43% C1–C2, 17% C3–C4, 33% C5–C6 and 7% C7. Add more in the same format; the tests check that every new question's corpus, gold passages and regexes hold together.
- **D5 is a stand-in.** It uses the NISPOM (DoD 5220.22-M, Feb 28 2006, amended in place by Changes 1 and 2) for the "same base date, amended in place" case. In reality, the NISPOM was replaced by 32 CFR Part 117 in 2021, and the mock registry deliberately leaves that out. A currently active DoDI with a Change notice would be a better D5 if the team has one in mind.
- **The registry is a frozen universe.** "Latest" means latest *among the versions in this experiment*. FY2026 per diem rates and newer pandas releases are left out on purpose.
- **Freeze `data/` in Git** before the sweep. Each run's `meta.json` records the commit it ran on.

## Where this differs from the design doc

- **Models:** the main sweep runs on DeepSeek V4.1 Flash, as in the design doc. Confirmation uses GLM 5.3 rather than GPT-6 Luna and Gemini 4 Argon, and the judge is GPT-6 Luna rather than DeepSeek. Luna is cheap, it's a different model family from both models under test, and it supports strict JSON-schema output. For the funded run, use Sol as the judge and Argon / Gemini 3.8 Flash for confirmation.
- **GLM 5.3 reasoning:** GLM 5.3 always reasons, and its default effort is `max`, which multiplies output tokens. It's set to `low` to keep it in budget, which departs from the doc's "reasoning effort kept at the default". Everything else uses its model default. Change it with `TTS_REASONING_EFFORT`, which overrides every model; whatever is used is logged on every call.
- **Temperature and seeds:** temperature 0 and a seed are sent on every call and logged. Some models ignore them, notably reasoning models and Gemini 3.8 Flash, which Google says ignores sampling settings. So treat the three seeds as repeated samples for measuring variance, not as a determinism guarantee. The design doc's fixed top‑k isn't sent, because not all of these models support it.
- **Providers:** OpenRouter may route a model to different providers. The provider and the exact model version served are logged per call (`provider`, `model_version` in the trace), so you can check this afterwards.
- **Judge:** rule-based regex matching takes precedence wherever the answer is numeric or a short identifier. Luna labels the freshness flags, and the hand-check of 10% + all disagreements still applies.
- **Skill (A5):** OpenRouter has no native skill primitive. A skill is simulated as an on-demand instruction load through a tool call that also unlocks the registry tool. Say so in the write-up.
- **Reasoning across tool turns:** tool calling is handled manually. The assistant message is appended to the history exactly as returned, including `reasoning_details`, which OpenRouter needs back for reasoning models (for example, Gemini's thought signatures).
- **Cost:** the cost logged per call is what OpenRouter reports, so it includes web search fees. The price table in `config.py` is used only for estimates and as a fallback.

## Cost estimate

`python -m harness estimate` prints this table. The token assumptions are about 1,100–1,600 input tokens per call (the base prompt measures about 670) and 400–1,500 output tokens per call. Reasoning tokens are the big unknown. On the current 42 questions, the full design-doc plan comes to 88 pilot runs, 1,008 sweep runs, 90 registry-unavailable runs, 20 live runs and about 240 confirmation runs.

| Model | Pilot | Sweep | Unavailable | Live | Confirmation set | Full plan on this model (excl. confirm) |
|---|---|---|---|---|---|---|
| DeepSeek V4.1 Flash | $0.05–0.15 | $0.56–1.74 | $0.06–0.20 | $0.01–0.03 | $0.09–0.28 | **$0.68–2.13** |
| GLM 5.3 (effort low) | $0.58–1.56 | $6.65–17.82 | $0.77–2.07 | $0.13–0.35 | $1.06–2.83 | **$8.14–21.80** |
| Gemini 3.8 Flash (funded) | $0.41–1.20 | $4.69–13.76 | $0.54–1.60 | $0.09–0.27 | $0.74–2.18 | $5.73–16.83 |

The judge makes one short call per run: about **$0.31–0.56 on GPT-6 Luna**, or $6–11 on GPT-6 Sol.

**Recommended budget plan:** run the full plan on DeepSeek, then only the confirmation set on GLM 5.3, with Luna as the judge. That's about **$1.10–3.00** in total, plus a few cents for embeddings and web search. Running the full sweep on GLM 5.3 as well costs roughly 12× DeepSeek. Scaling to the doc's 90 questions roughly doubles the sweep figures (`estimate --questions 90`). After the pilot, `estimate --from-run pilot` redoes the table from the tokens that were actually used.
