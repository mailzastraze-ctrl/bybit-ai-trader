/* Mass screener (stage 1 of the research lab).
 *
 * Uses the owner's Bybit Strategy Lab engine (engine.js, unchanged) to try thousands of
 * strategy × parameter × exit combinations per coin and timeframe:
 *   A = first 60% of the history  → search (keep the best few per strategy)
 *   B = last 40% (never seen by the search) → must stay profitable with a steady equity
 *       curve (R² of the line), a positive last 3 months and enough trades.
 * Survivors go on to the freqtrade walk-forward (4 unseen windows, stress, Deflated Sharpe)
 * and the forward test on live data. Leverage 1x, Bybit fees, slippage, no reversal.
 *
 *   node screen.js --data DIR --out FILE [--combos 260] [--top 4] [--workers 4] [--seed 7]
 */
'use strict';
const fs = require('fs');
const path = require('path');
const os = require('os');
const { Worker, isMainThread, parentPort, workerData } = require('worker_threads');
const E = require('./engine.js');

// strategies with an exact twin family in the trading system (same signals)
const FAMILY = {
  zscore: 'zscore_revert', supertrend: 'supertrend', macd: 'macd_cross', adx_di: 'adx_di', hma_trend: 'hull_turn',
  rsi_revert: 'rsi_revert', stoch: 'stoch_cross', ema_cross: 'ema_cross', bb_revert: 'bb_revert', donchian: 'turtle',
};
// exits the trading system can reproduce: ATR stop, R:R take profit or none, ATR trail or none
const EXITS = [];
for (const sl of [1.5, 2, 2.5, 3, 4]) for (const tp of [0, 1.5, 2, 3, 4]) for (const tr of [0, 2, 3]) EXITS.push({ sl, tp, tr });

function settings(x) {
  return {
    category: 'linear', capital: 10000, sizing: 'pct', sizeValue: 100, leverage: 1, direction: 'both', marginMode: 'isolated',
    execOn: 'open', reverse: false, takerFee: 0.055, makerFee: 0.02, tpMaker: true, slippage: 0.02,
    slType: 'atr', slValue: x.sl, tpType: x.tp > 0 ? 'rr' : 'none', tpValue: x.tp, trailType: x.tr > 0 ? 'atr' : 'none',
    trailValue: x.tr || 2, atrLen: 14, maxBars: 0, funding: false, liquidation: false,
  };
}

function symmetric(id, p) { // the system's twins use symmetric levels
  if (id === 'rsi_revert') { p.upper = 100 - p.lower; p.exitS = 100 - p.exitL; }
  if (id === 'stoch') p.hi = 100 - p.lo;
  return p;
}

function steadiness(eq, barsPerDay) {
  const n = eq.length;
  if (n < 20) return { r2: 0, last90: 0 };
  let sx = 0, sy = 0, sxx = 0, sxy = 0;
  for (let i = 0; i < n; i++) { sx += i; sy += eq[i]; sxx += i * i; sxy += i * eq[i]; }
  const slope = (n * sxy - sx * sy) / (n * sxx - sx * sx), icpt = (sy - slope * sx) / n, mean = sy / n;
  let ssr = 0, sst = 0;
  for (let i = 0; i < n; i++) { const f = slope * i + icpt; ssr += (eq[i] - f) ** 2; sst += (eq[i] - mean) ** 2; }
  const r2 = sst > 0 ? Math.max(0, 1 - ssr / sst) * Math.sign(slope) : 0;
  const k = Math.max(0, n - Math.round(90 * barsPerDay));
  return { r2, last90: eq[k] > 0 ? eq[n - 1] / eq[k] - 1 : 0 };
}

const pick = (m) => m && { trades: m.trades, pf: +m.pf.toFixed(3), net: +m.netPct.toFixed(2), dd: +m.maxDD.toFixed(2),
  sharpe: +m.sharpe.toFixed(3), win: +m.winRate.toFixed(1) };

function screenSeries(job, opt) {
  const d = JSON.parse(fs.readFileSync(job.file, 'utf8'));
  const n = d.c.length, ivMin = job.tf === '15m' ? 15 : 60, iv = String(ivMin), bpd = 1440 / ivMin;
  const warm = 400, split = Math.floor(n * 0.6);
  let evaluated = 0;
  const out = [];
  if (n < 2000) return { evaluated, survivors: out };
  for (const strat of E.STRATEGIES) {
    if (!FAMILY[strat.id]) continue;
    const ranges = strat.params.map((q) => ({ key: q.key, min: q.min, max: q.max, step: q.step, type: q.type }));
    const combos = E.randomCombos({}, ranges, opt.combos, opt.seed + job.k * 7919);
    let rnd = opt.seed + job.k;
    const best = [];
    for (const raw of combos) {
      const p = symmetric(strat.id, raw);
      rnd = (rnd * 1103515245 + 12345) & 0x7fffffff;
      const x = EXITS[rnd % EXITS.length];
      const m = E.evaluate(d, strat, p, settings(x), { from: warm, to: split - 1, iv });
      evaluated++;
      if (!m || m.trades < opt.minTradesA || m.pf < 1.1 || m.netPct <= 0) continue;
      best.push({ p, x, m });
    }
    best.sort((a, b) => b.m.sharpe - a.m.sharpe);
    for (const c of best.slice(0, opt.top)) {
      const r = E.run(d, strat, c.p, settings(c.x), { from: split, to: n - 1, iv });
      evaluated++;
      const st = steadiness(r.bt.eq, bpd), mB = r.m;
      const pass = mB.trades >= opt.minTradesB && mB.pf >= 1.15 && mB.netPct > 0 && st.r2 >= 0.5 && st.last90 >= 0 && mB.maxDD < 30;
      if (!pass) continue;
      const eq = r.bt.eq, step = Math.max(1, Math.ceil(eq.length / 100)), curve = [];
      for (let i = 0; i < eq.length; i += step) curve.push([d.t[split + i], +(eq[i] / 10000).toFixed(4)]);
      curve.push([d.t[n - 1], +(eq[eq.length - 1] / 10000).toFixed(4)]);
      out.push({ strategy: strat.id, family: FAMILY[strat.id], name: strat.name, pair: job.pair, timeframe: job.tf, curve,
        params: c.p, exits: c.x, A: pick(c.m), B: pick(mB), r2: +st.r2.toFixed(3), last90: +(st.last90 * 100).toFixed(2),
        holdout_from: d.t[split], holdout_to: d.t[n - 1] });
    }
  }
  return { evaluated, survivors: out };
}

function parseArgs() {
  const a = process.argv.slice(2), o = { combos: 260, top: 4, workers: os.cpus().length, seed: 7, minTradesA: 30, minTradesB: 15 };
  for (let i = 0; i < a.length; i += 2) {
    const k = a[i].replace(/^--/, ''), v = a[i + 1];
    o[k.replace(/-([a-z])/g, (_, c) => c.toUpperCase())] = isNaN(+v) ? v : +v;
  }
  return o;
}

if (isMainThread) {
  const opt = parseArgs();
  const files = fs.readdirSync(opt.data).filter((f) => f.endsWith('.json')).sort();
  const jobs = files.map((f, k) => {
    const m = f.match(/^(.+)__(15m|1h)\.json$/);
    return m && { k, file: path.join(opt.data, f), pair: m[1].replace(/_/g, '/').replace(/\/USDT\/USDT$/, '/USDT:USDT'), tf: m[2] };
  }).filter(Boolean);
  const t0 = Date.now();
  const all = [];
  let evaluated = 0, done = 0, next = 0;
  const finish = () => {
    all.sort((a, b) => b.B.sharpe - a.B.sharpe);
    const res = { created: new Date().toISOString(), engine: 'Bybit Strategy Lab engine.js (owner)', evaluated,
      series: jobs.length, seconds: Math.round((Date.now() - t0) / 1000), rules: {
        search: 'first 60% of history', holdout: 'last 40% (unseen by the search)',
        pass: 'holdout trades>=15, PF>=1.15, return>0, equity R²>=0.5, last 90 days>=0, max DD<30%' },
      survivors: all };
    fs.writeFileSync(opt.out, JSON.stringify(res));
    console.log(`screened ${evaluated} combinations on ${jobs.length} series in ${res.seconds}s → ${all.length} survivors`);
  };
  if (!jobs.length) { finish(); return; }
  const nw = Math.max(1, Math.min(opt.workers, jobs.length));
  for (let w = 0; w < nw; w++) {
    const wk = new Worker(__filename, { workerData: { opt } });
    const feed = () => { if (next < jobs.length) wk.postMessage(jobs[next++]); else wk.postMessage(null); };
    wk.on('message', (r) => {
      evaluated += r.evaluated; all.push(...r.survivors); done++;
      if (done % 10 === 0) console.log(`${done}/${jobs.length} series, ${evaluated} combinations, ${all.length} survivors`);
      feed();
    });
    wk.on('exit', () => { if (done === jobs.length && !finish.done) { finish.done = true; finish(); } });
    feed();
  }
} else {
  parentPort.on('message', (job) => {
    if (!job) { process.exit(0); }
    let r;
    try { r = screenSeries(job, workerData.opt); } catch (e) { console.error(job.file, e.message); r = { evaluated: 0, survivors: [] }; }
    parentPort.postMessage(r);
  });
}

module.exports = { screenSeries, steadiness, FAMILY };
