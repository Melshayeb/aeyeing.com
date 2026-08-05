import json, yaml
from notifier import Notifier

with open('config.yaml', 'r', encoding='utf-8') as f:
    cfg = yaml.safe_load(f)
n = Notifier(cfg)

with open(r'C:\Users\openclaw\Desktop\aeyeing.com\ozmoeg-latest.json', 'r', encoding='utf-8') as f:
    d = json.load(f)

alerts = [r for r in d.get('scan_results', []) if r.get('status') == 'ALERT']
if not alerts:
    print('No alerts to notify')
else:
    lines = ['🚀 <b>OzMoEg US Pre-Market Scan — ' + str(len(alerts)) + ' alert(s)</b>']
    lines.append('')
    for r in alerts:
        p = r.get('plan', {})
        score = r.get('news', {}).get('max_score', 0)
        lines.append(f'<b>{r.get("ticker")}</b> — {r.get("name")} ({r.get("country", "?")})')
        lines.append(f'  Entry ${p.get("entry")} | Stop ${p.get("stop")} | T1 ${p.get("targets", {}).get("t1")} | T3 ${p.get("targets", {}).get("t3")}')
        lines.append(f'  R:R {p.get("risk_reward")}:1 | Shares {p.get("shares")} | Impact {score}/5')
        lines.append(f'  {r.get("result", "")}')
        lines.append('')
    lines.append('📡 <a href="https://aeyeing.com/ozmoeg-trader.html">Dashboard</a>')
    msg = '\n'.join(lines)
    print(msg[:500])
    ok = n.send_telegram(msg, parse_mode='HTML')
    print('Telegram summary sent:', ok)
