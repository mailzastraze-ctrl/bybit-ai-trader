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


/* Swing mode — the Strategy Lab autopilot: rare but accurate trades on higher timeframes.
   Everything the Lab offers as separate tabs runs automatically, per coin × timeframe × rule;
   a configuration survives only if it passes ALL checks (bad ones are never shown):
   1. search      random parameters × exits on ~3 years (everything but the last 90 days)
   2. stability   on those years: 0.5–12 trades/month and >= 20 trades, PF >= 1.4, every
                  third of the period profitable, equity R² >= 0.75, max drawdown <= 25%
   3. robustness  >= 70% of neighbouring parameter sets also profitable (PF >= 1.15)
   4. walk-fwd    the same search, re-run without the last year, must find a configuration
                  that is profitable on that unseen year (tests the method, not the lucky pick)
   5. last 3 mo.  never seen by any search: at least one trade and not losing
   6. Monte Carlo resampled trades: 95th-percentile drawdown <= 35%, P(loss) <= 10%
   7. coins       tested on the other top coins of the timeframe; coins where it also holds
                  (profitable on the 3 years and not losing in the last 3 months) join its list
   Seven checks are still not enough on their own: on pure random walks this search finds
   "perfect" configurations (Sharpe 2+, PF 4, several coins) simply because it tries
   ~10^5 of them. So the whole procedure is also run on decoys — the same coins with their
   daily blocks of returns shuffled in time (jointly across coins, so correlations stay but
   any real predictability is destroyed). A survivor is accepted only above the score where
   decoys would supply at most q (20%) of the accepted list (target–decoy false-discovery
   control): what is left beat luck, not just looked good. */
const SWING_TF = { '2h': 120, '4h': 240, '6h': 360, '12h': 720 };
const DAY = 864e5;

function idxAt(t, ms) { let lo = 0, hi = t.length; while (lo < hi) { const m = (lo + hi) >> 1; if (t[m] < ms) lo = m + 1; else hi = m; } return lo; }

function blocksOk(eq, parts) { // every block of the period ends above where it started
  const n = eq.length;
  for (let k = 0; k < parts; k++) {
    const a = Math.floor(k * n / parts), b = Math.floor((k + 1) * n / parts) - 1;
    if (b <= a || !(eq[b] > eq[a])) return false;
  }
  return true;
}

function stableOn(d, strat, p, x, from, to, iv, opt, parts) { // checks 1–2 on [from, to]
  const m = E.evaluate(d, strat, p, settings(x), { from, to, iv });
  if (!m || m.trades < opt.swingMinTrades || m.tradesPerMonth < 0.5 || m.tradesPerMonth > 12 || m.pf < 1.4
      || m.netPct <= 0 || m.maxDD > 25) return null;
  const r = E.run(d, strat, p, settings(x), { from, to, iv });
  const st = steadiness(r.bt.eq, 0);
  if (st.r2 < 0.75 || !blocksOk(r.bt.eq, parts)) return null;
  return { m, r, r2: st.r2 };
}

function searchBest(d, strat, ranges, opt, seed, from, to, iv, parts, keep) {
  const combos = E.randomCombos({}, ranges, opt.swingCombos, seed);
  let rnd = seed, evaluated = 0;
  const found = [];
  for (const raw of combos) {
    const p = symmetric(strat.id, raw);
    rnd = (rnd * 1103515245 + 12345) & 0x7fffffff;
    const x = EXITS[rnd % EXITS.length];
    evaluated++;
    const ok = stableOn(d, strat, p, x, from, to, iv, opt, parts);
    if (ok) found.push({ p, x, ...ok, score: ok.m.sharpe * ok.r2 });
  }
  found.sort((a, b) => b.score - a.score);
  return { evaluated, best: found.slice(0, keep) };
}

function neighbours(strat, p) {
  const out = [];
  for (const q of strat.params) {
    if (q.type === 'bool') continue;
    for (const s of [-1, 1]) {
      const v = +(p[q.key] + s * q.step).toFixed(8);
      if (v < q.min || v > q.max) continue;
      const n = symmetric(strat.id, { ...p, [q.key]: v });
      if (!strat.valid || strat.valid(n)) out.push(n);
    }
  }
  return out;
}

function tradeP(trades) { return pValue(trades); }

// Decoy: daily blocks of each bar's (return, open/high/low shape) shuffled in time with one
// permutation shared by every coin of the timeframe (blocks counted from the latest bar).
function decoySeries(d, perm, block) {
  const n = d.c.length, m = Math.floor(n / block), start = n - m * block;
  const order = perm.filter((j) => j < m);
  const r = new Float64Array(n), oo = new Float64Array(n), hh = new Float64Array(n), ll = new Float64Array(n);
  for (let i = 1; i < n; i++) { r[i] = Math.log(d.c[i] / d.c[i - 1]); oo[i] = d.o[i] / d.c[i]; hh[i] = d.h[i] / d.c[i]; ll[i] = d.l[i] / d.c[i]; }
  const out = { t: d.t, o: [], h: [], l: [], c: [], v: d.v };
  let c = d.c[start];
  const push = (i) => { c *= Math.exp(r[i]); out.c.push(c); out.o.push(c * oo[i]); out.h.push(c * Math.max(hh[i], 1, oo[i])); out.l.push(c * Math.min(ll[i], 1, oo[i])); };
  for (let i = 0; i < start; i++) { out.c.push(d.c[i]); out.o.push(d.o[i]); out.h.push(d.h[i]); out.l.push(d.l[i]); }
  // blocks are numbered from the end: block j covers bars [n-(j+1)*block, n-j*block)
  for (let k = m - 1; k >= 0; k--) { const j = order[m - 1 - k]; const b0 = n - (j + 1) * block; for (let i = b0; i < b0 + block; i++) push(Math.max(i, 1)); }
  return out;
}
function permutation(m, seed) {
  const rnd = mulberry(seed), a = Array.from({ length: m }, (_, i) => i);
  for (let i = m - 1; i > 0; i--) { const j = Math.floor(rnd() * (i + 1)); [a[i], a[j]] = [a[j], a[i]]; }
  return a;
}
function mulberry(a) { return () => { a |= 0; a = a + 0x6D2B79F5 | 0; let t = Math.imul(a ^ a >>> 15, 1 | a); t = t + Math.imul(t ^ t >>> 7, 61 | t) ^ t; return ((t ^ t >>> 14) >>> 0) / 4294967296; }; }

function swingTask(job, opt) {
  const tfMin = SWING_TF[job.tf], iv = String(tfMin);
  const strat = E.STRATEGIES.find((x) => x.id === job.strategy);
  let series = job.files.map((f) => ({ pair: f.pair, d: JSON.parse(fs.readFileSync(f.file, 'utf8')) }))
    .filter((x) => x.d.c.length > 400 && x.d.t[x.d.t.length - 1] - x.d.t[0] >= opt.swingMinDays * DAY);
  if (job.decoy) {
    const block = Math.round(1440 / tfMin), maxM = Math.max(1, ...series.map((x) => Math.floor(x.d.c.length / block)));
    const perm = permutation(maxM, 7777 + job.decoy * 131 + tfMin);
    series = series.map((x) => ({ pair: x.pair, d: decoySeries(x.d, perm, block) }));
  }
  const out = [], pvals = [];
  let evaluated = 0;
  if (!strat || !series.length) return { evaluated, survivors: out, pvals, tested: 0 };
  const ranges = strat.params.map((q) => ({ key: q.key, min: q.min, max: q.max, step: q.step, type: q.type }));
  const warm = 300;
  const cut = (d) => { // index boundaries: search | walk-forward year | last 90 days
    const tEnd = d.t[d.t.length - 1], hold = idxAt(d.t, tEnd - 90 * DAY), wf = idxAt(d.t, d.t[hold] - 365 * DAY);
    return { hold, wf, n: d.c.length };
  };
  let tested = 0;
  for (const [si, sr] of series.entries()) {
    const d = sr.d, c = cut(d);
    if (c.wf - warm < 365 * DAY / (tfMin * 60000)) continue;   // need >= 1 year before the walk-forward year
    const seed = opt.seed + job.k * 7919 + si * 104729;
    const s1 = searchBest(d, strat, ranges, opt, seed, warm, c.hold - 1, iv, 3, opt.top);
    evaluated += s1.evaluated;
    if (!s1.best.length) continue;
    // 4. walk-forward: the method, re-run without the last year, judged on that year
    const s2 = searchBest(d, strat, ranges, opt, seed + 31, warm, c.wf - 1, iv, 2, 1);
    evaluated += s2.evaluated;
    if (!s2.best.length) continue;
    const w = s2.best[0], wr = E.run(d, strat, w.p, settings(w.x), { from: c.wf, to: c.hold - 1, iv });
    evaluated++;
    const wfOk = wr.m.trades >= 1 && wr.m.netPct > 0 && wr.m.pf >= 1.1;
    for (const cand of s1.best) {
      tested++;
      // 3. robustness on the search period
      const nb = neighbours(strat, cand.p);
      let good = 0;
      for (const q of nb) {
        const m = E.evaluate(d, strat, q, settings(cand.x), { from: warm, to: c.hold - 1, iv });
        evaluated++;
        if (m && m.netPct > 0 && m.pf >= 1.15) good++;
      }
      const robust = nb.length ? good / nb.length : 0;
      // 5. last 3 months, unseen by every search
      const h = E.run(d, strat, cand.p, settings(cand.x), { from: c.hold, to: c.n - 1, iv });
      evaluated++;
      // 6. Monte Carlo over all trades (search + last 3 months)
      const pcts = cand.r.bt.trades.map((t) => t.pct).concat(h.bt.trades.map((t) => t.pct));
      const mc = E.monteCarlo(pcts, { sims: 600, method: 'bootstrap', seed: 99 });
      const mcOk = mc.ddQ[4] <= 35 && mc.probLoss <= 10;
      const holdOk = h.m.trades >= 1 && h.m.netPct >= 0 && h.m.maxDD <= 25;
      // unseen evidence for the significance note: the walk-forward year + the last 3 months
      const pv = tradeP(wr.bt.trades.concat(h.bt.trades));
      pvals.push(pv);
      if (!(robust >= 0.7 && wfOk && holdOk && mcOk)) continue;
      // 7. the same configuration on the other top coins of this timeframe
      const coins = [{ pair: sr.pair, sharpe: cand.m.sharpe }];
      for (const other of series) {
        if (other === sr) continue;
        const oc = cut(other.d);
        const mS = E.evaluate(other.d, strat, cand.p, settings(cand.x), { from: warm, to: oc.hold - 1, iv });
        const mH = E.evaluate(other.d, strat, cand.p, settings(cand.x), { from: oc.hold, to: oc.n - 1, iv });
        evaluated += 2;
        if (mS && mH && mS.trades >= opt.swingMinTrades && mS.pf >= 1.2 && mS.netPct > 0 && mS.maxDD <= 30 && mH.netPct >= 0)
          coins.push({ pair: other.pair, sharpe: mS.sharpe });
      }
      coins.sort((a, b) => (a.pair === sr.pair ? -1 : b.pair === sr.pair ? 1 : b.sharpe - a.sharpe));
      const full = E.run(d, strat, cand.p, settings(cand.x), { from: warm, to: c.n - 1, iv });
      evaluated++;
      const eq = full.bt.eq, step = Math.max(1, Math.ceil(eq.length / 160)), curve = [];
      for (let i = 0; i < eq.length; i += step) curve.push([d.t[warm + i], +(eq[i] / 10000).toFixed(4)]);
      curve.push([d.t[c.n - 1], +(eq[eq.length - 1] / 10000).toFixed(4)]);
      const A = { ...pick(cand.m), tpm: +cand.m.tradesPerMonth.toFixed(2), years: +(cand.m.days / 365).toFixed(1) };
      out.push({ strategy: strat.id, family: FAMILY[strat.id], name: strat.name, mode: 'swing', pair: sr.pair,
        pairs: coins.slice(0, 15).map((q) => q.pair), timeframe: job.tf, curve, params: cand.p, exits: cand.x,
        A, B: { ...pick(h.m), sharpe: +h.m.sharpe.toFixed(3) }, r2: +cand.r2.toFixed(3), last90: +h.m.netPct.toFixed(2),
        robust: +robust.toFixed(2), wf: { ...pick(wr.m), params: w.p, exits: w.x },
        mc: { dd95: +mc.ddQ[4].toFixed(1), ploss: +mc.probLoss.toFixed(1) },
        coins: { tested: series.length, pass: coins.length, list: coins.map((q) => q.pair) },
        p: pv, holdout_from: d.t[c.hold], wf_from: d.t[c.wf],
        // evidence: steady Sharpe on ~3 years × robustness, plus every other coin it also holds on
        score: +(cand.score * robust * (1 + 0.15 * (coins.length - 1))).toFixed(3) });
    }
  }
  return { evaluated, survivors: out, pvals, tested };
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
  const a = process.argv.slice(2), o = { combos: 260, top: 4, workers: os.cpus().length, seed: 7, minTradesA: 30, minTradesB: 15, fdr: 0.2, mode: 'pooled',
    swingCombos: 500, swingMinTrades: 20, swingMinDays: 900, decoys: 2 };
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
    const m = f.match(/^(.+)__(15m|1h|2h|4h|6h|12h)\.json$/);
    return m && { k, file: path.join(opt.data, f), pair: m[1].replace(/_/g, '/').replace(/\/USDT\/USDT$/, '/USDT:USDT'), tf: m[2] };
  }).filter(Boolean);
  const modes = String(opt.mode).split(',');
  const intraday = seriesJobs.filter((j) => !SWING_TF[j.tf]), swingSeries = seriesJobs.filter((j) => SWING_TF[j.tf]);
  let jobs = [];
  if (modes.includes('pair')) jobs.push(...intraday.map((j) => ({ ...j, k: jobs.length })));
  if (modes.includes('pooled')) {  // one task per strategy × timeframe, over all coins of that timeframe
    for (const tf of [...new Set(intraday.map((j) => j.tf))]) {
      const tfFiles = intraday.filter((j) => j.tf === tf);
      for (const st of E.STRATEGIES) if (FAMILY[st.id]) jobs.push({ k: jobs.length, pooled: true, tf, strategy: st.id, files: tfFiles });
    }
  }
  if (modes.includes('swing')) {   // one task per strategy × higher timeframe (all top coins)
    for (const tf of Object.keys(SWING_TF)) {
      const tfFiles = swingSeries.filter((j) => j.tf === tf);
      if (!tfFiles.length) continue;
      for (const st of E.STRATEGIES) if (FAMILY[st.id]) {
        jobs.push({ k: jobs.length, swing: true, tf, strategy: st.id, files: tfFiles });
        for (let c = 1; c <= opt.decoys; c++) jobs.push({ k: jobs.length, swing: true, decoy: c, tf, strategy: st.id, files: tfFiles });
      }
    }
  }
  const t0 = Date.now();
  const all = [], pvals = [], swing = [], swingP = [], decoyScores = [];
  let evaluated = 0, done = 0, next = 0, swingTested = 0;
  const swingStats = {};
  const finish = () => {
    const q = opt.fdr, thr = bhThreshold(pvals, q), before = all.length;
    const kept = all.filter((x) => x.p <= thr);
    all.length = 0; all.push(...kept);
    console.log(`false-discovery control: ${pvals.length} holdout tests, BH q=${q} → p ≤ ${thr < 0 ? "none" : thr.toExponential(2)}; ${before} → ${kept.length}`);
    all.sort((a, b) => b.B.sharpe - a.B.sharpe);
    // swing survivors passed seven independent checks; the significance of their unseen trades
    // (walk-forward year + last 3 months) is reported, the walk-forward runners and the
    // forward test decide. Strongest first.
    const sThr = bhThreshold(swingP, q);
    for (const x of swing) x.significant = sThr >= 0 && x.p <= sThr;
    swing.sort((a, b) => b.score - a.score);
    // target–decoy: largest accepted list whose expected decoy (luck) share is <= q
    const nd = Math.max(1, opt.decoys), dec = decoyScores.slice().sort((a, b) => b - a);
    let accept = 0, cutScore = null;
    for (let k = 1; k <= swing.length; k++) {
      const sc = swing[k - 1].score, falseN = dec.filter((v) => v >= sc).length / nd;
      if (falseN / k <= q) { accept = k; cutScore = sc; }
    }
    const passed7 = swing.length, accepted = swing.slice(0, accept);
    for (const x of accepted) x.luck_share = +(dec.filter((v) => v >= x.score).length / nd / Math.max(1, accepted.indexOf(x) + 1)).toFixed(2);
    // order for the runners: strongest first, but prefer configurations that bring coins not
    // yet covered, so the accepted set spreads over as many of the top coins as it honestly can
    const covered = new Set(), ordered = [], pool = accepted.slice();
    while (pool.length) {
      let bi = 0, bv = -Infinity;
      pool.forEach((x, i) => { const fresh = x.pairs.filter((p) => !covered.has(p)).length; const v = (fresh ? 1e3 : 0) + x.score; if (v > bv) { bv = v; bi = i; } });
      const x = pool.splice(bi, 1)[0]; x.pairs.forEach((p) => covered.add(p)); ordered.push(x);
    }
    swing.length = 0; swing.push(...ordered);
    swingStats.coins_covered = covered.size;
    swingStats.passed7 = passed7; swingStats.decoy_survivors = +(dec.length / nd).toFixed(1); swingStats.cut_score = cutScore;
    console.log(`swing autopilot: ${swingTested} configurations reached the checks, ${passed7} passed all seven; ` +
      `decoys (shuffled history) passed ${swingStats.decoy_survivors} per copy → accepted ${accept} at luck share <= ${q}` +
      ` (${swing.filter((x) => x.significant).length} also significant at BH q=${q})`);
    all.unshift(...swing);
    const res = { created: new Date().toISOString(), engine: 'Bybit Strategy Lab engine.js (owner)', evaluated,
      series: seriesJobs.length, mode: opt.mode, tasks: jobs.length, swing_tested: swingTested, swing_survivors: swing.length, swing_passed_checks: swingStats.passed7,
      swing_decoy_survivors: swingStats.decoy_survivors, swing_cut_score: swingStats.cut_score, swing_decoys: opt.decoys, swing_coins_covered: swingStats.coins_covered || 0, seconds: Math.round((Date.now() - t0) / 1000), holdout_tests: pvals.length, fdr_q: opt.fdr,
      expected_false: +(all.length * opt.fdr).toFixed(1), rules: {
        search: 'first 60% of history', holdout: 'last 40% (unseen by the search)',
        pass: (opt.mode === 'pooled' ? 'one config on all coins of a timeframe: holdout trades>=90, PF>=1.1, mean return>0, ' +
          'profitable on >=55% of coins, pooled equity R²>=0.5, last 90 days>=0, ' : 'holdout trades>=15, PF>=1.15, return>0, equity R²>=0.5, last 90 days>=0, max DD<30%, ') +
          'and significant after Benjamini–Hochberg over all holdout tests (q=' + opt.fdr + ')',
        swing: '2h–12h, ~3 years + last 3 months: 0.5–12 trades/month, PF>=1.4, every third profitable, R²>=0.75, DD<=25%; ' +
          'neighbours >=70% profitable; walk-forward year profitable; last 3 months not losing; Monte Carlo DD95<=35%, P(loss)<=10%' },
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
      evaluated += r.evaluated; done++;
      if (r.decoy) decoyScores.push(...r.survivors.map((x) => x.score));
      else if (r.swing) { swing.push(...r.survivors); swingP.push(...(r.pvals || [])); swingTested += r.tested || 0; }
      else { all.push(...r.survivors); pvals.push(...(r.pvals || [])); }
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
    try {
      r = job.swing ? { ...swingTask(job, workerData.opt), swing: true, decoy: !!job.decoy }
        : job.pooled ? screenPooled(job, workerData.opt) : screenSeries(job, workerData.opt);
    } catch (e) { console.error(job.file || job.strategy, e.message); r = { evaluated: 0, survivors: [], pvals: [], swing: !!job.swing }; }
    parentPort.postMessage(r);
  });
}

module.exports = { screenSeries, screenPooled, swingTask, steadiness, FAMILY, pValue, bhThreshold, SWING_TF };
