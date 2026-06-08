"""
Macro-coverage guard. Tokenizes every body paper, asserts that every
\\macro encountered is present in macros.TABLE. Writes a coverage report
to artifacts/text-verify/macro-coverage.txt and exits non-zero on any
unknown macro.
"""

from __future__ import annotations
import glob
import os
import re
import sys
from collections import Counter, defaultdict

sys.path.insert(0, os.path.dirname(__file__))
from latex_tokenizer import tokenize
import macros


PAPER_FILE_RE = re.compile(r".*/p\d{3}\.tex$")


def find_body_papers(tex_dir: str = "tex") -> list[str]:
    return sorted(p for p in glob.glob(f"{tex_dir}/p*.tex") if PAPER_FILE_RE.fullmatch(p))


def run() -> int:
    papers = find_body_papers()
    if not papers:
        print("ERROR: no body papers found under tex/p*.tex", file=sys.stderr)
        return 2

    counts: Counter[str] = Counter()
    locations: dict[str, list[tuple[str, int, int]]] = defaultdict(list)
    for path in papers:
        with open(path, encoding="utf-8") as f:
            src = f.read()
        for tok in tokenize(src):
            if tok.kind != "MACRO":
                continue
            counts[tok.value] += 1
            if len(locations[tok.value]) < 3:
                locations[tok.value].append((path, tok.line, tok.col))

    unknown = sorted([name for name in counts if not macros.is_known(name)])
    out_path = "artifacts/text-verify/macro-coverage.txt"
    os.makedirs(os.path.dirname(out_path), exist_ok=True)
    with open(out_path, "w", encoding="utf-8") as f:
        f.write(f"# macro coverage: {len(papers)} papers, {len(counts)} distinct macros, {sum(counts.values())} occurrences\n")
        f.write(f"# unknown macros (not in macros.TABLE): {len(unknown)}\n\n")
        for name, n in counts.most_common():
            status = "KNOWN  " if macros.is_known(name) else "UNKNOWN"
            f.write(f"{status}  {n:>7}  \\{name}\n")
            for path, line, col in locations[name][:3]:
                f.write(f"            at {path}:{line}:{col}\n")
    print(f"wrote {out_path}")

    if unknown:
        print(f"FAIL: {len(unknown)} unknown macros — add handlers to macros.TABLE", file=sys.stderr)
        for name in unknown:
            ex = locations[name][0] if locations[name] else ("?", 0, 0)
            print(f"  \\{name}  (e.g. {ex[0]}:{ex[1]}:{ex[2]})", file=sys.stderr)
        return 1

    print(f"PASS: all {len(counts)} distinct macros across {len(papers)} papers are in macros.TABLE")
    return 0


if __name__ == "__main__":
    sys.exit(run())
