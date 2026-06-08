"""
Extract verse-keyed plain text from a single LaTeX paper.

Input  : tex/pNNN.tex
Output : artifacts/text-verify/tex/pNNN.jsonl

Each JSONL output has:
  - one header line  : {"_kind":"paper", "paper":N, "title":..., "author":..., "sections":[...]}
  - one line per verse : {"paper":N, "section":S, "verse":V, "text":..., "italics":[[s,e],...], "macros_seen":[...]}

The extractor maintains a state machine that recognizes truly-structural
macros (verse and section/paper boundaries) and delegates inline body
expansion to a recursive expander that consults macros.TABLE.

Special handling:
  - \\makeatletter ... \\makeatother  → skip everything (TeX bookkeeping)
  - \\printvssuper{N}                  → enter poetic mode; current_verse = N
  - \\vsmark{S}{N}                     → flush pending text as verse (S, N);
                                         current_verse = N+1
  - \\par in poetic mode               → flush pending text as verse
                                         (current_section, current_verse);
                                         current_verse += 1
  - \\begin/\\end{quoting|ubquote|multicols}
                                        → transparent; ignored
  - {\\itshape WORD}                   → italic span for `WORD`
"""

from __future__ import annotations
import json
import os
import re
import sys
from dataclasses import dataclass, field
from typing import Optional

sys.path.insert(0, os.path.dirname(__file__))
from latex_tokenizer import tokenize, TokenStream, Token
import macros


PAPER_FILE_RE = re.compile(r".*?p(\d{3})\.tex$")

# A macro is "truly structural" (causes verse/section/paper transition)
TRULY_STRUCTURAL = {
    "vs", "vsmark", "printvssuper",
    "upaper", "upapertitle", "author",
    "usection", "usectiontwo",
    # \par is structural in poetic mode only; the top-level loop decides
    # what to do with it based on poetic_active. In normal mode it's a no-op.
    "par",
}


@dataclass
class Verse:
    paper: int
    section: int
    verse: int
    text: str
    italics: list[tuple[int, int]] = field(default_factory=list)
    macros_seen: list[str] = field(default_factory=list)
    combined: bool = False   # set later if this verse's section is part of a usectiontwo


@dataclass
class Section:
    n: int
    title: str
    combined: bool = False         # part of \usectiontwo
    combined_with: Optional[int] = None  # the other section number


# ---- The inline body expander ----

class Expander:
    """Recursively expand a token stream into (text, italic_spans, macros_seen).

    The expander stops when it hits a TRULY structural macro (peek-only;
    the caller consumes it), end of stream, or an unmatched CLOSE_BRACE
    (signaling the end of the group this expander is inside).
    """

    def __init__(self, stream: TokenStream, italic_active: bool = False, in_makeatletter: bool = False):
        self.stream = stream
        self.text_parts: list[str] = []
        self.italics: list[tuple[int, int]] = []
        self.macros_seen: list[str] = []
        self.italic_active = italic_active
        self.in_makeatletter = in_makeatletter

    def _len(self) -> int:
        return sum(len(p) for p in self.text_parts)

    def _emit(self, s: str, italic: bool = False) -> None:
        if not s:
            return
        start = self._len()
        self.text_parts.append(s)
        end = self._len()
        if italic or self.italic_active:
            self.italics.append((start, end))

    def _read_unbraced_length(self) -> Optional[str]:
        """Consume an unbraced length expression like '-1pt', '4pt', '0.5em'
        from the next TEXT token. Returns the consumed slice (which may
        include a trailing '\\relax' macro that some sources tack on).
        """
        nxt = self.stream.peek()
        if nxt is None or nxt.kind != "TEXT":
            return None
        m = re.match(r"^([+-]?\d+(?:\.\d+)?(?:pt|em|ex|mm|cm|in|bp|pc|sp|mu))", nxt.value)
        if not m:
            return None
        length = m.group(1)
        # Consume the matched portion; if the TEXT token has more after, leave the rest.
        rest = nxt.value[len(length):]
        if rest:
            nxt.value = rest
        else:
            self.stream.next()
        return length

    def _merge_italics(self) -> list[tuple[int, int]]:
        if not self.italics:
            return []
        out: list[tuple[int, int]] = []
        for s, e in sorted(self.italics):
            if out and s <= out[-1][1]:
                out[-1] = (out[-1][0], max(out[-1][1], e))
            else:
                out.append((s, e))
        return out

    def text(self) -> str:
        return "".join(self.text_parts)

    def run(self) -> None:
        """Drain the stream until structural macro / CLOSE_BRACE / end."""
        while True:
            tok = self.stream.peek()
            if tok is None:
                return

            if tok.kind == "CLOSE_BRACE":
                # Caller's group is closing; return without consuming.
                return

            if tok.kind == "NEWLINE":
                self.stream.next()
                self._emit(" ")
                continue

            if tok.kind == "COMMENT":
                self.stream.next()
                continue

            if tok.kind == "TEXT":
                self.stream.next()
                self._emit(tok.value)
                continue

            if tok.kind == "OPEN_BRACE":
                # Recurse into a fresh group. Italic state is inherited; the
                # recursion can flip it (e.g., for `{\itshape WORD}`).
                self.stream.next()
                inner = Expander(self.stream, italic_active=self.italic_active, in_makeatletter=self.in_makeatletter)
                inner.run()
                # Consume the matching CLOSE_BRACE (may be absent at EOF)
                cb = self.stream.peek()
                if cb is not None and cb.kind == "CLOSE_BRACE":
                    self.stream.next()
                # Merge inner output (with offset)
                offset = self._len()
                self.text_parts.append(inner.text())
                for s, e in inner.italics:
                    self.italics.append((s + offset, e + offset))
                self.macros_seen.extend(inner.macros_seen)
                continue

            if tok.kind == "OPEN_BRACKET" or tok.kind == "CLOSE_BRACKET":
                # Should only appear bound to an optional arg; if seen
                # standalone in body text, emit verbatim.
                self.stream.next()
                self._emit(tok.value)
                continue

            assert tok.kind == "MACRO", f"unexpected token {tok!r}"

            name = tok.value

            # Handle \makeatletter ... \makeatother as a skip region.
            if name == "makeatletter":
                self.stream.next()
                # Skip tokens until \makeatother (or end)
                while True:
                    t = self.stream.next()
                    if t is None:
                        return
                    if t.kind == "MACRO" and t.value == "makeatother":
                        break
                continue
            if name == "makeatother":
                # Shouldn't reach here in normal flow
                self.stream.next()
                continue

            # Truly structural — stop without consuming.
            if name in TRULY_STRUCTURAL:
                return

            # Otherwise, consult the table.
            spec = macros.get(name)
            if spec is None:
                # Should be caught by macro_coverage.py, but defensive:
                raise RuntimeError(f"unknown macro \\{name} at {tok.line}:{tok.col}")

            self.stream.next()
            self.macros_seen.append(name)

            # Starred-form: consume a leading '*' from the next TEXT.
            if name in macros.STARRED_FORMS:
                nxt = self.stream.peek()
                if nxt is not None and nxt.kind == "TEXT" and nxt.value.startswith("*"):
                    # Replace the TEXT token with its tail (or remove if empty)
                    if nxt.value == "*":
                        self.stream.next()
                    else:
                        nxt.value = nxt.value[1:]

            # \itshape opens an italic span for the rest of this group.
            if name == "itshape":
                self.italic_active = True
                continue

            # \begin{env} / \end{env} — strip wrapper, content stays in stream
            if name == "begin":
                env = self.stream.read_brace_arg_raw()
                # Strip optional bracket arg if any (e.g. [vskip=...])
                self.stream.read_optional_arg()
                if env not in macros.KNOWN_ENVIRONMENTS:
                    raise RuntimeError(f"unknown environment {env!r} at {tok.line}:{tok.col}")
                # multicols takes a mandatory column-count arg: \begin{multicols}{N}
                if env == "multicols":
                    self.stream.read_brace_arg_raw()
                continue
            if name == "end":
                env = self.stream.read_brace_arg_raw()
                if env not in macros.KNOWN_ENVIRONMENTS:
                    raise RuntimeError(f"unknown environment {env!r} at {tok.line}:{tok.col}")
                continue

            # Consume optional + brace args per spec.
            for _ in range(spec.opt):
                self.stream.read_optional_arg()
            arg_strings: list[str] = []
            for _ in range(spec.args):
                a = self.stream.read_brace_arg_raw()
                if a is None and name in macros.UNBRACED_LENGTH_MACROS:
                    # LaTeX accepts an unbraced length expression for
                    # spacing macros (\kern-1pt, \vspace*2em, \hspace0.5cm).
                    # Consume the next TEXT token as the length argument
                    # if it looks like a length.
                    a = self._read_unbraced_length()
                arg_strings.append(a if a is not None else "")

            # Apply action.
            if spec.action == macros.STRIP:
                pass
            elif spec.action == macros.EMIT_TEXT:
                self._emit(spec.text)
            elif spec.action in (macros.EMIT_ARG, macros.EMIT_ARG_ITALIC):
                # Recursively expand the chosen arg
                arg_src = arg_strings[spec.which - 1]
                inner_tokens = tokenize(arg_src)
                inner_stream = TokenStream(inner_tokens)
                italic_for_arg = (spec.action == macros.EMIT_ARG_ITALIC)
                inner = Expander(
                    inner_stream,
                    italic_active=self.italic_active or italic_for_arg,
                    in_makeatletter=self.in_makeatletter,
                )
                inner.run()
                offset = self._len()
                self.text_parts.append(inner.text())
                for s, e in inner.italics:
                    self.italics.append((s + offset, e + offset))
                self.macros_seen.extend(inner.macros_seen)
                # \ublistelem{1.} should emit "1." followed by no trailing
                # space (the following \bibnobreakspace provides the space).
            else:
                raise RuntimeError(f"unhandled action {spec.action} for \\{name}")


def expand_string(src: str, italic_active: bool = False) -> tuple[str, list[tuple[int, int]], list[str]]:
    """Expand a raw LaTeX string and return (text, italic_spans, macros_seen)."""
    stream = TokenStream(tokenize(src))
    exp = Expander(stream, italic_active=italic_active)
    exp.run()
    return exp.text(), exp._merge_italics(), exp.macros_seen


# ---- The paper-level state machine ----

def _post_process_body(text: str) -> str:
    """Body text post-processing: --- → em-dash, -- → en-dash, ~ → space, $ stripped, ws collapse."""
    # Per the design: extractor converts LaTeX-style dashes here.
    text = text.replace("---", "—").replace("--", "–")
    # LaTeX ~ is a non-breaking space; the SRT side uses a regular space.
    text = text.replace("~", " ")
    # Math-mode delimiters: drop entirely. Math content (between $...$) is
    # rendered as text by macro expansion; the $ markers should not survive
    # in the body output.
    text = text.replace("$", "")
    # Collapse whitespace runs to single space
    text = re.sub(r"\s+", " ", text).strip()
    return text


def _post_process_italics(text: str, italics: list[tuple[int, int]]) -> tuple[str, list[tuple[int, int]]]:
    """Re-compute italic spans through dash substitution and ws collapse.

    We re-walk the original text and the substituted text in lockstep,
    tracking which output indices each input index maps to. Italic spans
    are then projected through the map.
    """
    # Step 1: dash substitution char-by-char with offset map
    out_chars: list[str] = []
    in_to_out: list[int] = []  # in_to_out[i] = output index of input char i
    i = 0
    while i < len(text):
        if text[i:i + 3] == "---":
            in_to_out.extend([len(out_chars)] * 3)
            out_chars.append("—")
            i += 3
        elif text[i:i + 2] == "--":
            in_to_out.extend([len(out_chars)] * 2)
            out_chars.append("–")
            i += 2
        elif text[i] == "~":
            in_to_out.append(len(out_chars))
            out_chars.append(" ")
            i += 1
        elif text[i] == "$":
            # math-mode delimiter; drop without producing any char
            in_to_out.append(len(out_chars))
            i += 1
        else:
            in_to_out.append(len(out_chars))
            out_chars.append(text[i])
            i += 1
    in_to_out.append(len(out_chars))  # sentinel for end

    s1 = "".join(out_chars)

    # Step 2: whitespace collapse
    out2: list[str] = []
    map2: list[int] = []
    j = 0
    last_was_ws = True  # strip leading ws
    while j < len(s1):
        ch = s1[j]
        if ch.isspace():
            if not last_was_ws:
                map2.append(len(out2))
                out2.append(" ")
                last_was_ws = True
            else:
                map2.append(len(out2))  # collapsed to prior space (or stripped)
            j += 1
        else:
            map2.append(len(out2))
            out2.append(ch)
            last_was_ws = False
            j += 1
    map2.append(len(out2))

    # strip trailing space
    final = "".join(out2).rstrip()
    s1_to_final: list[int] = [min(o, len(final)) for o in map2]

    # Project italic spans
    new_italics: list[tuple[int, int]] = []
    for s, e in italics:
        s = max(0, min(s, len(text)))
        e = max(0, min(e, len(text)))
        ns = s1_to_final[min(in_to_out[s], len(s1))]
        ne = s1_to_final[min(in_to_out[e], len(s1))]
        if ns < ne:
            new_italics.append((ns, ne))
    # Merge overlapping
    if new_italics:
        new_italics.sort()
        merged = [new_italics[0]]
        for s, e in new_italics[1:]:
            if s <= merged[-1][1]:
                merged[-1] = (merged[-1][0], max(merged[-1][1], e))
            else:
                merged.append((s, e))
        new_italics = merged
    return final, new_italics


def extract_paper(tex_path: str) -> tuple[dict, list[Verse]]:
    m = PAPER_FILE_RE.match(tex_path)
    if not m:
        raise ValueError(f"not a paper file: {tex_path}")
    paper_num = int(m.group(1))

    with open(tex_path, encoding="utf-8") as f:
        src = f.read()
    src = src  # NFC done at normalization step

    stream = TokenStream(tokenize(src))

    sections: list[Section] = []
    secnum = 0
    paper_title: Optional[str] = None
    paper_subtitle: Optional[str] = None
    author: Optional[str] = None
    verses: list[Verse] = []

    # Poetic-mode state
    poetic_active = False
    cur_verse_section: Optional[int] = None
    cur_verse_number: Optional[int] = None
    cur_text_parts: list[str] = []
    cur_italics: list[tuple[int, int]] = []
    cur_macros: list[str] = []

    def flush_verse() -> None:
        """If a verse is currently being accumulated, emit it."""
        nonlocal cur_verse_section, cur_verse_number, cur_text_parts, cur_italics, cur_macros
        if cur_verse_section is None or cur_verse_number is None:
            cur_text_parts = []
            cur_italics = []
            cur_macros = []
            return
        raw = "".join(cur_text_parts)
        text, italics = _post_process_italics(raw, cur_italics)
        if text or italics:
            verses.append(Verse(
                paper=paper_num,
                section=cur_verse_section,
                verse=cur_verse_number,
                text=text,
                italics=italics,
                macros_seen=list(cur_macros),
            ))
        cur_text_parts = []
        cur_italics = []
        cur_macros = []

    def append_body(raw_text: str, raw_italics: list[tuple[int, int]], raw_macros: list[str]) -> None:
        nonlocal cur_text_parts, cur_italics, cur_macros
        offset = sum(len(p) for p in cur_text_parts)
        cur_text_parts.append(raw_text)
        for s, e in raw_italics:
            cur_italics.append((s + offset, e + offset))
        cur_macros.extend(raw_macros)

    def run_inline_to_boundary() -> None:
        """Run the Expander against the live stream until it hits a structural macro
        or end-of-stream; append all produced body text to the current verse."""
        exp = Expander(stream, italic_active=False)
        exp.run()
        append_body(exp.text(), exp._merge_italics(), exp.macros_seen)

    while True:
        tok = stream.peek()
        if tok is None:
            break

        if tok.kind == "MACRO" and tok.value in TRULY_STRUCTURAL:
            name = tok.value
            stream.next()

            if name == "upaper":
                # \upaper{N}{Title}
                a1 = stream.read_brace_arg_raw() or ""
                a2 = stream.read_brace_arg_raw() or ""
                assert int(a1.strip()) == paper_num, f"upaper {a1!r} != filename {paper_num}"
                t_text, _, _ = expand_string(a2)
                paper_title = _post_process_body(t_text)
                continue

            if name == "upapertitle":
                # Possible subtitle, not in current inventory but be safe
                a1 = stream.read_brace_arg_raw() or ""
                t_text, _, _ = expand_string(a1)
                paper_subtitle = _post_process_body(t_text)
                continue

            if name == "author":
                a1 = stream.read_brace_arg_raw() or ""
                t_text, _, _ = expand_string(a1)
                author = _post_process_body(t_text)
                continue

            if name == "usection":
                flush_verse()
                poetic_active = False
                cur_verse_section = None
                cur_verse_number = None
                secnum += 1
                title_raw = stream.read_brace_arg_raw() or ""
                t_text, _, _ = expand_string(title_raw)
                sections.append(Section(n=secnum, title=_post_process_body(t_text)))
                continue

            if name == "usectiontwo":
                flush_verse()
                poetic_active = False
                cur_verse_section = None
                cur_verse_number = None
                label_raw = stream.read_brace_arg_raw() or ""
                title_raw = stream.read_brace_arg_raw() or ""
                t_text, _, _ = expand_string(title_raw)
                secnum += 2
                n1 = secnum - 1
                n2 = secnum
                sections.append(Section(n=n1, title=_post_process_body(t_text), combined=True, combined_with=n2))
                sections.append(Section(n=n2, title=_post_process_body(t_text), combined=True, combined_with=n1))
                continue

            if name == "vs":
                # \vs pNNN C:V text...
                flush_verse()
                poetic_active = False
                # Next non-empty token should be a TEXT starting with "pNNN C:V "
                t = stream.next()
                # The tokenizer swallowed the trailing space after \vs already,
                # so `t` is the first TEXT token.
                assert t is not None and t.kind == "TEXT", repr(t)
                m_vs = re.match(r"\s*p(\d+)\s+(\d+):(\d+)(?:\s+(.*))?$", t.value, re.DOTALL)
                assert m_vs, f"bad \\vs header: {t.value!r} at {t.line}:{t.col}"
                p_n = int(m_vs.group(1))
                cur_verse_section = int(m_vs.group(2))
                cur_verse_number = int(m_vs.group(3))
                rest = m_vs.group(4) or ""
                assert p_n == paper_num
                # Now expand inline up to next structural macro
                if rest:
                    append_body(rest, [], [])
                run_inline_to_boundary()
                continue

            if name == "vsmark":
                # \vsmark{S}{V}: explicit verse number for the current poetic line.
                # The verse body is everything on the line (already accumulated
                # before this marker, plus anything after it up to \par).
                s_raw = stream.read_brace_arg_raw() or ""
                v_raw = stream.read_brace_arg_raw() or ""
                s_val = int(s_raw.strip())
                v_val = int(v_raw.strip())
                # Just relabel the current verse; \par will flush it.
                cur_verse_section = s_val
                cur_verse_number = v_val
                poetic_active = True
                run_inline_to_boundary()
                continue

            if name == "printvssuper":
                # Opens a poetic verse; the body is what follows on the same line
                flush_verse()
                n_raw = stream.read_brace_arg_raw() or ""
                n_val = int(n_raw.strip())
                cur_verse_section = secnum
                cur_verse_number = n_val
                poetic_active = True
                run_inline_to_boundary()
                continue

            if name == "par":
                # \par is structural in poetic mode (flushes the current verse
                # and increments the verse counter). In normal mode it's
                # a no-op since paragraph breaks fall on \vs boundaries.
                if poetic_active:
                    sec = cur_verse_section
                    ver = cur_verse_number
                    if cur_text_parts and "".join(cur_text_parts).strip():
                        flush_verse()
                        if sec is not None and ver is not None:
                            cur_verse_section = sec
                            cur_verse_number = ver + 1
                    else:
                        # discard empty accumulation
                        cur_text_parts.clear()
                        cur_italics.clear()
                        cur_macros.clear()
                continue

            raise RuntimeError(f"unhandled structural macro \\{name}")

        # Anything else: feed into inline expander, which appends to current verse
        run_inline_to_boundary()
        # If the loop returned because of a CLOSE_BRACE or unknown, consume one
        # token to make progress (otherwise we'd loop forever)
        nxt = stream.peek()
        if nxt is not None and nxt.kind == "CLOSE_BRACE":
            stream.next()

    flush_verse()

    header = {
        "_kind": "paper",
        "paper": paper_num,
        "title": paper_title,
        "subtitle": paper_subtitle,
        "author": author,
        "sections": [
            {"n": s.n, "title": s.title, "combined": s.combined, "combined_with": s.combined_with}
            for s in sections
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
                "macros_seen": v.macros_seen,
            }
            f.write(json.dumps(rec, ensure_ascii=False) + "\n")


def main() -> int:
    if len(sys.argv) < 2:
        print("usage: extract_tex.py tex/pNNN.tex [tex/pMMM.tex ...]")
        return 2
    for path in sys.argv[1:]:
        header, verses = extract_paper(path)
        out_path = f"artifacts/text-verify/tex/p{header['paper']:03d}.jsonl"
        write_jsonl(header, verses, out_path)
        print(f"{path}: paper={header['paper']} title={header['title']!r} "
              f"sections={len(header['sections'])} verses={len(verses)} -> {out_path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
