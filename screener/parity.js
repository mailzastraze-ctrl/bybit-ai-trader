// Parity helper for tests: the engine's own entry/exit signals for one rule on given candles.
// Usage: node screener/parity.js <candles.json> <strategy id> '<params json>'
const fs = require('fs');
const E = require('./engine.js');
const [file, id, pjson] = process.argv.slice(2);
const d = JSON.parse(fs.readFileSync(file, 'utf8'));
const strat = E.getBuiltin(id);
const p = E.paramsWithDefaults ? E.paramsWithDefaults(strat, JSON.parse(pjson)) : JSON.parse(pjson);
const sg = E.normalizeSignals(strat.signals(d, p, E.ta), d.c.length);
const bits = (a) => Array.from(a, (v) => (v ? 1 : 0));
process.stdout.write(JSON.stringify({ le: bits(sg.longEntry), se: bits(sg.shortEntry), lx: bits(sg.longExit), sx: bits(sg.shortExit) }));
