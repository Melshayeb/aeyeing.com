import json, glob, os, math
import matplotlib.pyplot as plt
import matplotlib.patches as mpatches

# Map full country names to short codes
country_map = {
    'United States': 'US',
    'China / Cayman-China': 'CN',
    'China / Cayman China': 'CN',
    'China': 'CN',
    'International (region 83)': 'IL',
    'International': 'IL',
    'Israel': 'IL',
    'Canada': 'CA',
    'Australia': 'AU',
    'United Kingdom': 'UK',
    'Hong Kong': 'HK',
    'Singapore': 'SG',
    'Japan': 'JP',
    'South Korea': 'KR',
    'Taiwan': 'TW',
    'India': 'IN',
    'Germany': 'DE',
    'France': 'FR',
    'Netherlands': 'NL',
    'Switzerland': 'CH',
    'Sweden': 'SE',
    'Bermuda': 'BM',
    'Ireland': 'IE',
    'British Virgin Islands': 'VG',
    'Cayman Islands': 'KY',
    'Luxembourg': 'LU',
    'Spain': 'ES',
    'Italy': 'IT',
    'Brazil': 'BR',
    'Mexico': 'MX',
    'South Africa': 'ZA',
    'UAE': 'AE',
}

f = sorted(glob.glob('ozmoeg-latest_*.json'), key=os.path.getmtime, reverse=True)[0]
with open(f) as fh:
    data = json.load(fh)

quotes = data.get('live_quotes', {})
tickers = []
for r in data.get('scan_results', []):
    q = quotes.get(r['ticker'], {})
    price = r.get('price') or q.get('price') or q.get('close') or 0
    if price < 0.20 or price > 50:
        continue
    prev = r.get('previous_price') or q.get('preClose') or price
    change = q.get('changeRatio') if q.get('changeRatio') is not None else ((price - prev) / prev if prev else 0)
    country = r.get('country', '') or ''
    short = country_map.get(country.strip())
    if not short:
        if len(country) <= 3 and country.isupper():
            short = country
        else:
            short = country[:2].upper() if country else '?'
    if short in ('UN', ''):
        short = '?'
    tickers.append({
        'ticker': r['ticker'],
        'price': float(price),
        'float': float(r.get('float_shares') or 1),
        'change_pct': float(change) * 100,
        'status': r.get('status', ''),
        'is_penny': bool(r.get('is_penny_stock')),
        'cap_size': r.get('cap_size', ''),
        'country': short,
    })

print('tickers:', [(t['ticker'], t['price'], t['float'], t['country']) for t in tickers])

# Plot coordinate transforms: log y, linear x
def price_to_y(p): return math.log10(p)
def float_to_x(f): return f

# Estimate bubble radius in plot coordinates (approx)
maxc = max(abs(t['change_pct']) or 1 for t in tickers)
for t in tickers:
    rel = (abs(t['change_pct']) or 0) / maxc
    t['plot_r'] = 0.08 + rel * 0.18  # in log-price units

# Simple force-directed repulsion for overlapping bubbles
positions = {t['ticker']: [float_to_x(t['float']), price_to_y(t['price'])] for t in tickers}

for _ in range(100):
    for i, t1 in enumerate(tickers):
        fx, fy = 0.0, 0.0
        x1, y1 = positions[t1['ticker']]
        for t2 in tickers:
            if t1['ticker'] == t2['ticker']:
                continue
            x2, y2 = positions[t2['ticker']]
            dx = x1 - x2
            dy = y1 - y2
            dist = math.hypot(dx, dy * 8_000_000)
            min_dist = (t1['plot_r'] + t2['plot_r']) * 8_000_000
            if dist < min_dist and dist > 0:
                force = (min_dist - dist) / dist
                fx += force * dx
                fy += force * dy / (8_000_000 ** 2)
        positions[t1['ticker']][0] += fx * 0.02
        positions[t1['ticker']][1] += fy * 0.02
        orig_x = float_to_x(t1['float'])
        orig_y = price_to_y(t1['price'])
        positions[t1['ticker']][0] = positions[t1['ticker']][0] * 0.85 + orig_x * 0.15
        positions[t1['ticker']][1] = positions[t1['ticker']][1] * 0.85 + orig_y * 0.15

# Ensure bottom bubbles don't get clipped
for tk in ['GCTK', 'CYCU']:
    if tk in positions:
        positions[tk][1] = max(positions[tk][1], math.log10(0.30))

fig, ax = plt.subplots(figsize=(15, 10.5), facecolor='#0b0f17')
ax.set_facecolor('#0b0f17')

# Focus the chart: small penny zone at bottom, large trade zone above
ax.set_xlim(-300_000, 12_500_000)
ax.set_yscale('log')
ax.set_ylim(0.20, 28)

# Penny zone < $1
ax.axhspan(0.20, 1, color='#f87171', alpha=0.05, zorder=1)

# Prominent green recommended trade zone, Float 2M, Price $1.80-$22
ax.fill_between([0, 2_000_000], 1.8, 22, color='#34d399', alpha=0.18, zorder=1)

# Bubbles
sizes = [min(5000, max(900, (abs(t['change_pct']) or 0) / maxc * 4500)) for t in tickers]

colors = []
edgecolors = []
for t in tickers:
    if abs(t['change_pct']) > 80:
        colors.append((34/255, 211/255, 238/255, 0.70)); edgecolors.append('#22d3ee')
    elif t['is_penny']:
        colors.append((248/255, 113/255, 113/255, 0.55)); edgecolors.append('#f87171')
    elif t['status'] == 'ALERT':
        colors.append((248/255, 113/255, 113/255, 0.55)); edgecolors.append('#f87171')
    else:
        colors.append((45/255, 212/255, 191/255, 0.55)); edgecolors.append('#2dd4bf')

x_vals = [positions[t['ticker']][0] for t in tickers]
y_vals = [10 ** positions[t['ticker']][1] for t in tickers]

ax.scatter(x_vals, y_vals, s=sizes, c=colors, edgecolors=edgecolors, linewidths=1.6, zorder=3)

# Decide label placement: inside if bubble is large enough, outside with arrow if too small
# Threshold based on relative change (bubble size)
label_outside = []
label_inside = []
for t in tickers:
    rel = (abs(t['change_pct']) or 0) / maxc
    if rel < 0.25:
        label_outside.append(t)
    else:
        label_inside.append(t)

print('inside:', [t['ticker'] for t in label_inside])
print('outside:', [t['ticker'] for t in label_outside])

# Inside labels - larger separation between ticker and country code
for t in label_inside:
    x, y = positions[t['ticker']][0], 10 ** positions[t['ticker']][1]
    ax.text(x, y * 1.015, t['ticker'],
            ha='center', va='bottom', color='white', fontsize=10, fontweight='bold',
            linespacing=0.7, zorder=6)
    ax.text(x, y * 0.985, t['country'],
            ha='center', va='top', color='white', fontsize=7,
            linespacing=0.7, zorder=6)

# Outside labels with arrows - placed just next to the bubble, small gap
for t in label_outside:
    bx, by = positions[t['ticker']][0], 10 ** positions[t['ticker']][1]
    offset_x = max(200_000, by * 140_000)
    tx = bx + offset_x
    # Stack ticker above country with vertical separation
    ax.text(tx, by * 1.006, t['ticker'],
            ha='left', va='bottom', color='white', fontsize=9.5,
            fontweight='bold', linespacing=0.7, zorder=6)
    ax.text(tx, by * 0.994, t['country'],
            ha='left', va='top', color='white', fontsize=7,
            linespacing=0.7, zorder=6)
    ax.annotate('', xy=(bx + offset_x * 0.08, by), xytext=(tx - 50_000, by),
                arrowprops=dict(arrowstyle='-', color='#94a3b8', lw=0.7), zorder=5)

# Hover tooltip mockup on NUWE
for t in tickers:
    if t['ticker'] == 'NUWE':
        x, y = positions[t['ticker']][0], 10 ** positions[t['ticker']][1]
        status_display = f"Alert: {t.get('alert_level','High')}" if t['status'] == 'ALERT' else t['status']
        ax.text(x, y * 0.78,
                f"${t['price']:.2f} | Float {t['float']/1_000_000:.2f}M\n"
                f"Change {t['change_pct']:+.1f}% | {status_display}\n"
                f"Vol 1.2M | News 12m | SEC 3",
                ha='center', va='top', color='#94a3b8', fontsize=8,
                bbox=dict(boxstyle='round,pad=0.35', facecolor='#111827', edgecolor='#374151', alpha=0.95))

# Axis formatting
ax.set_xlabel('Float (shares)', color='#94a3b8', fontsize=12, labelpad=14)
ax.set_ylabel('Price ($)', color='#94a3b8', fontsize=12, labelpad=10)
ax.xaxis.set_major_formatter(plt.FuncFormatter(lambda x, pos: f'{x/1_000_000:.1f}M' if x >= 1_000_000 else f'{x/1_000:.0f}K'))
ax.set_yticks([0.25, 0.5, 1, 2, 5, 10, 20, 25])
ax.get_yaxis().set_major_formatter(plt.FuncFormatter(lambda x, pos: f'${x:.2f}' if x < 1 else f'${x:.0f}'))
ax.tick_params(colors='#94a3b8', which='both', labelsize=10)
ax.grid(True, color='#1f2937', linestyle='-', linewidth=0.6, zorder=1)
for spine in ax.spines.values():
    spine.set_color('#374151')

# Zone labels
ax.text(100_000, 0.25, 'Penny zone (< $1)', color=(248/255, 113/255, 113/255, 0.7),
        fontsize=9, ha='left', fontstyle='italic')
ax.text(1_000_000, 23, 'Recommended trade zone', color=(52/255, 211/255, 153/255, 0.95),
        fontsize=10, ha='center', fontstyle='italic', fontweight='bold')

ax.set_title('OzMoEg Bubble View Prototype — Float vs Price', color='#2dd4bf', fontsize=16, pad=18)

# Legend at bottom
legend = [
    mpatches.Patch(color='#f87171', alpha=0.45, label='Penny stock (< $1)'),
    mpatches.Patch(color='#34d399', alpha=0.45, label='Recommended trade zone'),
    mpatches.Patch(color='#22d3ee', alpha=0.65, label='Price change > 80% (glow)'),
    mpatches.Patch(color='#f87171', alpha=0.55, label='ALERT status'),
    mpatches.Patch(color='none', label='Size = |price change %|'),
]
leg = ax.legend(handles=legend, loc='lower left', facecolor='#111827', edgecolor='#1f2937',
                labelcolor='#94a3b8', fontsize=10, framealpha=0.95, bbox_to_anchor=(0, -0.16),
                ncol=3)

out = 'ozmoeg-bubble-view-prototype.png'
plt.tight_layout()
plt.savefig(out, dpi=160, facecolor='#0b0f17', edgecolor='none', bbox_inches='tight', pad_inches=0.4)
print('Saved', out)
