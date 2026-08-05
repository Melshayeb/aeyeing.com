
const fs = require('fs');
const { JSDOM } = require('jsdom');

const html = fs.readFileSync('C:/Users/openclaw/Desktop/aeyeing.com/ozmoeg-trader-asx.html', 'utf8');
const dom = new JSDOM(html, { runScripts: 'dangerously', url: 'https://aeyeing.com/ozmoeg-trader-asx.html?nocache=node1' });
const window = dom.window;

setTimeout(() => {
  const results = [];
  results.push('getFloat type: ' + typeof window.getFloat);
  results.push('getPrice type: ' + typeof window.getPrice);
  results.push('renderScannerRow type: ' + typeof window.renderScannerRow);
  results.push('populateAlertSelector type: ' + typeof window.populateAlertSelector);

  const r = { ticker: 'BJDX', price: 1.46, market_cap: 1417000, plan: { entry: 1.46, stop: 1.43, target1: 1.52, target2: 1.55, target3: 1.61, shares: 100, risk_reward: 2.0 }, status: 'ALERT', country: 'United States', news: { max_score: 0, headlines: [] }, name: 'Bluejay Diagnostics Inc' };
  try {
    const fl = window.getFloat(r);
    results.push('getFloat(BJDX): ' + fl);
  } catch (e) {
    results.push('getFloat error: ' + e.message);
  }

  try {
    window.populateAlertSelector([r]);
    const sel = window.document.getElementById('alert-selector');
    results.push('dropdown options count: ' + (sel ? sel.options.length : 'no selector'));
    results.push('option[1]: ' + (sel && sel.options[1] ? sel.options[1].textContent : 'none'));
  } catch (e) {
    results.push('populateAlertSelector error: ' + e.message);
  }

  try {
    window.renderScannerRow(r);
    results.push('renderScannerRow succeeded');
  } catch (e) {
    results.push('renderScannerRow error: ' + e.message);
  }

  fs.writeFileSync('C:/Users/openclaw/Desktop/aeyeing.com/test-alert-dropdown-asx.out.txt', results.join('\n'));
  console.log(results.join('\n'));
  window.close();
}, 2000);
