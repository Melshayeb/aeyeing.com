#!/usr/bin/env python3
"""Manual override for the cadence gating in main.py"""
import argparse
import yaml
from pathlib import Path

def force_run(cwd: str = None):
    """Force run the scanner regardless of cadence"""
    if cwd:
        Path(cwd).cwd()
    
    # Import and run main with force
    import sys
    sys.argv = ['main.py', '--mode', 'scan', '--force']
    
    # Re-import main to simulate fresh run
    import importlib
    import main
    importlib.reload(main)
    
    # Run the scanner with force
    main.run_scanner(main.load_config(), force=True)

if __name__ == '__main__':
    # Simple command to run the scanner with force flag
    import subprocess
    subprocess.run(['python', 'main.py', '--mode', 'scan', '--force', '--force'], 
                   cwd='~/.hermes/skills/ozmoeg-money-maker')