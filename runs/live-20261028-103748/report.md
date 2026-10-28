# Results: `live-20261028-103748`

## deepseek/deepseek-v4.1-flash, condition: live_web

| Arm | Runs | Stale C1–C2 ↓ | Unverifiable handled C3–C4 ↑ | False flag C5–C6 ↓ | C7 flagged ↑ | Overall OK | Registry checked (C2–C4) | Cost / 100 Qs | Calls | Latency (s) |
|---|---|---|---|---|---|---|---|---|---|---|
| A3-web | 20 | 19% (n=16) | n/a | 0% (n=4) | n/a | 85% (n=20) | – | $0.094 | 1.00 | 2.5 |

<details><summary>Outcomes by case</summary>

| Arm | Case | correct | flagged_correctly | stale | false_flag | missed_flag | wrong |
|---|---|---|---|---|---|---|---|
| A3-web | C1 | 9 | 0 | 0 | 0 | 0 | 0 |
| A3-web | C2 | 2 | 2 | 3 | 0 | 0 | 0 |
| A3-web | C5 | 2 | 0 | 0 | 0 | 0 | 0 |
| A3-web | C6 | 2 | 0 | 0 | 0 | 0 | 0 |

</details>

## google/gemma-4-31b-it, condition: live_web

| Arm | Runs | Stale C1–C2 ↓ | Unverifiable handled C3–C4 ↑ | False flag C5–C6 ↓ | C7 flagged ↑ | Overall OK | Registry checked (C2–C4) | Cost / 100 Qs | Calls | Latency (s) |
|---|---|---|---|---|---|---|---|---|---|---|
| A3-web | 20 | 44% (n=16) | n/a | 0% (n=4) | n/a | 65% (n=20) | – | $0.039 | 1.00 | 21.2 |

<details><summary>Outcomes by case</summary>

| Arm | Case | correct | flagged_correctly | stale | false_flag | missed_flag | wrong |
|---|---|---|---|---|---|---|---|
| A3-web | C1 | 9 | 0 | 0 | 0 | 0 | 0 |
| A3-web | C2 | 0 | 0 | 7 | 0 | 0 | 0 |
| A3-web | C5 | 2 | 0 | 0 | 0 | 0 | 0 |
| A3-web | C6 | 2 | 0 | 0 | 0 | 0 | 0 |

</details>

## Scoring notes

- Rule-based vs judge disagreements: 1 (export with `python -m harness handcheck`).
- Runs with an empty answer or error: 0.
- Judge cost: $0.0061 (not included in arm cost).
