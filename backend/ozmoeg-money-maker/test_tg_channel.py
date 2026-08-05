#!/usr/bin/env python3
"""Test Telegram channel delivery."""
import yaml, requests, json

# Read config (token is real in file, masked in memory display)
cfg = yaml.safe_load(open('config.yaml'))
token = cfg['telegram']['bot_token']
chat_id = cfg['telegram']['chat_id']

print(f"Testing chat_id: {chat_id}")

# First, try getChat to verify channel exists
url = f"https://api.telegram.org/bot{token}/getChat"
resp = requests.post(url, json={"chat_id": chat_id}, timeout=15)
print(f"getChat result: {json.dumps(resp.json(), indent=2)}")

if resp.json().get('ok'):
    # If channel exists, send test message
    send_url = f"https://api.telegram.org/bot{token}/sendMessage"
    payload = {
        "chat_id": chat_id,
        "text": "🧪 OzMoEg Money Maker — Channel Test\n\n✅ Bot has access to channel\n✅ Config chat_id matches\n⏱ Future alerts will come here.",
        "parse_mode": "HTML"
    }
    send_resp = requests.post(send_url, json=payload, timeout=15)
    print(f"sendMessage result: {json.dumps(send_resp.json(), indent=2)}")
else:
    print("ERROR: Cannot access channel. Check if bot is admin and channel ID is correct.")
