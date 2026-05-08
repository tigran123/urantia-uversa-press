import xml.etree.ElementTree as ET
import sys
import re
from collections import defaultdict


def find_orphans(html_file):
    """
    Detect orphan-word column starts in a two-column PDF layout.

    An "orphan" is the last line of a paragraph that has wrapped to the start
    of a new column (left or right) and is followed by paragraph spacing
    (a \\pc break in the source) before the next paragraph begins. This
    creates an aesthetically poor column-top: a single short line, then a
    blank gap, then the next paragraph.

    Detection criteria:
      - The first non-title line of a column is "short" (line width <
        SHORT_WIDTH_THRESHOLD).
      - The vertical gap to the next line in that column exceeds
        PARAGRAPH_GAP_THRESHOLD (indicating paragraph spacing, not just a
        normal line break).

    The fix is to add \\plusone to one of the preceding paragraphs (typically
    the wrapping paragraph itself) so that its line count changes and the
    orphan disappears.
    """
    SHORT_WIDTH_THRESHOLD = 100   # less than ~half of a ~200-unit column
    PARAGRAPH_GAP_THRESHOLD = 16  # normal line spacing is ~11 units

    with open(html_file, 'r', encoding='utf-8') as f:
        content = f.read()

    content = re.sub(r'\sxmlns="[^"]+"', '', content, count=1)
    tree = ET.fromstring(content)
    doc = tree.find('.//doc')

    count = 0

    for page_idx, page in enumerate(doc.findall('.//page')):
        y_lines = defaultdict(list)
        for word in page.findall('.//word'):
            if word.text and word.text.strip():
                yMax = float(word.get('yMax'))
                y_key = round(yMax)
                y_lines[y_key].append({
                    'text': word.text,
                    'xMin': float(word.get('xMin')),
                    'xMax': float(word.get('xMax')),
                })

        valid_y = sorted(y for y in y_lines.keys() if 50 < y < 630)

        left_col = []   # (y, xMin, xMax, text)
        right_col = []

        for y in valid_y:
            words = y_lines[y]
            words_sorted = sorted(words, key=lambda w: w['xMin'])
            line_xMin = words_sorted[0]['xMin']
            line_xMax = max(w['xMax'] for w in words_sorted)

            # Detect titles (single-flow lines that cross the column gutter)
            gap_crosses_middle = False
            for j in range(len(words_sorted) - 1):
                w1 = words_sorted[j]
                w2 = words_sorted[j + 1]
                gap = w2['xMin'] - w1['xMax']
                if gap > 5 and w1['xMax'] < 240 and w2['xMin'] > 225:
                    gap_crosses_middle = True
            crosses_middle = (line_xMin < 220 and line_xMax > 260)
            is_title = crosses_middle and not gap_crosses_middle
            if is_title:
                continue

            left_w = [w for w in words if w['xMin'] < 228]
            right_w = [w for w in words if w['xMin'] > 228]

            if left_w:
                lxMin = min(w['xMin'] for w in left_w)
                lxMax = max(w['xMax'] for w in left_w)
                ltext = " ".join(w['text'] for w in sorted(left_w, key=lambda x: x['xMin']))
                left_col.append((y, lxMin, lxMax, ltext))

            if right_w:
                rxMin = min(w['xMin'] for w in right_w)
                rxMax = max(w['xMax'] for w in right_w)
                rtext = " ".join(w['text'] for w in sorted(right_w, key=lambda x: x['xMin']))
                right_col.append((y, rxMin, rxMax, rtext))

        # Filter footnote lines (start with digit immediately followed by letter)
        left_col = [l for l in left_col if not re.match(r'^\d+[a-zA-Z]', l[3])]
        right_col = [l for l in right_col if not re.match(r'^\d+[a-zA-Z]', l[3])]

        for col_name, col in [('left', left_col), ('right', right_col)]:
            if len(col) < 2:
                continue

            first_y, first_xMin, first_xMax, first_text = col[0]
            second_y = col[1][0]

            first_width = first_xMax - first_xMin
            gap = second_y - first_y

            if first_width < SHORT_WIDTH_THRESHOLD and gap > PARAGRAPH_GAP_THRESHOLD:
                print(f"Page {page_idx + 1}: ORPHAN at top of {col_name} column")
                print(f"  Orphan line at y={first_y}: '{first_text}' (width={first_width:.1f})")
                print(f"  Gap to next line: {gap}")
                count += 1

    print(f"Total orphans found: {count}")


if __name__ == "__main__":
    find_orphans(sys.argv[1])
