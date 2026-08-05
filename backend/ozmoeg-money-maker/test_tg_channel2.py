#!/usr/bin/env python3
"""Test Telegram channel delivery — attempt direct message."""
import yaml, requests, json

cfg = yaml.safe_load(open('config.yaml'))
token = cfg['telegram']['bot_token']
chat_id = "-1003734081914"  # The channel ID you confirmed

print(f"Token length: {len(token)}")
print(f"Chat ID: {chat_id}")

# Try getChatMember to verify bot status
url = f"https://api.telegram.org/bot{token}/getChatMember"
payload = {"chat_id": chat_id, "user_id": 8985575808}
resp = requests.post(url, json=payload, timeout=15)
print(f"getChatMember result: {json.dumps(resp.json(), indent=2)}")

# If that fails, try sending a simple text message directly
if not resp.json().get('ok'):
    print("\nTrying sendMessage anyway...")
    send_url = f"https://api.telegram.org/bot{token}/sendMessage"
    send_payload = {
        "chat_id": chat_id,
        "text": "Test message from OzMoEg Bot"
    }
    send_resp = requests.post(send_url, json=send_payload, timeout=15)
    print(f"sendMessage result: {json.dumps(send_resp.json(), indent=2)}")
