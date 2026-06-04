import xml.etree.ElementTree as ET
import sys
import re
from collections import defaultdict, Counter


# Body text is set at a glyph height of ~9.96.  Everything else uses a
# different size: Paper titles ("PAPER", the Paper number) ~11.96, section
# headings >=12.95, the "SM" service mark ~3.0, verse/footnote markers ~5.98,
# footnotes ~8.97.  Restricting the analysis to body-height words drops all of
# those, which is what used to flood the output with false positives.
BODY_H_LO, BODY_H_HI = 9.6, 10.3

SPLIT = 231.0                 # x dividing the left column from the right column
PARAGRAPH_GAP_THRESHOLD = 16  # normal body line spacing is ~11; a \pc break is ~22
FLUSH_TOL = 6.0               # a continuation line sits at the margin; an indent is ~12 further in
GUTTER_OFFSET = 4.0           # probe point this far left of the right column margin (inside the gutter)
SINGLE_COL_GUTTER_MIN = 3     # this many body words crossing the gutter => not a two-column page


def is_body(h):
    return BODY_H_LO < h < BODY_H_HI


def find_orphans(html_file):
    """
    Detect orphan (widow) lines at the top of a column in the two-column body.

    An orphan here is the final line of a paragraph that has wrapped to the top
    of a new column and is followed by paragraph spacing (a ``\\pc`` break)
    before the next paragraph: a single line, a blank gap, then a fresh
    paragraph.  The fix is normally a ``\\plusone`` on a preceding paragraph so
    the line count shifts and the lone line is absorbed.

    The line is identified by two robust signals rather than by width (an
    orphan can be almost a full line wide, e.g. "in a God who fosters human
    survival:" on page 1014):

      * It is **flush** with the column's left margin -- i.e. a paragraph
        continuation/tail, not an indented new-paragraph start.  The true margin
        is taken per page-parity (recto/verso shift the text block ~13pt), so a
        list label indented to the new-paragraph position is not mistaken for a
        tail.
      * The gap to the next body line in the column exceeds
        ``PARAGRAPH_GAP_THRESHOLD`` (paragraph spacing, not a normal break).

    Footnotes, headings, markers and the single-column forematter (preface,
    contents, resource pages) are excluded -- the first three by font height,
    the last by detecting the absence of a clean column gutter.
    """
    with open(html_file, 'r', encoding='utf-8') as f:
        content = f.read()

    content = re.sub(r'\sxmlns="[^"]+"', '', content, count=1)
    tree = ET.fromstring(content)
    doc = tree.find('.//doc')
    pages = doc.findall('.//page')

    def page_lines(page):
        """Group a page's words into rounded-yMax lines (within the text body)."""
        y_lines = defaultdict(list)
        for word in page.findall('.//word'):
            if word.text and word.text.strip():
                yMax = float(word.get('yMax'))
                yMin = float(word.get('yMin'))
                y_key = round(yMax)
                if 50 < y_key < 660:
                    y_lines[y_key].append({
                        'text': word.text,
                        'xMin': float(word.get('xMin')),
                        'xMax': float(word.get('xMax')),
                        'h': yMax - yMin,
                    })
        return y_lines

    # --- Pass 1: the flush left margin of each column, per page parity. ---
    # Continuation lines (the majority) sit exactly at the margin, so the most
    # common left edge per parity is the flush margin; indented paragraph starts
    # form a separate, smaller cluster ~12 units further in.
    left_xmin = defaultdict(Counter)
    right_xmin = defaultdict(Counter)
    for i, page in enumerate(pages):
        parity = (i + 1) % 2
        for words in page_lines(page).values():
            lw = [w for w in words if w['xMin'] < SPLIT and is_body(w['h'])]
            rw = [w for w in words if w['xMin'] > SPLIT and is_body(w['h'])]
            if lw:
                left_xmin[parity][round(min(w['xMin'] for w in lw))] += 1
            if rw:
                right_xmin[parity][round(min(w['xMin'] for w in rw))] += 1
    flush_left = {p: c.most_common(1)[0][0] for p, c in left_xmin.items()}
    flush_right = {p: c.most_common(1)[0][0] for p, c in right_xmin.items()}

    # --- Pass 2: find the orphans. ---
    count = 0
    for i, page in enumerate(pages):
        parity = (i + 1) % 2
        fl = flush_left.get(parity)
        fr = flush_right.get(parity)
        # A point just inside the gutter (left of the right column's margin).
        gutter_x = fr - GUTTER_OFFSET if fr is not None else None

        y_lines = page_lines(page)

        gutter_cover = 0
        left_col = []   # (y, xMin, xMax, text)
        right_col = []

        for y in sorted(y_lines):
            words = y_lines[y]

            if gutter_x is not None:
                for w in words:
                    if is_body(w['h']) and w['xMin'] <= gutter_x <= w['xMax']:
                        gutter_cover += 1

            ws = sorted(words, key=lambda w: w['xMin'])
            line_xMin = ws[0]['xMin']
            line_xMax = max(w['xMax'] for w in ws)

            # Skip centered single-flow titles/headings.
            gap_crosses_middle = False
            for j in range(len(ws) - 1):
                gap = ws[j + 1]['xMin'] - ws[j]['xMax']
                if gap > 12 and ws[j]['xMin'] < 240 and ws[j + 1]['xMax'] > 245:
                    gap_crosses_middle = True
            crosses_middle = (line_xMin < 220 and line_xMax > 260)
            if crosses_middle and not gap_crosses_middle and line_xMin > 80 and line_xMax < 390:
                continue

            lw = [w for w in words if w['xMin'] < SPLIT and is_body(w['h'])]
            rw = [w for w in words if w['xMin'] > SPLIT and is_body(w['h'])]
            if lw:
                lx = min(w['xMin'] for w in lw)
                lxmax = max(w['xMax'] for w in lw)
                left_col.append((y, lx, lxmax,
                                 " ".join(w['text'] for w in sorted(lw, key=lambda x: x['xMin']))))
            if rw:
                rx = min(w['xMin'] for w in rw)
                rxmax = max(w['xMax'] for w in rw)
                right_col.append((y, rx, rxmax,
                                  " ".join(w['text'] for w in sorted(rw, key=lambda x: x['xMin']))))

        # Single-column pages (forematter/contents) have no clean gutter: body
        # words run straight across it.  Two-column body pages leave it empty.
        if gutter_x is not None and gutter_cover >= SINGLE_COL_GUTTER_MIN:
            continue

        for col_name, col, flush in (('left', left_col, fl), ('right', right_col, fr)):
            if len(col) < 2 or flush is None:
                continue
            first_y, first_xMin, first_xMax, first_text = col[0]
            gap = col[1][0] - first_y
            is_flush = abs(first_xMin - flush) <= FLUSH_TOL
            if is_flush and gap > PARAGRAPH_GAP_THRESHOLD:
                print(f"Page {i + 1}: ORPHAN at top of {col_name} column")
                print(f"  Orphan line at y={first_y}: '{first_text}'")
                print(f"  Gap to next line: {gap}")
                count += 1

    print(f"Total orphans found: {count}")


if __name__ == "__main__":
    find_orphans(sys.argv[1])
