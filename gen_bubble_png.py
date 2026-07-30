import json, glob, os
import matplotlib.pyplot as plt
import matplotlib.patches as mpatches

# Map full country names to short codes (matches live site names)
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

fig, ax = plt.subplots(figsize=(15, 10), facecolor='#0b0f17')
ax.set_facecolor('#0b0f17')

# Widen Y axis: min separation $2, so penny zone gets more room
ax.set_xlim(-500_000, 12_000_000)
ax.set_ylim(-2, 26)

# Zones - no dotted lines
ax.axhspan(0, 1, color='#f87171', alpha=0.10, zorder=1)  # light red penny zone
ax.fill_between([0, 1_500_000], 2, 20, color='#fbbf24', alpha=0.10, zorder=1)  # golden trade zone

# Bubbles
maxc = max(abs(t['change_pct']) or 1 for t in tickers)
sizes = [min(3000, max(550, (abs(t['change_pct']) or 0) / maxc * 2800)) for t in tickers]

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

# Separate overlapping GCTK/CYCU slightly
for t in tickers:
    if t['ticker'] == 'CYCU':
        t['price_plot'] = t['price'] + 0.25
    elif t['ticker'] == 'GCTK':
        t['price_plot'] = t['price'] - 0.25
    else:
        t['price_plot'] = t['price']

ax.scatter([t['float'] for t in tickers], [t['price_plot'] for t in tickers],
           s=sizes, c=colors, edgecolors=edgecolors, linewidths=1.6, zorder=3)

# Labels inside bubbles
for t in tickers:
    ax.text(t['float'], t['price_plot'], f"{t['ticker']}\n{t['country']}",
            ha='center', va='center', color='white', fontsize=9, fontweight='bold',
            linespacing=0.72, zorder=6)

# Hover tooltip mockup on NUWE
for t in tickers:
    if t['ticker'] == 'NUWE':
        ax.text(t['float'], t['price_plot'] - 2.6,
                f"${t['price']:.2f}\nFloat: {t['float']/1_000_000:.2f}M",
                ha='center', va='top', color='#94a3b8', fontsize=7.5,
                bbox=dict(boxstyle='round,pad=0.3', facecolor='#111827', edgecolor='#374151', alpha=0.9))

# Axis formatting
ax.set_xlabel('Float (shares)', color='#94a3b8', fontsize=12, labelpad=14)
ax.set_ylabel('Price ($)', color='#94a3b8', fontsize=12, labelpad=10)
ax.xaxis.set_major_formatter(plt.FuncFormatter(lambda x, pos: f'{x/1_000_000:.1f}M' if x >= 1_000_000 else f'{x/1_000:.0f}K'))
ax.yaxis.set_major_locator(plt.MultipleLocator(2))
ax.tick_params(colors='#94a3b8', which='both', labelsize=10)
ax.grid(True, color='#1f2937', linestyle='-', linewidth=0.6, zorder=1)
for spine in ax.spines.values():
    spine.set_color('#374151')

# Zone labels
ax.text(100_000, 0.35, 'Penny stock zone (< $1)', color=(248/255, 113/255, 113/255, 0.85),
        fontsize=10, ha='left', fontstyle='italic')
ax.text(1_450_000, 21.5, 'Recommended trade zone', color=(251/255, 191/255, 36/255, 0.85),
        fontsize=10, ha='right', fontstyle='italic', fontweight='bold')

ax.set_title('OzMoEg Bubble View Prototype — Float vs Price', color='#2dd4bf', fontsize=16, pad=18)

# Legend at bottom, moved down further
legend = [
    mpatches.Patch(color='#f87171', alpha=0.45, label='Penny stock (< $1)'),
    mpatches.Patch(color='#fbbf24', alpha=0.45, label='Recommended trade zone'),
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
