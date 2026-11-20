"use strict";
// Пульт управления: вся компания на одном экране, только реальные данные.
const $ = (s) => document.querySelector(s);
const esc = (v) => String(v ?? "").replace(/[&<>"']/g, (c) => ({"&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;"}[c]));
const api = async (p) => { const r = await fetch(p, {cache: "no-store"}); if (!r.ok) throw new Error(`${p} → ${r.status}`); return r.json(); };
const S = {eqHours: 168, filter: "all", tab: "overview"};
const FAM = {trend_ema: "EMA-тренд + откат", meanrev_bb: "Боллинджер (с фильтрами)", donchian_breakout: "Пробой канала",
  squeeze_momentum: "Сжатие → импульс", tsmom: "Импульс за дни", funding_reversal: "Перекос фандинга",
  zscore_revert: "Z-score: возврат", supertrend: "SuperTrend", macd_cross: "MACD", adx_di: "ADX + DI",
  hull_turn: "Разворот Hull MA", rsi_revert: "RSI: возврат", stoch_cross: "Стохастик", ema_cross: "Пересечение EMA",
  bb_revert: "Боллинджер: возврат", turtle: "Черепахи (Дончиан)", rel_strength: "Сила против BTC", oi_flow: "Открытый интерес"};
const famName = (f) => FAM[f] || f || "—";
const pair = (p) => String(p || "").replace("/USDT:USDT", "");
const nf = (v, d = 2) => (+v).toLocaleString("ru-RU", {minimumFractionDigits: d, maximumFractionDigits: d});
const usd = (v, d = 2) => (v == null || isNaN(v)) ? "—" : (v < 0 ? "−" : "") + nf(Math.abs(v), d) + " $";
const sgnUsd = (v) => (v > 0 ? "+" : "") + usd(v);
const pct = (v, d = 2) => (v == null || isNaN(v)) ? "—" : (v > 0 ? "+" : v < 0 ? "−" : "") + nf(Math.abs(v * 100), d) + "%";
const cls = (v) => v > 0 ? "pos" : v < 0 ? "neg" : "";
const ago = (ts) => {
  if (!ts) return "—"; const s = (Date.now() - new Date(ts).getTime()) / 1000;
  if (s < 60) return "только что"; if (s < 3600) return `${Math.round(s / 60)} мин назад`;
  if (s < 86400) return `${nf(s / 3600, 1)} ч назад`; return `${nf(s / 86400, 1)} дн назад`;
};
const dur = (ts) => { if (!ts) return "—"; const m = (Date.now() - new Date(ts).getTime()) / 60000; return m < 60 ? `${Math.round(m)} мин` : m < 1440 ? `${Math.floor(m / 60)} ч ${Math.round(m % 60)} мин` : `${nf(m / 1440, 1)} дн`; };
const tip = $("#tip");
function showTip(e, html) { tip.innerHTML = html; tip.style.display = "block"; const x = Math.min(e.clientX + 14, innerWidth - tip.offsetWidth - 8); tip.style.left = x + "px"; tip.style.top = (e.clientY + 14) + "px"; }
const hideTip = () => { tip.style.display = "none"; };
function chip(id, state, text) { const c = $(id); c.className = "chip " + (state || ""); c.querySelector("span").textContent = text; }
const pill = (t, k = "") => `<span class="pill ${k}">${esc(t)}</span>`;
const STAGE = {production: ["основная", "good"], eligible: ["доказала себя", "good"], incubation: ["испытание", "blue"], exploration: ["разведка", "warn"],
  exploratory: ["кандидат", "warn"], validated: ["прошла проверки", "blue"], closing: ["закрывает", ""], rejected: ["отсеяна", "crit"], retired: ["снята", ""]};
const stagePill = (st) => pill(...(STAGE[st] || [st, ""]));
const labActive = () => { const lab = S.rs?.lab || {}; return lab.status && lab.status !== "end" && Date.now() - new Date(lab.ts || 0).getTime() < 4 * 3600e3; };

// ---------------------------------------------------------------------------- вкладки
function setTab(t) {
  S.tab = t; document.body.className = "t-" + t;
  const fr = $("#officeFrame");  // the 3D office loads only when its tab is opened (GPU/CPU heavy)
  if (t === "office" && !fr.src) fr.src = "/hq";
  document.querySelectorAll("#tabs button").forEach((b) => b.classList.toggle("on", b.dataset.t === t));
  try { history.replaceState(null, "", "#" + t); } catch (e) { /* ignore */ }
  renderAll();
}
document.querySelectorAll("#tabs button").forEach((b) => b.onclick = () => setTab(b.dataset.t));

// ---------------------------------------------------------------------------- шапка + KPI
function renderHeader() {
  const ov = S.ov || {}, rs = S.rs || {};
  chip("#chBot", ov.bot_up ? "good live" : "crit", ov.bot_up ? "Бот торгует · Bybit Demo" : "Бот не отвечает");
  const running = (rs.experiments || []).filter((e) => e.status === "running" && e.progress?.stage !== "evaluated").length;
  chip("#chLab", labActive() ? "good live" : rs.paused ? "warn" : "", labActive() ? `Лаборатория: идёт ${running} опытов` : rs.paused ? "Лаборатория на паузе" : "Лаборатория между прогонами");
  const ks = ov.kill_switch, paused = ov.entries_paused;
  chip("#chRisk", ks ? "crit" : paused ? "warn" : "good", ks ? "Аварийный стоп" : paused ? "Входы на паузе" : "Риск в норме");
  $("#chUpd span").textContent = "обновлено " + new Date().toLocaleTimeString("ru-RU");
}
function kpi(label, value, sub, k = "") { return `<div class="kpi"><div class="l">${esc(label)}</div><div class="v num ${k}">${value}</div><div class="s">${sub}</div></div>`; }
function renderKpis() {
  const ov = S.ov || {}, eq = (ov.equity || []).filter((r) => r.equity > 0), G = S.goals || {};
  const now = eq.at(-1)?.equity, dayAgo = eq.find((r) => new Date(r.ts).getTime() >= Date.now() - 864e5)?.equity;
  const ch = now && dayAgo ? now / dayAgo - 1 : null;
  const open = ov.open_trades || [], upnl = open.reduce((a, t) => a + (+t.profit_abs || 0), 0);
  const fw = S.fw || {}, rd = S.ready || {}, rsg = (G.goals || []).find((g) => g.id === "research");
  const nTrading = (ov.manifest?.sleeves || []).filter((s) => s.stage !== "closing").length;
  const fwLabel = {works: "Работает", not_working: "Не работает", inconclusive: "Неясно", early_positive: "Скорее +", early_negative: "Скорее −", too_early: "Сбор данных"}[fw.verdict] || "Сбор данных";
  $("#kpis").innerHTML = [
    kpi("Торговый капитал", usd(now, 0), ch == null ? "копим снимки" : `<span class="${cls(ch)}">${pct(ch)}</span> за 24ч`),
    kpi("Стратегий торгует", `${nTrading}`, `${open.length} открытых позиций · <span class="${cls(upnl)}">${sgnUsd(upnl)}</span>`),
    kpi("Закрытый P&L (демо)", `<span class="${cls(ov.closed_pnl)}">${sgnUsd(ov.closed_pnl)}</span>`, `${ov.closed_count ?? 0} сделок`),
    kpi("Форвард-тест", fwLabel, `${fw.top?.trades || 0} сделок на новых данных · ${fw.book_size ?? 0} стратегий`, {works: "pos", not_working: "neg"}[fw.verdict] || ""),
    kpi("Исследования · 7 дней", `${rsg?.value ?? 0}`, `строгих проверок (цель ${rsg?.target ?? "—"})`),
    kpi("Готовность к реалу", `${rd.passed ?? 0}/${rd.total ?? 8}`, rd.ready ? "все проверки пройдены" : "проверок пройдено · только совет"),
  ].join("");
  $("#mission").textContent = "Миссия: найти, доказать и масштабировать реальные торговые преимущества на Bybit Demo — без подгонки и без выдуманных результатов.";
  const gs = G.goals || []; $("#goalsDone").textContent = gs.length ? `${gs.filter((g) => g.progress >= 1).length} из ${gs.length} целей достигнуто` : "";
}
function renderPipeline() {
  const sc = S.scr || {}, rs = S.rs || {}, st = S.strats?.strategies || [], fw = S.fw || {};
  const c = (s) => st.filter((x) => x.stage === s).length;
  const steps = [
    ["1", "Скринер", sc.evaluated ? `${nf(sc.evaluated, 0)} вариантов → выжило ${sc.n_survivors}` : "первый запуск с ближайшим прогоном"],
    ["2", "Строгая проверка", `${rs.counts?.done || 0} проверено · ${c("exploratory") + c("validated")} кандидатов`],
    ["3", "Форвард-тест", `${fw.book_size ?? 0} стратегий · ${fw.top?.trades || 0} сделок`],
    ["4", "Демо-торговля", `${(S.ov?.manifest?.sleeves || []).filter((s) => s.stage !== "closing").length} стратегий торгуют`],
    ["5", "Реальный счёт", `${S.ready?.passed ?? 0}/${S.ready?.total ?? 8} проверок · решаете вы`],
  ];
  $("#pipeline").innerHTML = steps.map(([n, t, d]) => `<div class="fstep"><span>шаг ${n}</span><b style="font-size:15px">${t}</b><span>${esc(d)}</span></div>`).join("");
}

// ---------------------------------------------------------------------------- графики
function lineChart(el, pts, fmtV, fmtT, label) {
  if (pts.length < 2) { el.innerHTML = `<div class="empty">${esc(label)}</div>`; return; }
  const W = el.clientWidth || 700, H = el.clientHeight || 260, L = 70, R = 12, T = 10, B = 26;
  let lo = Math.min(...pts.map((p) => p.v)), hi = Math.max(...pts.map((p) => p.v));
  const pad = Math.max((hi - lo) * 0.15, Math.abs(hi) * 0.0005 || 0.001); lo -= pad; hi += pad;
  const t0 = pts[0].t, t1 = pts.at(-1).t;
  const X = (t) => L + (t - t0) / Math.max(t1 - t0, 1) * (W - L - R), Y = (v) => T + (hi - v) / (hi - lo) * (H - T - B);
  const line = pts.map((p, i) => `${i ? "L" : "M"}${X(p.t).toFixed(1)},${Y(p.v).toFixed(1)}`).join("");
  const area = `${line}L${X(t1).toFixed(1)},${H - B}L${X(t0).toFixed(1)},${H - B}Z`;
  const col = "#3987e5", gid = "g" + Math.random().toString(36).slice(2, 7);
  const ticks = [0, 1, 2, 3].map((k) => lo + (hi - lo) * (k + 0.5) / 4);
  const xt = [0, 0.25, 0.5, 0.75, 1].map((f) => t0 + (t1 - t0) * f);
  el.innerHTML = `<svg width="${W}" height="${H}" role="img" aria-label="${esc(label)}">
    <defs><linearGradient id="${gid}" x1="0" x2="0" y1="0" y2="1"><stop offset="0" stop-color="${col}" stop-opacity=".28"/><stop offset="1" stop-color="${col}" stop-opacity="0"/></linearGradient></defs>
    ${ticks.map((v) => `<line x1="${L}" x2="${W - R}" y1="${Y(v)}" y2="${Y(v)}" stroke="#2c2c2a"/><text x="${L - 8}" y="${Y(v) + 4}" text-anchor="end" class="num">${fmtV(v)}</text>`).join("")}
    ${xt.map((t, i) => `<text x="${X(t)}" y="${H - 6}" text-anchor="${i === 0 ? "start" : i === 4 ? "end" : "middle"}">${fmtT(t, t1 - t0)}</text>`).join("")}
    <path d="${area}" fill="url(#${gid})"/><path d="${line}" fill="none" stroke="${col}" stroke-width="2" stroke-linejoin="round"/>
    <line class="vx" y1="${T}" y2="${H - B}" stroke="#8f8e86" stroke-dasharray="3 3" visibility="hidden"/>
    <circle class="dot" r="4.5" fill="${col}" stroke="#1a1a19" stroke-width="2" visibility="hidden"/>
    <rect x="${L}" y="${T}" width="${W - L - R}" height="${H - T - B}" fill="transparent" class="hit"/></svg>`;
  const svg = el.querySelector("svg"), vx = svg.querySelector(".vx"), dot = svg.querySelector(".dot"), hit = svg.querySelector(".hit");
  hit.addEventListener("mousemove", (e) => {
    const t = t0 + (e.clientX - svg.getBoundingClientRect().left - L) / (W - L - R) * (t1 - t0);
    let best = pts[0]; for (const p of pts) if (Math.abs(p.t - t) < Math.abs(best.t - t)) best = p;
    vx.setAttribute("x1", X(best.t)); vx.setAttribute("x2", X(best.t)); vx.setAttribute("visibility", "visible");
    dot.setAttribute("cx", X(best.t)); dot.setAttribute("cy", Y(best.v)); dot.setAttribute("visibility", "visible");
    showTip(e, `<b class="num">${fmtV(best.v)}</b><br><span class="dim">${new Date(best.t).toLocaleString("ru-RU")}</span>`);
  });
  hit.addEventListener("mouseleave", () => { hideTip(); vx.setAttribute("visibility", "hidden"); dot.setAttribute("visibility", "hidden"); });
}
const fmtDate = (t, span) => { const d = new Date(t); return span > 2 * 864e5 ? d.toLocaleDateString("ru-RU", {day: "numeric", month: "short"}) : d.toLocaleTimeString("ru-RU", {hour: "2-digit", minute: "2-digit"}); };
function renderEquity() {
  if (S.tab !== "overview") return;
  const all = (S.ov?.equity || []).filter((r) => r.equity > 0), since = S.eqHours ? Date.now() - S.eqHours * 3600e3 : 0;
  const pts = all.filter((r) => new Date(r.ts).getTime() >= since).map((r) => ({t: new Date(r.ts).getTime(), v: +r.equity}));
  lineChart($("#eqChart"), pts, (v) => nf(v, 0), fmtDate, "Копим снимки капитала (каждые 10 минут).");
}
document.querySelectorAll("#eqRange button").forEach((b) => b.onclick = () => {
  document.querySelectorAll("#eqRange button").forEach((x) => x.classList.toggle("on", x === b)); S.eqHours = +b.dataset.h; renderEquity();
});

// ---------------------------------------------------------------------------- позиции
function sleeveOf(tag) { return (S.ov?.manifest?.sleeves || []).find((s) => s.id === tag) || (S.strats?.strategies || []).find((s) => s.id === tag); }
function renderPositions() {
  if (S.tab !== "overview" && S.tab !== "trades") return;
  const open = S.ov?.open_trades || [];
  $("#posSub").textContent = open.length ? `${open.length} открыто · стоп у каждой позиции` : "";
  if (!open.length) { $("#positions").innerHTML = `<div class="empty">Открытых позиций нет. ${(S.ov?.manifest?.sleeves || []).filter((s) => s.stage !== "closing").length} стратегий ждут своих условий входа.</div>`; return; }
  $("#positions").innerHTML = `<table><thead><tr><th>Монета</th><th>Стратегия</th><th class="r">P&L</th><th>Защита</th><th class="r">В сделке</th></tr></thead><tbody>${open.map((t) => {
    const sl = sleeveOf(t.enter_tag), short = !!t.is_short, entry = +t.open_rate, stop = +t.stop_loss_abs, amt = +t.amount || 0;
    const locked = stop && (short ? stop <= entry : stop >= entry);
    const atStop = stop ? (short ? entry - stop : stop - entry) * amt : null;
    const prot = !stop ? pill("нет данных о стопе", "warn") : locked ? pill(`прибыль зафиксирована ${sgnUsd(atStop)}`, "good") : pill(`риск до стопа ${usd(Math.abs(atStop))}`, "");
    const pr = +(t.profit_ratio ?? 0);
    return `<tr><td><b>${esc(pair(t.pair))}</b> ${pill(short ? "шорт" : "лонг", short ? "crit" : "good")}<div class="dim mono">вход ${entry}</div></td>
      <td>${esc(famName(sl?.family))}<div class="dim mono">${esc(t.enter_tag || "")}</div></td>
      <td class="r num"><span class="${cls(t.profit_abs)}">${sgnUsd(+t.profit_abs)}</span><div class="dim">${pct(pr)}</div></td>
      <td>${prot}<div class="dim mono">стоп ${stop || "—"}</div></td><td class="r num">${dur(t.open_date)}</td></tr>`;
  }).join("")}</tbody></table>`;
}

// ---------------------------------------------------------------------------- стратегии (карточки)
const KIND = {trading: "Торгуют на демо", candidate: "Кандидаты", screen: "Нашёл скринер", rejected: "Отсеяны"};
const curvePts = (curve) => (curve || []).map(([t, v]) => ({t: typeof t === "number" ? t : new Date(t).getTime(), v: +v})).filter((p) => isFinite(p.t) && isFinite(p.v));
function spark(curve) {
  const pts = curvePts(curve);
  if (pts.length < 2) return `<div class="spark dim" style="display:grid;place-items:center;font-size:11.5px">график появится после строгой проверки</div>`;
  const W = 300, H = 46, lo = Math.min(...pts.map((p) => p.v)), hi = Math.max(...pts.map((p) => p.v)), t0 = pts[0].t, t1 = pts.at(-1).t;
  const X = (t) => (t - t0) / Math.max(t1 - t0, 1) * W, Y = (v) => 3 + (hi - v) / Math.max(hi - lo, 1e-9) * (H - 6);
  const d = pts.map((p, i) => `${i ? "L" : "M"}${X(p.t).toFixed(1)},${Y(p.v).toFixed(1)}`).join("");
  const col = pts.at(-1).v >= pts[0].v ? "#3fc23f" : "#e66767";
  return `<svg class="spark" viewBox="0 0 ${W} ${H}" preserveAspectRatio="none" width="100%"><path d="${d}" fill="none" stroke="${col}" stroke-width="1.8" vector-effect="non-scaling-stroke"/></svg>`;
}
const met = (l, v, k = "") => `<div><span>${l}</span><b class="num ${k}">${v}</b></div>`;
function renderCards() {
  if (S.tab !== "strategies") return;
  const cs = S.cards?.cards || [], counts = S.cards?.counts || {};
  $("#filters").innerHTML = [["all", `Все · ${cs.length}`], ...Object.entries(KIND).map(([k, l]) => [k, `${l} · ${counts[k] || 0}`])]
    .map(([k, l]) => `<button data-f="${k}" class="${S.filter === k ? "on" : ""}">${esc(l)}</button>`).join("");
  document.querySelectorAll("#filters button").forEach((b) => b.onclick = () => { S.filter = b.dataset.f; renderCards(); });
  const list = cs.filter((c) => S.filter === "all" || c.kind === S.filter);
  if (!list.length) { $("#cards").innerHTML = `<div class="card empty">${S.filter === "screen" ? "Скринер запустится с ближайшим прогоном лаборатории и покажет здесь выживших." : "Пока пусто."}</div>`; return; }
  $("#cards").innerHTML = list.map((c) => {
    const o = c.oos || {};
    return `<div class="scard" data-i="${cs.indexOf(c)}">
      <div class="top"><div><div class="nm">${esc(c.title)}</div><div class="sub">${esc(c.pairs.slice(0, 4).map(pair).join(", "))}${c.pairs.length > 4 ? " +" + (c.pairs.length - 4) : ""} · ${esc(c.timeframe)}${c.external ? " · ваша" : ""}</div></div>${stagePill(c.kind === "screen" ? "exploratory" : c.stage)}</div>
      <div class="idea">${esc(c.idea)}</div>
      ${spark(c.curve)}
      <div class="mets">${met("Сделок", o.trades ?? "—")}${met("PF", o.profit_factor ?? "—", (o.profit_factor || 0) >= 1 ? "pos" : "neg")}${met("Доходность", o.total_return != null ? pct(o.total_return, 1) : "—", cls(o.total_return))}${met("Ровность", o.curve_r2 != null ? nf(o.curve_r2, 2) : "—")}</div>
      <div class="sub">${c.kind === "trading" ? `на демо: ${c.live?.trades ?? 0} сделок · ${c.live?.pnl != null ? sgnUsd(c.live.pnl) : "—"}` : c.why_not?.length ? "не прошла: " + esc(c.why_not.slice(0, 2).join("; ")) : esc(c.status)}</div>
    </div>`;
  }).join("");
  document.querySelectorAll(".scard").forEach((el) => el.onclick = () => openCard(cs[+el.dataset.i]));
}
function openCard(c) {
  const o = c.oos || {}, cl = c.claimed;
  $("#dbody").innerHTML = `<h3>${esc(c.title)}</h3><div class="dim">${esc(c.pairs.map(pair).join(", "))} · ${esc(c.timeframe)} · ${stagePill(c.kind === "screen" ? "exploratory" : c.stage)} ${esc(c.status)}</div>
    <div class="box"><b>Суть стратегии.</b> ${esc(c.idea)}<br><b>Выходы и риск:</b> ${esc(c.exits)}; без плеча, риск на сделку на демо 0,1% капитала.</div>
    <h2 style="margin:14px 0 6px">Капитал на данных, которых подбор не видел</h2><div id="dChart" style="height:240px"></div>
    <div class="kv2">${[["Сделок", o.trades ?? "—"], ["Profit factor", o.profit_factor ?? "—"], ["Доходность", o.total_return != null ? pct(o.total_return, 1) : "—"],
      ["Макс. просадка", o.max_drawdown != null ? nf(o.max_drawdown * 100, 1) + "%" : "—"], ["Прибыльных сделок", o.win_rate != null ? nf(o.win_rate * 100, 0) + "%" : "—"],
      ["Шарп", o.sharpe ?? "—"], ["Ровность кривой (R²)", o.curve_r2 ?? "—"], ["Последние 3 мес.", o.last90_return != null ? pct(o.last90_return, 1) : "—"]]
      .map(([k, v]) => `<div><span>${k}</span><b class="num">${v}</b></div>`).join("")}</div>
    ${c.folds?.length ? `<h2 style="margin:14px 0 6px">Окна проверки (по 90 дней)</h2><div>${c.folds.map((f) => `<span class="pill ${f.ret > 0 ? "good" : "crit"}" style="margin:0 6px 6px 0">${esc(f.test || "")}: ${pct(f.ret, 1)} · ${f.trades ?? 0} сд.</span>`).join("")}</div>` : ""}
    ${c.why_not?.length ? `<div class="box" style="border-left-color:var(--crit)"><b>Почему не допущена к капиталу:</b> ${esc(c.why_not.join("; "))}.</div>` : ""}
    ${c.kind === "trading" ? `<div class="box" style="border-left-color:var(--good)"><b>На демо-счёте:</b> ${c.live?.trades ?? 0} сделок, P&L ${c.live?.pnl != null ? sgnUsd(c.live.pnl) : "—"}, PF ${c.live?.profit_factor ?? "—"}.</div>` : ""}
    ${cl ? `<div class="box" style="border-left-color:var(--warn)"><b>Ваш анализатор показывал:</b> ${pct(cl.total_return, 0)} за ${esc(cl.period)}, PF ${cl.profit_factor}, ${cl.trades} сделок, просадка ${nf(cl.max_drawdown * 100, 1)}% (плечо ${cl.leverage}×). Здесь — честная проверка той же логики без плеча.</div>` : ""}
    <h2 style="margin:14px 0 6px">Параметры входа</h2><div class="kv2">${Object.entries(c.params || {}).map(([k, v]) => `<div><span>${esc(k)}</span><b class="num">${esc(v)}</b></div>`).join("")}</div>
    <p class="howto">Как читать: «доходность» и «PF» — только по периоду, который подбор параметров не видел, после комиссий Bybit. Ровность 1,0 — идеально ровная линия вверх. На демо стратегия торгует, если прошла строгую проверку; на реальный счёт — только после форвард-теста и всех проверок готовности, и только по вашему решению.</p>`;
  $("#drawer").classList.add("open");
  lineChart($("#dChart"), curvePts(c.curve), (v) => pct(v - 1, 1), fmtDate, "График появится после строгой проверки этой стратегии.");
}
$("#dx").onclick = () => $("#drawer").classList.remove("open");
addEventListener("keydown", (e) => { if (e.key === "Escape") $("#drawer").classList.remove("open"); });

// ---------------------------------------------------------------------------- лаборатория
const STEPS = ["download", "hyperopt fold 1", "oos fold 1", "hyperopt fold 2", "oos fold 2", "hyperopt fold 3", "oos fold 3", "hyperopt fold 4", "oos fold 4", "robustness", "evaluated"];
function stepIndex(stage) { stage = String(stage || ""); const i = STEPS.findIndex((s) => stage.startsWith(s)); return i < 0 ? 0 : i; }
function stageText(p) {
  const st = String(p.stage || "");
  if (st.startsWith("hyperopt")) return `Подбор параметров на прошлом (окно ${st.replace("hyperopt fold ", "")})${p.epoch ? ` · эпоха ${p.epoch}/${p.epochs || "?"}` : ""}`;
  if (st.startsWith("oos")) return `Проверка на невиданных месяцах (окно ${st.replace("oos fold ", "")})`;
  return {download: "Загрузка истории Bybit", robustness: "Стресс-тест и устойчивость", evaluated: "Готово · ждёт сводки", failed: "Ошибка"}[st] || st;
}
function renderLab() {
  if (S.tab !== "lab") return;
  const rs = S.rs || {}, lab = rs.lab || {}, exps = rs.experiments || [];
  const run = exps.filter((e) => e.status === "running" && e.progress?.remote && (!lab.run_id || e.progress.run_id == lab.run_id));
  const byJob = {}; for (const e of run) { const j = e.progress?.job ?? 0; if (!byJob[j] || e.created > byJob[j].created) byJob[j] = e; }
  const doneRun = run.filter((e) => e.progress?.stage === "evaluated").length;
  $("#labSub").textContent = labActive() ? `прогон ${lab.run_id || ""} · начат ${ago(lab.started)} · готово опытов: ${doneRun} · бюджет ${lab.budget_min || "?"} мин на вычислитель`
    : `последний прогон ${ago(lab.ts)} · всего прогонов ${lab.runs || 0} · опытов ${lab.experiments_total || 0}`;
  $("#lanes").innerHTML = [0, 1, 2, 3].map((j) => {
    const e = byJob[j];
    if (!e || !labActive()) return `<div class="lane idle"><div>Вычислитель ${j + 1}</div><div class="dim">${labActive() ? "запускается…" : "ждёт прогона"}</div></div>`;
    const p = e.progress || {}, k = stepIndex(p.stage), info = e.info || {};
    const why = info.screen ? "выживший из скринера" : info.external ? "ваша стратегия" : info.revalidates ? `перепроверка ${info.revalidates}` : info.refines ? `доработка ${info.refines}` : "новый поиск";
    return `<div class="lane"><div class="hd"><span>Вычислитель ${j + 1}</span><span class="mono">${esc(e.id)}</span></div>
      <div class="fam">${esc(famName(e.family))}</div><div class="meta">${e.pairs} монет · ${esc(why)}</div>
      <div class="steps">${STEPS.map((_, i) => `<i class="${i < k ? "d" : i === k ? "c" : ""}"></i>`).join("")}</div>
      <div class="stage">${esc(stageText(p))}</div>
      ${p.epochs && String(p.stage).startsWith("hyperopt") ? `<div class="bar"><i style="width:${Math.min(100, (p.epoch || 0) / p.epochs * 100)}%"></i></div>` : ""}
      <div class="best">${p.best_trades ? `лучший пока: ${p.best_trades} сделок, ${pct(p.best_profit)} на обучении` : ""}${p.budget_left_min != null ? ` · осталось ${Math.round(p.budget_left_min)} мин` : ""}</div></div>`;
  }).join("");
  [renderScreen, renderResults, renderFamilies, renderReadiness, renderLearn].forEach(safe);
}
function renderScreen() {
  const sc = S.scr || {}, top = sc.top || [];
  const tested = new Map((S.rs?.experiments || []).filter((e) => e.info?.screen).map((e) => [e.info.screen, e]));
  $("#scrSub").textContent = sc.evaluated ? `${nf(sc.evaluated, 0)} вариантов на ${sc.series} рядах «монета × таймфрейм» · выжило ${sc.n_survivors}${sc.expected_false != null ? ` (из них случайных ожидается ≈ ${nf(sc.expected_false, 1)})` : ""} · ${ago(sc.ts || sc.created)}` : "ваш движок Strategy Lab · первый запуск с ближайшим прогоном";
  if (!top.length) { $("#screen").innerHTML = `<div class="empty">${sc.evaluated ? "Ни один вариант не удержал прибыль с ровной кривой на невиданных данных." : "Скринер ещё не запускался. Он переберёт тысячи вариантов 10 стратегий вашего анализатора на 30 монетах (15m и 1h) и покажет здесь выживших."}</div>`; return; }
  const ex = (x) => `стоп ${x.sl}×ATR · ${x.tp ? "тейк " + x.tp + "R" : "без тейка"} · ${x.tr ? "трейлинг " + x.tr + "×ATR" : "без трейлинга"}`;
  $("#screen").innerHTML = `<table><thead><tr><th>Стратегия</th><th>Монета · ТФ</th><th class="r">Сделок</th><th class="r">PF</th><th class="r">Доходн.</th><th class="r">Просадка</th><th class="r">Ровность</th><th class="r">3 мес.</th><th>Строгая проверка</th></tr></thead><tbody>${top.map((x) => {
    const e = tested.get(x.id), v = e?.summary?.verdict;
    const wf = !e ? pill("в очереди", "") : e.status === "running" ? pill("идёт", "blue") : pill(`${{validated: "прошла", exploratory: "кандидат", rejected: "отсеяна"}[v] || v} · PF ${e.oos?.profit_factor ?? "—"}`, {validated: "good", exploratory: "warn", rejected: "crit"}[v] || "");
    return `<tr><td>${esc(x.name || famName(x.family))}<div class="dim mono">${esc(JSON.stringify(x.params))} · ${esc(ex(x.exits || {}))}</div></td>
      <td>${esc(pair(x.pair))} · ${esc(x.timeframe)}</td><td class="r num">${x.B?.trades ?? "—"}</td><td class="r num pos">${x.B?.pf ?? "—"}</td>
      <td class="r num ${cls(x.B?.net)}">${x.B?.net != null ? (x.B.net > 0 ? "+" : "") + nf(x.B.net, 1) + "%" : "—"}</td><td class="r num">${x.B?.dd != null ? nf(x.B.dd, 1) + "%" : "—"}</td>
      <td class="r num">${x.r2}</td><td class="r num ${cls(x.last90)}">${x.last90 > 0 ? "+" : ""}${x.last90}%</td><td>${wf}</td></tr>`;
  }).join("")}</tbody></table>
  <p class="dim" style="margin:8px 0 0;font-size:12px">Цифры скринера — бэктест вашего движка без плеча на всю сумму, с комиссиями и проскальзыванием, только на невиданных 40% истории. Потом каждую проверяют строже: 4 окна по 90 дней, двойные комиссии, поправка на число попыток; затем форвард-тест и демо.</p>`;
}
function renderResults() {
  const done = (S.rs?.experiments || []).filter((e) => e.status === "done").slice(0, 14);
  if (!done.length) { $("#results").innerHTML = `<div class="empty">Готовых проверок пока нет.</div>`; return; }
  const vp = (v) => pill({validated: "прошла", exploratory: "кандидат", rejected: "отсеяна"}[v] || v, {validated: "good", exploratory: "warn", rejected: ""}[v] || "");
  $("#results").innerHTML = `<table><thead><tr><th>Стратегия</th><th class="r">Сделок</th><th class="r">PF</th><th class="r">Шарп</th><th class="r">Просадка</th><th class="r">Ровность</th><th>Окна</th><th>Итог</th></tr></thead><tbody>${done.map((e) => {
    const o = e.oos || {}, f = e.folds || [];
    return `<tr><td>${esc(famName(e.family))}<div class="dim">${e.pairs} монет · ${esc(e.timeframe || "1h")} · ${ago(e.finished)}</div></td>
      <td class="r num">${o.trades ?? "—"}</td><td class="r num ${(o.profit_factor || 0) >= 1 ? "pos" : "neg"}">${o.profit_factor ?? "—"}</td>
      <td class="r num">${o.sharpe ?? "—"}</td><td class="r num">${o.max_drawdown != null ? nf(o.max_drawdown * 100, 1) + "%" : "—"}</td>
      <td class="r num">${o.curve_r2 != null ? nf(o.curve_r2, 2) : "—"}</td>
      <td title="каждый квадрат — одно окно 90 дней">${f.map((x) => `<span class="fold ${x.ret > 0 ? "p" : x.ret < 0 ? "n" : ""}" title="${esc(x.test)}: ${pct(x.ret)}, ${x.trades ?? 0} сделок"></span>`).join("")}</td>
      <td>${vp(e.summary?.verdict || "—")}</td></tr>`;
  }).join("")}</tbody></table>`;
}
const GN = {deflated_sharpe: "может быть удачей перебора", fold_consistency: "прибыльна не во всех окнах", trades: "мало сделок", profit_factor: "низкий PF", sharpe: "низкий Шарп", max_drawdown: "большая просадка", stress_pf: "не держит двойные комиссии", wfe: "хуже на новых данных", robustness: "неустойчивые параметры", monte_carlo: "Монте-Карло"};
function renderFamilies() {
  const fs = S.rs?.family_stats || {}, rows = Object.entries(fs);
  const m = Math.max(0.05, ...rows.map(([, v]) => Math.abs(v[1])));
  $("#families").innerHTML = rows.sort((a, b) => b[1][1] - a[1][1]).map(([f, [n, mean]]) => {
    const w = Math.abs(mean) / m * 50, left = mean >= 0 ? 50 : 50 - w;
    return `<div class="famrow"><span class="nm">${esc(famName(f))}</span><div class="dv"><i style="left:${left}%;width:${w}%;background:${mean >= 0 ? "var(--blue)" : "var(--crit)"}"></i></div><span class="val num">${nf(mean, 2)} · ${n}</span></div>`;
  }).join("");
  const gf = Object.entries(S.rs?.gate_failures || {}).sort((a, b) => b[1] - a[1]).slice(0, 5), gm = Math.max(1, ...gf.map((x) => x[1]));
  $("#gates").innerHTML = gf.map(([g, n]) => `<div class="famrow"><span class="nm">${esc(GN[g] || g)}</span><div class="bar"><i style="width:${n / gm * 100}%;background:#c3c2b7"></i></div><span class="val num">${n}</span></div>`).join("") || `<div class="empty">—</div>`;
}
function renderReadiness() {
  const r = S.ready || {};
  $("#rdSub").textContent = `${r.passed ?? 0}/${r.total ?? 8} · только рекомендация`;
  const RU = {forward_days: "Форвард после повышения", trades: "Закрытых сделок", diversified: "Независимых стратегий", t_stat: "Статистическая значимость", profit_factor: "PF после поправки", drawdown: "Макс. просадка", stability: "Прибыльные трети периода", consistency: "Демо совпадает с проверкой"};
  $("#readiness").innerHTML = (r.checks || []).map((c) => `<div class="check"><span class="ic ${c.pass ? "ok" : "no"}">${c.pass ? "✓" : "·"}</span><span>${esc(RU[c.id] || c.title)}<div class="need">нужно ${esc(c.need)}</div></span><b class="num">${esc(c.value)}</b></div>`).join("")
    + `<p class="dim" style="margin:8px 0 0;font-size:11.5px">Система никогда не переключится на реальный счёт сама — только по вашему решению.</p>`;
}
function renderForward() {
  if (S.tab !== "overview") return;
  const f = S.fw || {}, t = f.top || {}, rest = f.rest || {}, p = f.persistence || {};
  const v = {works: ["Работает", "good"], not_working: ["Не работает", "crit"], inconclusive: ["Неясно", "warn"], early_positive: ["Ранний сигнал: скорее плюс", "blue"], early_negative: ["Ранний сигнал: скорее минус", "warn"], too_early: ["Копим данные", ""]}[f.verdict] || ["Копим данные", ""];
  const n = t.trades || 0, need = f.rules?.final_trades ?? 200;
  const row = (l, g) => `<tr><td>${l}</td><td class="r num">${g.strategies ?? 0}</td><td class="r num">${g.trades ?? 0}</td><td class="r num ${cls(g.pnl_pct)}">${g.pnl_pct != null ? (g.pnl_pct > 0 ? "+" : "") + nf(g.pnl_pct, 2) + "%" : "—"}</td><td class="r num">${g.pf ?? "—"}</td><td class="r num">${g.t_daily ?? "—"}</td></tr>`;
  const pers = p.experiments ? `Проверка на истории (${p.experiments} опытов): если первая половина невиданного периода была в плюсе, вторая была в плюсе в <b>${p.p_second_pos_if_first_pos != null ? Math.round(p.p_second_pos_if_first_pos * 100) + "%" : "—"}</b> случаев (после минусовой — в ${p.p_second_pos_if_first_neg != null ? Math.round(p.p_second_pos_if_first_neg * 100) + "%" : "—"}).` : "";
  $("#forward").innerHTML = `<div style="display:flex;gap:14px;align-items:center;margin-bottom:10px;flex-wrap:wrap">${pill(v[0], v[1])}<span>${n < 100 ? `Решение примем на ${need} сделках лучших стратегий (сейчас ${n}). Первая оценка — на 100 сделках и 7 днях.` : esc(f.text || "")}</span></div>
    <div class="bar" style="margin-bottom:12px"><i style="width:${Math.min(100, n / need * 100)}%"></i></div>
    <table><thead><tr><th>Группа (по оценке на истории)</th><th class="r">Стратегий</th><th class="r">Сделок на новых данных</th><th class="r">Доходность</th><th class="r">PF</th><th class="r">t по дням</th></tr></thead>
    <tbody>${row("Лучшая четверть — те, что лаборатория считает лучшими", t)}${row("Все остальные (контрольная группа)", rest)}</tbody></table>
    <p class="dim" style="margin:10px 0 0;font-size:12px">${f.book_size ?? 0} замороженных стратегий каждый прогон проверяются на свечах Bybit только после момента заморозки, с комиссиями и проскальзыванием. Правило решения записано заранее: «работает» = у лучшей четверти ≥ ${need} сделок за ≥ ${f.rules?.final_days ?? 14} дней, PF ≥ ${f.rules?.pf_works ?? 1.15}, t ≥ ${f.rules?.t_works ?? 2}. ${pers}</p>`;
}
function renderGoals() {
  if (S.tab !== "overview") return;
  const RU = {forward: "Форвард-тест: лучшие стратегии в плюсе на новых данных", readiness: "Готовность к реальному счёту (все проверки)", validated: "Найти стратегию, прошедшую все строгие проверки",
    evidence: "Набрать сделки на демо", research: "Исследования: строгих проверок за 7 дней", pf: "Profit factor на демо ≥ 1,3 (≥ 30 сделок)", production: "Стратегий в основной торговле", return: "Капитал демо +10% (просадка < 15%)"};
  $("#goals").innerHTML = (S.goals?.goals || []).map((g) => `<div class="goal"><span class="t">${esc(RU[g.id] || g.title)}</span><b class="num">${esc(g.value)}${g.unit === "%" ? "%" : ""}<span class="dim"> / ${esc(g.target)}${g.unit === "%" ? "%" : ""}</span></b>
    <div class="bar"><i style="width:${Math.round(Math.max(0, Math.min(1, g.progress)) * 100)}%;background:${g.progress >= 1 ? "var(--good)" : g.warning ? "var(--crit)" : "var(--blue)"}"></i></div></div>`).join("");
}
// журнал: сервер пишет по-английски (для отладки), пульт показывает по-русски
const famRe = (f) => famName(f.trim());
const RU_EVENTS = [
  [/^lab: experiment (\S+) started — (\S+) on (\d+) pairs \((.+)\)$/, (m) => `опыт ${m[1]} начат — ${famRe(m[2])} на ${m[3]} монетах (${m[4].replace("new search", "новый поиск").replace("refines", "доработка").replace("revalidates", "перепроверка")})`],
  [/^lab: experiment (\S+) failed: (.*)$/, (m) => `опыт ${m[1]} — ошибка: ${m[2]}`],
  [/^lab: GitHub research run (\S+) started \((\d+) CPUs, budget (\S+) min\)$/, (m) => `запущен прогон лаборатории ${m[1]} (${m[2]} ядер, бюджет ${m[3]} мин)`],
  [/^lab: universe refreshed on (\S+) — (\d+) pairs$/, (m) => `список монет обновлён (${m[1]}) — ${m[2]} монет`],
  [/^lab: batch (\S+) imported — (\d+) experiments, (\d+) new candidates.*$/, (m) => `сводка прогона ${m[1]}: ${m[2]} опытов, новых кандидатов: ${m[3]}`],
  [/^lab: forward test of (\d+) frozen strategies on unseen Bybit data — (\d+) forward trades$/, (m) => `форвард-тест: ${m[1]} стратегий проверено на новых данных — ${m[2]} сделок`],
  [/^screener: ([\d,]+) strategy combinations tested on (\d+) .* — (\d+) stayed.*$/, (m) => `скринер: проверено ${m[1].replace(/,/g, " ")} вариантов на ${m[2]} рядах — выжило ${m[3]} → строгая проверка`],
  [/^manifest v(\d+): (\d+) sleeves.*?(\d+) pairs.*$/, (m) => `торговый план v${m[1]}: ${m[2]} стратегий, ${m[3]} монет`],
  [/^(\S+) (long|short): stop moved to (\S+) — profit locked \+?\$?(\S+)$/, (m) => `${m[1]} ${m[2] === "long" ? "лонг" : "шорт"}: стоп перенесён на ${m[3]} — зафиксировано +${m[4]} $`],
  [/^synced (\d+) new closed demo trades$/, (m) => `учтено новых закрытых сделок: ${m[1]}`],
  [/^new learning \[(.+?)\] (.*)$/, (m) => `новый вывод [${m[1]}]: ${m[2]}`],
  [/^universe refreshed: (\d+) pairs \((.+)\)$/, (m) => `список монет обновлён: ${m[1]} (${m[2]})`],
  [/^real-money readiness (\d+)\/(\d+) checks.*$/, (m) => `готовность к реальному счёту: ${m[1]}/${m[2]} проверок`],
  [/^(\S+): (validated|exploratory|rejected) — OOS trades (\d+), PF (\S+).*$/, (m) => `${m[1]}: ${{validated: "прошла проверки", exploratory: "кандидат", rejected: "отсеяна"}[m[2]]} — ${m[3]} сделок, PF ${m[4]}`],
  [/^forward test: (.*)$/, (m) => `форвард-тест: ${m[1]}`],
  [/^manager started$/, () => "менеджер запущен"],
  [/^research mode: remote.*$/, () => "исследования идут в лаборатории на GitHub — сервер только торгует"],
  [/^started: (.*)$/, (m) => `система запущена: ${m[1]}`],
  [/^self-test PASSED.*$/, () => "самопроверка пройдена"],
  [/^execution test PASSED.*$/, () => "проверка исполнения пройдена: вход, стоп на бирже, выход"],
  [/^control action: (.*)$/, (m) => `действие с пульта: ${m[1]}`],
];
const ruEvent = (msg) => { for (const [re, f] of RU_EVENTS) { const m = re.exec(msg); if (m) return f(m); } return msg; };

function renderLog() {
  if (S.tab !== "overview" && S.tab !== "lab") return;
  const ev = S.ev?.events || S.ov?.events || [];
  const SRC = {research: "исследования", lifecycle: "отбор", strategy: "стратегия", manager: "менеджер", supervisor: "система", scanner: "рынок", risk: "риск", web: "пульт", learner: "обучение"};
  $("#log").innerHTML = ev.slice(0, 60).map((e) => `<div class="${esc(e.level)}"><time class="num">${esc((e.ts || "").slice(11, 16))}</time><span class="src">${esc(SRC[e.source] || e.source)}</span><span class="msg">${esc(ruEvent(e.message))}</span></div>`).join("") || `<div class="empty">тихо</div>`;
}
function renderLearn() {
  const ln = (S.ln?.learnings || []).filter((l) => l.active).slice(0, 25);
  $("#learn").innerHTML = ln.map((l) => `<div><time class="num">${esc((l.ts || "").slice(5, 10))}</time><span class="src">${esc(l.scope)}</span><span class="msg">${esc(l.insight)}</span></div>`).join("") || `<div class="empty">Пока нет выводов — они появляются из завершённых проверок и закрытых сделок.</div>`;
}

// ---------------------------------------------------------------------------- сделки
function renderTrades() {
  if (S.tab !== "trades") return;
  const sl = (S.ov?.manifest?.sleeves || []).filter((s) => s.stage !== "closing");
  const byId = Object.fromEntries((S.strats?.strategies || []).map((x) => [x.id, x]));
  $("#slvSub").textContent = `${sl.length} стратегий · ${new Set(sl.flatMap((s) => s.pairs)).size} монет под наблюдением`;
  $("#sleeves").innerHTML = sl.length ? `<table><thead><tr><th>Стратегия</th><th>Стадия</th><th>ТФ</th><th>Монеты</th><th class="r">Риск/сделка</th><th class="r">Сделок</th><th class="r">P&L</th></tr></thead><tbody>${sl.map((s) => {
    const lv = byId[s.id]?.live || {};
    return `<tr><td>${esc(famName(s.family))}<div class="dim mono">${esc(s.id)}</div></td><td>${stagePill(s.stage)}</td><td>${esc(s.timeframe || "1h")}</td>
      <td class="dim">${s.pairs.slice(0, 6).map(pair).join(", ")}${s.pairs.length > 6 ? ` +${s.pairs.length - 6}` : ""}</td>
      <td class="r num">${nf(s.risk * 100, 2)}%</td><td class="r num">${lv.trades ?? 0}</td><td class="r num ${cls(lv.pnl)}">${lv.pnl != null ? sgnUsd(lv.pnl) : "—"}</td></tr>`;
  }).join("")}</tbody></table>` : `<div class="empty">Стратегии не развёрнуты.</div>`;
  const tr = S.trades?.closed || [];
  const tot = tr.reduce((a, t) => a + (+t.profit_abs || 0), 0), wins = tr.filter((t) => +t.profit_abs > 0).length;
  const RS = {stop_loss: "стоп", stoploss_on_exchange: "стоп на бирже", managed_stop: "защитный стоп", take_profit: "тейк", exit_signal: "сигнал выхода", time_exit: "по времени", custom_exit: "фиксация прибыли", force_exit: "вручную"};
  $("#closedSub").textContent = tr.length ? `${tr.length} сделок · ${Math.round(wins / tr.length * 100)}% прибыльных · ${sgnUsd(tot)} на демо` : "";
  $("#closed").innerHTML = tr.length ? `<table><thead><tr><th>Закрыта</th><th>Монета</th><th>Стратегия</th><th class="r">Вход → выход</th><th>Причина</th><th class="r">P&L</th><th class="r">%</th></tr></thead><tbody>${tr.slice(0, 60).map((t) => {
    const s = sleeveOf(t.sleeve_id);
    return `<tr><td class="num">${esc((t.close_date || "").slice(5, 16).replace("T", " "))}</td><td><b>${esc(pair(t.pair))}</b> ${pill(t.is_short ? "шорт" : "лонг", t.is_short ? "crit" : "good")}</td>
      <td>${esc(famName(s?.family))}<div class="dim mono">${esc(t.sleeve_id)}</div></td><td class="r num">${t.open_rate} → ${t.close_rate}</td><td>${esc(RS[t.exit_reason] || t.exit_reason)}</td>
      <td class="r num ${cls(t.profit_abs)}">${sgnUsd(+t.profit_abs)}</td><td class="r num ${cls(t.profit_ratio)}">${pct(+t.profit_ratio)}</td></tr>`;
  }).join("")}</tbody></table>` : `<div class="empty">Закрытых сделок пока нет.</div>`;
}

// ---------------------------------------------------------------------------- опрос данных
function safe(fn) { try { fn(); } catch (e) { console.warn(fn.name, e); } }
function renderAll() { [renderHeader, renderKpis, renderPipeline, renderEquity, renderPositions, renderForward, renderGoals, renderLog, renderCards, renderLab, renderTrades].forEach(safe); }
async function fast() {
  try { const [ov, rs] = await Promise.all([api("/api/overview"), api("/api/research")]); Object.assign(S, {ov, rs}); renderAll(); }
  catch (e) { chip("#chUpd", "crit", "ошибка данных: " + e.message); }
}
let lastSlow = 0;
async function slow() {
  if (Date.now() - lastSlow < 50000) return; lastSlow = Date.now();
  const get = (p) => api(p).catch(() => null);
  const [goals, ready, strats, trades, ln, fw, ev, scr, cards] = await Promise.all([get("/api/goals"), get("/api/readiness"), get("/api/strategies"), get("/api/trades?limit=200"),
    get("/api/learnings"), get("/api/forward"), get("/api/events?limit=60"), get("/api/screen"), get("/api/cards")]);
  Object.assign(S, Object.fromEntries(Object.entries({goals, ready, strats, trades, ln, fw, ev, scr, cards}).filter(([, v]) => v)));
  renderAll();
}
async function tick() { await fast(); await slow(); window.__ready = true; }
const startTab = (location.hash || "").slice(1);
if (["overview", "strategies", "lab", "trades", "office"].includes(startTab)) setTab(startTab);
tick(); setInterval(tick, 10000);
addEventListener("resize", () => safe(renderEquity));
