import re
content = open('ozmoeg-trader.html', encoding='utf-8').read()
start = content.find('function renderScannerView()')
chunk = content[start:start+12000]
print('renderScannerView braces open', chunk.count('{'), 'close', chunk.count('}'))
start2 = content.find('async function renderSelectedAlert()')
chunk2 = content[start2:start2+9000]
print('renderSelectedAlert braces open', chunk2.count('{'), 'close', chunk2.count('}'))
bad = re.findall(r'tbody\.innerHTML = `[^`]*\$', chunk)
print('suspicious template literals', len(bad))
print('contains async renderSelectedAlert:', 'async function renderSelectedAlert()' in content)
print('contains resolveLiveEntryPrice:', 'resolveLiveEntryPrice' in content)
print('contains isExtendedHoursSession:', 'isExtendedHoursSession' in content)
