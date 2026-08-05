#!/usr/bin/env python3
import yaml, requests, json, time, hashlib
from pathlib import Path

ROOT = Path.home() / '.hermes' / 'skills' / 'ozmoeg-money-maker'
cfg = yaml.safe_load(open(ROOT / 'config.yaml'))
tok = cfg['telegram']['bot_token']
chat = cfg['telegram']['chat_id']
url = f'https://api.telegram.org/bot{tok}/sendMessage'

with open('C:/Users/openclaw/Desktop/aeyeing.com/ozmoeg-latest.json') as f:
    data = json.load(f)

sent_path = ROOT / '.sent_alerts.json'
try:
    sent_data = json.load(open(sent_path))
except Exception:
    sent_data = {}

sent = []
for r in data['scan_results']:
    if r.get('status') != 'ALERT':
        continue
    sig = r.get('_alert_signature') or hashlib.md5(r['ticker'].encode()).hexdigest()[:32]
    if sig in sent_data:
        print(f'Skip duplicate {r["ticker"]}')
        continue
    p = r.get('plan', {})
    score = r.get('news', {}).get('max_score', 0)
    catalyst = (r.get('news', {}).get('catalyst') or r.get('result', '')[:80])
    msg = f"""🚀 OzMoEg Alert — {r['ticker']}
📰 Catalyst: {catalyst}
💥 Impact Score: {score}/5
💰 Entry Zone: ${p.get('entry', '—')}
🛑 Stop Loss: ${p.get('stop', '—')} (-2%)
🎯 T1: ${p.get('target_1', '—')} | T2: ${p.get('target_2', '—')} | T3: {p.get('target_3', '—')}
📊 Shares: {p.get('shares', '—')} | Value: ${p.get('position_value', '—')}
📈 Risk:Reward: {p.get('rr_ratio', '—')}
⚠️ Confidence: LOW — verify catalyst independently"""
    resp = requests.post(url, data={'chat_id': chat, 'text': msg, 'parse_mode': 'HTML'}, timeout=20)
    print(r['ticker'], resp.status_code, resp.json().get('ok'))
    if resp.json().get('ok'):
        sent_data[sig] = time.time()
        sent.append(r['ticker'])

json.dump(sent_data, open(sent_path, 'w'))
print('Sent tickers:', sent)
