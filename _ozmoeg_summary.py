import json
from collections import Counter

with open('ozmoeg-latest.json') as f:
    d = json.load(f)

print('=== OzMoEg Scan Summary ===')
print(f"Last updated: {d.get('last_updated')}")
print(f"Market: {d.get('scan_stats',{}).get('market','?').upper()}")
print(f"Market status: {d.get('market_status','?')}")
print(f"Gainers scanned: {len(d.get('all_gainers',[]))}")
print(f"Losers scanned: {len(d.get('all_losers',[]))}")
print(f"Bouncers: {len(d.get('bounce_results',[]))}")
status=Counter(r.get('status') for r in d.get('scan_results',[]))
print(f"Candidates total: {len(d.get('scan_results',[]))}  by status: {dict(status)}")
for r in d.get('scan_results',[]):
    if r.get('status') == 'SKIP':
        print(f"  {r['ticker']:5} | SKIP      | {r.get('name','')[:30]:30} | reason: {r.get('_scan_reason','')[:60]}")
        continue
    p=r.get('plan') or {}
    print(f"  {r['ticker']:5} | {r.get('status','?'):9} | {r.get('name','')[:30]:30} | ${p.get('entry','-'):>7} | stop ${p.get('stop','-'):>7} | R:R {p.get('risk_reward','-'):>5} | score {r.get('news',{}).get('max_score',0)}")
