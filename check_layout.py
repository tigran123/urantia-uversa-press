import sys

def check_file(filename):
    with open(filename, 'r', encoding='utf-8') as f:
        pages = f.read().split('\x0c')
    
    for p_num, page in enumerate(pages):
        lines = page.split('\n')
        
        if len(lines) < 6: continue
        
        blocks = []
        current_block = []
        
        for i in range(2, len(lines)-2):
            line = lines[i]
            
            gap = line[44:47]
            is_spanning = bool(line.strip()) and bool(gap.strip())
            
            if is_spanning:
                if current_block:
                    blocks.append(current_block)
                    current_block = []
            else:
                current_block.append((i, line))
                
        if current_block:
            blocks.append(current_block)
            
        for block in blocks:
            left_last = -1
            right_last = -1
            for orig_i, line in block:
                if not line.strip(): continue
                left_text = line[:43].strip()
                right_text = line[48:].strip() if len(line) > 48 else ""
                
                # Check for footnotes (they have a line like "___________________" or just numbers)
                if left_text and not left_text.isdigit(): 
                    left_last = orig_i
                if right_text and not right_text.isdigit():
                    right_last = orig_i
                    
            if left_last != -1 and right_last != -1 and left_last != right_last:
                print(f"Page {p_num+1}: Block unbalanced! Left ends at L{left_last}, Right ends at L{right_last} (Diff: {abs(left_last-right_last)})")
                print(f"  Left: {lines[left_last][:43].strip()}")
                print(f"  Right: {lines[right_last][48:].strip() if len(lines[right_last])>48 else ''}")

if __name__ == "__main__":
    check_file(sys.argv[1])