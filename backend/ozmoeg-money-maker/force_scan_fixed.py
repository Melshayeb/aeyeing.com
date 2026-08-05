#!/usr/bin/env python3
"""Manual override for the cadence gating in main.py"""
import argparse
import yaml
from pathlib import Path

def force_run(cwd: str = None):
    """Force run the scanner regardless of cadence"""
    if cwd:
        # Change to the specified directory
        os.chdir(cwd)
    
    # Import and run main with force
    import sys
    sys.argv = ['main.py', '--mode', 'scan', '--force']
    
    # Import main and run directly
    import main
    config = main.load_config()
    main.run_scan(config, argparse.Namespace(force=True, market='us'))

if __name__ == '__main__':
    import os
    force_run('~/.hermes/skills/ozmoeg-money-maker')