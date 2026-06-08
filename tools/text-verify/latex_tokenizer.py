"""
Brace-aware LaTeX tokenizer for The Urantia Book LaTeX corpus.

No regex shortcuts for macro arguments — that class of bugs (nested
\\fnc{... \\bibemph{x} ...} arg leakage) is exactly what this tokenizer
exists to prevent.

The tokenizer is intentionally DUMB about macro semantics. It emits a flat
stream of tokens; the extract_tex.py consumer dispatches per the macros.py
handler table to decide what each macro means.

Token types:
  TEXT(value)           literal text run
  MACRO(name)           \\foo  (letters-only name; single-char names like \\- handled too)
  OPEN_BRACE            {  (not yet bound to a macro argument)
  CLOSE_BRACE           }
  OPEN_BRACKET          [
  CLOSE_BRACKET         ]
  COMMENT(value)        %... up to end of line (not including the newline)
  NEWLINE               literal newline

The consumer reads a MACRO and then peeks the upcoming tokens to decide
how many {...} (or optional [...]) arguments to bind. Helpers
`read_balanced_group` and `read_optional_arg` perform that binding while
honoring brace nesting.
"""

from __future__ import annotations
from dataclasses import dataclass
from typing import Iterator, Optional


# ----- Token definition -----

@dataclass
class Token:
    kind: str           # TEXT | MACRO | OPEN_BRACE | CLOSE_BRACE | OPEN_BRACKET | CLOSE_BRACKET | COMMENT | NEWLINE
    value: str = ""     # for TEXT, MACRO (name), COMMENT
    line: int = 0       # 1-based source line where the token begins
    col: int = 0        # 1-based source column where the token begins

    def __repr__(self) -> str:
        v = self.value if len(self.value) <= 40 else self.value[:37] + "..."
        return f"Token({self.kind} {v!r} @ {self.line}:{self.col})"


# ----- Low-level tokenizer -----

def tokenize(src: str) -> list[Token]:
    """Tokenize a LaTeX source string into a flat list of tokens.

    Brace and bracket characters appear as tokens; they are NOT yet bound
    to a particular macro's arguments. Comments (% to EOL) are emitted as
    COMMENT tokens with the comment body (sans leading %) for traceability;
    the consumer typically drops them.
    """
    out: list[Token] = []
    i = 0
    n = len(src)
    line = 1
    col = 1
    # accumulator for runs of plain text
    text_buf: list[str] = []
    text_start_line = 1
    text_start_col = 1

    def flush_text() -> None:
        if text_buf:
            out.append(Token("TEXT", "".join(text_buf), text_start_line, text_start_col))
            text_buf.clear()

    def push_text(ch: str) -> None:
        if not text_buf:
            nonlocal text_start_line, text_start_col
            text_start_line = line
            text_start_col = col
        text_buf.append(ch)

    while i < n:
        ch = src[i]

        if ch == "\\":
            # Macro: '\' then either letters+ (control word) or one non-letter (control symbol)
            flush_text()
            start_line, start_col = line, col
            i += 1
            col += 1
            if i >= n:
                out.append(Token("MACRO", "", start_line, start_col))
                break
            nxt = src[i]
            if nxt.isalpha():
                j = i
                while j < n and src[j].isalpha():
                    j += 1
                name = src[i:j]
                col += j - i
                i = j
                # LaTeX convention: a control word swallows following spaces
                # (until newline). Doing so keeps "\\foo bar" from emitting a
                # leading space in the TEXT that follows.
                while i < n and src[i] in " \t":
                    i += 1
                    col += 1
                out.append(Token("MACRO", name, start_line, start_col))
            else:
                # Control symbol — one char (e.g., \\-, \\%, \\{, \\}, \\\\)
                name = nxt
                i += 1
                col += 1
                out.append(Token("MACRO", name, start_line, start_col))
            continue

        if ch == "{":
            flush_text()
            out.append(Token("OPEN_BRACE", "{", line, col))
            i += 1
            col += 1
            continue
        if ch == "}":
            flush_text()
            out.append(Token("CLOSE_BRACE", "}", line, col))
            i += 1
            col += 1
            continue
        if ch == "[":
            flush_text()
            out.append(Token("OPEN_BRACKET", "[", line, col))
            i += 1
            col += 1
            continue
        if ch == "]":
            flush_text()
            out.append(Token("CLOSE_BRACKET", "]", line, col))
            i += 1
            col += 1
            continue

        if ch == "%":
            flush_text()
            j = i + 1
            while j < n and src[j] != "\n":
                j += 1
            out.append(Token("COMMENT", src[i + 1:j], line, col))
            col += j - i
            i = j
            continue

        if ch == "\n":
            flush_text()
            out.append(Token("NEWLINE", "\n", line, col))
            i += 1
            line += 1
            col = 1
            continue

        push_text(ch)
        i += 1
        col += 1

    flush_text()
    return out


# ----- Consumer helpers (used by extract_tex.py) -----

class TokenStream:
    """Random-access cursor over a token list, with helpers for argument binding."""

    def __init__(self, tokens: list[Token]):
        self.tokens = tokens
        self.pos = 0

    def __len__(self) -> int:
        return len(self.tokens) - self.pos

    def peek(self, offset: int = 0) -> Optional[Token]:
        idx = self.pos + offset
        if idx < 0 or idx >= len(self.tokens):
            return None
        return self.tokens[idx]

    def next(self) -> Optional[Token]:
        tok = self.peek()
        if tok is not None:
            self.pos += 1
        return tok

    def skip_whitespace(self) -> None:
        """Skip TEXT tokens that are only whitespace, and NEWLINE tokens."""
        while True:
            tok = self.peek()
            if tok is None:
                return
            if tok.kind == "NEWLINE":
                self.pos += 1
                continue
            if tok.kind == "TEXT" and tok.value.strip() == "":
                self.pos += 1
                continue
            return

    def read_optional_arg(self) -> Optional[str]:
        """If next non-ws token is `[`, consume up to matching `]` and return raw string.
        Returns None if no optional arg present.
        """
        save = self.pos
        self.skip_whitespace()
        tok = self.peek()
        if tok is None or tok.kind != "OPEN_BRACKET":
            self.pos = save
            return None
        # consume the [
        self.pos += 1
        out: list[str] = []
        depth = 1
        while True:
            tok = self.next()
            if tok is None:
                # unbalanced; restore and bail
                self.pos = save
                return None
            if tok.kind == "OPEN_BRACKET":
                depth += 1
                out.append("[")
            elif tok.kind == "CLOSE_BRACKET":
                depth -= 1
                if depth == 0:
                    return "".join(out)
                out.append("]")
            else:
                out.append(_token_to_raw(tok))

    def read_brace_group_tokens(self) -> Optional[list[Token]]:
        """If next non-ws token is `{`, consume up to its matching `}` and
        return the tokens INSIDE the group (not including the braces).
        Returns None if no group present.
        """
        save = self.pos
        self.skip_whitespace()
        tok = self.peek()
        if tok is None or tok.kind != "OPEN_BRACE":
            self.pos = save
            return None
        self.pos += 1
        depth = 1
        out: list[Token] = []
        while True:
            tok = self.next()
            if tok is None:
                self.pos = save
                return None
            if tok.kind == "OPEN_BRACE":
                depth += 1
                out.append(tok)
            elif tok.kind == "CLOSE_BRACE":
                depth -= 1
                if depth == 0:
                    return out
                out.append(tok)
            else:
                out.append(tok)

    def read_brace_arg_raw(self) -> Optional[str]:
        """Same as read_brace_group_tokens but reconstructs source text."""
        toks = self.read_brace_group_tokens()
        if toks is None:
            return None
        return _tokens_to_raw(toks)


def _token_to_raw(tok: Token) -> str:
    """Reconstruct best-effort source representation of a token."""
    if tok.kind == "TEXT":
        return tok.value
    if tok.kind == "NEWLINE":
        return "\n"
    if tok.kind == "MACRO":
        if tok.value and tok.value[0].isalpha():
            return "\\" + tok.value + " "
        return "\\" + tok.value
    if tok.kind == "OPEN_BRACE":
        return "{"
    if tok.kind == "CLOSE_BRACE":
        return "}"
    if tok.kind == "OPEN_BRACKET":
        return "["
    if tok.kind == "CLOSE_BRACKET":
        return "]"
    if tok.kind == "COMMENT":
        return "%" + tok.value
    return ""


def _tokens_to_raw(tokens: list[Token]) -> str:
    return "".join(_token_to_raw(t) for t in tokens)


# ----- Unit tests (run as `python3 latex_tokenizer.py --test`) -----

def _test() -> None:
    cases = [
        ("plain", "Hello world.", [("TEXT", "Hello world.")]),
        ("macro_word",
         r"\foo bar",
         [("MACRO", "foo"), ("TEXT", "bar")]),
        ("macro_symbol",
         r"a\-b",
         [("TEXT", "a"), ("MACRO", "-"), ("TEXT", "b")]),
        ("group",
         r"a{b}c",
         [("TEXT", "a"), ("OPEN_BRACE", "{"), ("TEXT", "b"), ("CLOSE_BRACE", "}"), ("TEXT", "c")]),
        ("comment",
         "a%hidden\nb",
         [("TEXT", "a"), ("COMMENT", "hidden"), ("NEWLINE", "\n"), ("TEXT", "b")]),
        ("backslash_space_swallow",
         r"\foo   bar",
         [("MACRO", "foo"), ("TEXT", "bar")]),
    ]
    for name, src, expected in cases:
        got = tokenize(src)
        got_simple = [(t.kind, t.value) for t in got]
        assert got_simple == expected, f"FAIL {name}: got {got_simple!r}, want {expected!r}"
        print(f"ok  {name}")

    # Brace nesting (the bug class this tool exists to prevent)
    src = r"\fnc{outer \bibemph{inner} more}TAIL"
    toks = tokenize(src)
    stream = TokenStream(toks)
    mac = stream.next()
    assert mac.kind == "MACRO" and mac.value == "fnc", repr(mac)
    arg_tokens = stream.read_brace_group_tokens()
    assert arg_tokens is not None
    arg_raw = _tokens_to_raw(arg_tokens)
    # The raw arg should include the entire nested content
    assert "bibemph" in arg_raw and "inner" in arg_raw and "more" in arg_raw
    assert "TAIL" not in arg_raw, f"arg leaked: {arg_raw!r}"
    # After the arg, the cursor should see TEXT "TAIL"
    nxt = stream.next()
    assert nxt is not None and nxt.kind == "TEXT" and "TAIL" in nxt.value, repr(nxt)
    print("ok  nested_brace_arg")

    # Optional arg
    src = r"\linebreak[4]rest"
    toks = tokenize(src)
    stream = TokenStream(toks)
    mac = stream.next()
    assert mac.value == "linebreak"
    opt = stream.read_optional_arg()
    assert opt == "4", repr(opt)
    nxt = stream.next()
    assert nxt.kind == "TEXT" and nxt.value == "rest", repr(nxt)
    print("ok  optional_arg")

    # Multi-arg
    src = r"\usectiontwo{9 and 10}{James and Judas Alpheus}"
    toks = tokenize(src)
    stream = TokenStream(toks)
    mac = stream.next()
    assert mac.value == "usectiontwo"
    a1 = stream.read_brace_arg_raw()
    a2 = stream.read_brace_arg_raw()
    assert a1 == "9 and 10", repr(a1)
    assert a2 == "James and Judas Alpheus", repr(a2)
    print("ok  multi_arg")

    # \hyp{} inside a word
    src = r"all\hyp{}powerful"
    toks = tokenize(src)
    assert [(t.kind, t.value) for t in toks] == [
        ("TEXT", "all"),
        ("MACRO", "hyp"),
        ("OPEN_BRACE", "{"),
        ("CLOSE_BRACE", "}"),
        ("TEXT", "powerful"),
    ]
    print("ok  hyp_in_word")

    print("\nALL TESTS PASS")


if __name__ == "__main__":
    import sys
    if len(sys.argv) > 1 and sys.argv[1] == "--test":
        _test()
    elif len(sys.argv) > 1:
        path = sys.argv[1]
        with open(path, encoding="utf-8") as f:
            src = f.read()
        toks = tokenize(src)
        print(f"# {len(toks)} tokens from {path}")
        for t in toks[:200]:
            print(t)
        if len(toks) > 200:
            print(f"... ({len(toks) - 200} more)")
    else:
        print("usage: latex_tokenizer.py [--test | FILE]")
