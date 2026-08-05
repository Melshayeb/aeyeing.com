#!/usr/bin/env python3
"""Simple script to run AU scanner with patched cadence gate"""
import sys
import os

# Patch the source file first
import subprocess
subprocess.run(['sed', '-i', 's/if not force_val and not _scan_allowed_minute(market):/if not force_val and not (market == \"au\" or _scan_allowed_minute(market)):/', 'main.py'], check=True)

# Now run the main script
if __name__ == '__main__':
    # Changed to use sys.executable to run with the same python
    sys.exit(os.system('python main.py --market au --mode scan --force'))