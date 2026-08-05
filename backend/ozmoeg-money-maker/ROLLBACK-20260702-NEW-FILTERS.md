# OzMoEg Money Maker — Filter Tightening Rollback Plan
# Date: 2026-07-02
# Reason: Tighter small-cap US filters were deployed; keep this rollback ready if alert quality degrades.

## Files changed in this deployment
1. scanner.py
2. config.yaml
3. main.py
4. website/ozmoeg-trader.html (rendered filter list)

## Full rollback command (one step)
BACKUP_DIR="/c/Users/openclaw/Backups/OzMoEg-backup-20260702"
cp "$BACKUP_DIR/active-skill/scanner.py.ORIGINAL"   /c/Users/openclaw/.hermes/skills/ozmoeg-money-maker/scanner.py
cp "$BACKUP_DIR/active-skill/config.yaml.ORIGINAL"  /c/Users/openclaw/.hermes/skills/ozmoeg-money-maker/config.yaml
cp "$BACKUP_DIR/aeyeing.com-repo/ozmoeg-trader.html" /c/Users/openclaw/Desktop/aeyeing.com/ozmoeg-trader.html
# main.py only added us_filters dict for website display; optional to leave or revert via git:
cd /c/Users/openclaw/.hermes/skills/ozmoeg-money-maker
git checkout main.py 2>/dev/null || echo 'main.py not under git; manually remove us_filters block if desired'

## Partial rollback options
- To raise max market cap only: set scanner.market_cap_max=300000000 in config.yaml back to 5000000000
- To remove upper move cap: set scanner.move_max_pct=999.0 (or delete the key)
- To disable float filter: set scanner.max_float_shares=999999999999
- To disable volume/float filter: set scanner.min_volume_float_ratio=0.0
- To disable avg $vol filter: set scanner.min_avg_daily_dollar_volume=0.0

## After rollback
Restart any running OzMoEg cron/terminal sessions to load the restored code.
