import xml.etree.ElementTree as ET
import sys
import re

def get_unbalanced(html_file):
    with open(html_file, 'r', encoding='utf-8') as f:
        content = f.read()
    
    content = re.sub(r'\sxmlns="[^"]+"', '', content, count=1)
    tree = ET.fromstring(content)
    doc = tree.find('.//doc')
    
    for i, page in enumerate(doc.findall('.//page')):
        lines = []
        for flow in page.findall('.//flow'):
            for block in flow.findall('.//block'):
                for line in block.findall('.//line'):
                    xMin = float(line.get('xMin'))
                    xMax = float(line.get('xMax'))
                    yMax = float(line.get('yMax'))
                    yMin = float(line.get('yMin'))
                    words = []
                    for word in line.findall('.//word'):
                        if word.text:
                            words.append(word.text)
                    text = " ".join(words).strip()
                    if text:
                        lines.append({
                            'text': text,
                            'xMin': xMin,
                            'xMax': xMax,
                            'yMax': yMax,
                            'yMin': yMin
                        })
        
        # filter headers and footers/footnotes
        body_lines = [l for l in lines if l['yMax'] > 100 and l['yMax'] < 610]
        body_lines.sort(key=lambda l: l['yMin'])
        
        left_lines = []
        right_lines = []
        
        def check_block():
            if not left_lines or not right_lines:
                return None
            left_bottom = max(left_lines, key=lambda l: l['yMax'])
            right_bottom = max(right_lines, key=lambda l: l['yMax'])
            diff = abs(left_bottom['yMax'] - right_bottom['yMax'])
            if diff > 5.0:
                # return info
                return (i+1, left_bottom, right_bottom)
            return None

        for line in body_lines:
            if line['xMin'] < 240 and line['xMax'] > 240:
                res = check_block()
                if res: return res
                left_lines = []
                right_lines = []
            elif line['xMax'] < 240:
                left_lines.append(line)
            elif line['xMin'] > 240:
                right_lines.append(line)
                
        res = check_block()
        if res: return res

    return None

if __name__ == "__main__":
    res = get_unbalanced(sys.argv[1])
    if res:
        page, left, right = res
        print(f"Page {page}: Left ends yMax={left['yMax']:.2f}, Right ends yMax={right['yMax']:.2f}")
        print(f"Left text: {left['text']}")
        print(f"Right text: {right['text']}")
    else:
        print("BALANCED")
