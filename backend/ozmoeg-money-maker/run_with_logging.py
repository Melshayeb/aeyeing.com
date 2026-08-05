#!/usr/bin/env python3
"""Run the OzMoEg scanner with logging to capture full output for analysis"""
import sys
import os
import logging
from pathlib import Path

# Configure logging to capture all stdout and stderr
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s,%(msecs)03d [%(levelname)s] %(name)s: %(message)s',
    datefmt='%Y-%m-%d %H:%M:%S',
    handlers=[
        logging.FileHandler('scan_runner.log'),
        logging.StreamHandler()
    ]
)

# Also configure stdout to be captured by logging
import io
import contextlib

# Redirect stdout and stderr to logging
old_stdout = sys.stdout
old_stderr = sys.stderr
sys.stdout = logging.getLogger().handlers[-1].stream
sys.stderr = logging.getLogger().handlers[-1].stream

# Import and run the scan
if __name__ == '__main__':
    try:
        from main import run_scan
        from kill_switch import load_config
        
        # Create args to force the scan
        class SimpleArgs:
            mode = 'scan'
            force = True
            market = 'us'
            background = False
            notify_on_complete = False
            watch_patterns = None
            timeout = None
            workdir = None
            pty = False
            
        args = SimpleArgs()
        config = load_config()
        
        print("Running OzMoEg Money Maker scanner with logging enabled...")
        result = run_scan(config, args)
        
        if isinstance(result, dict) and result.get('skipped'):
            print(f"\nScan was skipped: {result.get('reason', 'unknown')}")
        else:
            print(f"\nScan completed with result: {result}")
            
    except Exception as e:
        print(f"Error running scan: {e}")
        import traceback
        traceback.print_exc()
    finally:
        # Restore stdout and stderr
        sys.stdout = old_stdout
        sys.stderr = old_stderr