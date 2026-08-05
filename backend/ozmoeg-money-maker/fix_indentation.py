import re

# Read the original file
with open('main.py', 'r') as f:
    content = f.read()

# Fix the indentation issue around line 144
# Find and replace the problematic pattern
# The pattern shows: if _is_us_active_trading_window():
#                 indentation error followed by comment on next line

# Let's read the file and fix it manually
lines = content.split('\n')

# Find the line with "if market == 'us':"
us_block_start = None
for i, line in enumerate(lines):
    if "if market == 'us':" in line:
        us_block_start = i
        break

if us_block_start is not None:
    # Find the problematic block
    for i in range(us_block_start, min(us_block_start + 30, len(lines))):
        if lines[i].strip().startswith("if _is_us_active_trading_window():"):
            # The next line has indentation error
            # Current: "        # Simple override: force run at minute 47 for testing"
            # Should be: "            # Simple override: force run at minute 47 for testing"
            if i + 1 < len(lines):
                # Fix the indentation
                lines[i + 1] = lines[i + 1].replace("        # Simple override", "            # Simple override")
                print(f"Fixed indentation at line {i+2}")
                print(f"Was:        # Simple override")
                print(f"Now:            # Simple override")
                break

# Also fix similar pattern around the next "if minute == 47:"
for i, line in enumerate(lines):
    if "if minute == 47:" in line and "return True" in line:
        # Make sure this is the first occurrence (US mode)
        if i > 0 and "if _is_us_active_trading_window():" in lines[i-1]:
            # Check next line
            if i + 1 < len(lines) and "return minute % 10 == 0" in lines[i + 1]:
                # This is the problematic pattern, fix it
                # The "return minute % 10 == 0" should be at same indentation as "if minute == 47:"
                lines[i + 1] = "            " + lines[i + 1].lstrip()
                print(f"Fixed pattern at line {i+2}")
                print(f"Removed duplicate indentation")

# Write back
with open('main.py', 'w') as f:
    f.write('\n'.join(lines))

print("File fixed successfully")
