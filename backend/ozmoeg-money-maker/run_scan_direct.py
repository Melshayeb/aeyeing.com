#!/usr/bin/env python3
"""Direct scanner runner for OzMoEg Money Maker"""
import sys
import os
from pathlib import Path

# Add the skill directory to Python path
sys.path.insert(0, str(Path(__file__).parent))

# Import necessary modules
from kill_switch import load_config
from main import run_scan

def main():
    # Load config
    config = load_config()
    
    # Create namespace object with required attributes
    class Args:
        mode = 'scan'
        force = True
        market = 'us'
    
    args = Args()
    
    print("Starting OzMoEg Money Maker scan...")
    
    # Run the scan
    result = run_scan(config, args)
    
    print(f"Scan completed. Result: {result}")
    
    # Check if scan was skipped due to cadence
    if isinstance(result, dict) and result.get('skipped'):
        print(f"Scan skipped: {result.get('reason', 'unknown')}")
        # Try to read the latest JSON to see if any data exists
        latest_json = Path.home() / ".hermes/skills/ozmoeg-money-maker" / "ozmoeg-latest.json"
        if latest_json.exists():
            print(f"Latest scan data exists: {latest_json}")
            import json
            with open(latest_json, 'r') as f:
                data = json.load(f)
                print(f"Scan results count: {len(data.get('scan_results', []))}")
                print(f"Last updated: {data.get('last_updated')}")
                
                # Check for any alerts
                alerts = [r for r in data.get('scan_results', []) if r.get('status') == 'ALERT']
                print(f"Alerts found: {len(alerts)}")
                for alert in alerts[:3]:  # Show first 3
                    print(f"  - {alert.get('ticker')}: {alert.get('changes', {}).get('change_pct', 0):.1f}%")
        else:
            print("No scan data file found")
    else:
        print("Scan appears to have run successfully")

if __name__ == '__main__':
    main()