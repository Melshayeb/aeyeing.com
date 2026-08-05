#!/usr/bin/env python3
import json, requests, yaml
from pathlib import Path

cfg = yaml.safe_load(open('C:/Users/openclaw/.hermes/skills/ozmoeg-money-maker/config.yaml'))
tok = cfg['telegram']['bot_token']
chat = cfg['telegram']['chat_id']
url = f'https://api.telegram.org/bot{tok}/sendMessage'

with open('C:/Users/openclaw/Desktop/aeyeing.com/ozmoeg-latest.json') as f:
    d = json.load(f)

alerts = [r for r in d.get('scan_results', []) if r.get('status') == 'ALERT']
msg = f"""OzMoEg US Scan Update
Market: OPEN (US) | 50 gainers scanned
{len(d.get('scan_results', []))} candidates | {len(alerts)} alerts"""
for r in alerts:
    p = r.get('plan', {})
    msg += f"\n<b>{r['ticker']}</b> — Entry ${p.get('entry')} | Stop ${p.get('stop')} | T1 ${p.get('target_1')} | R:R {p.get('risk_reward')} | Conf {p.get('confidence')}"

resp = requests.post(url, data={'chat_id': chat, 'text': msg, 'parse_mode': 'HTML'}, timeout=20)
print('status', resp.status_code, 'ok', resp.json().get('ok'))
print(resp.text[:300])
