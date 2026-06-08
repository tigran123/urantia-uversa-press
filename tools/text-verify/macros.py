"""
Explicit dispatch table for every LaTeX macro encountered in the 197
body papers of tex/p[0-9][0-9][0-9].tex.

The TABLE below MUST be exhaustive. The macro-coverage guard
(verify_verifier.py) tokenizes every body paper and fails loudly if any
\\name appears that is NOT in TABLE. This is the strongest assurance
that the extractor is not silently dropping content.

Each entry is keyed by macro name and maps to a Spec:

  Spec(opt=N, args=M, action=ACTION, ...)

opt    — number of [...] optional args to consume
args   — number of {...} mandatory args to consume
action — what to emit:
    STRIP            : emit nothing
    EMIT_TEXT        : emit a fixed literal (text= field)
    EMIT_ARG         : emit the arg indexed by `which` (1-based), expanded
    EMIT_ARG_ITALIC  : emit arg `which` expanded, wrapped in an italic span
    STRUCTURAL       : recognized by extract_tex.py as a paper/section/verse
                       boundary or other structural event; handler will not
                       be called via this table
"""

from __future__ import annotations
from dataclasses import dataclass, field
from typing import Optional


# Action sentinels
STRIP = "STRIP"
EMIT_TEXT = "EMIT_TEXT"
EMIT_ARG = "EMIT_ARG"
EMIT_ARG_ITALIC = "EMIT_ARG_ITALIC"
STRUCTURAL = "STRUCTURAL"


@dataclass
class Spec:
    action: str
    opt: int = 0
    args: int = 0
    which: int = 1        # for EMIT_ARG / EMIT_ARG_ITALIC, the 1-based arg index
    text: str = ""        # for EMIT_TEXT, the literal text to emit
    note: str = ""        # human-readable explanation, optional


# The complete table for all 50 distinct macros in 197 body papers.
# (Counts from the inventory; structural macros are handled by extract_tex.py
# rather than by an emit rule here, but we still list them as STRUCTURAL so
# the macro-coverage guard recognizes them.)

TABLE: dict[str, Spec] = {

    # ---- Structural (handled by extract_tex.py state machine) ----
    "vs":            Spec(STRUCTURAL, note="verse marker: \\vs pNNN C:V body..."),
    "vsmark":        Spec(STRUCTURAL, args=2, note="inline verse marker: \\vsmark{C}{V}"),
    "printvssuper":  Spec(STRUCTURAL, args=1, note="Psalm-style poetic verse marker: opens verse N"),
    "upaper":        Spec(STRUCTURAL, args=2, note="paper title: \\upaper{N}{Title}"),
    "author":        Spec(STRUCTURAL, args=1, note="paper author"),
    "usection":      Spec(STRUCTURAL, args=1, note="section heading; bumps secnum by 1"),
    "usectiontwo":   Spec(STRUCTURAL, args=2, note="combined section heading; bumps secnum by 2"),
    "begin":         Spec(STRUCTURAL, args=1, note="environment open (quoting|ubquote|multicols)"),
    "end":           Spec(STRUCTURAL, args=1, note="environment close"),
    "itshape":       Spec(STRUCTURAL, note="group-scoped italic; extractor must track enclosing group"),

    # ---- Body emit rules ----
    "hyp":           Spec(EMIT_TEXT, args=1, text="-",  note="hard hyphen in compounds; arg is empty {}"),
    "bibemph":       Spec(EMIT_ARG_ITALIC, args=1, note="italic emphasis (matches HTML <em>)"),
    "emph":          Spec(EMIT_ARG_ITALIC, args=1, note="synonym for bibemph"),
    "textcolor":     Spec(EMIT_ARG, args=2, which=2, note="drop color wrapper, keep text"),
    "ublistelem":    Spec(EMIT_ARG, args=1, note="list element label like '1.' — preserve as text + trailing space (see extractor)"),
    "bibnobreakspace": Spec(EMIT_TEXT, text=" ", note="non-breaking space → ordinary space"),
    "tunemarkup":    Spec(STRIP, args=2, note="\\tunemarkup{tag}{body}: typesetting tuning hook; both args are non-textual (tag identifies the rule, body contains layout macros). Strip entirely."),
    "ldots":         Spec(EMIT_TEXT, text="...", note="ellipsis — SRT uses ASCII '...' not U+2026"),

    # textsc renders small caps in print but the SRT keeps the original casing
    "textsc":        Spec(EMIT_ARG, args=1, note="small caps wrapper; keep arg text as-is"),
    "Large":         Spec(STRIP, note="font-size selector (no args)"),
    "small":         Spec(STRIP, note="font-size selector (no args; inside a group)"),

    # ---- Tabular delimiters / spacing that should render as empty in text ----
    "bibdf":         Spec(EMIT_TEXT, text="", note="dot-leader between row label and number; SRT renders as <span class=dot> (also empty in text)"),
    "separatorshort":Spec(STRIP, note="visual divider rule"),
    "separatorline": Spec(STRIP, note="visual divider rule"),
    "preftitle":     Spec(EMIT_ARG, args=1, note="prefix-title decoration; keep text"),
    "ts":            Spec(EMIT_ARG, args=1, note="superscript like 606\\ts{th} → 606th — keep arg text inline"),

    # ---- Layout / line-balancing / spacing — strip silently ----
    "pc":            Spec(STRIP, note="paragraph-chrome separator"),
    "plusone":       Spec(STRIP, note="\\looseness=+1"),
    "plustwo":       Spec(STRIP, note="\\looseness=+2"),
    "minusone":      Spec(STRIP, note="\\looseness=-1"),
    "vsetoff":       Spec(STRIP, note="vertical offset before presenter block"),
    "hsetoff":       Spec(STRIP, note="horizontal indent (used in Lord's Prayer)"),
    "par":           Spec(STRIP, note="paragraph break"),
    "newline":       Spec(STRIP, note="forced newline"),
    "relax":         Spec(STRIP, note="no-op"),
    "linebreak":     Spec(EMIT_TEXT, opt=1, text=" ", note="line break with optional priority [N]; emit a space because it visually separates words (normalize.py collapses any duplicate whitespace)"),
    "newpage":       Spec(STRIP, note="page break"),
    "thispagestyle": Spec(STRIP, args=1, note="page style selector"),
    "-":             Spec(STRIP, note="discretionary hyphen"),
    "\\":            Spec(STRIP, opt=1, note="forced line break, optional [Nex] vertical skip"),
    "_":             Spec(EMIT_TEXT, text="_", note="escaped underscore"),
    ",":             Spec(EMIT_TEXT, text=" ", note="thin space → ordinary"),
    " ":             Spec(EMIT_TEXT, text=" ", note="control-space → ordinary space"),

    # ---- Lengths / spacing that take args — strip silently ----
    "vspace":        Spec(STRIP, opt=1, args=1, note="vertical space (handles \\vspace* via tokenizer naming — see below)"),
    "hspace":        Spec(STRIP, opt=1, args=1, note="horizontal space"),
    "kern":          Spec(STRIP, args=1, note="raw kern; arg is a length expression"),
    "setlength":     Spec(STRIP, args=2, note="set length register"),
    "parindent":     Spec(STRIP, note="length variable; appears bare inside \\setlength args"),
    "baselineskip":  Spec(STRIP, note="length variable inside \\vspace*{N\\baselineskip}"),
    "columnwidth":   Spec(STRIP, note="length variable inside \\hspace*{0.15\\columnwidth}"),
    "linewidth":     Spec(STRIP, note="length variable"),

    # ---- Editorial footnotes — strip entirely (not present in SRT) ----
    "fnc":           Spec(STRIP, args=1, note="editorial footnote (added by this print edition only)"),
    "footnote":      Spec(STRIP, args=1, note="footnote (only 1 occurrence, in p000 1:24)"),

    # ---- Misc one-offs to handle ----
    "makebox":       Spec(EMIT_ARG, opt=2, args=1, note="\\makebox[width][alignment]{text}; emit text — both optional args are layout-only"),
    "times":         Spec(EMIT_TEXT, text=" x ", note="multiplication sign; SRT uses ' x ' (ASCII x with spaces) not '×'"),
    "write":         Spec(STRIP, args=1, note="\\write@mark in p122:69 — internal label emission; strip"),
    "makeatletter":  Spec(STRIP, note="catcode change"),
    "makeatother":   Spec(STRIP, note="catcode change"),
}


# Vspace* / hspace* — TeX accepts `\vspace*{...}` as a starred form. Our
# tokenizer emits MACRO(vspace) followed by TEXT('*{...}'). To keep the
# handler table simple, the extractor pre-strips a single leading '*' when
# present immediately after a starred-form macro. We list which macros
# accept the starred form here:
STARRED_FORMS = {"vspace", "hspace"}


# Macros whose mandatory length argument may be either braced (\\kern{1pt})
# or unbraced (\\kern1pt) — the latter is preferred in some sources. The
# extractor falls back to reading an unbraced length expression from the
# next TEXT token when no `{` is found.
UNBRACED_LENGTH_MACROS = {"kern", "vspace", "hspace"}


# Macros recognized inside body verses as opening/closing an italic group.
# (Used by extract_tex.py to handle `{\itshape WORD}` correctly.)
ITALIC_OPENING_MACROS = {"itshape"}


# Environment names accepted by \begin{...} / \end{...}. The extractor
# strips the env wrapper and keeps the inner content.
KNOWN_ENVIRONMENTS = {"quoting", "ubquote", "multicols"}


def get(name: str) -> Optional[Spec]:
    return TABLE.get(name)


def is_known(name: str) -> bool:
    return name in TABLE
