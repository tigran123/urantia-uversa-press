import xml.etree.ElementTree as ET
import sys
import re

with open("p009_bbox.html", "r", encoding="utf-8") as f:
    content = f.read()
content = re.sub(r'\sxmlns="[^"]+"', '', content, count=1)
tree = ET.fromstring(content)
doc = tree.find('.//doc')
page = doc.findall('.//page')[7]
for flow in page.findall('.//flow'):
    for block in flow.findall('.//block'):
        for line in block.findall('.//line'):
            if 62 < float(line.get('yMax')) < 64:
                for word in line.findall('.//word'):
                    if word.text and word.text.strip():
                        print(f"{word.text}: {word.get('xMin')} -> {word.get('xMax')}")
