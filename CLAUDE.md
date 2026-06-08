# Project Instructions: Urantia Uversa Press

XeLaTeX two-column book (197 papers, 1149+ pages, 6.5×9 in, `multicol`).
Source in `tex/pNNN.tex`; style in `urantia-uversa-press.sty`; build via `Makefile`.

## Critical Workflow Rules

**Per-paper verification after EVERY edit.** Whole-book builds are too slow.
After any change to `tex/pNNN.tex`:

```bash
make clean ; make LIST=pNNN DRAFT=1
pdftotext -bbox-layout urantia-uversa-press.pdf pNNN_bbox.html
python3 find_unbalanced.py pNNN_bbox.html   # target: 0
python3 find_orphans.py    pNNN_bbox.html   # target: 0
grep -c 'Overfull \\hbox'  urantia-uversa-press.log   # target: 0 for that paper
```

A fix is not done until all three are clean. A "fix" that resolves one warning but
introduces an orphan or imbalance elsewhere in the paper is **not** a fix — revert it.

**Commit style.** One paper per commit (e.g., `Fix overfull \hbox at 2:7.11`).
Do not bundle papers.

## Column Balancing Macros

- `\plusone` — stretch a paragraph by exactly one line. Append with **NO space before**
  the macro. Prefer the **longest** paragraph with the **longest trailing line** in the
  column you want to extend (minimizes visual stretching).
- `\plustwo` — stretch by two. Use on the **shorter** paragraph in the underfilled
  column when `\plusone` alone leaves a single-line widow at the column top.
- `\minusone` — Not as effective as `\plusone`, but occasionally does shrink the text.
- After any layout-shifting hyphen addition, **re-evaluate existing `\plusone`/`\plustwo`** in
  the same paper. New imbalances may be caused by macros that are now redundant.
- Margin constraint: stretching grows text height; do not let columns cross `y > 625`
  (watch for `Overfull \vbox` / "Text extends into bottom margin" warnings).

## Fixing Overfull \hbox

The user prefers fixing visible overflow (≥ ~3 pt at this trim) with **discretionary
hyphenation** rather than `\plusone`. Techniques, in order of preference:

1. **Discretionary hyphens `\-`** at syllable boundaries inside the words on the
   offending line. Add hyphens to several candidate words — TeX picks the best break.
   Example: `con\-tem\-pla\-tion of the spir\-i\-tu\-al super\-think\-ing`.

2. **`\allowbreak{}`** inside long numbers/identifiers, ideally after a comma or
   punctuation so the break is invisible. Example: `842,\allowbreak{}842,\allowbreak{}682`.

3. **`\resizebox{\linewidth}{!}{...}`** (from `graphicx`, already loaded in
   `urantia-uversa-press.sty:15`) when the overfull line is inside a `\makebox` —
   discretionary hyphens **don't break inside single-line boxes**. `\resizebox` scales
   the content (usually < 1 %) to fit.

4. **`\plusone` / `\plustwo`** as fallback when no good hyphen split exists.

Known limits:

- TeX's badness optimizer may stay locked on a slightly overfull break even after you
  add hyphens elsewhere — if 2–3 attempts at different hyphen sets don't change the
  break, accept ≤ ~3 pt overflow and revert.
- A `\-` that splits a short word (e.g., `Day\-nals`) may push it onto two lines,
  growing the paragraph by a line and **cascading** into column imbalances downstream.
  Verify per-paper after every hyphenation; revert if it breaks layout elsewhere.
- `\mbox{word}` to forbid a bad break usually makes things worse (the previous line gets
  much longer).
- `\linebreak[4]` eliminates overfull but commonly produces a `badness 10000` underfull
  with ugly stretched inter-word spacing — avoid.

## Text Conventions

- All quote marks are curly (`“ ”`, `‘ ’`); never `"` or `''`.
- Hyphenated compounds in body text use `\hyp{}` (raw `-` only inside `\fnc{}`).
- Hyphenation exceptions live in `tex/urantia-hyphen-en.tex`. Words hyphenated > N times
  across the book are candidates for adding there.
- Verse markers are `\vs pNNN C:V`; sections start with `\usection{...}` (or
  `\usectiontwo{C and C+1}{...}` for merged sections — note this bumps `secnum` by 2
  and skips a `\label`, so manual `\label{pNNN_C}` may be needed for the TOC).

## Diagnostic Tools

- `find_unbalanced.py pNNN_bbox.html` — column-height differences per page.
- `find_orphans.py    pNNN_bbox.html` — single-line orphans at column top.
- `urantia-uversa-press.log` — `Overfull \hbox`, `Overfull \vbox`, `Underfull`,
  `Package multicol Warning: I moved some lines to the next page` (a column-flow event
  worth eye-balling).
- Stack-aware log parsing: each `Overfull \hbox` warning maps to a source file by
  tracking nested `(./tex/pNNN.tex` open/close parens around the warning line.
- Clean up `*_bbox.html` after use — they are diagnostic-only, never commit.

## Don't Commit

- `The-Urantia-Book-Uversa-Press-2012.pdf` (reference copy, untracked).
- `*_bbox.html`, `urantia-uversa-press.{aux,log,pdf}` (build artifacts).

## Pre-print Plan

See `~/.claude/plans/as-you-remember-we-moonlit-hellman.md` for the 23-item
pre-print checklist (A. layout scripts, B. log/xref audit, C. text integrity,
D. press-ready PDF). Current position: B8 (overfull \hbox triage) complete;
B9 (19 overfull \vbox) next.
