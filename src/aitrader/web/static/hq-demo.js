// Demo data for a static preview of the HQ (loaded only when the company API does not exist).
// Shapes follow the real endpoints; every value here is made up and the HUD says so.
let s = 42;
const r = () => ((s = (s * 16807) % 2147483647) - 1) / 2147483646;
const PAIRS = ["BTC", "ETH", "SOL", "XRP", "DOGE", "LINK", "ADA", "AVAX", "SUI", "LTC", "BNB", "TON"].map(c => `${c}/USDT:USDT`);
const BASE = {BTC: 96400, ETH: 3420, SOL: 182, XRP: 1.42, DOGE: 0.231, LINK: 21.4, ADA: 0.81, AVAX: 38.2, SUI: 3.95, LTC: 104, BNB: 655, TON: 5.6};
const FAM = ["tsmom", "trend_ema", "macd", "meanrev_bb", "donchian", "supertrend", "zscore", "squeeze"];
const T0 = Date.now(), iso = ms => new Date(ms).toISOString();
const sleeves = Array.from({length: 12}, (_, i) => ({id: `b20261121-${812 + i}-${FAM[i % FAM.length].slice(0, 5)}-${String(i).padStart(2, "0")}`, family: FAM[i % FAM.length],
  pairs: [PAIRS[i % PAIRS.length], PAIRS[(i + 3) % PAIRS.length]], stage: i === 2 ? "incubation" : "exploration", risk: 0.001, params: {tp_rr: 2, sl_atr: 2}}));
const candles = {};
function series(pair) {
  if (candles[pair]) return candles[pair];
  const c = pair.split("/")[0]; let p = BASE[c] || 10; const rows = [];
  for (let i = 0; i < 72; i++) { const o = p; p *= 1 + (r() - 0.49) * 0.012 + Math.sin(i / 9) * 0.0015; rows.push([iso(T0 - (72 - i) * 3600e3), o, Math.max(o, p) * (1 + r() * 0.004), Math.min(o, p) * (1 - r() * 0.004), p, 1000 * r()]); }
  return (candles[pair] = rows);
}
function live(pair) { const rows = series(pair), last = rows.at(-1), k = Math.sin(Date.now() / 7000 + pair.length) * 0.0012 + Math.sin(Date.now() / 1900) * 0.0006; last[4] = last[1] * (1 + k + 0.002); last[2] = Math.max(last[2], last[4]); last[3] = Math.min(last[3], last[4]); return rows; }
let tid = 100;
const open = [0, 1, 3, 5, 6, 9].map((k, j) => { const sl = sleeves[k], pair = sl.pairs[0], px = series(pair).at(-1)[4], short = j % 3 === 1; const stop = px * (short ? 1.018 : 0.982);
  return {trade_id: tid++, pair, enter_tag: sl.id, is_short: short, open_rate: px * (1 + (r() - 0.5) * 0.01), stop_loss_abs: stop, initial_stop_loss_abs: stop, profit_abs: 0, stake_amount: 2200, leverage: 1, open_date: iso(T0 - r() * 20 * 3600e3)}; });
const closed = Array.from({length: 14}, (_, i) => { const win = r() < 0.45, sl = sleeves[i % 12]; const p = win ? 40 + r() * 70 : -(25 + r() * 12);
  return {trade_id: 50 + i, sleeve_id: sl.id, pair: sl.pairs[0], is_short: r() < 0.4, open_date: iso(T0 - (i + 2) * 7 * 3600e3), close_date: iso(T0 - (i + 1) * 7 * 3600e3), open_rate: 1, close_rate: 1, profit_ratio: p / 2200, profit_abs: p,
    exit_reason: win ? (r() < 0.6 ? "roi" : "trailing_stop_loss") : (r() < 0.8 ? "stop_loss" : "exit_signal")}; });
const events = [["research", "lab: GitHub research run 913 started (4 CPUs, budget 170 min)"], ["lifecycle", "manifest v31: 12 sleeves"], ["research", "lab: experiment x913a started — tsmom on 8 pairs"]].map(([source, message], i) => ({id: i + 1, ts: iso(T0 - (3 - i) * 600e3), source, message}));
const equity = []; { let e = 49400; for (let i = 0; i < 400; i++) { e *= 1 + (r() - 0.47) * 0.0016; equity.push({ts: iso(T0 - (400 - i) * 600e3), equity: e}); } }
const gates = {trades: [64, 40], profit_factor: [1.38, 1.2], sharpe: [1.1, 0.8], max_drawdown: [0.07, 0.2], stress_pf: [1.12, 1.05], wfe: [0.31, 0.4], robustness: [0.75, 0.6], monte_carlo: [0.81, 0.7], deflated_sharpe: [0.62, 0.9]};
const G = Object.fromEntries(Object.entries(gates).map(([k, [v, t]]) => [k, {value: v, threshold: t, pass: k === "max_drawdown" ? v <= t : v >= t}]));
const exps = Array.from({length: 9}, (_, i) => ({id: `x${913 - i}abc`, family: FAM[(i + 2) % FAM.length], status: "done", timeframe: ["1h", "4h", "2h", "6h"][i % 4], pairs: 8, created: iso(T0 - (i + 1) * 3600e3),
  summary: {verdict: ["exploratory", "rejected", "rejected", "exploratory", "rejected", "validated", "rejected", "exploratory", "rejected"][i], dsr: 0.6, n_trials: 412}, variant: `${FAM[(i + 2) % FAM.length]} +HTF-trend(200)`,
  oos: {profit_factor: 0.8 + r() * 0.8, sharpe: r() * 1.6 - 0.2, trades: 60 + Math.floor(r() * 90)}, gates: G, folds: Array.from({length: 4}, () => ({ret: (r() - 0.4) * 0.06, pf: 0.8 + r() * 0.8, trades: 20}))}));
let tick = 0, lossHist = -1.2;
const EMPTY = new URLSearchParams(location.search).get("demo") === "empty";   // a fresh server: bot down, nothing yet
function emptyGet(p) {
  return {"/api/overview": {bot_up: false, balance: null, profit: null, open_trades: [], equity: [], kill_switch: null, entries_paused: false, manifest: {sleeves: []}, closed_count: 0, closed_pnl: 0, events: []},
    "/api/research": {experiments: [], counts: {}, gate_failures: {}, family_stats: {}, paused: false, lab: null, universe: null},
    "/api/health": {heartbeats: [], bot_up: false, selftest: null, exec_test: null, disk: null},
    "/api/goals": {mission: "", goals: [{id: "forward", value: "0 trades", target: "200 trades", progress: 0}, {id: "readiness", value: 0, target: 8, progress: 0}], readiness: {}, drawdown: 0},
    "/api/context": {markets: [], events: []}, "/api/market": {pairs: []}, "/api/learnings": {learnings: []}, "/api/trades": {closed: [], open: []}, "/api/strategies": {strategies: []}, "/api/candles": {candles: []}}[p] || {};
}
export async function demoGet(path) {
  await new Promise(res => setTimeout(res, 60));
  const u = new URL(path, "http://x"), p = u.pathname;
  if (EMPTY) return emptyGet(p);
  if (p === "/api/overview") {
    tick++;
    for (const t of open) { const px = live(t.pair).at(-1)[4]; t.profit_abs = (t.is_short ? t.open_rate - px : px - t.open_rate) / t.open_rate * t.stake_amount; }
    if (tick % 9 === 0) { const t = open.shift(); closed.unshift({...t, sleeve_id: t.enter_tag, close_date: iso(Date.now()), profit_abs: t.profit_abs, exit_reason: t.profit_abs >= 0 ? "roi" : "stop_loss"}); }
    if (tick % 9 === 4) { const sl = sleeves[Math.floor(r() * 12)], pair = sl.pairs[0], px = live(pair).at(-1)[4], short = r() < 0.4; open.push({trade_id: tid++, pair, enter_tag: sl.id, is_short: short, open_rate: px, stop_loss_abs: px * (short ? 1.018 : 0.982), initial_stop_loss_abs: px * (short ? 1.018 : 0.982), profit_abs: 0, stake_amount: 2200, leverage: 1, open_date: iso(Date.now())}); }
    if (tick % 7 === 3) events.push({id: events.length + 1, ts: iso(Date.now()), source: "research", message: `lab: experiment x${900 + tick}b started — ${FAM[tick % 8]} on 8 pairs`});
    const last = equity.at(-1).equity * (1 + (r() - 0.47) * 0.0012); equity.push({ts: iso(Date.now()), equity: last});
    return {bot_up: true, balance: {total_bot: last}, profit: {profit_closed_coin: closed.reduce((a, t) => a + t.profit_abs, 0), closed_trade_count: closed.length}, open_trades: open.map(t => ({...t})), equity: equity.slice(-400),
      kill_switch: null, entries_paused: false, manifest: {sleeves}, closed_count: closed.length, closed_pnl: closed.reduce((a, t) => a + t.profit_abs, 0), events: events.slice(-12).reverse(),
      exposure: {positions: open.length, eff_bets: 2.4, one_side_share: 0.71}, signals: {signals: 47, executed: 31, missed: {pair_busy: 9, same_candle: 4, explore_risk: 3}},
      postmortem: {stop: {n: 9, reversed: 3, confirmed: 5, open: 1, slipped: 1, slip_usd: 14}}};
  }
  if (p === "/api/research") {
    lossHist -= 0.02 + r() * 0.03;
    const ep = Math.min(80, 12 + tick * 3);
    return {experiments: [{id: "x913a", family: "tsmom", status: "running", pairs: 8, progress: {stage: ep < 80 ? "hyperopt fold 2/4" : "oos fold 2/4", epoch: ep, epochs: 80, best_loss: lossHist, best_profit: 0.08 + tick * 0.004, best_trades: 120, remote: true}}, ...exps],
      counts: {done: 1484, failed: 31, running: 1}, gate_failures: {deflated_sharpe: 41, wfe: 22}, family_stats: {tsmom: [212, 0.42], trend_ema: [188, 0.18], macd: [160, 0.21], meanrev_bb: [140, -0.1], donchian: [97, -0.05], supertrend: [120, 0.12]},
      lab: {status: "start", runs: 214, cpus: 4, budget_min: 170, experiments_total: 1484, last_batch: "b20261122-913", run_id: "44991738708", last_import: iso(T0 - 52 * 60e3)}, universe: {pairs: PAIRS}, paused: false};
  }
  if (p === "/api/health") return {bot_up: true, selftest: {ok: true}, exec_test: {ok: true}, disk: {total: 2e9, used: 0.62e9, free: 1.38e9},
    heartbeats: [{service: "manager", status: "ok", age_s: 12, detail: {mem_headroom_mb: 410 + Math.round(Math.sin(Date.now() / 60000) * 30)}}, {service: "research", status: "busy", age_s: 40, detail: {remote: true}}, {service: "supervisor", status: "ok", age_s: 8}, {service: "context", status: "ok", age_s: 300}]};
  if (p === "/api/goals") return {mission: "", drawdown: 0.012, goals: [
    {id: "forward", value: "38 trades", target: "200 trades", progress: 0.19}, {id: "readiness", value: 2, target: 10, progress: 0.2}, {id: "validated", value: 1, target: 1, progress: 1},
    {id: "evidence", value: closed.length, target: 100, progress: closed.length / 100}, {id: "research", value: 74, target: 60, progress: 1}, {id: "pf", value: 1.12, target: 1.3, progress: 0.4},
    {id: "production", value: 0, target: 3, progress: 0}, {id: "return", value: 0.84, target: 10, unit: "%", progress: 0.084}],
    readiness: {passed: 2, total: 10, checks: ["forward_days", "trades", "diversified", "t_stat", "t_daily", "alpha", "profit_factor", "drawdown", "stability", "divergence"].map((id, i) => ({id, title: id, value: [6.5, 14, "1 (corr –)", 0.8, 0.6, 0.0004, 1.12, 0.03, "1/3", "ok"][i], need: ["≥ 90 days", "≥ 250", "≥ 2", "≥ 2.5", "≥ 2.5", "t ≥ 2", "≥ 1.3", "≤ 10%", "≥ 2/3", "—"][i], pass: i === 7 || i === 9}))}};
  if (p === "/api/context") { const d = new Date(); return {markets: [], fear_greed: {value: 38, label: "Fear", week_ago: 45}, dvol: {value: 47.3, pct30: 62}, long_short: {BTC: 57.4, ETH: 61.2, SOL: 64.8},
    events: [{kind: "FOMC", name: "Решение ФРС по ставке", ts: new Date(d.getTime() + 3.2 * 86400e3).toISOString()}, {kind: "CPI", name: "Инфляция США (CPI)", ts: new Date(d.getTime() + 9.4 * 86400e3).toISOString()}]}; }
  if (p === "/api/market") return {pairs: PAIRS.map(pair => ({pair, data: {trend_score: r(), revert_score: r(), ret_30d: (r() - 0.5) * 0.3}}))};
  if (p === "/api/learnings") return {learnings: []};
  if (p === "/api/trades") return {closed: closed.slice(0, 40), open};
  if (p === "/api/strategies") return {strategies: [...sleeves.map((sl, i) => ({id: sl.id, family: sl.family, stage: sl.stage, live: {trades: 3 + i, profit_factor: 0.8 + (i % 5) * 0.15, pnl: (i % 3 - 1) * 30}})),
    ...Array.from({length: 40}, (_, i) => ({id: "old" + i, stage: i % 3 ? "rejected" : "retired"}))]};
  if (p === "/api/candles") { const pair = u.searchParams.get("pair"); return {pair, candles: live(pair).map(x => [...x])}; }
  return {};
}
