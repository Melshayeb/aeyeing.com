#!/usr/bin/env python3
"""Wrapper to run OzMoEg Money Maker US scanner from cron."""
import os
import subprocess
import sys

mm_dir = r"C:\Users\elsha\Desktop\aeyeing.com\backend\ozmoeg-money-maker"
main = os.path.join(mm_dir, "main.py")

args = [sys.executable, main, "--mode", "scan", "--market", "us"] + sys.argv[1:]
subprocess.run(args, cwd=mm_dir)
