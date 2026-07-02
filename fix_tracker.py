import re
from pathlib import Path

p = Path(r'C:\Users\openclaw\Desktop\aeyeing.com\ozmoeg-trader.html')
c = p.read_text(encoding='utf-8')

# 1. Fix updateTrackerCurrentPrice to accept forceFresh parameter
old_func = '''async function updateTrackerCurrentPrice(ticker, entry, t1, t2, t3, shareQty) {
            const curEl = document.getElementById('perf-current');
            const subEl = document.getElementById('perf-current-sub');
            const pnlEl = document.getElementById('perf-pnl');
            const pnlSub = document.getElementById('perf-pnl-sub');
            if (curEl) { curEl.textContent = '—'; curEl.className = 'value'; }
            if (subEl) subEl.textContent = 'Fetching price…';
            if (pnlEl) { pnlEl.textContent = '—'; pnlEl.className = 'value'; }
            if (pnlSub) pnlSub.textContent = 'Waiting for price';

            const resolved = await resolveCurrentPrice(ticker);'''

new_func = '''async function updateTrackerCurrentPrice(ticker, entry, t1, t2, t3, shareQty, forceFresh = false) {
            const curEl = document.getElementById('perf-current');
            const subEl = document.getElementById('perf-current-sub');
            const pnlEl = document.getElementById('perf-pnl');
            const pnlSub = document.getElementById('perf-pnl-sub');
            if (curEl) { curEl.textContent = '—'; curEl.className = 'value'; }
            if (subEl) subEl.textContent = 'Fetching price…';
            if (pnlEl) { pnlEl.textContent = '—'; pnlEl.className = 'value'; }
            if (pnlSub) pnlSub.textContent = 'Waiting for price';

            // If forceFresh, skip JSON cache and go directly to Yahoo for fresh price
            let resolved;
            if (forceFresh) {
                const freshPrice = await getFreshPrice(ticker);
                if (freshPrice && freshPrice.price > 0) {
                    resolved = freshPrice;
                } else {
                    resolved = { price: null, source: null, timestamp: null };
                }
            } else {
                resolved = await resolveCurrentPrice(ticker);
            }'''

if old_func in c:
    c = c.replace(old_func, new_func)
    print('Updated updateTrackerCurrentPrice signature')
else:
    print('updateTrackerCurrentPrice pattern not found')

# Also need to add getFreshPrice function if not present
if 'async function getFreshPrice' not in c:
    # Find location to insert after fetchPublicQuote
    insert_marker = '        }\n\n        function isExtendedHoursSession'
    insert_code = '''        }

        // Get truly fresh price - bypasses JSON cache entirely
        async function getFreshPrice(ticker) {
            // Skip the JSON cache; go directly to Yahoo or another source
            let price = await fetchPublicQuote(ticker);
            if (price) return { price, source: 'live', timestamp: new Date() };
            return null;
        }

        function isExtendedHoursSession'''
    if insert_marker in c:
        c = c.replace(insert_marker, insert_code)
        print('Added getFreshPrice function')
    else:
        print('Could not find insertion point for getFreshPrice')

p.write_text(c, encoding='utf-8')
print('Done')