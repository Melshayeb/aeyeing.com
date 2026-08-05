#!/usr/bin/env python3
"""
OzMoEg Money Maker — Webull Browser Authentication
Uses Playwright to log into app.webull.com and extract session tokens.
Saves credentials so the API client can reuse them without re-logging in.
"""
import json
import logging
import time
from pathlib import Path
from typing import Dict, Optional
from playwright.sync_api import sync_playwright, TimeoutError as PlaywrightTimeout

logger = logging.getLogger(__name__)

WEBULL_LOGIN_URL = "https://app.webull.com/watchlist"
COOKIE_NAMES = ["accessToken", "refreshToken", "uuid", "account_id", "accountType"]
TOKEN_FILE = Path.home() / ".hermes/skills/ozmoeg-money-maker/.webull_tokens.json"

def extract_tokens_from_cookies(cookies: list) -> Dict[str, str]:
    """Extract relevant tokens from browser cookies."""
    tokens = {}
    for cookie in cookies:
        name = cookie.get("name", "")
        if name in COOKIE_NAMES or "token" in name.lower() or "uuid" in name.lower():
            tokens[name] = cookie.get("value", "")
    return tokens

def save_tokens(tokens: Dict[str, str]):
    """Save extracted tokens to local file."""
    TOKEN_FILE.parent.mkdir(parents=True, exist_ok=True)
    with open(TOKEN_FILE, "w", encoding="utf-8") as f:
        json.dump(tokens, f, indent=2)
    logger.info("Tokens saved to %s", TOKEN_FILE)

def load_tokens() -> Optional[Dict[str, str]]:
    """Load previously saved tokens."""
    if TOKEN_FILE.exists():
        with open(TOKEN_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    return None

def authenticate_webull(
    email: str,
    password: str,
    mfa: str = "",
    headless: bool = True,
    timeout: int = 60
) -> Dict[str, str]:
    """
    Launch browser, log into Webull, and extract session tokens.
    
    Args:
        email: Webull login email
        password: Webull login password
        mfa: 6-digit MFA code (if 2FA enabled)
        headless: Run browser invisibly if True
        timeout: Max seconds to wait for login
    
    Returns:
        Dict with accessToken, refreshToken, uuid, etc.
    """
    tokens = {}
    
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=headless)
        context = browser.new_context(
            viewport={"width": 1280, "height": 800},
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
        )
        page = context.new_page()
        
        try:
            logger.info("Navigating to %s", WEBULL_LOGIN_URL)
            page.goto(WEBULL_LOGIN_URL, wait_until="domcontentloaded", timeout=timeout*1000)
            
            # Handle geo-location popup if present
            logger.info("Dismissing geo popup...")
            try:
                # Look for "No" button or close on geo prompt
                no_btn = page.locator("text=No, thanks >> visible=true, text=No >> visible=true, button:has-text('No') >> visible=true").first
                if no_btn.is_visible(timeout=3000):
                    no_btn.click()
                    logger.info("Clicked 'No' on geo prompt")
                    time.sleep(1)
            except:
                pass  # No geo prompt
            
            # Handle cookie consent if present
            try:
                cookie_accept = page.locator("button:has-text('Accept'), button:has-text('Agree'), button:has-text('OK'), .cookie-accept").first
                if cookie_accept.is_visible(timeout=3000):
                    cookie_accept.click()
                    time.sleep(1)
            except:
                pass
            
            # Look for login button in header/navbar
            logger.info("Looking for login button...")
            # Webull header often has login in top right
            login_selectors = [
                "header >> text=Log in",
                "nav >> text=Log in",
                ".header >> text=Log in",
                "[class*='header'] >> text=Log in",
                "text=Log in >> visible=true",
                "a:has-text('Log in') >> visible=true",
                "button:has-text('Log in') >> visible=true"
            ]
            
            login_clicked = False
            for selector in login_selectors:
                try:
                    loc = page.locator(selector).first
                    if loc.is_visible(timeout=2000):
                        logger.info("Found login button with: %s", selector)
                        loc.click()
                        login_clicked = True
                        break
                except:
                    continue
            
            if not login_clicked:
                # Fallback: scroll down to find login button
                logger.info("Scrolling to find login button...")
                page.evaluate("window.scrollBy(0, 300)")
                time.sleep(1)
                for selector in login_selectors:
                    try:
                        loc = page.locator(selector).first
                        if loc.is_visible(timeout=2000):
                            loc.click()
                            login_clicked = True
                            break
                    except:
                        continue
            
            if not login_clicked:
                raise Exception("Could not find login button")
            
            time.sleep(2)  # Wait for login modal to appear
            
            # Wait for email input
            logger.info("Waiting for email input...")
            page.wait_for_selector("input[type='email'], input[placeholder*='email' i], input[name='account']", timeout=15000)
            
            # Fill credentials
            email_input = page.locator("input[type='email'], input[placeholder*='email' i], input[name='account']").first
            password_input = page.locator("input[type='password']").first
            
            email_input.fill(email)
            password_input.fill(password)
            
            # Click login submit
            logger.info("Submitting login...")
            page.click("button[type='submit'], .login-btn, button:has-text('Log in'), button:has-text('Sign in')")
            
            # Wait for MFA if needed
            if mfa:
                logger.info("Waiting for MFA input...")
                page.wait_for_selector("input[type='text'], input[placeholder*='code' i]", timeout=15000)
                mfa_input = page.locator("input[type='text'], input[placeholder*='code' i]").first
                mfa_input.fill(mfa)
                page.click("button[type='submit'], .confirm-btn")
            
            # Wait for dashboard to load (indicates successful login)
            logger.info("Waiting for dashboard...")
            page.wait_for_selector(".dashboard, .portfolio, .watchlist, nav, [class*='home']", timeout=30000)
            time.sleep(3)  # Allow cookies to settle
            
            # Extract cookies
            cookies = context.cookies()
            tokens = extract_tokens_from_cookies(cookies)
            
            # Also check localStorage / sessionStorage for tokens
            local_storage = page.evaluate("() => JSON.stringify(localStorage)")
            if local_storage:
                try:
                    ls_data = json.loads(local_storage)
                    for key, value in ls_data.items():
                        if any(t in key.lower() for t in ["token", "uuid", "account"]):
                            tokens[key] = value
                except json.JSONDecodeError:
                    pass
            
            if tokens:
                logger.info("Extracted %d tokens: %s", len(tokens), list(tokens.keys()))
                save_tokens(tokens)
            else:
                logger.warning("No tokens found in cookies or storage")
                # Fallback: screenshot for debugging
                screenshot_path = TOKEN_FILE.parent / "webull_login_debug.png"
                page.screenshot(path=str(screenshot_path))
                logger.info("Debug screenshot saved to %s", screenshot_path)
                
        except PlaywrightTimeout as e:
            logger.error("Timeout during Webull login: %s", e)
            screenshot_path = TOKEN_FILE.parent / "webull_timeout.png"
            page.screenshot(path=str(screenshot_path))
            logger.info("Timeout screenshot saved to %s", screenshot_path)
        except Exception as e:
            logger.error("Error during Webull authentication: %s", e)
        finally:
            browser.close()
    
    return tokens

def update_config_with_token(config_path: str, tokens: Dict[str, str]):
    """Update config.yaml with extracted access_token."""
    import yaml
    
    with open(config_path, "r", encoding="utf-8") as f:
        config = yaml.safe_load(f)
    
    if "accessToken" in tokens:
        config["webull"]["access_token"] = tokens["accessToken"]
        logger.info("Updated config with access_token")
    if "uuid" in tokens:
        config["webull"]["account_id"] = tokens["uuid"]
        logger.info("Updated config with account_id (uuid)")
    
    with open(config_path, "w", encoding="utf-8") as f:
        yaml.dump(config, f, default_flow_style=False, sort_keys=False)
    logger.info("Config saved to %s", config_path)

def main():
    """CLI entry point for manual authentication."""
    import argparse
    
    parser = argparse.ArgumentParser(description="Webull Browser Authentication")
    parser.add_argument("--email", default="elshayeb@gmail.com", help="Webull email")
    parser.add_argument("--password", required=True, help="Webull password")
    parser.add_argument("--mfa", default="", help="6-digit MFA code")
    parser.add_argument("--visible", action="store_true", help="Show browser window")
    parser.add_argument("--config", default=None, help="Path to config.yaml")
    args = parser.parse_args()
    
    logging.basicConfig(level=logging.INFO)
    
    tokens = authenticate_webull(
        email=args.email,
        password=args.password,
        mfa=args.mfa,
        headless=not args.visible
    )
    
    if tokens:
        print("\n✅ Authentication successful!")
        print(f"Tokens saved to: {TOKEN_FILE}")
        for key in tokens:
            print(f"  - {key}: {'*' * min(len(tokens[key]), 10)}...")
        
        if args.config:
            update_config_with_token(args.config, tokens)
            print(f"Config updated: {args.config}")
    else:
        print("\n❌ Authentication failed. Check screenshots in skill directory.")

if __name__ == "__main__":
    main()
