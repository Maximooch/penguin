#!/usr/bin/env python3
"""Minimal PyDoll diagnostic script."""

import asyncio
import sys
from pathlib import Path

# Add project root to path
PROJECT_ROOT = str(Path(__file__).resolve().parents[1])
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

print("Step 1: Importing pydoll modules...")
try:
    from pydoll.browser.chrome import Chrome
    from pydoll.browser.options import Options
    print("✓ Imports successful")
except Exception as e:
    print(f"✗ Import failed: {e}")
    sys.exit(1)

print("\nStep 2: Creating browser options...")
try:
    options = Options()
    options.add_argument('--headless=new')
    chrome_path = '/Applications/Google Chrome.app/Contents/MacOS/Google Chrome'
    options.binary_location = chrome_path
    print(f"✓ Options created, Chrome path: {chrome_path}")
except Exception as e:
    print(f"✗ Options failed: {e}")
    sys.exit(1)

print("\nStep 3: Creating Chrome instance...")
try:
    browser = Chrome(options=options)
    print("✓ Chrome instance created")
except Exception as e:
    print(f"✗ Chrome creation failed: {e}")
    import traceback
    traceback.print_exc()
    sys.exit(1)

print("\nStep 4: Starting browser...")
async def test_start():
    try:
        await browser.start()
        print("✓ Browser started successfully")
        
        page = await browser.get_page()
        print(f"✓ Got page: {page}")
        
        await browser.stop()
        print("✓ Browser stopped")
        return True
    except Exception as e:
        print(f"✗ Browser start failed: {e}")
        import traceback
        traceback.print_exc()
        return False

if __name__ == "__main__":
    result = asyncio.run(test_start())
    sys.exit(0 if result else 1)
