// One candle chart for every page (owner, 23.11): Bybit candles of the coin, the demo trades of
// this bot and each strategy's trades from the lab's backtest on history. Wheel / pinch = zoom,
// drag = scroll back in time (older candles load on their own), hover or tap a trade = details.
(() => {
  "use strict";
  const TFS = ["15m", "1h", "2h", "4h", "6h", "1d"];
  const TF_MS = {"15m": 9e5, "30m": 18e5, "1h": 36e5, "2h": 72e5, "4h": 144e5, "6h": 216e5, "12h": 432e5, "1d": 864e5};
  const C = {bg: "#13171c", grid: "#20262e", text: "#8b95a1", up: "#2fbf71", down: "#ef5350", open: "#f0b429", cross: "#5b6573", hist: "#7aa7ff"};
  const RS = {stop_loss: "стоп", stoploss_on_exchange: "стоп на бирже", managed_stop: "защитный стоп", take_profit: "тейк-профит",
              exit_signal: "сигнал выхода", time_exit: "по времени", custom_exit: "фиксация прибыли", force_exit: "конец данных / вручную"};
  const esc = (v) => String(v ?? "").replace(/[&<>"']/g, (c) => ({"&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;"}[c]));
  const api = (u) => fetch(u, {credentials: "same-origin"}).then(async (r) => {
    if (!r.ok) throw new Error((await r.json().catch(() => ({}))).detail || r.status); return r.json(); });
  const fmtP = (v) => { v = +v; if (!isFinite(v)) return "—"; const a = Math.abs(v);
    return v.toLocaleString("ru-RU", {maximumFractionDigits: a >= 1000 ? 1 : a >= 10 ? 2 : a >= 1 ? 4 : 6}); };
  const fmtT = (ms, tf) => new Date(ms).toLocaleString("ru-RU", tf === "1d" ? {day: "2-digit", month: "short", year: "2-digit"} : {day: "2-digit", month: "short", hour: "2-digit", minute: "2-digit"});
  const coin = (p) => String(p || "").split("/")[0];

  function mount(el, opt) {
    const st = {pair: opt.pair, tf: TFS.includes(opt.tf) ? opt.tf : "1h", sid: opt.sid || null, focus: opt.focus || null,
                candles: [], more: true, loading: false, i0: 0, i1: 0, trades: null, show: {demo: true, hist: true}, only: null,
                hover: null, drag: null, err: null, h: opt.height || 380};
    const strip = (label, inner) => `<span class="tc-grp"><span class="tc-l">${label}</span>${inner}</span>`;
    el.innerHTML = `<div class="tc">
      <div class="tc-bar"></div>
      <div class="tc-wrap"><canvas></canvas><div class="tc-tip"></div><div class="tc-ohlc"></div><div class="tc-msg">Загрузка свечей…</div></div>
      <div class="tc-legend">▲ вход в лонг · ▼ вход в шорт · ● выход (зелёный — прибыль, красный — убыток) · <b>сплошные</b> — сделки на демо,
        <span style="color:${C.hist}">пунктир с пустыми значками</span> — бэктест этой стратегии на истории (иллюстрация: часть года стратегия видела при подборе; доказательство — проверка вне выборки и форвард) ·
        колесо — масштаб, тянуть — назад во времени, наведите на сделку — подробности.</div></div>`;
    const bar = el.querySelector(".tc-bar"), cv = el.querySelector("canvas"), tip = el.querySelector(".tc-tip"),
          ohlc = el.querySelector(".tc-ohlc"), msg = el.querySelector(".tc-msg"), wrap = el.querySelector(".tc-wrap");
    const ctx = cv.getContext("2d");
    let alive = true;

    // -------------------------------------------------------------- data
    async function loadTrades() {
      try { st.trades = await api(`/api/chart/trades?pair=${encodeURIComponent(st.pair)}${st.sid ? `&sid=${encodeURIComponent(st.sid)}` : ""}`); }
      catch (e) { st.trades = {demo: [], history: {}, labels: {}, strategies: []}; }
      if (st.sid && st.only === null) st.only = new Set([st.sid]);
      renderBar(); draw();
    }
    async function loadCandles(reset) {
      if (st.loading) return; st.loading = true;
      try {
        let end = "";
        if (!reset && st.candles.length) end = `&end=${st.candles[0][0] - 1}`;
        else if (reset && st.focus && st.focus.t1 && Date.now() - st.focus.t1 > TF_MS[st.tf] * 600) end = `&end=${Math.round(st.focus.t1 + TF_MS[st.tf] * 300)}`;
        const d = await api(`/api/chart/candles?pair=${encodeURIComponent(st.pair)}&tf=${st.tf}&limit=1000${end}`);
        const rows = (d.candles || []).filter((r) => !st.candles.length || reset || r[0] < st.candles[0][0]);
        if (reset) { st.candles = rows; st.more = d.more; fitView(); }
        else if (rows.length) { st.candles = rows.concat(st.candles); st.i0 += rows.length; st.i1 += rows.length; st.more = d.more; }
        else st.more = false;
        st.err = null;
      } catch (e) { st.err = `Свечи недоступны: ${e.message}`; }
      st.loading = false; msg.style.display = st.err ? "flex" : "none"; msg.textContent = st.err || ""; draw();
    }
    function fitView() {
      const n = st.candles.length; if (!n) return;
      const span = Math.min(n, Math.max(60, Math.round((cv.clientWidth || 900) / 7)));
      let end = n;
      if (st.focus && st.focus.t0) {  // a trade asked for: centre it
        const a = idx(st.focus.t0), b = idx(st.focus.t1 || st.focus.t0);
        end = Math.min(n, Math.max(span, Math.round((a + b) / 2 + span / 2)));
      }
      st.i1 = end + 3; st.i0 = st.i1 - span - 3;
    }
    const idx = (ms) => {  // time → fractional candle index (binary search; candles are contiguous)
      const cs = st.candles, n = cs.length; if (!n) return 0;
      if (ms <= cs[0][0]) return (ms - cs[0][0]) / TF_MS[st.tf];
      let lo = 0, hi = n - 1;
      while (lo < hi) { const m = (lo + hi + 1) >> 1; if (cs[m][0] <= ms) lo = m; else hi = m - 1; }
      return lo + (ms - cs[lo][0]) / TF_MS[st.tf];
    };
    function visibleTrades() {
      const T = st.trades; if (!T) return [];
      const keep = (s) => !st.only || st.only.has(s);
      const out = [];
      if (st.show.demo) for (const t of T.demo || []) if (keep(t.sid)) out.push(t);
      if (st.show.hist) for (const [s, h] of Object.entries(T.history || {})) if (keep(s)) for (const t of h.trades || []) out.push(t);
      return out;
    }

    // -------------------------------------------------------------- controls
    function renderBar() {
      const T = st.trades || {}, L = T.labels || {};
      const nDemo = (T.demo || []).length, nHist = Object.values(T.history || {}).reduce((a, h) => a + (h.trades || []).length, 0);
      const sids = [...new Set([...(T.strategies || []), ...(T.demo || []).map((t) => t.sid).filter(Boolean)])];
      const lab = (s) => L[s]?.code ? `#${L[s].code}` : (L[s]?.method || s);
      bar.innerHTML = strip("Свечи", TFS.map((t) => `<button data-tf="${t}" class="${t === st.tf ? "on" : ""}">${t}</button>`).join("")) +
        strip("Сделки", `<button data-k="demo" class="${st.show.demo ? "on" : ""}">Демо · ${nDemo}</button><button data-k="hist" class="${st.show.hist ? "on" : ""}">История теста · ${nHist}</button>`) +
        (sids.length > 1 ? strip("Стратегии", `<button data-s="" class="${!st.only ? "on" : ""}">все</button>` +
          sids.map((s) => `<button data-s="${esc(s)}" title="${esc(L[s]?.method || s)}" class="${st.only && st.only.has(s) ? "on" : ""}">${esc(lab(s))}</button>`).join("")) : "") +
        `<span class="tc-grp"><button data-k="now">→ сейчас</button></span>` +
        (nHist === 0 && T.strategies && T.strategies.length ? `<span class="tc-note">история теста появится после ближайшего прогона лаборатории</span>` : "");
      bar.querySelectorAll("[data-tf]").forEach((b) => b.onclick = () => { st.tf = b.dataset.tf; st.candles = []; st.more = true; msg.style.display = "flex"; msg.textContent = "Загрузка свечей…"; renderBar(); loadCandles(true); });
      bar.querySelectorAll("[data-k=demo],[data-k=hist]").forEach((b) => b.onclick = () => { st.show[b.dataset.k] = !st.show[b.dataset.k]; renderBar(); draw(); });
      bar.querySelectorAll("[data-s]").forEach((b) => b.onclick = () => {
        const s = b.dataset.s;
        if (!s) st.only = null;
        else { st.only = st.only ? new Set(st.only) : new Set(); st.only.has(s) ? st.only.delete(s) : st.only.add(s); if (!st.only.size) st.only = null; }
        renderBar(); draw(); });
      const now = bar.querySelector("[data-k=now]"); if (now) now.onclick = () => {
        st.focus = null; const last = st.candles.at(-1);
        if (!last || Date.now() - last[0] > TF_MS[st.tf] * 3) { st.candles = []; st.more = true; loadCandles(true); } else { fitView(); draw(); } };
    }

    // -------------------------------------------------------------- drawing
    let geo = null;
    function draw() {
      if (!alive) return;
      const dpr = window.devicePixelRatio || 1, W = wrap.clientWidth || 900, H = st.h;
      if (cv.width !== Math.round(W * dpr) || cv.height !== Math.round(H * dpr)) { cv.width = Math.round(W * dpr); cv.height = Math.round(H * dpr); cv.style.height = H + "px"; }
      ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
      ctx.fillStyle = C.bg; ctx.fillRect(0, 0, W, H);
      const cs = st.candles; if (!cs.length) { geo = null; return; }
      const R = 70, B = 22, pw = W - R, ph = H - B;
      st.i0 = Math.max(-20, st.i0); st.i1 = Math.min(cs.length + 40, Math.max(st.i0 + 15, st.i1));
      const span = st.i1 - st.i0, X = (i) => (i - st.i0 + 0.5) / span * pw;
      const a = Math.max(0, Math.floor(st.i0)), b = Math.min(cs.length - 1, Math.ceil(st.i1));
      let lo = Infinity, hi = -Infinity;
      for (let i = a; i <= b; i++) { lo = Math.min(lo, cs[i][3]); hi = Math.max(hi, cs[i][2]); }
      const trs = visibleTrades().filter((t) => { const x0 = idx(t.t0), x1 = t.t1 ? idx(t.t1) : cs.length; return x1 >= st.i0 && x0 <= st.i1; });
      for (const t of trs) for (const p of [t.p0, t.p1]) if (p != null && isFinite(+p) && +p > lo * 0.7 && +p < hi * 1.3) { lo = Math.min(lo, +p); hi = Math.max(hi, +p); }
      if (!isFinite(lo)) { lo = 0; hi = 1; }
      const pad = (hi - lo) * 0.06 || hi * 0.01; lo -= pad; hi += pad;
      const Y = (v) => (1 - (v - lo) / (hi - lo)) * ph;
      geo = {X, Y, pw, ph, W, H, lo, hi, span};
      // grid + axes
      ctx.font = "11px system-ui, sans-serif"; ctx.textBaseline = "middle";
      const step = niceStep((hi - lo) / 6), yLast = Y(cs[cs.length - 1][4]);
      for (let v = Math.ceil(lo / step) * step; v < hi; v += step) {
        const y = Math.round(Y(v)) + 0.5; ctx.strokeStyle = C.grid; ctx.beginPath(); ctx.moveTo(0, y); ctx.lineTo(pw, y); ctx.stroke();
        if (Math.abs(y - yLast) > 14) { ctx.fillStyle = C.text; ctx.fillText(fmtP(v), pw + 6, y); }  // the last-price tag sits there
      }
      const every = Math.max(1, Math.round(span / Math.max(2, Math.floor(pw / 110))));
      ctx.textAlign = "center";
      for (let i = Math.ceil(st.i0 / every) * every; i <= st.i1; i += every) {
        if (i < 0 || i >= cs.length) continue;
        const x = Math.round(X(i)) + 0.5; ctx.strokeStyle = C.grid; ctx.beginPath(); ctx.moveTo(x, 0); ctx.lineTo(x, ph); ctx.stroke();
        ctx.fillStyle = C.text; ctx.fillText(fmtT(cs[i][0], st.tf), x, ph + 11);
      }
      ctx.textAlign = "left";
      // candles
      const cw = Math.max(1, pw / span * 0.7);
      for (let i = a; i <= b; i++) {
        const [, o, h, l, c] = cs[i], x = X(i), col = c >= o ? C.up : C.down;
        ctx.strokeStyle = col; ctx.fillStyle = col; ctx.lineWidth = 1;
        ctx.beginPath(); ctx.moveTo(Math.round(x) + 0.5, Y(h)); ctx.lineTo(Math.round(x) + 0.5, Y(l)); ctx.stroke();
        const y0 = Y(Math.max(o, c)), y1 = Y(Math.min(o, c));
        ctx.fillRect(x - cw / 2, y0, cw, Math.max(1, y1 - y0));
      }
      // last price
      const last = cs[cs.length - 1][4], yl = Y(last);
      if (yl > 0 && yl < ph) { ctx.setLineDash([2, 3]); ctx.strokeStyle = C.cross; ctx.beginPath(); ctx.moveTo(0, yl); ctx.lineTo(pw, yl); ctx.stroke(); ctx.setLineDash([]);
        ctx.fillStyle = "#2a313b"; ctx.fillRect(pw + 1, yl - 8, R - 2, 16); ctx.fillStyle = "#e6e9ed"; ctx.fillText(fmtP(last), pw + 6, yl); }
      // trades
      geo.marks = [];
      ctx.save(); ctx.beginPath(); ctx.rect(0, 0, pw, ph); ctx.clip();
      for (const t of trs) drawTrade(t, X, Y, cs.length);
      ctx.restore();
      // crosshair
      if (st.hover && !st.drag) {
        const {x, y} = st.hover;
        if (x < pw && y < ph) {
          ctx.setLineDash([3, 3]); ctx.strokeStyle = C.cross; ctx.beginPath(); ctx.moveTo(x + 0.5, 0); ctx.lineTo(x + 0.5, ph); ctx.moveTo(0, y + 0.5); ctx.lineTo(pw, y + 0.5); ctx.stroke(); ctx.setLineDash([]);
          const v = lo + (1 - y / ph) * (hi - lo); ctx.fillStyle = "#2a313b"; ctx.fillRect(pw + 1, y - 8, R - 2, 16); ctx.fillStyle = "#e6e9ed"; ctx.fillText(fmtP(v), pw + 6, y);
          const i = Math.round(st.i0 + x / pw * span - 0.5);
          if (i >= 0 && i < cs.length) { const k = cs[i];
            ohlc.innerHTML = `${esc(coin(st.pair))} · ${st.tf} · ${fmtT(k[0], "1h")} &nbsp; O <b>${fmtP(k[1])}</b> H <b>${fmtP(k[2])}</b> L <b>${fmtP(k[3])}</b> C <b class="${k[4] >= k[1] ? "pos" : "neg"}">${fmtP(k[4])}</b>`; }
        }
      } else ohlc.innerHTML = `${esc(coin(st.pair))} · ${st.tf}`;
      if (st.i0 < 30 && st.more && !st.loading) loadCandles(false);  // scrolled to the start: fetch older candles
    }
    function drawTrade(t, X, Y, n) {
      const hist = !!t.hist, x0 = X(idx(t.t0)), y0 = Y(+t.p0);
      const win = t.open ? +t.pnl >= 0 : (t.ret != null ? +t.ret >= 0 : +t.pnl >= 0);
      const col = t.open ? C.open : win ? C.up : C.down, a = hist ? 0.75 : 1;
      ctx.globalAlpha = a;
      let x1 = null, y1 = null;
      if (t.t1 && t.p1 != null) { x1 = X(idx(t.t1)); y1 = Y(+t.p1); }
      else if (t.open) { x1 = X(n - 1); y1 = Y(+t.p1 || +t.p0); }
      if (x1 != null) {
        ctx.strokeStyle = hist ? C.hist : col; ctx.lineWidth = hist ? 1.2 : 2; ctx.setLineDash(hist || t.open ? [5, 4] : []);
        ctx.beginPath(); ctx.moveTo(x0, y0); ctx.lineTo(x1, y1); ctx.stroke(); ctx.setLineDash([]);
      }
      if (t.open && t.stop) { const ys = Y(+t.stop); ctx.strokeStyle = C.down; ctx.setLineDash([2, 4]); ctx.lineWidth = 1; ctx.beginPath(); ctx.moveTo(x0, ys); ctx.lineTo(X(n - 1), ys); ctx.stroke(); ctx.setLineDash([]); }
      // entry triangle
      const s = hist ? 6 : 8, up = !t.short;
      ctx.beginPath();
      if (up) { ctx.moveTo(x0, y0); ctx.lineTo(x0 - s, y0 + s * 1.3); ctx.lineTo(x0 + s, y0 + s * 1.3); }
      else { ctx.moveTo(x0, y0); ctx.lineTo(x0 - s, y0 - s * 1.3); ctx.lineTo(x0 + s, y0 - s * 1.3); }
      ctx.closePath();
      if (hist) { ctx.lineWidth = 1.5; ctx.strokeStyle = up ? C.up : C.down; ctx.fillStyle = C.bg; ctx.fill(); ctx.stroke(); }
      else { ctx.fillStyle = up ? C.up : C.down; ctx.fill(); ctx.lineWidth = 1; ctx.strokeStyle = "#fff"; ctx.stroke(); }
      if (t.t1 && t.p1 != null) {
        ctx.beginPath(); ctx.arc(x1, y1, hist ? 3.5 : 5, 0, Math.PI * 2);
        if (hist) { ctx.lineWidth = 1.5; ctx.strokeStyle = col; ctx.fillStyle = C.bg; ctx.fill(); ctx.stroke(); }
        else { ctx.fillStyle = col; ctx.fill(); ctx.lineWidth = 1.2; ctx.strokeStyle = C.bg; ctx.stroke(); }
      }
      ctx.globalAlpha = 1;
      geo.marks.push({t, x: x0, y: y0}); if (x1 != null) geo.marks.push({t, x: x1, y: y1});
    }
    function niceStep(raw) { const p = Math.pow(10, Math.floor(Math.log10(raw || 1))), f = raw / p; return (f < 1.5 ? 1 : f < 3 ? 2 : f < 7 ? 5 : 10) * p; }

    // -------------------------------------------------------------- tooltip
    function tradeTip(t) {
      const L = (st.trades || {}).labels || {}, lb = L[t.sid] || {};
      const who = `${lb.code ? "#" + lb.code + " · " : ""}${esc(lb.method || t.sid || "")}`;
      const kind = t.hist ? "бэктест на истории" : t.open ? "демо · позиция открыта" : "демо";
      const res = t.hist ? (t.ret != null ? `${(t.ret * 100).toFixed(2)}%` : "—")
                         : `${t.pnl != null ? (+t.pnl >= 0 ? "+" : "") + (+t.pnl).toFixed(2) + " $" : "—"}${t.ret != null ? ` (${(t.ret * 100).toFixed(2)}%)` : ""}`;
      return `<b>${t.short ? "Шорт" : "Лонг"} ${esc(coin(st.pair))}</b> · ${kind}<br>${who}<br>
        Вход: ${fmtT(t.t0, "1h")} по <b>${fmtP(t.p0)}</b><br>` +
        (t.t1 ? `Выход: ${fmtT(t.t1, "1h")} по <b>${fmtP(t.p1)}</b> — ${esc(RS[t.why] || t.why || "")}<br>` : t.open ? `Сейчас: ${fmtP(t.p1)}${t.stop ? ` · стоп ${fmtP(t.stop)}` : ""}<br>` : "") +
        `Результат: <b class="${(t.hist ? +t.ret : +t.pnl) >= 0 ? "pos" : "neg"}">${res}</b>${t.before_experiment ? `<br><span class="dim">до начала эксперимента</span>` : ""}`;
    }
    function nearest(x, y) {
      let best = null, bd = 12 * 12;
      for (const m of geo?.marks || []) { const d = (m.x - x) ** 2 + (m.y - y) ** 2; if (d < bd) { bd = d; best = m; } }
      return best;
    }
    function showTip(m, x, y) {
      if (!m) { tip.style.display = "none"; return; }
      tip.innerHTML = tradeTip(m.t); tip.style.display = "block";
      const w = tip.offsetWidth, h = tip.offsetHeight, W = wrap.clientWidth;
      tip.style.left = Math.max(4, Math.min(x + 14, W - w - 4)) + "px"; tip.style.top = Math.max(4, y - h - 10 < 0 ? y + 14 : y - h - 10) + "px";
    }

    // -------------------------------------------------------------- interaction
    const pos = (e) => { const r = cv.getBoundingClientRect(); return {x: e.clientX - r.left, y: e.clientY - r.top}; };
    cv.addEventListener("mousemove", (e) => {
      const p = pos(e); st.hover = p;
      if (st.drag && geo) { const di = (p.x - st.drag.x) / geo.pw * geo.span; st.i0 = st.drag.i0 - di; st.i1 = st.drag.i1 - di; }
      draw(); if (!st.drag) showTip(nearest(p.x, p.y), p.x, p.y);
    });
    cv.addEventListener("mouseleave", () => { st.hover = null; st.drag = null; tip.style.display = "none"; draw(); });
    cv.addEventListener("mousedown", (e) => { const p = pos(e); st.drag = {x: p.x, i0: st.i0, i1: st.i1}; cv.style.cursor = "grabbing"; });
    addEventListener("mouseup", () => { st.drag = null; cv.style.cursor = "crosshair"; });
    cv.addEventListener("wheel", (e) => {
      if (!geo) return; e.preventDefault();
      const p = pos(e), at = st.i0 + Math.min(p.x, geo.pw) / geo.pw * geo.span, k = Math.exp(e.deltaY * 0.0015);
      const span = Math.max(15, Math.min(st.candles.length + 60, geo.span * k));
      st.i0 = at - (at - st.i0) * span / geo.span; st.i1 = st.i0 + span; draw();
    }, {passive: false});
    // touch: one finger scrolls, two fingers zoom, a tap shows the nearest trade
    let tch = null;
    cv.addEventListener("touchstart", (e) => {
      const ts = [...e.touches].map(pos);
      tch = {ts, i0: st.i0, i1: st.i1, moved: false};
    }, {passive: true});
    cv.addEventListener("touchmove", (e) => {
      if (!tch || !geo) return; e.preventDefault();
      const ts = [...e.touches].map(pos); tch.moved = true;
      if (ts.length === 1 && tch.ts.length === 1) { const di = (ts[0].x - tch.ts[0].x) / geo.pw * (tch.i1 - tch.i0); st.i0 = tch.i0 - di; st.i1 = tch.i1 - di; }
      else if (ts.length === 2 && tch.ts.length === 2) {
        const d0 = Math.abs(tch.ts[0].x - tch.ts[1].x) || 1, d1 = Math.abs(ts[0].x - ts[1].x) || 1, span = Math.max(15, (tch.i1 - tch.i0) * d0 / d1);
        const mid = tch.i0 + ((tch.ts[0].x + tch.ts[1].x) / 2) / geo.pw * (tch.i1 - tch.i0);
        st.i0 = mid - span / 2; st.i1 = mid + span / 2;
      }
      draw();
    }, {passive: false});
    cv.addEventListener("touchend", (e) => {
      if (tch && !tch.moved && tch.ts.length === 1) { const p = tch.ts[0]; showTip(nearest(p.x, p.y), p.x, p.y); }
      if (!e.touches.length) tch = null;
    });
    const ro = new ResizeObserver(() => draw()); ro.observe(wrap);
    cv.style.cursor = "crosshair";

    renderBar(); loadCandles(true); loadTrades();
    return {destroy() { alive = false; ro.disconnect(); el.innerHTML = ""; },
            refresh() { loadTrades(); }};
  }

  // shared styles, injected once
  const css = `.tc-bar{display:flex;flex-wrap:wrap;gap:6px 14px;align-items:center;margin-bottom:8px}
  .tc-grp{display:inline-flex;gap:3px;align-items:center;flex-wrap:wrap}.tc-l{font-size:11px;color:#8b95a1;margin-right:4px}
  .tc-bar button{background:#1b2129;border:1px solid #2a313b;color:#b8c0ca;font:inherit;font-size:12px;padding:3px 9px;border-radius:6px;cursor:pointer}
  .tc-bar button.on{border-color:#3987e5;color:#fff;background:#1d3150}.tc-note{font-size:11.5px;color:#8b95a1}
  .tc-wrap{position:relative;border-radius:8px;overflow:hidden;background:${C.bg}}.tc canvas{display:block;width:100%;touch-action:none}
  .tc-tip{position:absolute;display:none;z-index:5;background:#0f1216;border:1px solid #2f3742;border-radius:8px;padding:8px 10px;font-size:12.5px;line-height:1.5;color:#e6e9ed;max-width:320px;pointer-events:none;box-shadow:0 8px 24px rgba(0,0,0,.45)}
  .tc-ohlc{position:absolute;left:8px;top:6px;font-size:11.5px;color:#8b95a1;pointer-events:none}.tc-ohlc b{color:#e6e9ed;font-weight:600}.tc-ohlc .pos{color:${C.up}}.tc-ohlc .neg{color:${C.down}}
  .tc-tip .pos{color:${C.up}}.tc-tip .neg{color:${C.down}}.tc-tip .dim{color:#8b95a1}
  .tc-msg{position:absolute;inset:0;display:flex;align-items:center;justify-content:center;color:#8b95a1;font-size:13px;pointer-events:none}
  .tc-legend{font-size:11.5px;color:#8b95a1;margin-top:6px;line-height:1.5}`;
  const s = document.createElement("style"); s.textContent = css; document.head.appendChild(s);
  window.TChart = {mount};
})();
