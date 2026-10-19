#!/usr/bin/env python3
"""Wrapper to run OzMoEg Money Maker AU scanner from cron.

Resilience features:
- Always points to the live repo (source of truth).
- Validates the Python interpreter can import critical dependencies.
- Auto-reinstalls requirements if a dependency is missing.
- Propagates the scan exit code so cron failure_streak reports real status.
"""
import os
import subprocess
import sys

mm_dir = r"C:\Users\elsha\Desktop\aeyeing.com\backend\ozmoeg-money-maker"
main = os.path.join(mm_dir, "main.py")
requirements = os.path.join(mm_dir, "requirements.txt")

import glob

# Discover the Hermes-managed Python runtime. The hardcoded path with literal
# asterisks does not exist as a file, so fall back to the newest matching
# Hermes tools Python, then to the cron environment's interpreter.
def _find_hermes_python():
    candidates = sorted(
        glob.glob(r"C:\Users\elsha\AppData\Local\hermes\tools\python-*\python.exe"),
        reverse=True,
    )
    for c in candidates:
        if os.path.exists(c):
            return c
    return sys.executable


hermes_python = _find_hermes_python()
python = hermes_python if os.path.exists(hermes_python) else sys.executable


def _check_imports():
    """Return list of missing critical modules."""
    critical = ["pytz", "yaml", "pandas", "numpy", "requests", "yfinance", "webull"]
    missing = []
    for mod in critical:
        try:
            __import__(mod)
        except Exception:
            missing.append(mod)
    return missing


def _install_requirements():
    subprocess.run([python, "-m", "pip", "install", "-r", requirements], cwd=mm_dir)


# Validate environment and heal if needed.
missing = _check_imports()
if missing:
    print(f"[ozmoeg_au_scan] Missing deps: {missing}. Reinstalling...", file=sys.stderr)
    _install_requirements()
    still_missing = _check_imports()
    if still_missing:
        print(f"[ozmoeg_au_scan] Still missing after reinstall: {still_missing}", file=sys.stderr)
        sys.exit(1)

# Run the scan and propagate the exit code to cron.
args = [python, main, "--mode", "scan", "--market", "au"] + sys.argv[1:]
result = subprocess.run(args, cwd=mm_dir)
sys.exit(result.returncode)
