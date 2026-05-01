#!/usr/bin/env python3.12

import re
import sys

def fix_list_spacing(filename):
    with open(filename, 'r', encoding='utf-8') as f:
        content = f.read()

    # Regex Breakdown:
    # ^                               : Start of the line (multiline mode)
    # (?![ \t]*\\pc\b)                : Negative lookahead: Do NOT match if line starts with optional spaces followed by \pc
    # (?=.*\\vs.*\\ublistelem\{1\.\}) : Positive lookahead: MUST contain \vs followed later by \ublistelem{1.}
    
    pattern = re.compile(r'^(?![ \t]*\\pc\b)(?=.*\\vs.*\\ublistelem\{1\.\})', re.MULTILINE)
    
    # subn returns a tuple: (new_string, number_of_replacements)
    fixed_content, num_subs = pattern.subn(r'\\pc ', content)

    if num_subs > 0:
        with open(filename, 'w', encoding='utf-8') as f:
            f.write(fixed_content)
        print(f"Processed '{filename}': Inserted \\pc in {num_subs} locations.")
    else:
        print(f"Processed '{filename}': No changes needed.")

if __name__ == '__main__':
    if len(sys.argv) > 1:
        for file in sys.argv[1:]:
            fix_list_spacing(file)
    else:
        print("Usage: python fix_spacing.py <filename> [<filename2> ...]")
