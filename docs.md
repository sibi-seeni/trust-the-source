# How the harness works

This is a walk-through of what happens inside the harness, from a question in `data/questions.json` to a number in `report.md`. The [README](README.md) covers what the experiment is and how to run it; this file covers how it works. The diagrams are Mermaid, which GitHub renders inline.

- [1. The big picture](#1-the-big-picture)
- [2. Data: corpus, questions, registry](#2-data-corpus-questions-registry)
- [3. Retrieval](#3-retrieval)
- [4. The mock version registry](#4-the-mock-version-registry)
- [5. The tool loop](#5-the-tool-loop)
- [6. The eight arms](#6-the-eight-arms)
- [7. Talking to OpenRouter](#7-talking-to-openrouter)
- [8. Running both models in parallel](#8-running-both-models-in-parallel)
- [9. Scoring](#9-scoring)
- [10. The report and the closure rule](#10-the-report-and-the-closure-rule)
- [11. Cost estimates](#11-cost-estimates)
- [12. Extending it](#12-extending-it)

---

## 1. The big picture

Each **run** is one (model, arm, question, seed, condition) combination. A stage, like `sweep`, is just a long list of runs. Every run goes through the same pipeline, and every step writes to a log, so any number in the report can be traced back to the exact requests that produced it.

```mermaid
flowchart LR
    subgraph data["data/"]
        Q[questions.json]
        D[docs.json]
        R[registry.json]
    end

    Q --> RET
    D --> RET[Retrieval<br/>BM25 + dense, top-5,<br/>gold passages forced in]
    RET --> ARM[Arm A0–A7<br/>builds the prompt,<br/>runs the tool loop]
    R --> REG[Mock registry<br/>check_latest_version]
    REG <--> ARM
    ARM <--> OR[(OpenRouter<br/>DeepSeek / Nemotron)]
    ARM --> RES[results.jsonl<br/>answer + full trace]

    RES --> RULE[Rule match<br/>regex on numbers/ids]
    RES --> JUDGE[LLM judge<br/>GPT-6 Luna, low effort]
    JUDGE <--> OR2[(OpenRouter<br/>GPT-6 Luna)]
    RULE --> OUT[Outcome<br/>case → label]
    JUDGE --> OUT
    OUT --> SC[scored.jsonl]
    SC --> REP[report.md<br/>headline numbers,<br/>closure rule]
    SC --> HC[handcheck.csv]
```

Code map:

| Step | Module |
|---|---|
| Loading data | `harness/data.py` |
| Retrieval | `harness/retrieval.py` |
| Registry | `harness/registry.py` |
| Arms and tool loop | `harness/arms.py`, prompt text in `harness/prompts.py` |
| Model calls | `harness/llm.py` |
| Running jobs, caching, logging | `harness/runner.py` |
| Rules, judge, outcomes | `harness/scoring.py` |
| Report, hand-check, confirmation set | `harness/report.py` |
| Cost estimates | `harness/estimate.py` |
| Settings and model table | `harness/config.py` |
| Command line | `harness/__main__.py` |

---

## 2. Data: corpus, questions, registry

Three JSON files hold everything the experiment knows. They're meant to be frozen in Git before the main sweep, and each run records the commit it used.

```mermaid
erDiagram
    FAMILY ||--o{ DOC : "has versions"
    DOC ||--|{ PASSAGE : contains
    FAMILY ||--o{ REGISTRY_VERSION : "registry knows"
    QUESTION }o--|| FAMILY : "is about"
    QUESTION }o--|{ DOC : "corpus (in scope)"
    QUESTION }o--|{ PASSAGE : "gold_passages (always retrieved)"

    DOC {
        string doc_id
        string family
        string filename "shown to the model"
        string title "shown to the model"
        object ingest "date, version, status: shown in A2 only"
        bool default_pool "distractor for other families"
    }
    PASSAGE {
        string pid
        string text
        string locator "where in the source PDF"
    }
    REGISTRY_VERSION {
        string version
        string effective
        string status "current / superseded / withdrawn"
        string superseded_by
        list changes "in-place changes, if any"
    }
    QUESTION {
        string id
        string case "C1..C7"
        string question
        string gold_answer
        string alt_answer "the other version's value"
        list accept "regexes for the gold value"
        list alt "regexes for the alternative value"
        bool pilot
        bool live
        bool verified
    }
```

How the case types are built from the corpus:

| Case | What's in the question's `corpus` | What the registry says |
|---|---|---|
| C1 | old and new versions | old is superseded, new is current |
| C2 | old version only | old is superseded by a version that isn't in the corpus |
| C3 | an undated variant (`*-undated`) | can't match a version, so it lists all known versions |
| C4 | base text only (NISPOM, NIST Rev 5 as first published) | current, but lists in-place changes dated later |
| C5 | old and new; the question names the old one | as C1 |
| C6 | old and new; the value is the same in both | as C1 |
| C7 | a doc whose filename/title say one version and whose text says another (`*-c7`) | the version from the filename, i.e. "current" |

C7 is a deliberate trap: the registry lookup succeeds and says "current", so only a model that reads the passage text notices that the header contradicts the filename.

---

## 3. Retrieval

Retrieval runs once per question, before any arm, and every arm and every model sees exactly the same five passages. Retrieval isn't what's being tested, so the version passages that matter are always included.

```mermaid
flowchart TD
    Q[Question] --> POOL["Build the pool:<br/>passages of the question's corpus docs<br/>+ default_pool docs of every other family (distractors)"]
    POOL --> BM[BM25 ranking<br/>title + text]
    POOL --> DENSE["Dense ranking<br/>OpenRouter embeddings, cosine<br/>(skipped with --retrieval bm25)"]
    BM --> RRF["Reciprocal rank fusion<br/>score = Σ 1 / (60 + rank)"]
    DENSE --> RRF
    RRF --> PICK["Take every gold passage,<br/>then fill up to 5 from the top of the fused ranking"]
    PICK --> ORDER["Present them in fused-score order<br/>(so gold isn't always listed first)"]
```

Embeddings are cached on disk by (model, text), so the corpus is embedded once. If a question's gold passage isn't in its own corpus, retrieval raises an error, and the tests catch that for every question.

---

## 4. The mock version registry

`check_latest_version(title_or_id)` is a lookup against `data/registry.json`. The matching is deliberately simple and predictable, so that results depend on the model's behaviour, not on fuzzy search luck.

```mermaid
flowchart TD
    IN["title_or_id<br/>e.g. 'NIST SP 800-53 Revision 4 (NIST.SP.800-53r4.pdf)'"] --> UNAV{Condition is<br/>registry_unavailable?}
    UNAV -- yes --> TO["{error: TIMEOUT ...}"]
    UNAV -- no --> NORM[Lower-case; _ and / become spaces]
    NORM --> FAM{Any family alias<br/>appears in the text?<br/>e.g. '800-53', 'form 1040'}
    FAM -- no --> NF["{found: false}"]
    FAM -- yes --> VER{Which version aliases match?<br/>word-bounded, e.g. 'rev 4', '2024', 'fy2025'}
    VER -- none --> UNK["version: unknown<br/>+ list of all known versions + latest"]
    VER -- one --> ONE["{version, effective, status,<br/>superseded_by, latest, changes?}"]
    VER -- several --> MANY["all matching versions"]
```

Undated documents (C3) naturally land on "version: unknown". Their titles carry no version string, so the registry can only say which versions exist, not which one the passage came from. That's exactly the situation a real lookup would be in.

The registry is a **frozen universe**: "latest" means latest among the versions in the experiment, not today's real-world latest.

---

## 5. The tool loop

Every arm that gives the model tools uses the same loop, in `arms.tool_loop`. It's written by hand, not left to an SDK, so every turn can be logged and the same code works for every model on OpenRouter.

```mermaid
flowchart TD
    START["messages = [user: question + passages]"] --> CALL["POST /chat/completions<br/>system + messages + tools"]
    CALL --> LOG[Log request, response, usage, cost]
    LOG --> TC{Tool calls<br/>in the reply?}
    TC -- no --> DONE[Return the text as the answer]
    TC -- yes --> APPEND["Append the assistant message as returned<br/>(keeps reasoning_details)"]
    APPEND --> EXEC["Run each tool locally<br/>(registry, load_skill, verify_sources)"]
    EXEC --> TOOLMSG["Append {role: tool, tool_call_id, content: JSON result}"]
    TOOLMSG --> STEP{Reached MAX_TOOL_STEPS = 4?}
    STEP -- no --> CALL
    STEP -- yes --> FORCE["One last call with tool_choice = none<br/>to force a final answer"]
    FORCE --> DONE
```

Details that matter:

- **Reasoning is kept across turns.** The assistant message goes back into the history exactly as OpenRouter returned it, including `reasoning_details`. Reasoning models need that to continue properly after a tool call; Gemini's thought signatures are the best-known case.
- **Tool results are matched by id.** Each tool reply carries the `tool_call_id` of the call it answers.
- **Bad tool calls don't crash the run.** Unknown tool names and unparseable arguments come back to the model as an error result.
- **The loop is bounded.** At most 5 model calls per loop: 4 tool-using turns, then a forced answer.

---

## 6. The eight arms

All arms share the base system prompt ("answer from the passages in 1–3 sentences, cite passage numbers"). A1–A7 add the design doc's freshness line: *"Check document dates or versions; prefer the most current; say if a source may be outdated."* What differs is how much help the model gets, and who decides whether to check.

```mermaid
flowchart LR
    subgraph g0["Nobody checks"]
        A0[A0 Plain RAG]
    end
    subgraph g1["Model checks from text"]
        A1[A1 System prompt]
        A2[A2 Metadata labels]
    end
    subgraph g2["Model decides to call the registry"]
        A3[A3 Tool]
        A5[A5 Skill]
        A6[A6 Sub-agent]
    end
    subgraph g3["Code always checks"]
        A4[A4 Forced lookup]
        A7[A7 Forced sub-agent]
    end
    g0 --> g1 --> g2 --> g3
```

### A0, A1, A2: one call, no tools

These are a single model call. A0 has no freshness line. A1 adds it. A2 also adds an ingestion metadata line to each passage, i.e. what an ingestion pipeline could read off the document itself:

```
[2] Source: NIST.SP.800-53r4.pdf | "NIST SP 800-53 Revision 4: ..."
    Metadata: date=2013-04-30 | version=Rev 4 | status=withdrawn
```

### A3: optional tool call

```mermaid
sequenceDiagram
    participant H as Harness
    participant M as Model
    participant R as Registry
    H->>M: question + passages, tools: [check_latest_version]
    alt model decides to check
        M->>H: tool call check_latest_version("2024 Instructions for Form 1040")
        H->>R: lookup
        R-->>H: {version: Tax Year 2024, status: superseded, latest: Tax Year 2025}
        H->>M: tool result
        M->>H: answer, e.g. "superseded, the current figure is..."
    else model doesn't check
        M->>H: answer straight from the passages
    end
```

`check_invoked` in the results records whether the registry was actually queried. That's the "did the model remember to check" number.

### A4: forced harness check

The harness looks up every distinct retrieved document *before* the model sees anything, using the title and filename, the same text a model would pass. It writes the result onto the passage:

```mermaid
sequenceDiagram
    participant H as Harness
    participant R as Registry
    participant M as Model
    loop each distinct document in the top-5
        H->>R: lookup("title (filename)")
        R-->>H: status
    end
    H->>M: question + annotated passages, no tools
    M->>H: answer
```

```
[1] Source: i1040gi_2024.pdf | "2024 Instructions for Form 1040"
    Registry check: IRS-1040-INSTR Tax Year 2024: SUPERSEDED, SUPERSEDED by Tax Year 2025; latest: Tax Year 2025.
```

### A5: skill

The model starts with only a `load_skill` tool. Loading `version-check` returns [`skills/version-check/SKILL.md`](skills/version-check/SKILL.md) and adds `check_latest_version` to the tool list for the rest of the conversation.

```mermaid
sequenceDiagram
    participant H as Harness
    participant M as Model
    participant R as Registry
    H->>M: question + passages, tools: [load_skill]
    opt model decides to load it
        M->>H: load_skill("version-check")
        H->>M: SKILL.md text, check_latest_version unlocked
        M->>H: check_latest_version(...)
        H->>R: lookup
        R-->>H: status
        H->>M: tool result
    end
    M->>H: answer
```

OpenRouter has no native skill primitive, so this simulates one the way agent harnesses implement skills: as on-demand instructions loaded by a tool call. The write-up should say so.

### A6 and A7: verifier sub-agent

The verifier is a separate tool loop with its own system prompt. It sees **only the passages**, not the question, plus the registry tool, and returns one JSON object per document: `{doc, status, latest_value, confidence, note}`. Its status is one of `current`, `superseded`, `withdrawn`, `amended`, `unverifiable`, `inconsistent` or `unable_to_verify`.

```mermaid
sequenceDiagram
    participant H as Harness
    participant M as Main model
    participant V as Verifier (same model, separate call)
    participant R as Registry
    Note over H,M: A6: the model decides
    H->>M: question + passages, tools: [verify_sources]
    M->>H: verify_sources()
    H->>V: passages only, tools: [check_latest_version]
    V->>R: lookups
    R-->>V: statuses
    V-->>H: JSON report
    H->>M: report as the tool result
    M->>H: answer
    Note over H,M: A7: the code always runs the verifier first
    H->>V: passages only
    V-->>H: JSON report
    H->>M: question + passages + "Source verification report", no tools
    M->>H: answer
```

If the verifier's JSON can't be parsed, its raw text is passed on instead, and `parse_error` is logged.

### A3-web: the live condition

This is A3 with OpenRouter's `openrouter:web_search` server tool instead of the registry. OpenRouter runs the search itself, so there are no local tool calls. It's reported separately and isn't scored against the closure rule.

### The registry-unavailable condition

This uses the same arms, but every registry lookup returns `{error: TIMEOUT ...}`. A4 then annotates every passage with "REGISTRY UNAVAILABLE (timeout). Freshness not verified." The correct behaviour is to answer with an "unable to verify" warning.

---

## 7. Talking to OpenRouter

`harness/llm.py` is a small OpenAI-compatible client, used for every model: the ones under test, the verifier and the judge.

```mermaid
flowchart TD
    REQ["Build the body:<br/>model slug, system + messages, temperature 0, seed,<br/>tools (function format; + openrouter:web_search for A3-web),<br/>tool_choice, reasoning.effort if set,<br/>response_format json_schema (judge only)"] --> RL[Per-model rate limiter<br/>--rpm]
    RL --> POST[POST /chat/completions]
    POST --> S{Status}
    S -- "408 / 429 / 5xx<br/>or network error" --> WAIT["Wait (Retry-After or 2s, 4s, 8s... up to 60s)<br/>up to 6 attempts"] --> POST
    S -- "other 4xx" --> ERR[Raise; the run is logged with the error, not cached]
    S -- 200 --> E{Body has error<br/>and no choices?}
    E -- yes --> WAIT
    E -- no --> PARSE["Parse: text, tool calls (args JSON-decoded),<br/>usage (prompt / output / reasoning / cached),<br/>cost = OpenRouter's reported cost, else price table,<br/>provider and served model version"]
```

- **Pinned versions:** models are pinned to dated slugs where OpenRouter has one, e.g. `deepseek/deepseek-v4.1-flash-20260910`, so results don't drift mid-run. The model version and provider actually served are logged anyway.
- **Reasoning effort:** this comes from the model table: model default for DeepSeek and Nemotron, `low` for the judge. `TTS_REASONING_EFFORT` and `TTS_JUDGE_REASONING_EFFORT` override it.
- **Usage:** reasoning tokens are split out of `completion_tokens`, so the log shows how much each model "thinks". That's the biggest driver of cost.

---

## 8. Running both models in parallel

`run` builds one list of jobs per model and **interleaves** them (`runner.interleave`), alternating models, before handing everything to a single thread pool. So both models progress together, and if you stop halfway through, both are about halfway done.

```mermaid
flowchart LR
    subgraph jobs["Job list (interleaved)"]
        J1["deepseek · A0 · irs-01 · seed 0"]
        J2["nemotron · A0 · irs-01 · seed 0"]
        J3["deepseek · A1 · irs-01 · seed 0"]
        J4["nemotron · A1 · irs-01 · seed 0"]
        J5["..."]
    end
    jobs --> POOL["Thread pool<br/>--workers 8 in total"]
    POOL --> C{In cache/runs/?}
    C -- yes --> USE[Reuse the cached result]
    C -- no --> RUN["Run the arm<br/>(that model's rate limiter applies)"]
    RUN --> OK{Error?}
    OK -- no --> SAVE[Write to cache]
    OK -- yes --> SKIP[Don't cache, so a rerun retries it]
    USE --> APP[Append a line to results.jsonl]
    SAVE --> APP
    SKIP --> APP
```

Each model has its own client and its own rate limiter, so a slow or rate-limited provider for one model doesn't throttle the other.

**Cache keys:**

| Cache | Key | Location |
|---|---|---|
| Runs | model slug, reasoning effort, arm, question, seed, condition, prompt version, retrieved passage ids | `cache/runs/` |
| Judge labels | judge model, judge effort, prompt version, judge prompt, question, answer | `cache/judge/` |
| Embeddings | embedding model, text | `cache/embeddings.json` |

`PROMPT_VERSION` in `config.py` is part of the run key, so changing a prompt or an arm and bumping it makes sure stale cached answers aren't reused.

---

## 9. Scoring

Scoring turns each answer into one outcome label, in three steps: a rule match, a judge label, and a fixed mapping from case type + labels to outcome.

### Step 1: rule match

For questions with a numeric or short-identifier answer, `accept` and `alt` regexes are tried against the normalised answer (lower-case, `$` and thousands separators removed, so "$15,750" becomes "15750").

```mermaid
flowchart TD
    A[Answer text] --> N[Normalise]
    N --> G{accept hits?}
    G -- yes --> GA{alt hits too?}
    GA -- no --> GOLD[rule = gold]
    GA -- yes --> NONE["rule = undecided<br/>(e.g. 'now $15,750, up from $14,600')"]
    G -- no --> AH{alt hits?}
    AH -- yes --> ALT[rule = alt]
    AH -- no --> NONE
```

### Step 2: the judge

GPT-6 Luna (low effort) gets the question, the reference answer, the alternative answer and the answer to label. It must reply in a strict JSON schema:

| Field | Values |
|---|---|
| `answer_matches` | `gold`, `alt`, `both`, `neither`, `no_answer`: which value the answer presents as its answer |
| `flags` | any of `outdated`, `unverifiable`, `inconsistent`, `unable_to_verify`: every freshness warning the answer actually makes |
| `mentions_newer_version` | whether a newer version is mentioned at all, warning or not |
| `rationale` | one or two sentences |

Simply citing a source's year isn't a flag, and neither is mentioning a newer value as history. The judge's instructions spell this out, because the line between "useful context" and "false flag" is exactly what C5 and C6 test.

**The rule wins when it's decided.** `matches = rule if rule is not None else judge.answer_matches`. When both exist and disagree, the row is marked `disagreement` and goes to the hand-check.

### Step 3: case → outcome

```mermaid
flowchart TD
    START{Condition} -- registry_unavailable --> U{flags include<br/>unable_to_verify?}
    U -- yes --> FC1[flagged_correctly]
    U -- no --> MF1[missed_flag]
    START -- normal --> CASE{Case}

    CASE -- C1 --> C1{matches}
    C1 -- gold --> OK1[correct]
    C1 -- alt --> ST1[stale]
    C1 -- other --> W1[wrong]

    CASE -- "C2, C4" --> C2{matches gold?}
    C2 -- yes --> OK2[correct]
    C2 -- no --> C2F{outdated / unverifiable /<br/>unable_to_verify flag?}
    C2F -- yes --> FC2[flagged_correctly]
    C2F -- no --> C2A{matches alt?}
    C2A -- yes --> ST2[stale]
    C2A -- no --> W2[wrong]

    CASE -- C3 --> C3{any flag?}
    C3 -- yes --> FC3[flagged_correctly]
    C3 -- no --> MF3[missed_flag]

    CASE -- "C5, C6" --> C5{"any flag?<br/>(C5: or matches alt)"}
    C5 -- yes --> FF[false_flag]
    C5 -- no --> C5G{matches gold?}
    C5G -- yes --> OK5[correct]
    C5G -- no --> W5[wrong]

    CASE -- C7 --> C7{inconsistent flag?}
    C7 -- yes --> FC7[flagged_correctly]
    C7 -- no --> MF7[missed_flag]
```

### Hand-check

`handcheck` exports every disagreement plus a seeded random 10% sample to `handcheck.csv`, with empty `human_outcome` and `human_note` columns for the team. That's the design doc's "hand-check a 10% sample plus all disagreements".

---

## 10. The report and the closure rule

`report.md` groups scored runs by **model** and **condition**, then by arm, keeping only the latest row per job. So there's one table for DeepSeek and one for Nemotron.

| Column | Computed over | Definition |
|---|---|---|
| Stale C1–C2 ↓ | C1 + C2 runs | share with outcome `stale` |
| Unverifiable handled C3–C4 ↑ | C3 + C4 runs | share `correct` or `flagged_correctly` |
| False flag C5–C6 ↓ | C5 + C6 runs | share `false_flag` |
| C7 flagged ↑ | C7 runs | share `flagged_correctly` |
| Overall OK | all runs | share `correct` or `flagged_correctly` |
| Registry checked (C2–C4) | C2–C4 runs, arms A3–A7 | share where the registry was actually queried |
| Cost / 100 Qs | all runs | mean OpenRouter cost per run × 100 (judge cost excluded) |
| Calls, Latency | all runs | means |

```mermaid
flowchart LR
    T[Per-arm numbers for one model] --> CHK{"stale C1–C2 ≤ 5%<br/>and false flag C5–C6 ≤ 5%?"}
    CHK -- "yes, for some arms" --> CHEAP["Closure rule met.<br/>Name the cheapest passing arm"]
    CHK -- "no arm" --> NOT[Closure rule not met]
    CHEAP --> RES["Residual limits paragraph:<br/>C3 / C4 failures handed to Track 1"]
    NOT --> RES
```

Below each table is an "Outcomes by case" breakdown, which is where the residual-limits paragraph comes from: undated documents and in-place amendments that no date check can catch. The report ends with the number of disagreements, runs with an empty answer or an error, and the judge's total cost.

`select-confirm` (only needed if a confirmation round is ever run) picks every question that any arm got wrong, plus a stratified random 25 across case types. It pairs them with arms A1, A4 and whichever model-driven arm (A3 / A5 / A6) had the lowest stale + false-flag rate.

---

## 11. Cost estimates

`estimate` multiplies the run plan by per-call token assumptions and the price table:

```
cost = Σ over stages and arms:  runs × calls_per_run(arm) × (in_tokens × $in + out_tokens × $out) / 1M
judge = runs × (900 × $in + judge_out(effort) × $out) / 1M
```

- **Calls per run** follow from how each arm works: A0–A2 and A4 make 1 call, A3 makes 2, A5 3, A6 4 and A7 3.
- **Two token scenarios:** low is 1,100 in / 400 out per call, high is 1,600 in / 1,500 out.
- **Judge output** depends on its effort: about 250–600 tokens at `low`.

With `--from-run pilot`, it replaces the assumptions with what the pilot actually measured per arm: calls per run, prompt tokens per call, and output + reasoning tokens per call. That's the more trustworthy figure.

---

## 12. Extending it

**Add a model.** Add a line to `MODELS` in `harness/config.py` with an alias, slug, price, reasoning effort and tier. Then run it with `--models <alias>` or add it to `TTS_MODELS`. Raw OpenRouter slugs work too, without a table entry; they just won't appear in estimates. Run `preflight --models <alias>` first.

**Switch the judge.** Set `TTS_JUDGE_MODEL=gpt-6-sol`. The judge must support strict JSON-schema output, which preflight checks.

**Add an arm.** Write a function `aX(ctx) -> str` in `harness/arms.py`, using `single_call` or `tool_loop`. Register it in `ARM_FUNCS` and add it to `config.ARMS`, and to `REGISTRY_ARMS` / `MODEL_DRIVEN_ARMS` if relevant. Add its calls-per-run to `estimate.CALLS_PER_RUN`. Then bump `PROMPT_VERSION`.

**Add questions or documents.** See "Adding a question" in the README. `python -m pytest` validates the whole data set offline.
