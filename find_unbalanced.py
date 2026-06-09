import xml.etree.ElementTree as ET
import sys
import re
from collections import defaultdict

# Body text is set at a glyph height of ~9.96.  Footnotes (~8.97), the
# publisher's preface (~11.96), the single-column table of contents (~9.27/9.46),
# and section/part titles (>=12.95) all use distinctly different sizes.  Keeping
# only body-height words for the column-end comparison therefore drops footnotes
# (which sit below a rule at the column bottom) and the single-column forematter,
# both of which used to produce false "unbalanced" reports.
BODY_H_LO, BODY_H_HI = 9.6, 10.3

def is_body(h):
    return BODY_H_LO < h < BODY_H_HI

def analyze_bbox(html_file):
    with open(html_file, 'r', encoding='utf-8') as f:
        content = f.read()
    
    content = re.sub(r'\sxmlns="[^"]+"', '', content, count=1)
    tree = ET.fromstring(content)
    doc = tree.find('.//doc')
    
    events = []
    
    for i, page in enumerate(doc.findall('.//page')):
        y_lines = defaultdict(list)
        for flow in page.findall('.//flow'):
            for block in flow.findall('.//block'):
                for line in block.findall('.//line'):
                    for word in line.findall('.//word'):
                        if word.text and word.text.strip():
                            yMax = float(word.get('yMax'))
                            yMin = float(word.get('yMin'))
                            y_key = round(yMax)
                            y_lines[y_key].append({
                                'text': word.text,
                                'xMin': float(word.get('xMin')),
                                'xMax': float(word.get('xMax')),
                                'yMax': yMax,
                                'h': yMax - yMin
                            })
                            
        valid_y = [y for y in y_lines.keys() if 50 < y < 660]
        valid_y.sort()
        
        for y in valid_y:
            words = y_lines[y]
            words_sorted = sorted(words, key=lambda w: w['xMin'])
            if not words_sorted: continue
            line_xMin = words_sorted[0]['xMin']
            line_xMax = max(w['xMax'] for w in words_sorted)
            
            # Find if there is a gap crossing the middle
            gap_crosses_middle = False
            for j in range(len(words_sorted) - 1):
                w1 = words_sorted[j]
                w2 = words_sorted[j+1]
                gap = w2['xMin'] - w1['xMax']
                if gap > 12 and w1['xMin'] < 240 and w2['xMax'] > 245:
                    gap_crosses_middle = True

            crosses_middle = (line_xMin < 220 and line_xMax > 260)
            line_width = line_xMax - line_xMin
            is_title = crosses_middle and not gap_crosses_middle and line_xMin > 80 and line_xMax < 390 and line_width > 100
                
            if is_title:
                events.append({'type': 'title'})
            else:
                left_w = [w for w in words if w['xMin'] < 231]
                right_w = [w for w in words if w['xMin'] > 231]
                
                left_text = " ".join(w['text'] for w in sorted(left_w, key=lambda x: x['xMin'])) if left_w else ""
                right_text = " ".join(w['text'] for w in sorted(right_w, key=lambda x: x['xMin'])) if right_w else ""

                events.append({
                    'type': 'line',
                    'page': i+1,
                    'y': y,
                    'left': left_text,
                    'right': right_text,
                    'left_body': any(is_body(w['h']) for w in left_w),
                    'right_body': any(is_body(w['h']) for w in right_w)
                })
        
        events.append({'type': 'page_break', 'page': i+1})
        
    events.append({'type': 'eof'})

    sections = []
    current_section_lines = []
    
    for ev in events:
        if ev['type'] == 'line':
            current_section_lines.append(ev)
        elif ev['type'] in ('title', 'eof'):
            if current_section_lines:
                sections.append(current_section_lines)
                current_section_lines = []

    count = 0
    # Real bottom-margin intrusion: a body baseline below the empirical full-page
    # ceiling.  Across the whole book normal full pages bottom out at y=625 (deepest
    # of the 621-625 cluster); nothing legitimate reaches 626.  A baseline > 625
    # therefore means a line was crammed past \textheight -- genuine intrusion.
    # (This is distinct from an "Overfull \vbox" log warning, which is a benign
    # \flushbottom/footnote box-accounting effect and does NOT put text in the margin.)
    MARGIN_Y = 625
    margin_count = 0
    margin_reported = set()
    for sec_idx, sec_lines in enumerate(sections):
        # find all pages in this section
        pages = sorted(list(set(l['page'] for l in sec_lines)))
        
        for page in pages:
            # get all lines on this page of this section
            page_lines = [l for l in sec_lines if l['page'] == page]

            # Only body-text lines count toward the column-end comparison.  This
            # excludes footnotes (smaller font, below a rule at the column foot)
            # and the single-column forematter (preface/contents, different fonts),
            # both of which otherwise registered as spurious imbalances.
            left_valid = [(l['y'], l['left']) for l in page_lines if l['left'] and l['left_body']]
            right_valid = [(l['y'], l['right']) for l in page_lines if l['right'] and l['right_body']]
            
            if not left_valid or not right_valid:
                continue

            left_last_y = left_valid[-1][0]
            right_last_y = right_valid[-1][0]

            is_last_page = (page == pages[-1])

            # If it's not the last page of the block, it should be full.
            # A full column usually ends around y=623.
            # If it's the last page of the block, it should be balanced.

            diff = abs(left_last_y - right_last_y)
            if diff > 5:
                count += 1
                print(f"Page {page}: UNBALANCED (Diff: {diff})")
                print(f"  Left ends at y={left_last_y}: {left_valid[-1][1]}")
                print(f"  Right ends at y={right_last_y}: {right_valid[-1][1]}")

            # Independent of the balance check: flag real bottom-margin intrusion.
            if (left_last_y > MARGIN_Y or right_last_y > MARGIN_Y) and page not in margin_reported:
                margin_reported.add(page)
                margin_count += 1
                over = max(left_last_y, right_last_y) - MARGIN_Y
                print(f"Page {page}: MARGIN INTRUSION - body baseline y={max(left_last_y, right_last_y)} "
                      f"({over} pt past the y={MARGIN_Y} full-page ceiling)  Left:{left_last_y} Right:{right_last_y}")

    print(f"Total unbalanced columns found: {count}")
    print(f"Total bottom-margin intrusions found: {margin_count}  (body baseline > y={MARGIN_Y})")

if __name__ == "__main__":
    analyze_bbox(sys.argv[1])
