import pathlib, re

p = pathlib.Path('ozmoeg-trader.html')
text = p.read_text(encoding='utf-8')

# 1. Fix resetRefreshTimer: always update countdown and call loadLiveData with catch
old = '''        function resetRefreshTimer() {
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
        }'''
new = '''        function resetRefreshTimer() {
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
        }'''
print('reset old found' if old in text else 'reset old NOT found')
text = text.replace(old, new)

# 2. Recompute nextRefreshAt from scan timestamp after every load
old2 = '''                // Anchor the auto-refresh countdown to the JSON timestamp so it stays
                // aligned with the cron schedule, not the browser load time.
                window._lastScanTimestamp = lastUpdated;
                // Do not recompute nextRefreshAt here; the interval timer handles firing
                // at the next wall-clock cron boundary and will reschedule after the fetch.

                // Update badge — prefer real-time US market status when the JSON scan is stale'''
new2 = '''                // Anchor the auto-refresh countdown to the JSON timestamp so it stays
                // aligned with the cron schedule, not the browser load time.
                window._lastScanTimestamp = lastUpdated;
                // Recompute the next refresh boundary from the scan timestamp so the timer
                // shows the true time to the next scheduled fetch instead of re-using the
                // stale value that just fired.
                scheduleNextRefresh(lastUpdated);

                // Update badge — prefer real-time US market status when the JSON scan is stale'''
print('nextRefreshAt old found' if old2 in text else 'nextRefreshAt old NOT found')
text = text.replace(old2, new2)

# 3. Add drop-sound detection
old3 = '''                const prevAlertTickers = new Set(window._lastAlertTickers || []);
                const currentAlerts = allResultsForSound.filter(r => r.status === 'ALERT');
                const newAlertTickers = currentAlerts.map(r => r.ticker).filter(t => !prevAlertTickers.has(t));
                if (soundEnabled && newAlertTickers.length > 0) {
                    playNewAlertSound(newAlertTickers.length);
                }
                window._lastAlertTickers = currentAlerts.map(r => r.ticker);

                const rawStatus = stats.market_status || 'OPEN';'''
new3 = '''                const prevAlertTickers = new Set(window._lastAlertTickers || []);
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
print('drop old found' if old3 in text else 'drop old NOT found')
text = text.replace(old3, new3)

# 4. Add playDropSound function
old4 = '''                osc.stop(now + i * 0.18 + 0.4);
            }
        }

        function scheduleNextRefresh(anchor) {'''
new4 = '''                osc.stop(now + i * 0.18 + 0.4);
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
print('playDropSound old found' if old4 in text else 'playDropSound old NOT found')
text = text.replace(old4, new4)

# 5. Simplify second duplicate scheduleNextRefresh to just use computeNextRefresh
old5 = '''        function scheduleNextRefresh(anchor) {
            const now = Date.now();
            const interval = getRefreshIntervalMs();
            if (interval === 0) {
                nextRefreshAt = now;
                updateRefreshCountdown();
                return;
            }
            let next;
            if (anchor && Number.isFinite(new Date(anchor).getTime())) {
                const alignedAnchor = new Date(anchor).getTime();
                const start = alignedAnchor <= now
                    ? alignedAnchor
                    : Math.floor(now / interval) * interval;
                next = start;
                while (next <= now) next += interval;
            } else {
                const start = Math.floor(now / interval) * interval;
                next = start + interval;
            }
            nextRefreshAt = Number.isFinite(next) ? next : now + interval;
            try {
                localStorage.setItem('ozmoeg-next-refresh', String(nextRefreshAt));
            } catch (e) { /* storage may be unavailable */ }
            updateRefreshCountdown();
        }

        function resetRefreshTimer() {'''
new5 = '''        function scheduleNextRefresh(anchor) {
            const interval = getRefreshIntervalMs();
            if (interval <= 0) {
                nextRefreshAt = Date.now() + 60000;
                updateRefreshCountdown();
                return;
            }
            nextRefreshAt = computeNextRefresh();
            try {
                localStorage.setItem('ozmoeg-next-refresh', String(nextRefreshAt));
            } catch (e) { /* storage may be unavailable */ }
            updateRefreshCountdown();
        }

        function resetRefreshTimer() {'''
print('dup schedule old found' if old5 in text else 'dup schedule old NOT found')
text = text.replace(old5, new5)

# 6. Add concurrency guard to loadLiveData start
old6 = '''        async function loadLiveData() {
            try {
                setMarketLoading(currentMarket, true);'''
new6 = '''        async function loadLiveData() {
            if (window._loadingLiveData) return;
            window._loadingLiveData = true;
            try {
                setMarketLoading(currentMarket, true);'''
print('loadLiveData start old found' if old6 in text else 'loadLiveData start old NOT found')
text = text.replace(old6, new6)

# 7. Release concurrency guard in finally
old6b = '''            } catch (e) {
                console.error('Live data refresh failed:', e);
            } finally {
                setMarketLoading(currentMarket, false);'''
new6b = '''            } catch (e) {
                console.error('Live data refresh failed:', e);
            } finally {
                window._loadingLiveData = false;
                setMarketLoading(currentMarket, false);'''
print('loadLiveData finally old found' if old6b in text else 'loadLiveData finally old NOT found')
text = text.replace(old6b, new6b)

# 8. Add manual-refresh listener if not present
if 'manual-refresh' not in text:
    init_old = '''        // Initialise: load data first, then anchor the refresh countdown to the JSON timestamp.
        // This prevents a brief flash of "15:00" before the first fetch completes.
        (async function init() {'''
    init_new = '''        // Manual refresh button (if present) re-fetches immediately and restarts the timer.
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
    if init_old in text:
        text = text.replace(init_old, init_new)
        print('added manual-refresh listener')
    else:
        print('init block not found')
else:
    print('manual-refresh listener already present')

p.write_text(text, encoding='utf-8')
print('done')
