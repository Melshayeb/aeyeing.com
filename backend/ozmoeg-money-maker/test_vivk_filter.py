import sys, os, re
sys.path.insert(0, os.path.expanduser('~/.hermes/skills/ozmoeg-money-maker'))
from scanner import SmallCapScanner
from kill_switch import load_config
from webull_client import WebullClient

cfg = load_config()
cfg['market'] = 'us'
cfg['region_code'] = 6

wb = WebullClient(cfg)
sc = SmallCapScanner(wb, cfg)

print('is_sydney_active_window:', sc._is_sydney_active_window())
print('detected_market_status:', sc._detect_market_status())
print('is_extended_hours_raw:', sc._detect_market_status() in ('PRE-MARKET','AFTER-HOURS','WEEKEND','CLOSED'))

stock = {
    'ticker': {'tickerId': 123, 'symbol': 'VIVK', 'name': 'Vivakor', 'price': 6.79, 'close': 1.73, 'changeRatio': 3.92485549132948, 'volume': 65723489, 'marketValue': 3107511.4, 'outstandingShares': 404703},
    'values': {}
}

# Simulate Sydney active window by overriding
class SydneyScanner(SmallCapScanner):
    def _is_sydney_active_window(self):
        return True
    def _detect_market_status(self):
        return 'OPEN'

sc2 = SydneyScanner(wb, cfg)
print('\nWith Sydney active window override:')
print('is_sydney_active_window:', sc2._is_sydney_active_window())
print('detected_market_status:', sc2._detect_market_status())

passed, reason = sc2._passes_filter_with_reason(stock)
print('passed:', passed, 'reason:', reason)
