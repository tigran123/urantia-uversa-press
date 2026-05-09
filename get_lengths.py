import re

def get_last_line_length(text):
    # Remove formatting commands
    text = re.sub(r'\\bibemph{([^}]+)}', r'\1', text)
    text = re.sub(r'\\fnc{[^}]+}', '', text)
    text = re.sub(r'\\hyp{}', '-', text)
    
    lines = []
    current_line = ""
    words = text.split()
    for word in words:
        if len(current_line) + len(word) + 1 <= 85: # approximate column width
            current_line += (" " if current_line else "") + word
        else:
            lines.append(current_line)
            current_line = word
    if current_line:
        lines.append(current_line)
    return len(lines[-1]) if lines else 0

with open("tex/p068.tex", "r") as f:
    for line in f:
        m = re.search(r'\\vs p068 (\d+:\d+) (.*)', line)
        if m:
            print(f"{m.group(1)}: {get_last_line_length(m.group(2))}")

