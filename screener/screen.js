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

// one-sided p-value that the mean trade return on the holdout is > 0 (normal approximation of
// the t statistic; holdout tests need >= 15 trades, where it is adequate)
function pValue(trades) {
  const x = trades.map((t) => t.pct), n = x.length;
  if (n < 3) return 1;
  const m = x.reduce((a, b) => a + b, 0) / n;
  const sd = Math.sqrt(x.reduce((a, b) => a + (b - m) ** 2, 0) / (n - 1));
  if (!(sd > 0)) return m > 0 ? 0 : 1;
  const t = m / sd * Math.sqrt(n);
  return 0.5 * erfc(t / Math.SQRT2);
}
function erfc(z) { // Numerical Recipes erfc (|err| < 1.2e-7)
  const t = 1 / (1 + 0.5 * Math.abs(z));
  const r = t * Math.exp(-z * z - 1.26551223 + t * (1.00002368 + t * (0.37409196 + t * (0.09678418 + t * (-0.18628806 +
    t * (0.27886807 + t * (-1.13520398 + t * (1.48851587 + t * (-0.82215223 + t * 0.17087277)))))))));
  return z >= 0 ? r : 2 - r;
}

const pick = (m) => m && { trades: m.trades, pf: +m.pf.toFixed(3), net: +m.netPct.toFixed(2), dd: +m.maxDD.toFixed(2),
  sharpe: +m.sharpe.toFixed(3), win: +m.winRate.toFixed(1) };

function screenSeries(job, opt) {
  const d = JSON.parse(fs.readFileSync(job.file, 'utf8'));
  const n = d.c.length, ivMin = job.tf === '15m' ? 15 : 60, iv = String(ivMin), bpd = 1440 / ivMin;
  const warm = 400, split = Math.floor(n * 0.6);
  let evaluated = 0;
  const out = [], pvals = [];
  if (n < 2000) return { evaluated, survivors: out, pvals };
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
      const st = steadiness(r.bt.eq, bpd), mB = r.m, pv = pValue(r.bt.trades);
      pvals.push(pv);
      const pass = mB.trades >= opt.minTradesB && mB.pf >= 1.15 && mB.netPct > 0 && st.r2 >= 0.5 && st.last90 >= 0 && mB.maxDD < 30;
      if (!pass) continue;
      const eq = r.bt.eq, step = Math.max(1, Math.ceil(eq.length / 100)), curve = [];
      for (let i = 0; i < eq.length; i += step) curve.push([d.t[split + i], +(eq[i] / 10000).toFixed(4)]);
      curve.push([d.t[n - 1], +(eq[eq.length - 1] / 10000).toFixed(4)]);
      out.push({ strategy: strat.id, family: FAMILY[strat.id], name: strat.name, pair: job.pair, timeframe: job.tf, curve,
        params: c.p, exits: c.x, A: pick(c.m), B: pick(mB), r2: +st.r2.toFixed(3), last90: +(st.last90 * 100).toFixed(2), p: pv,
        holdout_from: d.t[split], holdout_to: d.t[n - 1] });
    }
  }
  return { evaluated, survivors: out, pvals };
}

/* Pooled mode: one configuration must work across all coins of a timeframe. Per-coin
   holdouts have only 15–40 trades, so after the false-discovery correction over ~1 200
   tests nothing can be significant; pooling gives hundreds of holdout trades per test and
   ~20× fewer tests, and an edge that holds on many coins is far less likely to be luck. */
function screenPooled(job, opt) {
  const series = job.files.map((f) => ({ pair: f.pair, d: JSON.parse(fs.readFileSync(f.file, 'utf8')) }))
    .filter((x) => x.d.c.length >= 2000);
  const ivMin = job.tf === '15m' ? 15 : 60, iv = String(ivMin), bpd = 1440 / ivMin, warm = 400;
  const strat = E.STRATEGIES.find((x) => x.id === job.strategy);
  let evaluated = 0;
  const out = [], pvals = [];
  if (!strat || series.length < 5) return { evaluated, survivors: out, pvals };
  const ranges = strat.params.map((q) => ({ key: q.key, min: q.min, max: q.max, step: q.step, type: q.type }));
  const combos = E.randomCombos({}, ranges, opt.combos, opt.seed + job.k * 7919);
  let rnd = opt.seed + job.k;
  const best = [];
  for (const raw of combos) {
    const p = symmetric(strat.id, raw);
    rnd = (rnd * 1103515245 + 12345) & 0x7fffffff;
    const x = EXITS[rnd % EXITS.length];
    const nets = [];
    let trades = 0;
    for (const sr of series) {
      const split = Math.floor(sr.d.c.length * 0.6);
      const m = E.evaluate(sr.d, strat, p, settings(x), { from: warm, to: split - 1, iv });
      evaluated++;
      if (!m) continue;
      nets.push(m.netPct); trades += m.trades;
    }
    if (trades < opt.minTradesA * 4 || nets.length < 5) continue;
    const mean = nets.reduce((a, b) => a + b, 0) / nets.length;
    const sd = Math.sqrt(nets.reduce((a, b) => a + (b - mean) ** 2, 0) / Math.max(nets.length - 1, 1)) || 1e-9;
    const breadth = nets.filter((v) => v > 0).length / nets.length;
    if (mean <= 0 || breadth < 0.55) continue;
    best.push({ p, x, score: mean / sd * Math.sqrt(nets.length), A: { trades, net: +mean.toFixed(2), breadth: +breadth.toFixed(2) } });
  }
  best.sort((a, b) => b.score - a.score);
  for (const c of best.slice(0, opt.top)) {
    const all = [], per = [];
    for (const sr of series) {
      const n = sr.d.c.length, split = Math.floor(n * 0.6);
      const r = E.run(sr.d, strat, c.p, settings(c.x), { from: split, to: n - 1, iv });
      evaluated++;
      per.push({ pair: sr.pair, net: r.m.netPct, trades: r.m.trades, dd: r.m.maxDD });
      for (const t of r.bt.trades) all.push({ pct: t.pct / series.length, xt: t.xt, pnl: t.pnl });
    }
    const pv = pValue(all);
    pvals.push(pv);
    all.sort((a, b) => a.xt - b.xt);
    const eq = [], ts = [];
    let v = 1;
    for (const t of all) { v *= 1 + t.pct / 100; eq.push(v); ts.push(t.xt); }
    const st = steadiness(eq, 0);
    const lastT = ts.length ? ts[ts.length - 1] : 0, k90 = ts.findIndex((t) => t >= lastT - 90 * 864e5);
    const last90 = k90 >= 0 && eq[k90] > 0 ? eq[eq.length - 1] / (k90 > 0 ? eq[k90 - 1] : 1) - 1 : 0;
    const gp = all.filter((t) => t.pnl > 0).reduce((a, t) => a + t.pnl, 0), gl = -all.filter((t) => t.pnl < 0).reduce((a, t) => a + t.pnl, 0);
    const pf = gl > 0 ? gp / gl : 0, net = per.reduce((a, b) => a + b.net, 0) / per.length;
    const breadth = per.filter((q) => q.net > 0).length / per.length;
    const pass = all.length >= opt.minTradesB * 6 && pf >= 1.1 && net > 0 && st.r2 >= 0.5 && last90 >= 0 && breadth >= 0.55;
    if (!pass) continue;
    const step = Math.max(1, Math.ceil(eq.length / 100)), curve = [];
    for (let i = 0; i < eq.length; i += step) curve.push([ts[i], +eq[i].toFixed(4)]);
    if (eq.length) curve.push([ts[eq.length - 1], +eq[eq.length - 1].toFixed(4)]);
    const goodPairs = per.filter((q) => q.net > 0).sort((a, b) => b.net - a.net).map((q) => q.pair);
    out.push({ strategy: strat.id, family: FAMILY[strat.id], name: strat.name, pooled: true, pair: goodPairs[0],
      pairs: goodPairs.slice(0, 8), timeframe: job.tf, curve, params: c.p, exits: c.x, A: c.A,
      B: { trades: all.length, pf: +pf.toFixed(3), net: +net.toFixed(2), dd: +Math.max(...per.map((q) => q.dd)).toFixed(2),
        win: +(all.filter((t) => t.pnl > 0).length / Math.max(all.length, 1) * 100).toFixed(1), breadth: +breadth.toFixed(2),
        coins: per.length }, r2: +st.r2.toFixed(3), last90: +(last90 * 100).toFixed(2), p: pv });
  }
  return { evaluated, survivors: out, pvals };
}

/* Benjamini–Hochberg: among all holdout tests (m), keep discoveries with p <= p*, where p* is
   the largest p_(k) <= k/m * q. Controls the expected share of lucky survivors at q. */
function bhThreshold(pvals, q) {
  const p = [...pvals].sort((a, b) => a - b), m = p.length;
  let thr = -1;
  for (let k = 1; k <= m; k++) if (p[k - 1] <= k / m * q) thr = p[k - 1];
  return thr;
}

function parseArgs() {
  const a = process.argv.slice(2), o = { combos: 260, top: 4, workers: os.cpus().length, seed: 7, minTradesA: 30, minTradesB: 15, fdr: 0.2, mode: 'pooled' };
  for (let i = 0; i < a.length; i += 2) {
    const k = a[i].replace(/^--/, ''), v = a[i + 1];
    o[k.replace(/-([a-z])/g, (_, c) => c.toUpperCase())] = isNaN(+v) ? v : +v;
  }
  return o;
}

if (isMainThread && require.main === module) {
  const opt = parseArgs();
  const files = fs.readdirSync(opt.data).filter((f) => f.endsWith('.json')).sort();
  const seriesJobs = files.map((f, k) => {
    const m = f.match(/^(.+)__(15m|1h)\.json$/);
    return m && { k, file: path.join(opt.data, f), pair: m[1].replace(/_/g, '/').replace(/\/USDT\/USDT$/, '/USDT:USDT'), tf: m[2] };
  }).filter(Boolean);
  let jobs = seriesJobs;
  if (opt.mode === 'pooled') {  // one task per strategy × timeframe, over all coins of that timeframe
    jobs = [];
    for (const tf of [...new Set(seriesJobs.map((j) => j.tf))]) {
      const tfFiles = seriesJobs.filter((j) => j.tf === tf);
      for (const st of E.STRATEGIES) if (FAMILY[st.id]) jobs.push({ k: jobs.length, pooled: true, tf, strategy: st.id, files: tfFiles });
    }
  }
  const t0 = Date.now();
  const all = [], pvals = [];
  let evaluated = 0, done = 0, next = 0;
  const finish = () => {
    const q = opt.fdr, thr = bhThreshold(pvals, q), before = all.length;
    const kept = all.filter((x) => x.p <= thr);
    all.length = 0; all.push(...kept);
    console.log(`false-discovery control: ${pvals.length} holdout tests, BH q=${q} → p ≤ ${thr < 0 ? "none" : thr.toExponential(2)}; ${before} → ${kept.length}`);
    all.sort((a, b) => b.B.sharpe - a.B.sharpe);
    const res = { created: new Date().toISOString(), engine: 'Bybit Strategy Lab engine.js (owner)', evaluated,
      series: seriesJobs.length, mode: opt.mode, tasks: jobs.length, seconds: Math.round((Date.now() - t0) / 1000), holdout_tests: pvals.length, fdr_q: opt.fdr,
      expected_false: +(all.length * opt.fdr).toFixed(1), rules: {
        search: 'first 60% of history', holdout: 'last 40% (unseen by the search)',
        pass: (opt.mode === 'pooled' ? 'one config on all coins of a timeframe: holdout trades>=90, PF>=1.1, mean return>0, ' +
          'profitable on >=55% of coins, pooled equity R²>=0.5, last 90 days>=0, ' : 'holdout trades>=15, PF>=1.15, return>0, equity R²>=0.5, last 90 days>=0, max DD<30%, ') +
          'and significant after Benjamini–Hochberg over all holdout tests (q=' + opt.fdr + ')' },
      survivors: all };
    fs.writeFileSync(opt.out, JSON.stringify(res));
    console.log(`screened ${evaluated} backtests (${opt.mode}) on ${seriesJobs.length} series in ${res.seconds}s → ${all.length} survivors`);
  };
  if (!jobs.length) { finish(); return; }
  const nw = Math.max(1, Math.min(opt.workers, jobs.length));
  for (let w = 0; w < nw; w++) {
    const wk = new Worker(__filename, { workerData: { opt } });
    const feed = () => { if (next < jobs.length) wk.postMessage(jobs[next++]); else wk.postMessage(null); };
    wk.on('message', (r) => {
      evaluated += r.evaluated; all.push(...r.survivors); pvals.push(...(r.pvals || [])); done++;
      if (done % 10 === 0) console.log(`${done}/${jobs.length} tasks, ${evaluated} combinations, ${all.length} survivors`);
      feed();
    });
    wk.on('exit', () => { if (done === jobs.length && !finish.done) { finish.done = true; finish(); } });
    feed();
  }
} else if (!isMainThread) {
  parentPort.on('message', (job) => {
    if (!job) { process.exit(0); }
    let r;
    try { r = job.pooled ? screenPooled(job, workerData.opt) : screenSeries(job, workerData.opt); } catch (e) { console.error(job.file || job.strategy, e.message); r = { evaluated: 0, survivors: [], pvals: [] }; }
    parentPort.postMessage(r);
  });
}

module.exports = { screenSeries, screenPooled, steadiness, FAMILY, pValue, bhThreshold };
