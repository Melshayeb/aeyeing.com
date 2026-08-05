#!/usr/bin/env python3
"""
Simple force AU scanner run script.
"""
import sys
import os

# Add current directory to path
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

# Now import and run main
from main import main as run_main

if __name__ == '__main__':
    try:
        sys.argv = ['force_scan_au.py', '--market', 'au', '--mode', 'scan', '--force']
        run_main()
    except Exception as e:
        print(f"Error running main: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)
