#!/usr/bin/env python3
"""Run AU scanner with proper patching"""
import subprocess
import os

# Change to script directory
os.chdir(os.path.dirname(os.path.abspath(__file__)))

# Create a minimal scan runner that loads config and runs scan directly
import sys
sys.path.insert(0, '.')

# Import necessary modules
from kill_switch import load_config
from webull_client import WebullClient
from scanner import SmallCapScanner
from analyzer import TechnicalAnalyzer
from trade_planner import TradePlanner
from news_monitor import NewsMonitor
from tape_analyzer import TapeAnalyzer
from notifier import Notifier
from website_updater import WebsiteUpdater
from state_store import NotificationState
import logging

# Configure basic logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s [%(levelname)s] %(name)s: %(message)s')
logger = logging.getLogger(__name__)

# Load config
config = load_config()

# Set AU market config
config['scanner']['market'] = 'au'
config['webull']['region_code'] = 18
config['webull']['market'] = 'au'

# Determine market status for AU
import pytz
from datetime import datetime as _dt
sydney = pytz.timezone('Australia/Sydney')
now = _dt.now(sydney)
weekday = now.weekday()
minutes = now.hour * 60 + now.minute
if weekday >= 5:
    market_status = 'WEEKEND'
elif 600 <= minutes < 960:
    market_status = 'OPEN'
else:
    market_status = 'CLOSED'
market_time = now.strftime('%I:%M %p AEST')

# Initialize components with AU config
wb = WebullClient(config['webull'])
scanner = SmallCapScanner(wb, config['scanner'], region_code=18, market='au')
ticker_ids = {}

# Get gainers and losers for AU
logger.info("Fetching AU gainers...")
gainers = scanner.get_gainers(count=50)
if not gainers:
    logger.warning("No AU gainers found - API may be down or market closed")
    sys.exit(0)

logger.info(f"Enriching {len(gainers)} AU gainers with quotes...")
gainers = scanner.enrich_gainers_with_quotes(gainers, ticker_ids=ticker_ids)

# Apply filters
logger.info("Filtering candidates...")
candidates = scanner.filter_candidates(gainers, mode='momentum')
logger.info(f"Found {len(candidates)} AU momentum candidates")

print(f"\n=== AU SCANNER RESULTS ===")
print(f"🟢 Market: {config['scanner']['market']}")
print(f"📊 Gainers scanned: {len(gainers)}")
print(f"🎯 Candidates found: {len(candidates)}")
print(f"🏷️ Market status: {market_status} ({market_time})")

if candidates:
    print(f"\n📈 Top candidates:")
    for i, stock in enumerate(candidates[:5]):
        ticker = stock.get('ticker', {}).get('symbol', stock.get('ticker', ''))
        change_pct = stock.get('change', {}).get('changeRatio', 0) * 100 if 'change' in stock else stock.get('changeRatio', 0) * 100
        price = stock.get('price', {}).get('close', 0) if 'price' in stock else stock.get('pprice', 0)
        print(f"   {i+1}. {ticker} — {change_pct:+.1f}% @ ${price:.3f}")

# Note: Not generating alerts or updating website per guidelines for AU
print(f"\nℹ️  AU alerts disabled per guidelines - synthetic quotes only")
print(f"✅ AU scan completed successfully")