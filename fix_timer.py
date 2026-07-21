import pathlib

p = pathlib.Path('ozmoeg-trader.html')
text = p.read_text(encoding='utf-8')

# 1. Replace resetRefreshTimer so expiry always updates countdown and fetches data.
old_reset = '''        function resetRefreshTimer() {
            if (refreshTimerId) clearInterval(refreshTimerId);
            scheduleNextRefresh(window._lastScanTimestamp);
            refreshTimerId = setInterval(() => {
                const interval = getRefreshIntervalMs();
                if (interval === 0) {
                    updateRefreshCountdown();
                    return;
                }
                try {
                    localStorage.setItem('ozmoeg-next-refresh', String(nextRefreshAt));
                } catch (e) { /* storage may be unavailable */ }
                if (Date.now() >= nextRefreshAt) {
                    const candidate = computeNextRefresh();
                    nextRefreshAt = Number.isFinite(candidate) ? candidate : Date.now() + interval;
                    loadLiveData();
                } else {
                    updateRefreshCountdown();
                }
            }, 1000);
        }
'''
new_reset = '''        function resetRefreshTimer() {
            if (refreshTimerId) clearInterval(refreshTimerId);
            scheduleNextRefresh(window._lastScanTimestamp);
            refreshTimerId = setInterval(() => {
                const interval = getRefreshIntervalMs();
                if (interval === 0) {
                    updateRefreshCountdown();
                    return;
                }
                try {
                    localStorage.setItem('ozmoeg-next-refresh', String(nextRefreshAt));
                } catch (e) { /* storage may be unavailable */ }
                if (Date.now() >= nextRefreshAt) {
                    const candidate = computeNextRefresh();
                    nextRefreshAt = Number.isFinite(candidate) ? candidate : Date.now() + interval;
                    loadLiveData().catch(err => console.error('Auto loadLiveData failed:', err));
                }
                updateRefreshCountdown();
            }, 1000);
        }
'''
assert old_reset in text, 'resetRefreshTimer block not found'
text = text.replace(old_reset, new_reset)

# 2. Recompute nextRefreshAt after each successful fetch.
old_next = '''                // Anchor the auto-refresh countdown to the JSON timestamp so it stays
                // aligned with the cron schedule, not the browser load time.
                window._lastScanTimestamp = lastUpdated;
                // Do not recompute nextRefreshAt here; the interval timer handles firing
                // at the next wall-clock cron boundary and will reschedule after the fetch.

                // Update badge — prefer real-time US market status when the JSON scan is stale'''
new_next = '''                // Anchor the auto-refresh countdown to the JSON timestamp so it stays
                // aligned with the cron schedule, not the browser load time.
                window._lastScanTimestamp = lastUpdated;
                // Recompute the next refresh boundary from the scan timestamp so the timer
                // shows the true time to the next scheduled fetch instead of re-using the
                // stale value that just fired.
                scheduleNextRefresh(lastUpdated);

                // Update badge — prefer real-time US market status when the JSON scan is stale'''
assert old_next in text, 'nextRefreshAt comment block not found'
text = text.replace(old_next, new_next)

# 3. Add drop-sound detection.
old_alert = '''                const prevAlertTickers = new Set(window._lastAlertTickers || []);
                const currentAlerts = allResultsForSound.filter(r => r.status === 'ALERT');
                const newAlertTickers = currentAlerts.map(r => r.ticker).filter(t => !prevAlertTickers.has(t));
                if (soundEnabled && newAlertTickers.length > 0) {
                    playNewAlertSound(newAlertTickers.length);
                }
                window._lastAlertTickers = currentAlerts.map(r => r.ticker);

                const rawStatus = stats.market_status || 'OPEN';'''
new_alert = '''                const prevAlertTickers = new Set(window._lastAlertTickers || []);
                const currentAlerts = allResultsForSound.filter(r => r.status === 'ALERT');
                const newAlertTickers = currentAlerts.map(r => r.ticker).filter(t => !prevAlertTickers.has(t));
                if (soundEnabled && newAlertTickers.length > 0) {
                    playNewAlertSound(newAlertTickers.length);
                }
                window._lastAlertTickers = currentAlerts.map(r => r.ticker);

                // Detect tickers that disappeared from the combined scanner list and play a drop sound.
                // We track every ticker that was visible in any scanner view (live, pre/after, watchlist, bouncers).
                const allResultsForDrop = [
                    ...(results || []),
                    ...(preMarketResults || []),
                    ...(preMarketWatchlist || []),
                    ...(data.bouncers || [])
                ];
                const prevVisibleTickers = new Set(window._lastVisibleTickers || []);
                const currentVisibleTickers = new Set(allResultsForDrop.map(r => r.ticker).filter(Boolean));
                const droppedTickers = [...prevVisibleTickers].filter(t => !currentVisibleTickers.has(t));
                if (soundEnabled && droppedTickers.length > 0) {
                    playDropSound(droppedTickers.length);
                }
                window._lastVisibleTickers = [...currentVisibleTickers];

                const rawStatus = stats.market_status || 'OPEN';'''
assert old_alert in text, 'alert sound block not found'
text = text.replace(old_alert, new_alert)

# 4. Add playDropSound function.
old_play_alert = '''                osc.stop(now + i * 0.18 + 0.4);
            }
        }

        function scheduleNextRefresh(anchor) {'''
new_play_alert = '''                osc.stop(now + i * 0.18 + 0.4);
            }
        }

        function playDropSound(count) {
            if (!sharedAudioCtx) return;
            if (sharedAudioCtx.state === 'suspended') {
                sharedAudioCtx.resume().catch(err => console.warn('AudioContext resume failed:', err));
            }
            const now = sharedAudioCtx.currentTime;
            for (let i = 0; i < Math.min(count, 3); i++) {
                const osc = sharedAudioCtx.createOscillator();
                const gain = sharedAudioCtx.createGain();
                osc.type = 'sine';
                // A short descending "drop" tone: 440 Hz down to 220 Hz.
                osc.frequency.setValueAtTime(440, now + i * 0.22);
                osc.frequency.exponentialRampToValueAtTime(220, now + i * 0.22 + 0.18);
                gain.gain.setValueAtTime(0.0001, now + i * 0.22);
                gain.gain.exponentialRampToValueAtTime(0.12, now + i * 0.22 + 0.03);
                gain.gain.exponentialRampToValueAtTime(0.0001, now + i * 0.22 + 0.45);
                osc.connect(gain);
                gain.connect(sharedAudioCtx.destination);
                osc.start(now + i * 0.22);
                osc.stop(now + i * 0.22 + 0.5);
            }
        }

        function scheduleNextRefresh(anchor) {'''
assert old_play_alert in text, 'playNewAlertSound end block not found'
text = text.replace(old_play_alert, new_play_alert)

# 5. Simplify duplicate scheduleNextRefresh definitions.
old_dup = '''        // Schedule the next refresh relative to the actual data timestamp.
        // We keep stepping forward by the active/idle interval until we land in the future,
        // so the countdown does not reset to "now + interval" every time a page reloads.
        function scheduleNextRefresh(anchorTimestamp) {
            const interval = getRefreshIntervalMs();
            const now = Date.now();
            let next;
            if (interval <= 0) {
                next = now + 60000;
            } else {
                const anchor = anchorTimestamp ? new Date(anchorTimestamp).getTime() : now;
                // Snap to the previous wall-clock interval boundary because the cron fires on
                // the boundary (18:00, 18:02, 18:04 ...), not at the exact scan completion time.
                const alignedAnchor = Math.floor(anchor / interval) * interval;
                // If the anchor is unreasonably old (no data yet), fall back to the current wall-clock boundary.
                const start = (anchorTimestamp && alignedAnchor > now - 24 * 3600 * 1000)
                    ? alignedAnchor
                    : Math.floor(now / interval) * interval;
                next = start + interval;
            }
            nextRefreshAt = Number.isFinite(next) ? next : now + (isActiveTradingWindow() ? ACTIVE_REFRESH_INTERVAL_MS : IDLE_REFRESH_INTERVAL_MS);
            // Persist so the countdown survives page reloads.
            try {
                localStorage.setItem('ozmoeg-next-refresh', String(nextRefreshAt));
            } catch (e) { /* storage may be unavailable */ }
            updateRefreshCountdown();
        }

'''
assert old_dup in text, 'first scheduleNextRefresh duplicate not found'
text = text.replace(old_dup, '')

old_anchor = '''        function scheduleNextRefresh(anchor) {
            const interval = getRefreshIntervalMs();
            if (interval <= 0) {
                nextRefreshAt = Date.now() + 60000;
                updateRefreshCountdown();
                return;
            }
            nextRefreshAt = computeNextRefresh();'''
new_anchor = '''        function scheduleNextRefresh(anchorTimestamp) {
            const interval = getRefreshIntervalMs();
            if (interval <= 0) {
                nextRefreshAt = Date.now() + 60000;
                updateRefreshCountdown();
                return;
            }
            nextRefreshAt = computeNextRefresh();'''
assert old_anchor in text, 'remaining scheduleNextRefresh not found'
text = text.replace(old_anchor, new_anchor)

# 6. Add concurrency guard to loadLiveData.
old_load_start = '''        async function loadLiveData() {
            try {
                setMarketLoading(currentMarket, true);'''
new_load_start = '''        async function loadLiveData() {
            if (window._loadingLiveData) return;
            window._loadingLiveData = true;
            try {
                setMarketLoading(currentMarket, true);'''
assert old_load_start in text, 'loadLiveData start not found'
text = text.replace(old_load_start, new_load_start)

old_load_finally = '''            } catch (e) {
                console.error('Live data refresh failed:', e);
            } finally {
                setMarketLoading(currentMarket, false);'''
new_load_finally = '''            } catch (e) {
                console.error('Live data refresh failed:', e);
            } finally {
                window._loadingLiveData = false;
                setMarketLoading(currentMarket, false);'''
assert old_load_finally in text, 'loadLiveData finally not found'
text = text.replace(old_load_finally, new_load_finally)

# 7. Add manual-refresh button listener if the page has one.
if 'manual-refresh' not in text:
    old_init = '''        // Initialise: load data first, then anchor the refresh countdown to the JSON timestamp.
        // This prevents a brief flash of "15:00" before the first fetch completes.
        (async function init() {'''
    new_init = '''        // Manual refresh button (if present) re-fetches immediately and restarts the timer.
        document.addEventListener('DOMContentLoaded', () => {
            const manualRefreshBtn = document.getElementById('manual-refresh');
            if (manualRefreshBtn) {
                manualRefreshBtn.addEventListener('click', () => {
                    nextRefreshAt = Date.now();
                    loadLiveData();
                });
            }
        });

        // Initialise: load data first, then anchor the refresh countdown to the JSON timestamp.
        // This prevents a brief flash of "15:00" before the first fetch completes.
        (async function init() {'''
    assert old_init in text, 'init block not found'
    text = text.replace(old_init, new_init)

p.write_text(text, encoding='utf-8')
print('patch ok')
