# Track 2 Closure Report: Does a Freshness Check Fix Stale Documents?

**Team Signet · October 28, 2026 · Experiment from the design doc of October 23, 2026**

## The short answer

**Yes, Track 2 can be closed.** If the system checks every document against a version list *before* the AI answers (arm A4), stale answers on our test drop from 44% to **0%**. That held for both AI models we tested. It cost almost nothing (about 3–5 cents per 100 questions) and it caused **no false alarms**.

Team Signet's position holds: *the harness* has to do the check. Leaving it up to the AI to remember to check only works for some models. DeepSeek usually remembers; Gemma almost never does.

The check has two limits, which we're handing to Track 1:

1. **Documents that were updated without changing their name** (like NIST SP 800-53 Rev 5, which got new controls in Releases 5.1.1 and 5.2.0 but is still called "Rev 5"). A version check says "Rev 5 is current", so it never catches these: **0 out of 12** for both models.
2. **Documents with no date, or with dates that contradict each other.** There's nothing reliable to check.

## The problem we were testing

AI assistants answer questions using documents pulled from a library (this is called RAG, retrieval-augmented generation). Sometimes the library holds an **old version** of a document: last year's tax instructions, a withdrawn security standard, or docs for an old software release. If the AI reads the old version, it can give an answer that *used* to be right but isn't anymore. We call that a **stale answer**.

The question was simple: **if we add a step that checks whether each document is the latest version, does the stale-answer problem go away?**

## How we tested it

### The test questions

We wrote **38 questions** across 5 document families, and every gold answer was checked against the real source documents:

| Family | Questions | Example |
|---|---|---|
| NIST SP 800-53 (security controls, Rev 4 vs Rev 5) | 14 | "How many control families does SP 800-53 define?" |
| IRS Form 1040 instructions (2024 vs 2025) | 9 | "What is the standard deduction for a single filer?" |
| GSA travel per diem rates (FY2024 vs FY2025) | 6 | "What is the standard CONUS lodging rate?" |
| pandas docs (1.5 vs 2.0) | 6 | "Can I use DataFrame.append?" |
| NumPy docs (1.26 vs 2.0) | 3 | "Can I use np.float_?" |

Each question tests one kind of situation, which we call a **case**:

| Case | What's going on | What a good answer does | Questions |
|---|---|---|---|
| **C1** | Both the old and the new version are in the pile | Uses the new one | 9 |
| **C2** | Only the old version is in the pile; the new one exists outside it | Warns that it's outdated, or gives the new value | 7 |
| **C3** | The document has no date or version at all | Warns that it can't be verified | 4 |
| **C4** | Same document name, but it was quietly updated later | Uses the update, or warns that there may be one | 4 |
| **C5** | The question *asks* for the old version ("for tax year 2024…") | Answers from the old version, without "correcting" it | 6 |
| **C6** | The value didn't change between versions | Just answers, with no scary warning | 6 |
| **C7** | The file name and the document header disagree about the date | Points out the mismatch | 2 |

C5 and C6 matter because they catch a lazy check that always says "pick the newest". That approach would fail them by raising **false alarms**.

### The eight ways of adding the check (the "arms")

Every question was answered eight times, once per arm. Retrieval was identical across arms; only the freshness check changed.

| Arm | What the AI gets | Who decides to check? |
|---|---|---|
| **A0** | Just the documents | Nobody (the baseline) |
| **A1** | A system-prompt line: "check dates, prefer the newest, warn if outdated" | The AI, from text alone |
| **A2** | Documents labelled with date / version / status | The AI, using the labels |
| **A3** | A `check_latest_version` tool it *can* call | The AI, if it wants to |
| **A4** | The harness looks up every document *before* answering and marks it (e.g. "SUPERSEDED by Rev 5") | **The code, always** |
| **A5** | A "skill" it can load, which unlocks the tool | The AI, if it wants to |
| **A6** | A helper "verifier" AI it can ask to check the sources | The AI decides; the helper checks |
| **A7** | The same verifier, but it always runs before the answer | **The code, always** |

The "latest version" lookups used a **mock version registry**, a fixed list of which version of each document is current. We didn't use the live web as the source of truth, because it changes from day to day and couldn't be scored.

### The models

| Role | Model | Notes |
|---|---|---|
| Model under test | DeepSeek V4.1 Flash (`deepseek/deepseek-v4.1-flash-20260910`) | default reasoning |
| Model under test | Gemma 4 31B (`google/gemma-4-31b-it-20260402`) | US open-weight model; thinking switched on; served only from fp8-or-better providers |
| Judge | GPT-6 Luna (`openai/gpt-6-luna-20260922`) | low reasoning effort; a different company from both models under test |

Gemma replaced Nemotron 3.5 Super VL on October 28 at the project sponsor's request. Nemotron's pilot results are kept in `runs/pilot/` for the record.

### How answers were graded

Each answer got one label: **correct**, **flagged correctly** (warned when it should have), **stale** (gave the old value with no warning), **false flag** (warned or "corrected" when it shouldn't have), **missed flag**, or **wrong**.

- **Numbers and IDs:** checked by pattern matching ("does the answer say $15,750?").
- **Everything else:** the judge model decided whether the answer included a freshness warning and whether that warning undermined the answer.
- **Disagreements:** every case where the pattern match and the judge disagreed was exported, together with a random 10% sample, and checked by hand (see [Hand-check](#hand-check)).

### The rule for closing the track (set before any runs)

> Track 2 is closed as *"mitigated by a harness freshness check"* if the best low-cost arm gets **stale ≤ 5% on C1–C2** and **false flags ≤ 5% on C5–C6**.

## What we ran

| Run | What it tested | Runs |
|---|---|---|
| `runs/pilot/` | Quick test: 11 questions × 8 arms, DeepSeek + Nemotron | 176 |
| `runs/pilot-gemma/` | The same quick test with Gemma | 176 |
| **`runs/sweep-20261028-010735/`** | **Main experiment: 38 questions × 8 arms × 3 repeats × 2 models** | **1,824** |
| `runs/unavailable-20261028-102943/` | The version registry "times out": does the AI admit it couldn't check? | 160 |
| `runs/live-20261028-103748/` | A3 with real web search in place of the registry (20 questions) | 40 |

**Total cost of every run, including judging: about $1.63.** All runs used code commit `277d958` and prompt version `v2`.

## Results: the main sweep

### DeepSeek V4.1 Flash

| Arm | Stale (C1–C2) ↓ | Unverifiable handled (C3–C4) ↑ | False flags (C5–C6) ↓ | Overall OK | Checked registry (C2–C4) | Cost / 100 Qs | Seconds |
|---|---|---|---|---|---|---|---|
| A0 none | 44% | 0% | 0% | 49% | – | $0.020 | 1.5 |
| A1 prompt | 12% | 38% | 0% | 80% | – | $0.033 | 2.4 |
| A2 labels | 17% | 58% | 0% | 84% | – | $0.026 | 2.4 |
| A3 tool | **2%** ✅ | 88% | 0% | 96% | 96% | $0.037 | 2.6 |
| **A4 harness check** | **0%** ✅ | 50% | 0% | 88% | 100% | **$0.035** | 2.5 |
| A5 skill | 6% ❌ | 62% | 0% | 89% | 56% | $0.048 | 3.0 |
| A6 helper | **0%** ✅ | 96% | 0% | 98% | 100% | $0.094 | 6.9 |
| A7 forced helper | **0%** ✅ | 92% | 0% | 96% | 100% | $0.093 | 7.0 |

**Passes the closure rule: A3, A4, A6, A7. Cheapest: A4.**

### Gemma 4 31B

| Arm | Stale (C1–C2) ↓ | Unverifiable handled (C3–C4) ↑ | False flags (C5–C6) ↓ | Overall OK | Checked registry (C2–C4) | Cost / 100 Qs | Seconds |
|---|---|---|---|---|---|---|---|
| A0 none | 44% | 0% | 0% | 48% | – | $0.034 | 13.1 |
| A1 prompt | 44% | 0% | 0% | 58% | – | $0.040 | 19.3 |
| A2 labels | 31% | 46% | 3% | 72% | – | $0.046 | 20.3 |
| A3 tool | 35% ❌ | 0% | 0% | 59% | **2%** | $0.036 | 19.0 |
| **A4 harness check** | **0%** ✅ | 50% | 0% | 86% | 100% | **$0.049** | 20.9 |
| A5 skill | 31% ❌ | 0% | 0% | 63% | **0%** | $0.035 | 18.0 |
| A6 helper | 42% ❌ | 0% | 0% | 57% | **0%** | $0.033 | 15.8 |
| A7 forced helper | **0%** ✅ | 88% | 0% | 94% | 100% | $0.139 | 59.2 |

**Passes the closure rule: A4, A7. Cheapest: A4.**

## What the results mean

### Question 1: Does a freshness check get rid of stale answers?

**Yes, as long as the harness does the check.** With no check, both models gave the outdated answer **44%** of the time on C1–C2. With A4 (the harness always checks), that dropped to **0%** for both. A4 also handled C3 perfectly (12 out of 12 for both models), meaning documents whose newer version exists only outside the library.

A4 also didn't make things worse elsewhere: **no false alarms** on C5–C6 for either model. When a question asked for the 2024 value, A4 still gave the 2024 value.

### Question 2: Which way of adding the check works best for the cost?

**A4, the forced harness check, for any model.** It's the cheapest arm that passes for both models. It costs about the same as doing nothing ($0.035–0.049 per 100 questions against $0.020–0.034), and it adds almost no time.

The arms where the AI *chooses* whether to check (A3, A5, A6) came out very differently for the two models:

- **DeepSeek usually remembers to check.** It called the version tool in 96% of A3 runs and used the helper in every A6 run. Those arms passed.
- **Gemma almost never checks.** It called the tool in 1 out of 45 A3 runs and never used the skill or the helper. We read its reasoning to make sure this wasn't a setup bug. The tools were offered to it every time, and preflight showed it *can* call them when told to directly. It reads the instruction "check document dates" and takes it to mean "compare the documents in front of me". It never thinks of looking further.

**This is the most important finding:** *"let the model decide" depends on which model you use, while "the harness always checks" works for both.* Swapping one model for another could quietly break any setup that relies on the AI remembering to check.

A7 (always run the helper) scored best on hard cases for Gemma (94% overall), but it costs 3 to 4 times more and is much slower (59 seconds per answer for Gemma). It's only worth it where the extra cases it catches matter (see Question 3).

### Question 3: Where does a date or version check stop working?

| Situation | A4 (harness check) | A7 (forced helper that reads the content) |
|---|---|---|
| **C4: quietly updated documents** (same name, new content) | **0/12** for both models ❌ | DeepSeek 10/12, Gemma 9/12 |
| **C7: dates that contradict each other** | DeepSeek 4/6, Gemma 2/6 | DeepSeek 3/6, Gemma 3/6 |

- **C4 is the big gap.** NIST SP 800-53 Rev 5 has been updated in place twice (Release 5.1.1 in 2023 and Release 5.2.0 in 2025, which added controls like SA-24 and SA-15(13)), but it is still called "Rev 5". The version list correctly says "Rev 5 is current", so A4 labels the old text "current" and the AI trusts it. A version-label check *cannot* catch this. A7 mostly does, because its helper compares what the registry says changed against what the text actually contains.
- **C7 (contradictory dates) is weak for every arm.** There's no single reliable date to check against.
- **Undated documents (C3) are fine with A4.** The registry says "can't confirm this version", and both models passed that warning on.

## Extra tests

### When the version registry is down

We made the registry "time out". The right behaviour is to answer, but to say that freshness couldn't be checked. (16 C1–C2 questions per arm.)

| Arm | DeepSeek warned "couldn't verify" | Gemma warned "couldn't verify" |
|---|---|---|
| A3 tool | 12/16 | 0/16 |
| **A4 harness check** | **16/16** | **4/16** |
| A5 skill | 12/16 | 0/16 |
| A6 helper | 15/16 | 0/16 |
| A7 forced helper | 12/16 | 1/16 |

With A4, the harness wrote "REGISTRY UNAVAILABLE, freshness not verified" right next to each document. DeepSeek passed that on every time. **Gemma ignored it 12 times out of 16.** It usually still picked the newer document when both were present, but it didn't tell the user that the check had failed. So the harness can't just add a note and hope the model mentions it. **If the registry is down, the harness should add the warning to the answer itself.**

### Real web search in place of the registry

We swapped the registry for real web search (A3 only, 20 questions). This isn't scored against the closure rule.

| | Stale (C1–C2) | Overall OK | Actually searched the web |
|---|---|---|---|
| DeepSeek | 19% (3/16) | 85% | 2 of 20 times |
| Gemma | 44% (7/16) | 65% | 0 of 20 times |

The interesting part: **the models hardly ever searched.** DeepSeek searched only twice, and both of those answers came out right. Gemma never searched. So this test mostly shows the same thing as Question 2: an optional tool only helps if the model decides to use it. It doesn't tell us much about whether web search would make a good freshness check.

## Hand-check

Of 1,824 sweep answers, the pattern match and the judge disagreed on **22**. **None of them changed a score:**

- **19 were on one question (nist-03).** Models answered "18 security families *and* 8 privacy families" (from Rev 4). The pattern match read that as the stale answer ("18"). The judge said "neither", because 18 + 8 isn't exactly "18". The pattern match wins in scoring, and its label (stale if there was no warning, flagged correctly if there was) was the right one every time.
- **3 were on nist-14.** DeepSeek said "no, but Release 5.2.0 added SA-15(13), so check the current text". Both readings ("correct" and "flagged correctly") count as handling the case, so nothing changes.

The unavailable and live runs had 4 more disagreements, all the same nist-03 pattern, and again no score changed.

The random sample turned up one small inconsistency. On C4, the judge sometimes counted "a newer release exists" as a warning and sometimes didn't, when the answer didn't link that fact to its own answer. That could move one or two A7 C4 runs either way. It doesn't affect the closure rule, and it doesn't touch the A4 C4 result of 0/12.

## How much to trust these numbers

- **The sample is smallish.** It's 38 questions, not the ~90 the design doc planned. Each C1–C2 percentage rests on 48 runs, but C3, C4 and C7 rest on only 12, 12 and 6. The big effects (44% → 0%, and DeepSeek against Gemma on self-checking) are far larger than that noise. The smaller differences between arms aren't.
- **The registry is a frozen, ideal world.** In real life the version list itself can be wrong or out of date. Our results assume it's right.
- **Only two models were tested.** The model-dependence finding is real, but we can't say which other models behave like DeepSeek and which like Gemma.
- **"Repeats" were at temperature 0.** The three seeds show some variation, but not as much as real-world use would.
- **Gemma was served by several different providers** (all fp8 or better). That's realistic, but it adds a little noise that a single fixed server wouldn't.

## Recommendation

1. **Close Track 2 (H6) as "mitigated by a harness freshness check".** The pre-agreed closure rule was met by A4 for both models, at almost no cost.
2. **Build it the A4 way: the harness always checks, and never relies on the model remembering to.** Mark every retrieved document with its registry status before generation.
3. **If the registry can't be reached, the harness should add its own "couldn't verify" warning to the answer.** Don't trust the model to repeat it, because Gemma didn't.

### Handed to Track 1 (what's left)

- **Documents updated in place under the same name** (C4) need more than a version label: either a registry that tracks releases and errata (e.g. "Rev 5, Release 5.2.0"), or a content check like A7 for families where this happens (NIST especially).
- **Documents with missing or contradictory dates** (C3/C7) can be flagged, but not fixed by a date check. They need better metadata at ingestion time.
- **Optional tools (A3/A5/A6, and web search) are unreliable across models.** Don't build freshness on them.

## Where everything is

- **Run folders:** each one in `runs/<name>/` has `report.md` (tables), `scored.jsonl` (every graded answer), `results.jsonl` (every full trace) and `meta.json` (exact settings). The hand-check file is `runs/sweep-20261028-010735/handcheck.csv`.
- **Rebuilding a report** from the saved runs needs no API calls: `python -m harness report --run sweep-20261028-010735`.
- **How the harness works:** see [`README.md`](README.md) and [`docs.md`](docs.md).
