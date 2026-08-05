#!/usr/bin/env python3
"""Quick test to see what Webull login page looks like."""
from playwright.sync_api import sync_playwright
from pathlib import Path

with sync_playwright() as p:
    browser = p.chromium.launch(headless=True)
    page = browser.new_page(viewport={"width": 1280, "height": 800})
    
    page.goto("https://www.webull.com", wait_until="domcontentloaded", timeout=30000)
    page.wait_for_timeout(3000)
    
    # Screenshot
    screenshot = Path.home() / ".hermes/skills/ozmoeg-money-maker/webull_page_test.png"
    page.screenshot(path=str(screenshot), full_page=True)
    print(f"Screenshot saved: {screenshot}")
    
    # Get all buttons/links text
    buttons = page.locator("button, a").all()
    for btn in buttons[:30]:
        text = btn.text_content()
        if text and len(text.strip()) > 0 and len(text.strip()) < 50:
            print(f"Button/Link: '{text.strip()}'")
    
    browser.close()
