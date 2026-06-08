"""
Verify the verifier itself. Six independent checks; ALL must pass before
any CLEAN report from diff_verses.py is trusted.

  1. Macro-coverage guard (delegated to macro_coverage.py)
  2. Triple verse-count cross-check (extractor vs grep vs DOM)
  3. Round-trip determinism (re-extract; sha256 byte-identical)
  4. Mutation testing (5 in-memory mutants must each be flagged)
  5. Combined-section regression (p139)
  6. Spot-check generator (--spot-check N prints N random side-by-side)

Usage:
  python3 verify_verifier.py --macros           # check 1 only
  python3 verify_verifier.py --triple-count     # check 2 only
  python3 verify_verifier.py --determinism      # check 3 only
  python3 verify_verifier.py --mutation         # check 4 only
  python3 verify_verifier.py --p139-regression  # check 5 only
  python3 verify_verifier.py --spot-check N     # check 6: print N samples
  python3 verify_verifier.py --all              # all of 1..5 (not spot-check)
"""

from __future__ import annotations
import glob
import hashlib
import io
import json
import os
import random
import re
import subprocess
import sys
import tempfile
from typing import Optional

sys.path.insert(0, os.path.dirname(__file__))
from latex_tokenizer import tokenize
from extract_tex import extract_paper as ex_tex, write_jsonl as wj_tex
from extract_html import find_html_file, extract_paper as ex_html, write_jsonl as wj_html


PAPER_TEX_RE = re.compile(r"tex/p(\d{3})\.tex$")


def paper_files() -> list[tuple[int, str, str]]:
    """Return list of (paper_num, tex_path, html_path) for all 197 papers."""
    out = []
    for tex_path in sorted(glob.glob("tex/p[0-9][0-9][0-9].tex")):
        m = PAPER_TEX_RE.search(tex_path)
        if not m:
            continue
        n = int(m.group(1))
        html_path = find_html_file(n)
        out.append((n, tex_path, html_path))
    return out


# ---- 1. Macro coverage ----

def check_macros() -> bool:
    print("--- check 1: macro coverage ---")
    rc = subprocess.call([sys.executable, os.path.join(os.path.dirname(__file__), "macro_coverage.py")])
    return rc == 0


# ---- 2. Triple verse-count cross-check ----

def _grep_vs_count(tex_path: str) -> int:
    """Count verse markers in TeX source by independent regex.
    Matches \\vs pNNN C:V and \\vsmark{C}{V} and \\printvssuper{N}+\\par-pairs.
    For simplicity we count \\vs and \\vsmark; printvssuper opens N verses
    that each end at a \\par, and counting those requires structure walk.
    """
    with open(tex_path, encoding="utf-8") as f:
        s = f.read()
    return len(re.findall(r"\\vs\s+p\d+\s+\d+:\d+|\\vsmark\{\d+\}\{\d+\}", s))


def _dom_verse_count(html_path: str) -> int:
    """Count <p id="UN_S_V"> paragraphs (not section heads, not floaters
    that duplicate a non-floater).
    """
    with open(html_path, encoding="utf-8") as f:
        s = f.read()
    ids = re.findall(r'<p id="(U\d+_\d+_\d+[A-Z]*)"', s)
    keys = set()
    for i in ids:
        m = re.match(r"U(\d+)_(\d+)_(\d+)", i)
        if m:
            keys.add((int(m.group(1)), int(m.group(2)), int(m.group(3))))
    return len(keys)


def check_triple_count() -> bool:
    """Verify per-side that the extractor counts match an independent
    method on the same side. Cross-side mismatches (TeX vs HTML) are
    expected in papers with SRT-only `* * *` separators (p031, p056,
    p120, p134, p144) and are NOT a check failure.
    """
    print("--- check 2: triple verse-count cross-check ---")
    bad = 0
    for n, tex, html in paper_files():
        header_t, verses_t = ex_tex(tex)
        a = len(verses_t)
        b = _grep_vs_count(tex)
        # B (grep) undercounts in poetic sections (printvssuper-opened
        # verses that increment by \par); require A >= B.
        if a < b:
            bad += 1
            print(f"  p{n:03d}: TeX extractor={a} < grep={b}  (extractor under-counts)")
        # HTML side: extractor count should EXACTLY match unique DOM
        # paragraph IDs (after floater deduplication).
        c = _dom_verse_count(html)
        header_h, verses_h = ex_html(html)
        e = len(verses_h)
        if e != c:
            bad += 1
            print(f"  p{n:03d}: HTML extractor={e} != DOM count={c}  (extractor mismatch)")
    if bad == 0:
        print(f"  PASS: extractor counts on each side agree with independent method")
    return bad == 0


# ---- 3. Round-trip determinism ----

def _hash_dir(dirpath: str) -> str:
    h = hashlib.sha256()
    for f in sorted(os.listdir(dirpath)):
        if not f.endswith(".jsonl"):
            continue
        with open(os.path.join(dirpath, f), "rb") as fp:
            h.update(f.encode())
            h.update(fp.read())
    return h.hexdigest()


def check_determinism() -> bool:
    print("--- check 3: round-trip determinism ---")
    # Re-extract a small sample (full re-extract is slow). Use 10 papers.
    sample = [0, 1, 30, 48, 100, 139, 144, 150, 180, 196]
    with tempfile.TemporaryDirectory() as a_dir, tempfile.TemporaryDirectory() as b_dir:
        for outdir in (a_dir, b_dir):
            os.makedirs(os.path.join(outdir, "tex"))
            os.makedirs(os.path.join(outdir, "html"))
            for n in sample:
                h, v = ex_tex(f"tex/p{n:03d}.tex")
                wj_tex(h, v, os.path.join(outdir, "tex", f"p{n:03d}.jsonl"))
                hh, vv = ex_html(find_html_file(n))
                wj_html(hh, vv, os.path.join(outdir, "html", f"p{n:03d}.jsonl"))
        ha = _hash_dir(os.path.join(a_dir, "tex")) + _hash_dir(os.path.join(a_dir, "html"))
        hb = _hash_dir(os.path.join(b_dir, "tex")) + _hash_dir(os.path.join(b_dir, "html"))
    ok = ha == hb
    print(f"  {'PASS' if ok else 'FAIL'}: re-extract is{'' if ok else ' NOT'} byte-identical across runs")
    return ok


# ---- 4. Mutation testing ----

def check_mutations() -> bool:
    """Mutate p042 in-memory five different ways; each mutant must be flagged."""
    print("--- check 4: mutation testing on p042 ---")
    tex_src = open("tex/p042.tex", encoding="utf-8").read()
    html_src = open(find_html_file(42), encoding="utf-8").read()

    # Establish baseline: extract from in-memory sources, compare. Should be CLEAN.
    def extract_pair(tex_text: str, html_text: str) -> tuple[list, list]:
        with tempfile.NamedTemporaryFile("w", suffix="_p042.tex", delete=False) as f:
            f.write(tex_text)
            tex_path = f.name
        os.rename(tex_path, "/tmp/_mut_p042.tex")
        h_tex, v_tex = ex_tex("/tmp/_mut_p042.tex")
        # html_text is same as on disk for the unmutated case; for mutants we patch in-memory
        # but extract_html.find_html_file expects a file; we use a temp file
        with tempfile.NamedTemporaryFile("w", suffix="Paper042.html", delete=False) as f:
            f.write(html_text)
            html_path = f.name
        h_html, v_html = ex_html(html_path)
        os.unlink(html_path)
        os.unlink("/tmp/_mut_p042.tex")
        return v_tex, v_html

    base_tex, base_html = extract_pair(tex_src, html_src)
    # Build keyed dicts
    def keyed(vs):
        return {(v.section, v.verse): v.text for v in vs}
    base_k_tex = keyed(base_tex)
    base_k_html = keyed(base_html)
    base_diff = sum(1 for k in set(base_k_tex) & set(base_k_html) if base_k_tex[k] != base_k_html[k])
    baseline_passes = base_diff
    print(f"  baseline (unmutated): {base_diff} text diffs")

    mutants_caught = 0
    mutants_missed = 0

    # Mutant 1: drop first word from verse 1:1 in TeX
    m1 = re.sub(
        r"(\\vs p042 1:1)\s+\w+",
        r"\1 XXX",
        tex_src, count=1,
    )
    v1_tex, v1_html = extract_pair(m1, html_src)
    if keyed(v1_tex).get((1, 1)) != keyed(v1_html).get((1, 1)):
        mutants_caught += 1
        print("  M1 (drop first word) — CAUGHT")
    else:
        mutants_missed += 1
        print("  M1 — MISSED")

    # Mutant 2: replace a , with . in verse 1:1
    m2 = tex_src.replace("\\vs p042 1:1", "\\vs p042 1:1", 1)  # no-op placeholder; do real swap:
    m2 = re.sub(r"(\\vs p042 1:1[^\n]{40,80}),", r"\1.", tex_src, count=1)
    v2_tex, v2_html = extract_pair(m2, html_src)
    if keyed(v2_tex).get((1, 1)) != keyed(v2_html).get((1, 1)):
        mutants_caught += 1
        print("  M2 (, → .) — CAUGHT")
    else:
        mutants_missed += 1
        print("  M2 — MISSED")

    # Mutant 3: drop an entire sentence (last sentence of 1:1)
    m3 = re.sub(
        r"(\\vs p042 1:1[^\n]+?\.)\s+[A-Z][^.]+\.",
        r"\1",
        tex_src, count=1,
    )
    v3_tex, v3_html = extract_pair(m3, html_src)
    if keyed(v3_tex).get((1, 1)) != keyed(v3_html).get((1, 1)):
        mutants_caught += 1
        print("  M3 (drop sentence) — CAUGHT")
    else:
        mutants_missed += 1
        print("  M3 — MISSED")

    # Mutant 4: change italics — wrap a previously-non-italic word in \bibemph{...}
    m4 = re.sub(
        r"(\\vs p042 1:1 \w+ \w+ )(\w+)( )",
        r"\1\\bibemph{\2}\3",
        tex_src, count=1,
    )
    v4_tex, v4_html = extract_pair(m4, html_src)
    t4 = v4_tex
    h4 = v4_html
    # Italic span comparison
    tex_italics = next((v.italics for v in t4 if (v.section, v.verse) == (1, 1)), [])
    html_italics = next((v.italics for v in h4 if (v.section, v.verse) == (1, 1)), [])
    if tex_italics != html_italics:
        mutants_caught += 1
        print("  M4 (add italics) — CAUGHT")
    else:
        mutants_missed += 1
        print("  M4 — MISSED")

    # Mutant 5: change italics on HTML side — drop a <em> tag if any
    if "<em>" in html_src:
        m5h = html_src.replace("<em>", "", 1).replace("</em>", "", 1)
        v5_tex, v5_html = extract_pair(tex_src, m5h)
        tex_italics = sum(len(v.italics) for v in v5_tex)
        html_italics = sum(len(v.italics) for v in v5_html)
        if tex_italics != html_italics:
            mutants_caught += 1
            print("  M5 (drop SRT <em>) — CAUGHT")
        else:
            mutants_missed += 1
            print("  M5 — MISSED")
    else:
        print("  M5 — skipped (no <em> in p042 HTML)")

    ok = mutants_missed == 0
    print(f"  {'PASS' if ok else 'FAIL'}: {mutants_caught}/{mutants_caught + mutants_missed} mutants caught")
    return ok


# ---- 5. Combined-section regression ----

def check_p139_regression() -> bool:
    """p139 has \\usectiontwo{9 and 10}{James and Judas Alpheus}. The TeX
    side keys these verses under section 9 (LaTeX's \\usectiontwo does NOT
    advance the section counter past the first number). The SRT side keys
    them under section 10. The diff_verses.py remap MUST map TeX section 9
    to canonical SRT section 10 for these verses to align."""
    print("--- check 5: combined-section regression on p139 ---")
    header, verses = ex_tex("tex/p139.tex")
    sec9 = next((s for s in header["sections"] if s["n"] == 9), None)
    sec10 = next((s for s in header["sections"] if s["n"] == 10), None)
    if not sec9 or not sec10:
        print("  FAIL: sections 9 and 10 not both registered")
        return False
    if not (sec9["combined"] and sec10["combined"]):
        print(f"  FAIL: sections 9/10 not flagged combined: 9={sec9}, 10={sec10}")
        return False
    section_keys_used = sorted({v.section for v in verses})
    if 9 not in section_keys_used:
        print(f"  FAIL: TeX has no verses keyed under section 9 (expected): {section_keys_used}")
        return False
    # Now verify the diff_verses remap maps section 9 → canonical 10
    sys.path.insert(0, os.path.dirname(__file__))
    from diff_verses import remap_combined_sections
    remap = remap_combined_sections(header, verses)
    if remap.get(9) != 10:
        print(f"  FAIL: remap_combined_sections did not map 9→10: {remap}")
        return False
    print(f"  PASS: TeX uses section 9; SRT uses section 10; remap maps 9→10 correctly")
    return True


# ---- 6. Spot-check generator ----

def spot_check(n: int) -> int:
    print(f"--- spot-check: {n} random verses side-by-side ---\n")
    random.seed(int(os.environ.get("VV_SEED", "0")))
    all_verses: list[tuple[int, int, int]] = []
    for path in sorted(glob.glob("artifacts/text-verify/tex/p*.jsonl")):
        m = re.search(r"p(\d+)\.jsonl", path)
        paper = int(m.group(1))
        with open(path, encoding="utf-8") as f:
            next(f)
            for line in f:
                r = json.loads(line)
                all_verses.append((paper, r["section"], r["verse"]))
    sample = random.sample(all_verses, min(n, len(all_verses)))
    sample.sort()
    for paper, sec, ver in sample:
        tex_text = _read_verse("tex", paper, sec, ver)
        srt_text = _read_verse("html", paper, sec, ver)
        same = "✓" if tex_text == srt_text else "✗"
        print(f"### {paper:03d}:{sec}:{ver}  {same}")
        print(f"TEX: {tex_text[:300]}")
        print(f"SRT: {srt_text[:300]}")
        print()
    return 0


def _read_verse(side: str, paper: int, sec: int, ver: int) -> str:
    path = f"artifacts/text-verify/{side}/p{paper:03d}.jsonl"
    with open(path, encoding="utf-8") as f:
        next(f)
        for line in f:
            r = json.loads(line)
            if r["section"] == sec and r["verse"] == ver:
                return r["text"]
    return "(missing)"


def main() -> int:
    args = sys.argv[1:]
    if not args:
        print(__doc__)
        return 2

    if args[0] == "--spot-check":
        n = int(args[1]) if len(args) > 1 else 50
        return spot_check(n)

    checks = []
    if args[0] == "--all":
        checks = [check_macros, check_p139_regression, check_determinism, check_triple_count, check_mutations]
    elif args[0] == "--macros":
        checks = [check_macros]
    elif args[0] == "--triple-count":
        checks = [check_triple_count]
    elif args[0] == "--determinism":
        checks = [check_determinism]
    elif args[0] == "--mutation":
        checks = [check_mutations]
    elif args[0] == "--p139-regression":
        checks = [check_p139_regression]
    else:
        print(__doc__)
        return 2

    fails = 0
    for c in checks:
        if not c():
            fails += 1
        print()
    print(f"{'ALL PASS' if fails == 0 else f'{fails} CHECK(S) FAILED'}")
    return 0 if fails == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
