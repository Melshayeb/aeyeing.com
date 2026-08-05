from webull import paper_webull
import yaml

with open('config.yaml', 'r') as f:
    config = yaml.safe_load(f)

cfg = config['scanner']

wb = paper_webull()

for rank_type in ['preMarket', 'afterMarket']:
    print(f'\n=== {rank_type.upper()} GAINERS ===')
    try:
        r = wb.active_gainer_loser(direction='gainer', rank_type=rank_type, count=50)
        data = r.get('data', [])
        print(f'Total: {len(data)}')
        
        passed = 0
        for stock in data:
            t = stock.get('ticker', stock)
            v = stock.get('values', {})
            symbol = t.get('symbol', '?')
            
            price = float(v.get('price', 0) or t.get('pprice', 0) or t.get('close', 0) or 0)
            close = float(t.get('close', 0) or 0)
            pchRatio = float(t.get('pchRatio', 0) or 0)
            volume = int(t.get('volume', 0) or 0)
            market_cap_raw = float(t.get('marketValue', 0) or 0)
            
            if close > 0 and price > 0:
                actual_change_pct = (price - close) / close * 100
            else:
                actual_change_pct = (pchRatio - 1) * 100 if pchRatio > 1 else pchRatio * 100
            
            market_cap = market_cap_raw
            
            price_ok = cfg['price_min'] <= price <= cfg['price_max']
            mc_ok = cfg['market_cap_min'] <= market_cap <= cfg['market_cap_max']
            change_ok = actual_change_pct >= cfg.get('premarket_pct_min', 5)
            vol_ok = volume >= 100_000
            
            if price_ok and mc_ok and change_ok and vol_ok:
                passed += 1
                print(f'>>> PASS: {symbol}: price=${price:.2f}, chg={actual_change_pct:.1f}%, mcap={market_cap:.0f}, vol={volume}')
            elif price_ok and mc_ok and change_ok:
                print(f'    NEAR: {symbol}: price=${price:.2f}, chg={actual_change_pct:.1f}%, mcap={market_cap:.0f}, vol={volume}')
        
        print(f'Passed: {passed}/{len(data)}')
    except Exception as e:
        print(f'Error: {e}')

