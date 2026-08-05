# Read the file
with open('main.py', 'r') as f:
    lines = f.readlines()

# Fix the problematic section (lines around 144-152)
# The pattern should be:
# if _is_us_active_trading_window():
#     # comment
#     if minute == 47:
#         return True
#     return minute % 10 == 0
# # comment
# if minute == 47:
#     return True
# return minute % 15 == 0

# Find the problematic section
in_au_block = False
in_us_block = False
saw_us_block_start = False

for i, line in enumerate(lines):
    # Look for the start of the US block
    if "if market == 'us':" in line:
        in_us_block = True
        saw_us_block_start = True
        continue
    
    if in_us_block:
        # Look for the _is_us_active_trading_window() block
        if "if _is_us_active_trading_window():" in line:
            # The next line should have proper indentation if minute == 47
            if i + 1 < len(lines) and "if minute == 47:" in lines[i + 1]:
                # Fix the indentation of the next two lines
                lines[i + 1] = "        " + lines[i + 1].lstrip()  # if minute == 47:
                if i + 2 < len(lines) and "return True" in lines[i + 2]:
                    lines[i + 2] = "            " + lines[i + 2].lstrip()  # return True
                if i + 3 < len(lines) and "return minute % 10 == 0" in lines[i + 3]:
                    lines[i + 3] = "            " + lines[i + 3].lstrip()  # return minute % 10 == 0
            continue
        
        # Look for the second "if minute == 47:" block
        if "if minute == 47:" in line and not "if _is_us_active_trading_window()" in line:
            # This is the second occurrence, fix indentation
            lines[i] = "        " + line.lstrip()  # if minute == 47:
            if i + 1 < len(lines) and "return True" in lines[i + 1]:
                lines[i + 1] = "            " + lines[i + 1].lstrip()  # return True
            continue
            
        # Look for the return minute % 15 == 0
        if "return minute % 15 == 0" in line:
            lines[i] = "        " + line.lstrip()
            continue
        
        # Look for the duplicate comment
        if "# Simple override: force run at minute 47 for testing" in line:
            # Check if this is the duplicate comment (not the one after if _is_us_active_trading_window)
            if i > 0 and "if _is_us_active_trading_window():" not in lines[i-1]:
                # This is the duplicate comment, fix indentation
                lines[i] = "        " + line.lstrip()
            continue

# Write back the file
with open('main.py', 'w') as f:
    f.writelines(lines)

print("Fixed indentation issues in main.py")
