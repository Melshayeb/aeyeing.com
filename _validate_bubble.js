const fs = require('fs');
const h = fs.readFileSync('ozmoeg-trader.html', 'utf8');
const m = h.match(/<script[\s\S]*?>([\s\S]*?)<\/script>/g);
let ok=0,bad=0;
m.forEach((s,i) => {
  const b=s.replace(/<script[^>]*>/i,'').replace(/<\/script>/i,'');
  if(!b.trim())return;
  try{new Function(b); ok++;}catch(e){bad++; console.error('script',i,'ERR:',e.message);}
});
const open=(h.match(/<div/gi)||[]).length, close=(h.match(/<\/div>/gi)||[]).length;
console.log('JS scripts:',ok,'OK,',bad,'bad');
console.log('div balance:',open,close);
process.exit(open===close && bad===0 ? 0 : 1);
