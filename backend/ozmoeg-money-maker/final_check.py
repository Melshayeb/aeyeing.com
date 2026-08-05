#!/usr/bin/env python3
import json
from pathlib import Path

with open(Path.home() / 'Desktop/aeyeing.com/ozmoeg-latest.json') as f:
    data = json.load(f)

results = data.get('scan_results', [])
alerts = [r for r in results if r.get('status') == 'ALERT']
skips = [r for r in results if r.get('status') == 'SKIP']

print(f"Total candidates: {len(results)}")
print(f"ALERTS: {len(alerts)}")
print(f"SKIPPED: {len(skips)}")
print(f"Last updated: {data.get('last_updated')}")

# Check if SPRO has the FDA headline (score 4)
for a in alerts:
    if a.get('ticker') == 'SPRO':
        news = a.get('news', {})
        max_score = news.get('max_score', 0)
        print(f"\nSPRO max_score: {max_score}")
        headlines = news.get('headlines', [])
        for h in headlines[:3]:
            print(f"  [{h.get('score')}/5] {h.get('title')[:80]}")