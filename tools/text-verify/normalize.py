"""
Shared normalization for verse text.

Both extractors have already done their side-specific work (LaTeX side
converts --- → em-dash, expands macros, collapses whitespace; HTML side
collapses whitespace, projects italic spans). This module performs the
FINAL identical pass on both sides immediately before comparison.

Rules:
  - NFC unicode normalization
  - NBSP (U+00A0), narrow NBSP (U+202F), thin space (U+2009) → space
  - Modifier letter apostrophe (U+02BC) → curly apostrophe (U+2019) (defensive)
  - Collapse runs of whitespace to a single ASCII space
  - Strip leading/trailing whitespace
  - DO NOT normalize curly-quote variants — both sides confirmed uniform.

Logs suspicious characters (NBSP/U+02BC) as warnings so they can be
audited even though they are absorbed.
"""

from __future__ import annotations
import re
import unicodedata
from typing import Optional


SUSPICIOUS_CHARS = {
    " ": "NBSP",
    " ": "NARROW_NBSP",
    " ": "THIN_SPACE",
    "ʼ": "MODIFIER_APOSTROPHE",
}


def find_suspicious(s: str) -> dict[str, int]:
    """Count suspicious glyphs in s. Returns name → count."""
    out: dict[str, int] = {}
    for ch, name in SUSPICIOUS_CHARS.items():
        n = s.count(ch)
        if n:
            out[name] = n
    return out


def normalize_with_offsets(s: str) -> tuple[str, list[int]]:
    """Apply normalization and return (normalized_string, offset_map).

    offset_map[i] = output index of input character i (with sentinel
    offset_map[len(s)] = len(output)).
    """
    s = unicodedata.normalize("NFC", s)
    # Char-by-char substitution + ws collapse in one pass
    out: list[str] = []
    in_to_out: list[int] = []
    last_was_ws = True  # strip leading ws
    for ch in s:
        # Defensive remaps
        if ch == "ʼ":
            ch = "’"
        if ch in (" ", " ", " "):
            ch = " "
        if ch.isspace():
            if not last_was_ws:
                in_to_out.append(len(out))
                out.append(" ")
                last_was_ws = True
            else:
                in_to_out.append(len(out))  # collapsed
        else:
            in_to_out.append(len(out))
            out.append(ch)
            last_was_ws = False
    in_to_out.append(len(out))

    result = "".join(out).rstrip()
    final_len = len(result)
    in_to_final = [min(o, final_len) for o in in_to_out]
    return result, in_to_final


def normalize(s: str) -> str:
    out, _ = normalize_with_offsets(s)
    return out


def project_italics(italics: list[tuple[int, int]], offset_map: list[int], text_len_out: int) -> list[tuple[int, int]]:
    """Project italic spans through the normalization offset map."""
    out: list[tuple[int, int]] = []
    for s, e in italics:
        s = max(0, min(s, len(offset_map) - 1))
        e = max(0, min(e, len(offset_map) - 1))
        ns = offset_map[s]
        ne = offset_map[e]
        if ns < ne:
            out.append((ns, ne))
    if out:
        out.sort()
        merged = [out[0]]
        for s, e in out[1:]:
            if s <= merged[-1][1]:
                merged[-1] = (merged[-1][0], max(merged[-1][1], e))
            else:
                merged.append((s, e))
        out = merged
    return out


def normalize_verse(text: str, italics: list[list[int]]) -> tuple[str, list[tuple[int, int]], dict[str, int]]:
    """Normalize text + project italics. Returns (text, italics, suspicious_counts)."""
    sus = find_suspicious(text)
    out, omap = normalize_with_offsets(text)
    new_italics = project_italics([(s, e) for s, e in italics], omap, len(out))
    return out, new_italics, sus
