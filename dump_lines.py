import xml.etree.ElementTree as ET
import sys
import re

html_file = sys.argv[1]
page_idx = int(sys.argv[2])
with open(html_file, 'r', encoding='utf-8') as f:
    content = f.read()

content = re.sub(r'\sxmlns="[^"]+"', '', content, count=1)
tree = ET.fromstring(content)
doc = tree.find('.//doc')

page = doc.findall('.//page')[page_idx]
for flow in page.findall('.//flow'):
    for block in flow.findall('.//block'):
        for line in block.findall('.//line'):
            yMax = float(line.get('yMax'))
            words = [w.text for w in line.findall('.//word') if w.text]
            print(f"yMax={yMax:.2f}, xMin={line.get('xMin')}, xMax={line.get('xMax')}: {' '.join(words)}")
