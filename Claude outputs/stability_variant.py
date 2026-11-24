"""Add-on: code-only D3 with a per-field stability list (as Exp 4's D3 used).
Amounts that belong to fields known to change in 2025 are ignored. Usage: python -I stability_variant.py <frozen dir> <out dir>"""
import json, sys
from pathlib import Path
D, OUT = Path(sys.argv[1]), Path(sys.argv[2])
gt = json.load(open(D / "ground_truth.json"))
changing = {str(float(g["correct"].replace("$", "").replace(",", ""))) for g in gt if g["value_changed_between_editions"]}
rows = [json.loads(l) for l in open(OUT / "overlap_baseline_rows.jsonl")]
def flag(r):
    return bool(set(r.get("new_format_aware", [])) - changing)
L = ["\n### With a per-field stability list (stable values only, format-aware reader)\n",
     "Fields known to change in 2025 are skipped, as Experiment 4's D3 did. Values that changed are 'could not verify'.\n",
     "| Passages | n | Flagged |", "|---|---:|---:|"]
def add(name, rs): L.append(f"| {name} | {len(rs)} | {sum(map(flag, rs))} |")
st = lambda **kw: [r for r in rows if r["stable"] and all(r[k] == v for k, v in kw.items())]
add("Edited, plain format", st(kind="edited", variant="plain"))
add("Clean (false flags)", st(kind="clean"))
for f in ("fmt_k", "fmt_nocomma", "fmt_words"):
    add(f"Edited, {f}", st(kind="edited", variant=f))
    add(f"Control, {f} (false flags)", st(kind="control", variant=f))
txt = "\n".join(L) + "\n"
with open(OUT / "overlap_baseline_report.md", "a") as fh: fh.write(txt)
print(txt)
