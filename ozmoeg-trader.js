
        // ── Market region toggle (US / AUS) ─────────────────────────────
        let currentMarket = localStorage.getItem('ozmoeg-market') || 'US'; // 'US' or 'AUS'
        // If the URL path indicates the AUS market (e.g., /au), force the market to AUS
        if (window.location.pathname.includes('/au')) {
            currentMarket = 'AUS';
            localStorage.setItem('ozmoeg-market', 'AUS');
        }

        function setMarketButtons() {
            document.querySelectorAll('#market-toggle button').forEach(btn => {
                btn.classList.toggle('active', btn.dataset.market === currentMarket);
            });
        }

        function resetScannerToggleToLive() {
            const toggle = document.getElementById('scanner-toggle');
            if (!toggle) return;
            toggle.querySelectorAll('button').forEach(b => b.classList.remove('active'));
            const liveBtn = toggle.querySelector('button[data-view="live"]');
            if (liveBtn) liveBtn.classList.add('active');
            userSelectedScannerView = 'live';
            saveScannerViewPreference('live');
        }

        function switchMarket(market) {
            currentMarket = market;
            localStorage.setItem('ozmoeg-market', market);
            setMarketButtons();
            updateHeaderText();
            updateDateTime();
            updateCountdown();
            // clear cached selection so the new market's top alert is selected
            localStorage.removeItem('ozmoeg-selected-alert');
            // Reset scanner first-load flag so the correct default view is applied for the new market
            scannerFirstLoadDone = false;
            userSelectedScannerView = null;
            loadLiveData().then(() => renderPlanRules());
        }

        document.addEventListener('click', e => {
            const marketBtn = e.target.closest('#market-toggle button');
            if (marketBtn && marketBtn.dataset.market && marketBtn.dataset.market !== currentMarket) {
                switchMarket(marketBtn.dataset.market);
            }
            const scannerBtn = e.target.closest('#scanner-toggle button');
            if (scannerBtn && !scannerBtn.classList.contains('active') && !scannerBtn.disabled) {
                const view = scannerBtn.dataset.view;
                setScannerToggleActive(view);
                // Switching between Live and Pre/After is only a view change;
                // it must not trigger a network reload. Render from already-fetched data.
                renderScannerView();
            }
        });

        function setScannerToggleActive(view) {
            const toggle = document.getElementById('scanner-toggle');
            if (!toggle) return;
            toggle.querySelectorAll('button').forEach(b => b.classList.remove('active'));
            const target = toggle.querySelector(`button[data-view="${view}"]`);
            if (target) target.classList.add('active');
            userSelectedScannerView = view;
            saveScannerViewPreference(view);
        }

        const alertSelector = document.getElementById('alert-selector');
        if (alertSelector) {
            alertSelector.addEventListener('change', function() {
                localStorage.setItem('ozmoeg-selected-alert', this.value);
                renderSelectedAlert();
            });
        }

        // Persist scanner view preference
        function saveScannerViewPreference(view) {
            localStorage.setItem('ozmoeg-scanner-view', view);
        }
        function loadScannerViewPreference() {
            return localStorage.getItem('ozmoeg-scanner-view') || 'live';
        }

        function updateHeaderText() {
            const sub = document.getElementById('header-subtitle');
            const label = document.getElementById('countdown-label');
            if (!sub || !label) return;
            if (currentMarket === 'AUS') {
                sub.textContent = 'ASX Small-Cap Monitor — Live Market Intelligence';
                label.textContent = '🇦🇺 AUS / ASX Market';
            } else {
                sub.textContent = 'US Small-Cap Scalp Monitor — Live Market Intelligence';
                label.textContent = '🇺🇸 US Market';
            }
        }

        // ASX is 10:00–16:00 AEST/AEDT Monday–Friday, no pre/after market.
        function getSydneyParts(date) {
            const parts = new Intl.DateTimeFormat('en-AU', {
                timeZone: 'Australia/Sydney',
                hour: '2-digit', minute: '2-digit', second: '2-digit',
                hour12: false, weekday: 'long'
            }).formatToParts(date);
            return {
                hour: parseInt(parts.find(p => p.type === 'hour').value),
                minute: parseInt(parts.find(p => p.type === 'minute').value),
                second: parseInt(parts.find(p => p.type === 'second').value),
                weekday: parts.find(p => p.type === 'weekday').value,
                weekdayNum: {'Monday':1,'Tuesday':2,'Wednesday':3,'Thursday':4,'Friday':5,'Saturday':6,'Sunday':0}[parts.find(p => p.type === 'weekday').value]
            };
        }

        function findNextASXOpen(fromTime) {
            let probe = new Date(fromTime);
            let safety = 0;
            while (safety++ < 10080) {
                probe.setMinutes(probe.getMinutes() + 1);
                const p = getSydneyParts(probe);
                if (p.weekdayNum >= 1 && p.weekdayNum <= 5 && p.hour === 10 && p.minute === 0) {
                    return probe;
                }
            }
            return null;
        }

        function findNextASXClose(fromTime) {
            let probe = new Date(fromTime);
            let safety = 0;
            while (safety++ < 480) {
                probe.setMinutes(probe.getMinutes() + 1);
                const p = getSydneyParts(probe);
                if (p.weekdayNum >= 1 && p.weekdayNum <= 5 && p.hour === 16 && p.minute === 0) {
                    return probe;
                }
            }
            return null;
        }

        function updateDateTime() {
            const now = new Date();
            
            // Sydney time display (always show correct AEST/AEDT)
            const sydneyOptions = {
                timeZone: 'Australia/Sydney',
                weekday: 'long', year: 'numeric', month: 'long', day: 'numeric',
                hour: '2-digit', minute: '2-digit', second: '2-digit'
            };
            document.getElementById('datetime-display').textContent = 
                now.toLocaleDateString('en-AU', sydneyOptions);
            
            // Detect if Sydney is in DST (AEDT) or standard (AEST)
            const janOffset = new Date(now.getFullYear(), 0, 1).toLocaleString('en-AU', {timeZone: 'Australia/Sydney', timeZoneName: 'short'});
            const julOffset = new Date(now.getFullYear(), 6, 1).toLocaleString('en-AU', {timeZone: 'Australia/Sydney', timeZoneName: 'short'});
            const isDst = now.toLocaleString('en-AU', {timeZone: 'Australia/Sydney', timeZoneName: 'short'}) === janOffset;
            const tzLabel = isDst ? 'Sydney AEDT' : 'Sydney AEST';
            document.querySelector('.timezone').textContent = tzLabel;
            
            // Market status based on selected region
            let status;
            if (currentMarket === 'AUS') {
                const syd = getSydneyParts(now);
                if (syd.weekdayNum === 0 || syd.weekdayNum === 6) {
                    status = "🔴 Weekend — ASX Closed";
                } else if (syd.hour >= 10 && syd.hour < 16) {
                    status = "🟢 ASX Open — Live monitoring";
                } else {
                    status = "🔴 ASX Closed — Next session at 10:00 Sydney";
                }
            } else {
                const etParts = new Intl.DateTimeFormat('en-US', {
                    timeZone: 'America/New_York',
                    hour: '2-digit', minute: '2-digit', hour12: false, weekday: 'long'
                }).formatToParts(now);
                const etHour = parseInt(etParts.find(p => p.type === 'hour').value);
                const etMin = parseInt(etParts.find(p => p.type === 'minute').value);
                const etWeekday = etParts.find(p => p.type === 'weekday').value;
                const etWeekdayNum = {'Monday':1,'Tuesday':2,'Wednesday':3,'Thursday':4,'Friday':5,'Saturday':6,'Sunday':0}[etWeekday];
                if (etWeekdayNum === 0 || etWeekdayNum === 6) {
                    status = "🔴 Weekend — Markets Closed";
                } else if (etHour < 9 || (etHour === 9 && etMin < 30)) {
                    status = "🟡 Pre-Market — Scanning for setups";
                } else if (etHour < 16) {
                    status = "🟢 Market Open — Live monitoring";
                } else {
                    status = "🟡 After Hours — Pre-market scan mode";
                }
            }
            document.getElementById('market-status').textContent = status;
        }
        updateDateTime();
        setInterval(updateDateTime, 1000);
        
        // US Market Countdown (Sydney-time based)
        let marketOpenTarget = null;
        let marketCloseTarget = null;
        let lastStatus = '';
        let lastMarket = '';

        function setMarketLoading(market, isLoading) {
            // No dedicated spinner currently exists; this prevents loadLiveData from crashing.
            // Future: toggle a loading class on the header/status badge if desired.
        }

        function updateScannerStatusBadge(marketStatus, gainersCount, losersCount) {
            const statusDot = document.getElementById('status-dot');
            const statusText = document.getElementById('scanner-active-text');
            const badge = document.querySelector('.status-badge');
            if (!statusDot || !statusText) return;

            // Use real-time US market status if the JSON scan is stale (older than ~90 min)
            // so weekend/closed sessions don't falsely show "OPEN" from Friday's last scan.
            let status = (marketStatus || 'UNKNOWN').toUpperCase();
            const now = new Date();
            const lastScanAgeMin = window._lastScanTimestamp
                ? Math.max(0, (now.getTime() - new Date(window._lastScanTimestamp).getTime()) / 60000)
                : Infinity;
            const realTimeStatus = getCurrentUSMarketStatus ? getCurrentUSMarketStatus() : status;
            if (lastScanAgeMin > 90 && ['OPEN','PRE-MARKET','AFTER-HOURS'].includes(realTimeStatus)) {
                status = realTimeStatus;
            }
            // If real-time status is closed/weekend, always prefer it regardless of JSON age.
            if (realTimeStatus === 'CLOSED' || realTimeStatus === 'WEEKEND') {
                status = realTimeStatus;
            }
            currentMarketStatus = status;

            const colorMap = {
                'OPEN': '#22c55e',
                'PRE-MARKET': '#f59e0b',
                'AFTER-HOURS': '#f59e0b',
                'CLOSED': '#ef4444',
                'WEEKEND': '#ef4444',
                'UNKNOWN': '#9ca3af'
            };
            const labelMap = {
                'OPEN': 'Live Scanner — Market Open',
                'PRE-MARKET': 'Scanner Active — Pre-Market',
                'AFTER-HOURS': 'Scanner Active — After Hours',
                'CLOSED': 'Scanner Idle — Market Closed',
                'WEEKEND': 'Scanner Idle — Weekend',
                'UNKNOWN': 'Scanner Status Unknown'
            };
            const color = colorMap[status] || colorMap['UNKNOWN'];

            statusDot.style.cssText = `width:8px;height:8px;border-radius:50%;background:${color};animation:pulse 2s infinite;`;
            if (badge) {
                badge.style.cssText = `display:flex;align-items:center;gap:0.5rem;background:${color}26;border:1px solid ${color};padding:0.4rem 1rem;border-radius:20px;font-size:0.8rem;font-weight:500;color:${color};`;
            }
            statusText.textContent = labelMap[status] || labelMap['UNKNOWN'];

            // Show a visible data-source warning when the scan returned no raw lists
            // but the market phase expects data (open, pre-market, after-hours).
            let warningEl = document.getElementById('data-source-warning');
            if (!warningEl) {
                warningEl = document.createElement('div');
                warningEl.id = 'data-source-warning';
                warningEl.style.cssText = 'margin-top:0.5rem;padding:0.5rem 0.75rem;border-radius:6px;background:rgba(239,68,68,0.15);color:#ff6b6b;font-size:0.8rem;border-left:3px solid #ef4444;';
                const headerStatus = document.querySelector('.header-status');
                if (headerStatus) headerStatus.appendChild(warningEl);
            }

            if (['OPEN','PRE-MARKET','AFTER-HOURS'].includes(status) && gainersCount === 0 && losersCount === 0) {
                warningEl.textContent = '⚠️ Data source returned 0 gainers/losers. The website will stay on the last known data until the API connection is restored.';
                warningEl.style.display = 'block';
            } else {
                warningEl.style.display = 'none';
            }
        }

        function findNextMarketOpen(fromTime) {

            let probe = new Date(fromTime);
            let safety = 0;
            while (safety++ < 10080) { // Max 1 week
                probe.setMinutes(probe.getMinutes() + 1);
                const pp = new Intl.DateTimeFormat('en-US', {
                    timeZone: 'America/New_York',
                    hour: '2-digit', minute: '2-digit', hour12: false, weekday: 'long'
                }).formatToParts(probe);
                const ph = parseInt(pp.find(p => p.type === 'hour').value);
                const pm = parseInt(pp.find(p => p.type === 'minute').value);
                const pw = pp.find(p => p.type === 'weekday').value;
                const pwn = {'Monday':1,'Tuesday':2,'Wednesday':3,'Thursday':4,'Friday':5,'Saturday':6,'Sunday':0}[pw];
                if (pwn >= 1 && pwn <= 5 && ph === 9 && pm === 30) {
                    return probe;
                }
            }
            return null;
        }
        
        function findNextMarketClose(fromTime) {
            // Walk forward minute-by-minute from fromTime until ET shows Mon-Fri 16:00
            let probe = new Date(fromTime);
            let safety = 0;
            while (safety++ < 480) { // Max 8 hours
                probe.setMinutes(probe.getMinutes() + 1);
                const pp = new Intl.DateTimeFormat('en-US', {
                    timeZone: 'America/New_York',
                    hour: '2-digit', minute: '2-digit', hour12: false, weekday: 'long'
                }).formatToParts(probe);
                const ph = parseInt(pp.find(p => p.type === 'hour').value);
                const pm = parseInt(pp.find(p => p.type === 'minute').value);
                const pw = pp.find(p => p.type === 'weekday').value;
                const pwn = {'Monday':1,'Tuesday':2,'Wednesday':3,'Thursday':4,'Friday':5,'Saturday':6,'Sunday':0}[pw];
                if (pwn >= 1 && pwn <= 5 && ph === 16 && pm === 0) {
                    return probe;
                }
            }
            return null;
        }

        function getETParts(date) {
            const parts = new Intl.DateTimeFormat('en-US', {
                timeZone: 'America/New_York',
                hour: '2-digit', minute: '2-digit', second: '2-digit',
                hour12: false, weekday: 'long', year: 'numeric', month: 'numeric', day: 'numeric'
            }).formatToParts(date);
            const get = type => parts.find(p => p.type === type).value;
            const weekdayNum = {'Monday':1,'Tuesday':2,'Wednesday':3,'Thursday':4,'Friday':5,'Saturday':6,'Sunday':0}[get('weekday')];
            return {
                hour: parseInt(get('hour'), 10),
                minute: parseInt(get('minute'), 10),
                second: parseInt(get('second'), 10),
                weekday: get('weekday'),
                weekdayNum,
                year: parseInt(get('year'), 10),
                month: parseInt(get('month'), 10),
                day: parseInt(get('day'), 10)
            };
        }


        function getCurrentUSMarketStatus(now = new Date()) {
            const et = getETParts(now);
            // Sunday (0) and Saturday (6) are weekend all day.
            if (et.weekdayNum === 0 || et.weekdayNum >= 6) return 'WEEKEND';
            // Friday after 16:00 ET is closed for the weekend.
            if (et.weekdayNum === 5 && (et.hour > 16 || (et.hour === 16 && et.minute >= 0))) return 'WEEKEND';
            if (et.hour < 9 || (et.hour === 9 && et.minute < 30)) {
                if (et.hour >= 4) return 'PRE-MARKET';
                return 'CLOSED';
            }
            if (et.hour >= 16) return 'AFTER-HOURS';
            return 'OPEN';
        }

        function getETDateFor(year, month, day, hour, minute) {
            // Build a Sydney-time Date whose ET components match the requested values by walking from midnight ET.
            // Start with the same calendar day in Sydney; then adjust minute-by-minute until ET matches.
            let probe = new Date(year, month - 1, day, hour, minute);
            for (let safety = 0; safety < 2880; safety++) {
                const et = getETParts(probe);
                if (et.year === year && et.month === month && et.day === day && et.hour === hour && et.minute === minute) {
                    return probe;
                }
                probe.setMinutes(probe.getMinutes() + 1);
            }
            return null;
        }

        function getUSMarketPhase(now) {
            const et = getETParts(now);
            const weekdayNum = et.weekdayNum;
            const minutes = et.hour * 60 + et.minute;
            const isWeekday = weekdayNum >= 1 && weekdayNum <= 5;
            const tomorrowNum = (weekdayNum + 1) % 7;

            // Phase boundaries in ET minutes from midnight
            const PRE_START = 4 * 60;      // 04:00
            const OPEN_START = 9 * 60 + 30; // 09:30
            const POST_START = 16 * 60;   // 16:00
            const DAY_END = 20 * 60;      // 20:00

            let phase, targetMinutes, statusText, phaseStart, phaseEnd;
            let targetWeekday = weekdayNum;

            if (!isWeekday) {
                // Weekend: treat as closed; target next Monday 04:00 pre-market.
                phase = 'closed';
                statusText = '🔴 Weekend — Pre-market in';
                targetWeekday = 1; // Monday
                targetMinutes = PRE_START;
                phaseStart = null;
                phaseEnd = null;
            } else if (minutes >= POST_START && minutes < DAY_END) {
                phase = 'post';
                statusText = '🟡 After Hours — Closes in';
                targetMinutes = DAY_END;
                phaseStart = POST_START;
                phaseEnd = DAY_END;
            } else if (minutes >= OPEN_START && minutes < POST_START) {
                phase = 'open';
                statusText = '🟢 Market Open — After hours in';
                targetMinutes = POST_START;
                phaseStart = OPEN_START;
                phaseEnd = POST_START;
            } else if (minutes >= PRE_START && minutes < OPEN_START) {
                phase = 'pre';
                statusText = '🟡 Pre-Market — Opens in';
                targetMinutes = OPEN_START;
                phaseStart = PRE_START;
                phaseEnd = OPEN_START;
            } else {
                // Closed overnight (00:00-04:00 or 20:00-24:00 ET)
                phase = 'closed';
                statusText = '🔴 Closed — Pre-market in';
                targetMinutes = PRE_START;
                if (minutes >= DAY_END) {
                    targetWeekday = tomorrowNum;
                }
                if (targetWeekday === 0 || targetWeekday === 6) targetWeekday = 1;
                phaseStart = null;
                phaseEnd = null;
            }

            // Calculate target Date in local (Sydney) time
            let probe = new Date(now);
            while (getETParts(probe).weekdayNum !== targetWeekday) {
                probe.setDate(probe.getDate() + 1);
            }
            const targetProbe = getETParts(probe);
            const target = getETDateFor(targetProbe.year, targetProbe.month, targetProbe.day,
                Math.floor(targetMinutes / 60), targetMinutes % 60);

            return { phase, target: target || probe, statusText, phaseStart, phaseEnd };
        }

        function updateTimeline(phase, phaseStart, phaseEnd, now) {
            const timeline = document.getElementById('market-timeline');
            const notch = document.getElementById('market-timeline-notch');
            if (!timeline || !notch) return;

            if (!phase) {
                timeline.style.display = 'none';
                return;
            }
            timeline.style.display = 'block';

            // Segment order and positions (each 25%)
            const segments = ['pre', 'open', 'post', 'closed'];
            const segIndex = segments.indexOf(phase);
            const segCount = segments.length;
            const segWidth = 100 / segCount;
            const segCenter = segWidth * segIndex + segWidth / 2;

            let progress = 0;
            if (phaseStart !== null && phaseEnd !== null && phaseEnd > phaseStart) {
                const et = getETParts(now);
                const minutes = et.hour * 60 + et.minute;
                progress = Math.max(0, Math.min(1, (minutes - phaseStart) / (phaseEnd - phaseStart)));
            }
            const left = segWidth * segIndex + segWidth * progress;
            notch.style.left = `${left}%`;

            // Highlight active label and dim other segments slightly
            timeline.querySelectorAll('.market-timeline-labels span').forEach(span => {
                span.classList.toggle('active', span.dataset.phase === phase);
            });
            timeline.querySelectorAll('.market-timeline-segment').forEach(seg => {
                seg.style.opacity = seg.dataset.phase === phase ? '1' : '0.45';
            });
        }

        function updateCountdown() {
            const now = new Date(); // Browser local time = Sydney time

            // If the market mode changed since the last tick, reset cached targets immediately.
            if (lastMarket !== currentMarket) {
                marketOpenTarget = null;
                marketCloseTarget = null;
                lastStatus = '';
                lastMarket = currentMarket;
            }

            if (currentMarket === 'AUS') {
                const syd = getSydneyParts(now);
                const isMarketOpen = syd.weekdayNum >= 1 && syd.weekdayNum <= 5 && syd.hour >= 10 && syd.hour < 16;
                updateTimeline(null, 0, 0, now);

                if (isMarketOpen) {
                    if (!marketCloseTarget || marketCloseTarget <= now || lastStatus !== 'open') {
                        marketCloseTarget = findNextASXClose(now);
                        lastStatus = 'open';
                    }
                    const diff = marketCloseTarget - now;
                    const h = Math.floor(diff / (1000 * 60 * 60));
                    const m = Math.floor((diff % (1000 * 60 * 60)) / (1000 * 60));
                    const s = Math.floor((diff % (1000 * 60)) / 1000);
                    document.getElementById('countdown-status').textContent = '🟢 ASX OPEN — Closing in';
                    document.getElementById('countdown-timer').textContent =
                        `${String(h).padStart(2,'0')}:${String(m).padStart(2,'0')}:${String(s).padStart(2,'0')}`;
                    document.getElementById('countdown-timer').className = 'countdown-timer open';
                    const closeStr = marketCloseTarget.toLocaleTimeString('en-AU', {hour: '2-digit', minute:'2-digit'});
                    document.getElementById('countdown-next').textContent = `Closes at ${closeStr} today (Sydney time)`;
                    return;
                }

                if (!marketOpenTarget || marketOpenTarget <= now || lastStatus === 'open') {
                    marketOpenTarget = findNextASXOpen(now);
                    marketCloseTarget = null;
                    lastStatus = 'closed';
                }
                let statusText;
                if (syd.weekdayNum === 0 || syd.weekdayNum === 6) {
                    statusText = "🔴 Weekend — ASX Opens Monday";
                } else if (syd.hour >= 16) {
                    const tomorrowWeekday = (syd.weekdayNum + 1) % 7;
                    statusText = (tomorrowWeekday === 0 || tomorrowWeekday === 6)
                        ? "🔴 ASX Closed — Opens Monday"
                        : "🔴 ASX Closed — Opens Tomorrow 10:00";
                } else {
                    statusText = "🔴 ASX Closed — Opens Today 10:00";
                }
                const diff = marketOpenTarget - now;
                const d = Math.floor(diff / (1000 * 60 * 60 * 24));
                const h = Math.floor((diff % (1000 * 60 * 60 * 24)) / (1000 * 60 * 60));
                const m = Math.floor((diff % (1000 * 60 * 60)) / (1000 * 60));
                const s = Math.floor((diff % (1000 * 60)) / 1000);
                const timerStr = d > 0
                    ? `${d}d ${String(h).padStart(2,'0')}:${String(m).padStart(2,'0')}:${String(s).padStart(2,'0')}`
                    : `${String(h).padStart(2,'0')}:${String(m).padStart(2,'0')}:${String(s).padStart(2,'0')}`;
                const dayNames = ['Sunday','Monday','Tuesday','Wednesday','Thursday','Friday','Saturday'];
                const sydneyDay = dayNames[marketOpenTarget.getDay()];
                const sydneyTime = marketOpenTarget.toLocaleTimeString('en-AU', {hour: '2-digit', minute:'2-digit'});
                const sydneyDate = marketOpenTarget.toLocaleDateString('en-AU', {weekday:'short', month:'short', day:'numeric'});
                document.getElementById('countdown-status').textContent = statusText;
                document.getElementById('countdown-timer').textContent = timerStr;
                document.getElementById('countdown-timer').className = 'countdown-timer closed';
                document.getElementById('countdown-next').textContent = `Opens ${sydneyDay} ${sydneyDate} at ${sydneyTime} (Sydney time)`;
                return;
            }

            // US Market phase-aware countdown
            const phaseInfo = getUSMarketPhase(now);
            const target = phaseInfo.target;
            updateTimeline(phaseInfo.phase, phaseInfo.phaseStart, phaseInfo.phaseEnd, now);

            const diff = target - now;
            const d = Math.floor(diff / (1000 * 60 * 60 * 24));
            const h = Math.floor((diff % (1000 * 60 * 60 * 24)) / (1000 * 60 * 60));
            const m = Math.floor((diff % (1000 * 60 * 60)) / (1000 * 60));
            const s = Math.floor((diff % (1000 * 60)) / 1000);
            const timerStr = d > 0
                ? `${d}d ${String(h).padStart(2,'0')}:${String(m).padStart(2,'0')}:${String(s).padStart(2,'0')}`
                : `${String(h).padStart(2,'0')}:${String(m).padStart(2,'0')}:${String(s).padStart(2,'0')}`;

            const isOpen = phaseInfo.phase === 'open';
            document.getElementById('countdown-status').textContent = phaseInfo.statusText;
            document.getElementById('countdown-timer').textContent = timerStr;
            document.getElementById('countdown-timer').className = isOpen ? 'countdown-timer open' : 'countdown-timer closed';

            const dayNames = ['Sunday','Monday','Tuesday','Wednesday','Thursday','Friday','Saturday'];
            const sydneyDay = dayNames[target.getDay()];
            const sydneyTime = target.toLocaleTimeString('en-AU', {hour: '2-digit', minute:'2-digit'});
            const sydneyDate = target.toLocaleDateString('en-AU', {weekday:'short', month:'short', day:'numeric'});
            const etTime = target.toLocaleTimeString('en-US', {timeZone: 'America/New_York', hour: '2-digit', minute:'2-digit'});
            let nextLabel;
            if (phaseInfo.phase === 'pre') nextLabel = 'Market open';
            else if (phaseInfo.phase === 'open') nextLabel = 'After hours';
            else if (phaseInfo.phase === 'post') nextLabel = 'After hours close';
            else nextLabel = 'Pre-market';
            document.getElementById('countdown-next').textContent =
                `${nextLabel} ${sydneyDay} ${sydneyDate} at ${sydneyTime} Sydney / ${etTime} ET`;
        }
        updateHeaderText();
        setMarketButtons();
        updateCountdown();
        setInterval(updateCountdown, 1000);

        // Live data refresh: fetch latest scan results from ozmoeg-latest.json.
        // Intervals are driven by Sydney wall-clock time and US market status:
        //   CATALYST WATCHLIST (Sydney 17:00 → 17:59): every 1 minute, news-only mode
        //   PRE-MARKET (Sydney 18:00 → 23:59)            : every 1 minute
        //   OPEN / AFTER-HOURS / after 23:59 Syd          : every 10 minutes
        //   CLOSED / WEEKEND                              : no auto-fetch
        const CLOSED_REFRESH_INTERVAL_MS = 0;          // disabled when markets are closed
        const IDLE_REFRESH_INTERVAL_MS = 600000;        // 10 min during US open/after-hours
        const ACTIVE_REFRESH_INTERVAL_MS = 60000;     // 1 min during Sydney active window (17:00-23:59)
        let liveResults = [];
        let displayedResults = [];
        let userSelectedScannerView = null;
        let scannerFirstLoadDone = false;
        let liveLastUpdated = new Date();
        let currentMarketStatus = 'OPEN';
        let refreshTimerId = null;

        // Active = Sydney window for the website 1-minute refresh: 17:00 to 23:59 Sydney time.
        // Uses Intl format parts instead of Date.parse to avoid browser-timezone ambiguity.
        function isActiveTradingWindow(now = new Date()) {
            try {
                const fmt = new Intl.DateTimeFormat('en-AU', {
                    timeZone: 'Australia/Melbourne',
                    hour: 'numeric',
                    minute: 'numeric',
                    hour12: false,
                });
                const parts = fmt.formatToParts(now);
                let h = 0, m = 0;
                for (const p of parts) {
                    if (p.type === 'hour') h = parseInt(p.value, 10);
                    if (p.type === 'minute') m = parseInt(p.value, 10);
                }
                const mins = h * 60 + m;
                const start = 17 * 60;      // Sydney 17:00
                const end = 24 * 60;        // Sydney 24:00 (exclusive)
                return mins >= start && mins < end;
            } catch (e) {
                // Fallback: assume active only if US market status is PRE-MARKET.
                return currentMarketStatus === 'PRE-MARKET';
            }
        }

        function getRefreshIntervalMs() {
            const usStatus = getCurrentUSMarketStatus ? getCurrentUSMarketStatus() : currentMarketStatus;
            if (usStatus === 'CLOSED' || usStatus === 'WEEKEND') {
                // Catalyst watchlist scans every minute during Sydney 17:00-17:59 even though the US market is closed.
                return isActiveTradingWindow() ? ACTIVE_REFRESH_INTERVAL_MS : CLOSED_REFRESH_INTERVAL_MS;
            }
            if (isActiveTradingWindow()) return ACTIVE_REFRESH_INTERVAL_MS;
            // US OPEN, AFTER-HOURS, and pre-market outside the Sydney 17:00-23:59 window refresh every 10 minutes.
            return IDLE_REFRESH_INTERVAL_MS;
        }

        // Compute the next wall-clock aligned refresh.
        function computeNextRefresh() {
            const interval = getRefreshIntervalMs();
            const now = Date.now();
            if (interval <= 0) {
                // Markets are closed; check again in 60 seconds so the label can recover if status changes.
                return now + 60000;
            }
            // Round up to the next interval boundary from the epoch.
            const next = Math.ceil(now / interval) * interval;
            // If we are exactly on a boundary, add one interval so we don't fire immediately.
            return next <= now ? next + interval : next;
        }

        // Persist the next refresh time across page reloads so the countdown is always
        // anchored to the cron schedule, not to when the browser happens to open.
        let nextRefreshAt = (() => {
            try {
                const stored = localStorage.getItem('ozmoeg-next-refresh');
                const ts = stored ? parseInt(stored, 10) : 0;
                if (ts && !isNaN(ts) && ts > Date.now()) return ts;
            } catch (e) { /* storage may be unavailable */ }
            const initial = computeNextRefresh();
            return Number.isFinite(initial) ? initial : Date.now() + (isActiveTradingWindow() ? ACTIVE_REFRESH_INTERVAL_MS : IDLE_REFRESH_INTERVAL_MS);
        })();

        function updateRefreshCountdown() {
            const label = document.getElementById('page-refresh-label');
            const lastLabel = document.getElementById('last-refresh-label');
            if (lastLabel && window._lastScanTimestamp) {
                const jsonAgeMin = Math.max(0, (Date.now() - new Date(window._lastScanTimestamp).getTime()) / 60000);
                const stale = jsonAgeMin > 5;  // GitHub Pages can lag a few minutes
                const ageText = stale ? ` ⚠️ ${Math.round(jsonAgeMin)}m stale` : '';
                lastLabel.textContent = `Last refresh: ${formatScanTimestamp(window._lastScanTimestamp)}${ageText}`;
                lastLabel.style.color = stale ? 'var(--danger)' : '';
            }
            if (!label) return;
            const usStatus = getCurrentUSMarketStatus ? getCurrentUSMarketStatus() : currentMarketStatus;
            const interval = getRefreshIntervalMs();
            const active = (usStatus === 'PRE-MARKET' && isActiveTradingWindow()) ||
                            (usStatus === 'OPEN' && isActiveTradingWindow());
            label.classList.toggle('active-refresh', active);

            let modeLabel;
            if (isActiveTradingWindow() && usStatus === 'CLOSED') {
                modeLabel = '(1-min catalyst watchlist mode)';
            } else if (usStatus === 'PRE-MARKET' && isActiveTradingWindow()) {
                modeLabel = '(1-min pre-market mode)';
            } else if (usStatus === 'OPEN') {
                modeLabel = '(10-min open market mode)';
            } else if (usStatus === 'AFTER-HOURS') {
                modeLabel = '(10-min after-hours mode)';
            } else if (usStatus === 'PRE-MARKET' && !isActiveTradingWindow()) {
                modeLabel = '(10-min pre-market mode)';
            } else {
                modeLabel = '(markets closed)';
            }

            if (interval === 0) {
                const nextOpen = findNextMarketOpen(new Date());
                let openText;
                if (nextOpen) {
                    const usOpen = nextOpen.toLocaleString('en-AU', { timeZone: 'America/New_York', weekday: 'short', hour: '2-digit', minute: '2-digit', hour12: true });
                    const sydneyOpen = nextOpen.toLocaleString('en-AU', { timeZone: 'Australia/Sydney', weekday: 'short', hour: '2-digit', minute: '2-digit', hour12: true });
                    openText = `Opens ${usOpen} ET / ${sydneyOpen} Sydney`;
                } else {
                    openText = 'market closed';
                }
                label.textContent = `⏸ No scans — ${usStatus.toLowerCase()} (${openText})`;
                return;
            }

            const remaining = Math.max(0, nextRefreshAt - Date.now());
            const totalSeconds = Math.ceil(remaining / 1000);
            const m = Math.floor(totalSeconds / 60);
            const s = totalSeconds % 60;
            const active = isActiveTradingWindow();
            label.classList.toggle('active-refresh', active);
            label.textContent = `${active ? '⚡ ' : ''}Next refresh: ${m}:${String(s).padStart(2, '0')} ${modeLabel}`;
        }

        // Schedule the next refresh relative to the actual data timestamp.
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
                next = start;
                while (next <= now) next += interval;
            }
            nextRefreshAt = Number.isFinite(next) ? next : now + (isActiveTradingWindow() ? ACTIVE_REFRESH_INTERVAL_MS : IDLE_REFRESH_INTERVAL_MS);
            // Persist so the countdown survives page reloads.
            try {
                localStorage.setItem('ozmoeg-next-refresh', String(nextRefreshAt));
            } catch (e) { /* storage may be unavailable */ }
            updateRefreshCountdown();
        }

        function resetRefreshTimer() {
            if (refreshTimerId) clearInterval(refreshTimerId);
            scheduleNextRefresh(window._lastScanTimestamp);
            refreshTimerId = setInterval(() => {
                const interval = getRefreshIntervalMs();
                if (interval === 0) {
                    // Markets are closed; do not fetch, just update the label.
                    updateRefreshCountdown();
                    return;
                }
                // Persist every tick so the value stays current across reloads.
                try {
                    localStorage.setItem('ozmoeg-next-refresh', String(nextRefreshAt));
                } catch (e) { /* storage may be unavailable */ }
                if (Date.now() >= nextRefreshAt) {
                    // Advance to the next boundary before fetching so overlapping ticks
                    // don't fire multiple loads while this one is in flight.
                    const candidate = computeNextRefresh();
                    nextRefreshAt = Number.isFinite(candidate) ? candidate : Date.now() + interval;
                    loadLiveData();
                } else {
                    updateRefreshCountdown();
                }
            }, 1000);
        }

        function fmtCurrency(n) {
            if (n === undefined || n === null || isNaN(n)) return '—';
            return '$' + parseFloat(n).toFixed((parseFloat(n) % 1 === 0) ? 2 : 4).replace(/\.?0+$/, '');
        }

        function impactLabel(score, r) {
            const auState = r && r.au_state;
            if (auState === 'AU-LIMITED' || (r && r.plan && r.plan.confidence === 'AU-LIMITED')) {
                return { text: '🇦🇺 AU-LIMITED', cls: 'impact-au-limited' };
            }
            if (auState === 'AU-ANNOUNCEMENT') {
                return { text: '🇦🇺 AU-ANNOUNCEMENT', cls: 'impact-au-limited' };
            }
            if (score >= 4) return { text: `🔥 High (${score})`, cls: 'impact-high' };
            if (score >= 2) return { text: `⚡ Medium (${score})`, cls: 'impact-medium' };
            return { text: `🌱 Low (${score})`, cls: 'impact-low' };
        }
        function getAlertMaxScore(r) {
            const news = r.news || {};
            return news.max_score !== undefined ? news.max_score : (news.headlines || []).reduce((m, h) => Math.max(m, h.score || 0), 0);
        }

        function renderPlanRules() {
            const list = document.getElementById('plan-rules-list');
            if (!list) return;
            const stats = window._lastScanStats || {};
            // If no scan stats yet, leave the static rules list in place.
            if (!stats.market && !Object.keys(stats.au_filters || {}).length && !Object.keys(stats.us_filters || {}).length) return;
            const auFilters = stats.au_filters || {};
            const usFilters = stats.us_filters || {};
            const isAu = currentMarket === 'AUS';
            if (isAu && Object.keys(auFilters).length) {
                const priceMin = auFilters.price_min;
                const priceMax = auFilters.price_max;
                const mktMin = auFilters.market_cap_min;
                const mktMax = auFilters.market_cap_max;
                const moveMin = auFilters.premarket_pct_min;
                const rvolMin = auFilters.rvol_min;
                const dollarVolMin = auFilters.volume_value_aud_min;
                list.innerHTML = `
                    <li>Price range: A$${priceMin}–A$${priceMax} ✅</li>
                    <li>Market cap: A$${(mktMin/1e6).toFixed(1)}M–A$${(mktMax/1e6).toFixed(0)}M ✅</li>
                    <li>Pre-market/active mover ≥${moveMin}% or RVOL ≥${rvolMin}x ✅</li>
                    <li>Approx. dollar volume ≥A$${dollarVolMin.toLocaleString()} ✅</li>
                    <li>Near demand zone, candlestick signal, price above VWAP — context, not hard filters ✅</li>
                    <li>ASX announcement preferred; limited-catalyst rows flagged 🇦🇺 AU-LIMITED ✅</li>
                    <li>Risk:Reward ≥2.0:1 ✅</li>
                    <li>Position sizing: ~A$100 test per trade ✅</li>
                `;
            } else if (Object.keys(usFilters).length) {
                const fm = (n) => n >= 1_000_000 ? `$${(n/1e6).toFixed(0)}M` : `$${(n/1e3).toFixed(0)}K`;
                const priceMin = usFilters.price_min;
                const priceMax = usFilters.price_max;
                const mktMin = usFilters.market_cap_min;
                const mktMax = usFilters.market_cap_max;
                const rvolMin = usFilters.rvol_min;
                const moveMin = usFilters.premarket_pct_min;
                const volumeMin = usFilters.volume_min;
                const avgDvMin = usFilters.min_avg_daily_dollar_volume;
                const maxFloat = usFilters.max_float_shares;
                const vfrMin = usFilters.min_volume_float_ratio;
                const moveMax = usFilters.move_max_pct;
                const moveTier2 = usFilters.move_tier_2_max;
                const tinyMoveMax = usFilters.tiny_cap_move_max_pct;
                const tinyMoveTier2 = usFilters.tiny_cap_move_tier_2_max;
                const extRvol = usFilters.extended_hours_rvol_min;
                const extMove = usFilters.extended_hours_premarket_pct_min;
                const extAvgDv = usFilters.extended_hours_min_avg_daily_dollar_volume;
                list.innerHTML = `
                    <li>Price range: $${priceMin}–$${priceMax} ✅</li>
                    <li>Market cap: ${fm(mktMin)}–${fm(mktMax)} ✅</li>
                    <li>Active mover ≥${moveMin}% or RVOL ≥${rvolMin}x (pre/after-hours ≥${extMove}% or RVOL ≥${extRvol}x) ✅</li>
                    <li>Minimum volume ${volumeMin.toLocaleString()} shares; avg dollar volume ≥${fm(avgDvMin)} (${fm(extAvgDv)} in pre/after-hours) ✅</li>
                    <li>Max float ${maxFloat.toLocaleString()} shares; volume/float ≥${vfrMin}x (≥1.0x for $5M–$10M tiny-caps) ✅</li>
                    <li>Move cap ${moveMax}% (tier-2 exception up to ${moveTier2}% with RVOL ≥${usFilters.move_tier_2_min_rvol}x &amp; VFR ≥${usFilters.move_tier_2_min_float_ratio}x); tiny-cap tier up to ${tinyMoveTier2}% ✅</li>
                    <li>Near demand zone, candlestick signal, price above VWAP — context, not hard filters ✅</li>
                    <li>News catalyst scored ≥3 from ≥2 sources; gating relaxed in extended hours and regular-hours US ✅</li>
                    <li>Red flags block: offering, dilution, bankruptcy, delisting, SEC investigation, restated, going concern, short report ✅</li>
                    <li>Volume indicator: today's volume vs 3-month average (RVOL) ✅</li>
                    <li>Risk:Reward ≥2.0:1 ✅</li>
                    <li>Position sizing: R = account balance × max daily loss % ÷ max trades per day; shares = R ÷ (entry − stop) ✅</li>
                    <li>Scale out: 50% at 2R (T1), 25% at 3R (T2), trail rest above 5R (T3); breakeven stop after +1% ✅</li>
                `;
            } else {
                list.innerHTML = `
                    <li>Price range: $0.50–$30 ✅</li>
                    <li>Market cap: $5M–$300M ✅</li>
                    <li>Active mover ≥5% or RVOL ≥2.0x (≥1.0x in pre/after-hours) ✅</li>
                    <li>Minimum volume 100,000 shares; avg dollar volume ≥$2M ✅</li>
                    <li>Max float 50M shares; volume/float ≥0.5x (≥1.0x for $5M–$10M tiny-caps) ✅</li>
                    <li>Move cap 40% (tier-2 exception up to 80% with RVOL ≥3.0x &amp; VFR ≥2.0x); tiny-cap tier up to 300% ✅</li>
                    <li>Near demand zone, candlestick signal, price above VWAP — context, not hard filters ✅</li>
                    <li>News catalyst scored ≥3 from ≥2 sources; gating relaxed in extended hours and regular-hours US ✅</li>
                    <li>Red flags block: offering, dilution, bankruptcy, delisting, SEC investigation, restated, going concern, short report ✅</li>
                    <li>Volume indicator: today's volume vs 3-month average (RVOL) ✅</li>
                    <li>Risk:Reward ≥2.0:1 ✅</li>
                    <li>Position sizing: R = account balance × max daily loss % ÷ max trades per day; shares = R ÷ (entry − stop) ✅</li>
                    <li>Scale out: 50% at 2R (T1), 25% at 3R (T2), trail rest above 5R (T3); breakeven stop after +1% ✅</li>
                `;
            }
        }

        function fmtPct(base, val) {
            if (!base || !val) return '';
            const pct = ((val - base) / base) * 100;
            return ` (${pct >= 0 ? '+' : ''}${pct.toFixed(1)}%)`;
        }

        function escapeHtml(str) {
            return String(str || '').replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;');
        }

        // ---- Live/current price lookup for tracker ----
        // Prefer a real-time public quote so the tracker is not stuck with a stale
        // scan snapshot. Fall back to the last scan price only when live data fails.
        function getPriceFromAllGainers(ticker) {
            const gainers = window._lastAllGainers || [];
            const match = gainers.find(g => {
                const t = g.ticker || g;
                return (t.symbol || '').toUpperCase() === (ticker || '').toUpperCase();
            });
            if (!match) return null;
            const t = match.ticker || match;
            const v = match.values || {};
            // Use the real-time price fields first; never fall back to the prior close
            // because that creates a misleading "current price" for gap-up/gap-down stocks.
            const price = parseFloat(v.price || t.pprice || 0);
            return price > 0 ? price : null;
        }

        // Get truly fresh price - bypasses JSON cache entirely
        async function getFreshPrice(ticker) {
            // Skip the JSON cache; go directly to Yahoo or another source
            let price = await fetchPublicQuote(ticker);
            if (price) return { price, source: 'live', timestamp: new Date() };
            return null;
        }

        function isExtendedHoursSession() {
            return currentMarket !== 'AUS' && (currentMarketStatus === 'PRE-MARKET' || currentMarketStatus === 'AFTER-HOURS');
        }

        async function resolveLiveEntryPrice(ticker, fallbackEntry) {
            // During US pre/after-market we must base the trade plan on the current
            // live price, because the scanner's plan was computed from the prior
            // regular-session close and will never be fillable in extended hours.
            if (!isExtendedHoursSession()) {
                return { price: fallbackEntry, source: 'scan', liveAvailable: false };
            }
            const resolved = await resolveCurrentPrice(ticker);
            if (resolved && resolved.price > 0 && Math.abs(resolved.price - fallbackEntry) > 0.0001) {
                return { price: resolved.price, source: resolved.source || 'live', liveAvailable: true };
            }
            return { price: fallbackEntry, source: 'scan', liveAvailable: false };
        }

        function formatScanTimestamp(dateObj) {
            if (!dateObj || isNaN(dateObj)) return '';
            return dateObj.toLocaleString('en-AU', {
                timeZone: 'Australia/Sydney',
                weekday: 'short', month: 'short', day: 'numeric',
                hour: '2-digit', minute: '2-digit'
            });
        }

        async function fetchPublicQuote(ticker) {
            try {
                const now = new Date();
                const period2 = Math.floor(now.getTime() / 1000);
                // 1h range with 1m bars captures pre/after-hours trade if available
                const url = `https://query1.finance.yahoo.com/v8/finance/chart/${encodeURIComponent(ticker)}?interval=1m&range=1h&period2=${period2}`;
                const res = await fetch(url, { cache: 'no-store' });
                if (!res.ok) return null;
                const data = await res.json();
                const result = data?.chart?.result?.[0];
                if (!result) return null;

                // Prefer the latest real-time/extended-hours meta fields
                const meta = result.meta || {};
                const latestPrice = (
                    parseFloat(meta.regularMarketPrice || 0)
                    || parseFloat(meta.previousClose || 0)
                );
                if (latestPrice > 0) return latestPrice;

                // Fallback to the last non-null 1m close
                const quote = result?.indicators?.quote?.[0] || {};
                const closes = quote.close || [];
                for (let i = closes.length - 1; i >= 0; i--) {
                    if (closes[i] != null) return parseFloat(closes[i]);
                }
                // Try adjclose as last resort
                const adjclose = result?.indicators?.adjclose?.[0]?.adjclose || [];
                for (let i = adjclose.length - 1; i >= 0; i--) {
                    if (adjclose[i] != null) return parseFloat(adjclose[i]);
                }
                return null;
            } catch (e) {
                console.warn('Public quote fetch failed for', ticker, e);
                return null;
            }
        }

        async function resolveCurrentPrice(ticker) {
            // 1. Use live Webull quotes fetched by the backend (same source as the scanner).
            const liveQuotes = window._lastLiveQuotes || {};
            const live = liveQuotes[(ticker || '').toUpperCase()];
            if (live && live.price > 0) {
                return { price: live.price, source: 'live', timestamp: new Date(live._timestamp || window._lastScanTimestamp || Date.now()) };
            }
            // 2. Try a public quote as a last resort.
            let price = await fetchPublicQuote(ticker);
            if (price) return { price, source: 'live', timestamp: new Date() };
            // 3. Fall back to the scan snapshot with a clear timestamp.
            price = getPriceFromAllGainers(ticker);
            if (price) return { price, source: 'scan', timestamp: window._lastScanTimestamp || liveLastUpdated || new Date() };
            return { price: null, source: null, timestamp: null };
        }

        async function updateTrackerCurrentPrice(ticker, entry, t1, t2, t3, shareQty, forceFresh = false) {
            const curEl = document.getElementById('perf-current');
            const subEl = document.getElementById('perf-current-sub');
            const pnlEl = document.getElementById('perf-pnl');
            const pnlSub = document.getElementById('perf-pnl-sub');
            if (curEl) { curEl.textContent = '—'; curEl.className = 'value'; }
            if (subEl) subEl.textContent = 'Fetching price…';
            if (pnlEl) { pnlEl.textContent = '—'; pnlEl.className = 'value'; }
            if (pnlSub) pnlSub.textContent = 'Waiting for price';

            // If forceFresh, skip JSON cache and go directly to Yahoo for fresh price
            let resolved;
            if (forceFresh) {
                const freshPrice = await getFreshPrice(ticker);
                if (freshPrice && freshPrice.price > 0) {
                    resolved = freshPrice;
                } else {
                    resolved = { price: null, source: null, timestamp: null };
                }
            } else {
                resolved = await resolveCurrentPrice(ticker);
            }

            // Abort if the user switched to a different alert while the fetch was in flight
            if (document.getElementById('perf-ticker')?.textContent !== ticker) return;

            const current = resolved.price;
            if (current === null || current === undefined || isNaN(current) || current <= 0) {
                if (curEl) { curEl.textContent = '—'; curEl.className = 'value'; }
                if (subEl) subEl.textContent = 'Live price unavailable';
                if (pnlEl) { pnlEl.textContent = '—'; pnlEl.className = 'value'; }
                if (pnlSub) pnlSub.textContent = 'No current price data';
                return;
            }

            const pnl = (current - entry) * shareQty;
            const pct = entry > 0 ? ((current - entry) / entry) * 100 : 0;
            if (curEl) {
                curEl.textContent = fmtCurrency(current);
                curEl.className = 'value ' + (current >= entry ? 'green' : 'red');
            }
            if (subEl) {
                if (resolved.source === 'live') {
                    const isPreAfter = /PRE-MARKET|AFTER-HOURS/i.test(document.getElementById('market-status')?.textContent || '')
                        || /PRE-MARKET|AFTER-HOURS/i.test(document.getElementById('badge')?.textContent || '')
                        || /Pre-Market|After-Hours/i.test(document.getElementById('session-status')?.textContent || '');
                    subEl.textContent = isPreAfter ? 'Live pre/after-hours quote' : 'Live quote';
                } else if (resolved.timestamp) {
                    subEl.textContent = `From scan at ${formatScanTimestamp(resolved.timestamp)}`;
                } else {
                    subEl.textContent = 'From latest scan';
                }
            }
            if (pnlEl) {
                pnlEl.textContent = (pnl >= 0 ? '+$' : '-$') + Math.abs(pnl).toFixed(2);
                pnlEl.className = 'value ' + (pnl >= 0 ? 'green' : 'red');
            }
            if (pnlSub) pnlSub.textContent = `${pct >= 0 ? '+' : ''}${pct.toFixed(2)}% unrealized`;
        }

        function populateAlertSelector(entries) {
            const sel = document.getElementById('alert-selector');
            if (!sel) return;
            const previousTicker = sel.value;
            sel.innerHTML = '';
            let selectable = entries.filter(r => r.plan && (r.status === 'ALERT' || r.status === 'CANDIDATE'));
            selectable.forEach(r => { r._maxScore = getAlertMaxScore(r); });
            // Sort High impact (≥4) first, then Medium (≥2), then Low
            selectable.sort((a, b) => b._maxScore - a._maxScore);
            if (!selectable.length) {
                sel.innerHTML = '<option value="">No alerts yet</option>';
                renderSelectedAlert();
                return;
            }
            const defaultOption = document.createElement('option');
            defaultOption.value = '';
            defaultOption.textContent = 'Select an alert…';
            sel.appendChild(defaultOption);
            selectable.forEach(r => {
                const opt = document.createElement('option');
                opt.value = r.ticker;
                const imp = impactLabel(r._maxScore, r);
                opt.textContent = `${r.ticker} — ${imp.text}${r.status === 'CANDIDATE' ? ' (candidate)' : ''}`;
                sel.appendChild(opt);
            });
            // Prefer previously-selected ticker (from localStorage or prior selection), otherwise top sorted alert.
            const storedTicker = localStorage.getItem('ozmoeg-selected-alert');
            if (storedTicker && selectable.some(a => a.ticker === storedTicker)) {
                sel.value = storedTicker;
            } else if (previousTicker && selectable.some(a => a.ticker === previousTicker)) {
                sel.value = previousTicker;
            } else {
                sel.value = selectable[0].ticker;
            }
            renderSelectedAlert();
        }

        async function renderSelectedAlert() {
            const sel = document.getElementById('alert-selector');
            const ticker = sel ? sel.value : '';
            const activeRows = getActiveScannerView() === 'premarket'
                ? (window._lastPreMarketResults || [])
                : (window._lastLiveResults || []);
            const selectable = activeRows.filter(r => r.plan && (r.status === 'ALERT' || r.status === 'CANDIDATE'));
            const r = selectable.find(a => a.ticker === ticker);

            if (!r || !r.plan || !r.plan.valid) {
                document.getElementById('plan-ticker').textContent = '—';
                document.getElementById('perf-ticker').textContent = '—';
                ['plan-entry','plan-stop','plan-t1','plan-t2','plan-t3','plan-shares','plan-position','plan-rr'].forEach(id => {
                    const el = document.getElementById(id);
                    if (el) el.textContent = '—';
                });
                document.getElementById('plan-exit-rules').innerHTML = '<li>Select an alert to see exit rules.</li>';
                ['perf-investment','perf-entry','perf-current','perf-pnl','perf-t1-pnl','perf-t2-pnl','perf-t3-pnl','perf-risk'].forEach(id => {
                    const el = document.getElementById(id);
                    if (el) { el.textContent = '—'; el.className = 'value'; }
                });
                document.getElementById('perf-entry-sub').textContent = '—';
                document.getElementById('perf-current-sub').textContent = '—';
                document.getElementById('perf-pnl-sub').textContent = '—';
                document.getElementById('perf-t1-pnl-sub').textContent = '—';
                document.getElementById('perf-t2-pnl-sub').textContent = '—';
                document.getElementById('perf-t3-pnl-sub').textContent = '—';
                document.getElementById('perf-risk-sub').textContent = '—';
                document.getElementById('impact-score').textContent = '—';
                document.getElementById('news-ticker-symbol').textContent = '—';
                document.getElementById('news-ticker-status').textContent = 'No active alert';
                document.getElementById('news-scan-time').textContent = 'No recent scan';
                document.getElementById('catalyst-headline').textContent = 'No active catalyst — waiting for next alert';
                document.getElementById('news-list').innerHTML = '<li><span class="score">[-]</span> Select an alert above to view its catalyst and news headlines.</li>';
                renderPlanRules();
                return;
            }

            const p = r.plan;
            const t = p.targets || {};

            // Resolve the entry basis. During US pre/after-market the backend's plan
            // was built from the prior close, so we rebase it on the live current price.
            const entryBasis = await resolveLiveEntryPrice(p.ticker, parseFloat(p.entry));
            const liveEntry = entryBasis.price;
            const liveSource = entryBasis.source;
            const isLiveRebased = isExtendedHoursSession() && entryBasis.liveAvailable;

            // When rebasing to live price, keep the same percentage-based stop/targets
            // relative to the original plan so risk/reward geometry is preserved.
            const rawEntry = parseFloat(p.entry);
            const rawStop = parseFloat(p.stop);
            const rawT1 = parseFloat(t.t1);
            const rawT2 = parseFloat(t.t2);
            const rawT3 = parseFloat(t.t3);

            let entry, stop, t1, t2, t3, shares, position, rr;
            if (isLiveRebased && rawEntry > 0 && liveEntry > 0) {
                entry = liveEntry;
                const stopPct = (rawStop - rawEntry) / rawEntry;
                const t1Pct = (rawT1 - rawEntry) / rawEntry;
                const t2Pct = (rawT2 - rawEntry) / rawEntry;
                const t3Pct = (rawT3 - rawEntry) / rawEntry;
                stop = entry * (1 + stopPct);
                t1 = entry * (1 + t1Pct);
                t2 = entry * (1 + t2Pct);
                t3 = entry * (1 + t3Pct);
                // Video formula: fixed $R risk per trade, shares = R / stop_distance.
                // Use the risk_amount stored in the plan (3% daily loss / 3 trades).
                const riskAmount = parseFloat(p.risk_amount) || 100.0;
                const stopDistance = Math.abs(entry - stop);
                shares = stopDistance > 0 ? Math.max(1, Math.round(riskAmount / stopDistance)) : 0;
                position = shares * entry;
                // Risk:Reward remains the original plan's ratio; recompute for safety.
                const risk = Math.abs(entry - stop);
                const reward = Math.abs(t1 - entry);
                rr = risk > 0 ? reward / risk : parseFloat(p.risk_reward);
            } else {
                entry = rawEntry;
                stop = rawStop;
                t1 = rawT1;
                t2 = rawT2;
                t3 = rawT3;
                shares = parseInt(p.shares);
                position = parseFloat(p.position_value);
                rr = parseFloat(p.risk_reward);
            }
            const riskAmount = parseFloat(p.risk_amount);
            const risk_per_share = Math.abs(entry - stop);

            // Render market-aware rules
            renderPlanRules();

            document.getElementById('plan-ticker').textContent = p.ticker;
            document.getElementById('perf-ticker').textContent = p.ticker;

            // Country badge on active trade plan and tracker header
            const country = (r.country || '').trim();
            const countryBadge = country ? ` <span class="country-badge">${escapeHtml(country)}</span>` : '';
            const planTickerEl = document.getElementById('plan-ticker');
            const perfTickerEl = document.getElementById('perf-ticker');
            if (planTickerEl && !planTickerEl.innerHTML.includes('country-badge')) {
                planTickerEl.innerHTML = escapeHtml(p.ticker) + countryBadge;
            }
            if (perfTickerEl && !perfTickerEl.innerHTML.includes('country-badge')) {
                perfTickerEl.innerHTML = escapeHtml(p.ticker) + countryBadge;
            }

            document.getElementById('plan-entry').textContent = fmtCurrency(entry);
            document.getElementById('plan-stop').textContent = fmtCurrency(stop) + fmtPct(entry, stop);
            document.getElementById('plan-t1').textContent = fmtCurrency(t1) + fmtPct(entry, t1);
            document.getElementById('plan-t2').textContent = fmtCurrency(t2) + fmtPct(entry, t2);
            document.getElementById('plan-t3').textContent = fmtCurrency(t3) + fmtPct(entry, t3);
            document.getElementById('plan-shares').textContent = isNaN(shares) ? '—' : shares.toLocaleString();
            document.getElementById('plan-position').textContent = fmtCurrency(position);
            document.getElementById('plan-rr').textContent = isNaN(rr) ? '—' : `1:${rr.toFixed(2)}`;

            // Render tape legend bars for the active plan
            const tape = r.tape || {};
            const isAuActive = currentMarket === 'AUS';
            const tapeLegend = document.getElementById('tape-legend');
            if (isAuActive || tape.not_available) {
                if (tapeLegend) {
                    const bars = tapeLegend.querySelectorAll('.tape-bar');
                    bars.forEach(bar => {
                        const fill = bar.querySelector('.tape-fill');
                        const valueEl = bar.querySelector('.tape-value');
                        if (fill) fill.style.width = '0%';
                        if (valueEl) valueEl.textContent = '—';
                    });
                    const note = tapeLegend.querySelector('.tape-note');
                    if (note) note.innerHTML = '<span class="tape-mini tape-missing">—</span> Tape / time-and-sales not available for ASX.';
                }
            } else if (tape.not_available) {
                if (tapeLegend) {
                    const bars = tapeLegend.querySelectorAll('.tape-bar');
                    bars.forEach(bar => {
                        const fill = bar.querySelector('.tape-fill');
                        const valueEl = bar.querySelector('.tape-value');
                        if (fill) fill.style.width = '0%';
                        if (valueEl) valueEl.textContent = '—';
                    });
                    const note = tapeLegend.querySelector('.tape-note');
                    if (note) note.innerHTML = '<span class="tape-mini tape-missing">—</span> Tape / time-and-sales not available for ASX.';
                }
            } else if (!tape.valid || tape.stale) {
                if (tapeLegend) {
                    const bars = tapeLegend.querySelectorAll('.tape-bar');
                    bars.forEach(bar => {
                        const fill = bar.querySelector('.tape-fill');
                        const valueEl = bar.querySelector('.tape-value');
                        if (fill) fill.style.width = '0%';
                        if (valueEl) valueEl.textContent = '—';
                    });
                    const note = tapeLegend.querySelector('.tape-note');
                    const staleAge = tape.stale_age_seconds ? ` · stale ${Math.round(tape.stale_age_seconds/60)}m` : '';
                    if (note) note.innerHTML = `<span class="tape-mini tape-missing">—</span> Tape data unavailable or stale${staleAge}. Last trade: ${tape.last_trade_time ? new Date(tape.last_trade_time).toLocaleTimeString() : 'unknown'}.`;
                }
            } else if (tape.no_move) {
                if (tapeLegend) {
                    const bars = tapeLegend.querySelectorAll('.tape-bar');
                    bars.forEach(bar => {
                        const fill = bar.querySelector('.tape-fill');
                        const valueEl = bar.querySelector('.tape-value');
                        if (fill) fill.style.width = '0%';
                        if (valueEl) valueEl.textContent = '—';
                    });
                    const note = tapeLegend.querySelector('.tape-note');
                    const timeNote = formatTapeTime(tape.last_trade_time);
                    if (note) note.innerHTML = `<span class="tape-mini tape-missing">—</span> No tape movement / no trades detected${timeNote}.`;
                }
            } else {
                const va = tape.valid && !tape.stale ? (tape.volume_acceleration || 0) : null;
                const vel = tape.valid && !tape.stale ? (tape.price_velocity_pct || 0) : null;
                const bp = tape.valid && !tape.stale ? (tape.buy_pressure_pct || 0) : null;
                const lb = tape.valid && !tape.stale ? (tape.large_bar_count || 0) : null;
                function setTapeBar(id, val, fmt, cap) {
                    const wrap = document.getElementById(id);
                    if (!wrap) return;
                    const fill = wrap.querySelector('.tape-fill');
                    const valueEl = wrap.querySelector('.tape-value');
                    if (val === null || val === undefined) {
                        if (fill) fill.style.width = '0%';
                        if (valueEl) valueEl.textContent = '—';
                        return;
                    }
                    const pct = Math.min(100, Math.max(0, (val / cap) * 100));
                    if (fill) fill.style.width = pct + '%';
                    if (valueEl) valueEl.textContent = fmt(val);
                }
                setTapeBar('tape-legend-va', va, v => `${v.toFixed(1)}%`, 200);
                setTapeBar('tape-legend-vel', vel, v => `${v > 0 ? '+' : ''}${v.toFixed(2)}%`, 20);
                setTapeBar('tape-legend-bp', bp, v => `${v.toFixed(1)}%`, 100);
                setTapeBar('tape-legend-lb', lb, v => `${Math.round(v)}`, 10);

                const note = tapeLegend?.querySelector('.tape-note');
                if (note) note.innerHTML = '<span class="tape-mini tape-high">🔥</span> = high volume (RVOL ≥ 2.0) · <span class="tape-mini tape-medium">⚡</span> = moderate volume (RVOL 1.0–1.99) · <span class="tape-mini tape-low">🌱</span> = low volume (RVOL &lt; 1.0)';
            }

            const exitRules = p.exit_rules || {};
            const half = isNaN(shares) ? '—' : Math.round(shares * 0.5);
            const quarter = isNaN(shares) ? '—' : Math.round(shares * 0.25);
            const t1R = risk_per_share > 0 ? ((t1 - entry) / risk_per_share).toFixed(1) : '—';
            const t2R = risk_per_share > 0 ? ((t2 - entry) / risk_per_share).toFixed(1) : '—';
            const t3R = risk_per_share > 0 ? ((t3 - entry) / risk_per_share).toFixed(1) : '—';
            document.getElementById('plan-exit-rules').innerHTML = `
                <li>Sell 50% (${half} shares) at Target 1: ${fmtCurrency(t1)} (${t1R}R)</li>
                <li>Sell 25% (${quarter} shares) at Target 2: ${fmtCurrency(t2)} (${t2R}R)</li>
                <li>Trail remaining 25% with 2% cushion above Target 3: ${fmtCurrency(t3)} (${t3R}R)</li>
                <li>Hard stop: ${fmtCurrency(stop)}${fmtPct(entry, stop)} — Webull requires stop/take-profit legs ≥ 0.1% apart</li>
                ${isLiveRebased ? `<li style="color:var(--accent-amber)">⚠️ Live pre/after-market rebase: original close plan was ${fmtCurrency(rawEntry)} → ${fmtCurrency(entry)}</li>` : ''}
                <li>Move stop to breakeven once up ${exitRules.trail_breakeven_at || '+1%'}</li>
                <li>Exit if bearish engulfing or volume drops below 1.5x average</li>
            `;

            // Tracker — video formula sizing: fixed $R risk per trade, shares = R / stop distance
            const riskAmountTracker = parseFloat(p.risk_amount) || 100.0;
            const stopDistanceTracker = Math.abs(entry - stop);
            const shareQty = stopDistanceTracker > 0 ? Math.max(1, Math.round(riskAmountTracker / stopDistanceTracker)) : 0;
            const totalCost = shareQty * entry;
            // P&L if the full share qty is executed (sold) at each target
            const pnlT1 = entry > 0 ? (t1 - entry) * shareQty : 0;
            const pnlT2 = entry > 0 ? (t2 - entry) * shareQty : 0;
            const pnlT3 = entry > 0 ? (t3 - entry) * shareQty : 0;
            const maxRisk = (stop - entry) * shareQty;

            document.getElementById('perf-investment').textContent = `${shareQty.toLocaleString()} sh`;
            document.getElementById('perf-investment-sub').textContent = `~${fmtCurrency(totalCost)} @ entry`;
            // Tracker "Proposed Entry" = previous scan refresh price, "Current Price" = current scan price.
            // When no previous scan price exists yet, we deliberately show "—" on the proposed entry side
            // instead of faking it with the current price or raw plan entry, so the user knows the tracker
            // is waiting for the next refresh to establish a real prior price.
            const prevQuote = window._prevLiveQuotes?.[(p.ticker || '').toUpperCase()];
            const currentQuote = window._lastLiveQuotes?.[(p.ticker || '').toUpperCase()];
            const hasPrevPrice = prevQuote && prevQuote.price > 0;
            const currentPrice = (currentQuote && currentQuote.price > 0) ? currentQuote.price : null;

            if (hasPrevPrice) {
                document.getElementById('perf-entry').textContent = fmtCurrency(prevQuote.price);
                document.getElementById('perf-entry-sub').textContent = `${p.ticker} — Previous scan price · ${prevQuote?._timestamp ? new Date(prevQuote._timestamp).toLocaleTimeString('en-AU', {hour:'2-digit', minute:'2-digit'}) : (r.time || '—')}`;
            } else {
                document.getElementById('perf-entry').textContent = '—';
                document.getElementById('perf-entry-sub').textContent = 'Waiting for previous refresh';
            }

            if (currentPrice !== null && currentPrice > 0) {
                document.getElementById('perf-current').textContent = fmtCurrency(currentPrice);
                document.getElementById('perf-current-sub').textContent = `Current scan price · ${currentQuote?._timestamp ? new Date(currentQuote._timestamp).toLocaleTimeString('en-AU', {hour:'2-digit', minute:'2-digit'}) : '—'}`;
                if (hasPrevPrice) {
                    const sameRefresh = prevQuote._timestamp && currentQuote._timestamp && prevQuote._timestamp === currentQuote._timestamp;
                    if (sameRefresh) {
                        document.getElementById('perf-pnl').textContent = '—';
                        document.getElementById('perf-pnl-sub').textContent = 'Next refresh will compare prices';
                    } else {
                        const pnl = (currentPrice - prevQuote.price) * shareQty;
                        const pct = prevQuote.price > 0 ? ((currentPrice - prevQuote.price) / prevQuote.price) * 100 : 0;
                        const pnlEl = document.getElementById('perf-pnl');
                        if (pnlEl) {
                            pnlEl.textContent = (pnl >= 0 ? '+$' : '-$') + Math.abs(pnl).toFixed(2);
                            pnlEl.className = 'value ' + (pnl >= 0 ? 'green' : 'red');
                        }
                        const pnlSub = document.getElementById('perf-pnl-sub');
                        if (pnlSub) pnlSub.textContent = `${pct >= 0 ? '+' : ''}${pct.toFixed(2)}% since last refresh`;
                    }
                } else {
                    document.getElementById('perf-pnl').textContent = '—';
                    document.getElementById('perf-pnl-sub').textContent = 'Next refresh will show real P&L';
                }
            } else {
                document.getElementById('perf-current').textContent = '—';
                document.getElementById('perf-current-sub').textContent = 'No current scan price';
                document.getElementById('perf-pnl').textContent = '—';
                document.getElementById('perf-pnl-sub').textContent = 'Waiting for current price';
            }

            const t1El = document.getElementById('perf-t1-pnl');
            t1El.textContent = (pnlT1 >= 0 ? '+$' : '-$') + Math.abs(pnlT1).toFixed(2);
            t1El.className = 'value ' + (pnlT1 >= 0 ? 'green' : 'red');
            document.getElementById('perf-t1-pnl-sub').textContent = `At T1: ${fmtCurrency(t1)}`;
            const t2El = document.getElementById('perf-t2-pnl');
            t2El.textContent = (pnlT2 >= 0 ? '+$' : '-$') + Math.abs(pnlT2).toFixed(2);
            t2El.className = 'value ' + (pnlT2 >= 0 ? 'green' : 'red');
            document.getElementById('perf-t2-pnl-sub').textContent = `At T2: ${fmtCurrency(t2)}`;
            const t3El = document.getElementById('perf-t3-pnl');
            t3El.textContent = (pnlT3 >= 0 ? '+$' : '-$') + Math.abs(pnlT3).toFixed(2);
            t3El.className = 'value ' + (pnlT3 >= 0 ? 'green' : 'red');
            document.getElementById('perf-t3-pnl-sub').textContent = `At T3: ${fmtCurrency(t3)}`;
            const riskEl = document.getElementById('perf-risk');
            riskEl.textContent = (maxRisk >= 0 ? '+$' : '-$') + Math.abs(maxRisk).toFixed(2);
            riskEl.className = 'value red';
            document.getElementById('perf-risk-sub').textContent = `At stop: ${fmtCurrency(stop)}`;

            // News & catalyst
            const news = r.news || {};
            const maxScore = getAlertMaxScore(r);
            const imp = impactLabel(maxScore, r);
            const impactBadge = document.getElementById('impact-score');
            impactBadge.textContent = imp.text;
            impactBadge.className = 'impact-badge ' + imp.cls;

            document.getElementById('news-ticker-symbol').innerHTML = escapeHtml(p.ticker) + countryBadge;
            document.getElementById('news-ticker-status').textContent = news.catalyst || 'Alert active';
            document.getElementById('news-scan-time').textContent = news.scan_time ? `Scanned ${news.scan_time}` : '';
            document.getElementById('catalyst-headline').textContent = news.catalyst || 'No catalyst headline available';

            const list = document.getElementById('news-list');
            const headlines = news.headlines || [];
            if (headlines.length) {
                list.innerHTML = headlines.map(h => {
                    const s = h.score || 0;
                    const scoreClass = s >= 4 ? 'impact-high' : (s >= 2 ? 'impact-medium' : 'impact-low');
                    // Recompute age from raw timestamp so saved snapshots stay accurate.
                    const age = computeNewsAge(h.raw_time) || (h.time || '');
                    const isVeryStale = /^(\d+mo|\d+y|\d+d)\s+ago/.test(age) && (
                        /^(\d+mo|\d+y)\s+ago/.test(age) ||
                        (age.match(/^(\d+)d\s+ago/) && parseInt(age.match(/^(\d+)d\s+ago/)[1]) > 7)
                    );
                    const staleClass = isVeryStale ? 'news-age stale' : 'news-age';
                    const staleEmoji = isVeryStale ? '⚠️ ' : '';
                    // Show exact original timestamp as a tooltip
                    const rawIso = h.raw_time || '';
                    const titleTip = rawIso ? ` title="First published: ${escapeHtml(rawIso)}"` : '';
                    const timeHtml = age ? `<span class="${staleClass}"${titleTip}>${staleEmoji}${escapeHtml(age)}</span> ` : '';
                    const hasUrl = h.url && /^https?:\/\//i.test(h.url);
                    const searchUrl = `https://www.google.com/search?q=${encodeURIComponent(h.title + ' ' + (h.source || ''))}`;
                    const titleHtml = hasUrl
                        ? `<a href="${escapeHtml(h.url)}" target="_blank" rel="noopener">${escapeHtml(h.title)}</a>`
                        : `<a href="${searchUrl}" target="_blank" rel="noopener">${escapeHtml(h.title)}</a>`;
                    return `<li>${timeHtml}<span class="score ${scoreClass}">[${s}]</span> ${titleHtml} <em>${escapeHtml(h.source || '')}</em></li>`;
                }).join('');
            } else {
                list.innerHTML = '<li><span class="score">[-]</span> No qualifying news headlines found for this alert.</li>';
            }

            // Surface AU data quality note when applicable
            if (currentMarket === 'AUS' && (r.au_state === 'AU-LIMITED' || r.au_state === 'AU-ANNOUNCEMENT')) {
                const dataNote = document.createElement('li');
                dataNote.style.cssText = 'color: var(--accent-amber); font-style: italic; font-size: 0.8rem;';
                dataNote.innerHTML = 'ℹ️ ASX intraday bars/TA are limited from this network. Price, volume and announcements are live; verify on your ASX broker before acting.';
                list.appendChild(dataNote);
            }
        }

        // List of headlines that are known to leak from other tickers / generic feeds and should never
        // be shown as a ticker-specific red flag. When a skip reason matches one of these, we fall back
        // to a generic red-flag label and surface the actual flag category (offering, dilution, etc.).
        const BAD_RED_FLAG_HEADLINES = [
            'Video: SpaceX dips after notes offering, KeyBanc initiation',
            'SpaceX dips after notes offering',
            'KeyBanc initiation'
        ];

        function sanitizeSkipReason(r) {
            const raw = (r.result || r.detail || '').trim();
            if (!raw) return '';
            const lower = raw.toLowerCase();
            const hasBadHeadline = BAD_RED_FLAG_HEADLINES.some(bad => lower.includes(bad.toLowerCase()));
            if (!hasBadHeadline) return raw;
            // Extract the flag category if present, e.g. "Red flags: offering:..." -> "offering"
            const m = raw.match(/Red flags:\s*([^:]+):/i);
            const flag = m ? m[1].trim() : 'red flag';
            return `Red flags: ${flag} — headline mismatch (unrelated news item leaked into this ticker)`;
        }

        function renderScannerRow(r) {
            let statusClass = 'result-skip';
            let emoji = '⏭️';
            if (r.status === 'ALERT') { statusClass = 'result-alert'; emoji = '🚨'; }
            else if (r.status === 'CANDIDATE') { statusClass = 'result-candidate'; emoji = '🔬'; }
            else if (r.status === 'WATCHLIST') { statusClass = 'result-candidate'; emoji = '⏰'; }
            const imp = impactLabel(getAlertMaxScore(r), r);
            const escaped = escapeHtml(sanitizeSkipReason(r));
            const showImpact = true;
            const ageCell = formatNewsAgeCell(r.news);
            const tape = r.tape || {};
            const isAuMarket = currentMarket === 'AUS';
            const isWatchlist = r.status === 'WATCHLIST';

            function formatTapeTime(iso) {
                if (!iso) return '';
                try {
                    const d = new Date(iso);
                    if (isNaN(d.getTime())) return '';
                    // Show local HH:MM:SS with relative age in minutes
                    const now = Date.now();
                    const ageMin = Math.round((now - d.getTime()) / 60000);
                    const ageText = ageMin < 1 ? 'just now' : ageMin < 60 ? `${ageMin}m ago` : `${Math.floor(ageMin/60)}h ago`;
                    return ` · last ${d.toLocaleTimeString([], {hour:'2-digit', minute:'2-digit', second:'2-digit'})} (${ageText})`;
                } catch (e) { return ''; }
            }

            let tapeCell;
            if (isWatchlist) {
                tapeCell = `<span class="tape-mini tape-missing" title="Catalyst watchlist — no live volume data yet">— pending</span>`;
            } else if (isAuMarket || tape.not_available) {
                tapeCell = `<span class="tape-mini tape-missing" title="Tape / time-and-sales not available for ASX">— N/A</span>`;
            } else if (tape.no_move) {
                const timeNote = formatTapeTime(tape.last_trade_time);
                const ageNote = tape.stale_age_seconds ? ` · stale ${Math.round(tape.stale_age_seconds/60)}m` : '';
                tapeCell = `<span class="tape-mini tape-missing" title="15s bars show no tape movement / no trades${timeNote}${ageNote}">— no move${timeNote}${ageNote}</span>`;
            } else {
                const timeNote = formatTapeTime(tape.last_trade_time);
                const rvol = tape.rvol || 0;
                const volume = tape.volume || 0;
                const adv = tape.adv || 0;
                const indicator = tape.volume_indicator || '';
                let tapeClass = 'tape-missing';
                let tapeText = '— missing';
                let title = 'Volume data unavailable';

                if (indicator === 'high') {
                    tapeClass = 'tape-high';
                    tapeText = '🔥 high volume';
                    title = `RVOL ${rvol}x vs ADV (${volume.toLocaleString()} today / ${adv.toLocaleString()} avg)${timeNote}`;
                } else if (indicator === 'moderate') {
                    tapeClass = 'tape-medium';
                    tapeText = '⚡ moderate volume';
                    title = `RVOL ${rvol}x vs ADV (${volume.toLocaleString()} today / ${adv.toLocaleString()} avg)${timeNote}`;
                } else if (indicator === 'low') {
                    tapeClass = 'tape-low';
                    tapeText = '🌱 low volume';
                    title = `RVOL ${rvol}x vs ADV (${volume.toLocaleString()} today / ${adv.toLocaleString()} avg)${timeNote}`;
                } else if (tape.no_move) {
                    tapeClass = 'tape-missing';
                    tapeText = '— no move';
                    title = `No volume recorded${timeNote}`;
                }
                tapeCell = `\u003cspan class="tape-mini ${tapeClass}" title="${title}">${tapeText}\u003c/span\u003e`;
            }
            const country = (r.country || '').trim();
            const countryBadge = country ? `<span class="country-badge">${escapeHtml(country)}</span>` : '';
            return `<tr><td class="ticker-cell">${r.ticker}${countryBadge}</td><td>${r.name}</td><td><span class="${statusClass}">${emoji} ${r.status}</span> ${showImpact ? `<span class="impact-mini ${imp.cls}">${imp.text}</span>` : ''}</td><td class="news-age-cell">${ageCell}</td><td>${tapeCell}</td><td>${escaped}</td></tr>`;
        }

        function formatNewsAgeCell(news) {
            if (!news || !Array.isArray(news.headlines) || news.headlines.length === 0) {
                return '<span class="news-age missing" title="No qualifying news headlines">—</span>';
            }
            // Pick the newest (most recent) headline by its exact raw timestamp.
            const newest = news.headlines
                .filter(h => h.raw_time)
                .sort((a, b) => newsAgeMinutes(a) - newsAgeMinutes(b))[0];
            if (!newest) {
                return '<span class="news-age missing" title="No qualifying news headlines">—</span>';
            }
            const age = computeNewsAge(newest.raw_time);
            if (!age) {
                return '<span class="news-age missing" title="No qualifying news headlines">—</span>';
            }
            const rawIso = newest.raw_time || '';
            const isVeryStale = /^(\d+mo|\d+y|\d+d)\s+ago/.test(age) && (
                /^(\d+mo|\d+y)\s+ago/.test(age) ||
                (age.match(/^(\d+)d\s+ago/) && parseInt(age.match(/^(\d+)d\s+ago/)[1]) > 7)
            );
            const staleClass = isVeryStale ? 'news-age stale' : 'news-age';
            const staleEmoji = isVeryStale ? '⚠️ ' : '';
            const titleTip = rawIso ? ` title="First published: ${escapeHtml(rawIso)}"` : '';
            return `<span class="${staleClass}"${titleTip}>${staleEmoji}${escapeHtml(age)}</span>`;
        }

        function formatNewsAgeInline(news) {
            if (!news || !Array.isArray(news.headlines) || news.headlines.length === 0) {
                return '';
            }
            // For the live ticker stream, only badge news younger than 24h so old headlines don't look live.
            const newest = news.headlines
                .filter(h => h.raw_time)
                .map(h => ({ age: computeNewsAge(h.raw_time), mins: newsAgeMinutes(h) }))
                .filter(x => x.age && x.mins < 24 * 60)
                .sort((a, b) => a.mins - b.mins)[0];
            if (!newest) return '';
            return ` <span class="news-age" title="Age of the most recent qualifying headline">${escapeHtml(newest.age)}</span>`;
        }

        // Convert a headline's exact raw ISO timestamp to approximate minutes.
        // Smaller number = newer. Unknown/missing ages are treated as very old so they sort last.
        function computeNewsAge(rawIso) {
            if (!rawIso) return null;
            // Normalise Webull's +0000/+00:00 offsets to Z so Safari/IE parse them reliably
            const normalised = String(rawIso).trim().replace(/\+0000$/, 'Z').replace(/\+00:00$/, 'Z');
            const parsed = new Date(normalised);
            if (isNaN(parsed.getTime())) return null;
            const diffMin = Math.max(0, Math.floor((Date.now() - parsed.getTime()) / 60000));
            if (diffMin < 1) return 'just now';
            if (diffMin < 60) return `${diffMin}m ago`;
            const diffHour = Math.floor(diffMin / 60);
            if (diffHour < 24) return `${diffHour}h ago`;
            const diffDay = Math.floor(diffHour / 24);
            if (diffDay < 30) return `${diffDay}d ago`;
            const diffMonth = Math.floor(diffDay / 30.44);
            if (diffMonth < 12) return `${diffMonth}mo ago`;
            const diffYear = Math.floor(diffMonth / 12);
            return `${diffYear}y ago`;
        }

        function newsAgeMinutes(headline) {
            if (!headline || !headline.raw_time) return Number.POSITIVE_INFINITY;
            const age = computeNewsAge(headline.raw_time);
            if (!age) return Number.POSITIVE_INFINITY;
            const m = age.match(/^(\d+)m?\s+ago$/);
            if (m) return parseInt(m[1]);
            const h = age.match(/^(\d+)h\s+ago$/);
            if (h) return parseInt(h[1]) * 60;
            const d = age.match(/^(\d+)d\s+ago$/);
            if (d) return parseInt(d[1]) * 1440;
            const mo = age.match(/^(\d+)mo\s+ago$/);
            if (mo) return parseInt(mo[1]) * 30.44 * 1440;
            const y = age.match(/^(\d+)y\s+ago$/);
            if (y) return parseInt(y[1]) * 365.25 * 1440;
            if (age === 'just now') return 0;
            return Number.POSITIVE_INFINITY;
        }
        function getActiveScannerView() {
            const toggle = document.getElementById('scanner-toggle');
            if (!toggle) return 'live';
            const active = toggle.querySelector('button.active');
            return active?.dataset.view || 'live';
        }

        function renderScannerView() {
            const view = getActiveScannerView();
            const isPre = view === 'premarket';
            const isWatchlist = view === 'watchlist';
            const rows = isWatchlist ? (window._lastPreMarketWatchlist || []) :
                         isPre ? (window._lastPreMarketResults || []) :
                         (window._lastLiveResults || []);
            displayedResults = rows;
            const tsEl = document.getElementById('scanner-timestamp');
            const tbody = document.querySelector('#scanner-table tbody');
            if (!tbody) return;
            if (isWatchlist) {
                const sorted = [...rows].sort((a, b) => (getAlertMaxScore(b) || 0) - (getAlertMaxScore(a) || 0));
                if (rows.length) {
                    tbody.innerHTML = sorted.map(r => renderScannerRow(r)).join('');
                    populateAlertSelector(displayedResults);
                    renderSelectedAlert().catch(err => console.error('renderSelectedAlert failed:', err));
                } else {
                    tbody.innerHTML = '<tr><td colspan="6" style="text-align:center; padding: 2rem; color: var(--text-secondary);">No catalyst watchlist saved yet. Runs Sydney 17:00-17:59 weekdays.</td></tr>';
                    populateAlertSelector([]);
                    renderSelectedAlert().catch(err => console.error('renderSelectedAlert failed:', err));
                }
                if (tsEl) {
                    const ts = window._lastScanTimestamp ? window._lastScanTimestamp.toLocaleString('en-AU', { month:'short', day:'numeric', hour:'2-digit', minute:'2-digit' }) : '';
                    tsEl.textContent = window._lastPreMarketWatchlist?.length ? `${window._lastPreMarketWatchlist.length} catalyst rows from ${ts}` : 'No catalyst watchlist';
                }
            } else if (isPre) {
                const sorted = [...rows].sort((a, b) => {
                    const aAlert = a.status === 'ALERT' ? 1 : 0;
                    const bAlert = b.status === 'ALERT' ? 1 : 0;
                    if (aAlert !== bAlert) return bAlert - aAlert;
                    if (aAlert) {
                        const scoreDiff = getAlertMaxScore(b) - getAlertMaxScore(a);
                        if (scoreDiff !== 0) return scoreDiff;
                        return getYoungestNewsAgeMinutes(a) - getYoungestNewsAgeMinutes(b);
                    }
                    return 0;
                });
                if (rows.length) {
                    tbody.innerHTML = sorted.map(r => renderScannerRow(r)).join('');
                    populateAlertSelector(displayedResults);
                    renderSelectedAlert().catch(err => console.error('renderSelectedAlert failed:', err));
                } else {
                    tbody.innerHTML = '<tr><td colspan="6" style="text-align:center; padding: 2rem; color: var(--text-secondary);">No pre-market/after-hours watchlist saved yet.</td></tr>';
                    populateAlertSelector([]);
                    renderSelectedAlert().catch(err => console.error('renderSelectedAlert failed:', err));
                }
                if (tsEl) {
                    const ts = window._lastScanTimestamp ? window._lastScanTimestamp.toLocaleString('en-AU', { month:'short', day:'numeric', hour:'2-digit', minute:'2-digit' }) : '';
                    tsEl.textContent = window._lastPreMarketResults?.length ? `${window._lastPreMarketResults.length} saved rows from ${ts}` : 'No saved watchlist';
                }
            } else {
                // Live view: show the actual scan results whenever they exist.
                // During pre/after-hours these are the extended-hours candidates, not an empty state.
                if (rows.length) {
                    const sorted = [...rows].sort((a, b) => {
                        const aAlert = a.status === 'ALERT' ? 1 : 0;
                        const bAlert = b.status === 'ALERT' ? 1 : 0;
                        if (aAlert !== bAlert) return bAlert - aAlert;
                        if (aAlert) {
                            const scoreDiff = getAlertMaxScore(b) - getAlertMaxScore(a);
                            if (scoreDiff !== 0) return scoreDiff;
                            return getYoungestNewsAgeMinutes(a) - getYoungestNewsAgeMinutes(b);
                        }
                        return 0;
                    });
                    tbody.innerHTML = sorted.map(r => renderScannerRow(r)).join('');
                    populateAlertSelector(displayedResults);
                    renderSelectedAlert().catch(err => console.error('renderSelectedAlert failed:', err));
                    if (tsEl) {
                        const ts = window._lastScanTimestamp ? window._lastScanTimestamp.toLocaleString('en-AU', { month:'short', day:'numeric', hour:'2-digit', minute:'2-digit' }) : '';
                        tsEl.textContent = ts ? `Updated ${ts}` : '';
                    }
                } else {
                    const isExtendedHours = currentMarket !== 'AUS' && (currentMarketStatus === 'PRE-MARKET' || currentMarketStatus === 'AFTER-HOURS');
                    const isClosed = currentMarketStatus === 'CLOSED' || currentMarketStatus === 'WEEKEND';
                    const marketLabel = currentMarketStatus === 'PRE-MARKET' ? 'pre-market' : (currentMarketStatus === 'AFTER-HOURS' ? 'after-hours' : 'closed');
                    let msg;
                    if (currentMarket === 'AUS') {
                        msg = `The ASX is currently ${marketLabel}. Live scan results will resume when the market opens.`;
                    } else if (isExtendedHours) {
                        msg = `The US market is currently ${marketLabel}. No scan results available yet — the next scan will populate this table.`;
                    } else if (isClosed) {
                        msg = `The US market is currently ${marketLabel}. Live scan results will resume when the market opens.`;
                    } else {
                        msg = 'No candidates met the alert criteria in the latest scan.';
                    }
                    tbody.innerHTML = `<tr><td colspan="6" style="text-align:center; padding: 2rem; color: var(--text-secondary);">${msg}</td></tr>`;
                    populateAlertSelector([]);
                    renderSelectedAlert().catch(err => console.error('renderSelectedAlert failed:', err));
                    if (tsEl) tsEl.textContent = '';
                }
            }
        }

        function getYoungestNewsAgeMinutes(r) {
            if (!r || !r.news || !Array.isArray(r.news.headlines)) return Infinity;
            return Math.min(...r.news.headlines.map(h => newsAgeMinutes(h.time)), Infinity);
        }


        async function loadLiveData() {
            try {
                setMarketLoading(currentMarket, true);
                const ts = Date.now();
                const cacheBuster = `${ts}_${Math.random().toString(36).slice(2, 10)}`;
                const jsonFile = currentMarket === 'AUS' ? 'ozmoeg-latest-au.json' : 'ozmoeg-latest.json';
                // Aggressive cache-busting: GitHub Pages/Cloudflare can hold ozmoeg-latest.json
                // for several minutes even with no-store. Use a random token per request.
                const res = await fetch(jsonFile + '?_=' + cacheBuster, {
                    cache: 'no-store',
                    headers: { 'Cache-Control': 'no-cache', 'Pragma': 'no-cache' }
                });
                window._lastFetchAttemptAt = new Date();
                if (!res.ok) {
                    console.warn('Could not load', jsonFile, res.status);
                    setMarketLoading(currentMarket, false);
                    return;
                }
                const data = await res.json();
                const results = data.scan_results || [];
                const preMarketResults = data.pre_market_results || [];
                const preMarketWatchlist = data.pre_market_watchlist || [];
                const allGainers = data.all_gainers || [];
                const stats = data.scan_stats || {};
                window._lastScanStats = stats;
                window._lastLiveQuotes = data.live_quotes || {};
                window._previousLiveQuotes = data.previous_live_quotes || {};
                const lastUpdated = new Date(data.last_updated || Date.now());

                // The backend now ships the previous scan's live quotes in the JSON,
                // so the tracker can compute real scan-to-scan P&L immediately without
                // waiting for browser localStorage to cycle. Fallback to localStorage
                // only when the backend snapshot is absent.
                try {
                    const prev = localStorage.getItem('ozmoeg-prev-live-quotes');
                    window._prevLiveQuotes = window._previousLiveQuotes && Object.keys(window._previousLiveQuotes).length
                        ? window._previousLiveQuotes
                        : (prev ? JSON.parse(prev) : {});
                } catch (e) {
                    window._prevLiveQuotes = {};
                }

                // Anchor the auto-refresh countdown to the JSON timestamp so it stays
                // aligned with the cron schedule, not the browser load time.
                window._lastScanTimestamp = lastUpdated;
                // Do not recompute nextRefreshAt here; the interval timer handles firing
                // at the next wall-clock cron boundary and will reschedule after the fetch.

                // Update badge — prefer real-time US market status when the JSON scan is stale
                // so weekend/closed sessions don't falsely show OPEN from Friday's last scan.
                const alerts = results.filter(r => r.status === 'ALERT').length;
                const candidates = results.filter(r => r.status !== 'ALERT' && r.status !== 'INFO').length;
                const rawStatus = stats.market_status || 'OPEN';
                const lastScanAgeMin = window._lastScanTimestamp
                    ? Math.max(0, (new Date().getTime() - new Date(window._lastScanTimestamp).getTime()) / 60000)
                    : 0;
                let marketStatus = rawStatus;
                const realTimeStatus = getCurrentUSMarketStatus ? getCurrentUSMarketStatus() : rawStatus;
                if (lastScanAgeMin > 90 || realTimeStatus === 'CLOSED' || realTimeStatus === 'WEEKEND') {
                    marketStatus = realTimeStatus;
                }
                currentMarketStatus = marketStatus;
                const marketTime = stats.market_time || '';
                const marketFromData = (stats.market || 'us').toUpperCase() === 'AU' ? 'AUS' : 'US';
                const statusEmoji = { 'OPEN': '🟢', 'PRE-MARKET': '🟡', 'AFTER-HOURS': '🟡', 'WEEKEND': '🔴', 'CLOSED': '🔴' }[marketStatus] || '⚪';
                const marketLabel = marketFromData;
                const timeAgo = lastUpdated ? ` · updated ${lastUpdated.toLocaleString('en-AU', { month:'short', day:'numeric', hour:'2-digit', minute:'2-digit' })}` : '';
                document.getElementById('scanner-badge').textContent = `${statusEmoji} ${marketLabel} ${marketStatus} ${marketTime} | Scanned: ${stats.gainers_scanned || allGainers.length || '—'} | ${candidates} candidates | ${alerts} alerts${timeAgo}`;

                liveResults = results;
                liveLastUpdated = lastUpdated;
                // Preserve pre-market/after-hours watchlist and catalyst watchlist for US.
                window._lastPreMarketResults = preMarketResults;
                window._lastPreMarketWatchlist = preMarketWatchlist;
                window._lastLiveResults = results;
                window._lastAllGainers = allGainers;
                window._lastLiveQuotes = data.live_quotes || {};

                // Save current scan quotes to localStorage so next refresh can compare prev vs current
                try {
                    localStorage.setItem('ozmoeg-prev-live-quotes', JSON.stringify(data.live_quotes || {}));
                } catch (e) { /* storage may be unavailable */ }

                // Show Pre/After toggle only for US markets (ASX has no extended session).
                const showPreAfterToggle = currentMarket !== 'AUS';
                const watchBtn = document.querySelector('#scanner-toggle button[data-view="watchlist"]');
                const preBtn = document.querySelector('#scanner-toggle button[data-view="premarket"]');
                const liveBtn = document.querySelector('#scanner-toggle button[data-view="live"]');
                [preBtn, watchBtn].forEach(btn => {
                    if (btn) btn.style.display = showPreAfterToggle ? 'inline-flex' : 'none';
                });

                if (!scannerFirstLoadDone) {
                    // Use real-time market status for toggle defaults, not the stale JSON status.
                    const effectiveStatus = currentMarketStatus || marketStatus;
                    const isUsExtendedHours = currentMarket !== 'AUS' && (effectiveStatus === 'PRE-MARKET' || effectiveStatus === 'AFTER-HOURS');
                    const isUsClosedWithWatchlist = currentMarket !== 'AUS' && (effectiveStatus === 'WEEKEND' || effectiveStatus === 'CLOSED') && window._lastPreMarketWatchlist.length > 0;
                    const isCurrentlyClosed = currentMarket !== 'AUS' && (effectiveStatus === 'WEEKEND' || effectiveStatus === 'CLOSED');
                    const isWatchlistWindow = currentMarket !== 'AUS' && isActiveTradingWindow() && effectiveStatus === 'CLOSED';
                    if (isWatchlistWindow) {
                        setScannerToggleActive('watchlist');
                    } else if (isUsExtendedHours || isUsClosedWithWatchlist) {
                        setScannerToggleActive('premarket');
                    } else if (isCurrentlyClosed) {
                        // During closed/weekend there is no live session to watch; grey out both toggles.
                        setScannerToggleActive('premarket');
                        if (liveBtn) {
                            liveBtn.disabled = true;
                            liveBtn.style.opacity = '0.5';
                            liveBtn.style.cursor = 'not-allowed';
                        }
                        if (preBtn) {
                            preBtn.disabled = true;
                            preBtn.style.opacity = '0.5';
                            preBtn.style.cursor = 'not-allowed';
                        }
                    } else {
                        setScannerToggleActive('live');
                    }
                    scannerFirstLoadDone = true;
                }

                // Re-render current view according to active toggle
                renderScannerView();
                renderPlanRules();

                // If watchlist rows exist but current view is live, surface a subtle hint.
                if (currentMarket !== 'AUS' && window._lastPreMarketWatchlist?.length > 0 && getActiveScannerView() === 'live') {
                    const badge = document.getElementById('scanner-badge');
                    if (badge) badge.textContent = badge.textContent + ` · ⏰ ${window._lastPreMarketWatchlist.length} catalyst watchlist item(s)`;
                }

                // Update news ticker - only show actionable results with recent news (< 24h), not all 50 skipped scans
                const ticker = document.getElementById('news-ticker');
                if (ticker) {
                    const NEWS_TICKER_MAX_AGE_HOURS = 24;
                    const actionable = results.filter(r => ['ALERT','CANDIDATE','BOUNCE'].includes(r.status));
                    const recentItems = actionable.filter(r => {
                        if (!r.news || !Array.isArray(r.news.headlines) || r.news.headlines.length === 0) return true;
                        const newestMin = Math.min(...r.news.headlines.map(h => newsAgeMinutes(h)));
                        return newestMin < NEWS_TICKER_MAX_AGE_HOURS * 60;
                    });
                    const itemsToShow = recentItems.length ? recentItems : actionable;
                    if (itemsToShow.length) {
                        const items = itemsToShow.map(r => {
                            const date = r.date || lastUpdated.toLocaleDateString('en-US', { month:'long', day:'numeric' });
                            const time = r.time || lastUpdated.toLocaleTimeString('en-US', { hour:'2-digit', minute:'2-digit', hour12:true });
                            const imp = impactLabel(getAlertMaxScore(r), r);
                            const impactTag = ` <span class="impact-mini ${imp.cls}">${imp.text}</span>`;

                            const newsAge = formatNewsAgeInline(r.news);
                            const catalyst = (r.news && r.news.top_headline) ? r.news.top_headline : (r.news && r.news.catalyst ? r.news.catalyst : '');

                            const catalystPrefix = catalyst ? `<span style="color:var(--accent-amber)">📰 ${escapeHtml(catalyst)}</span> — ` : '';
                            const country = (r.country || '').trim();
                            const countryBadge = country ? `<span class="country-badge">${escapeHtml(country)}</span>` : '';
                            return `<div class="news-item ${(r.status || 'SKIP').toLowerCase()}"><span class="score">${r.status}</span>${impactTag}${newsAge} <span class="date">${date}</span> <span class="time">${time}</span> — ${r.ticker}${countryBadge} (${r.name}) — ${catalystPrefix}${r.result || ''}</div>`;
                        }).join('');
                        ticker.innerHTML = items + '\n' + items;
                    } else {
                        const info = `<div class="news-item skip"><span class="score">INFO</span><span class="time">Now</span> — No candidates passed filter criteria — Scan continues every 15 min</div>`;
                        ticker.innerHTML = info + '\n' + info;
                    }
                }

                // Update all-scanned gainers and losers details tables dynamically from JSON.
                // This guarantees they always reflect the latest scan instead of stale server-rendered HTML.
                const isAu = (stats.market || 'us').toLowerCase() === 'au';
                const allLosers = data.all_losers || [];
                const renderScannedRow = (stock, isLoser) => {
                    const symbol = stock.ticker || '';
                    const name = stock.name || symbol;
                    const price = parseFloat(stock.price || 0);
                    let changePct = parseFloat(stock.change_pct || 0);
                    const volume = parseInt(stock.volume || 0);
                    const mktCap = parseFloat(stock.market_cap || 0);
                    const rvol = parseFloat(stock.rvol || 0);
                    const passed = stock.passed;
                    const badgeClass = passed ? 'scan-pass' : 'scan-skip';
                    const badgeText = passed ? 'PASS' : 'SKIP';
                    const reason = stock.reason || '';
                    const priceDecimals = isAu ? 3 : 2;
                    const sign = changePct >= 0 ? '+' : '';
                    return `\u003ctr\u003e\u003ctd class="ticker-cell"\u003e${escapeHtml(symbol)}\u003c/td\u003e\u003ctd\u003e${escapeHtml(name)}\u003c/td\u003e\u003ctd\u003e$${price.toFixed(priceDecimals)}\u003c/td\u003e\u003ctd\u003e${sign}${changePct.toFixed(1)}%\u003c/td\u003e\u003ctd\u003e${volume.toLocaleString()}\u003c/td\u003e\u003ctd\u003e${rvol.toFixed(1)}x\u003c/td\u003e\u003ctd\u003e$${(mktCap/1e6).toFixed(1)}M\u003c/td\u003e\u003ctd\u003e\u003cspan class="${badgeClass}"\u003e${badgeText}\u003c/span\u003e\u003c/td\u003e\u003ctd\u003e${escapeHtml(reason)}\u003c/td\u003e\u003c/tr\u003e`;
                };
                const gainersDetails = document.getElementById('scanned-gainers-details');
                if (gainersDetails) {
                    const table = gainersDetails.querySelector('table tbody');
                    if (table) {
                        table.innerHTML = allGainers.length
                            ? allGainers.map(s => renderScannedRow(s, false)).join('')
                            : '\u003ctr\u003e\u003ctd colspan="9" style="text-align:center;color:var(--text-secondary)"\u003eNo gainers data available for this scan\u003c/td\u003e\u003c/tr\u003e';
                    }
                }
                const losersDetails = document.getElementById('scanned-losers-details');
                if (losersDetails) {
                    const table = losersDetails.querySelector('table tbody');
                    if (table) {
                        table.innerHTML = allLosers.length
                            ? allLosers.map(s => renderScannedRow(s, true)).join('')
                            : '\u003ctr\u003e\u003ctd colspan="9" style="text-align:center;color:var(--text-secondary)"\u003eNo losers data available for this scan\u003c/td\u003e\u003c/tr\u003e';
                    }
                }

                // Update header status badge to reflect actual market phase.
                updateScannerStatusBadge(marketStatus, allGainers.length, allLosers.length);

            } catch (e) {
                console.error('Live data refresh failed:', e);
            } finally {
                setMarketLoading(currentMarket, false);
                // Reset the visible refresh countdown every time a fetch completes
                // (success or failure) so the timer stays honest after manual refresh.
                resetRefreshTimer();
            }
        }

        // Initialise: load data first, then anchor the refresh countdown to the JSON timestamp.
        // This prevents a brief flash of "15:00" before the first fetch completes.
        (async function init() {
            resetScannerToggleToLive();
            await loadLiveData();
            resetRefreshTimer();
        })();

