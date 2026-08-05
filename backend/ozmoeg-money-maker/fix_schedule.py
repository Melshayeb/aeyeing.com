# Read the file with proper line endings
with open('main.py', 'r', newline='') as f:
    lines = f.readlines()

# Fix the problematic section (lines around 144-152)
# The correct logic should be:
# if _is_us_active_trading_window():
#     # Simple override: force run at minute 47 for testing
#     if minute == 47:
#         return True
#     return minute % 10 == 0
# # Simple override: force run at minute 47 for testing
# if minute == 47:
#     return True
# return minute % 15 == 0

# Find the start of the function
for i, line in enumerate(lines):
    if "def _should_scan_now(" in line:
        # Find the problematic section in the US block
        for j in range(i, min(i+30, len(lines))):
            if "if market == 'us':" in lines[j]:
                # Find the _is_us_active_trading_window block
                for k in range(j, min(j+20, len(lines))):
                    if "if _is_us_active_trading_window():" in lines[k]:
                        # Fix the indentation
                        # Line k: if _is_us_active_trading_window():
                        # Line k+1: should be properly indented comment
                        if k+1 < len(lines):
                            lines[k+1] = "            " + lines[k+1].lstrip()
                        # Line k+2: should be if minute == 47:
                        if k+2 < len(lines):
                            lines[k+2] = "            " + lines[k+2].lstrip()
                        # Line k+3: should be return True
                        if k+3 < len(lines):
                            lines[k+3] = "                " + lines[k+3].lstrip()
                        # Line k+4: should be return minute % 10 == 0
                        if k+4 < len(lines):
                            lines[k+4] = "            " + lines[k+4].lstrip()
                        
                        # Find the duplicate "if minute == 47:" after this
                        for m in range(k+5, min(k+15, len(lines))):
                            if "if minute == 47:" in lines[m] and "if _is_us_active_trading_window()" not in lines[m-1]:
                                lines[m] = "        " + lines[m].lstrip()
                                if m+1 < len(lines) and "return True" in lines[m+1]:
                                    lines[m+1] = "            " + lines[m+1].lstrip()
                                break
                        
                        # Fix the return minute % 15 line
                        for n in range(k+10, min(k+20, len(lines))):
                            if "return minute % 15 == 0" in lines[n]:
                                lines[n] = "        " + lines[n].lstrip()
                                break
                        break
                break
        break

# Write back with proper line endings
with open('main.py', 'w', newline='') as f:
    f.writelines(lines)

print("Fixed schedule function indentation in main.py")
