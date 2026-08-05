#!/usr/bin/env python3
"""Simplified scan runner using basic system Python"""
import sys
import os
import json
from pathlib import Path

# Try to run the scan with minimal imports
def run_scan_directly():
    try:
        # Import just the essentials
        import yaml
        from pathlib import Path
        
        # Load config directly
        config_path = Path.home() / ".hermes/skills/ozmoeg-money-maker/config.yaml"
        with open(config_path, 'r') as f:
            config = yaml.safe_load(f)
        
        # Basic scan logic - simplified
        print("Config loaded successfully")
        print(f"Scanner market: {config.get('scanner', {}).get('market', 'not set')}")
        print(f"Scan enabled: {config.get('scanner', {}).get('enabled', True)}")
        
        # Check if we have a recent scan
        latest_json = Path.home() / ".hermes/skills/ozmoeg-money-maker/ozmoeg-latest.json"
        if latest_json.exists():
            with open(latest_json, 'r') as f:
                data = json.load(f)
            
            print(f"\nLast scan updated: {data.get('last_updated', 'N/A')}")
            scan_results = data.get('scan_results', [])
            print(f"Last scan found {len(scan_results)} candidates")
            
            # Show current active alerts
            alerts = [r for r in scan_results if r.get('status') == 'ALERT']
            print(f"Active alerts: {len(alerts)}")
            
            for alert in alerts[:3]:  # Show first 3
                ticker = alert.get('ticker', 'N/A')
                changes = alert.get('changes', {})
                change_pct = changes.get('change_pct', 0)
                print(f"  - {ticker}: {change_pct:+.1f}%")
                
                plan = alert.get('plan')
                if plan:
                    print(f"    Entry: ${plan.get('entry', 0):.4f}, Stop: ${plan.get('stop', 0):.4f}, R:R: {plan.get('risk_reward', 0):.2f}")
                    print(f"    Confidence: {plan.get('confidence', 'N/A')}")
            
            return data
        else:
            print("No scan data found")
            return None
            
    except Exception as e:
        print(f"Error: {e}")
        import traceback
        traceback.print_exc()
        return None

if __name__ == '__main__':
    run_scan_directly()