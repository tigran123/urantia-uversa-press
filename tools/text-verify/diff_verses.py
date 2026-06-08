"""
Diff verse-keyed text between the TeX-side and SRT-side JSONL extracts
for a single paper.

Input  : artifacts/text-verify/tex/pNNN.jsonl
         artifacts/text-verify/html/pNNN.jsonl
Output : artifacts/text-verify/reports/pNNN.md
Stdout : one-line summary

Exit 0 iff CLEAN (no unaccepted mismatches).

Allow-list lives in tools/text-verify/accepted-deviations.yaml; supports:
  - per-verse text override (we expect this exact mismatch)
  - per-verse italics override
  - per-verse skip entirely
"""

from __future__ import annotations
import difflib
import json
import os
import re
import sys
from dataclasses import dataclass, field
from typing import Optional

sys.path.insert(0, os.path.dirname(__file__))
import normalize as norm


@dataclass
class VerseRecord:
    paper: int
    section: int
    verse: int
    text: str
    italics: list[tuple[int, int]]
    floater: bool = False
    macros_seen: list[str] = field(default_factory=list)


@dataclass
class Mismatch:
    kind: str           # STRUCT | TEXT | ITALIC | PAPER_TITLE | SECTION_TITLE
    detail: str         # human-readable description
    key: Optional[tuple[int, int]] = None  # (section, verse) when applicable


def load_jsonl(path: str) -> tuple[dict, list[VerseRecord]]:
    with open(path, encoding="utf-8") as f:
        lines = f.readlines()
    header = json.loads(lines[0])
    verses: list[VerseRecord] = []
    for line in lines[1:]:
        r = json.loads(line)
        verses.append(VerseRecord(
            paper=r["paper"],
            section=r["section"],
            verse=r["verse"],
            text=r["text"],
            italics=[tuple(x) for x in r.get("italics", [])],
            floater=r.get("floater", False),
            macros_seen=r.get("macros_seen", []),
        ))
    return header, verses


def load_deviations(path: str = "tools/text-verify/accepted-deviations.yaml") -> dict:
    """Very small YAML-subset reader (we only use simple key/value lists).

    Two top-level key forms:
      PAPER:SECTION:VERSE:        single verse
      PAPER:SECTION:V1-V2:        inclusive range, V1 <= V2 (fans out to N entries)
    """
    if not os.path.exists(path):
        return {}
    # Minimal parser for our schema; avoids adding PyYAML as a dep.
    out: dict = {}
    cur_keys: list[tuple[int, int, int]] = []
    cur_block: dict = {}

    def flush():
        for k in cur_keys:
            out[k] = dict(cur_block)

    with open(path, encoding="utf-8") as f:
        for raw in f:
            line = raw.rstrip("\n")
            stripped = line.strip()
            if not stripped or stripped.startswith("#"):
                continue
            # top-level range key like "144:5:11-108:"
            m = re.match(r"^(\d+):(\d+):(\d+)-(\d+):\s*$", line)
            if m:
                flush()
                p, s, v1, v2 = int(m.group(1)), int(m.group(2)), int(m.group(3)), int(m.group(4))
                if v2 < v1:
                    raise ValueError(f"invalid range {p}:{s}:{v1}-{v2}: V2 < V1")
                cur_keys = [(p, s, v) for v in range(v1, v2 + 1)]
                cur_block = {}
                continue
            # top-level single-verse key like "1:0:1:"
            m = re.match(r"^(\d+):(\d+):(\d+):\s*$", line)
            if m:
                flush()
                cur_keys = [(int(m.group(1)), int(m.group(2)), int(m.group(3)))]
                cur_block = {}
                continue
            m = re.match(r"^\s+(skip|reason|expect_tex|expect_srt|ignore_italics):\s*(.*)$", line)
            if m:
                k = m.group(1)
                v = m.group(2)
                # strip surrounding quotes if any
                if (v.startswith('"') and v.endswith('"')) or (v.startswith("'") and v.endswith("'")):
                    v = v[1:-1]
                if k in ("skip", "ignore_italics"):
                    cur_block[k] = v.lower() in ("true", "yes", "1")
                else:
                    cur_block[k] = v
        flush()
    return out


def remap_combined_sections(tex_header: dict, tex_verses: list[VerseRecord]) -> dict[int, int]:
    """For TeX sections flagged combined, build a section→canonical_section
    map. The canonical key is the higher number (matching SRT convention,
    as confirmed for p139: SRT uses U139_10_*).
    """
    remap: dict[int, int] = {}
    for s in tex_header.get("sections", []):
        if s.get("combined") and s.get("combined_with"):
            n = s["n"]
            cw = s["combined_with"]
            canon = max(n, cw)
            remap[n] = canon
    return remap


def diff_paper(tex_jsonl: str, html_jsonl: str, report_path: str,
               deviations: Optional[dict] = None) -> tuple[bool, str]:
    """Diff one paper's extracts. Returns (clean, summary_line)."""
    deviations = deviations or {}
    tex_h, tex_v = load_jsonl(tex_jsonl)
    html_h, html_v = load_jsonl(html_jsonl)
    paper = tex_h["paper"]
    assert paper == html_h["paper"]

    mismatches: list[Mismatch] = []
    sus_log: list[str] = []

    # Paper title
    if (tex_h.get("title") or "") != (html_h.get("title") or ""):
        mismatches.append(Mismatch("PAPER_TITLE",
            f"TEX={tex_h.get('title')!r}  SRT={html_h.get('title')!r}"))

    # Section titles — compare by raw section number. Both extractors
    # register BOTH numbers for a combined-section pair; the remap
    # applies to VERSE keys only (TeX-side verses keyed under the lower
    # combined number get remapped to the canonical higher number).
    sec_remap = remap_combined_sections(tex_h, tex_v)
    tex_secs = {s["n"]: s for s in tex_h.get("sections", [])}
    html_secs = {s["n"]: s for s in html_h.get("sections", [])}
    for n in sorted(set(tex_secs) | set(html_secs)):
        ts = tex_secs.get(n)
        hs = html_secs.get(n)
        if ts is None:
            mismatches.append(Mismatch("SECTION_TITLE",
                f"section {n} present in SRT ({hs['title']!r}) but missing on TeX side"))
            continue
        if hs is None:
            mismatches.append(Mismatch("SECTION_TITLE",
                f"section {n} present in TeX ({ts['title']!r}) but missing on SRT side"))
            continue
        if norm.normalize(ts["title"]) != norm.normalize(hs["title"]):
            mismatches.append(Mismatch("SECTION_TITLE",
                f"section {n} title mismatch: TEX={ts['title']!r} SRT={hs['title']!r}"))

    # Verses
    tex_keyed: dict[tuple[int, int], VerseRecord] = {}
    for v in tex_v:
        canon_sec = sec_remap.get(v.section, v.section)
        key = (canon_sec, v.verse)
        if key in tex_keyed:
            mismatches.append(Mismatch("STRUCT",
                f"duplicate TeX verse {key}: previously seen, this collision suggests bad remap or source duplication", key=key))
        tex_keyed[key] = v

    html_keyed: dict[tuple[int, int], VerseRecord] = {}
    for v in html_v:
        key = (v.section, v.verse)
        if key in html_keyed:
            mismatches.append(Mismatch("STRUCT",
                f"duplicate SRT verse {key}", key=key))
        html_keyed[key] = v

    only_tex = sorted(set(tex_keyed) - set(html_keyed))
    only_html = sorted(set(html_keyed) - set(tex_keyed))
    common = sorted(set(tex_keyed) & set(html_keyed))

    for key in only_tex:
        if deviations.get((paper, key[0], key[1]), {}).get("skip"):
            continue
        mismatches.append(Mismatch("STRUCT", f"verse {paper}:{key[0]}:{key[1]} present in TeX but missing in SRT", key=key))
    for key in only_html:
        if deviations.get((paper, key[0], key[1]), {}).get("skip"):
            continue
        mismatches.append(Mismatch("STRUCT", f"verse {paper}:{key[0]}:{key[1]} present in SRT but missing in TeX", key=key))

    text_diffs: list[tuple[tuple[int, int], str, str]] = []
    italic_diffs: list[tuple[tuple[int, int], list, list]] = []

    for key in common:
        dev = deviations.get((paper, key[0], key[1]), {})
        if dev.get("skip"):
            continue
        tv = tex_keyed[key]
        hv = html_keyed[key]

        # Final normalization pass
        t_text, t_it, t_sus = norm.normalize_verse(tv.text, [list(x) for x in tv.italics])
        h_text, h_it, h_sus = norm.normalize_verse(hv.text, [list(x) for x in hv.italics])
        for name, n in t_sus.items():
            sus_log.append(f"  {paper}:{key[0]}:{key[1]} TeX side has {n}×{name}")
        for name, n in h_sus.items():
            sus_log.append(f"  {paper}:{key[0]}:{key[1]} SRT side has {n}×{name}")

        if t_text != h_text:
            text_diffs.append((key, t_text, h_text))
            mismatches.append(Mismatch("TEXT", f"verse {paper}:{key[0]}:{key[1]} body differs", key=key))
        elif (not dev.get("ignore_italics")) and t_it != h_it:
            italic_diffs.append((key, t_it, h_it))
            mismatches.append(Mismatch("ITALIC",
                f"verse {paper}:{key[0]}:{key[1]} italic spans differ: TEX={t_it} SRT={h_it}", key=key))

    # Write report
    os.makedirs(os.path.dirname(report_path), exist_ok=True)
    clean = len(mismatches) == 0
    with open(report_path, "w", encoding="utf-8") as f:
        f.write(f"# Paper {paper} verification report\n\n")
        f.write(f"- TeX verses: {len(tex_v)}   SRT verses: {len(html_v)}   common: {len(common)}\n")
        f.write(f"- Only in TeX: {len(only_tex)}   Only in SRT: {len(only_html)}\n")
        f.write(f"- Text diffs: {len(text_diffs)}   Italic diffs: {len(italic_diffs)}\n")
        f.write(f"- Status: {'CLEAN' if clean else 'FAIL'}\n\n")

        f.write("## Title\n")
        f.write(f"- TeX title: {tex_h.get('title')!r}\n")
        f.write(f"- SRT title: {html_h.get('title')!r}\n")
        f.write(f"- Sections: {len(tex_h.get('sections', []))} (TeX) / {len(html_h.get('sections', []))} (SRT)\n\n")

        if mismatches:
            f.write("## Mismatches\n\n")
            for m in mismatches:
                f.write(f"- **{m.kind}**: {m.detail}\n")
            f.write("\n")
        if text_diffs:
            f.write("## Text diffs (per verse)\n\n")
            for key, t_text, h_text in text_diffs[:50]:
                f.write(f"### {paper}:{key[0]}:{key[1]}\n\n")
                _write_diff(f, t_text, h_text)
                f.write("\n")
            if len(text_diffs) > 50:
                f.write(f"... ({len(text_diffs) - 50} more text diffs not shown)\n\n")
        if italic_diffs:
            f.write("## Italic diffs (per verse)\n\n")
            for key, t_it, h_it in italic_diffs[:50]:
                t = tex_keyed[key].text
                f.write(f"### {paper}:{key[0]}:{key[1]}\n")
                f.write(f"- TeX italics: {t_it}\n")
                f.write(f"- SRT italics: {h_it}\n")
                # Show first 200 chars with markers
                f.write(f"- text: {t[:200]!r}\n\n")
        if sus_log:
            f.write("## Suspicious glyphs (normalized to ASCII but noted)\n\n")
            for line in sus_log[:50]:
                f.write(line + "\n")
            if len(sus_log) > 50:
                f.write(f"... ({len(sus_log) - 50} more)\n")

    status = "CLEAN" if clean else f"FAIL ({len(mismatches)} mismatches)"
    summary = (f"p{paper:03d}: tex={len(tex_v)} srt={len(html_v)} common={len(common)} "
               f"only_tex={len(only_tex)} only_srt={len(only_html)} "
               f"text_diff={len(text_diffs)} italic_diff={len(italic_diffs)} {status}")
    return clean, summary


def _write_diff(f, a: str, b: str) -> None:
    """Show character-level diff via difflib opcodes with ±20 char context."""
    sm = difflib.SequenceMatcher(None, a, b)
    for tag, i1, i2, j1, j2 in sm.get_opcodes():
        if tag == "equal":
            continue
        ctx_pre = a[max(0, i1 - 20):i1]
        ctx_post = a[i2:i2 + 20]
        a_text = a[i1:i2]
        b_text = b[j1:j2]
        f.write(f"- `...{ctx_pre}` **TEX→**`{a_text}` **SRT→**`{b_text}` `{ctx_post}...`\n")


def main() -> int:
    if len(sys.argv) < 2:
        print("usage: diff_verses.py p001 [p002 ...]")
        return 2
    deviations = load_deviations()
    fail = 0
    for arg in sys.argv[1:]:
        # accept "1" or "p001"
        m = re.match(r"p?(\d+)$", arg)
        if not m:
            print(f"bad arg: {arg}", file=sys.stderr)
            fail += 1
            continue
        n = int(m.group(1))
        tex = f"artifacts/text-verify/tex/p{n:03d}.jsonl"
        html = f"artifacts/text-verify/html/p{n:03d}.jsonl"
        if not os.path.exists(tex):
            print(f"missing {tex} — run extract_tex first", file=sys.stderr)
            fail += 1
            continue
        if not os.path.exists(html):
            print(f"missing {html} — run extract_html first", file=sys.stderr)
            fail += 1
            continue
        report = f"artifacts/text-verify/reports/p{n:03d}.md"
        clean, summary = diff_paper(tex, html, report, deviations=deviations)
        print(summary)
        if not clean:
            fail += 1
    return 0 if fail == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
