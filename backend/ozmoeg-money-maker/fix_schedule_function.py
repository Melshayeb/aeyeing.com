import re

# Read the file
with open('main.py', 'r') as f:
    content = f.read()

# Pattern to match the problematic section in _scan_allowed_minute
# We're looking for the US block with the indentation issue
pattern = r'''def _scan_allowed_minute\(market: str\) -> bool:
    \"\"\"
    Return True only when the current wall-clock minute aligns with the allowed
    cadence for this market\.  Called after the cron job fires every 5 minutes\.

    US outside active window: every 15 minutes \(0,15,30,45\)\.\n    US inside active window  : every 10 minutes \(0,10,20,30,40,50\)\.\n    AU                       : every 30 minutes \(0,30\)\.\n    \"\"\"
    from datetime import datetime as _dt
    import pytz
    sydney_now = _dt\.now\(pytz\.timezone\(\'Australia/Sydney\'\)\)
    minute = sydney_now\.minute
    if market == \'au\':
        return minute in \{0, 30\}
    if market == \'us\':
            if _is_us_active_trading_window\(\):
                            # Simple override: force run at minute 47 for testing
            if minute == 47:
                return True
            return minute % 10 == 0
            # Simple override: force run at minute 47 for testing
            if minute == 47:
                return True
            return minute % 15 == 0
    return False'''

# Correct version
replacement = '''def _scan_allowed_minute(market: str) -> bool:
    """
    Return True only when the current wall-clock minute aligns with the allowed
    cadence for this market.  Called after the cron job fires every 5 minutes.

    US outside active window: every 15 minutes (0,15,30,45).
    US inside active window  : every 10 minutes (0,10,20,30,40,50).
    AU                       : every 30 minutes (0,30).
    """
    from datetime import datetime as _dt
    import pytz
    sydney_now = _dt.now(pytz.timezone('Australia/Sydney'))
    minute = sydney_now.minute
    if market == 'au':
        return minute in {0, 30}
    if market == 'us':
        if _is_us_active_trading_window():
            # Simple override: force run at minute 47 for testing
            if minute == 47:
                return True
            return minute % 10 == 0
        # Simple override: force run at minute 47 for testing
        if minute == 47:
            return True
        return minute % 15 == 0
    return False'''

# Fix the specific problematic lines
lines = content.split('\n')
for i, line in enumerate(lines):
    if "if _is_us_active_trading_window():" in line:
        # Fix the comment line and all following indentation
        if i+1 < len(lines) and "# Simple override: force run at minute 47 for testing" in lines[i+1]:
            lines[i+1] = "            " + lines[i+1].lstrip() if len(lines[i+1]) > 12 else lines[i+1]
        if i+2 < len(lines) and lines[i+2].strip().startswith("if minute == 47:"):
            lines[i+2] = "            " + lines[i+2].lstrip()
        if i+3 < len(lines) and lines[i+3].strip().startswith("return True"):
            lines[i+3] = "                " + lines[i+3].lstrip()
        if i+4 < len(lines) and lines[i+4].strip().startswith("return minute % 10 == 0"):
            lines[i+4] = "            " + lines[i+4].lstrip()
        
        # Fix duplicate comment
        for j in range(i+5, min(len(lines), i+25)):
            if "# Simple override: force run at minute 47 for testing" in lines[j]:
                # Check if it's the duplicate (after _is_us_active_trading_window block)
                if j > i+5 and "return minute % 10 == 0" in lines[j-1]:
                    lines[j] = "        " + lines[j].lstrip()
            if lines[j].strip() == "if minute == 47:" and j > i:
                lines[j] = "        " + lines[j].lstrip()
            if lines[j].strip() == "return True" and j > 0 and lines[j-1].strip() == "if minute == 47:":
                lines[j] = "            " + lines[j].lstrip()
            if lines[j].strip() == "return minute % 15 == 0" and "return minute % 10 == 0" in lines[j-1]:
                lines[j] = "        " + lines[j].lstrip()
        break

# Write back
with open('main.py', 'w') as f:
    f.write('\n'.join(lines))

print("Fixed indentation in _scan_allowed_minute function")
