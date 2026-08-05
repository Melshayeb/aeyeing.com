#!/usr/bin/env python3
import json
from pathlib import Path

with open(Path.home() / 'Desktop/aeyeing.com/ozmoeg-latest.json') as f:
    data = json.load(f)

results = data.get('scan_results', [])
alerts = [r for r in results if r.get('status') == 'ALERT']
skips = [r for r in results if r.get('status') == 'SKIP']

print(f'Market: {data.get("scan_stats", {}).get("market", "us")}')
print(f'Total scan_results: {len(results)}')
print(f'ALERT count: {len(alerts)}')
print(f'SKIP count: {len(skips)}')
print(f'Last updated: {data.get("last_updated")}')
print()
print('Alert tickers:')
for a in alerts[:15]:
    print(f'  {a.get("ticker")} - {a.get("result")}')