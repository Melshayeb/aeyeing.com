import json, os, glob

repo = 'C:/Users/openclaw/Desktop/aeyeing.com'
files = sorted(glob.glob(os.path.join(repo, 'ozmoeg-latest_*.json')), key=os.path.getmtime, reverse=True)[:3]
snapshots = []
for f in files:
    with open(f, 'r') as fh:
        data = json.load(fh)
    snapshot = {'time': data.get('last_updated'), 'tickers': []}
    quotes = data.get('live_quotes', {})
    for r in data.get('scan_results', []):
        q = quotes.get(r['ticker'], {})
        price = r.get('price') or q.get('price') or q.get('close') or 0
        prev = r.get('previous_price') or q.get('preClose') or price
        change_ratio = q.get('changeRatio') if q.get('changeRatio') is not None else ((price - prev) / prev if prev else 0)
        news = r.get('news', {})
        headlines = news.get('headlines', [])
        newest = None
        if headlines:
            try:
                newest = min((h for h in headlines if h.get('raw_time')), key=lambda h: h.get('raw_time',''), default=None)
            except Exception:
                pass
        news_age = newest.get('time','—') if newest else '—'
        news_status = 'catalyst confirmed' if news.get('catalyst_confirmed') else (news.get('news_filter_reason','—'))
        sec = (r.get('sec_filings') or '').strip() or '—'
        snapshot['tickers'].append({
            'ticker': r['ticker'],
            'name': r.get('name',''),
            'status': r.get('status',''),
            'price': float(price) if price else 0,
            'float': float(r.get('float_shares') or 0) or 1,
            'change_pct': float(change_ratio) * 100,
            'volume': int(q.get('volume') or r.get('volume') or 0),
            'market_cap': q.get('marketValue') or r.get('market_value') or 0,
            'country': r.get('country',''),
            'cap_size': r.get('cap_size',''),
            'is_penny': bool(r.get('is_penny_stock')),
            'news_status': news_status,
            'news_age': news_age,
            'top_headline': (news.get('top_headline') or (headlines[0].get('title') if headlines else '')),
            'sec_filings': sec,
            'entry_price': float(r.get('entry_price') or price or 0),
        })
    snapshots.append(snapshot)

json_str = json.dumps(snapshots)

html_content = f'''<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<title>OzMoEg Bubble View Prototype</title>
<script src="https://d3js.org/d3.v7.min.js"></script>
<style>
:root {{
  --bg: #0b0f17;
  --panel: #111827;
  --panel-2: #1f2937;
  --text: #f8fafc;
  --text-2: #94a3b8;
  --accent: #2dd4bf;
  --danger: #f87171;
  --penny: #f59e0b;
  --glow: #22d3ee;
}}
body {{
  margin: 0; padding: 1rem;
  background: var(--bg); color: var(--text);
  font-family: 'Segoe UI', system-ui, sans-serif;
  text-align: center;
}}
h1 {{ margin: 0.2rem 0 0.8rem; font-size: 1.3rem; color: var(--accent); }}
p {{ color: var(--text-2); font-size: 0.9rem; max-width: 700px; margin: 0 auto 1rem; }}
button {{
  background: var(--accent); color: #000; border: none; border-radius: 999px;
  padding: 0.7rem 1.4rem; font-weight: 700; cursor: pointer; font-size: 1rem;
  transition: transform 0.1s;
}}
button:hover {{ transform: scale(1.03); }}
</style>
</head>
<body>
<h1>🫧 OzMoEg Bubble View — Prototype</h1>
<p>This is a preview only. It does not change the live website. Click the button to open the bubble chart in a separate popup window, just like it would behave when a "Bubble View" button is added to the scanner.</p>
<button onclick="openBubbleView()">Open Bubble View</button>

<script>
const snapshots = {json_str};
let currentSnapshotIdx = 0;
let newTickers = new Set();
let droppedTickers = new Set();
let popup = null;
let refreshTimer = null;

function openBubbleView() {{
  if (popup && !popup.closed) {{ popup.focus(); return; }}
  popup = window.open('', 'ozmoeg-bubble-view', 'width=1100,height=800,scrollbars=yes,resizable=yes');
  popup.document.write(buildBubbleHTML());
  popup.document.close();
  setTimeout(() => initChart(popup), 200);
}}

function buildBubbleHTML() {{
  return `<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<title>OzMoEg Bubble View</title>
<script src="https://d3js.org/d3.v7.min.js"></script>
<style>
:root {{
  --bg: #0b0f17;
  --panel: #111827;
  --panel-2: #1f2937;
  --text: #f8fafc;
  --text-2: #94a3b8;
  --accent: #2dd4bf;
  --danger: #f87171;
  --penny: #f59e0b;
  --glow: #22d3ee;
}}
body {{
  margin: 0; padding: 0;
  background: var(--bg); color: var(--text);
  font-family: 'Segoe UI', system-ui, sans-serif;
  overflow: hidden;
}}
#header {{
  position: absolute; top: 0; left: 0; right: 0; height: 44px;
  background: var(--panel); border-bottom: 1px solid var(--panel-2);
  display: flex; align-items: center; justify-content: space-between;
  padding: 0 1rem; z-index: 10;
}}
#header h2 {{ margin: 0; font-size: 1rem; color: var(--accent); }}
#controls {{ display: flex; align-items: center; gap: 0.7rem; }}
#controls span {{ color: var(--text-2); font-size: 0.8rem; }}
#controls button {{
  background: var(--panel-2); color: var(--text); border: 1px solid #374151;
  border-radius: 999px; padding: 0.35rem 0.9rem; font-size: 0.8rem;
  cursor: pointer;
}}
#chart {{
  position: absolute; top: 44px; left: 0; right: 0; bottom: 0;
}}
.legend {{
  position: absolute; bottom: 12px; left: 12px;
  background: rgba(17,24,39,0.85); border: 1px solid var(--panel-2);
  border-radius: 10px; padding: 0.7rem 1rem; font-size: 0.78rem;
  color: var(--text-2); z-index: 10; pointer-events: none;
}}
.legend .dot {{ display: inline-block; width: 10px; height: 10px; border-radius: 50%; margin-right: 6px; }}
.tooltip {{
  position: absolute; pointer-events: none; opacity: 0;
  background: rgba(17,24,39,0.95); border: 1px solid var(--panel-2);
  border-radius: 10px; padding: 0.7rem; font-size: 0.78rem;
  color: var(--text); max-width: 280px; box-shadow: 0 10px 25px rgba(0,0,0,0.4);
  transition: opacity 0.15s; z-index: 20;
}}
.tooltip h4 {{ margin: 0 0 0.3rem; color: var(--accent); font-size: 0.95rem; }}
.tooltip .row {{ margin: 0.15rem 0; color: var(--text-2); }}
.tooltip .row b {{ color: var(--text); }}
@keyframes flashNew {{
  0% {{ fill-opacity: 1; stroke: var(--accent); stroke-width: 3px; }}
  50% {{ fill-opacity: 0.7; stroke: var(--accent); stroke-width: 5px; }}
  100% {{ fill-opacity: 1; stroke: #334155; stroke-width: 1px; }}
}}
@keyframes popOut {{
  0% {{ transform: scale(1); opacity: 1; }}
  100% {{ transform: scale(0); opacity: 0; }}
}}
.flash-new circle {{
  animation: flashNew 5s ease-out forwards;
}}
.popped circle {{
  animation: popOut 0.5s ease-in forwards;
}}
.glow circle {{
  filter: drop-shadow(0 0 8px var(--glow)) drop-shadow(0 0 16px var(--glow));
}}
</style>
</head>
<body>
<div id="header">
  <h2>🫧 Bubble View &nbsp;|&nbsp; Float vs Price</h2>
  <div id="controls">
    <span id="last-updated">—</span>
    <button id="pause-btn" onclick="window.parent.postMessage('toggle-pause','*')">Pause refresh</button>
    <button onclick="window.parent.postMessage('close','*')">Close</button>
  </div>
</div>
<div id="chart"></div>
<div class="legend">
  <div><span class="dot" style="background:var(--penny)"></span>Penny stock (&lt; $1)</div>
  <div><span class="dot" style="background:var(--accent); box-shadow:0 0 8px var(--glow)"></span>Price change &gt; 80% (glowing)</div>
  <div><span class="dot" style="background:var(--danger)"></span>ALERT status</div>
  <div>Bubble size = price change % (abs)</div>
</div>
<div class="tooltip" id="tooltip"></div>
</body>
</html>`;
}}

function initChart(win) {{
  render(win, snapshots[0].tickers, snapshots[0].time);
}}

function render(win, data, timeStr) {{
  const container = win.document.getElementById('chart');
  if (!container) return;
  const tooltip = win.document.getElementById('tooltip');
  const width = container.clientWidth;
  const height = container.clientHeight;
  data.forEach(d => {{ d._id = d.ticker; }});

  const margin = {{ top: 20, right: 30, bottom: 55, left: 65 }};
  const innerW = width - margin.left - margin.right;
  const innerH = height - margin.top - margin.bottom;

  const x = d3.scaleLog()
    .domain(d3.extent(data, d => Math.max(d.float, 1)))
    .range([0, innerW])
    .nice();
  const y = d3.scaleLinear()
    .domain([0, d3.max(data, d => d.price) * 1.15])
    .range([innerH, 0]);
  const size = d3.scaleSqrt()
    .domain([0, d3.max(data, d => Math.abs(d.change_pct) || 1)])
    .range([6, 60]);

  container.innerHTML = '';

  const svg = d3.select(container)
    .append('svg')
    .attr('width', width)
    .attr('height', height);

  const g = svg.append('g')
    .attr('transform', `translate(${{margin.left}},${{margin.top}})`);

  g.append('g')
    .attr('class', 'grid')
    .attr('transform', `translate(0,${{innerH}})`)
    .call(d3.axisBottom(x).ticks(6).tickSize(-innerH).tickFormat(''))
    .call(g => g.select('.domain').remove())
    .call(g => g.selectAll('.tick line').attr('stroke', '#1f2937'));

  g.append('g')
    .attr('class', 'grid')
    .call(d3.axisLeft(y).ticks(6).tickSize(-innerW).tickFormat(''))
    .call(g => g.select('.domain').remove())
    .call(g => g.selectAll('.tick line').attr('stroke', '#1f2937'));

  g.append('g')
    .attr('transform', `translate(0,${{innerH}})`)
    .call(d3.axisBottom(x).ticks(6).tickFormat(d3.format('.2s')))
    .call(g => g.select('.domain').attr('stroke', '#374151'))
    .call(g => g.selectAll('.tick text').attr('fill', '#94a3b8').attr('font-size', 11));

  g.append('g')
    .call(d3.axisLeft(y).ticks(6).tickFormat(d => `$${{d.toFixed(2)}}`))
    .call(g => g.select('.domain').attr('stroke', '#374151'))
    .call(g => g.selectAll('.tick text').attr('fill', '#94a3b8').attr('font-size', 11));

  g.append('text')
    .attr('x', innerW / 2)
    .attr('y', innerH + 42)
    .attr('text-anchor', 'middle')
    .attr('fill', '#94a3b8')
    .attr('font-size', 12)
    .text('Float (shares, log scale)');

  g.append('text')
    .attr('transform', 'rotate(-90)')
    .attr('x', -innerH / 2)
    .attr('y', -45)
    .attr('text-anchor', 'middle')
    .attr('fill', '#94a3b8')
    .attr('font-size', 12)
    .text('Price ($)');

  const y1 = y(1);
  if (y1 < innerH && y1 > 0) {{
    g.append('rect')
      .attr('x', 0)
      .attr('y', y1)
      .attr('width', innerW)
      .attr('height', innerH - y1)
      .attr('fill', 'rgba(245,158,11,0.06)')
      .attr('stroke', 'none');
    g.append('text')
      .attr('x', innerW - 8)
      .attr('y', innerH - 8)
      .attr('text-anchor', 'end')
      .attr('fill', 'rgba(245,158,11,0.5)')
      .attr('font-size', 11)
      .text('Penny stock zone (< $1)');
  }}

  const nodes = g.selectAll('.bubble')
    .data(data, d => d._id)
    .join(
      enter => {{
        const node = enter.append('g')
          .attr('class', d => {{
            let cls = 'bubble';
            if (Math.abs(d.change_pct) > 80) cls += ' glow';
            if (newTickers.has(d.ticker)) cls += ' flash-new';
            return cls;
          }})
          .attr('transform', d => `translate(${{x(Math.max(d.float,1))}},${{y(d.price)}})`)
          .style('cursor', 'pointer')
          .style('opacity', 0)
          .call(g => g.transition().duration(600).style('opacity', 1));
        node.append('circle')
          .attr('r', 0)
          .attr('fill', d => d.is_penny ? 'var(--penny)' : (d.status === 'ALERT' ? 'var(--danger)' : 'var(--accent)'))
          .attr('stroke', d => d.is_penny ? 'var(--penny)' : '#334155')
          .attr('stroke-width', 1)
          .attr('fill-opacity', d => d.is_penny ? 0.35 : 0.55)
          .transition().duration(600)
          .attr('r', d => size(Math.abs(d.change_pct) || 1));
        node.append('text')
          .attr('text-anchor', 'middle')
          .attr('dy', '.35em')
          .attr('fill', '#f8fafc')
          .attr('font-size', d => Math.max(9, size(Math.abs(d.change_pct)||1)/3.5))
          .attr('font-weight', 700)
          .attr('pointer-events', 'none')
          .text(d => d.ticker);
        return node;
      }},
      update => {{
        return update
          .attr('class', d => {{
            let cls = 'bubble';
            if (Math.abs(d.change_pct) > 80) cls += ' glow';
            if (newTickers.has(d.ticker)) cls += ' flash-new';
            return cls;
          }})
          .transition().duration(750)
          .attr('transform', d => `translate(${{x(Math.max(d.float,1))}},${{y(d.price)}})`)
          .selection()
          .select('circle')
          .transition().duration(750)
          .attr('r', d => size(Math.abs(d.change_pct) || 1))
          .attr('fill', d => d.is_penny ? 'var(--penny)' : (d.status === 'ALERT' ? 'var(--danger)' : 'var(--accent)'));
      }},
      exit => {{
        return exit.attr('class', 'bubble popped')
          .transition().duration(500).style('opacity', 0).remove();
      }}
    );

  nodes
    .on('mouseenter', function(event, d) {{
      const fmt = n => n ? n.toLocaleString(undefined, {{maximumFractionDigits:2}}) : '—';
      const pct = d.change_pct ? `${{d.change_pct >= 0 ? '+' : ''}}${{d.change_pct.toFixed(1)}}%` : '—';
      tooltip.innerHTML = `
        <h4>${{d.ticker}} — ${{d.name}}</h4>
        <div class="row"><b>Status:</b> ${{d.status}}</div>
        <div class="row"><b>Price:</b> $${{fmt(d.price)}}</div>
        <div class="row"><b>Entry price:</b> $${{fmt(d.entry_price)}}</div>
        <div class="row"><b>Change:</b> ${{pct}}</div>
        <div class="row"><b>Float:</b> ${{fmt(d.float)}}</div>
        <div class="row"><b>Volume:</b> ${{fmt(d.volume)}}</div>
        <div class="row"><b>Cap:</b> ${{d.cap_size || '—'}} (${{d.country}})</div>
        <div class="row"><b>News:</b> ${{d.news_status}}</div>
        <div class="row"><b>News age:</b> ${{d.news_age}}</div>
        <div class="row"><b>SEC filings:</b> ${{d.sec_filings}}</div>
        <div class="row" style="margin-top:0.3rem;color:#cbd5e1;font-style:italic;">${{d.top_headline}}</div>
      `;
      tooltip.style.opacity = 1;
      const box = container.getBoundingClientRect();
      let left = event.clientX - box.left + 15;
      let top = event.clientY - box.top + 15;
      if (left + 280 > width) left -= 300;
      if (top + 200 > height) top -= 220;
      tooltip.style.left = left + 'px';
      tooltip.style.top = top + 'px';
    }})
    .on('mousemove', function(event) {{
      const box = container.getBoundingClientRect();
      let left = event.clientX - box.left + 15;
      let top = event.clientY - box.top + 15;
      if (left + 280 > width) left -= 300;
      if (top + 200 > height) top -= 220;
      tooltip.style.left = left + 'px';
      tooltip.style.top = top + 'px';
    }})
    .on('mouseleave', () => {{ tooltip.style.opacity = 0; }});

  const lu = win.document.getElementById('last-updated');
  if (lu) lu.textContent = 'Updated: ' + (timeStr ? new Date(timeStr).toLocaleString('en-AU', {{timeZone:'Australia/Sydney'}}) : '—');
}}

function nextRefresh() {{
  if (!popup || popup.closed) return;
  const prev = snapshots[currentSnapshotIdx].tickers;
  currentSnapshotIdx = (currentSnapshotIdx + 1) % snapshots.length;
  const next = snapshots[currentSnapshotIdx];
  const prevSet = new Set(prev.map(d => d.ticker));
  const nextSet = new Set(next.tickers.map(d => d.ticker));
  newTickers = new Set(next.tickers.map(d => d.ticker).filter(t => !prevSet.has(t)));
  droppedTickers = new Set([...prevSet].filter(t => !nextSet.has(t)));
  if (newTickers.size === 0 && next.tickers.length) {{
    const idx = currentSnapshotIdx % next.tickers.length;
    newTickers.add(next.tickers[idx].ticker);
  }}
  render(popup, next.tickers, next.time);
  setTimeout(() => {{ newTickers.clear(); }}, 5000);
}}

let paused = false;
function startRefresh() {{
  if (refreshTimer) clearInterval(refreshTimer);
  refreshTimer = setInterval(() => {{ if (!paused) nextRefresh(); }}, 60000);
}}
function stopRefresh() {{
  if (refreshTimer) clearInterval(refreshTimer);
}}

window.addEventListener('message', e => {{
  if (e.data === 'toggle-pause') {{
    paused = !paused;
    if (popup && !popup.closed) {{
      const btn = popup.document.getElementById('pause-btn');
      if (btn) btn.textContent = paused ? 'Resume refresh' : 'Pause refresh';
    }}
  }} else if (e.data === 'close') {{
    stopRefresh();
    if (popup && !popup.closed) popup.close();
    popup = null;
  }}
}});

startRefresh();
</script>
</body>
</html>'''

out_path = os.path.join(repo, 'ozmoeg-bubble-view-prototype.html')
with open(out_path, 'w') as f:
    f.write(html_content)
print('Wrote', out_path, f'{len(html_content):,} bytes')
