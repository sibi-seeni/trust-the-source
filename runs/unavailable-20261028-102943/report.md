# Results: `unavailable-20261028-102943`

## deepseek/deepseek-v4.1-flash, condition: registry_unavailable

| Arm | Runs | Stale C1–C2 ↓ | Unverifiable handled C3–C4 ↑ | False flag C5–C6 ↓ | C7 flagged ↑ | Overall OK | Registry checked (C2–C4) | Cost / 100 Qs | Calls | Latency (s) |
|---|---|---|---|---|---|---|---|---|---|---|
| A3 | 16 | 0% (n=16) | n/a | n/a | n/a | 75% (n=16) | 100% (n=7) | $0.036 | 1.94 | 4.1 |
| A4 | 16 | 0% (n=16) | n/a | n/a | n/a | 100% (n=16) | 100% (n=7) | $0.027 | 1.00 | 3.2 |
| A5 | 16 | 0% (n=16) | n/a | n/a | n/a | 75% (n=16) | 71% (n=7) | $0.055 | 2.56 | 4.5 |
| A6 | 16 | 0% (n=16) | n/a | n/a | n/a | 94% (n=16) | 100% (n=7) | $0.109 | 5.25 | 10.1 |
| A7 | 16 | 0% (n=16) | n/a | n/a | n/a | 75% (n=16) | 100% (n=7) | $0.094 | 4.06 | 7.0 |

<details><summary>Outcomes by case</summary>

| Arm | Case | correct | flagged_correctly | stale | false_flag | missed_flag | wrong |
|---|---|---|---|---|---|---|---|
| A3 | C1 | 0 | 5 | 0 | 0 | 4 | 0 |
| A3 | C2 | 0 | 7 | 0 | 0 | 0 | 0 |
| A4 | C1 | 0 | 9 | 0 | 0 | 0 | 0 |
| A4 | C2 | 0 | 7 | 0 | 0 | 0 | 0 |
| A5 | C1 | 0 | 7 | 0 | 0 | 2 | 0 |
| A5 | C2 | 0 | 5 | 0 | 0 | 2 | 0 |
| A6 | C1 | 0 | 9 | 0 | 0 | 0 | 0 |
| A6 | C2 | 0 | 6 | 0 | 0 | 1 | 0 |
| A7 | C1 | 0 | 7 | 0 | 0 | 2 | 0 |
| A7 | C2 | 0 | 5 | 0 | 0 | 2 | 0 |

</details>

## google/gemma-4-31b-it, condition: registry_unavailable

| Arm | Runs | Stale C1–C2 ↓ | Unverifiable handled C3–C4 ↑ | False flag C5–C6 ↓ | C7 flagged ↑ | Overall OK | Registry checked (C2–C4) | Cost / 100 Qs | Calls | Latency (s) |
|---|---|---|---|---|---|---|---|---|---|---|
| A3 | 16 | 0% (n=16) | n/a | n/a | n/a | 0% (n=16) | 0% (n=7) | $0.034 | 1.00 | 16.9 |
| A4 | 16 | 0% (n=16) | n/a | n/a | n/a | 25% (n=16) | 100% (n=7) | $0.041 | 1.00 | 26.7 |
| A5 | 16 | 0% (n=16) | n/a | n/a | n/a | 0% (n=16) | 0% (n=7) | $0.034 | 1.00 | 19.0 |
| A6 | 16 | 0% (n=16) | n/a | n/a | n/a | 0% (n=16) | 0% (n=7) | $0.032 | 1.00 | 15.5 |
| A7 | 16 | 0% (n=16) | n/a | n/a | n/a | 6% (n=16) | 100% (n=7) | $0.109 | 3.00 | 46.0 |

<details><summary>Outcomes by case</summary>

| Arm | Case | correct | flagged_correctly | stale | false_flag | missed_flag | wrong |
|---|---|---|---|---|---|---|---|
| A3 | C1 | 0 | 0 | 0 | 0 | 9 | 0 |
| A3 | C2 | 0 | 0 | 0 | 0 | 7 | 0 |
| A4 | C1 | 0 | 0 | 0 | 0 | 9 | 0 |
| A4 | C2 | 0 | 4 | 0 | 0 | 3 | 0 |
| A5 | C1 | 0 | 0 | 0 | 0 | 9 | 0 |
| A5 | C2 | 0 | 0 | 0 | 0 | 7 | 0 |
| A6 | C1 | 0 | 0 | 0 | 0 | 9 | 0 |
| A6 | C2 | 0 | 0 | 0 | 0 | 7 | 0 |
| A7 | C1 | 0 | 0 | 0 | 0 | 9 | 0 |
| A7 | C2 | 0 | 1 | 0 | 0 | 6 | 0 |

</details>

## Scoring notes

- Rule-based vs judge disagreements: 3 (export with `python -m harness handcheck`).
- Runs with an empty answer or error: 0.
- Judge cost: $0.0288 (not included in arm cost).
