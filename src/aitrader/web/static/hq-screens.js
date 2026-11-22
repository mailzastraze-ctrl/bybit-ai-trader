// AI Trader HQ — what everyone is doing on their computer. Each desk runs a small "app" with
// its own script (move the cursor, click, scroll, type); people's hands follow the app.
// Apps marked live draw the company's real data; world-market feeds are illustrative.
import * as THREE from "three";
import { S, D, fmt, coin, headlines, fgRu, STAGE_RU, VERDICT_RU, wantCandles } from "./hq-data.js";

// ------------------------------------------------------------------ drawing kit
const SANS = "Inter, system-ui, -apple-system, 'Segoe UI', sans-serif", MONO = "'JetBrains Mono', ui-monospace, Menlo, Consolas, monospace";
const f = (size, weight = 500, mono = false) => `${weight} ${size}px ${mono ? MONO : SANS}`;
export const T = {bg: "#0c1119", panel: "#131a25", panel2: "#19222f", line: "#223043", text: "#e9eef5", muted: "#8a9bb0", dim: "#5b697c",
  green: "#3ddc97", red: "#ff6b7a", amber: "#ffc15e", blue: "#6aa8ff", violet: "#a78bfa", cyan: "#5ad1e6", orange: "#ff9f43", pink: "#f48fb1"};
const clamp = (v, a, b) => Math.max(a, Math.min(b, v)), lerp = (a, b, t) => a + (b - a) * t;
const ease = t => t < 0.5 ? 2 * t * t : 1 - (-2 * t + 2) ** 2 / 2;
const rand = (a, b) => a + Math.random() * (b - a), pick = a => a[Math.floor(Math.random() * a.length)];
function txt(g, s, x, y, c = T.text, font = f(11), align = "left", maxW = 0) {
  g.fillStyle = c; g.font = font; g.textAlign = align; s = String(s ?? "");
  if (maxW && g.measureText(s).width > maxW) { while (s.length > 1 && g.measureText(s + "…").width > maxW) s = s.slice(0, -1); s += "…"; }
  g.fillText(s, x, y); return s;
}
function rr(g, x, y, w, h, r, fill, stroke, lw = 1) {
  g.beginPath(); g.roundRect ? g.roundRect(x, y, w, h, r) : g.rect(x, y, w, h);
  if (fill) { g.fillStyle = fill; g.fill(); }
  if (stroke) { g.strokeStyle = stroke; g.lineWidth = lw; g.stroke(); }
}
function chip(g, x, y, label, color, font = f(8.5, 700), align = "left") {
  g.font = font; const w = g.measureText(label).width + 10, X = align === "right" ? x - w : x;
  rr(g, X, y - 9, w, 12.5, 6, color + "26"); txt(g, label, X + 5, y, color, font); return w;
}
function wrap(g, s, x, y, maxW, lh, maxLines, c, font) {
  g.font = font; g.fillStyle = c; g.textAlign = "left";
  const words = String(s || "").split(" "); let line = "", n = 0;
  for (const w of words) {
    const t = line ? line + " " + w : w;
    if (g.measureText(t).width > maxW && line) { if (n === maxLines - 1) { txt(g, line + " " + w, x, y + n * lh, c, font, "left", maxW); return n + 1; } g.fillText(line, x, y + n * lh); line = w; n++; }
    else line = t;
  }
  if (line) g.fillText(line, x, y + n * lh);
  return n + 1;
}
function spark(g, pts, x, y, w, h, color, fill = true, lw = 1.5) {
  if (!pts || pts.length < 2) return;
  let lo = Infinity, hi = -Infinity; for (const v of pts) { if (v < lo) lo = v; if (v > hi) hi = v; }
  const r = hi - lo || 1, X = i => x + (i / (pts.length - 1)) * w, Y = v => y + h - ((v - lo) / r) * h;
  g.beginPath(); pts.forEach((v, i) => i ? g.lineTo(X(i), Y(v)) : g.moveTo(X(i), Y(v)));
  if (fill) { g.save(); g.lineTo(x + w, y + h); g.lineTo(x, y + h); g.closePath(); const gr = g.createLinearGradient(0, y, 0, y + h); gr.addColorStop(0, color + "55"); gr.addColorStop(1, color + "00"); g.fillStyle = gr; g.fill(); g.restore(); g.beginPath(); pts.forEach((v, i) => i ? g.lineTo(X(i), Y(v)) : g.moveTo(X(i), Y(v))); }
  g.strokeStyle = color; g.lineWidth = lw; g.lineJoin = "round"; g.stroke();
  return {X, Y, lo, hi};
}
function candles(g, rows, x, y, w, h, lines = [], opt = {}) {
  if (!rows || rows.length < 3) { txt(g, "загрузка свечей…", x + w / 2, y + h / 2, T.dim, f(10), "center"); return null; }
  let lo = Infinity, hi = -Infinity;
  for (const r of rows) { if (r[3] < lo) lo = r[3]; if (r[2] > hi) hi = r[2]; }
  for (const l of lines) { if (l.v < lo) lo = l.v; if (l.v > hi) hi = l.v; }
  const pad = (hi - lo) * 0.08 || 1; lo -= pad; hi += pad;
  const Y = v => y + h - ((v - lo) / (hi - lo)) * h, cw = w / rows.length;
  g.strokeStyle = "#ffffff0d"; g.lineWidth = 1;
  for (let k = 1; k < 4; k++) { g.beginPath(); g.moveTo(x, y + (h * k) / 4); g.lineTo(x + w, y + (h * k) / 4); g.stroke(); }
  rows.forEach((r, i) => {
    const [, o, hh, l, c] = r, up = c >= o, cx = x + i * cw + cw / 2;
    g.strokeStyle = up ? "#34c38f" : "#f46a6a"; g.beginPath(); g.moveTo(cx, Y(hh)); g.lineTo(cx, Y(l)); g.stroke();
    g.fillStyle = up ? "#34c38f" : "#f46a6a"; g.fillRect(cx - cw * 0.34, Y(Math.max(o, c)), Math.max(1, cw * 0.68), Math.max(1, Math.abs(Y(o) - Y(c))));
  });
  for (const l of lines) {
    g.strokeStyle = l.c; g.setLineDash([4, 3]); g.beginPath(); g.moveTo(x, Y(l.v)); g.lineTo(x + w, Y(l.v)); g.stroke(); g.setLineDash([]);
    if (opt.axis !== false) { rr(g, x + w + 2, Y(l.v) - 6, 30, 12, 3, l.c); txt(g, l.label, x + w + 17, Y(l.v) + 3.5, "#0c1119", f(7.5, 700), "center"); }
  }
  const last = rows.at(-1)[4];
  if (opt.axis !== false) { rr(g, x + w + 2, Y(last) - 6, 30, 12, 3, "#e9eef5"); txt(g, fmt.price(last).slice(0, 7), x + w + 17, Y(last) + 3.5, "#0c1119", f(7, 700), "center"); }
  return {Y, cw, lo, hi};
}
function cursorShape(g, c) {
  if (!c.visible) return;
  if (c.ripple > 0) { g.strokeStyle = `rgba(255,255,255,${c.ripple * 0.8})`; g.lineWidth = 1.5; g.beginPath(); g.arc(c.x, c.y, 4 + (1 - c.ripple) * 12, 0, 7); g.stroke(); }
  g.save(); g.translate(c.x, c.y);
  if (c.shape === "text") { g.strokeStyle = "#fff"; g.lineWidth = 1.2; g.beginPath(); g.moveTo(0, -6); g.lineTo(0, 6); g.moveTo(-2.5, -6); g.lineTo(2.5, -6); g.moveTo(-2.5, 6); g.lineTo(2.5, 6); g.stroke(); g.restore(); return; }
  g.beginPath(); g.moveTo(0, 0); g.lineTo(0, 13); g.lineTo(3.5, 9.8); g.lineTo(6.2, 15); g.lineTo(8.2, 14); g.lineTo(5.6, 9); g.lineTo(10, 9); g.closePath();
  g.fillStyle = "#fff"; g.fill(); g.strokeStyle = "#000"; g.lineWidth = 1; g.stroke(); g.restore();
}
function titleBar(g, W, title, accent, o = {}) {
  const h = o.h || 18, light = o.light;
  g.fillStyle = light ? "#e9ecf1" : "#0a0e15"; g.fillRect(0, 0, W, h);
  [T.red, T.amber, T.green].forEach((c, i) => { g.fillStyle = c; g.beginPath(); g.arc(9 + i * 10, h / 2, 3, 0, 7); g.fill(); });
  txt(g, title, 42, h / 2 + 3.5, light ? "#273142" : T.text, f(9, 600), "left", W - 120);
  const now = new Date();
  txt(g, fmt.time(now), W - 7, h / 2 + 3.5, light ? "#5b6575" : T.muted, f(8.5, 500, true), "right");
  if (o.live) { g.fillStyle = T.green; g.beginPath(); g.arc(W - 62, h / 2, 2.6, 0, 7); g.fill(); txt(g, "live", W - 57, h / 2 + 3, T.green, f(7.5, 700), "left"); }
  if (accent) { g.fillStyle = accent; g.fillRect(0, h - 1.5, W, 1.5); }
  return h;
}
function bgFill(g, W, H, c = T.bg) { g.fillStyle = c; g.fillRect(0, 0, W, H); }
function seeded(seed) { let s = seed; return () => ((s = (s * 16807) % 2147483647) - 1) / 2147483646; }

// ------------------------------------------------------------------ app base: a script of cursor moves, clicks, typing
export class App {
  constructor(W = 384, H = 240) {
    this.W = W; this.H = H; this.t = 0; this.seq = []; this.cur = null; this.mode = "read"; this.away = false; this.awayName = "";
    this.cursor = {x: W * 0.6, y: H * 0.6, down: 0, ripple: 0, visible: true, shape: "arrow"};
    this.title = ""; this.live = true; this.keys = 0; this.scrollKick = 0;
  }
  get cursorN() { return {x: this.cursor.x / this.W, y: this.cursor.y / this.H, down: this.cursor.down}; }
  move(x, y, d = 0.7) { this.seq.push({k: "move", x, y, d}); return this; }
  click(fn) { this.seq.push({k: "click", fn}); return this; }
  wait(d, mode = "read") { this.seq.push({k: "wait", d, mode}); return this; }
  type(text, onChar, speed = 13) { this.seq.push({k: "type", text, onChar, speed}); return this; }
  scroll(px, d = 1, fn) { this.seq.push({k: "scroll", px, d, fn}); return this; }
  call(fn) { this.seq.push({k: "call", fn}); return this; }
  plan() { this.wait(2); }
  update(dt) {
    this.t += dt;
    this.cursor.ripple = Math.max(0, this.cursor.ripple - dt * 2.5);
    this.tick?.(dt);
    if (this.away) { this.mode = "idle"; return; }
    if (!this.cur) { if (!this.seq.length) this.plan(); this.cur = this.seq.shift(); if (!this.cur) return; this.cur.t = 0; }
    const c = this.cur, cu = this.cursor; c.t += dt;
    let done = false;
    switch (c.k) {
      case "move": {
        if (!c.from) { c.from = {x: cu.x, y: cu.y}; c.bend = rand(-0.18, 0.18); }
        const k = ease(clamp(c.t / c.d, 0, 1)), dx = c.x - c.from.x, dy = c.y - c.from.y;
        cu.x = c.from.x + dx * k - dy * c.bend * Math.sin(k * Math.PI); cu.y = c.from.y + dy * k + dx * c.bend * Math.sin(k * Math.PI);
        this.mode = "mouse"; done = k >= 1; break;
      }
      case "click": if (!c.fired) { c.fired = true; cu.ripple = 1; c.fn?.(); } cu.down = c.t < 0.12 ? 1 : 0; this.mode = "mouse"; done = c.t > 0.3; break;
      case "wait": this.mode = c.mode; done = c.t >= c.d; break;
      case "type": {
        this.mode = "type"; c.n ??= 0; c.pause ??= 0;
        if (c.pause > 0) { c.pause -= dt; this.mode = "type-pause"; break; }
        const before = Math.floor(c.n); c.n += dt * c.speed * (0.6 + Math.random() * 0.8);
        for (let i = before; i < Math.min(Math.floor(c.n), c.text.length); i++) { c.onChar?.(c.text[i], i); this.keys++; if (c.text[i] === "\n" || (c.text[i] === " " && Math.random() < 0.05)) c.pause = rand(0.25, 0.9); }
        done = c.n >= c.text.length; break;
      }
      case "scroll": { const k = clamp(c.t / c.d, 0, 1), prev = c.done || 0; c.done = ease(k) * c.px; c.fn?.(c.done - prev); this.scrollKick = 1; this.mode = "scroll"; done = k >= 1; break; }
      case "call": c.fn(); done = true; break;
    }
    if (done) this.cur = null;
  }
  // overlay when the person is away from the desk
  paint(g) {
    this.draw(g, this.W, this.H);
    if (this.away) {
      g.fillStyle = "rgba(6,9,14,.72)"; g.fillRect(0, 0, this.W, this.H);
      const s = this.W / 384;
      txt(g, fmt.time(new Date()), this.W / 2, this.H / 2 - 4 * s, "#e9eef5", f(30 * s, 300), "center");
      txt(g, this.awayName ? `${this.awayName} · скоро вернётся` : "экран заблокирован", this.W / 2, this.H / 2 + 18 * s, T.muted, f(10 * s, 500), "center");
    } else if (this.showCursor !== false) cursorShape(g, this.cursor);
  }
}

// ------------------------------------------------------------------ 1. CEO: reading the report (light PDF viewer)
const GOAL_RU = {forward: "Форвард-тест на новых данных", readiness: "Готовность к реальным деньгам", validated: "Стратегия, прошедшая все проверки",
  evidence: "Доказательства: сделки на демо", research: "Эксперименты за 7 дней", pf: "Profit factor ≥ 1,3 (≥ 30 сделок)", production: "Стратегии в боевом режиме", return: "Рост капитала +10%"};
export const goalTitle = g => GOAL_RU[g.id] || g.title;
export const goalTarget = g => String(g.target ?? "").replace("trades", "сделок");
export const goalValue = g => ({works: "работает", no: "нет", unclear: "неясно"}[g.value] ?? (typeof g.value === "string" ? g.value.replace("trades", "сделок") : fmt.n(g.value, Number.isInteger(g.value) ? 0 : 2)));
export class ReportApp extends App {
  constructor() { super(); this.title = "Отчёт управляющему"; this.scrollY = 0; this.mark = null; this.marks = []; }
  plan() {
    const H = this.contentH || 600, maxS = Math.max(0, H - 200);
    this.move(rand(200, 320), rand(90, 200), 0.9).wait(rand(3, 5));
    if (Math.random() < 0.4) { const y = rand(70, 190); this.move(80, y, 0.6).call(() => { this.mark = {x0: 80, y: y + this.scrollY}; }).move(rand(200, 300), y, 1.1).call(() => { this.marks.push({...this.mark, x1: this.cursor.x}); this.mark = null; if (this.marks.length > 4) this.marks.shift(); }); }
    if (this.scrollY >= maxS - 1) this.scroll(-this.scrollY, 1.6, d => { this.scrollY = clamp(this.scrollY + d, 0, maxS); }).call(() => { this.marks = []; });
    else this.scroll(rand(60, 110), 1.4, d => { this.scrollY = clamp(this.scrollY + d, 0, maxS); });
  }
  draw(g, W, H) {
    bgFill(g, W, H, "#545b67");
    g.fillStyle = "#2b2f36"; g.fillRect(0, 0, W, 20);
    txt(g, "Отчёт_управляющему.pdf", 8, 13.5, "#e6e9ee", f(9, 600));
    txt(g, `стр. ${1 + Math.floor(this.scrollY / 220)} из 3   ·   110%`, W - 8, 13.5, "#aab2bf", f(8.5), "right");
    g.save(); g.beginPath(); g.rect(0, 20, W, H - 20); g.clip(); g.translate(0, 26 - this.scrollY);
    const x0 = 44, pw = W - 88;
    g.fillStyle = "rgba(0,0,0,.25)"; g.fillRect(x0 + 3, 3, pw, 640); g.fillStyle = "#fffdf9"; g.fillRect(x0, 0, pw, 640);
    // highlighter strokes
    g.fillStyle = "rgba(255,226,84,.55)";
    for (const m of this.marks) g.fillRect(m.x0, m.y - 26 - 8, m.x1 - m.x0, 10);
    if (this.mark) g.fillRect(this.mark.x0, this.mark.y - 26 - 8, this.cursor.x - this.mark.x0, 10);
    const L = x0 + 16, R = x0 + pw - 16; let y = 22;
    rr(g, L, y - 9, 10, 10, 2, "#1fb89a"); txt(g, "AI TRADER · отчёт управляющему", L + 15, y, "#1d2430", f(9, 700));
    txt(g, new Date().toLocaleDateString("ru-RU", {day: "numeric", month: "long"}), R, y, "#7b8494", f(8), "right");
    y += 22; const cap = D.capital(), eq = D.equity(), ret = eq.length > 1 ? eq.at(-1) / eq[0] - 1 : null;
    txt(g, "Капитал демо-счёта", L, y, "#6b7383", f(8)); y += 17;
    txt(g, cap ? fmt.n(cap, 0) + " USDT" : "—", L, y, "#111827", f(17, 700));
    if (ret !== null) txt(g, fmt.spct(ret, 2) + " с начала", R, y, ret >= 0 ? "#0f9d6b" : "#d6455a", f(9, 600), "right");
    y += 8; spark(g, eq.slice(-160), L, y, R - L, 34, ret === null || ret >= 0 ? "#1fb89a" : "#e2566a"); y += 48;
    const pr = S.ov?.profit || {}, rd = D.readiness();
    const kpi = [["Результат закрытых", fmt.signed(pr.profit_closed_coin ?? S.ov?.closed_pnl, 2) + " $"], ["Позиции", `${D.open().length} · ${fmt.signed(D.unrealised(), 1)} $`],
      ["Сделок закрыто", fmt.n(pr.closed_trade_count ?? S.ov?.closed_count)], ["Готовность", `${rd.passed ?? 0}/${rd.total ?? 10}`]];
    kpi.forEach(([k, v], i) => { const bx = L + (i % 2) * ((R - L) / 2 + 3), by = y + Math.floor(i / 2) * 34; rr(g, bx, by, (R - L) / 2 - 3, 29, 4, "#f2f0ea"); txt(g, k, bx + 6, by + 11, "#7b8494", f(7.5)); txt(g, v, bx + 6, by + 24, "#1d2430", f(10.5, 700)); });
    y += 80; txt(g, "Цели компании", L, y, "#1d2430", f(10, 700)); y += 6;
    for (const gl of (S.goals?.goals || []).slice(0, 6)) {
      y += 17; txt(g, goalTitle(gl), L, y, "#3b4352", f(8), "left", R - L - 50); txt(g, goalValue(gl), R, y, "#1d2430", f(8, 700), "right");
      rr(g, L, y + 3, R - L, 3, 1.5, "#e7e3da"); rr(g, L, y + 3, (R - L) * clamp(gl.progress || 0, 0, 1), 3, 1.5, gl.warning ? "#d6455a" : gl.progress >= 1 ? "#0f9d6b" : "#3b82f6");
    }
    y += 26; txt(g, "Выводы", L, y, "#1d2430", f(10, 700)); y += 14;
    const fw = D.goal("forward"), lab = S.rs?.lab || {};
    const notes = [
      `Форвард-тест: ${fw.note ? fw.note.slice(0, 120) : "данных пока мало — вердикт не раньше 90 дней."}`,
      `Лаборатория: ${D.goal("research").value ?? 0} экспериментов за неделю, запусков всего ${lab.runs ?? "—"}; ${D.labActive() ? "сейчас идёт прогон." : "ждёт следующий прогон."}`,
      `Риск: ${S.ov?.kill_switch ? "сработал аварийный стоп!" : "аварийный стоп не срабатывал"}, ${S.ov?.entries_paused ? "входы на паузе" : "входы разрешены"}; позиций ${D.open().length}.`,
    ];
    for (const n of notes) { y += wrap(g, n, L, y, R - L, 11, 4, "#3b4352", f(8)) * 11 + 6; }
    this.contentH = y + 40;
    g.restore();
    rr(g, W - 6, 24 + (this.scrollY / Math.max(1, this.contentH)) * (H - 40), 3, 30, 1.5, "#9aa3b0");
  }
}

// ------------------------------------------------------------------ 2. News: a live broadcast in the browser (headlines from real data)
const NEWS_DOTS = (() => { const r = seeded(9), out = []; for (let i = 0; i < 260; i++) { const a = r() * Math.PI * 2, d = Math.sqrt(r()); const x = 0.5 + Math.cos(a) * d * 0.46, y = 0.5 + Math.sin(a) * d * 0.3; if (Math.sin(x * 19) + Math.cos(y * 23) > -0.3) out.push([x, y]); } return out; })();
export function studio(g, x, y, w, h, t, head, sub = "") {
  g.save(); g.beginPath(); g.rect(x, y, w, h); g.clip();
  const gr = g.createLinearGradient(x, y, x + w, y + h); gr.addColorStop(0, "#08204a"); gr.addColorStop(1, "#14509c"); g.fillStyle = gr; g.fillRect(x, y, w, h);
  g.fillStyle = "rgba(140,200,255,.35)"; for (const [dx, dy] of NEWS_DOTS) { g.beginPath(); g.arc(x + w * 0.55 + (dx - 0.5) * w * 0.9, y + dy * h * 0.8, w * 0.004, 0, 7); g.fill(); }
  // studio screen with BTC (real candles) behind the anchor
  const sx = x + w * 0.6, sy = y + h * 0.12, sw = w * 0.34, sh = h * 0.36;
  rr(g, sx, sy, sw, sh, 3, "rgba(5,15,35,.7)", "rgba(140,200,255,.4)");
  const btc = D.candles("BTC/USDT:USDT");
  if (btc?.length > 10) { const cl = btc.slice(-48).map(r => r[4]), ch = cl.at(-1) / cl[0] - 1; spark(g, cl, sx + 4, sy + sh * 0.35, sw - 8, sh * 0.55, ch >= 0 ? "#3ddc97" : "#ff6b7a", true, Math.max(1, w * 0.004)); txt(g, `BTC ${fmt.spct(ch)}`, sx + 5, sy + sh * 0.25, "#fff", f(w * 0.026, 700)); }
  // anchor: desk, shoulders, head (bobbing), mouth moves while "talking"
  const ax = x + w * 0.3, bob = Math.sin(t * 1.3) * h * 0.006;
  g.fillStyle = "#1d2b44"; g.beginPath(); g.ellipse(ax, y + h * 0.86 + bob, w * 0.16, h * 0.2, 0, Math.PI, 0); g.fill();
  g.fillStyle = "#f1f4f8"; g.beginPath(); g.moveTo(ax - w * 0.03, y + h * 0.66 + bob); g.lineTo(ax, y + h * 0.76 + bob); g.lineTo(ax + w * 0.03, y + h * 0.66 + bob); g.fill();
  g.fillStyle = "#c2392b"; g.fillRect(ax - w * 0.006, y + h * 0.68 + bob, w * 0.012, h * 0.1);
  g.fillStyle = "#d9a07e"; g.fillRect(ax - w * 0.022, y + h * 0.58 + bob, w * 0.044, h * 0.08);
  g.beginPath(); g.ellipse(ax, y + h * 0.5 + bob, w * 0.055, h * 0.11, 0, 0, 7); g.fill();
  g.fillStyle = "#2b1d16"; g.beginPath(); g.ellipse(ax, y + h * 0.43 + bob, w * 0.06, h * 0.07, 0, Math.PI, 0); g.fill(); g.fillRect(ax - w * 0.06, y + h * 0.43 + bob, w * 0.015, h * 0.1);
  g.fillStyle = "#1b1b1b"; g.fillRect(ax - w * 0.022, y + h * 0.48 + bob, w * 0.01, h * 0.012); g.fillRect(ax + w * 0.012, y + h * 0.48 + bob, w * 0.01, h * 0.012);
  g.fillStyle = "#8a3b3b"; g.beginPath(); g.ellipse(ax, y + h * 0.565 + bob, w * 0.012, h * (0.004 + Math.abs(Math.sin(t * 9)) * 0.01), 0, 0, 7); g.fill();
  g.fillStyle = "#0b1426"; rr(g, x + w * 0.05, y + h * 0.78, w * 0.5, h * 0.25, 4, "#0b1426");
  // badges + lower third
  rr(g, x + w * 0.03, y + h * 0.05, w * 0.17, h * 0.09, 2, "#e0242f"); txt(g, "● ЭФИР", x + w * 0.115, y + h * 0.115, "#fff", f(w * 0.03, 800), "center");
  txt(g, "WN24", x + w - w * 0.03, y + h * 0.12, "rgba(255,255,255,.85)", f(w * 0.04, 800), "right");
  const ly = y + h * 0.7;
  g.fillStyle = "#ff8a00"; g.fillRect(x, ly, w * 0.2, h * 0.1); txt(g, (sub || "РЫНКИ").toUpperCase(), x + w * 0.1, ly + h * 0.07, "#111", f(w * 0.028, 800), "center");
  g.fillStyle = "rgba(255,255,255,.96)"; g.fillRect(x, ly + h * 0.1, w, h * 0.14);
  txt(g, head || "Мировые новости 24 — прямой эфир", x + w * 0.025, ly + h * 0.195, "#0b1426", f(w * 0.036, 700), "left", w * 0.95);
  g.restore();
}
function ticker(g, x, y, w, h, t, items, speed = 40, scale = 1) {
  g.save(); g.beginPath(); g.rect(x, y, w, h); g.clip(); g.fillStyle = "#0b1426"; g.fillRect(x, y, w, h);
  g.fillStyle = "#e0242f"; g.fillRect(x, y, 46 * scale, h); txt(g, "СРОЧНО", x + 23 * scale, y + h / 2 + 3.2 * scale, "#fff", f(8 * scale, 800), "center");
  const line = items.map(i => `${i.tag}: ${i.text}`).join("     •     ") || "—";
  g.font = f(9 * scale, 500); const lw = g.measureText(line).width + 60;
  const off = (t * speed * scale) % lw;
  for (let k = 0; k < 3; k++) txt(g, line, x + 52 * scale - off + k * lw, y + h / 2 + 3.2 * scale, "#e9eef5", f(9 * scale, 500));
  g.restore();
}
export class NewsApp extends App {
  constructor() { super(); this.title = "Новостной эфир"; this.sel = 0; this.items = []; }
  tick(dt) { this.acc = (this.acc || 0) + dt; if (this.acc > 5 || !this.items.length) { this.acc = 0; this.items = headlines(); } if (this.sel >= this.items.length) this.sel = 0; }
  plan() {
    const n = Math.max(1, Math.min(5, this.items.length)), next = (this.sel + 1) % n;
    this.wait(rand(5, 8)).move(300, 66 + next * 33, 0.8).click(() => { this.sel = next; });
    if (Math.random() < 0.3) this.move(rand(30, 230), rand(40, 150), 0.9).wait(rand(2, 3));
  }
  draw(g, W, H) {
    bgFill(g, W, H, "#f3f4f6");
    g.fillStyle = "#dfe3e8"; g.fillRect(0, 0, W, 21);
    rr(g, 46, 4, 210, 13, 6.5, "#fff"); txt(g, "🔒 news24.live/эфир", 54, 13.6, "#4a5260", f(8));
    [T.red, T.amber, T.green].forEach((c, i) => { g.fillStyle = c; g.beginPath(); g.arc(9 + i * 10, 10.5, 3, 0, 7); g.fill(); });
    const head = this.items[this.sel];
    studio(g, 8, 27, 236, 133, this.t, head?.text, head?.tag);
    txt(g, head?.text || "", 8, 175, "#111827", f(10.5, 700), "left", 236);
    txt(g, `Мировые новости 24 · ${fmt.time(new Date())} · ${head?.tag || ""}`, 8, 189, "#6b7383", f(8));
    txt(g, "Главное", 252, 38, "#111827", f(10.5, 800));
    this.items.slice(0, 5).forEach((it, i) => {
      const y = 46 + i * 33, on = i === this.sel;
      rr(g, 250, y, 128, 30, 4, on ? "#e8eefc" : "#fff", on ? "#3b82f6" : "#e3e6ea");
      txt(g, it.tag.toUpperCase(), 255, y + 10, on ? "#2563eb" : "#d6455a", f(6.5, 800));
      wrap(g, it.text, 255, y + 19.5, 118, 8.5, 2, "#1d2430", f(7.2, 600));
    });
    ticker(g, 0, H - 17, W, 17, this.t, this.items);
  }
}
export class NewsWallApp extends App {
  constructor() { super(640, 360); this.title = "Новостная стена"; this.sel = 0; this.items = []; this.showCursor = false; }
  tick(dt) { this.acc = (this.acc || 0) + dt; if (!this.items.length || this.acc > 9) { this.items = headlines(); if (this.acc > 9) { this.acc = 0; this.sel = (this.sel + 1) % Math.max(1, this.items.length); } } }
  plan() { this.wait(60); }
  draw(g, W, H) { const h = this.items[this.sel % Math.max(1, this.items.length)]; studio(g, 0, 0, W, H - 28, this.t, h?.text, h?.tag); ticker(g, 0, H - 28, W, 28, this.t, this.items, 40, 1.6); }
}

// ------------------------------------------------------------------ 3. Macro: world indices (illustrative feed; BTC row is real)
const WATCH = [["S&P 500", 0.0006, 0.0011], ["Nasdaq 100", 0.0008, 0.0015], ["Dow Jones", 0.0004, 0.0009], ["DAX", 0.0003, 0.001], ["Nikkei 225", -0.0002, 0.0012],
  ["Золото", 0.0002, 0.0008], ["Нефть Brent", -0.0004, 0.0016], ["Индекс доллара", -0.0001, 0.0004], ["UST 10Y", 0.0001, 0.0007], ["BTC", 0, 0]];
export class MacroApp extends App {
  constructor() {
    super(); this.title = "Мировые рынки"; this.live = "mixed"; this.sel = 0; this.range = 0; this.acc = 0;
    this.series = WATCH.map(([, mu, sd], i) => { const r = seeded(101 + i * 7), out = [0]; for (let k = 1; k < 90; k++) out.push(out[k - 1] + mu + (r() - 0.5) * 2 * sd * 1.7); return out; });
  }
  tick(dt) {
    this.acc += dt;
    if (this.acc > 1.5) { this.acc = 0; this.series.forEach((s, i) => { if (i === 9) return; const [, mu, sd] = WATCH[i]; s.push(s.at(-1) + mu * 0.3 + (Math.random() - 0.5) * 2 * sd); if (s.length > 90) s.shift(); }); }
    const btc = D.candles("BTC/USDT:USDT"); if (btc?.length > 30) { const cl = btc.slice(-72).map(r => r[4]); this.series[9] = cl.map(v => v / cl[0] - 1); }
  }
  plan() {
    this.move(rand(150, 360), rand(60, 180), 0.9).move(rand(150, 360), rand(60, 180), 2.2).wait(rand(1.5, 3));
    if (Math.random() < 0.6) { const i = Math.floor(Math.random() * WATCH.length); this.move(60, 36 + i * 19, 0.8).click(() => { this.sel = i; }); }
    else { const r = Math.floor(Math.random() * 3); this.move(300 + r * 26, 31, 0.7).click(() => { this.range = r; }); }
  }
  draw(g, W, H) {
    bgFill(g, W, H, "#06080c"); titleBar(g, W, "Мировые рынки · индексы, сырьё, ставки", T.orange);
    WATCH.forEach(([name], i) => {
      const y = 22 + i * 19, s = this.series[i], ch = s.at(-1) - s[0], on = i === this.sel;
      if (on) rr(g, 2, y, 128, 18, 3, "#1b2330");
      txt(g, name, 7, y + 12, on ? "#fff" : "#c7d0dc", f(8.5, on ? 700 : 500), "left", 62);
      spark(g, s.slice(-40), 70, y + 4, 26, 10, ch >= 0 ? "#3ddc97" : "#ff6b7a", false, 1);
      txt(g, fmt.spct(ch, 2), 127, y + 12, ch >= 0 ? T.green : T.red, f(8.5, 700, true), "right");
    });
    const s = this.series[this.sel], ch = s.at(-1) - s[0], X0 = 140, Y0 = 44, CW = 236, CH = 150;
    txt(g, WATCH[this.sel][0], X0, 36, "#fff", f(13, 800)); txt(g, fmt.spct(ch, 2), X0 + 4 + g.measureText(WATCH[this.sel][0]).width + 6, 36, ch >= 0 ? T.green : T.red, f(11, 700, true));
    ["1Д", "5Д", "1М"].forEach((r, i) => { rr(g, 290 + i * 26, 24, 22, 13, 3, i === this.range ? T.orange : "#1b2330"); txt(g, r, 301 + i * 26, 33.5, i === this.range ? "#111" : "#9aa7b8", f(8, 700), "center"); });
    const view = s.slice(-[90, 70, 50][this.range] || -90);
    g.strokeStyle = "#ffffff10"; for (let k = 0; k <= 4; k++) { g.beginPath(); g.moveTo(X0, Y0 + (CH * k) / 4); g.lineTo(X0 + CW, Y0 + (CH * k) / 4); g.stroke(); }
    const sp = spark(g, view, X0, Y0, CW, CH, ch >= 0 ? "#3ddc97" : "#ff6b7a", true, 1.8);
    const cx = this.cursor.x;
    if (sp && cx > X0 && cx < X0 + CW) {
      const i = Math.round(((cx - X0) / CW) * (view.length - 1)), v = view[i];
      g.strokeStyle = "#ffffff55"; g.setLineDash([3, 3]); g.beginPath(); g.moveTo(cx, Y0); g.lineTo(cx, Y0 + CH); g.stroke(); g.setLineDash([]);
      g.fillStyle = "#fff"; g.beginPath(); g.arc(sp.X(i), sp.Y(v), 2.8, 0, 7); g.fill();
      rr(g, clamp(cx - 30, X0, X0 + CW - 60), Y0 + 2, 60, 14, 3, "#1b2330"); txt(g, fmt.spct(v, 2), clamp(cx, X0 + 30, X0 + CW - 30), Y0 + 12, "#fff", f(8, 700, true), "center");
    }
    const ev = D.nextEvent();
    rr(g, X0, 202, CW, 30, 4, "#11161f");
    txt(g, "Календарь ФРС / США", X0 + 7, 214, T.orange, f(7.5, 700));
    txt(g, ev ? `${ev.name} — через ${fmt.until(ev.ts)}` : "ближайших событий нет", X0 + 7, 226, "#e9eef5", f(8.5, 600), "left", CW - 14);
  }
}

// ------------------------------------------------------------------ 4. Sentiment: social feed (fictional posts) + real crowd gauges
const POSTS = [["@onchain_ru", "Фандинг по SOL снова ниже нуля — шорты платят лонгам"], ["@macro_owl", "Перед решением ФРС рынок осторожничает, объёмы падают"], ["@deribit_flow", "Опционы на BTC: спрос на путы растёт третий день"],
  ["@whale_alert_ru", "Крупный перевод BTC на биржу — следим за реакцией"], ["@alt_season", "ETH/BTC пытается развернуться, но пока без объёма"], ["@quant_cat", "Моментум на 4ч всё ещё сильнее среднего возврата"],
  ["@risk_first", "Не забывайте про стопы: волатильность растёт"], ["@liq_map", "Над рынком скопились ликвидации шортов"], ["@dex_daily", "Объёмы на DEX выросли на 18% за неделю"], ["@funding_bot", "Средний фандинг по альтам вернулся к нулю"]];
const AV = ["#f59e0b", "#10b981", "#6366f1", "#ef4444", "#06b6d4", "#a855f7", "#84cc16", "#f97316"];
export class SentimentApp extends App {
  constructor() { super(); this.title = "Пульс рынка"; this.live = "mixed"; this.feed = []; this.off = 0; this.liked = new Set(); for (let i = 0; i < 6; i++) this.push(); this.nextPost = 4; }
  push() { const [h, t] = pick(POSTS); this.feed.unshift({h, t, c: pick(AV), ago: 0, likes: Math.floor(rand(3, 240)), id: Math.random()}); if (this.feed.length > 9) this.feed.pop(); this.off = -48; }
  tick(dt) { this.off = Math.min(0, this.off + dt * 120); this.nextPost -= dt; if (this.nextPost < 0) { this.push(); this.nextPost = rand(5, 9); } this.feed.forEach(p => p.ago += dt); }
  plan() {
    this.wait(rand(2, 4)).scroll(40, 0.8);
    if (Math.random() < 0.5) { const i = Math.floor(rand(0, 3)); this.move(176, 64 + i * 48, 0.7).click(() => { const p = this.feed[i]; if (p) { this.liked.add(p.id); p.likes++; } }); }
    this.move(rand(240, 360), rand(60, 150), 0.9).wait(rand(2, 3));
  }
  draw(g, W, H) {
    bgFill(g, W, H, "#0d0b16"); titleBar(g, W, "Пульс рынка · соцсети и толпа", T.violet);
    g.save(); g.beginPath(); g.rect(0, 19, 210, H - 19); g.clip();
    this.feed.forEach((p, i) => {
      const y = 24 + i * 48 + this.off; if (y > H) return;
      rr(g, 5, y, 200, 44, 5, "#171427");
      g.fillStyle = p.c; g.beginPath(); g.arc(18, y + 13, 8, 0, 7); g.fill(); txt(g, p.h[1].toUpperCase(), 18, y + 16, "#fff", f(8, 800), "center");
      txt(g, p.h, 31, y + 11, "#e9e6f5", f(8, 700)); txt(g, p.ago < 60 ? "сейчас" : `${Math.round(p.ago / 60)} мин`, 200, y + 11, "#7d7896", f(7), "right");
      wrap(g, p.t, 31, y + 22, 168, 9, 2, "#c9c4dd", f(7.6));
      const on = this.liked.has(p.id); txt(g, `${on ? "♥" : "♡"} ${p.likes}`, 176, y + 41, on ? "#ff5d8f" : "#7d7896", f(7.5, 700));
    });
    g.restore();
    const fg = S.ctx?.fear_greed, cx = 296, cy = 92, r = 52;
    txt(g, "Страх и жадность", 216, 32, "#cfc9e6", f(8.5, 700)); if (fg) chip(g, 378, 32, "live", T.green, f(7, 700), "right");
    const segs = ["#e5484d", "#f08c46", "#f5c451", "#9bd25b", "#3ddc97"];
    segs.forEach((c, i) => { g.strokeStyle = c; g.lineWidth = 9; g.beginPath(); g.arc(cx, cy, r, Math.PI + (i * Math.PI) / 5 + 0.03, Math.PI + ((i + 1) * Math.PI) / 5 - 0.03); g.stroke(); });
    const v = fg ? fg.value : 50, a = Math.PI + (v / 100) * Math.PI + Math.sin(this.t * 2) * 0.01;
    g.strokeStyle = "#fff"; g.lineWidth = 2.2; g.beginPath(); g.moveTo(cx, cy); g.lineTo(cx + Math.cos(a) * (r - 10), cy + Math.sin(a) * (r - 10)); g.stroke(); g.fillStyle = "#fff"; g.beginPath(); g.arc(cx, cy, 3.5, 0, 7); g.fill();
    txt(g, fg ? String(fg.value) : "—", cx, cy + 20, "#fff", f(17, 800), "center"); txt(g, fg ? fgRu(fg.label) : "нет данных", cx, cy + 32, "#a7a1c2", f(8), "center");
    txt(g, "Лонг/шорт на Bybit", 216, 146, "#cfc9e6", f(8.5, 700));
    const ls = S.ctx?.long_short || {};
    ["BTC", "ETH", "SOL"].forEach((c, i) => { const y = 154 + i * 17, l = ls[c]; txt(g, c, 216, y + 9, "#cfc9e6", f(8, 700)); rr(g, 240, y + 1, 136, 10, 3, "#3a1f2a"); if (l) { rr(g, 240, y + 1, 136 * l / 100, 10, 3, "#2f9e6e"); txt(g, `${fmt.n(l, 0)}%`, 244, y + 9, "#fff", f(7.5, 700)); } else txt(g, "—", 244, y + 9, "#aaa", f(7.5)); });
    const dv = S.ctx?.dvol;
    txt(g, "DVOL (опционы BTC)", 216, 222, "#cfc9e6", f(8, 700)); txt(g, dv ? `${fmt.n(dv.value, 1)} · ${dv.pct30}-й %` : "—", 378, 222, "#fff", f(8.5, 700, true), "right");
  }
}

// ------------------------------------------------------------------ 5. Trader: real candles of the desk's strategies, entry / stop / target
function mySleeves(slot, n) { const all = D.sleeves(); return all.filter((_, i) => i % n === slot); }
function pairsFor(sleeves) { const open = D.open(), out = []; for (const s of sleeves) { const t = open.find(x => x.enter_tag === s.id); const p = t ? t.pair : s.pairs[0]; if (p && !out.includes(p)) out.push(p); } return out; }
function tradeLines(t, sl) {
  if (!t) return [];
  const dir = t.is_short ? -1 : 1, isl = Number(t.initial_stop_loss_abs || t.stop_loss_abs), rr_ = Number(sl?.params?.tp_rr || sl?.params?.lab_tp || 2), out = [{v: t.open_rate, c: "#9fdbf1", label: "вход"}, {v: t.stop_loss_abs, c: "#ff6b7a", label: "стоп"}];
  if (isl && t.open_rate && rr_ > 0) out.push({v: t.open_rate + dir * rr_ * Math.abs(t.open_rate - isl), c: "#3ddc97", label: "цель"});
  return out;
}
export class TraderApp extends App {
  constructor(slot = 0, of = 2, owner = "") { super(); this.slot = slot; this.of = of; this.title = "Торговый терминал"; this.tab = 0; this.owner = owner; }
  get pairs() { const p = pairsFor(mySleeves(this.slot, this.of)).slice(0, 4); return p.length ? p : ["BTC/USDT:USDT"]; }
  plan() {
    const P = this.pairs;
    this.move(rand(120, 250), rand(70, 170), 0.8).move(rand(200, 262), rand(70, 170), 1.8).wait(rand(2, 4));
    if (P.length > 1 && Math.random() < 0.7) { const n = (this.tab + 1) % P.length; this.move(30 + n * 62, 30, 0.8).click(() => { this.tab = n; }); }
    else this.move(340, 150, 0.8).click().wait(rand(1.5, 2.5));
  }
  draw(g, W, H) {
    bgFill(g, W, H); titleBar(g, W, `Терминал · стратегии: ${this.owner}`, T.green, {live: true});
    const P = this.pairs, pair = P[this.tab % Math.max(1, P.length)];
    P.forEach((p, i) => { const on = p === pair; txt(g, coin(p), 30 + i * 62, 33, on ? "#fff" : T.muted, f(9, on ? 700 : 500), "center"); if (on) { g.fillStyle = T.green; g.fillRect(8 + i * 62, 37, 44, 2); } });
    if (!pair) { txt(g, "Стратегий за этим столом пока нет", W / 2, H / 2, T.muted, f(11), "center"); return; }
    wantCandles(pair);
    const sleeves = mySleeves(this.slot, this.of), pos = D.open().find(t => t.pair === pair), sl = sleeves.find(s => s.id === pos?.enter_tag) || sleeves.find(s => s.pairs.includes(pair));
    const rows = D.candles(pair)?.slice(-56), geo = candles(g, rows, 6, 46, 258, 150, tradeLines(pos, sl));
    const cx = this.cursor.x, cy = this.cursor.y;
    if (geo && rows && cx > 6 && cx < 264 && cy > 46 && cy < 196) {
      const i = clamp(Math.floor((cx - 6) / geo.cw), 0, rows.length - 1), r = rows[i];
      g.strokeStyle = "#ffffff40"; g.setLineDash([2, 3]); g.beginPath(); g.moveTo(cx, 46); g.lineTo(cx, 196); g.moveTo(6, cy); g.lineTo(264, cy); g.stroke(); g.setLineDash([]);
      txt(g, `O ${fmt.price(r[1])}  H ${fmt.price(r[2])}  L ${fmt.price(r[3])}  C ${fmt.price(r[4])}`, 9, 56, "#c7d0dc", f(7, 500, true));
    }
    const X = 304; rr(g, X, 46, 74, 150, 5, T.panel);
    if (pos) {
      chip(g, X + 6, 60, pos.is_short ? "ШОРТ" : "ЛОНГ", pos.is_short ? T.red : T.green);
      [["Вход", fmt.price(pos.open_rate)], ["Стоп", fmt.price(pos.stop_loss_abs)], ["Сейчас", fmt.price(D.lastPrice(pair))]].forEach(([k, v], i) => { txt(g, k, X + 6, 80 + i * 22, T.muted, f(7.5)); txt(g, v, X + 6, 90 + i * 22, T.text, f(8.5, 700, true)); });
      const pnl = Number(pos.profit_abs || 0); txt(g, "P&L", X + 6, 150, T.muted, f(7.5)); txt(g, fmt.signed(pnl, 2) + " $", X + 6, 164, pnl >= 0 ? T.green : T.red, f(11, 800, true));
      rr(g, X + 6, 174, 62, 15, 4, "#22303f"); txt(g, "обновить", X + 37, 184.5, "#c7d0dc", f(7.5, 600), "center");
    } else {
      txt(g, "Позиции нет", X + 6, 62, T.text, f(8.5, 700));
      wrap(g, "Ждём сигнал стратегии — вход только по правилам, со стопом на бирже.", X + 6, 76, 62, 9.5, 5, T.muted, f(7.2));
      if (sl) { txt(g, sl.family, X + 6, 140, T.cyan, f(7.5, 700), "left", 62); txt(g, `риск ${fmt.pct(sl.risk, 2)}`, X + 6, 152, T.muted, f(7.5)); txt(g, STAGE_RU[sl.stage] || sl.stage, X + 6, 164, T.amber, f(7.5, 700)); }
    }
    const n = sleeves.length, inMkt = sleeves.filter(s => D.open().some(t => t.enter_tag === s.id)).length;
    rr(g, 6, 202, 372, 32, 5, T.panel);
    txt(g, `${n} стратегий за столом · в рынке ${inMkt}`, 13, 215, T.text, f(8.5, 700));
    txt(g, sleeves.slice(0, 6).map(s => coin(s.pairs[0])).join(" · "), 13, 228, T.muted, f(8, 500, true), "left", 350);
  }
}
export class StrategiesApp extends App {
  constructor(slot = 0, of = 2) { super(); this.slot = slot; this.of = of; this.title = "Мои стратегии"; this.showCursor = false; this.hi = 0; }
  plan() { this.wait(3).call(() => { this.hi++; }); }
  draw(g, W, H) {
    bgFill(g, W, H); titleBar(g, W, "Мои стратегии", T.cyan, {live: true});
    const list = mySleeves(this.slot, this.of);
    txt(g, `${list.length} стратегий`, 8, 33, T.muted, f(8.5, 600));
    list.slice(0, 9).forEach((s, i) => {
      const y = 40 + i * 21, st = D.strategy(s.id)?.live || {}, on = i === this.hi % Math.max(1, Math.min(9, list.length));
      rr(g, 5, y, W - 10, 19, 4, on ? "#1d2a3a" : T.panel);
      txt(g, s.family, 11, y + 13, T.text, f(8.5, 600), "left", 120);
      txt(g, s.pairs.slice(0, 3).map(coin).join(" "), 140, y + 13, T.muted, f(8, 500, true), "left", 90);
      chip(g, 240, y + 13, STAGE_RU[s.stage] || s.stage, s.stage === "production" ? T.green : s.stage === "incubation" ? T.blue : T.amber, f(7, 700));
      txt(g, st.trades ? `${st.trades} сд · PF ${fmt.n(st.profit_factor, 2)}` : "нет сделок", W - 10, y + 13, st.trades ? T.text : T.dim, f(7.5, 600, true), "right");
    });
  }
}

// ------------------------------------------------------------------ 6. Order book around the real last price (depth illustrative) + tape
export class DomApp extends App {
  constructor(slot = 1, of = 2) { super(); this.slot = slot; this.of = of; this.title = "Стакан и лента"; this.live = "mixed"; this.tab = 0; this.sizes = Array.from({length: 24}, () => rand(0.2, 9)); this.tape = []; this.acc = 0; this.hot = -1; }
  get pairs() { const p = pairsFor(mySleeves(this.slot, this.of)).slice(0, 3); return p.length ? p : ["ETH/USDT:USDT"]; }
  tick(dt) {
    this.acc += dt;
    if (this.acc > 0.35) {
      this.acc = 0; this.sizes = this.sizes.map(s => clamp(s * (0.85 + Math.random() * 0.3) + (Math.random() < 0.08 ? rand(2, 8) : 0), 0.1, 14));
      const p = this.price(); if (p) { this.tape.unshift({p: p * (1 + (Math.random() - 0.5) * 0.0008), q: rand(0.01, 3), up: Math.random() < 0.5, t: new Date()}); if (this.tape.length > 12) this.tape.pop(); }
    }
  }
  price() { const pair = this.pairs[this.tab % Math.max(1, this.pairs.length)]; return D.lastPrice(pair) || D.open().find(t => t.pair === pair)?.open_rate || null; }
  plan() {
    const lv = Math.floor(rand(2, 22)); this.move(70, 32 + lv * 8.2, 0.7).call(() => { this.hot = lv; }).wait(rand(1, 2), "read").click().wait(rand(1.5, 3));
    if (this.pairs.length > 1 && Math.random() < 0.5) { const n = (this.tab + 1) % this.pairs.length; this.move(200 + n * 50, 30, 0.8).click(() => { this.tab = n; }); }
    else this.move(rand(190, 370), rand(50, 120), 1).wait(2);
  }
  draw(g, W, H) {
    bgFill(g, W, H, "#0a0d13"); titleBar(g, W, "Стакан · лента сделок", T.blue);
    const P = this.pairs, pair = P[this.tab % Math.max(1, P.length)];
    if (!pair) { txt(g, "Нет стратегий за этим столом", W / 2, H / 2, T.muted, f(11), "center"); return; }
    wantCandles(pair);
    const px = this.price() || 100, step = Math.pow(10, Math.floor(Math.log10(px)) - 3) * 2.5;
    txt(g, "Цена", 8, 32, T.dim, f(7)); txt(g, "Объём", 160, 32, T.dim, f(7), "right");
    for (let i = 0; i < 24; i++) {
      const ask = i < 12, k = ask ? 12 - i : i - 11, p = px + (ask ? k : -k) * step, y = 36 + i * 8.2 + (ask ? 0 : 12), q = this.sizes[i];
      if (i === this.hot) rr(g, 4, y - 1, 162, 8.6, 2, "#1f2a3b");
      g.fillStyle = ask ? "rgba(255,107,122,.18)" : "rgba(61,220,151,.18)"; g.fillRect(166 - q * 9, y, q * 9, 7.2);
      txt(g, fmt.price(p), 8, y + 6.4, ask ? "#ff8a96" : "#5ee6a8", f(7, 600, true)); txt(g, q.toFixed(2), 162, y + 6.4, "#c7d0dc", f(7, 500, true), "right");
    }
    rr(g, 4, 133, 162, 12, 3, "#151c28"); txt(g, fmt.price(px), 8, 142, "#fff", f(8.5, 800, true)); txt(g, coin(pair) + "/USDT", 162, 142, T.muted, f(7, 600), "right");
    P.forEach((p, i) => { const on = p === pair; txt(g, coin(p), 200 + i * 50, 33, on ? "#fff" : T.muted, f(8.5, on ? 700 : 500), "center"); if (on) { g.fillStyle = T.blue; g.fillRect(184 + i * 50, 36, 32, 2); } });
    candles(g, D.candles(pair)?.slice(-40), 176, 44, 168, 78, [], {axis: true});
    txt(g, "Лента", 178, 138, T.muted, f(7.5, 700));
    this.tape.slice(0, 9).forEach((x, i) => { const y = 148 + i * 9.5; txt(g, fmt.price(x.p), 178, y, x.up ? "#5ee6a8" : "#ff8a96", f(7.2, 600, true)); txt(g, x.q.toFixed(3), 300, y, "#c7d0dc", f(7.2, 500, true), "right"); txt(g, x.t.toLocaleTimeString("ru-RU"), 376, y, T.dim, f(6.8, 500, true), "right"); });
  }
}
const MISS_RU = {pair_busy: "монета занята", same_candle: "два сигнала на свече", paused: "пауза", side_count: "лимит на сторону", explore_count: "лимит разведки", open_risk: "лимит риска", side_risk: "риск стороны", explore_risk: "риск разведки", not_entered: "не вошёл"};
export class SignalsApp extends App {
  constructor() { super(); this.title = "Сигналы и исполнение"; this.showCursor = false; }
  plan() { this.wait(5); }
  draw(g, W, H) {
    bgFill(g, W, H); titleBar(g, W, "Сигналы за 7 дней", T.blue, {live: true});
    const sg = S.ov?.signals, ex = S.ov?.exposure || {};
    if (!sg?.signals) { wrap(g, "Журнал сигналов собирается — цифры появятся с первыми сигналами стратегий.", 12, 50, W - 24, 14, 3, T.muted, f(10)); }
    else {
      const k = sg.executed / sg.signals;
      txt(g, String(sg.signals), 14, 60, "#fff", f(26, 800)); txt(g, "сигналов", 14, 74, T.muted, f(8.5));
      txt(g, fmt.pct(k, 0), 130, 60, T.green, f(26, 800)); txt(g, `исполнено (${sg.executed})`, 130, 74, T.muted, f(8.5));
      Object.entries(sg.missed || {}).sort((a, b) => b[1] - a[1]).slice(0, 5).forEach(([r, n], i) => { const y = 96 + i * 18, w = (n / sg.signals) * 250; txt(g, MISS_RU[r] || r, 14, y + 9, "#c7d0dc", f(8)); rr(g, 120, y + 1, 250, 10, 3, "#1b2330"); rr(g, 120, y + 1, Math.max(2, w), 10, 3, T.amber); txt(g, n, 374, y + 9, "#fff", f(7.5, 700), "right"); });
    }
    const cl = D.closed().slice(0, 3);
    if (sg?.signals && cl.length) { txt(g, "ПОСЛЕДНИЕ ИСПОЛНЕНИЯ", 14, 160, T.dim, f(6.8, 700)); cl.forEach((t, i) => { const y = 172 + i * 8.4, p = Number(t.profit_abs || 0); txt(g, `${coin(t.pair)} · ${t.is_short ? "шорт" : "лонг"}`, 14, y, "#c7d0dc", f(7.2, 600)); txt(g, ({stop_loss: "стоп", trailing_stop_loss: "трейлинг-стоп", roi: "тейк", exit_signal: "сигнал выхода", force_exit: "вручную"})[t.exit_reason] || t.exit_reason || "", 120, y, T.muted, f(7)); txt(g, fmt.signed(p, 2) + " $", 374, y, p >= 0 ? T.green : T.red, f(7.2, 700), "right"); }); }
    rr(g, 8, 196, W - 16, 36, 5, T.panel);
    txt(g, "Независимых ставок", 16, 210, T.muted, f(8)); txt(g, ex.eff_bets != null ? "≈" + fmt.n(ex.eff_bets, 1) : "—", 16, 226, "#fff", f(11, 800));
    txt(g, "Риск в одну сторону", 200, 210, T.muted, f(8)); txt(g, ex.one_side_share != null ? fmt.pct(ex.one_side_share, 0) : "—", 200, 226, ex.one_side_share > 0.8 ? T.amber : "#fff", f(11, 800));
  }
}

// ------------------------------------------------------------------ 7. Blotter: every open position (real)
export class BlotterApp extends App {
  constructor() { super(); this.title = "Открытые позиции"; this.sel = 0; }
  plan() {
    const n = D.open().length;
    if (!n) { this.move(rand(100, 300), rand(80, 180), 1).wait(rand(3, 5)); return; }
    const i = (this.sel + 1) % Math.min(n, 8);
    this.move(rand(40, 330), 52 + i * 15, 0.7).click(() => { this.sel = i; }).wait(rand(2.5, 4));
  }
  draw(g, W, H) {
    bgFill(g, W, H, "#0b1220"); titleBar(g, W, "Позиции · весь портфель", T.cyan, {live: true});
    const open = D.open(), up = D.unrealised(), ex = S.ov?.exposure || {};
    txt(g, `${open.length} позиций`, 8, 33, "#fff", f(10, 800)); txt(g, `нереализ. ${fmt.signed(up, 2)} $`, 90, 33, up >= 0 ? T.green : T.red, f(9, 700, true));
    if (ex.eff_bets != null) txt(g, `≈${fmt.n(ex.eff_bets, 1)} незав. ставок`, W - 8, 33, T.muted, f(8), "right");
    const cols = [["Монета", 10], ["Сторона", 62], ["Вход", 116], ["Стоп", 176], ["P&L", 260], ["R", 296]];
    cols.forEach(([c, x]) => txt(g, c, x, 46, T.dim, f(7.2, 700)));
    open.slice(0, 8).forEach((t, i) => {
      const y = 50 + i * 15, on = i === this.sel % Math.max(1, Math.min(8, open.length)), pnl = Number(t.profit_abs || 0);
      const risk = Math.abs(t.open_rate - Number(t.initial_stop_loss_abs || t.stop_loss_abs)) / t.open_rate * Number(t.stake_amount || 0) * Number(t.leverage || 1), R = risk ? pnl / risk : 0;
      if (on) rr(g, 4, y, W - 8, 14, 3, "#1b2a40");
      txt(g, coin(t.pair), 10, y + 10, "#fff", f(8, 700)); txt(g, t.is_short ? "шорт" : "лонг", 62, y + 10, t.is_short ? T.red : T.green, f(8, 600));
      txt(g, fmt.price(t.open_rate), 116, y + 10, "#c7d0dc", f(7.5, 500, true)); txt(g, fmt.price(t.stop_loss_abs), 176, y + 10, "#c7d0dc", f(7.5, 500, true));
      txt(g, fmt.signed(pnl, 2), 285, y + 10, pnl >= 0 ? T.green : T.red, f(7.8, 700, true), "right");
      rr(g, 296, y + 4, 76, 6, 3, "#1b2330"); const w = clamp(Math.abs(R) / 3, 0, 1) * 38; rr(g, R >= 0 ? 334 : 334 - w, y + 4, Math.max(1, w), 6, 2, R >= 0 ? T.green : T.red);
    });
    if (!open.length) txt(g, "Открытых позиций нет — стратегии ждут условий входа", W / 2, 110, T.muted, f(9), "center");
    const t = open[this.sel % Math.max(1, open.length)];
    rr(g, 4, 172, W - 8, 64, 5, T.panel);
    if (t) { wantCandles(t.pair); txt(g, `${coin(t.pair)} · ${fmt.time(t.open_date || Date.now())}`, 10, 184, T.muted, f(7.5, 600)); candles(g, D.candles(t.pair)?.slice(-60), 10, 188, 330, 44, tradeLines(t, null), {axis: true}); }
  }
}

// ------------------------------------------------------------------ 8. Trade review spreadsheet (light; real closed trades, typed conclusions)
const EXIT_NOTE = r => { r = String(r || ""); if (/stop_loss|stoploss/.test(r)) return "стоп по плану — убыток в рамках риска"; if (/trailing/.test(r)) return "трейлинг сохранил прибыль"; if (/roi|take_profit|tp/.test(r)) return "тейк-профит — план выполнен"; if (/exit_signal|signal/.test(r)) return "выход по сигналу стратегии"; if (/time|max_hold/.test(r)) return "выход по времени"; if (/force/.test(r)) return "закрыта вручную"; return "разобрать отдельно"; };
export class SheetApp extends App {
  constructor() { super(); this.title = "Разбор сделок"; this.row = 0; this.typed = {}; this.cell = ""; }
  plan() {
    const rows = D.closed().slice(0, 11); if (!rows.length) { this.wait(4); return; }
    const r = this.row % rows.length, note = EXIT_NOTE(rows[r].exit_reason);
    this.typed[r] = ""; this.move(300, 70 + r * 15, 0.6).click().type(note, ch => { this.typed[r] += ch; }, 15).wait(0.6, "type").call(() => { this.row = (r + 1) % Math.min(11, rows.length); if (this.row === 0) this.typed = {}; }).wait(rand(1, 2.5));
  }
  draw(g, W, H) {
    bgFill(g, W, H, "#ffffff");
    g.fillStyle = "#1e7d45"; g.fillRect(0, 0, W, 18); txt(g, "Разбор_сделок.xlsx", 8, 12.5, "#fff", f(8.5, 700)); txt(g, "Мила · автосохранение", W - 8, 12.5, "#cfe9d9", f(7.5), "right");
    g.fillStyle = "#f3f5f4"; g.fillRect(0, 18, W, 16); txt(g, "fx", 8, 29, "#1e7d45", f(8, 700, true));
    const rows = D.closed().slice(0, 11), r = this.row % Math.max(1, rows.length);
    txt(g, this.typed[r] ?? "", 26, 29, "#1d2430", f(8));
    const cols = [["", 20], ["Дата", 52], ["Монета", 40], ["Ст.", 32], ["Результат $", 58], ["Выход", 70], ["Вывод", 110]];
    let x = 0; const X = []; cols.forEach(([, w]) => { X.push(x); x += w; });
    g.fillStyle = "#eef1f0"; g.fillRect(0, 36, W, 13); g.fillRect(0, 36, 20, H);
    cols.forEach(([c], i) => { if (i) txt(g, c, X[i] + 4, 46, "#3d4a44", f(7.5, 700)); });
    g.strokeStyle = "#e1e5e3"; g.lineWidth = 1;
    for (let i = 0; i <= 12; i++) { g.beginPath(); g.moveTo(0, 49 + i * 15); g.lineTo(W, 49 + i * 15); g.stroke(); }
    X.forEach(x0 => { g.beginPath(); g.moveTo(x0, 36); g.lineTo(x0, H); g.stroke(); });
    rows.forEach((t, i) => {
      const y = 49 + i * 15 + 10.5, p = Number(t.profit_abs || 0);
      txt(g, i + 2, 10, y, "#7b8494", f(7), "center");
      txt(g, String(t.close_date || "").slice(5, 16).replace("T", " "), X[1] + 3, y, "#1d2430", f(7, 500, true));
      txt(g, coin(t.pair), X[2] + 4, y, "#1d2430", f(7.5, 600)); txt(g, t.is_short ? "S" : "L", X[3] + 12, y, t.is_short ? "#c0394b" : "#0f8a5c", f(7.5, 700));
      g.fillStyle = p >= 0 ? "#e7f6ee" : "#fdecef"; g.fillRect(X[4] + 1, 49 + i * 15 + 1, cols[4][1] - 2, 13);
      txt(g, fmt.signed(p, 2), X[4] + cols[4][1] - 4, y, p >= 0 ? "#0f8a5c" : "#c0394b", f(7.5, 700, true), "right");
      txt(g, String(t.exit_reason || "").replace(/_/g, " "), X[5] + 4, y, "#4a5260", f(7), "left", 64);
      txt(g, this.typed[i] ?? "", X[6] + 4, y, "#1d2430", f(7.2), "left", 104);
    });
    if (rows.length) { g.strokeStyle = "#1e7d45"; g.lineWidth = 2; g.strokeRect(X[6], 49 + r * 15, cols[6][1], 15); }
    else txt(g, "Закрытых сделок пока нет", W / 2, 120, "#7b8494", f(10), "center");
    const pm = S.ov?.postmortem?.stop; if (pm?.n) { rr(g, 230, H - 24, 150, 20, 4, "#f1f8f4", "#cfe3d7"); txt(g, `стопы: ${pm.n}, прав ${pm.confirmed}, разворот ${pm.reversed}`, 305, H - 11, "#1e5a3a", f(7.2, 600), "center"); }
  }
}

// ------------------------------------------------------------------ 9. Research notebook (real lab progress) + GitHub runners
export class LabApp extends App {
  constructor() { super(); this.title = "Лаборатория · ноутбук"; this.exec = 0; this.extra = ""; this.n = 7; }
  tick(dt) { this.exec = Math.max(0, this.exec - dt); }
  plan() {
    this.move(rand(60, 360), rand(60, 200), 0.9).wait(rand(2, 3.5));
    if (Math.random() < 0.45) { const line = pick(["wf = walk_forward(spec, folds=4)", "dsr = deflated_sharpe(trials=ledger)", "stress = run(spec, costs=2.0)", "mc = monte_carlo(trades, n=2000)", "fold_returns(best).plot()"]); this.extra = ""; this.move(70, 214, 0.6).click().type(line, ch => { this.extra += ch; }, 11).wait(0.4, "type"); }
    this.move(20, 47, 0.7).click(() => { this.exec = 1.4; this.n++; });
  }
  draw(g, W, H) {
    bgFill(g, W, H, "#10131a"); titleBar(g, W, "research.ipynb — Лаборатория", T.violet, {live: true});
    const lab = S.rs?.lab || {}, run = D.running(), last = D.lastDone();
    const cell = (y, h, n, label) => { rr(g, 30, y, W - 36, h, 4, "#161b25", "#262e3d"); txt(g, this.exec > 0 && n === this.n ? "[*]" : `[${n}]`, 26, y + 11, this.exec > 0 && n === this.n ? T.amber : "#6b7a90", f(7.5, 600, true), "right"); txt(g, label, 36, y + 11, "#c3b8ff", f(7.5, 600, true)); };
    rr(g, 12, 40, 16, 14, 3, this.exec > 0 ? T.violet : "#232b3a"); txt(g, "▶", 20, 50.5, "#fff", f(8), "center");
    cell(26, 36, this.n - 2, "lab.status()");
    txt(g, `статус: ${lab.status === "start" ? "идёт прогон" : lab.status || "—"} · запусков ${lab.runs ?? "—"} · ${lab.cpus ?? "—"} CPU · бюджет ${lab.budget_min ?? "—"} мин`, 36, 52, "#e9eef5", f(7.8, 500), "left", W - 50);
    cell(66, 78, this.n - 1, run ? `hyperopt(${run.family})` : "hyperopt()");
    if (run) {
      const pg = run.progress || {}, k = pg.epoch && pg.epochs ? pg.epoch / pg.epochs : 0;
      txt(g, `${pg.stage || "работа"} · эпоха ${pg.epoch ?? "—"}/${pg.epochs ?? "—"}`, 36, 92, "#e9eef5", f(8, 600));
      rr(g, 36, 97, 150, 6, 3, "#262e3d"); rr(g, 36, 97, 150 * k, 6, 3, T.violet);
      txt(g, pg.best_profit != null ? `лучший in-sample ${fmt.spct(pg.best_profit)} на ${pg.best_trades ?? "—"} сделках` : "", 36, 116, "#9aa7b8", f(7.5), "left", 150);
      txt(g, "в зачёт не идёт — только вне выборки", 36, 128, "#6b7a90", f(7));
      const h = S.lossHist[run.id] || []; if (h.length > 1) spark(g, h.map(v => -v), 196, 86, W - 214, 50, T.violet); else txt(g, "кривая лосса появится по ходу", 270, 112, "#6b7a90", f(7.5), "center");
    } else txt(g, "Сейчас эксперимент не идёт — следующий прогон в очереди GitHub.", 36, 96, "#9aa7b8", f(8), "left", W - 50);
    cell(148, 56, this.n, "folds(last)");
    if (last) {
      const fs = last.folds || [], mx = Math.max(0.005, ...fs.map(x => Math.abs(x.ret || 0)));
      txt(g, `${last.variant || last.family}`, 36, 174, "#e9eef5", f(7.5, 600), "left", 120);
      const v = last.summary?.verdict; if (v) chip(g, 36, 190, VERDICT_RU[v] || v, v === "validated" ? T.green : v === "exploratory" ? T.amber : T.red);
      fs.slice(0, 8).forEach((x, i) => { const r = x.ret || 0, h = (Math.abs(r) / mx) * 20, bx = 170 + i * 26; g.fillStyle = r >= 0 ? T.green : T.red; g.fillRect(bx, r >= 0 ? 180 - h : 180, 16, h); });
      g.strokeStyle = "#ffffff30"; g.beginPath(); g.moveTo(166, 180); g.lineTo(W - 10, 180); g.stroke();
    }
    rr(g, 30, 208, W - 36, 18, 4, "#161b25", "#3a2f6b"); txt(g, this.extra || "", 36, 220, "#e9eef5", f(7.8, 500, true));
    if (this.mode === "type" || this.mode === "type-pause") { g.font = f(7.8, 500, true); g.fillStyle = "#fff"; g.fillRect(37 + g.measureText(this.extra).width, 212, 1, 10); }
  }
}
export class RunnersApp extends App {
  constructor() { super(); this.title = "GitHub Actions"; this.showCursor = false; }
  plan() { this.wait(5); }
  draw(g, W, H) {
    bgFill(g, W, H, "#0d1117"); titleBar(g, W, "GitHub Actions · research-lab", "#8b949e", {live: true});
    const lab = S.rs?.lab || {}, active = D.labActive(), run = D.running();
    txt(g, active ? "● выполняется" : "○ ожидает запуска", 10, 34, active ? T.amber : "#8b949e", f(9, 700));
    txt(g, `run ${lab.run_id || "—"} · всего запусков ${lab.runs ?? "—"}`, W - 10, 34, "#8b949e", f(8, 500, true), "right");
    for (let i = 0; i < 4; i++) {
      const x = 8 + (i % 2) * 186, y = 44 + Math.floor(i / 2) * 64;
      rr(g, x, y, 182, 58, 6, "#161b22", "#30363d");
      txt(g, `runner ${i + 1} · 4 vCPU`, x + 8, y + 14, "#c9d1d9", f(8, 700));
      const k = active ? ((this.t * 0.03 + i * 0.23) % 1) : 0;
      txt(g, active ? (i === 0 && run ? (run.progress?.stage || run.family) : ["hyperopt", "walk-forward", "стресс-тест", "Монте-Карло"][i]) : "свободен", x + 8, y + 30, active ? T.amber : "#6e7681", f(7.8), "left", 165);
      rr(g, x + 8, y + 40, 166, 5, 2.5, "#21262d"); if (active) rr(g, x + 8, y + 40, 166 * k, 5, 2.5, "#2f81f7");
    }
    rr(g, 8, 178, W - 16, 54, 6, "#161b22", "#30363d");
    txt(g, `последний импорт: ${lab.last_import ? fmt.ago(lab.last_import) : "—"}`, 16, 194, "#c9d1d9", f(8));
    txt(g, `экспериментов импортировано: ${lab.experiments_total ?? "—"}`, 16, 208, "#c9d1d9", f(8));
    txt(g, `партия ${lab.last_batch || "—"}`, 16, 222, "#8b949e", f(7.5, 500, true), "left", W - 40);
  }
}

// ------------------------------------------------------------------ 10. Code editor: the quant writes and tests code
const SNIPPETS = [
  ["tsmom.py", "def tsmom_signal(close, lookback=180, vol_win=60):\n    \"\"\"Time-series momentum, scaled by volatility.\"\"\"\n    ret = close.pct_change(lookback)\n    vol = close.pct_change().rolling(vol_win).std()\n    score = ret / (vol * lookback ** 0.5)\n    return score.clip(-3, 3)\n\ndef entry(df):\n    s = tsmom_signal(df.close)\n    return (s > 1.0) & (s.shift() <= 1.0)\n", "pytest -q tests/test_tsmom.py", "12 passed in 1.84s"],
  ["riskcore.py", "def managed_stop(entry, atr, side, k=2.0):\n    # stop sits on the exchange from the first second\n    dist = k * atr\n    stop = entry - dist if side == \"long\" else entry + dist\n    risk = abs(entry - stop)\n    return stop, risk\n\ndef size(equity, risk_pct, risk):\n    return equity * risk_pct / max(risk, 1e-9)\n", "pytest -q tests/test_riskcore.py", "21 passed in 2.31s"],
  ["evidence.py", "def anytime_threshold(n, rho=0.5):\n    # normal-mixture boundary: valid when peeking daily\n    v = n * rho ** 2\n    return ((v + 1) / v * (2 * log(1 / 0.05)\n            + log(v + 1))) ** 0.5\n\ndef verdict(daily):\n    t = daily.mean() / daily.std() * len(daily) ** 0.5\n    return t >= anytime_threshold(len(daily))\n", "pytest -q tests/test_evidence.py", "14 passed in 2.07s"],
];
// code already in each file: the developer adds a new function at the bottom, so the editor is never empty
const PRELUDE = {
  "tsmom.py": "\"\"\"Time-series momentum family: one signal for backtest and live.\"\"\"\nfrom __future__ import annotations\n\nimport numpy as np\nimport pandas as pd\n\nfrom .base import Family, Param\n\nPARAMS = [\n    Param(\"lookback\", 90, 360, step=30),\n    Param(\"vol_win\", 20, 120, step=10),\n    Param(\"threshold\", 0.5, 2.0, step=0.25),\n]\n\n\nclass TSMOM(Family):\n    name = \"tsmom\"\n    timeframes = (\"1h\", \"2h\", \"4h\")\n\n",
  "riskcore.py": "\"\"\"Risk core: every position has a stop on the exchange.\"\"\"\nfrom dataclasses import dataclass\n\nMAX_RISK_PCT = 0.01      # of equity per trade\nMAX_SIDE_PCT = 0.04      # all longs (or shorts) together\nKILL_DD = 0.08           # kill-switch drawdown\n\n\n@dataclass(frozen=True)\nclass Stop:\n    price: float\n    risk: float\n\n\n",
  "evidence.py": "\"\"\"Forward evidence: is the edge real, or still luck?\"\"\"\nfrom math import log, sqrt\n\nimport numpy as np\n\nALPHA = 0.05\nMIN_DAYS = 30\n\n\ndef daily_returns(trades, days):\n    out = np.zeros(days)\n    for t in trades:\n        out[t.day] += t.pnl_pct\n    return out\n\n",
};
const KW = /^(def|return|if|else|for|in|import|from|and|or|not|max|min|abs|log|class|as|with)$/;
export class CodeApp extends App {
  constructor() { super(); this.title = "Редактор кода"; this.live = false; this.file = 0; this.code = ""; this.term = []; }
  plan() {
    const [, src, cmd, out] = SNIPPETS[this.file];
    this.code = PRELUDE[SNIPPETS[this.file][0]] || ""; this.term = [];
    this.move(140, 60, 0.5).click().type(src, ch => { this.code += ch; }, 16).wait(1.2, "read")
      .move(150, 196, 0.6).click().call(() => { this.term = ["$ "]; }).type(cmd, ch => { this.term[0] += ch; }, 14)
      .call(() => { this.term.push("........................"); }).wait(1.2, "read").call(() => { this.term.push("✓ " + out); }).wait(rand(2.5, 4))
      .move(70 + ((this.file + 1) % 3) * 70, 26, 0.7).click(() => { this.file = (this.file + 1) % SNIPPETS.length; });
  }
  draw(g, W, H) {
    bgFill(g, W, H, "#1e1e1e"); g.fillStyle = "#181818"; g.fillRect(0, 0, W, 18); txt(g, "aitrader — Visual Studio Code", W / 2, 12.5, "#c5c5c5", f(8), "center");
    g.fillStyle = "#252526"; g.fillRect(0, 18, 34, H); g.fillStyle = "#2d2d2d"; g.fillRect(34, 18, W - 34, 14);
    SNIPPETS.forEach(([fn], i) => { const on = i === this.file; g.fillStyle = on ? "#1e1e1e" : "#2d2d2d"; g.fillRect(34 + i * 70, 18, 70, 14); txt(g, fn, 69 + i * 70, 28, on ? "#fff" : "#969696", f(7.5), "center"); if (on) { g.fillStyle = "#007acc"; g.fillRect(34 + i * 70, 18, 70, 1.5); } });
    for (let i = 0; i < 5; i++) { g.strokeStyle = i === 0 ? "#e6e6e6" : "#6e6e6e"; g.lineWidth = 1.2; g.strokeRect(12, 30 + i * 22, 10, 10); }
    if (this.code.length) { g.fillStyle = "rgba(121,121,121,.18)"; g.fillRect(W - 26, 32, 22, 156); this.code.split("\n").slice(0, 70).forEach((ln, i) => { if (ln.trim()) { g.fillStyle = ln.trim().startsWith("#") || ln.trim().startsWith("\"") ? "#5d8a52" : ln.startsWith("def") || ln.startsWith("class") ? "#a57fb0" : "#8b8b8b"; g.fillRect(W - 24 + (ln.length - ln.trimStart().length) * 0.4, 34 + i * 2.2, Math.min(18, ln.trim().length * 0.35), 1.2); } }); }
    const lines = this.code.split("\n");
    g.font = f(8, 500, true);
    lines.slice(-15).forEach((ln, i) => {
      const y = 44 + i * 10.4; txt(g, String(Math.max(0, lines.length - 15) + i + 1), 52, y, "#6e7681", f(7.5, 500, true), "right");
      g.textAlign = "left"; g.font = f(8, 500, true);
      let x = 58; const parts = ln.split(/(#.*$|"[^"]*"?|\b\d+(?:\.\d+)?\b|\bdef\b|\breturn\b|\bif\b|\belse\b|\bfor\b|\bin\b|\band\b|\bor\b|\bnot\b|\b[a-z_]+(?=\())/g).filter(Boolean);
      for (const p of parts) {
        const c = p.startsWith("#") ? "#6a9955" : p.startsWith("\"") ? "#ce9178" : /^\d/.test(p) ? "#b5cea8" : KW.test(p) ? "#c586c0" : /^[a-z_]+$/.test(p) && ln.includes(p + "(") ? "#dcdcaa" : "#d4d4d4";
        g.fillStyle = c; g.fillText(p, x, y); x += g.measureText(p).width;
      }
      if (i === Math.min(lines.length, 15) - 1 && this.mode.startsWith("type") && !this.term.length && Math.floor(this.t * 2) % 2 === 0) { g.fillStyle = "#aeafad"; g.fillRect(x + 1, y - 8, 1.2, 10); }
    });
    g.fillStyle = "#181818"; g.fillRect(34, 190, W - 34, 38); g.fillStyle = "#2b2b2b"; g.fillRect(34, 190, W - 34, 1);
    txt(g, "ТЕРМИНАЛ", 42, 200, "#969696", f(6.8, 700));
    this.term.forEach((l, i) => txt(g, l, 42, 211 + i * 8.5, l.startsWith("✓") ? "#3fb950" : "#cccccc", f(7.2, 500, true), "left", W - 50));
    g.fillStyle = "#007acc"; g.fillRect(0, H - 11, W, 11); txt(g, "⎇ main   Python 3.13   UTF-8", 6, H - 3, "#fff", f(6.8, 600));
  }
}

// ------------------------------------------------------------------ 11. Risk: gates of the latest candidate, ticked one by one (real)
const GATE_RU = {trades: "Сделок вне выборки", profit_factor: "Profit factor", sharpe: "Sharpe", max_drawdown: "Макс. просадка", stress_pf: "PF при 2× издержках", wfe: "Эффективность walk-forward",
  robustness: "Устойчивость ±10%", monte_carlo: "Монте-Карло", deflated_sharpe: "Deflated Sharpe", fold_consistency: "Прибыльные отрезки", clean_oos: "Чистая проверка", market_alpha: "Альфа к BTC", steadiness: "Ровность кривой"};
export class RiskApp extends App {
  constructor() { super(); this.title = "Валидация кандидата"; this.k = 0; this.stamp = 0; this.id = null; }
  gates() { const e = D.lastGated(); return e ? Object.entries(e.gates).slice(0, 9) : []; }
  plan() {
    const G = this.gates();
    if (!G.length) { this.move(rand(60, 330), rand(60, 200), 1).wait(4); return; }
    if (this.k >= G.length) { this.wait(1.2).call(() => { this.stamp = 1; }).wait(rand(4, 6)).call(() => { this.k = 0; this.stamp = 0; }); return; }
    this.move(rand(30, 240), 62 + this.k * 17, 0.55).click(() => { this.k++; }).wait(rand(0.5, 1.1));
  }
  draw(g, W, H) {
    bgFill(g, W, H, "#f7f8fa"); titleBar(g, W, "Валидация · строгие ворота", "#ff8f70", {light: true, live: true});
    const e = D.lastGated(), G = this.gates();
    if (!e) { txt(g, "Кандидатов пока нет — ворота строгие", W / 2, H / 2, "#5b6575", f(10), "center"); return; }
    txt(g, e.variant || e.family, 10, 34, "#111827", f(10, 800), "left", 260); txt(g, `${e.pairs || "—"} пар · ${e.timeframe || ""}`, W - 10, 34, "#7b8494", f(8), "right");
    rr(g, 10, 40, W - 20, 4, 2, "#e5e7eb"); rr(g, 10, 40, (W - 20) * (this.k / Math.max(1, G.length)), 4, 2, "#ff8f70");
    G.forEach(([k, v], i) => {
      const y = 52 + i * 17, done = i < this.k;
      rr(g, 10, y, W - 20, 15, 3, done ? (v.pass ? "#ecfbf3" : "#fdecef") : "#fff", "#e5e7eb");
      txt(g, done ? (v.pass ? "✓" : "✗") : i === this.k ? "…" : "○", 20, y + 11, done ? (v.pass ? "#0f9d6b" : "#d6455a") : "#9aa3b0", f(9, 800), "center");
      txt(g, GATE_RU[k] || k, 32, y + 11, "#1d2430", f(8, 600));
      txt(g, done ? `${typeof v.value === "number" ? fmt.n(v.value, 2) : v.value} / нужно ${v.threshold}` : "", W - 16, y + 11, "#5b6575", f(7.5, 500, true), "right");
    });
    if (this.stamp) {
      const v = e.summary?.verdict || "", c = v === "validated" ? "#0f9d6b" : v === "exploratory" ? "#d9911a" : "#d6455a";
      g.save(); g.translate(W - 92, H - 42); g.rotate(-0.18); g.globalAlpha = 0.9; rr(g, -66, -16, 132, 32, 4, null, c, 2.5); txt(g, (VERDICT_RU[v] || v).toUpperCase(), 0, 6, c, f(13, 900), "center"); g.restore();
    }
  }
}
export class ReadinessApp extends App {
  constructor() { super(); this.title = "Готовность к реальным деньгам"; this.showCursor = false; }
  plan() { this.wait(5); }
  draw(g, W, H) {
    bgFill(g, W, H, "#f7f8fa"); titleBar(g, W, "Готовность к реальным деньгам", "#0f9d6b", {light: true, live: true});
    const rd = D.readiness(), checks = rd.checks || [];
    txt(g, `${rd.passed ?? 0}`, 14, 50, "#111827", f(24, 800)); txt(g, `из ${rd.total ?? 10} проверок`, 14 + (String(rd.passed ?? 0).length * 14) + 4, 50, "#5b6575", f(9));
    txt(g, "советующий гейт — никогда не включается сам", W - 10, 48, "#9aa3b0", f(7.5), "right");
    const RU = {forward_days: "Форвард после повышения", trades: "Закрытых сделок", diversified: "Независимых стратегий", t_stat: "Значимость (t)", t_daily: "Значимость по дням", alpha: "Альфа к BTC", profit_factor: "Profit factor", drawdown: "Макс. просадка", stability: "Прибыльные трети", divergence: "Совпадение с бэктестом"};
    checks.slice(0, 10).forEach((c, i) => { const y = 60 + i * 17.5; txt(g, c.pass ? "✓" : "✗", 16, y + 10, c.pass ? "#0f9d6b" : "#d6455a", f(9, 800), "center"); txt(g, RU[c.id] || c.title, 28, y + 10, "#1d2430", f(8, 600), "left", 200); txt(g, `${typeof c.value === "number" ? fmt.n(c.value, 2) : c.value}  ·  ${c.need}`, W - 10, y + 10, "#5b6575", f(7.2, 500, true), "right", 150); });
    if (!checks.length) txt(g, "Проверки появятся с первой стратегией в боевом режиме", W / 2, 140, "#5b6575", f(9), "center");
  }
}

// ------------------------------------------------------------------ 12. Ops: monitoring dashboard (real heartbeats/events) + terminal
export class OpsApp extends App {
  constructor() { super(); this.title = "Мониторинг"; this.scrollLog = 0; }
  plan() { this.move(rand(20, 370), rand(30, 120), 0.9).wait(rand(2, 3)).move(rand(20, 370), rand(140, 220), 0.9).scroll(20, 1).wait(rand(2, 3)); }
  draw(g, W, H) {
    bgFill(g, W, H, "#111217"); titleBar(g, W, "Мониторинг · Railway EU", "#f46800", {live: true});
    const hl = S.hl || {}, disk = hl.disk, mem = D.mem();
    const tiles = [["Бот", hl.bot_up ? "работает" : "НЕ ОТВЕЧАЕТ", hl.bot_up], ["Самотест", hl.selftest?.ok ? "пройден" : "—", !!hl.selftest?.ok], ["Тест ордеров", hl.exec_test?.ok ? "пройден" : "—", !!hl.exec_test?.ok], ["Диск свободен", disk ? fmt.n(disk.free / 1e9, 1) + " ГБ" : "—", !disk || disk.free / disk.total > 0.2]];
    tiles.forEach(([k, v, ok], i) => { const x = 6 + i * 94; rr(g, x, 24, 90, 40, 4, "#181b1f", "#24282e"); txt(g, k, x + 7, 36, "#8e8e8e", f(7.5)); txt(g, v, x + 7, 55, ok ? "#73bf69" : "#f2495c", f(10.5, 800), "left", 80); });
    rr(g, 6, 70, 186, 80, 4, "#181b1f", "#24282e"); txt(g, "Свободная память, МБ", 13, 82, "#ccccdc", f(7.8, 700));
    const mh = S.memHist.length > 1 ? S.memHist : mem ? [mem, mem] : [];
    if (mh.length) { spark(g, mh, 13, 90, 172, 52, "#73bf69"); txt(g, fmt.n(mh.at(-1)), 185, 82, "#73bf69", f(8, 700, true), "right"); }
    rr(g, 198, 70, 180, 80, 4, "#181b1f", "#24282e"); txt(g, "Пульс сервисов", 205, 82, "#ccccdc", f(7.8, 700));
    (hl.heartbeats || []).slice(0, 5).forEach((h, i) => { const y = 95 + i * 11, ok = h.status !== "error" && ((h.age_s ?? 0) < 900 || h.detail?.remote); g.fillStyle = ok ? "#73bf69" : "#f2495c"; g.beginPath(); g.arc(208, y - 3, 2.5, 0, 7); g.fill(); txt(g, h.service, 215, y, "#ccccdc", f(7.5)); txt(g, `${h.status} · ${h.age_s ?? "—"} с`, 372, y, "#8e8e8e", f(7.2, 500, true), "right"); });
    rr(g, 6, 156, W - 12, 78, 4, "#0b0c0e", "#24282e"); txt(g, "Журнал компании", 13, 167, "#ccccdc", f(7.8, 700));
    const ev = (S.ov?.events || []).slice(0, 6);
    ev.forEach((e, i) => { const y = 179 + i * 9.5; txt(g, String(e.ts || "").slice(11, 16), 13, y, "#6e7681", f(7, 500, true)); txt(g, e.source, 42, y, "#5794f2", f(7, 700, true)); txt(g, e.message, 92, y, "#c7c7d0", f(7, 500, true), "left", W - 104); });
  }
}
export class TerminalApp extends App {
  constructor() { super(); this.title = "Терминал"; this.live = true; this.lines = ["aitrader@railway:~$ "]; this.k = 0; this.showCursor = false; }
  plan() {
    const cmds = [["railway logs --service aitrader | tail -4", () => (S.ov?.events || []).slice(0, 4).map(e => `${String(e.ts).slice(11, 19)} ${e.source}: ${e.message}`)],
      ["curl -s localhost:8080/healthz", () => ['{"ok": true}']], ["df -h /data", () => { const d = S.hl?.disk; return d ? [`/data  ${fmt.n(d.total / 1e9, 1)}G  used ${fmt.n(d.used / 1e9, 1)}G  free ${fmt.n(d.free / 1e9, 1)}G`] : ["нет данных"]; }],
      ["ps aux | grep -c freqtrade", () => [S.hl?.bot_up ? "1" : "0"]]];
    const [cmd, out] = cmds[this.k++ % cmds.length];
    this.type(cmd, ch => { this.lines[this.lines.length - 1] += ch; }, 15).wait(0.4, "type").call(() => { for (const l of out()) this.lines.push(l); this.lines.push("aitrader@railway:~$ "); while (this.lines.length > 19) this.lines.shift(); }).wait(rand(3, 6));
  }
  draw(g, W, H) {
    bgFill(g, W, H, "#0b0e0c"); titleBar(g, W, "ssh · aitrader@railway", "#3fb950");
    this.lines.forEach((l, i) => txt(g, l, 6, 30 + i * 11, l.startsWith("aitrader@") ? "#3fb950" : "#c9d1d9", f(7.6, 500, true), "left", W - 12));
    if (Math.floor(this.t * 2) % 2 === 0) { g.font = f(7.6, 500, true); g.fillStyle = "#c9d1d9"; g.fillRect(7 + g.measureText(this.lines.at(-1)).width, 22 + (this.lines.length - 1) * 11, 5, 9); }
  }
}

// ------------------------------------------------------------------ wall displays
export class VideoWallApp extends App {
  constructor() { super(1024, 276); this.title = "Видеостена"; this.showCursor = false; }
  plan() { this.wait(60); }
  draw(g, W, H) {
    const gr = g.createLinearGradient(0, 0, W, H); gr.addColorStop(0, "#0b1424"); gr.addColorStop(1, "#0a0f1a"); g.fillStyle = gr; g.fillRect(0, 0, W, H);
    const eq = D.equity(), cap = D.capital(), ret = eq.length > 1 ? eq.at(-1) / eq[0] - 1 : null;
    txt(g, "Капитал · Bybit Demo", 26, 34, "#8fa3b8", f(15, 600));
    txt(g, cap ? fmt.n(cap, 0) : "—", 26, 82, "#f3f6fa", f(44, 800)); g.font = f(44, 800); const cw = g.measureText(cap ? fmt.n(cap, 0) : "—").width;
    txt(g, "USDT", 34 + cw, 82, "#8fa3b8", f(16, 600)); if (ret !== null) txt(g, `${fmt.spct(ret, 2)} с начала`, 26, 106, ret >= 0 ? T.green : T.red, f(14, 700));
    const sp = spark(g, eq.slice(-300), 26, 120, 400, 130, ret === null || ret >= 0 ? "#4ee6c4" : "#ff6b7a", true, 3);
    if (sp) { const x = 426, y = sp.Y(eq.slice(-300).at(-1)); g.fillStyle = "#4ee6c455"; g.beginPath(); g.arc(x, y, 9 + Math.sin(this.t * 3) * 2, 0, 7); g.fill(); g.fillStyle = "#c9fff2"; g.beginPath(); g.arc(x, y, 4.5, 0, 7); g.fill(); }
    g.fillStyle = "#ffffff12"; g.fillRect(452, 22, 1, H - 44); g.fillRect(752, 22, 1, H - 44);
    const open = D.open();
    txt(g, "Открытые позиции", 474, 34, "#8fa3b8", f(15, 600)); txt(g, String(open.length), 732, 34, "#ffc15e", f(16, 800), "right");
    open.slice(0, 7).forEach((t, i) => { const y = 62 + i * 27, p = Number(t.profit_abs || 0); rr(g, 474, y - 15, 258, 23, 5, "#ffffff08"); chip(g, 482, y + 1, t.is_short ? "ШОРТ" : "ЛОНГ", t.is_short ? T.red : T.green, f(9, 800)); txt(g, coin(t.pair), 540, y + 2, "#f3f6fa", f(14, 700)); txt(g, fmt.signed(p, 2), 724, y + 2, p >= 0 ? T.green : T.red, f(14, 800, true), "right"); });
    if (!open.length) wrap(g, "Позиций нет — стратегии ждут своих сигналов. Стоп у каждой сделки сразу на бирже.", 474, 72, 258, 20, 3, "#8fa3b8", f(13));
    if (open.length > 7) txt(g, `и ещё ${open.length - 7}`, 474, 258, "#8fa3b8", f(12));
    txt(g, "Мир сейчас", 774, 34, "#8fa3b8", f(15, 600));
    D.markets().slice(0, 5).forEach((m, i) => { const y = 62 + i * 24; g.fillStyle = m.open ? T.green : "#3a4658"; g.beginPath(); g.arc(780, y - 4, 4.5, 0, 7); g.fill(); txt(g, m.name, 792, y, "#e9eef5", f(13, 600)); txt(g, m.local, 1000, y, "#8fa3b8", f(13, 600, true), "right"); });
    const ev = D.nextEvent(), fg = S.ctx?.fear_greed;
    rr(g, 774, 184, 228, 34, 6, "#ffffff0a"); txt(g, ev ? ev.name : "Макро-событий нет", 784, 199, "#ffc15e", f(11, 700), "left", 210); txt(g, ev ? `через ${fmt.until(ev.ts)}` : "", 784, 213, "#c7d0dc", f(10));
    rr(g, 774, 224, 228, 30, 6, "#ffffff0a"); txt(g, "Страх и жадность", 784, 243, "#c7d0dc", f(11, 600)); txt(g, fg ? `${fg.value} · ${fgRu(fg.label)}` : "—", 992, 243, "#fff", f(12, 800), "right");
  }
}
export class LabWallApp extends App {
  constructor() { super(768, 288); this.title = "Стена лаборатории"; this.showCursor = false; }
  plan() { this.wait(60); }
  draw(g, W, H) {
    const gr = g.createLinearGradient(0, 0, 0, H); gr.addColorStop(0, "#151129"); gr.addColorStop(1, "#0d0b18"); g.fillStyle = gr; g.fillRect(0, 0, W, H);
    const active = D.labActive(), lab = S.rs?.lab || {}, c = S.rs?.counts || {}, st = D.stageCounts();
    txt(g, "Лаборатория исследований", 22, 34, "#e9e6f5", f(19, 800)); chip(g, W - 22, 30, active ? "ИДЁТ ПРОГОН" : "ОЖИДАНИЕ", active ? T.amber : "#8b86a8", f(10, 800), "right");
    txt(g, `GitHub Actions · ${lab.cpus ?? 4} CPU на раннер · тяжёлые расчёты не на сервере`, 22, 54, "#9a94ba", f(11));
    const stages = [["Walk-forward", c.done ?? 0, "экспериментов"], ["Форвард-тест", D.goal("forward").value ?? "—", "на новых данных"], ["Демо", D.sleeves().length, "стратегий торгуют"], ["Боевые", st.production || 0, "после доказательств"]];
    stages.forEach(([name, v, sub], i) => {
      const x = 22 + i * 186, y = 74;
      rr(g, x, y, 166, 82, 8, "#1e1838", "#3a2f6b");
      txt(g, name, x + 12, y + 22, "#c3b8ff", f(12, 700)); txt(g, typeof v === "number" ? fmt.n(v) : goalValueRaw(v), x + 12, y + 56, "#fff", f(24, 800)); txt(g, sub, x + 12, y + 73, "#8b86a8", f(9.5));
      if (i < 3) { g.fillStyle = "#3a2f6b"; g.beginPath(); g.moveTo(x + 170, y + 34); g.lineTo(x + 182, y + 41); g.lineTo(x + 170, y + 48); g.fill();
        if (active) { const k = (this.t * 0.6 + i * 0.3) % 1; g.fillStyle = "#b79cff"; g.beginPath(); g.arc(x + 166 + k * 20, y + 41, 3, 0, 7); g.fill(); } }
    });
    txt(g, "Какие семейства стратегий выбирает бандит (UCB)", 22, 184, "#c3b8ff", f(11, 700));
    const fam = Object.entries(S.rs?.family_stats || {}).sort((a, b) => (b[1][1] || 0) - (a[1][1] || 0)).slice(0, 6), mx = Math.max(0.01, ...fam.map(([, v]) => Math.abs(v[1] || 0)));
    fam.forEach(([name, [n, r]], i) => { const x = 22 + (i % 3) * 248, y = 200 + Math.floor(i / 3) * 38; txt(g, name, x, y + 10, "#e9e6f5", f(10.5, 600), "left", 150); txt(g, `n=${n}`, x + 230, y + 10, "#8b86a8", f(9.5, 500, true), "right"); rr(g, x, y + 17, 230, 7, 3.5, "#2a2448"); rr(g, x, y + 17, 230 * clamp(Math.abs(r || 0) / mx, 0.02, 1), 7, 3.5, (r || 0) >= 0 ? "#b79cff" : "#ff6b7a"); });
    if (!fam.length) txt(g, "статистика появится после первых экспериментов", 22, 214, "#8b86a8", f(11));
  }
}
const goalValueRaw = v => ({works: "работает", no: "нет", unclear: "неясно"}[v] ?? String(v).replace("trades", "сд."));
export class MeetWallApp extends App {
  constructor() { super(640, 356); this.title = "Миссия и цели"; this.showCursor = false; }
  plan() { this.wait(60); }
  draw(g, W, H) {
    const gr = g.createLinearGradient(0, 0, W, H); gr.addColorStop(0, "#101a2b"); gr.addColorStop(1, "#1a1426"); g.fillStyle = gr; g.fillRect(0, 0, W, H);
    txt(g, "Миссия", 26, 40, "#f48fb1", f(13, 800));
    wrap(g, "Найти, доказать и масштабировать настоящие торговые преимущества на Bybit Demo — без подгонки и фальшивых результатов.", 26, 64, W - 52, 21, 2, "#f3f6fa", f(16, 700));
    (S.goals?.goals || []).slice(0, 8).forEach((gl, i) => {
      const x = 26 + (i % 2) * 300, y = 126 + Math.floor(i / 2) * 54;
      txt(g, goalTitle(gl), x, y, "#c7d0dc", f(11.5, 600), "left", 200); txt(g, `${goalValue(gl)}${gl.unit === "%" ? "%" : ""} / ${goalTarget(gl)}`, x + 284, y, "#fff", f(11.5, 800), "right");
      rr(g, x, y + 10, 284, 9, 4.5, "#ffffff14"); rr(g, x, y + 10, 284 * clamp(gl.progress || 0, 0.01, 1), 9, 4.5, gl.warning ? T.red : gl.progress >= 1 ? T.green : "#6aa8ff");
      const sh = ((this.t * 60 + i * 40) % 340) - 30; g.fillStyle = "#ffffff22"; g.fillRect(x + clamp(sh, 0, 284 * clamp(gl.progress || 0, 0, 1)), y + 10, 10, 9);
    });
  }
}
export class BoardApp extends App {
  constructor() { super(512, 300); this.title = "Конвейер стратегий"; this.showCursor = false; }
  plan() { this.wait(60); }
  draw(g, W, H) {
    bgFill(g, W, H, "#0f1420");
    txt(g, "Конвейер стратегий", 20, 32, "#f3f6fa", f(17, 800)); txt(g, "строгие ворота · малый риск · доказательства", 20, 50, "#8fa3b8", f(10.5));
    const st = D.stageCounts(), live = D.sleeves();
    const rows = [["Разведка (0,1% риска)", live.filter(s => s.stage === "exploration").length || st.exploration || 0, "#ffc15e"], ["Инкубация", st.incubation || 0, "#6aa8ff"], ["Боевые", st.production || 0, "#3ddc97"], ["Сняты / отклонены", (st.retired || 0) + (st.rejected || 0), "#5b697c"]];
    const mx = Math.max(1, ...rows.map(r => r[1]));
    rows.forEach(([name, n, c], i) => { const y = 72 + i * 42, w = 300 * clamp(n / mx, 0.03, 1); txt(g, name, 20, y + 12, "#c7d0dc", f(11.5, 600)); rr(g, 20, y + 18, 300, 14, 7, "#ffffff10"); rr(g, 20, y + 18, w, 14, 7, c); txt(g, fmt.n(n), 332, y + 30, "#fff", f(15, 800)); });
    const ex = S.ov?.exposure || {};
    rr(g, 372, 72, 120, 160, 10, "#ffffff08");
    txt(g, "Сейчас в рынке", 384, 94, "#8fa3b8", f(10)); txt(g, String(D.open().length), 384, 128, "#fff", f(30, 800));
    txt(g, "незав. ставок", 384, 156, "#8fa3b8", f(10)); txt(g, ex.eff_bets != null ? "≈" + fmt.n(ex.eff_bets, 1) : "—", 384, 182, "#4ee6c4", f(18, 800));
    txt(g, ex.one_side_share != null ? `${fmt.pct(ex.one_side_share, 0)} риска в одну сторону` : "", 384, 214, "#8fa3b8", f(9), "left", 100);
    txt(g, `Сигналов за 7 дней: ${S.ov?.signals?.signals ?? "—"} · исполнено ${S.ov?.signals?.executed ?? "—"}`, 20, H - 22, "#8fa3b8", f(10.5));
  }
}

// ------------------------------------------------------------------ registry: which app runs where
export function makeApps(roster) {
  const apps = {};
  for (const p of roster) {
    const [Main, Second] = {report: [ReportApp], news: [NewsApp], macro: [MacroApp], sentiment: [SentimentApp], trader: [TraderApp, StrategiesApp], dom: [DomApp, SignalsApp],
      blotter: [BlotterApp], sheet: [SheetApp], lab: [LabApp, RunnersApp], code: [CodeApp], risk: [RiskApp, ReadinessApp], ops: [OpsApp, TerminalApp]}[p.app];
    const args = p.app === "trader" ? [0, 2, p.name] : p.app === "dom" ? [1, 2] : [];
    apps[p.id] = new Main(...args);
    apps[p.id].awayName = p.name;
    if (Second) { apps[p.id + "#2"] = new Second(...(p.app === "trader" ? [0, 2] : [])); apps[p.id + "#2"].awayName = p.name; }
  }
  apps.videowall = new VideoWallApp(); apps.labwall = new LabWallApp(); apps.newswall = new NewsWallApp(); apps.meetwall = new MeetWallApp(); apps.board = new BoardApp();
  return apps;
}

// ------------------------------------------------------------------ the display scheduler: redraw only what is seen, as often as it is seen
const _v = new THREE.Vector3(), _f = new THREE.Frustum(), _pm = new THREE.Matrix4();
export class Screens {
  constructor(displays, apps) {
    this.list = [];
    for (const d of displays) {
      const app = apps[d.id]; if (!app) continue;
      const s = {d, app, scale: 1, last: 0, canvas: null, g: null, tex: null};
      d.mesh.material = new THREE.MeshBasicMaterial({toneMapped: false});
      this.alloc(s, 1); this.paint(s);
      this.list.push(s);
    }
    this.budgetMs = 4; this.maxPerFrame = 4;
  }
  alloc(s, scale) {
    const c = document.createElement("canvas"); c.width = Math.round(s.app.W * scale); c.height = Math.round(s.app.H * scale);
    const tex = new THREE.CanvasTexture(c); tex.colorSpace = THREE.SRGBColorSpace; tex.anisotropy = 4;
    s.tex?.dispose(); s.canvas = c; s.g = c.getContext("2d"); s.tex = tex; s.scale = scale; s.d.mesh.material.map = tex; s.d.mesh.material.needsUpdate = true;
  }
  paint(s) { s.g.setTransform(s.scale, 0, 0, s.scale, 0, 0); s.app.paint(s.g); s.tex.needsUpdate = true; }
  update(dt, camera, viewH, quality = 1) {
    for (const s of this.list) s.app.update(dt);
    _pm.multiplyMatrices(camera.projectionMatrix, camera.matrixWorldInverse); _f.setFromProjectionMatrix(_pm);
    const now = performance.now(), due = [], tanF = Math.tan((camera.fov * Math.PI) / 360);
    for (const s of this.list) {
      const d = s.d; _v.copy(camera.position).sub(d.center); const dist = _v.length();
      d.sphere ??= new THREE.Sphere(d.center, Math.max(d.w, d.h) * 0.6);
      if (_v.dot(d.normal) <= 0.02 * dist || !_f.intersectsSphere(d.sphere)) continue;
      const px = (d.h / (dist * tanF)) * viewH * 0.5 * Math.max(0.3, _v.dot(d.normal) / dist);
      const wall = d.w > 1.5, fps = clamp(px / (wall ? 18 : 9), 0.6, wall ? 10 : 18) * quality;
      const want = px > 330 ? 2 : 1;
      if (want !== s.scale && now - (s.scaleAt || 0) > 1500) { s.scaleAt = now; this.alloc(s, want); s.last = 0; }
      const wait = 1000 / fps; if (now - s.last >= wait) due.push([(now - s.last) / wait, s]);
    }
    due.sort((a, b) => b[0] - a[0]);
    const t0 = performance.now(); let n = 0;
    for (const [, s] of due) { if (n >= this.maxPerFrame || performance.now() - t0 > this.budgetMs) break; this.paint(s); s.last = now; n++; }
  }
}
