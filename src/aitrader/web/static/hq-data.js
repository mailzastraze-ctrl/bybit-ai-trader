// AI Trader HQ — data layer. Polls the company's own API (only while the office is visible),
// keeps one shared store S and tells listeners what changed. Demo data is used only when the
// API does not exist at all (a static preview), never to cover a failing server.

export const S = {
  ov: null, rs: null, hl: null, goals: null, ctx: null, market: null, ln: null, trades: null, strats: null,
  candles: {}, memHist: [], lossHist: {}, demo: false, error: null, updated: 0, eventsSeen: 0,
};
const listeners = new Set();
export const onData = fn => listeners.add(fn);
const emit = (type, payload) => { for (const fn of listeners) { try { fn(type, payload); } catch (e) { console.error(e); } } };

// ------------------------------------------------------------------ formatting (Russian)
const nf = d => new Intl.NumberFormat("ru-RU", {minimumFractionDigits: d, maximumFractionDigits: d});
const NF = [nf(0), nf(1), nf(2), nf(3), nf(4), nf(5)];
const bad = v => v === null || v === undefined || Number.isNaN(Number(v));
export const fmt = {
  n: (v, d = 0) => bad(v) ? "—" : NF[Math.min(5, d)].format(Number(v)),
  signed: (v, d = 2) => bad(v) ? "—" : (Number(v) > 0 ? "+" : Number(v) < 0 ? "−" : "") + NF[d].format(Math.abs(Number(v))),
  pct: (v, d = 1) => bad(v) ? "—" : NF[d].format(Number(v) * 100) + "%",
  spct: (v, d = 1) => bad(v) ? "—" : (Number(v) > 0 ? "+" : Number(v) < 0 ? "−" : "") + NF[d].format(Math.abs(Number(v) * 100)) + "%",
  price: v => bad(v) ? "—" : NF[Math.abs(v) < 1 ? 5 : Math.abs(v) < 20 ? 4 : Math.abs(v) < 1000 ? 2 : 1].format(Number(v)),
  time: d => (d instanceof Date ? d : new Date(d)).toLocaleTimeString("ru-RU", {hour: "2-digit", minute: "2-digit"}),
  ago: iso => { const s = (Date.now() - new Date(iso).getTime()) / 1000; if (!isFinite(s)) return "—"; if (s < 90) return "только что"; if (s < 3600) return `${Math.round(s / 60)} мин назад`; if (s < 86400 * 2) return `${Math.round(s / 3600)} ч назад`; return `${Math.round(s / 86400)} дн назад`; },
  until: iso => { const s = (new Date(iso).getTime() - Date.now()) / 1000; if (!isFinite(s)) return "—"; if (s < 0) return "сейчас"; const d = Math.floor(s / 86400), h = Math.floor((s % 86400) / 3600), m = Math.floor((s % 3600) / 60); return d ? `${d} д ${h} ч` : h ? `${h} ч ${m} мин` : `${m} мин`; },
};
export const coin = pair => String(pair || "").split("/")[0];
export const esc = s => String(s ?? "").replace(/[&<>"]/g, c => ({"&": "&amp;", "<": "&lt;", ">": "&gt;", "\"": "&quot;"}[c]));
export const STAGE_RU = {exploration: "разведка", exploratory: "разведка", incubation: "инкубация", production: "боевая", validated: "валидирована", eligible: "к повышению", retired: "снята", rejected: "отклонена", closing: "закрывается"};
export const VERDICT_RU = {validated: "валидирована", exploratory: "разведка", rejected: "отклонена"};

// ------------------------------------------------------------------ derived views
export const D = {
  sleeves: () => (S.ov?.manifest?.sleeves || []).filter(s => s.stage !== "closing"),
  open: () => S.ov?.open_trades || [],
  equity: () => (S.ov?.equity || []).map(r => Number(r.equity)).filter(v => v > 0),
  capital: () => { const b = S.ov?.balance; const v = b?.total_bot ?? b?.total; return v ?? D.equity().at(-1) ?? null; },
  unrealised: () => D.open().reduce((a, t) => a + Number(t.profit_abs || 0), 0),
  running: () => (S.rs?.experiments || []).find(e => e.status === "running"),
  lastDone: () => (S.rs?.experiments || []).find(e => e.oos || e.gates),
  lastGated: () => (S.rs?.experiments || []).find(e => e.gates && Object.keys(e.gates).length),
  labActive: () => { const l = S.rs?.lab || {}; return !!D.running() || l.status === "start" || l.status === "scan"; },
  goal: id => (S.goals?.goals || []).find(g => g.id === id) || {},
  readiness: () => S.goals?.readiness || {},
  closed: () => S.trades?.closed || [],
  strategy: id => (S.strats?.strategies || []).find(s => s.id === id),
  stageCounts: () => { const c = {}; for (const s of S.strats?.strategies || []) c[s.stage] = (c[s.stage] || 0) + 1; return c; },
  candles: pair => S.candles[pair]?.rows || null,
  lastPrice: pair => { const r = D.candles(pair); return r?.length ? Number(r.at(-1)[4]) : null; },
  mem: () => (S.hl?.heartbeats || []).find(h => h.service === "manager")?.detail?.mem_headroom_mb,
  // exchanges open now: from the server's context, else computed in the browser
  markets: () => S.ctx?.markets?.length ? S.ctx.markets : localMarkets(),
  nextEvent: () => (S.ctx?.events || []).find(e => new Date(e.ts).getTime() > Date.now() - 3 * 3600e3),
};
const MARKETS = [["Токио", "Asia/Tokyo", 9, 0, 15, 30], ["Гонконг", "Asia/Hong_Kong", 9, 30, 16, 0], ["Франкфурт", "Europe/Berlin", 9, 0, 17, 30], ["Лондон", "Europe/London", 8, 0, 16, 30], ["Нью-Йорк", "America/New_York", 9, 30, 16, 0]];
function localMarkets() {
  const now = new Date();
  return MARKETS.map(([name, tz, oh, om, ch, cm]) => {
    const parts = Object.fromEntries(new Intl.DateTimeFormat("en-GB", {timeZone: tz, hour: "2-digit", minute: "2-digit", weekday: "short", hour12: false}).formatToParts(now).map(p => [p.type, p.value]));
    const mins = Number(parts.hour) * 60 + Number(parts.minute), wk = !["Sat", "Sun"].includes(parts.weekday);
    return {name, local: `${parts.hour}:${parts.minute}`, open: wk && mins >= oh * 60 + om && mins < ch * 60 + cm};
  });
}

// News headlines for the analysts' screens — every line is built from real data.
export function headlines() {
  const H = [], c = S.ctx || {}, fg = c.fear_greed, dv = c.dvol, ls = c.long_short || {};
  const ev = (c.events || []).filter(e => new Date(e.ts).getTime() > Date.now() - 3 * 3600e3).slice(0, 2);
  for (const e of ev) H.push({tag: "Макро", text: `${e.name}: ${new Date(e.ts).getTime() < Date.now() ? "данные вышли" : "через " + fmt.until(e.ts)}`});
  if (fg) H.push({tag: "Настроения", text: `Индекс страха и жадности: ${fg.value} — ${FG_RU[fg.label] || fg.label || ""}${fg.week_ago != null ? `, неделю назад ${fg.week_ago}` : ""}`});
  const btc = D.candles("BTC/USDT:USDT");
  if (btc?.length > 24) { const ch = btc.at(-1)[4] / btc.at(-25)[4] - 1; H.push({tag: "Крипто", text: `Биткоин ${ch >= 0 ? "растёт" : "снижается"}: ${fmt.spct(ch)} за сутки, ${fmt.n(btc.at(-1)[4], 0)} $`}); }
  if (dv) H.push({tag: "Волатильность", text: `Опционный индекс DVOL по BTC: ${fmt.n(dv.value, 1)} (${dv.pct30}-й перцентиль за 30 дней)`});
  if (ls.BTC) H.push({tag: "Bybit", text: `Толпа на Bybit: ${fmt.n(ls.BTC, 0)}% счетов в лонге по BTC${ls.ETH ? `, ${fmt.n(ls.ETH, 0)}% по ETH` : ""}`});
  const open = D.markets().filter(m => m.open).map(m => m.name);
  H.push({tag: "Биржи", text: open.length ? `Сейчас открыты: ${open.join(", ")}` : "Фондовые биржи закрыты — торгует только крипторынок"});
  for (const d of (c.delistings || []).slice(0, 1)) H.push({tag: "Bybit", text: `Делистинг: ${coin(d.pair)} — новые входы запрещены`});
  const cap = D.capital(); if (cap) H.push({tag: "Компания", text: `Капитал демо-счёта ${fmt.n(cap, 0)} USDT, открыто позиций: ${D.open().length}`});
  const run = D.running(); if (run) H.push({tag: "Лаборатория", text: `Идёт эксперимент ${run.family}: ${run.progress?.stage || "работа"}`});
  return H;
}
const FG_RU = {"Extreme Fear": "сильный страх", Fear: "страх", Neutral: "нейтрально", Greed: "жадность", "Extreme Greed": "сильная жадность"};
export const fgRu = l => FG_RU[l] || l || "";

// ------------------------------------------------------------------ fetching
let getter = null;
async function realGet(path) {
  const r = await fetch(path, {credentials: "same-origin", headers: {Accept: "application/json"}});
  if (!r.ok) { const e = new Error(`${path} → HTTP ${r.status}`); e.status = r.status; throw e; }
  const ct = r.headers.get("content-type") || "";
  if (!ct.includes("json")) { const e = new Error(`${path}: not JSON`); e.status = 404; throw e; }
  return r.json();
}
async function useDemo() {
  const m = await import("./hq-demo.js");
  getter = m.demoGet; S.demo = true;
}
const wantPairs = new Set();
export const wantCandles = pair => { if (pair) wantPairs.add(pair); };

const tiers = {
  fast: {every: 20e3, last: 0, run: async () => {
    const [ov, rs, hl] = await Promise.all([getter("/api/overview"), getter("/api/research?limit=14"), getter("/api/health")]);
    const prevOpen = new Map((S.ov?.open_trades || []).map(t => [t.trade_id, t]));
    const first = !S.ov;
    Object.assign(S, {ov, rs, hl});
    const mem = D.mem(); if (mem) { S.memHist.push(mem); if (S.memHist.length > 90) S.memHist.shift(); }
    const run = D.running(); if (run?.progress?.best_loss !== undefined) { const h = S.lossHist[run.id] ||= []; if (h.at(-1) !== run.progress.best_loss) h.push(run.progress.best_loss); }
    // events and trades → reactions in the office (history is skipped on the first load)
    const evs = (ov.events || []).slice().sort((a, b) => a.id - b.id);
    if (first) S.eventsSeen = evs.at(-1)?.id || 0;
    else { const fresh = evs.filter(e => e.id > S.eventsSeen); if (fresh.length) { S.eventsSeen = fresh.at(-1).id; emit("events", fresh); } }
    if (!first) {
      const now = new Set(ov.open_trades.map(t => t.trade_id));
      for (const t of ov.open_trades) if (!prevOpen.has(t.trade_id)) emit("opened", t);
      for (const [id, t] of prevOpen) if (!now.has(id)) emit("closed", t);
    }
    emit("fast");
  }},
  slow: {every: 60e3, last: 0, run: async () => {
    const settled = await Promise.allSettled([getter("/api/goals"), getter("/api/context"), getter("/api/market"), getter("/api/learnings"), getter("/api/trades?limit=40")]);
    const [goals, ctx, market, ln, trades] = settled.map(r => r.status === "fulfilled" ? r.value : undefined);
    if (goals) S.goals = goals; if (ctx) S.ctx = ctx; if (market) S.market = market; if (ln) S.ln = ln; if (trades) S.trades = trades;
    emit("slow");
  }},
  rare: {every: 300e3, last: 0, run: async () => { try { S.strats = await getter("/api/strategies"); emit("strats"); } catch (e) { /* optional */ } }},
  candles: {every: 90e3, last: 0, run: async () => {
    for (const p of D.sleeves().flatMap(s => s.pairs.slice(0, 1))) wantPairs.add(p);
    for (const t of D.open()) wantPairs.add(t.pair);
    wantPairs.add("BTC/USDT:USDT");
    const list = [...wantPairs].slice(0, 10);
    for (const p of list) { try { const d = await getter("/api/candles?limit=72&pair=" + encodeURIComponent(p)); if (d.candles?.length) S.candles[p] = {ts: Date.now(), rows: d.candles}; } catch (e) { /* keep last */ } }
    emit("candles");
  }},
};

let active = true, timer = null, started = false;
export function setActive(on) {
  active = on;
  if (on) tick(); else clearTimeout(timer);
}
async function tick() {
  clearTimeout(timer);
  if (!active || document.hidden || !getter || !started) return;
  const now = Date.now();
  for (const t of Object.values(tiers)) {
    if (now - t.last < t.every) continue;
    t.last = now;
    try { await t.run(); S.error = null; S.updated = Date.now(); }
    catch (e) { S.error = e.message; emit("error", e); }
  }
  timer = setTimeout(tick, 2000);
}
document.addEventListener("visibilitychange", () => { if (!document.hidden) tick(); });

export async function start() {
  const params = new URLSearchParams(location.search);
  if (params.has("demo") || window.HQ_DEMO) await useDemo();
  else {
    getter = realGet;
    try { await tiers.fast.run(); tiers.fast.last = Date.now(); }
    catch (e) {
      // no API here at all (static preview / file) → clearly labelled demo data; a real server error stays an error
      if (e instanceof TypeError || e.status === 404) await useDemo();
      else { S.error = e.message; emit("error", e); }
    }
  }
  for (const t of Object.values(tiers)) if (!t.last) { t.last = Date.now(); try { await t.run(); } catch (e) { S.error = e.message; } }
  S.updated = Date.now(); started = true;
  emit("ready");
  timer = setTimeout(tick, 2000);
}
