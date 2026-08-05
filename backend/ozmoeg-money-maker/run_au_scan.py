#!/usr/bin/env python3
"""
Simple script to run AU scanner by calling main's internal functions directly
"""
import sys
import os

# Add current directory to path
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

# Now import the modules we need
from kill_switch import load_config
from main import main as run_main_with_args

if __name__ == '__main__':
    try:
        # Temporarily replace sys.argv to simulate command line arguments
        original_argv = sys.argv
        sys.argv = ['run_au_scan.py', '--market', 'au', '--mode', 'scan', '--force']
        
        # Import main module
        import importlib
        main_spec = importlib.util.spec_from_file_location("main", "main.py")
        main_module = importlib.util.module_from_spec(main_spec)
        main_spec.loader.exec_module(main_module)
        
        # Load config and create args
        config = main_module.load_config()
        
        # Create args object with the right attributes
        class Args:
            mode = 'scan'
            market = 'au'
            force = True
            kill_status = False
        
        args = Args()
        
        # Run scan directly
        result = main_module.run_scan(config, args)
        
        print(f"\n=== SCAN SUMMARY ===")
        print(f"🟢 Market: {result['scan_stats']['market']}")
        print(f"📊 Gainers scanned: {result['scan_stats']['gainers_scanned']}")
        print(f"🎯 Candidates found: {result['scan_stats']['candidates_found']}")
        print(f"⚡ Alerts generated: {result['scan_stats']['alerts_sent']}")
        print(f"📲 Telegram alerts sent: {result['scan_stats'].get('telegram_sent', 0)}")
        print(f"📈 Top tickers: {', '.join(result['scan_stats']['alert_tickers'][:3]) if result['scan_stats']['alert_tickers'] else 'None'}")
        print(f"🌐 Website updated: {'Yes' if main_module.update_website(main_module.load_config(), result['scan_results'], result['active_plan'], result['scan_stats']) else 'No'}")
        print(f"⏰ Market status: {result['scan_stats']['market_status']} ({result['scan_stats']['market_time']})")
        
        # Restore original argv
        sys.argv = original_argv
        
    except Exception as e:
        print(f"Error running AU scanner: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)