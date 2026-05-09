import xml.etree.ElementTree as ET
import sys
import re

def check_unbalanced(html_file):
    with open(html_file, 'r', encoding='utf-8') as f:
        content = f.read()
    
    # Remove xmlns to make parsing easier
    content = re.sub(r'\sxmlns="[^"]+"', '', content, count=1)
    
    tree = ET.fromstring(content)
    doc = tree.find('.//doc')
    
    for i, page in enumerate(doc.findall('.//page')):
        width = float(page.get('width'))
        height = float(page.get('height'))
        
        # Collect all lines
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
        
        # Filter out headers and footers
        # Headers are usually yMax < 100 (FOREWORD, DIVINE COUNSELOR)
        # Footers/page numbers are usually yMin > 615
        body_lines = [l for l in lines if l['yMax'] > 100 and l['yMin'] < 615]
        
        # Sort by yMin
        body_lines.sort(key=lambda l: l['yMin'])
        
        left_lines = []
        right_lines = []
        
        def check_block():
            if not left_lines or not right_lines:
                return
            left_bottom = max(left_lines, key=lambda l: l['yMax'])
            right_bottom = max(right_lines, key=lambda l: l['yMax'])
            diff = abs(left_bottom['yMax'] - right_bottom['yMax'])
            if diff > 5.0:
                print(f"Page {i+1}: UNBALANCED BLOCK!")
                print(f"     Left last line (yMax={left_bottom['yMax']:.2f}): {left_bottom['text']}")
                print(f"     Right last line (yMax={right_bottom['yMax']:.2f}): {right_bottom['text']}")
                
                # print context
                print(f"     --- Context (Last 2 lines of Left):")
                sorted_left = sorted(left_lines, key=lambda l: l['yMin'])
                for l in sorted_left[-2:]: print(f"         {l['text']}")
                print(f"     --- Context (Last 2 lines of Right):")
                sorted_right = sorted(right_lines, key=lambda l: l['yMin'])
                for l in sorted_right[-2:]: print(f"         {l['text']}")
                print()

        for line in body_lines:
            # Check if spanning
            if line['xMin'] < 240 and line['xMax'] > 240:
                check_block()
                left_lines = []
                right_lines = []
            elif line['xMax'] < 240:
                left_lines.append(line)
            elif line['xMin'] > 240:
                right_lines.append(line)
                
        # Check last block on page
        check_block()

if __name__ == "__main__":
    check_unbalanced(sys.argv[1])