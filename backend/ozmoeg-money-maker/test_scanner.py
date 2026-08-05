#!/usr/bin/env python3
"""
OzMoEg Money Maker — Simple Test Script
Test the scanner with a minimal working example.
"""
import sys
import os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from kill_switch import load_config
from webull_client import WebullClient
from scanner import SmallCapScanner

# Load config
config = load_config()
print(f"Config loaded: market={config['scanner']['market']}, region={config['scanner']['region_code']}")

# Initialize Webull client
webull_cfg = dict(config['webull'])
webull_cfg['region_code'] = config['scanner']['region_code']
webull_cfg['market'] = config['scanner']['market']

wb = WebullClient(webull_cfg)

# Test get_gainers directly
print("Testing WebullClient.active_gainer_loser...")
raw_result = wb.active_gainer_loser(direction='gainer', rank_type='1d', num=5)
print(f"Raw result type: {type(raw_result)}")
if isinstance(raw_result, dict) and 'data' in raw_result:
    gainers = raw_result['data']
    print(f"Got {len(gainers)} gainers")
    for g in gainers[:3]:
        print(f"  Ticker: {g.get('symbol')} or {g.get('ticker', {}).get('symbol')}")
else:
    print(f"Unexpected raw result: {raw_result}")

# Test scanner
print("\nTesting SmallCapScanner...")
scanner = SmallCapScanner(wb, config['scanner'])
print(f"Scanner initialized: market={scanner.market}, region={scanner.region_code}")

# Test get_gainers
print("\nTesting scanner.get_gainers...")
gainers = scanner.get_gainers(count=5)
print(f"Got {len(gainers)} gainers")
for g in gainers[:2]:
    print(f"  Ticker: {g.get('symbol', 'N/A')}")
    print(f"  Ticker dict: {g.get('ticker', {})}")

# Test filter_candidates
print("\nTesting scanner.filter_candidates...")
candidates = scanner.filter_candidates(gainers, mode='momentum')
print(f"Filtered to {len(candidates)} candidates")
for c in candidates[:2]:
    print(f"  Symbol: {c.get('symbol', c.get('ticker', {}).get('symbol', 'N/A'))}")
    print(f"  Passed: {c.get('_scan_passed', 'N/A')}")

print("\nTest complete!")