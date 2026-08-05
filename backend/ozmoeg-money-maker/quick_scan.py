#!/usr/bin/env python3
"""Quick manual scanner run for OzMoEg Money Maker"""
import json
from pathlib import Path
from kill_switch import load_config
from main import run_scan

class SimpleArgs:
    mode = 'scan'
    force = True
    market = 'us'

def main():
    config = load_config()
    args = SimpleArgs()
    
    print("Running OzMoEg Money Maker scanner for US market...")
    
    result = run_scan(config, args)
    
    if isinstance(result, dict) and result.get('skipped'):
        reason = result.get('reason', 'unknown')
        print(f"SCAN SKIPPED: {reason}")
        
        # Load latest scan results to show current status
        latest_json = Path.home() / ".hermes/skills/ozmoeg-money-maker" / "ozmoeg-latest.json"
        if latest_json.exists():
            with open(latest_json, 'r') as f:
                data = json.load(f)
            
            scan_results = data.get('scan_results', [])
            pre_market_results = data.get('pre_market_results', [])
            
            print(f"\nLATEST SCAN STATUS:")
            print(f"- Last updated: {data.get('last_updated', 'N/A')}")
            print(f"- Candidates found: {len(scan_results)}")
            print(f"- Pre-market results: {len(pre_market_results)}")
            
            # Show top candidates
            if scan_results:
                print(f"\nTOP CURRENT CANDIDATES:")
                for i, candidate in enumerate(scan_results[:5]):
                    ticker = candidate.get('ticker', 'N/A')
                    changes = candidate.get('changes', {})
                    change_pct = changes.get('change_pct', 0)
                    status = candidate.get('status', 'N/A')
                    print(f"  {i+1}. {ticker} - {change_pct:+.1f}% (Status: {status})")
                    
                    # Show plan if available
                    plan = candidate.get('plan')
                    if plan:
                        entry = plan.get('entry', 0)
                        stop = plan.get('stop', 0)
                        r_r = plan.get('risk_reward', 0)
                        print(f"     Entry: ${entry:.4f}, Stop: ${stop:.4f}, R:R: {r_r:.2f}")
            
            # Check for alerts (non-duplicate ones)
            alerts = [r for r in scan_results if r.get('status') == 'ALERT']
            print(f"\nCURRENT ALERTS: {len(alerts)}")
            
            return result
        else:
            print("No scan data file found")
    else:
        print("Scan completed successfully")
        return result

if __name__ == '__main__':
    main()