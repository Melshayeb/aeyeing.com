#!/usr/bin/env python3
"""
Force run AU scanner regardless of cadence.
"""
import sys
sys.path.insert(0, '.')

# Import the entire main module
import importlib.util
spec = importlib.util.spec_from_file_location("main", "main.py")
main_module = importlib.util.module_from_spec(spec)

# Monkey patch _scan_allowed_minute before loading the module
sys.modules['main'] = main_module

# Read the main.py file and exec with the patch
with open('main.py', 'r') as f:
    main_content = f.read()

# Apply the patch to the source code
patched_source = main_content.replace(
    "if not force_val and not _scan_allowed_minute(market):",
    "if not force_val and not _scan_allowed_minute(market) and market != 'au':"
)

exec(patched_source, main_module.__dict__)

# Now run the main function directly with the arguments
if __name__ == '__main__':
    # Simulate command-line arguments
    sys.argv = ['force_scan_au.py', '--market', 'au', '--mode', 'scan']
    try:
        main_module.main()
    except Exception as e:
        print(f"Error: {e}")
        import traceback
        traceback.print_exc()
