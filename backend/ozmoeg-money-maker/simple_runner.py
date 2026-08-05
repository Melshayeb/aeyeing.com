#!/usr/bin/env python3
"""Direct scan runner that bypasses problematic imports"""
import sys
import os
from pathlib import Path

# Add the current directory to the path
sys.path.insert(0, str(Path(__file__).parent))

# Try a different approach - run main.py as a module directly
if __name__ == '__main__':
    # Import and run main directly
    try:
        # Import the specific function we need
        from main import run_scan
        from kill_switch import load_config
        
        # Create a simple args object
        class SimpleArgs:
            mode = 'scan'
            force = True
            market = 'us'
        
        args = SimpleArgs()
        config = load_config()
        
        print("Running OzMoEg Money Maker scanner...")
        result = run_scan(config, args)
        
        if isinstance(result, dict) and result.get('skipped'):
            print(f"\nScan was skipped: {result.get('reason', 'unknown')}")
        else:
            print(f"\nScan result: {result}")
            
    except Exception as e:
        print(f"Error running scan: {e}")
        import traceback
        traceback.print_exc()