import xml.etree.ElementTree as ET
import sys
import re
from collections import defaultdict

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
                            y_key = round(yMax)
                            y_lines[y_key].append({
                                'text': word.text,
                                'xMin': float(word.get('xMin')),
                                'xMax': float(word.get('xMax')),
                                'yMax': float(word.get('yMax'))
                            })
                            
        valid_y = [y for y in y_lines.keys() if 50 < y < 630]
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
                if gap > 8 and w1['xMax'] < 240 and w2['xMin'] > 225:
                    gap_crosses_middle = True
            
            crosses_middle = (line_xMin < 220 and line_xMax > 260)
            is_title = crosses_middle and not gap_crosses_middle
                
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
                    'right': right_text
                })
        
        events.append({'type': 'page_break', 'page': i+1})
        
    events.append({'type': 'eof'})

    sections = []
    current_section_lines = []
    
    for ev in events:
        if ev['type'] == 'line':
            current_section_lines.append(ev)
        elif ev['type'] in ('title', 'eof', 'page_break'):
            if current_section_lines:
                sections.append(current_section_lines)
                current_section_lines = []

    count = 0
    for sec_idx, sec_lines in enumerate(sections):
        # find the last page in this section
        last_page = sec_lines[-1]['page']
        
        # get all lines on the last page of this section
        last_page_lines = [l for l in sec_lines if l['page'] == last_page]
        
        left_col = [(l['y'], l['left']) for l in last_page_lines if l['left']]
        right_col = [(l['y'], l['right']) for l in last_page_lines if l['right']]
        
        # filter footnotes
        left_valid = [l for l in left_col if not re.match(r'^\d+[a-zA-Z]', l[1])]
        right_valid = [l for l in right_col if not re.match(r'^\d+[a-zA-Z]', l[1])]
        
        if not left_valid or not right_valid:
            continue
            
        left_last_y = left_valid[-1][0]
        right_last_y = right_valid[-1][0]
        
        if abs(left_last_y - right_last_y) > 5:
            count += 1
            print(f"Page {last_page}: UNBALANCED (Diff: {abs(left_last_y - right_last_y)})")
            print(f"  Left ends at y={left_last_y}: {left_valid[-1][1]}")
            print(f"  Right ends at y={right_last_y}: {right_valid[-1][1]}")

    print(f"Total unbalanced columns found: {count}")

if __name__ == "__main__":
    analyze_bbox(sys.argv[1])