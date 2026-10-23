---
name: version-check
description: Procedure for checking whether the documents behind an answer are the latest version before answering.
---

# Version check

Use this whenever an answer depends on a document that could have been revised, superseded or amended.

1. List each distinct source document behind the passages you plan to rely on: its title or filename, plus any date, revision, tax year, fiscal year or software version shown in the text.
2. Call `check_latest_version` once per document, passing its title or filename. Include the version string if you have one.
3. Compare what the registry returns with what the passage says:
   - **Superseded or withdrawn:** if a newer version is among the passages, answer from it. If it isn't, say the source is outdated and name the newer version.
   - **Changed in place:** if the registry lists changes, errata or releases dated after the text you have, say the value may have been amended.
   - **No date or version in the text:** say the source can't be verified as current. Don't present the figure as definitely current.
   - **Filename and text disagree on the date or version:** point out the inconsistency.
   - **Registry unavailable or erroring:** answer from the passages, but say freshness couldn't be verified.
4. If the user asks about a specific older version (e.g. "for tax year 2024" or "under Rev 4"), answer from that version. Don't flag it or "correct" it to the newer one.
5. If the value is the same in every version, just answer it. No warning is needed.
