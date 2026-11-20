"use strict";
// Control room: the company at a glance, from real data only (no placeholders, no fake numbers).
const $ = (s) => document.querySelector(s);
const esc = (v) => String(v ?? "").replace(/[&<>"']/g, (c) => ({"&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;"}[c]));
const api = async (p) => { const r = await fetch(p, {cache: "no-store"}); if (!r.ok) throw new Error(`${p} → ${r.status}`); return r.json(); };
const S = {eqHours: 168};
const FAM = {trend_ema: "Trend EMA", meanrev_bb: "Mean reversion BB", donchian_breakout: "Donchian breakout",
  squeeze_momentum: "Squeeze momentum", tsmom: "Time-series momentum", funding_reversal: "Funding reversal",
  zscore_revert: "Z-score reversion", ema_cross: "EMA cross", bb_revert: "Bollinger reversion", turtle: "Turtle breakout", supertrend: "SuperTrend", macd_cross: "MACD cross", adx_di: "ADX + DI",
  hull_turn: "Hull MA turn", rsi_revert: "RSI reversion", stoch_cross: "Stochastic"};
const famName = (f) => FAM[f] || f || "—";
const pair = (p) => String(p || "").replace("/USDT:USDT", "");
const usd = (v, d = 2) => (v == null || isNaN(v)) ? "—" : (v < 0 ? "−$" : "$") + Math.abs(v).toLocaleString("en-US", {minimumFractionDigits: d, maximumFractionDigits: d});
const sgnUsd = (v) => (v > 0 ? "+" : "") + usd(v);
const pct = (v, d = 2) => (v == null || isNaN(v)) ? "—" : (v > 0 ? "+" : v < 0 ? "−" : "") + Math.abs(v * 100).toFixed(d) + "%";
const cls = (v) => v > 0 ? "pos" : v < 0 ? "neg" : "";
const ago = (ts) => {
  if (!ts) return "—"; const s = (Date.now() - new Date(ts).getTime()) / 1000;
  if (s < 60) return `${Math.max(0, Math.round(s))}s ago`; if (s < 3600) return `${Math.round(s / 60)} min ago`;
  if (s < 86400) return `${(s / 3600).toFixed(1)} h ago`; return `${(s / 86400).toFixed(1)} d ago`;
};
const dur = (ts) => { if (!ts) return "—"; const m = (Date.now() - new Date(ts).getTime()) / 60000; return m < 60 ? `${Math.round(m)}m` : m < 1440 ? `${Math.floor(m / 60)}h ${Math.round(m % 60)}m` : `${(m / 1440).toFixed(1)}d`; };
const tip = $("#tip");
function showTip(e, html) { tip.innerHTML = html; tip.style.display = "block"; const x = Math.min(e.clientX + 14, innerWidth - tip.offsetWidth - 8); tip.style.left = x + "px"; tip.style.top = (e.clientY + 14) + "px"; }
const hideTip = () => { tip.style.display = "none"; };
function chip(id, state, text) { const c = $(id); c.className = "chip " + (state || ""); c.querySelector("span").textContent = text; }
const pill = (t, k = "") => `<span class="pill ${k}">${esc(t)}</span>`;
const stagePill = (st) => pill(st, {production: "good", eligible: "good", incubation: "blue", exploration: "warn", exploratory: "warn", validated: "blue", closing: "", rejected: "crit", retired: ""}[st] || "");

// ---------------------------------------------------------------------------- header + KPIs
function renderHeader() {
  const ov = S.ov || {}, rs = S.rs || {}, lab = rs.lab || {};
  chip("#chBot", ov.bot_up ? "good live" : "crit", ov.bot_up ? "Bot trading · Bybit Demo" : "Bot offline");
  const labOn = lab.status && lab.status !== "end" && Date.now() - new Date(lab.ts || 0).getTime() < 4 * 3600e3;
  const running = (rs.experiments || []).filter((e) => e.status === "running" && e.progress?.stage !== "evaluated").length;
  chip("#chLab", labOn ? "good live" : rs.paused ? "warn" : "", labOn ? `Lab running · ${running} experiments` : rs.paused ? "Lab paused" : "Lab between runs");
  const ks = ov.kill_switch, paused = ov.entries_paused;
  chip("#chRisk", ks ? "crit" : paused ? "warn" : "good", ks ? "Kill switch active" : paused ? "Entries paused" : "Risk limits OK");
  $("#chUpd span").textContent = "updated " + new Date().toLocaleTimeString([], {hour: "2-digit", minute: "2-digit", second: "2-digit"});
}
function kpi(label, value, sub, k = "") { return `<div class="kpi"><div class="l">${esc(label)}</div><div class="v num ${k}">${value}</div><div class="s">${sub}</div></div>`; }
function renderKpis() {
  const ov = S.ov || {}, eq = (ov.equity || []).filter((r) => r.equity > 0), G = S.goals || {};
  const now = eq.at(-1)?.equity, dayAgo = eq.find((r) => new Date(r.ts).getTime() >= Date.now() - 864e5)?.equity;
  const ch = now && dayAgo ? now / dayAgo - 1 : null;
  const open = ov.open_trades || [], upnl = open.reduce((a, t) => a + (+t.profit_abs || 0), 0);
  const tr = S.trades?.closed || [], real = (S.goals?.goals || []).find((g) => g.id === "evidence");
  const rd = S.ready || {}, fw = S.fw || {}, rsg = (G.goals || []).find((g) => g.id === "research");
  const fwTop = fw.top || {};
  const fwLabel = {works: "Works", not_working: "Not working", inconclusive: "Unclear", early_positive: "Leaning +", early_negative: "Leaning −", too_early: "Collecting"}[fw.verdict] || "Collecting";
  $("#kpis").innerHTML = [
    kpi("Trading capital (USDT)", usd(now, 0), ch == null ? "collecting snapshots" : `<span class="${cls(ch)}">${pct(ch)}</span> in 24h`),
    kpi("Open positions", `${open.length}`, open.length ? `unrealized <span class="${cls(upnl)}">${sgnUsd(upnl)}</span>` : "no open risk"),
    kpi("Closed P&L (demo)", `<span class="${cls(ov.closed_pnl)}">${sgnUsd(ov.closed_pnl)}</span>`, `${ov.closed_count ?? tr.length} trades · ${real ? real.value + "/" + real.target + " evidence" : ""}`),
    kpi("Forward test", fwLabel, `${fwTop.trades || 0} unseen-data trades · ${fw.book_size ?? 0} strategies`, {works: "pos", not_working: "neg"}[fw.verdict] || ""),
    kpi("Research · 7 days", `${rsg?.value ?? 0}`, `walk-forward experiments (target ${rsg?.target ?? "—"})`),
    kpi("Real-money readiness", `${rd.passed ?? 0}/${rd.total ?? 8}`, rd.ready ? "all checks passed" : "checks passed · advisory only"),
  ].join("");
  $("#mission").textContent = G.mission || "";
  const gs = G.goals || []; $("#goalsDone").textContent = gs.length ? `${gs.filter((g) => g.progress >= 1).length} of ${gs.length} goals reached` : "";
}

// ---------------------------------------------------------------------------- equity chart
function renderEquity() {
  const el = $("#eqChart"), all = (S.ov?.equity || []).filter((r) => r.equity > 0);
  const since = S.eqHours ? Date.now() - S.eqHours * 3600e3 : 0;
  const pts = all.filter((r) => new Date(r.ts).getTime() >= since).map((r) => ({t: new Date(r.ts).getTime(), v: +r.equity}));
  if (pts.length < 2) { el.innerHTML = `<div class="empty">Collecting equity snapshots (every 10 minutes).</div>`; return; }
  const W = el.clientWidth || 700, H = el.clientHeight || 260, L = 64, R = 12, T = 10, B = 26;
  let lo = Math.min(...pts.map((p) => p.v)), hi = Math.max(...pts.map((p) => p.v));
  const pad = Math.max((hi - lo) * 0.15, hi * 0.0005); lo -= pad; hi += pad;
  const t0 = pts[0].t, t1 = pts.at(-1).t;
  const X = (t) => L + (t - t0) / Math.max(t1 - t0, 1) * (W - L - R), Y = (v) => T + (hi - v) / (hi - lo) * (H - T - B);
  const line = pts.map((p, i) => `${i ? "L" : "M"}${X(p.t).toFixed(1)},${Y(p.v).toFixed(1)}`).join("");
  const area = `${line}L${X(t1).toFixed(1)},${H - B}L${X(t0).toFixed(1)},${H - B}Z`;
  const ticks = [0, 1, 2, 3].map((k) => lo + (hi - lo) * (k + 0.5) / 4);
  const fmtT = (t) => { const d = new Date(t); return (t1 - t0 > 2 * 864e5) ? d.toLocaleDateString([], {month: "short", day: "numeric"}) : d.toLocaleTimeString([], {hour: "2-digit", minute: "2-digit"}); };
  const xt = [0, 0.25, 0.5, 0.75, 1].map((f) => t0 + (t1 - t0) * f);
  el.innerHTML = `<svg width="${W}" height="${H}" role="img" aria-label="Trading capital over time">
    <defs><linearGradient id="eqg" x1="0" x2="0" y1="0" y2="1"><stop offset="0" stop-color="#3987e5" stop-opacity=".28"/><stop offset="1" stop-color="#3987e5" stop-opacity="0"/></linearGradient></defs>
    ${ticks.map((v) => `<line x1="${L}" x2="${W - R}" y1="${Y(v)}" y2="${Y(v)}" stroke="#2c2c2a"/><text x="${L - 8}" y="${Y(v) + 4}" text-anchor="end" class="num">${Math.round(v).toLocaleString("en-US")}</text>`).join("")}
    ${xt.map((t, i) => `<text x="${X(t)}" y="${H - 6}" text-anchor="${i === 0 ? "start" : i === 4 ? "end" : "middle"}">${fmtT(t)}</text>`).join("")}
    <path d="${area}" fill="url(#eqg)"/><path d="${line}" fill="none" stroke="#3987e5" stroke-width="2" stroke-linejoin="round"/>
    <line id="eqX" y1="${T}" y2="${H - B}" stroke="#8f8e86" stroke-dasharray="3 3" visibility="hidden"/>
    <circle id="eqDot" r="4.5" fill="#3987e5" stroke="#1a1a19" stroke-width="2" visibility="hidden"/>
    <rect x="${L}" y="${T}" width="${W - L - R}" height="${H - T - B}" fill="transparent" id="eqHit"/></svg>`;
  const hit = el.querySelector("#eqHit"), vx = el.querySelector("#eqX"), dot = el.querySelector("#eqDot");
  hit.addEventListener("mousemove", (e) => {
    const bx = el.querySelector("svg").getBoundingClientRect(), t = t0 + (e.clientX - bx.left - L) / (W - L - R) * (t1 - t0);
    let best = pts[0]; for (const p of pts) if (Math.abs(p.t - t) < Math.abs(best.t - t)) best = p;
    vx.setAttribute("x1", X(best.t)); vx.setAttribute("x2", X(best.t)); vx.setAttribute("visibility", "visible");
    dot.setAttribute("cx", X(best.t)); dot.setAttribute("cy", Y(best.v)); dot.setAttribute("visibility", "visible");
    const d0 = best.v / pts[0].v - 1;
    showTip(e, `<b class="num">${usd(best.v)}</b><br><span class="dim">${new Date(best.t).toLocaleString()}</span><br><span class="${cls(d0)}">${pct(d0)}</span> <span class="dim">vs range start</span>`);
  });
  hit.addEventListener("mouseleave", () => { hideTip(); vx.setAttribute("visibility", "hidden"); dot.setAttribute("visibility", "hidden"); });
}
document.querySelectorAll("#eqRange button").forEach((b) => b.onclick = () => {
  document.querySelectorAll("#eqRange button").forEach((x) => x.classList.toggle("on", x === b)); S.eqHours = +b.dataset.h; renderEquity();
});

// ---------------------------------------------------------------------------- positions
function sleeveOf(tag) { return (S.ov?.manifest?.sleeves || []).find((s) => s.id === tag) || (S.strats?.strategies || []).find((s) => s.id === tag); }
function renderPositions() {
  const open = S.ov?.open_trades || [];
  $("#posSub").textContent = open.length ? `${open.length} open · stops on every position` : "";
  if (!open.length) { $("#positions").innerHTML = `<div class="empty">No open positions. Strategies are waiting for their entry conditions on ${(S.ov?.manifest?.sleeves || []).filter((s) => s.stage !== "closing").length} sleeves.</div>`; return; }
  $("#positions").innerHTML = `<table><thead><tr><th>Pair</th><th>Strategy</th><th class="r">P&L</th><th>Protection</th><th class="r">Age</th></tr></thead><tbody>${open.map((t) => {
    const sl = sleeveOf(t.enter_tag), short = !!t.is_short, entry = +t.open_rate, stop = +t.stop_loss_abs, amt = +t.amount || 0;
    const locked = stop && (short ? stop <= entry : stop >= entry);
    const atStop = stop ? (short ? entry - stop : stop - entry) * amt : null;
    const prot = !stop ? pill("no stop data", "warn") : locked ? pill(`profit locked ${sgnUsd(atStop)}`, "good") : pill(`risk to stop ${usd(Math.abs(atStop))}`, "");
    const pr = +(t.profit_ratio ?? t.profit_pct / 100 ?? 0);
    return `<tr><td><b>${esc(pair(t.pair))}</b> ${pill(short ? "short" : "long", short ? "crit" : "good")}<div class="dim mono">${(+t.leverage || 1).toFixed(0)}× · in ${entry}</div></td>
      <td>${esc(famName(sl?.family))}<div class="dim mono">${esc(t.enter_tag || "")}</div></td>
      <td class="r num"><span class="${cls(t.profit_abs)}">${sgnUsd(+t.profit_abs)}</span><div class="dim">${pct(pr)}</div></td>
      <td>${prot}<div class="dim mono">stop ${stop || "—"}</div></td><td class="r num">${dur(t.open_date)}</td></tr>`;
  }).join("")}</tbody></table>`;
}

// ---------------------------------------------------------------------------- research lab
const STEPS = ["download", "hyperopt fold 1", "oos fold 1", "hyperopt fold 2", "oos fold 2", "hyperopt fold 3", "oos fold 3", "hyperopt fold 4", "oos fold 4", "robustness", "evaluated"];
function stepIndex(stage) { stage = String(stage || ""); const i = STEPS.findIndex((s) => stage.startsWith(s)); return i < 0 ? 0 : i; }
function stageText(p) {
  const st = String(p.stage || "");
  if (st.startsWith("hyperopt")) return `Optimizing on the past (${st.replace("hyperopt ", "")})${p.epoch ? ` · epoch ${p.epoch}/${p.epochs || "?"}` : ""}`;
  if (st.startsWith("oos")) return `Testing on unseen months (${st.replace("oos ", "")})`;
  return {download: "Loading Bybit history", robustness: "Stress & parameter robustness", evaluated: "Done · waiting for batch merge"}[st] || st;
}
function renderLab() {
  const rs = S.rs || {}, lab = rs.lab || {}, exps = rs.experiments || [];
  const run = exps.filter((e) => e.status === "running" && e.progress?.remote && (!lab.run_id || e.progress.run_id == lab.run_id));
  const labOn = lab.status && lab.status !== "end" && Date.now() - new Date(lab.ts || 0).getTime() < 4 * 3600e3;
  const byJob = {}; for (const e of run) { const j = e.progress?.job ?? 0; if (!byJob[j] || e.created > byJob[j].created) byJob[j] = e; }
  const doneRun = run.filter((e) => e.progress?.stage === "evaluated").length;
  $("#labSub").textContent = labOn ? `GitHub run ${lab.run_id || ""} · started ${ago(lab.started)} · ${doneRun} finished this run · budget ${lab.budget_min || "?"} min per runner`
    : `last run ${ago(lab.ts)} · ${lab.runs || 0} runs total · ${lab.experiments_total || 0} experiments imported`;
  const lanes = [0, 1, 2, 3].map((j) => {
    const e = byJob[j];
    if (!e || !labOn) return `<div class="lane idle"><div>Runner ${j + 1}</div><div class="dim">${labOn ? "starting…" : "idle"}</div></div>`;
    const p = e.progress || {}, k = stepIndex(p.stage), info = e.info || {};
    const why = info.revalidates ? `re-checking ${info.revalidates}` : info.refines ? `refining ${info.refines}` : "new search";
    return `<div class="lane"><div class="hd"><span>Runner ${j + 1}</span><span class="mono">${esc(e.id)}</span></div>
      <div class="fam">${esc(famName(e.family))}</div><div class="meta">${e.pairs} pairs · ${esc(why)}</div>
      <div class="steps">${STEPS.map((_, i) => `<i class="${i < k ? "d" : i === k ? "c" : ""}"></i>`).join("")}</div>
      <div class="stage">${esc(stageText(p))}</div>
      ${p.epochs && String(p.stage).startsWith("hyperopt") ? `<div class="bar"><i style="width:${Math.min(100, (p.epoch || 0) / p.epochs * 100)}%"></i></div>` : ""}
      <div class="best">${p.best_trades ? `best so far: ${p.best_trades} trades, ${pct(p.best_profit)} in-sample` : ""}${p.budget_left_min != null ? ` · ${Math.round(p.budget_left_min)} min left` : ""}</div></div>`;
  });
  $("#lanes").innerHTML = lanes.join("");
}
function renderResults() {
  const done = (S.rs?.experiments || []).filter((e) => e.status === "done").slice(0, 14);
  if (!done.length) { $("#results").innerHTML = `<div class="empty">No finished experiments yet.</div>`; return; }
  const vp = (v) => pill(v, {validated: "good", exploratory: "warn", rejected: ""}[v] || "");
  $("#results").innerHTML = `<table><thead><tr><th>Strategy</th><th class="r">Trades</th><th class="r">PF</th><th class="r">Sharpe</th><th class="r">Max DD</th><th class="r" title="R² of the unseen-period equity curve (1 = steady line up) · last 3 months">Steadiness</th><th>Folds</th><th>Verdict</th></tr></thead><tbody>${done.map((e) => {
    const o = e.oos || {}, f = e.folds || [];
    return `<tr><td>${esc(e.variant || famName(e.family))}<div class="dim">${e.pairs} pairs · ${esc(e.timeframe || "1h")} · ${ago(e.finished)}</div></td>
      <td class="r num">${o.trades ?? "—"}</td><td class="r num ${(o.profit_factor || 0) >= 1 ? "pos" : "neg"}">${o.profit_factor ?? "—"}</td>
      <td class="r num">${o.sharpe ?? "—"}</td><td class="r num">${o.max_drawdown != null ? (o.max_drawdown * 100).toFixed(1) + "%" : "—"}</td>
      <td class="r num">${o.curve_r2 != null ? `<span class="${cls(o.curve_r2)}">${o.curve_r2.toFixed(2)}</span><div class="dim">3m ${pct(o.last90_return, 1)}</div>` : "—"}</td>
      <td title="each square = one 90-day test window">${f.map((x) => `<span class="fold ${x.ret > 0 ? "p" : x.ret < 0 ? "n" : ""}" title="${esc(x.test)}: ${pct(x.ret)}, ${x.trades ?? 0} trades"></span>`).join("")}</td>
      <td>${vp(e.summary?.verdict || "—")}</td></tr>`;
  }).join("")}</tbody></table>`;
}
function renderFamilies() {
  const fs = S.rs?.family_stats || {}, rows = Object.entries(fs);
  const m = Math.max(0.05, ...rows.map(([, v]) => Math.abs(v[1])));
  $("#families").innerHTML = rows.sort((a, b) => b[1][1] - a[1][1]).map(([f, [n, mean]]) => {
    const w = Math.abs(mean) / m * 50, left = mean >= 0 ? 50 : 50 - w;
    return `<div class="famrow"><span class="nm">${esc(famName(f))}</span><div class="dv" title="mean reward ${mean.toFixed(3)}"><i style="left:${left}%;width:${w}%;background:${mean >= 0 ? "var(--blue)" : "var(--crit)"}"></i></div><span class="val num">${mean.toFixed(2)} · ${n}</span></div>`;
  }).join("") || `<div class="empty">No completed experiments yet.</div>`;
  const gf = Object.entries(S.rs?.gate_failures || {}).sort((a, b) => b[1] - a[1]).slice(0, 5), gm = Math.max(1, ...gf.map((x) => x[1]));
  const GN = {deflated_sharpe: "Deflated Sharpe (luck filter)", fold_consistency: "Profitable in most windows", trades: "Enough trades", profit_factor: "Profit factor", sharpe: "Sharpe", max_drawdown: "Drawdown", stress_pf: "Survives double costs", wfe: "Walk-forward efficiency", robustness: "Robust to parameter changes", monte_carlo: "Monte Carlo"};
  $("#gates").innerHTML = gf.map(([g, n]) => `<div class="famrow"><span class="nm">${esc(GN[g] || g)}</span><div class="bar"><i style="width:${n / gm * 100}%;background:#c3c2b7"></i></div><span class="val num">${n}</span></div>`).join("") || `<div class="empty">—</div>`;
}

// ---------------------------------------------------------------------------- lifecycle / sleeves
function renderLifecycle() {
  const st = S.strats?.strategies || [], c = (s) => st.filter((x) => x.stage === s).length;
  const steps = [["exploratory", "Candidates", "promising, not proven"], ["validated", "Validated", "passed every gate"], ["incubation", "Incubation", "small demo capital"], ["eligible", "Eligible", "live-proven"], ["production", "Production", "full allocation"]];
  $("#funnel").innerHTML = steps.map(([k, l, d]) => `<div class="fstep ${c(k) ? "hot" : ""}"><b class="num">${c(k)}</b>${esc(l)}<br><span>${esc(d)}</span></div>`).join("")
    + `<div class="fstep" style="flex:.7"><b class="num dim">${c("rejected") + c("retired")}</b>Rejected<br><span>retired / failed</span></div>`;
  const sl = (S.ov?.manifest?.sleeves || []).filter((s) => s.stage !== "closing");
  const byId = Object.fromEntries(st.map((x) => [x.id, x]));
  $("#slvSub").textContent = `${sl.length} sleeves · ${new Set(sl.flatMap((s) => s.pairs)).size} pairs watched`;
  $("#sleeves").innerHTML = sl.length ? `<table><thead><tr><th>Sleeve</th><th>Stage</th><th>Pairs</th><th class="r">Risk/trade</th><th class="r">Live trades</th><th class="r">Live P&L</th></tr></thead><tbody>${sl.map((s) => {
    const lv = byId[s.id]?.live || {};
    return `<tr><td>${esc(byId[s.id]?.oos?.variant || famName(s.family))}<div class="dim mono">${esc(s.id)}</div></td><td>${stagePill(s.stage)}</td>
      <td class="dim">${s.pairs.slice(0, 6).map(pair).join(", ")}${s.pairs.length > 6 ? ` +${s.pairs.length - 6}` : ""}</td>
      <td class="r num">${(s.risk * 100).toFixed(2)}%</td><td class="r num">${lv.trades ?? 0}</td><td class="r num ${cls(lv.pnl)}">${lv.pnl != null ? sgnUsd(lv.pnl) : "—"}</td></tr>`;
  }).join("")}</tbody></table>` : `<div class="empty">No sleeves deployed.</div>`;
}

// ---------------------------------------------------------------------------- goals / readiness / forward
function renderGoals() {
  const gs = S.goals?.goals || [];
  $("#goals").innerHTML = gs.map((g) => `<div class="goal"><span class="t">${esc(g.title)}</span><b class="num">${esc(g.value)}${g.unit === "%" ? "%" : ""}<span class="dim"> / ${esc(g.target)}${g.unit === "%" ? "%" : ""}</span></b>
    <div class="bar"><i style="width:${Math.round(Math.max(0, Math.min(1, g.progress)) * 100)}%;background:${g.progress >= 1 ? "var(--good)" : g.warning ? "var(--crit)" : "var(--blue)"}"></i></div>${g.note ? `<span class="n">${esc(g.note)}</span>` : ""}</div>`).join("");
}
function renderReadiness() {
  const r = S.ready || {};
  $("#rdSub").textContent = `${r.passed ?? 0}/${r.total ?? 8} · advisory`;
  $("#readiness").innerHTML = (r.checks || []).map((c) => `<div class="check"><span class="ic ${c.pass ? "ok" : "no"}">${c.pass ? "✓" : "·"}</span><span>${esc(c.title)}<div class="need">need ${esc(c.need)}</div></span><b class="num">${esc(c.value)}</b></div>`).join("")
    + `<p class="dim" style="margin:8px 0 0;font-size:11.5px">${esc(r.note || "")}</p>`;
}
function renderForward() {
  const f = S.fw || {}, t = f.top || {}, rest = f.rest || {}, p = f.persistence || {};
  const v = {works: ["Works", "good"], not_working: ["Not working", "crit"], inconclusive: ["Inconclusive", "warn"], early_positive: ["Early read: leaning positive", "blue"], early_negative: ["Early read: leaning negative", "warn"], too_early: ["Collecting evidence", ""]}[f.verdict] || ["Collecting evidence", ""];
  const row = (l, g) => `<tr><td>${l}</td><td class="r num">${g.strategies ?? 0}</td><td class="r num">${g.trades ?? 0}</td><td class="r num ${cls(g.pnl_pct)}">${g.pnl_pct != null ? (g.pnl_pct > 0 ? "+" : "") + g.pnl_pct.toFixed(2) + "%" : "—"}</td><td class="r num">${g.pf ?? "—"}</td><td class="r num">${g.t_daily ?? "—"}</td></tr>`;
  const pers = p.experiments ? `History check (${p.experiments} experiments): when the first half of the unseen test period was profitable, the second half was profitable <b>${p.p_second_pos_if_first_pos != null ? Math.round(p.p_second_pos_if_first_pos * 100) + "%" : "—"}</b> of the time (vs ${p.p_second_pos_if_first_neg != null ? Math.round(p.p_second_pos_if_first_neg * 100) + "%" : "—"} after a losing first half).` : "";
  $("#forward").innerHTML = `<div style="display:flex;gap:14px;align-items:center;margin-bottom:10px">${pill(v[0], v[1])}<span>${esc(f.text || "")}</span></div>
    <table><thead><tr><th>Group (ranked by backtest score at freeze)</th><th class="r">Strategies</th><th class="r">Forward trades</th><th class="r">Return</th><th class="r">PF</th><th class="r">Daily t</th></tr></thead>
    <tbody>${row("Top quartile — the ones research likes most", t)}${row("Everything else (control group)", rest)}</tbody></table>
    <p class="dim" style="margin:10px 0 0;font-size:12px">${f.book_size ?? 0} frozen strategies are re-tested every lab run on Bybit candles after their freeze time only, with fees and slippage.
    Decision rule fixed in advance: works = top quartile ≥ ${f.rules?.final_trades ?? 200} trades over ≥ ${f.rules?.final_days ?? 14} days, PF ≥ ${f.rules?.pf_works ?? 1.15}, daily t ≥ ${f.rules?.t_works ?? 2}.
    ${f.rank_corr != null ? `Rank correlation backtest→forward: <b>${f.rank_corr}</b>.` : ""} ${pers}</p>`;
}

function renderScreen() {
  const sc = S.scr || {}, top = sc.top || [];
  const tested = new Map((S.rs?.experiments || []).filter((e) => e.info?.screen).map((e) => [e.info.screen, e]));
  $("#scrSub").textContent = sc.evaluated ? `${(+sc.evaluated).toLocaleString("en-US")} combinations on ${sc.series} coin/timeframe series · ${sc.n_survivors} survivors · ${ago(sc.ts || sc.created)}` : "first screening runs with the next lab run";
  if (!top.length) { $("#screen").innerHTML = `<div class="empty">${sc.evaluated ? "No combination stayed profitable with a steady curve on unseen data this time." : "Waiting for the first screening."}</div>`; return; }
  const ex = (x) => `stop ${x.sl}×ATR · ${x.tp ? "TP " + x.tp + "R" : "no TP"} · ${x.tr ? "trail " + x.tr + "×ATR" : "no trail"}`;
  $("#screen").innerHTML = `<table><thead><tr><th>Strategy</th><th>Coin · TF</th><th class="r">Unseen trades</th><th class="r">PF</th><th class="r">Return</th><th class="r">Max DD</th><th class="r">Curve R²</th><th class="r">Last 3m</th><th>Walk-forward</th></tr></thead><tbody>${top.map((x) => {
    const e = tested.get(x.id), v = e?.summary?.verdict;
    const wf = !e ? pill("queued", "") : e.status === "running" ? pill("testing", "blue") : pill(`${v} · PF ${e.oos?.profit_factor ?? "—"}`, {validated: "good", exploratory: "warn"}[v] || "");
    return `<tr><td>${esc(x.name || famName(x.family))}<div class="dim mono">${esc(JSON.stringify(x.params))} · ${esc(ex(x.exits || {}))}</div></td>
      <td>${esc(pair(x.pair))} · ${esc(x.timeframe)}</td><td class="r num">${x.B?.trades ?? "—"}</td><td class="r num pos">${x.B?.pf ?? "—"}</td>
      <td class="r num ${cls(x.B?.net)}">${x.B?.net != null ? (x.B.net > 0 ? "+" : "") + x.B.net.toFixed(1) + "%" : "—"}</td><td class="r num">${x.B?.dd != null ? x.B.dd.toFixed(1) + "%" : "—"}</td>
      <td class="r num">${x.r2}</td><td class="r num ${cls(x.last90)}">${x.last90 > 0 ? "+" : ""}${x.last90}%</td><td>${wf}</td></tr>`;
  }).join("")}</tbody></table>
  <p class="dim" style="margin:8px 0 0;font-size:12px">Returns here are 1× full-capital backtests in the owner's engine (fees + slippage). Survivors then run through the freqtrade walk-forward (4 unseen 90-day windows, double costs, Deflated Sharpe) and the forward test on live data; passing ones trade on demo at 0.1% risk.</p>`;
}

// ---------------------------------------------------------------------------- log / learnings / closed
function renderLog() {
  const ev = S.ev?.events || S.ov?.events || [];
  $("#log").innerHTML = ev.slice(0, 60).map((e) => `<div class="${esc(e.level)}"><time class="num">${esc((e.ts || "").slice(11, 16))}</time><span class="src">${esc(e.source)}</span><span class="msg">${esc(e.message)}</span></div>`).join("") || `<div class="empty">quiet</div>`;
  const ln = (S.ln?.learnings || []).filter((l) => l.active).slice(0, 25);
  $("#learn").innerHTML = ln.map((l) => `<div><time class="num">${esc((l.ts || "").slice(5, 10))}</time><span class="src">${esc(l.scope)}</span><span class="msg">${esc(l.insight)}</span></div>`).join("") || `<div class="empty">Nothing learned yet — learnings come from finished experiments and closed trades.</div>`;
}
function renderClosed() {
  const tr = S.trades?.closed || [];
  const tot = tr.reduce((a, t) => a + (+t.profit_abs || 0), 0), wins = tr.filter((t) => +t.profit_abs > 0).length;
  $("#closedSub").textContent = tr.length ? `${tr.length} trades · ${Math.round(wins / tr.length * 100)}% winners · ${sgnUsd(tot)} demo P&L (before slippage haircut)` : "";
  $("#closed").innerHTML = tr.length ? `<table><thead><tr><th>Closed</th><th>Pair</th><th>Strategy</th><th class="r">Entry → exit</th><th>Exit reason</th><th class="r">P&L</th><th class="r">Return</th></tr></thead><tbody>${tr.slice(0, 40).map((t) => {
    const sl = sleeveOf(t.sleeve_id);
    return `<tr><td class="num">${esc((t.close_date || "").slice(5, 16).replace("T", " "))}</td><td><b>${esc(pair(t.pair))}</b> ${pill(t.is_short ? "short" : "long", t.is_short ? "crit" : "good")}</td>
      <td>${esc(famName(sl?.family))}<div class="dim mono">${esc(t.sleeve_id)}</div></td><td class="r num">${t.open_rate} → ${t.close_rate}</td><td>${esc(t.exit_reason)}</td>
      <td class="r num ${cls(t.profit_abs)}">${sgnUsd(+t.profit_abs)}</td><td class="r num ${cls(t.profit_ratio)}">${pct(+t.profit_ratio)}</td></tr>`;
  }).join("")}</tbody></table>` : `<div class="empty">No closed trades yet.</div>`;
}

// ---------------------------------------------------------------------------- polling
function safe(fn) { try { fn(); } catch (e) { console.warn(fn.name, e); } }
function renderAll() { [renderHeader, renderKpis, renderEquity, renderPositions, renderLab, renderResults, renderFamilies, renderLifecycle, renderGoals, renderReadiness, renderForward, renderScreen, renderLog, renderClosed].forEach(safe); }
async function fast() {
  try { const [ov, rs] = await Promise.all([api("/api/overview"), api("/api/research")]); Object.assign(S, {ov, rs}); renderAll(); }
  catch (e) { chip("#chUpd", "crit", "data error: " + e.message); }
}
let lastSlow = 0;
async function slow() {
  if (Date.now() - lastSlow < 55000) return; lastSlow = Date.now();
  const get = (p) => api(p).catch(() => null);
  const [goals, ready, strats, trades, ln, fw, ev, scr] = await Promise.all([get("/api/goals"), get("/api/readiness"), get("/api/strategies"), get("/api/trades?limit=200"), get("/api/learnings"), get("/api/forward"), get("/api/events?limit=60"), get("/api/screen")]);
  Object.assign(S, Object.fromEntries(Object.entries({goals, ready, strats, trades, ln, fw, ev, scr}).filter(([, v]) => v)));
  renderAll();
}
async function tick() { await fast(); await slow(); window.__ready = true; }
tick(); setInterval(tick, 10000);
addEventListener("resize", () => safe(renderEquity));
