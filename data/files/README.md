# Source excerpts

These are the pages of the original documents that the passages in [`../docs.json`](../docs.json) were copied from. They're excerpts, not full documents, which keeps the repo small: the full IRS and NIST PDFs alone are about 20 MB. Every passage segment in `docs.json` was checked against the text of these excerpts, word for word (case-sensitive, ignoring whitespace and punctuation).

Page numbers below are the page's position in the original file (what a PDF viewer shows as "page N of M"), not the number printed on the page. Each excerpt keeps the pages in their original order. Where a PDF has a cover or title page, it's included as the first page, because that's what shows the edition.

## Files

| File | Source | Original pages kept | How it was made |
|---|---|---|---|
| `irs-2024_i1040gi--2024_pages.pdf` | [2024 Instructions for Form 1040](https://www.irs.gov/pub/irs-prior/i1040gi--2024.pdf) | 1 (cover), 6, 34, 93, 94 | pages copied from the IRS PDF |
| `irs-2025_i1040gi_pages.pdf` | [2025 Instructions for Form 1040](https://www.irs.gov/pub/irs-pdf/i1040gi.pdf) | 1 (cover), 6, 35, 98, 99 | pages copied from the IRS PDF |
| `nist-r4_NIST.SP.800-53r4_pages.pdf` | [NIST SP 800-53 Rev. 4](https://nvlpubs.nist.gov/nistpubs/SpecialPublications/NIST.SP.800-53r4.pdf) (April 2013, updates as of January 22, 2015) | 1 (cover), 33, 165, 327, 438–440 | pages copied from the NIST PDF |
| `nist-r5_NIST.SP.800-53r5_pages.pdf` | [NIST SP 800-53 Rev. 5](https://nvlpubs.nist.gov/nistpubs/SpecialPublications/NIST.SP.800-53r5.pdf) (September 2020, updates as of 12-10-2020) | 1 (cover), 16, 35, 46, 307, 360, 361, 390, 391, 468, 469, 481–484 | pages copied from the NIST PDF |
| `nist-r5_release-5.2.0-summary-of-changes.pdf` | [Summary of Changes: NIST SP 800-53 Release 5.2.0](https://csrc.nist.gov/files/projects/Risk-Management/800-53%20Comment%20Site/SP800-53-r5.2.0-changes.pdf) (August 27, 2025) | 1–2 (all) | copied from NIST. Not a passage source: it backs the registry's 5.2.0 entry and the gold answers of `nist-12`–`nist-14` |
| `gsa-fy24_per-diem_pages.pdf` | GSA [FY 2024 Per Diem Highlights](https://www.gsa.gov/system/files/FY2024PerDiemRatesHighlights_09272023.docx) and [M&IE Breakdown, FY 2022 – FY 2024](https://www.gsa.gov/system/files/FY%202022%20MIE%20Breakdown_0.docx) | page 1 of each | GSA publishes these as Word files; converted to PDF with LibreOffice |
| `gsa-fy25_per-diem_pages.pdf` | GSA [FY 2025 per diem highlights](https://www.gsa.gov/system/files/FY2025PerDiemRatesHighlights.docx) and [M&IE breakdowns, FY 2025](https://www.gsa.gov/system/files/FY%202025%20MIE%20Breakdown.docx) | page 1 of each | as above |
| `pandas-1.5_docs_pages.pdf` | pandas 1.5.3 docs: [DataFrame.append](https://pandas.pydata.org/pandas-docs/version/1.5/reference/api/pandas.DataFrame.append.html), [Series.iteritems](https://pandas.pydata.org/pandas-docs/version/1.5/reference/api/pandas.Series.iteritems.html), [What's new in 1.0.0](https://pandas.pydata.org/pandas-docs/version/1.5/whatsnew/v1.0.0.html), [DataFrame.merge](https://pandas.pydata.org/pandas-docs/version/1.5/reference/api/pandas.DataFrame.merge.html) | append p. 1; iteritems p. 1; what's new pp. 1, 10; merge p. 1 | web pages printed to PDF with Chromium |
| `pandas-2.0_docs_pages.pdf` | pandas 2.0.3 docs: [What's new in 2.0.0](https://pandas.pydata.org/pandas-docs/version/2.0/whatsnew/v2.0.0.html), [DataFrame.merge](https://pandas.pydata.org/pandas-docs/version/2.0/reference/api/pandas.DataFrame.merge.html) | what's new pp. 1, 19, 23; merge p. 1 | as above |
| `numpy-1.26_docs_pages.pdf` | NumPy v1.26 Manual: [Constants](https://numpy.org/doc/1.26/reference/constants.html), [Scalars](https://numpy.org/doc/1.26/reference/arrays.scalars.html) | constants pp. 1–2; scalars pp. 1, 5 | as above |
| `numpy-2.0_docs_pages.pdf` | NumPy v2.0 Manual: [2.0.0 Release Notes](https://numpy.org/doc/2.0/release/2.0.0-notes.html), [Constants](https://numpy.org/doc/2.0/reference/constants.html) | release notes pp. 1, 3–5; constants pp. 1–2 | as above |

The web pages were printed on October 28, 2026; each page's footer shows its URL and the print date. Page numbers for them refer to that printout. Link annotations were dropped from all excerpts, because they pointed at pages that aren't included.

## Where each passage is

| Passage | Original page(s) |
|---|---|
| `irs-2024-p1` | What's New, p. 6 |
| `irs-2024-p2` | Standard Deduction Worksheet for Dependents and the age/blindness chart heading, p. 34 |
| `irs-2024-p3` | Schedule 1, line 21, p. 93; its worksheet, p. 94 |
| `irs-2025-p1` | What's New, p. 6 |
| `irs-2025-p2` | Standard Deduction Worksheet for Dependents and the age/blindness chart heading, p. 35 |
| `irs-2025-p3` | Schedule 1, line 21, p. 98; its worksheet, p. 99 |
| `nist-r4-p1` | Section 2.2 and Table 1, p. 33 |
| `nist-r4-p2` | SA-12, p. 327 |
| `nist-r4-p3` | Appendix J title, p. 438; introduction and Table J-1, pp. 439–440 |
| `nist-r4-p4` | AC-2, p. 165 |
| `nist-r5-p1` | Section 2.2 and Table 1, p. 35 |
| `nist-r5-p2` | SA-12 (withdrawn), p. 307; Section 3.20, SR-1 and SR-2, pp. 390–391 |
| `nist-r5-p3` | Foreword, p. 16 |
| `nist-r5-p4` | AC-2, p. 46 |
| `nist-r5-p5` | Table C-7, pp. 468–469 |
| `nist-r5-p6` | Table C-17, pp. 481–484 |
| `nist-r5-p7` | SI-2 control enhancements, pp. 360–361 |
| `nist-r5-p8` | Table C-17, SA-15 rows, p. 483 |
| `gsa-fy24-p1` | FY 2024 highlights, p. 1 |
| `gsa-fy24-p2` | M&IE Breakdown FY 2022 – FY 2024, p. 1 |
| `gsa-fy25-p1` | FY 2025 highlights, p. 1 |
| `gsa-fy25-p2` | M&IE breakdowns FY 2025, p. 1 |
| `pandas-1.5-p1` | DataFrame.append, p. 1 |
| `pandas-1.5-p2` | Series.iteritems, p. 1 |
| `pandas-1.5-p3` | What's new in 1.0.0, p. 10 |
| `pandas-1.5-p4` | DataFrame.merge, p. 1 |
| `pandas-2.0-p1` | What's new in 2.0.0, p. 19 |
| `pandas-2.0-p2` | What's new in 2.0.0, p. 23 |
| `pandas-2.0-p3` | DataFrame.merge, p. 1 |
| `numpy-1.26-p1` | Constants, p. 2 |
| `numpy-1.26-p2` | Scalars, p. 5 |
| `numpy-2.0-p1` | 2.0.0 Release Notes, pp. 3–5 |
| `numpy-2.0-p2` | Constants, p. 2 |

The edited documents (`irs-undated`, `irs-c7`, `nist-undated`, `nist-c7`, `pandas-undated`) have no files of their own. They're built from the passages above, and each one's `source_url` in `docs.json` says what was changed.
