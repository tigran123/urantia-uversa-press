import re

with open("tex/p068.tex", "r") as f:
    for line in f:
        m = re.search(r'\\vs p068 (\d+:\d+) (.*)', line)
        if m:
            para = m.group(1)
            text = m.group(2).strip()
            # print last 40 characters to visually see the length
            print(f"{para}: {text[-40:]}")

