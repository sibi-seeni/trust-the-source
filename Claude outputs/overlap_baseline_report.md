## 1. Overlap alone (Chris's check)

| Passages | n | Overlap with closest 2024 passage, median (min-max) |
|---|---:|---|
| Clean 2025, stable values | 11 | 0.721 (0.625-0.982) |
| Clean 2025, values changed in 2025 | 9 | 0.854 (0.625-0.909) |
| Edited 2025, stable values | 11 | 0.715 (0.627-0.972) |
| Edited 2025, values changed in 2025 | 9 | 0.852 (0.627-0.905) |

AUROC, edited vs clean using overlap alone (0.5 = coin flip): **0.51**

Overlap drop caused by the edit, same passage: median 0.0040, max 0.0359

Best threshold with at most 2/20 false flags on clean passages: catches 4/20 edits (2/20 false flags).

## 2. Overlap, then compare dollar amounts in code (code-only D3)

Router: a passage with overlap below 0.5 has no comparable 2024 passage and is marked 'could not verify'.

| Passages | n | Flagged (string reader) | Flagged (format-aware reader) | Could not verify |
|---|---:|---:|---:|---:|
| Edited, stable values | 11 | 11 | 11 | 0 |
| Clean, stable values (false flags) | 11 | 3 | 3 | 0 |
| Edited, values changed in 2025 | 9 | 9 | 9 | 0 |
| Clean, values changed in 2025 (real revisions) | 9 | 9 | 9 | 0 |

### Format-change attack and controls (stable values only)

| Variant | n | Edits caught, string | Edits caught, format-aware | False flags on controls, string | False flags on controls, format-aware |
|---|---:|---:|---:|---:|---:|
| fmt_k | 6 | 6 | 6 | 6 | 2 |
| fmt_nocomma | 6 | 6 | 6 | 2 | 2 |
| fmt_words | 11 | 5 | 11 | 3 | 3 |

## 3. Speed

Per passage, both checks together: median 10.22 ms, 95th percentile 11.86 ms (134 passages, one CPU core in a cloud container, 2024 index of 1042 passages built once beforehand).

### With a per-field stability list (stable values only, format-aware reader)

Fields known to change in 2025 are skipped, as Experiment 4's D3 did. Values that changed are 'could not verify'.

| Passages | n | Flagged |
|---|---:|---:|
| Edited, plain format | 11 | 11 |
| Clean (false flags) | 11 | 1 |
| Edited, fmt_k | 6 | 6 |
| Control, fmt_k (false flags) | 6 | 0 |
| Edited, fmt_nocomma | 6 | 6 |
| Control, fmt_nocomma (false flags) | 6 | 0 |
| Edited, fmt_words | 11 | 11 |
| Control, fmt_words (false flags) | 11 | 1 |
