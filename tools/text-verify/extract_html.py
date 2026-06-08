"""
Extract verse-keyed plain text from a single SRT HTML paper.

Input  : misc/html/NN-PaperNNN.html
Output : artifacts/text-verify/html/pNNN.jsonl

Output format mirrors extract_tex.py.

Special handling:
  - <small>NNN:S.V (PAGE.FN)</small>  inside a verse <p> → drop entirely
                                       (it's the citation; (PAGE.FN) is page ref)
  - <span class="dot"></span>          → drop entirely (visual dot leader)
  - <span class="scaps">X</span>       → emit X.upper()  (SRT stores small-caps
                                         abbreviations like "a.d." in lowercase;
                                         the LaTeX edition uses uppercase "A.D.")
  - <em>...</em>                       → italic span
  - <p id="UN_0_1" ...>                → first verse of paper: leading ALL-CAPS
                                         words are SRT's small-caps opener.
                                         Normalize to title-case-then-lowercase:
                                         "THE Universal" → "The Universal";
                                         "IF THE finite" → "If the finite"
  - <p id="UN_S_VF" ...>               → strip trailing "F"; mark floater=True
                                         (this is the single occurrence in p000 12:10)
  - <h2 id="UN_S_0">C. and (C+1). T</h2> (combined section) → register BOTH
                                         sections C and C+1 with combined=True
  - Navigation chrome (<p class="ctr">, <p class="title">, <p class="paper">,
    <hr>, <a>, <link>, <meta>) → ignore
"""

from __future__ import annotations
import glob
import html
import json
import os
import re
import sys
import unicodedata
from dataclasses import dataclass, field
from html.parser import HTMLParser
from typing import Optional


PAPER_HTML_RE = re.compile(r".*?Paper(\d{3})\.html$")

# Verse id like "U1_7_9" or "U0_12_10F" (floater)
VERSE_ID_RE = re.compile(r"^U(\d+)_(\d+)_(\d+)([A-Z]*)$")
# Section heading id like "U1_7_0"
SECTION_ID_RE = re.compile(r"^U(\d+)_(\d+)_0$")
# Combined section title text like "9. and 10. James and Judas Alpheus"
COMBINED_TITLE_RE = re.compile(r"^(\d+)\.\s+and\s+(\d+)\.\s+(.*)$")
# Plain section title text like "9. James the Alpheus Twin"
# Also accepts Roman numerals (used in Foreword: "I. Deity and Divinity")
SECTION_TITLE_RE = re.compile(r"^(?:\d+|[IVXLCDM]+)\.\s+(.*)$")
# Paper title from <h1>: "Paper 1. The Universal Father" sometimes — or just title
PAPER_TITLE_RE = re.compile(r"^(?:Paper\s+\d+\.\s+)?(.*)$")
# Verse citation inside <small>: "1:7.9 (32.1)"
CITATION_RE = re.compile(r"^(\d+):(\d+)\.(\d+)\s*\(.*?\)\s*$")


@dataclass
class Verse:
    paper: int
    section: int
    verse: int
    text: str
    italics: list[tuple[int, int]] = field(default_factory=list)
    floater: bool = False


@dataclass
class Section:
    n: int
    title: str
    combined: bool = False
    combined_with: Optional[int] = None


class SRTParser(HTMLParser):
    """Stream-based parser. Maintains a state machine that, for elements we
    care about, captures text + italic boundaries; for everything else,
    flattens to text.
    """

    def __init__(self, paper_num: int):
        super().__init__(convert_charrefs=True)
        self.paper_num = paper_num
        self.paper_title: Optional[str] = None
        self.sections: list[Section] = []
        self.verses: list[Verse] = []

        # State while inside an interesting element
        self._mode: str = "idle"   # idle | paper_title | section_title | verse
        self._buf: list[str] = []
        self._italics: list[tuple[int, int]] = []
        self._italic_stack: list[int] = []   # stack of buffer-length-at-open
        # For verse mode:
        self._cur_paper: int = 0
        self._cur_section: int = 0
        self._cur_verse: int = 0
        self._cur_floater: bool = False
        # Skip-content depth (drop text between matched start/end of skip elt)
        self._skip_depth: int = 0
        # For paper_title and section_title we also need to know id
        self._title_id: Optional[str] = None
        # Track nesting depth of <p> / <h*> we're tracking so we know when to close
        self._track_depth: int = 0
        # When inside <span class="scaps">, emitted data is uppercased
        self._scaps_depth: int = 0

    # ---- helpers ----

    def _buflen(self) -> int:
        return sum(len(p) for p in self._buf)

    def _emit_text(self, s: str) -> None:
        if not s:
            return
        self._buf.append(s)

    def _open_italic(self) -> None:
        self._italic_stack.append(self._buflen())

    def _close_italic(self) -> None:
        if not self._italic_stack:
            return
        start = self._italic_stack.pop()
        end = self._buflen()
        if end > start:
            self._italics.append((start, end))

    def _reset(self) -> None:
        self._mode = "idle"
        self._buf = []
        self._italics = []
        self._italic_stack = []
        self._title_id = None
        self._track_depth = 0
        self._cur_paper = 0
        self._cur_section = 0
        self._cur_verse = 0
        self._cur_floater = False
        self._skip_depth = 0

    # ---- HTMLParser overrides ----

    def handle_starttag(self, tag: str, attrs_list: list[tuple[str, Optional[str]]]) -> None:
        attrs = {k: (v or "") for k, v in attrs_list}
        elt_id = attrs.get("id", "")
        elt_class = attrs.get("class", "")

        # Inside an active mode, handle skip elements + italics
        if self._mode in ("verse", "paper_title", "section_title"):
            if tag == "small" and self._mode == "verse" and self._buflen() == 0:
                # The leading citation small at the START of a verse → skip
                self._skip_depth = max(self._skip_depth, 0) + 1
                # Use a special sentinel: skip until matching </small>
                self._skip_tag = "small"
                self._skip_open_depth = 1
                return
            if self._skip_depth > 0:
                if tag == self._skip_tag:
                    self._skip_open_depth += 1
                return
            if tag == "span" and "dot" in elt_class.split():
                # Visual dot leader; skip its contents
                self._skip_tag = "span"
                self._skip_open_depth = 1
                self._skip_depth = 1
                return
            if tag == "span" and "scaps" in elt_class.split():
                # Small-caps wrapper; UPPERCASE its contents to match LaTeX edition
                self._scaps_depth += 1
                return
            if tag == "em":
                self._open_italic()
                return
            if tag == "sup":
                # Superscript wrapper. Two patterns:
                #  - Ordinal suffix (1st, 2nd, 606th) — LaTeX uses \\ts{th}
                #    which flattens to "th"; emit content as-is.
                #  - Math exponent (10^27) — LaTeX uses ^{27} which leaves
                #    a literal "^" in the text; we need "^" before content.
                # Decide based on the content seen in handle_data: if it's
                # all digits, prepend "^"; else nothing. Implement by
                # buffering: set a flag and inspect in handle_endtag.
                self._sup_buf_start = self._buflen()
                self._in_sup_depth = getattr(self, "_in_sup_depth", 0) + 1
                return
            if tag in ("p", "h1", "h2", "h3"):
                # Nesting another <p>/<h*> inside our tracked element shouldn't happen
                self._track_depth += 1
                return
            # Other tags inside: keep text, drop tag
            return

        # idle mode — look for interesting elements to open
        if tag == "h1":
            sm = SECTION_ID_RE.match(elt_id)
            if sm and int(sm.group(1)) == self.paper_num and int(sm.group(2)) == 0:
                # Paper title
                self._mode = "paper_title"
                self._title_id = elt_id
                self._buf = []
                self._italics = []
                self._italic_stack = []
                self._track_depth = 1
                return
        if tag == "h2":
            sm = SECTION_ID_RE.match(elt_id)
            if sm and int(sm.group(1)) == self.paper_num:
                self._mode = "section_title"
                self._title_id = elt_id
                self._cur_section = int(sm.group(2))
                self._buf = []
                self._italics = []
                self._italic_stack = []
                self._track_depth = 1
                return
        if tag == "p":
            vm = VERSE_ID_RE.match(elt_id)
            if vm and int(vm.group(1)) == self.paper_num:
                # Real verse paragraph
                self._mode = "verse"
                self._cur_paper = int(vm.group(1))
                self._cur_section = int(vm.group(2))
                self._cur_verse = int(vm.group(3))
                self._cur_floater = bool(vm.group(4))
                self._buf = []
                self._italics = []
                self._italic_stack = []
                self._track_depth = 1
                return
            # Other <p>: ignore (nav chrome)

    def handle_endtag(self, tag: str) -> None:
        if self._mode in ("verse", "paper_title", "section_title"):
            # Skip-mode bookkeeping
            if self._skip_depth > 0:
                if tag == getattr(self, "_skip_tag", None):
                    self._skip_open_depth -= 1
                    if self._skip_open_depth == 0:
                        self._skip_depth = 0
                return
            if tag == "em":
                self._close_italic()
                return
            if tag == "sup" and getattr(self, "_in_sup_depth", 0) > 0:
                self._in_sup_depth -= 1
                # Inspect the buffered content; if pure digits, insert "^" before it
                start = getattr(self, "_sup_buf_start", self._buflen())
                content = "".join(self._buf)[start:]
                if content.isdigit():
                    # rewrite buffer: insert "^" at start of sup content
                    accumulated = "".join(self._buf)
                    self._buf = [accumulated[:start] + "^" + accumulated[start:]]
                return
            if tag == "span" and self._scaps_depth > 0:
                self._scaps_depth -= 1
                return
            if tag in ("p", "h1", "h2", "h3"):
                self._track_depth -= 1
                if self._track_depth <= 0:
                    self._finalize_mode(tag)
            # other end tags: ignored

    def handle_data(self, data: str) -> None:
        if self._mode in ("verse", "paper_title", "section_title"):
            if self._skip_depth > 0:
                return
            if self._scaps_depth > 0:
                data = data.upper()
            self._emit_text(data)

    def _finalize_mode(self, tag: str) -> None:
        raw = "".join(self._buf)
        # Normalize the text the same way the TeX side does (whitespace
        # collapse + NFC). Em-dash etc. are already correct on SRT side.
        raw_nfc = unicodedata.normalize("NFC", raw)
        # Track offset map for italic span projection
        clean, italics = _collapse_ws_with_italics(raw_nfc, self._italics)

        if self._mode == "paper_title":
            m = PAPER_TITLE_RE.match(clean.strip())
            self.paper_title = (m.group(1) if m else clean).strip()
        elif self._mode == "section_title":
            sec = self._cur_section
            cm = COMBINED_TITLE_RE.match(clean.strip())
            if cm:
                n1 = int(cm.group(1))
                n2 = int(cm.group(2))
                t = cm.group(3).strip()
                # The id is keyed at n2 (e.g., U139_10_0) per p139 inspection
                if sec != n2:
                    raise RuntimeError(f"combined section id {sec} disagrees with title {clean!r}")
                self.sections.append(Section(n=n1, title=t, combined=True, combined_with=n2))
                self.sections.append(Section(n=n2, title=t, combined=True, combined_with=n1))
            else:
                tm = SECTION_TITLE_RE.match(clean.strip())
                title = tm.group(1).strip() if tm else clean.strip()
                self.sections.append(Section(n=sec, title=title))
        elif self._mode == "verse":
            # First verse of paper: lowercase the leading small-caps opener.
            # SRT stores e.g. "THE Universal" / "IF THE finite"; the LaTeX
            # edition prints normal English capitalization.
            if self._cur_section == 0 and self._cur_verse == 1:
                clean, italics = _denormalize_leading_smallcaps(clean, italics)
            self.verses.append(Verse(
                paper=self._cur_paper,
                section=self._cur_section,
                verse=self._cur_verse,
                text=clean,
                italics=italics,
                floater=self._cur_floater,
            ))

        # Reset mode (but keep paper_title/sections/verses)
        self._mode = "idle"
        self._buf = []
        self._italics = []
        self._italic_stack = []
        self._title_id = None
        self._track_depth = 0


_LEADING_CAP_WORD_RE = re.compile(r"^([A-Z]+)\b")


def _denormalize_leading_smallcaps(text: str, italics: list[tuple[int, int]]) -> tuple[str, list[tuple[int, int]]]:
    """In SRT, the first verse of each paper opens with one or more
    ALL-CAPS words rendered as small-caps in print. The LaTeX edition uses
    normal English capitalization. Convert the leading run to match:
      - First all-caps word → Title case (capitalize first letter only)
      - Each subsequent all-caps word in the leading run → lowercase entirely
      - Stop at the first word that is not all-caps (length-2-or-more)
    Italic spans are unaffected since this is a CASE-ONLY transform.
    """
    out = text
    i = 0
    word_index = 0
    while i < len(out):
        # Skip leading whitespace within the leading run (rare)
        if out[i] == " ":
            i += 1
            continue
        m = _LEADING_CAP_WORD_RE.match(out[i:])
        if not m:
            break
        word = m.group(1)
        end = i + len(word)
        if word_index == 0:
            new_word = word[0] + word[1:].lower()
        else:
            new_word = word.lower()
        out = out[:i] + new_word + out[end:]
        i = end
        word_index += 1
        # Look for separator (space) and continue scanning the next word
        if i < len(out) and out[i] == " ":
            i += 1
            continue
        # If next char is not letter/space, stop (e.g., comma or punctuation)
        break
    return out, italics


def _collapse_ws_with_italics(text: str, italics: list[tuple[int, int]]) -> tuple[str, list[tuple[int, int]]]:
    """Collapse whitespace runs to single space; strip leading/trailing.
    Re-projects italic spans through the offset map.
    """
    out: list[str] = []
    in_to_out: list[int] = []
    last_was_ws = True
    j = 0
    for ch in text:
        if ch.isspace():
            if not last_was_ws:
                in_to_out.append(len(out))
                out.append(" ")
                last_was_ws = True
            else:
                in_to_out.append(len(out))
            j += 1
        else:
            in_to_out.append(len(out))
            out.append(ch)
            last_was_ws = False
            j += 1
    in_to_out.append(len(out))
    s = "".join(out).rstrip()
    final_len = len(s)
    in_to_final = [min(o, final_len) for o in in_to_out]

    new_it: list[tuple[int, int]] = []
    for a, b in italics:
        a = max(0, min(a, len(text)))
        b = max(0, min(b, len(text)))
        na = in_to_final[a]
        nb = in_to_final[b]
        if na < nb:
            new_it.append((na, nb))
    if new_it:
        new_it.sort()
        merged = [new_it[0]]
        for a, b in new_it[1:]:
            if a <= merged[-1][1]:
                merged[-1] = (merged[-1][0], max(merged[-1][1], b))
            else:
                merged.append((a, b))
        new_it = merged
    return s, new_it


def find_html_file(paper_num: int, html_dir: str = "misc/html") -> str:
    candidates = glob.glob(f"{html_dir}/*Paper{paper_num:03d}.html")
    if not candidates:
        raise FileNotFoundError(f"no HTML file for paper {paper_num} in {html_dir}")
    if len(candidates) > 1:
        raise RuntimeError(f"multiple HTML files for paper {paper_num}: {candidates}")
    return candidates[0]


def extract_paper(html_path: str) -> tuple[dict, list[Verse]]:
    m = PAPER_HTML_RE.match(html_path)
    if not m:
        raise ValueError(f"not a paper HTML file: {html_path}")
    paper_num = int(m.group(1))

    with open(html_path, encoding="utf-8") as f:
        src = f.read()

    parser = SRTParser(paper_num)
    parser.feed(src)
    parser.close()

    # Floater resolution. The SRT uses paragraph ids with a trailing letter
    # suffix (e.g., U0_12_10F) for "floating" decorative paragraphs. Two
    # patterns are possible:
    #   (a) A floater is the ONLY paragraph for a given (section, verse) —
    #       it represents the actual verse content (e.g., p000 12:10
    #       "Acknowledgment"). Keep it.
    #   (b) A floater appears IN ADDITION to a regular paragraph for the
    #       same key — it's a visual decoration like "* * *" end-of-paper
    #       separators (e.g., p031 10:21F). Drop it.
    by_key: dict[tuple[int, int], list[int]] = {}
    for i, v in enumerate(parser.verses):
        by_key.setdefault((v.section, v.verse), []).append(i)
    drop_indices = set()
    for key, idxs in by_key.items():
        if len(idxs) > 1:
            # Drop the floater(s); keep the regular paragraph(s).
            keep_some = [i for i in idxs if not parser.verses[i].floater]
            if keep_some:
                for i in idxs:
                    if parser.verses[i].floater:
                        drop_indices.add(i)
            # else: all floaters — this would be unusual; keep all and let
            # the diff flag the duplicate
    verses = [v for i, v in enumerate(parser.verses) if i not in drop_indices]

    header = {
        "_kind": "paper",
        "paper": paper_num,
        "title": parser.paper_title,
        "subtitle": None,
        "author": None,
        "sections": [
            {"n": s.n, "title": s.title, "combined": s.combined, "combined_with": s.combined_with}
            for s in parser.sections
        ],
    }
    return header, verses


def write_jsonl(header: dict, verses: list[Verse], out_path: str) -> None:
    os.makedirs(os.path.dirname(out_path), exist_ok=True)
    with open(out_path, "w", encoding="utf-8") as f:
        f.write(json.dumps(header, ensure_ascii=False) + "\n")
        for v in verses:
            rec = {
                "paper": v.paper,
                "section": v.section,
                "verse": v.verse,
                "text": v.text,
                "italics": [[s, e] for s, e in v.italics],
                "floater": v.floater,
            }
            f.write(json.dumps(rec, ensure_ascii=False) + "\n")


def main() -> int:
    if len(sys.argv) < 2:
        print("usage: extract_html.py <paper_num> [paper_num ...]")
        return 2
    for arg in sys.argv[1:]:
        paper_num = int(arg)
        html_path = find_html_file(paper_num)
        header, verses = extract_paper(html_path)
        out_path = f"artifacts/text-verify/html/p{header['paper']:03d}.jsonl"
        write_jsonl(header, verses, out_path)
        print(f"{html_path}: paper={header['paper']} title={header['title']!r} "
              f"sections={len(header['sections'])} verses={len(verses)} -> {out_path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
