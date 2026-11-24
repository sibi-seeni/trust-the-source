"""Semantic-overlap baseline (Chris Alizar's suggestion), run offline on the frozen Exp 3 data.

Passage-level test. For each of the 20 questions:
  clean  = the original 2025 answer passage
  edited = the same passage with the true value replaced (attacked copy 1) -- what an in-place edit leaves behind
Reference = the 2024 edition only (no trusted 2025 copy is assumed).

Check S  : pure overlap. Char 3-5 TF-IDF cosine to the closest 2024 passage. Flag if below a threshold.
Check SV : overlap as a router, then plain-code dollar comparison against the matched 2024 window
           (best match +/- 1 chunk, since chunk boundaries shift between editions).
           Two number readers: 'string' (as in the Nov 8 detector) and 'format-aware'.
No model calls. Usage: python -I overlap_baseline.py <frozen_exp3 dir> <out dir>
"""
import json, re, sys, time
from difflib import SequenceMatcher
from pathlib import Path

import numpy as np
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.metrics import roc_auc_score

D, OUT = Path(sys.argv[1]), Path(sys.argv[2])
OUT.mkdir(parents=True, exist_ok=True)

gt = {g["id"]: g for g in json.load(open(D / "ground_truth.json"))}
clean = [json.loads(l) for l in open(D / "clean_passages.jsonl")]
byid = {p["id"]: p for p in clean}
attacked = {}
for l in open(D / "attacked_passages.jsonl"):
    a = json.loads(l)
    if a["copy_number"] == 1:
        attacked[a["question_id"]] = a["text"]

ref = [p for p in clean if str(p["year"]) == "2024"]
ref_idx = {p["id"]: i for i, p in enumerate(ref)}

# ---------- number formats ----------
ONES = "zero one two three four five six seven eight nine ten eleven twelve thirteen fourteen fifteen sixteen seventeen eighteen nineteen".split()
TENS = "_ _ twenty thirty forty fifty sixty seventy eighty ninety".split()

def words_under_1000(n):
    out = []
    if n >= 100:
        out += [ONES[n // 100], "hundred"]; n %= 100
    if n >= 20:
        out.append(TENS[n // 10] + ("-" + ONES[n % 10] if n % 10 else "")); n = 0
    if n:
        out.append(ONES[n])
    return out

def int_words(n):
    if n == 0:
        return ["zero"]
    out = []
    for scale, name in ((10**6, "million"), (1000, "thousand")):
        if n >= scale:
            out += words_under_1000(n // scale) + [name]; n %= scale
    return out + (words_under_1000(n) if n else [])

def money_value(s):
    return float(s.replace("$", "").replace(",", ""))

def to_words(s):
    v = money_value(s); d = int(v); c = round((v - d) * 100)
    w = " ".join(int_words(d)) + (" dollar" if d == 1 else " dollars")
    return w + (f" and {' '.join(int_words(c))} cents" if c else "")

def to_k(s):
    v = money_value(s)
    if v < 1000 or v != int(v):
        return None
    return "$" + (f"{v/1000:.3f}".rstrip("0").rstrip(".")) + "K"

def to_nocomma(s):
    v = money_value(s)
    if v < 1000:
        return None
    return "$" + (str(int(v)) if v == int(v) else f"{v:.2f}")

FORMATS = {"fmt_k": to_k, "fmt_nocomma": to_nocomma, "fmt_words": to_words}

# ---------- number readers ----------
MONEY_STR = re.compile(r"\$\s*\d[\d,]*(?:\.\d{2})?")              # Nov 8 detector's reader

def amounts_string(t):
    return {x.replace(" ", "").replace(",", "") for x in MONEY_STR.findall(t)}

MONEY_FA = re.compile(r"\$\s*(\d[\d,]*(?:\.\d+)?)\s*([KkMm](?![a-z]))?")
WORD_NUMS = {w: i for i, w in enumerate(ONES)} | {w: 10 * i for i, w in enumerate(TENS) if w != "_"}
WORD_RE = re.compile(r"\b((?:(?:" + "|".join(sorted(WORD_NUMS, key=len, reverse=True)) +
                     r"|hundred|thousand|million|and|-)\s*)+)dollars?(?:\s+and\s+((?:(?:" +
                     "|".join(sorted(WORD_NUMS, key=len, reverse=True)) + r"|-)\s*)+)cents?)?", re.I)

def parse_words(phrase):
    total = cur = 0
    for tok in re.split(r"[\s-]+", phrase.lower()):
        if tok in WORD_NUMS: cur += WORD_NUMS[tok]
        elif tok == "hundred": cur *= 100
        elif tok in ("thousand", "million"):
            total += cur * (1000 if tok == "thousand" else 10**6); cur = 0
    return total + cur

def amounts_fa(t):
    out = set()
    for num, suf in MONEY_FA.findall(t):
        v = float(num.replace(",", ""))
        if suf: v *= 1000 if suf.lower() == "k" else 10**6
        out.add(round(v, 2))
    for m in WORD_RE.finditer(t):
        v = parse_words(m.group(1))
        if m.group(2): v += parse_words(m.group(2)) / 100
        if v: out.add(round(v, 2))
    return out

READERS = {"string": amounts_string, "format_aware": amounts_fa}

# ---------- overlap ----------
vec = TfidfVectorizer(analyzer="char", ngram_range=(3, 5), max_features=60000)
R = vec.fit_transform([p["text"] for p in ref])

def overlap(text):
    s = (R @ vec.transform([text]).T).toarray().ravel()
    i = int(np.argmax(s))
    return float(s[i]), i

def window(i):
    return " ".join(ref[j]["text"] for j in range(max(0, i - 1), min(len(ref), i + 2)))

MATCH_T = 0.50   # router threshold: below this there is no comparable 2024 passage -> "could not verify"

def check(text):
    t0 = time.perf_counter()
    sim, i = overlap(text)
    res = {"overlap": round(sim, 4), "match": ref[i]["id"]}
    if sim < MATCH_T:
        for r in READERS: res[f"sv_{r}"] = "could_not_verify"
    else:
        w = window(i)
        for r, fn in READERS.items():
            new = fn(text) - fn(w)
            res[f"sv_{r}"] = "flag" if new else "pass"
            res[f"new_{r}"] = sorted(map(str, new))
    res["ms"] = (time.perf_counter() - t0) * 1000
    return res

# ---------- items ----------
items = []
for q, g in gt.items():
    src = byid[g["source_passage_id"]]["text"]
    ed = attacked[q]
    assert g["correct"] in src and g["planted"] in ed, q
    base = dict(q=q, stable=not g["value_changed_between_editions"])
    items.append(base | dict(kind="clean", variant="plain", text=src))
    items.append(base | dict(kind="edited", variant="plain", text=ed))
    for f, fn in FORMATS.items():
        p, c = fn(g["planted"]), fn(g["correct"])
        if p and c:
            items.append(base | dict(kind="edited", variant=f, text=ed.replace(g["planted"], p, 1)))
            items.append(base | dict(kind="control", variant=f, text=src.replace(g["correct"], c, 1)))

for _ in range(2):  # warm-up so timing excludes first-call overhead
    check(items[0]["text"])
rows = [it | check(it["text"]) for it in items]
for r in rows: r.pop("text")
(OUT / "overlap_baseline_rows.jsonl").write_text("\n".join(json.dumps(r) for r in rows))

# ---------- report ----------
def sel(**kw):
    return [r for r in rows if all(r[k] == v for k, v in kw.items())]

L = []
P = L.append
cl, ed = sel(kind="clean"), sel(kind="edited", variant="plain")
P("## 1. Overlap alone (Chris's check)\n")
P("| Passages | n | Overlap with closest 2024 passage, median (min-max) |")
P("|---|---:|---|")
for name, rs in [("Clean 2025, stable values", [r for r in cl if r["stable"]]),
                 ("Clean 2025, values changed in 2025", [r for r in cl if not r["stable"]]),
                 ("Edited 2025, stable values", [r for r in ed if r["stable"]]),
                 ("Edited 2025, values changed in 2025", [r for r in ed if not r["stable"]])]:
    o = [r["overlap"] for r in rs]
    P(f"| {name} | {len(o)} | {np.median(o):.3f} ({min(o):.3f}-{max(o):.3f}) |")
y = [0] * len(cl) + [1] * len(ed)
s = [-r["overlap"] for r in cl] + [-r["overlap"] for r in ed]
P(f"\nAUROC, edited vs clean using overlap alone (0.5 = coin flip): **{roc_auc_score(y, s):.2f}**")
pairs = {r["q"]: r["overlap"] for r in cl}
d = [pairs[r["q"]] - r["overlap"] for r in ed]
P(f"\nOverlap drop caused by the edit, same passage: median {np.median(d):.4f}, max {max(d):.4f}")
best = None
for t in sorted({r["overlap"] for r in cl + ed}):
    det = sum(r["overlap"] < t for r in ed); ff = sum(r["overlap"] < t for r in cl)
    if ff <= 2 and (best is None or det > best[1]): best = (t, det, ff)
P(f"\nBest threshold with at most 2/20 false flags on clean passages: catches {best[1]}/20 edits ({best[2]}/20 false flags).\n")

P("## 2. Overlap, then compare dollar amounts in code (code-only D3)\n")
P(f"Router: a passage with overlap below {MATCH_T} has no comparable 2024 passage and is marked 'could not verify'.\n")
P("| Passages | n | Flagged (string reader) | Flagged (format-aware reader) | Could not verify |")
P("|---|---:|---:|---:|---:|")
def line(name, rs):
    a = sum(r["sv_string"] == "flag" for r in rs); b = sum(r["sv_format_aware"] == "flag" for r in rs)
    c = sum(r["sv_string"] == "could_not_verify" for r in rs)
    P(f"| {name} | {len(rs)} | {a} | {b} | {c} |")
line("Edited, stable values", [r for r in ed if r["stable"]])
line("Clean, stable values (false flags)", [r for r in cl if r["stable"]])
line("Edited, values changed in 2025", [r for r in ed if not r["stable"]])
line("Clean, values changed in 2025 (real revisions)", [r for r in cl if not r["stable"]])

P("\n### Format-change attack and controls (stable values only)\n")
P("| Variant | n | Edits caught, string | Edits caught, format-aware | False flags on controls, string | False flags on controls, format-aware |")
P("|---|---:|---:|---:|---:|---:|")
for f in FORMATS:
    e = [r for r in sel(kind="edited", variant=f) if r["stable"]]
    c = [r for r in sel(kind="control", variant=f) if r["stable"]]
    P(f"| {f} | {len(e)} | {sum(r['sv_string']=='flag' for r in e)} | {sum(r['sv_format_aware']=='flag' for r in e)} | "
      f"{sum(r['sv_string']=='flag' for r in c)} | {sum(r['sv_format_aware']=='flag' for r in c)} |")

ms = [r["ms"] for r in rows]
P(f"\n## 3. Speed\n\nPer passage, both checks together: median {np.median(ms):.2f} ms, 95th percentile {np.percentile(ms,95):.2f} ms "
  f"({len(ms)} passages, one CPU core in a cloud container, 2024 index of {len(ref)} passages built once beforehand).")
(OUT / "overlap_baseline_report.md").write_text("\n".join(L) + "\n")
print("\n".join(L))
