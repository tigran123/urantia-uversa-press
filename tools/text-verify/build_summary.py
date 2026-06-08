"""
Generate artifacts/text-verify/SUMMARY.md — a book-wide overview of all
197 papers, organized for human triage. Lists CLEAN papers tersely and
groups failures by category (text diffs, structural diffs, section/title
case, italics).

Run AFTER all 197 papers have been extracted and diffed.
"""

from __future__ import annotations
import collections
import glob
import json
import os
import re
import sys
from typing import Optional


def load_summary_line(path: str) -> Optional[dict]:
    """Parse one per-paper report .md and extract counts."""
    if not os.path.exists(path):
        return None
    with open(path, encoding="utf-8") as f:
        content = f.read()
    m = re.search(r"# Paper (\d+) verification report", content)
    if not m:
        return None
    paper = int(m.group(1))
    stat = re.search(r"- Status: (\w+)", content)
    tex_v = re.search(r"TeX verses: (\d+)\s+SRT verses: (\d+)\s+common: (\d+)", content)
    sec = re.search(r"Sections: (\d+) \(TeX\) / (\d+) \(SRT\)", content)
    only = re.search(r"Only in TeX: (\d+)\s+Only in SRT: (\d+)", content)
    diffs = re.search(r"Text diffs: (\d+)\s+Italic diffs: (\d+)", content)
    return {
        "paper": paper,
        "status": stat.group(1) if stat else "?",
        "tex_v": int(tex_v.group(1)) if tex_v else 0,
        "srt_v": int(tex_v.group(2)) if tex_v else 0,
        "common": int(tex_v.group(3)) if tex_v else 0,
        "only_tex": int(only.group(1)) if only else 0,
        "only_srt": int(only.group(2)) if only else 0,
        "text_diffs": int(diffs.group(1)) if diffs else 0,
        "italic_diffs": int(diffs.group(2)) if diffs else 0,
        "tex_sec": int(sec.group(1)) if sec else 0,
        "srt_sec": int(sec.group(2)) if sec else 0,
        "mismatches_raw": [
            (m.group(1), m.group(2)) for m in re.finditer(r"- \*\*(\w+)\*\*: (.+)", content)
        ],
    }


def main() -> int:
    rows: list[dict] = []
    for n in range(197):
        r = load_summary_line(f"artifacts/text-verify/reports/p{n:03d}.md")
        if r:
            rows.append(r)

    if not rows:
        print("no reports found; run diff_verses.py first", file=sys.stderr)
        return 1

    clean = [r for r in rows if r["status"] == "CLEAN"]
    failed = [r for r in rows if r["status"] != "CLEAN"]

    # Categorize each mismatch across all FAIL reports
    bucket = collections.Counter()
    bucket_examples: dict[str, list[str]] = collections.defaultdict(list)
    for r in failed:
        for kind, detail in r["mismatches_raw"]:
            key = kind
            bucket[key] += 1
            if len(bucket_examples[key]) < 8:
                bucket_examples[key].append(f"p{r['paper']:03d}: {detail[:140]}")

    # Aggregate verse counts
    tot_tex = sum(r["tex_v"] for r in rows)
    tot_srt = sum(r["srt_v"] for r in rows)
    tot_common = sum(r["common"] for r in rows)
    tot_text = sum(r["text_diffs"] for r in rows)
    tot_italic = sum(r["italic_diffs"] for r in rows)
    tot_only_tex = sum(r["only_tex"] for r in rows)
    tot_only_srt = sum(r["only_srt"] for r in rows)

    out = []
    out.append("# Text-Integrity Verifier — Book-Wide Summary\n")
    out.append(f"Papers verified: **{len(rows)}**   CLEAN: **{len(clean)}**   FAIL: **{len(failed)}**\n\n")
    out.append("## Aggregate verse counts\n")
    out.append(f"- TeX verses: **{tot_tex}**   SRT verses: **{tot_srt}**   common: **{tot_common}**\n")
    out.append(f"- TeX-only verses: **{tot_only_tex}**   SRT-only verses: **{tot_only_srt}**\n")
    out.append(f"- Text diffs (body): **{tot_text}**   Italic-span diffs: **{tot_italic}**\n\n")

    out.append("## Mismatch categories\n")
    out.append("| Kind | Count | Sample |\n|---|---:|---|\n")
    for k, n in bucket.most_common():
        ex = bucket_examples[k][0] if bucket_examples[k] else ""
        out.append(f"| {k} | {n} | {ex} |\n")
    out.append("\n")

    out.append("## Per-paper status (all 197)\n\n")
    out.append("| Paper | TeX | SRT | Common | Only TeX | Only SRT | Text | Italic | Status |\n")
    out.append("|------:|----:|----:|-------:|---------:|---------:|-----:|-------:|:-------|\n")
    for r in rows:
        s = "CLEAN" if r["status"] == "CLEAN" else "**FAIL**"
        out.append(f"| {r['paper']:03d} | {r['tex_v']} | {r['srt_v']} | {r['common']} | "
                   f"{r['only_tex']} | {r['only_srt']} | {r['text_diffs']} | {r['italic_diffs']} | {s} |\n")
    out.append("\n")

    out.append("## All FAIL papers — detailed mismatch list\n\n")
    for r in failed:
        out.append(f"### p{r['paper']:03d}\n")
        out.append(f"`artifacts/text-verify/reports/p{r['paper']:03d}.md`\n\n")
        for kind, detail in r["mismatches_raw"][:20]:
            out.append(f"- **{kind}**: p{r['paper']:03d}: {detail}\n")
        if len(r["mismatches_raw"]) > 20:
            out.append(f"- _... ({len(r['mismatches_raw']) - 20} more — see per-paper report)_\n")
        out.append("\n")

    path = "artifacts/text-verify/SUMMARY.md"
    with open(path, "w", encoding="utf-8") as f:
        f.writelines(out)
    print(f"wrote {path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
