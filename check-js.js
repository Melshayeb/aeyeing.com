const acorn = require('./node_modules/acorn');
const fs = require('fs');
const html = fs.readFileSync('ozmoeg-trader.html', 'utf8');
const scripts = html.match(/<script[^>]*>([\s\S]*?)<\/script>/gi) || [];
for (let i = 0; i < scripts.length; i++) {
  const code = scripts[i].replace(/<script[^>]*>|<\/script>/gi, '');
  try {
    acorn.parse(code, { ecmaVersion: 'latest' });
    console.log('script', i, 'OK');
  } catch(e) {
    console.log('script', i, 'ERROR:', e.message);
    process.exit(1);
  }
}
console.log('All inline JS parsed OK');
