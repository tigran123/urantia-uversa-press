import xml.etree.ElementTree as ET
import sys
import re

html_file = sys.argv[1]
with open(html_file, 'r', encoding='utf-8') as f:
    content = f.read()

content = re.sub(r'\sxmlns="[^"]+"', '', content, count=1)
tree = ET.fromstring(content)
doc = tree.find('.//doc')

lines_with_xmax = []

for page in doc.findall('.//page'):
    for flow in page.findall('.//flow'):
        for block in flow.findall('.//block'):
            for line in block.findall('.//line'):
                words = [w for w in line.findall('.//word') if w.text and w.text.strip()]
                if words:
                    text = " ".join(w.text for w in words)
                    xmax = float(words[-1].get('xMax'))
                    lines_with_xmax.append((text, xmax))

targets = [
    "h the adoration of the perfect creature.", # 6:6
    "sonalities of the universe of universes.", # 6:9
    "nt universe expansion in time and space.", # 6:10
]

for target in targets:
    for text, xmax in lines_with_xmax:
        if text.endswith(target):
            print(f"Target: {target:40} xMax: {xmax}")
