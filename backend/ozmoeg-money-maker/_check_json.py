import json
with open('ozmoeg-latest.json', 'r', encoding='utf-8') as f:
    d = json.load(f)
print('last_updated:', d.get('last_updated'))
print('market:', d.get('scan_stats', {}).get('market'))
print('market_status:', d.get('scan_stats', {}).get('market_status'))
print('total candidates:', len(d.get('scan_results', [])))
alerts = [r for r in d.get('scan_results', []) if r.get('status') == 'ALERT']
print('ALERT count:', len(alerts))
for r in alerts[:5]:
    p = r.get('plan', {})
    print(' ', r['ticker'], r.get('name', ''), '| entry=$', p.get('entry'), 'stop=$', p.get('stop'), 'shares=', p.get('shares'), 'R=', p.get('risk_amount'), 'R:R=', p.get('risk_reward'))
print('all_gainers:', len(d.get('all_gainers', [])))
print('all_losers:', len(d.get('all_losers', [])))
print('bounce_results:', len(d.get('bounce_results', [])))
print('previous_live_quotes present:', bool(d.get('previous_live_quotes')))
