import sys

fixes = {
    "0:3": " advanced social development on Urantia.",
    "1:7": " from the realization of utopian dreams.",
    "2:11": "ation unfailingly destroys civilization.",
    "4:2": "nd therefore always shrouded in mystery.",
    "6:1": "ratio underlies all social civilization.",
    "6:2": "eisure to build a cultural civilization.",
    "6:8": "ys regarded twins as omens of good luck.",
    "6:9": "maternal affection is too strong.",
    "6:10": "twenty\\hyp{}five per cent of all babies.",
}

def apply_fixes():
    with open("tex/p068.tex", "r", encoding="utf-8") as f:
        lines = f.readlines()

    # remove all existing \plusone just in case
    for i in range(len(lines)):
        lines[i] = lines[i].replace(r"\plusone", "")

    for p_num, text in fixes.items():
        found = False
        text_clean = text.replace("'", "’").replace("-", "\\hyp{}")
        for i, line in enumerate(lines):
            if f"\\vs p068 {p_num} " in line or f"\\vs p068 {p_num}\n" in line:
                if text_clean in line:
                    lines[i] = line.rstrip() + "\\plusone\n"
                    print(f"Applied fix for {p_num}")
                    found = True
                    break
        if not found:
            print(f"ERROR: Could not find paragraph {p_num} with text '{text}'")

    with open("tex/p068.tex", "w", encoding="utf-8") as f:
        f.writelines(lines)

if __name__ == "__main__":
    apply_fixes()
