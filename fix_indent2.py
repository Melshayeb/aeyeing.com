import re
from pathlib import Path

p = Path(r'C:\Users\openclaw\Desktop\aeyeing.com\ozmoeg-trader.html')
c = p.read_text(encoding='utf-8')

corrupted = '''            // Tracker "Proposed Entry" = last scan refresh price (e.g., 15 mins ago), not current fetch
                        // This lets you see P&L as if you entered at scan time
                        // Current Price = fresh quote to show movement since last refresh
                        const liveQuote = window._lastLiveQuotes?.[(p.ticker || '').toUpperCase()];
                        const proposedEntry = (liveQuote && liveQuote.p'''

fixed = '''            // Tracker "Proposed Entry" = last scan refresh price (e.g., 15 mins ago), not current fetch
            // This lets you see P&L as if you entered at scan time
            // Current Price = fresh quote to show movement since last refresh
            const liveQuote = window._lastLiveQuotes?.[(p.ticker || '').toUpperCase()];
            const proposedEntry = (liveQuote && liveQuote.p'''

if corrupted in c:
    c = c.replace(corrupted, fixed)
    print('Fixed indentation in tracker section')
else:
    # Check if it's already correct
    if '''Proposed Entry" = last scan refresh''' in c:
        # Check if indentation is already 12 spaces
        lines = [l for l in c.split('\n') if 'Proposed Entry" = last scan refresh' in l]
        if lines:
            print(f'Found existing: {repr(lines[0][:50])}')
    else:
        print('Pattern not found')

p.write_text(c, encoding='utf-8')