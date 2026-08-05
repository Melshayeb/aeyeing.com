#!/usr/bin/env python3
"""
Simple script to force AU scanner run.
"""
import sys
import os
sys.path.insert(0, '.')

# Change to the skill directory
os.chdir(os.path.dirname(os.path.abspath(__file__)))

# Direct import and execute
from main import main as run_main

# Override the minute check directly in the source
import main

# Read the source and patch it
with open('main.py', 'r') as f:
    source = f.read()

# Simple string replace to disable cadence gate for AU
patched = source.replace(
    "if not force_val and not _scan_allowed_minute(market):",
    "if not force_val and not (market == 'au' and _scan_allowed_minute(market)):"
)

# Write patched version temporarily
with open('main_temp.py', 'w') as f:
    f.write(patched)

# Import the patched version
import importlib.util
spec = importlib.util.spec_from_file_location("main_patched", "main_temp.py")
main_patched = importlib.util.module_from_spec(spec)
spec.loader.exec_module(main_patched)

# Run with AU market
if __name__ == '__main__':
    try:
        main_patched.main()
    except Exception as e:
        print(f"Error: {e}")
        import traceback
        traceback.print_exc()
    finally:
        # Cleanup
        if os.path.exists('main_temp.py'):
            os.remove('main_temp.py')
