/* Bybit Strategy Lab — движок.
 * Индикаторы, встроенные стратегии, бэктестер (комиссии Bybit, проскальзывание, фандинг,
 * SL/TP/трейлинг, ликвидация, шаг лота), метрики, Монте-Карло, генерация сеток параметров.
 * Работает в окне браузера, в Web Worker и в Node (для тестов). Без зависимостей.
 */
(function (root) {
'use strict';

const isNum = Number.isFinite;
const PLOT = ['#3987e5', '#d95926', '#9085e9', '#c98500', '#d55181'];

function nanArr(n) { const a = new Float64Array(n); a.fill(NaN); return a; }
function L_(x) { return Math.max(1, Math.round(+x || 1)); }
function series(x, n) {
  if (typeof x === 'number') { const a = new Float64Array(n); a.fill(x); return a; }
  return x;
}

/* =============================== ИНДИКАТОРЫ =============================== */
const ta = {};

ta.sma = function (src, len) {
  len = L_(len);
  const n = src.length, out = nanArr(n);
  let sum = 0, bad = 0;
  for (let i = 0; i < n; i++) {
    const v = src[i];
    if (isNum(v)) sum += v; else bad++;
    if (i >= len) { const o = src[i - len]; if (isNum(o)) sum -= o; else bad--; }
    if (i >= len - 1 && bad === 0) out[i] = sum / len;
  }
  return out;
};

function emaAlpha(src, len, alpha) {
  const n = src.length, out = nanArr(n);
  let i = 0;
  while (i < n && !isNum(src[i])) i++;
  if (i + len > n) return out;
  let sum = 0;
  for (let k = 0; k < len; k++) { const v = src[i + k]; sum += isNum(v) ? v : 0; }
  let prev = sum / len;
  out[i + len - 1] = prev;
  for (let k = i + len; k < n; k++) {
    const v = src[k];
    if (isNum(v)) prev = alpha * v + (1 - alpha) * prev;
    out[k] = prev;
  }
  return out;
}
ta.ema = (src, len) => { len = L_(len); return emaAlpha(src, len, 2 / (len + 1)); };
ta.rma = (src, len) => { len = L_(len); return emaAlpha(src, len, 1 / len); };

ta.wma = function (src, len) {
  len = L_(len);
  const n = src.length, out = nanArr(n), den = len * (len + 1) / 2;
  for (let i = len - 1; i < n; i++) {
    let s = 0, ok = true;
    for (let k = 0; k < len; k++) {
      const v = src[i - k];
      if (!isNum(v)) { ok = false; break; }
      s += v * (len - k);
    }
    if (ok) out[i] = s / den;
  }
  return out;
};

ta.hma = function (src, len) {
  len = L_(len);
  const half = ta.wma(src, Math.max(1, Math.floor(len / 2)));
  const full = ta.wma(src, len);
  const n = src.length, diff = nanArr(n);
  for (let i = 0; i < n; i++) diff[i] = 2 * half[i] - full[i];
  return ta.wma(diff, Math.max(1, Math.round(Math.sqrt(len))));
};

ta.stdev = function (src, len) {
  len = L_(len);
  const n = src.length, out = nanArr(n);
  let s = 0, s2 = 0, bad = 0;
  for (let i = 0; i < n; i++) {
    const v = src[i];
    if (isNum(v)) { s += v; s2 += v * v; } else bad++;
    if (i >= len) { const o = src[i - len]; if (isNum(o)) { s -= o; s2 -= o * o; } else bad--; }
    if (i >= len - 1 && bad === 0) { const m = s / len; out[i] = Math.sqrt(Math.max(0, s2 / len - m * m)); }
  }
  return out;
};

function extreme(src, len, isMax) {
  len = L_(len);
  const n = src.length, out = nanArr(n), dq = new Int32Array(n);
  let head = 0, tail = 0;
  for (let i = 0; i < n; i++) {
    const v = src[i];
    if (isNum(v)) {
      while (tail > head && (isMax ? src[dq[tail - 1]] <= v : src[dq[tail - 1]] >= v)) tail--;
      dq[tail++] = i;
    }
    while (tail > head && dq[head] <= i - len) head++;
    if (i >= len - 1 && tail > head) out[i] = src[dq[head]];
  }
  return out;
}
ta.highest = (src, len) => extreme(src, len, true);
ta.lowest = (src, len) => extreme(src, len, false);

ta.shift = function (src, k) {
  k = Math.round(k || 1);
  const n = src.length, out = nanArr(n);
  for (let i = Math.max(0, k); i < n; i++) out[i] = src[i - k];
  return out;
};
ta.change = function (src, k) {
  k = Math.round(k || 1);
  const n = src.length, out = nanArr(n);
  for (let i = k; i < n; i++) out[i] = src[i] - src[i - k];
  return out;
};
ta.roc = function (src, k) {
  k = L_(k);
  const n = src.length, out = nanArr(n);
  for (let i = k; i < n; i++) out[i] = src[i - k] ? 100 * (src[i] / src[i - k] - 1) : NaN;
  return out;
};

ta.tr = function (h, l, c) {
  const n = c.length, out = new Float64Array(n);
  for (let i = 0; i < n; i++) {
    if (i === 0) { out[i] = h[i] - l[i]; continue; }
    const pc = c[i - 1];
    out[i] = Math.max(h[i] - l[i], Math.abs(h[i] - pc), Math.abs(l[i] - pc));
  }
  return out;
};
ta.atr = (h, l, c, len) => ta.rma(ta.tr(h, l, c), len);

ta.rsi = function (src, len) {
  const n = src.length, up = nanArr(n), dn = nanArr(n);
  for (let i = 1; i < n; i++) {
    const ch = src[i] - src[i - 1];
    if (isNum(ch)) { up[i] = ch > 0 ? ch : 0; dn[i] = ch < 0 ? -ch : 0; }
  }
  const ru = ta.rma(up, len), rd = ta.rma(dn, len), out = nanArr(n);
  for (let i = 0; i < n; i++) {
    if (!isNum(ru[i]) || !isNum(rd[i])) continue;
    out[i] = rd[i] === 0 ? 100 : (ru[i] === 0 ? 0 : 100 - 100 / (1 + ru[i] / rd[i]));
  }
  return out;
};

ta.macd = function (src, fast, slow, signal) {
  const f = ta.ema(src, fast), s = ta.ema(src, slow), n = src.length, m = nanArr(n);
  for (let i = 0; i < n; i++) m[i] = f[i] - s[i];
  const sg = ta.ema(m, signal), hist = nanArr(n);
  for (let i = 0; i < n; i++) hist[i] = m[i] - sg[i];
  return { macd: m, signal: sg, hist };
};

ta.bb = function (src, len, mult) {
  const mid = ta.sma(src, len), sd = ta.stdev(src, len), n = src.length;
  const upper = nanArr(n), lower = nanArr(n);
  for (let i = 0; i < n; i++) { upper[i] = mid[i] + mult * sd[i]; lower[i] = mid[i] - mult * sd[i]; }
  return { mid, upper, lower };
};

ta.keltner = function (h, l, c, len, mult) {
  const mid = ta.ema(c, len), a = ta.atr(h, l, c, len), n = c.length;
  const upper = nanArr(n), lower = nanArr(n);
  for (let i = 0; i < n; i++) { upper[i] = mid[i] + mult * a[i]; lower[i] = mid[i] - mult * a[i]; }
  return { mid, upper, lower };
};

ta.donchian = function (h, l, len) {
  const upper = ta.highest(h, len), lower = ta.lowest(l, len), n = h.length, mid = nanArr(n);
  for (let i = 0; i < n; i++) mid[i] = (upper[i] + lower[i]) / 2;
  return { upper, lower, mid };
};

ta.stoch = function (h, l, c, kLen, kSmooth, dLen) {
  const hh = ta.highest(h, kLen), ll = ta.lowest(l, kLen), n = c.length, raw = nanArr(n);
  for (let i = 0; i < n; i++) { const r = hh[i] - ll[i]; raw[i] = r > 0 ? 100 * (c[i] - ll[i]) / r : 50; if (!isNum(hh[i])) raw[i] = NaN; }
  const k = ta.sma(raw, kSmooth || 1), d = ta.sma(k, dLen || 3);
  return { k, d };
};

ta.supertrend = function (h, l, c, len, mult) {
  const n = c.length, a = ta.atr(h, l, c, len);
  const line = nanArr(n), dir = new Int8Array(n);
  let fu = NaN, fl = NaN, d = 1;
  for (let i = 0; i < n; i++) {
    if (!isNum(a[i])) continue;
    const mid = (h[i] + l[i]) / 2, bu = mid + mult * a[i], bl = mid - mult * a[i];
    const pc = i > 0 ? c[i - 1] : c[i];
    const nfu = (!isNum(fu) || bu < fu || pc > fu) ? bu : fu;
    const nfl = (!isNum(fl) || bl > fl || pc < fl) ? bl : fl;
    if (isNum(fu)) {
      if (d === -1 && c[i] > nfu) d = 1;
      else if (d === 1 && c[i] < nfl) d = -1;
    }
    fu = nfu; fl = nfl;
    dir[i] = d;
    line[i] = d === 1 ? fl : fu;
  }
  return { line, dir };
};

ta.adx = function (h, l, c, len) {
  const n = c.length, pdm = nanArr(n), mdm = nanArr(n);
  for (let i = 1; i < n; i++) {
    const up = h[i] - h[i - 1], dn = l[i - 1] - l[i];
    pdm[i] = up > dn && up > 0 ? up : 0;
    mdm[i] = dn > up && dn > 0 ? dn : 0;
  }
  const trr = ta.tr(h, l, c); trr[0] = NaN;
  const atr = ta.rma(trr, len), sp = ta.rma(pdm, len), sm = ta.rma(mdm, len);
  const plus = nanArr(n), minus = nanArr(n), dx = nanArr(n);
  for (let i = 0; i < n; i++) {
    if (!(atr[i] > 0)) continue;
    plus[i] = 100 * sp[i] / atr[i]; minus[i] = 100 * sm[i] / atr[i];
    const s = plus[i] + minus[i];
    dx[i] = s > 0 ? 100 * Math.abs(plus[i] - minus[i]) / s : 0;
  }
  return { adx: ta.rma(dx, len), plus, minus };
};

ta.cci = function (h, l, c, len) {
  len = L_(len);
  const n = c.length, tp = new Float64Array(n);
  for (let i = 0; i < n; i++) tp[i] = (h[i] + l[i] + c[i]) / 3;
  const m = ta.sma(tp, len), out = nanArr(n);
  for (let i = len - 1; i < n; i++) {
    let md = 0;
    for (let k = 0; k < len; k++) md += Math.abs(tp[i - k] - m[i]);
    md /= len;
    out[i] = md > 0 ? (tp[i] - m[i]) / (0.015 * md) : 0;
  }
  return out;
};

ta.zscore = function (src, len) {
  const m = ta.sma(src, len), sd = ta.stdev(src, len), n = src.length, out = nanArr(n);
  for (let i = 0; i < n; i++) out[i] = sd[i] > 0 ? (src[i] - m[i]) / sd[i] : NaN;
  return out;
};

ta.obv = function (c, v) {
  const n = c.length, out = new Float64Array(n);
  for (let i = 1; i < n; i++) out[i] = out[i - 1] + (c[i] > c[i - 1] ? v[i] : c[i] < c[i - 1] ? -v[i] : 0);
  return out;
};

ta.mfi = function (h, l, c, v, len) {
  len = L_(len);
  const n = c.length, out = nanArr(n), pos = new Float64Array(n), neg = new Float64Array(n);
  let prevTp = NaN;
  for (let i = 0; i < n; i++) {
    const tp = (h[i] + l[i] + c[i]) / 3, mf = tp * v[i];
    if (isNum(prevTp)) { if (tp > prevTp) pos[i] = mf; else if (tp < prevTp) neg[i] = mf; }
    prevTp = tp;
  }
  let sp = 0, sn = 0;
  for (let i = 0; i < n; i++) {
    sp += pos[i]; sn += neg[i];
    if (i >= len) { sp -= pos[i - len]; sn -= neg[i - len]; }
    if (i >= len) out[i] = sn === 0 ? 100 : 100 - 100 / (1 + sp / sn);
  }
  return out;
};

/** Скользящий VWAP за len баров */
ta.vwap = function (h, l, c, v, len) {
  len = L_(len);
  const n = c.length, out = nanArr(n);
  let pv = 0, vv = 0;
  for (let i = 0; i < n; i++) {
    const tp = (h[i] + l[i] + c[i]) / 3;
    pv += tp * v[i]; vv += v[i];
    if (i >= len) { const j = i - len, tpj = (h[j] + l[j] + c[j]) / 3; pv -= tpj * v[j]; vv -= v[j]; }
    if (i >= len - 1 && vv > 0) out[i] = pv / vv;
  }
  return out;
};

/** Дневной VWAP (сброс в 00:00 UTC) */
ta.vwapDaily = function (t, h, l, c, v) {
  const n = c.length, out = nanArr(n);
  let pv = 0, vv = 0, day = -1;
  for (let i = 0; i < n; i++) {
    const dd = Math.floor(t[i] / 86400000);
    if (dd !== day) { day = dd; pv = 0; vv = 0; }
    const tp = (h[i] + l[i] + c[i]) / 3;
    pv += tp * v[i]; vv += v[i];
    out[i] = vv > 0 ? pv / vv : tp;
  }
  return out;
};

ta.crossover = function (a, b) {
  const n = a.length, out = new Uint8Array(n);
  b = series(b, n);
  for (let i = 1; i < n; i++) if (a[i] > b[i] && a[i - 1] <= b[i - 1]) out[i] = 1;
  return out;
};
ta.crossunder = function (a, b) {
  const n = a.length, out = new Uint8Array(n);
  b = series(b, n);
  for (let i = 1; i < n; i++) if (a[i] < b[i] && a[i - 1] >= b[i - 1]) out[i] = 1;
  return out;
};
ta.rising = function (src, k) {
  k = L_(k); const n = src.length, out = new Uint8Array(n);
  for (let i = k; i < n; i++) if (src[i] > src[i - k]) out[i] = 1;
  return out;
};
ta.falling = function (src, k) {
  k = L_(k); const n = src.length, out = new Uint8Array(n);
  for (let i = k; i < n; i++) if (src[i] < src[i - k]) out[i] = 1;
  return out;
};

function binop(f) {
  return function (a, b) {
    const n = typeof a === 'number' ? b.length : a.length;
    a = series(a, n); b = series(b, n);
    const out = new Float64Array(n);
    for (let i = 0; i < n; i++) out[i] = f(a[i], b[i]);
    return out;
  };
}
ta.add = binop((x, y) => x + y);
ta.sub = binop((x, y) => x - y);
ta.mul = binop((x, y) => x * y);
ta.div = binop((x, y) => (y === 0 ? NaN : x / y));
ta.max = binop((x, y) => Math.max(x, y));
ta.min = binop((x, y) => Math.min(x, y));
ta.abs = (a) => Float64Array.from(a, Math.abs);
ta.hl2 = (d) => ta.mul(ta.add(d.h, d.l), 0.5);
ta.hlc3 = (d) => Float64Array.from(d.c, (c, i) => (d.h[i] + d.l[i] + c) / 3);
ta.ohlc4 = (d) => Float64Array.from(d.c, (c, i) => (d.o[i] + d.h[i] + d.l[i] + c) / 4);
ta.signals = (n) => ({ longEntry: new Uint8Array(n), longExit: new Uint8Array(n), shortEntry: new Uint8Array(n), shortExit: new Uint8Array(n) });
ta.nan = nanArr;

/* =========================== ВСТРОЕННЫЕ СТРАТЕГИИ =========================== */
const sig = ta.signals;
const P = (key, label, def, min, max, step, type) => ({ key, label, type: type || (Number.isInteger(def) && Number.isInteger(step) ? 'int' : 'float'), default: def, min, max, step });

const STRATEGIES = [
  {
    id: 'ema_cross', name: 'Пересечение EMA',
    desc: 'Лонг, когда быстрая EMA пересекает медленную снизу вверх; шорт — сверху вниз. Опционально торговать только по направлению длинной EMA-тренда.',
    params: [P('fast', 'Быстрая EMA', 12, 3, 60, 1), P('slow', 'Медленная EMA', 26, 10, 200, 2), P('trend', 'EMA-фильтр тренда (0 = выкл.)', 0, 0, 400, 50)],
    valid: (p) => p.fast < p.slow,
    signals(d, p, ta) {
      const n = d.c.length, f = ta.ema(d.c, p.fast), s = ta.ema(d.c, p.slow);
      const up = ta.crossover(f, s), dn = ta.crossunder(f, s), r = sig(n);
      const tr = p.trend > 0 ? ta.ema(d.c, p.trend) : null;
      for (let i = 0; i < n; i++) {
        if (up[i]) { r.shortExit[i] = 1; if (!tr || d.c[i] > tr[i]) r.longEntry[i] = 1; }
        if (dn[i]) { r.longExit[i] = 1; if (!tr || d.c[i] < tr[i]) r.shortEntry[i] = 1; }
      }
      r.plots = [{ name: 'EMA ' + p.fast, data: f, color: PLOT[0] }, { name: 'EMA ' + p.slow, data: s, color: PLOT[1] }];
      if (tr) r.plots.push({ name: 'EMA ' + p.trend, data: tr, color: PLOT[2], width: 2 });
      return r;
    },
  },
  {
    id: 'supertrend', name: 'SuperTrend',
    desc: 'Трендовая стратегия: вход при смене направления индикатора SuperTrend (ATR-канал), выход — при обратной смене.',
    params: [P('len', 'Период ATR', 10, 5, 50, 1), P('mult', 'Множитель ATR', 3, 1, 6, 0.25, 'float')],
    signals(d, p, ta) {
      const n = d.c.length, st = ta.supertrend(d.h, d.l, d.c, p.len, p.mult), r = sig(n);
      const up = nanArr(n), dn = nanArr(n);
      for (let i = 1; i < n; i++) {
        if (st.dir[i] === 1) up[i] = st.line[i]; else if (st.dir[i] === -1) dn[i] = st.line[i];
        if (st.dir[i] === 1 && st.dir[i - 1] === -1) { r.longEntry[i] = 1; r.shortExit[i] = 1; }
        if (st.dir[i] === -1 && st.dir[i - 1] === 1) { r.shortEntry[i] = 1; r.longExit[i] = 1; }
      }
      r.plots = [{ name: 'ST вверх', data: up, color: '#199e70', width: 2 }, { name: 'ST вниз', data: dn, color: '#e66767', width: 2 }];
      return r;
    },
  },
  {
    id: 'rsi_revert', name: 'RSI: возврат к среднему',
    desc: 'Лонг, когда RSI выходит из зоны перепроданности вверх; выход — при достижении уровня выхода. Шорт зеркально. Опционально — фильтр SMA-тренда.',
    params: [P('len', 'Период RSI', 14, 2, 40, 1), P('lower', 'Перепроданность', 30, 10, 45, 5), P('upper', 'Перекупленность', 70, 55, 90, 5),
      P('exitL', 'Выход из лонга (RSI ≥)', 55, 40, 80, 5), P('exitS', 'Выход из шорта (RSI ≤)', 45, 20, 60, 5), P('trend', 'SMA-фильтр тренда (0 = выкл.)', 0, 0, 400, 50)],
    valid: (p) => p.lower < p.upper,
    signals(d, p, ta) {
      const n = d.c.length, r = sig(n), x = ta.rsi(d.c, p.len);
      const tr = p.trend > 0 ? ta.sma(d.c, p.trend) : null;
      const le = ta.crossover(x, p.lower), se = ta.crossunder(x, p.upper);
      for (let i = 1; i < n; i++) {
        if (le[i] && (!tr || d.c[i] > tr[i])) r.longEntry[i] = 1;
        if (se[i] && (!tr || d.c[i] < tr[i])) r.shortEntry[i] = 1;
        if (x[i] >= p.exitL) r.longExit[i] = 1;
        if (x[i] <= p.exitS) r.shortExit[i] = 1;
      }
      r.plots = [{ name: 'RSI ' + p.len, data: x, color: PLOT[2], pane: 'osc', levels: [p.lower, p.upper], range: [0, 100] }];
      if (tr) r.plots.push({ name: 'SMA ' + p.trend, data: tr, color: PLOT[3] });
      return r;
    },
  },
  {
    id: 'bb_revert', name: 'Полосы Боллинджера: возврат',
    desc: 'Лонг, когда цена закрывается ниже нижней полосы; выход — при возврате к средней линии. Шорт — от верхней полосы.',
    params: [P('len', 'Период', 20, 10, 60, 2), P('mult', 'Ширина (σ)', 2, 1, 3.5, 0.25, 'float')],
    signals(d, p, ta) {
      const n = d.c.length, r = sig(n), b = ta.bb(d.c, p.len, p.mult);
      const le = ta.crossunder(d.c, b.lower), se = ta.crossover(d.c, b.upper);
      for (let i = 1; i < n; i++) {
        if (le[i]) r.longEntry[i] = 1;
        if (se[i]) r.shortEntry[i] = 1;
        if (d.c[i] >= b.mid[i]) r.longExit[i] = 1;
        if (d.c[i] <= b.mid[i]) r.shortExit[i] = 1;
      }
      r.plots = [{ name: 'BB верх', data: b.upper, color: PLOT[0] }, { name: 'BB середина', data: b.mid, color: PLOT[3], dash: [4, 4] }, { name: 'BB низ', data: b.lower, color: PLOT[0] }];
      return r;
    },
  },
  {
    id: 'donchian', name: 'Пробой Дончиана (Turtle)',
    desc: 'Лонг на пробое максимума за N баров, выход — при пробое минимума за M баров (система «черепах»). Шорт зеркально.',
    params: [P('entry', 'Канал входа, баров', 20, 5, 100, 5), P('exit', 'Канал выхода, баров', 10, 3, 60, 1)],
    signals(d, p, ta) {
      const n = d.c.length, r = sig(n);
      const hi = ta.shift(ta.highest(d.h, p.entry), 1), lo = ta.shift(ta.lowest(d.l, p.entry), 1);
      const xhi = ta.shift(ta.highest(d.h, p.exit), 1), xlo = ta.shift(ta.lowest(d.l, p.exit), 1);
      for (let i = 1; i < n; i++) {
        if (d.c[i] > hi[i]) r.longEntry[i] = 1;
        if (d.c[i] < lo[i]) r.shortEntry[i] = 1;
        if (d.c[i] < xlo[i]) r.longExit[i] = 1;
        if (d.c[i] > xhi[i]) r.shortExit[i] = 1;
      }
      r.plots = [{ name: 'Макс ' + p.entry, data: hi, color: PLOT[0] }, { name: 'Мин ' + p.entry, data: lo, color: PLOT[1] }];
      return r;
    },
  },
  {
    id: 'macd', name: 'MACD',
    desc: 'Пересечение линии MACD и сигнальной. Фильтр «по нулю»: лонг только при MACD > 0, шорт — при MACD < 0.',
    params: [P('fast', 'Быстрая', 12, 4, 30, 1), P('slow', 'Медленная', 26, 10, 80, 2), P('signal', 'Сигнальная', 9, 3, 20, 1), P('zero', 'Фильтр по нулю (0/1)', 0, 0, 1, 1, 'bool')],
    valid: (p) => p.fast < p.slow,
    signals(d, p, ta) {
      const n = d.c.length, r = sig(n), m = ta.macd(d.c, p.fast, p.slow, p.signal);
      const up = ta.crossover(m.macd, m.signal), dn = ta.crossunder(m.macd, m.signal);
      for (let i = 1; i < n; i++) {
        if (up[i]) { r.shortExit[i] = 1; if (!p.zero || m.macd[i] > 0) r.longEntry[i] = 1; }
        if (dn[i]) { r.longExit[i] = 1; if (!p.zero || m.macd[i] < 0) r.shortEntry[i] = 1; }
      }
      r.plots = [{ name: 'MACD', data: m.macd, color: PLOT[0], pane: 'osc', levels: [0] }, { name: 'Сигнал', data: m.signal, color: PLOT[1], pane: 'osc' }];
      return r;
    },
  },
  {
    id: 'adx_di', name: 'ADX + DI (сила тренда)',
    desc: 'Вход при пересечении +DI/−DI, только если ADX выше порога (тренд достаточно сильный). Выход — при обратном пересечении.',
    params: [P('len', 'Период', 14, 7, 30, 1), P('thr', 'Порог ADX', 25, 10, 40, 5)],
    signals(d, p, ta) {
      const n = d.c.length, r = sig(n), a = ta.adx(d.h, d.l, d.c, p.len);
      const up = ta.crossover(a.plus, a.minus), dn = ta.crossunder(a.plus, a.minus);
      for (let i = 1; i < n; i++) {
        if (up[i]) { r.shortExit[i] = 1; if (a.adx[i] > p.thr) r.longEntry[i] = 1; }
        if (dn[i]) { r.longExit[i] = 1; if (a.adx[i] > p.thr) r.shortEntry[i] = 1; }
      }
      r.plots = [{ name: 'ADX', data: a.adx, color: PLOT[3], pane: 'osc', levels: [p.thr] }, { name: '+DI', data: a.plus, color: '#199e70', pane: 'osc' }, { name: '−DI', data: a.minus, color: '#e66767', pane: 'osc' }];
      return r;
    },
  },
  {
    id: 'hma_trend', name: 'Разворот Hull MA',
    desc: 'Лонг, когда HMA разворачивается вверх, шорт — когда вниз. Быстрая трендовая стратегия с малой задержкой.',
    params: [P('len', 'Период HMA', 55, 10, 200, 5)],
    signals(d, p, ta) {
      const n = d.c.length, r = sig(n), h = ta.hma(d.c, p.len);
      for (let i = 2; i < n; i++) {
        if (h[i] > h[i - 1] && h[i - 1] <= h[i - 2]) { r.longEntry[i] = 1; r.shortExit[i] = 1; }
        if (h[i] < h[i - 1] && h[i - 1] >= h[i - 2]) { r.shortEntry[i] = 1; r.longExit[i] = 1; }
      }
      r.plots = [{ name: 'HMA ' + p.len, data: h, color: PLOT[0], width: 2 }];
      return r;
    },
  },
  {
    id: 'zscore', name: 'Z-score: возврат к среднему',
    desc: 'Лонг, когда цена ушла ниже среднего на N стандартных отклонений; выход — при возврате к −выход·σ. Шорт зеркально.',
    params: [P('len', 'Окно', 50, 10, 200, 10), P('entry', 'Вход, σ', 2, 1, 3.5, 0.25, 'float'), P('exit', 'Выход, σ', 0.5, 0, 1.5, 0.25, 'float')],
    valid: (p) => p.exit < p.entry,
    signals(d, p, ta) {
      const n = d.c.length, r = sig(n), z = ta.zscore(d.c, p.len);
      for (let i = 1; i < n; i++) {
        if (z[i] < -p.entry && z[i - 1] >= -p.entry) r.longEntry[i] = 1;
        if (z[i] > p.entry && z[i - 1] <= p.entry) r.shortEntry[i] = 1;
        if (z[i] >= -p.exit) r.longExit[i] = 1;
        if (z[i] <= p.exit) r.shortExit[i] = 1;
      }
      r.plots = [{ name: 'Z-score', data: z, color: PLOT[2], pane: 'osc', levels: [-p.entry, 0, p.entry] }];
      return r;
    },
  },
  {
    id: 'stoch', name: 'Стохастик',
    desc: 'Лонг при пересечении %K выше %D в зоне перепроданности, шорт — ниже %D в зоне перекупленности. Выход по обратному пересечению.',
    params: [P('k', 'Период %K', 14, 5, 30, 1), P('smooth', 'Сглаживание %K', 3, 1, 5, 1), P('dl', 'Период %D', 3, 2, 6, 1), P('lo', 'Нижний уровень', 20, 10, 35, 5), P('hi', 'Верхний уровень', 80, 65, 90, 5)],
    signals(d, p, ta) {
      const n = d.c.length, r = sig(n), s = ta.stoch(d.h, d.l, d.c, p.k, p.smooth, p.dl);
      const up = ta.crossover(s.k, s.d), dn = ta.crossunder(s.k, s.d);
      for (let i = 1; i < n; i++) {
        if (up[i]) { r.shortExit[i] = 1; if (s.k[i] < p.lo + 10) r.longEntry[i] = 1; }
        if (dn[i]) { r.longExit[i] = 1; if (s.k[i] > p.hi - 10) r.shortEntry[i] = 1; }
      }
      r.plots = [{ name: '%K', data: s.k, color: PLOT[0], pane: 'osc', levels: [p.lo, p.hi], range: [0, 100] }, { name: '%D', data: s.d, color: PLOT[1], pane: 'osc' }];
      return r;
    },
  },
  {
    id: 'hold', name: 'Купить и держать (эталон)',
    desc: 'Открывает лонг в начале периода и держит до конца — с учётом комиссий, фандинга и плеча. Удобно как эталон для сравнения.',
    params: [],
    signals(d) {
      const n = d.c.length, r = sig(n);
      r.longEntry.fill(1);
      return r;
    },
  },
];

/* =============================== БЭКТЕСТЕР =============================== */
const DEFAULTS = {
  category: 'linear', capital: 10000, sizing: 'pct', sizeValue: 100, leverage: 1, direction: 'both', marginMode: 'cross',
  execOn: 'open', reverse: true,
  takerFee: 0.055, makerFee: 0.02, tpMaker: true, slippage: 0.02,
  slType: 'none', slValue: 2, tpType: 'none', tpValue: 4, trailType: 'none', trailValue: 2, atrLen: 14, maxBars: 0,
  funding: true, liquidation: true, mmr: 0.5, qtyStep: 0, minQty: 0,
};

function intervalMinutes(iv) { return iv === 'D' ? 1440 : iv === 'W' ? 10080 : +iv; }

/** Суммарная ставка фандинга, приходящаяся на открытие каждого бара */
function fundingPerBar(t, fundT, fundR, stepMs) {
  const n = t.length, out = new Float64Array(n);
  if (!fundT || !fundT.length) return out;
  let j = 0;
  for (let i = 0; i < n; i++) {
    const a = t[i], b = a + stepMs;
    while (j < fundT.length && fundT[j] < a) j++;
    let k = j, s = 0;
    while (k < fundT.length && fundT[k] < b) { s += fundR[k]; k++; }
    out[i] = s; j = k;
  }
  return out;
}

let SCRATCH = new Float64Array(0);
function scratch(n) { if (SCRATCH.length < n) SCRATCH = new Float64Array(n); return SCRATCH; }

function cachedAtr(d, len) {
  if (!d._atr) Object.defineProperty(d, '_atr', { value: {}, enumerable: false });
  const k = String(len);
  if (!d._atr[k]) d._atr[k] = ta.atr(d.h, d.l, d.c, len);
  return d._atr[k];
}

function normalizeSignals(s, n) {
  s = s || {};
  for (const k of ['longEntry', 'longExit', 'shortEntry', 'shortExit']) if (!s[k] || s[k].length !== n) s[k] = s[k] && s[k].length ? s[k] : new Uint8Array(n);
  return s;
}

/**
 * Бэктест одной позиции (без пирамидинга) по барам.
 * Сигнал на закрытии бара i исполняется на открытии бара i+1 (execOn='open') или на закрытии i (execOn='close').
 * Внутри бара: гэп на открытии → ликвидация → стоп → тейк (консервативно: стоп раньше тейка).
 */
function backtest(d, sg, st, o) {
  o = o || {};
  const s = Object.assign({}, DEFAULTS, st);
  const n = d.c.length;
  const from = Math.max(0, o.from | 0);
  const to = Math.min(n - 1, o.to == null ? n - 1 : o.to);
  const span = Math.max(0, to - from + 1);
  const res = { trades: [], from, to, span, eq: null, fees: 0, funding: 0, exposure: 0, final: +s.capital, liq: 0, ruined: false };
  if (span < 2) { res.eq = new Float64Array(span).fill(+s.capital); return res; }

  const spot = s.category === 'spot';
  const Lev = spot ? 1 : Math.max(1, +s.leverage || 1);
  const fT = s.takerFee / 100, fM = s.makerFee / 100, slip = s.slippage / 100, mmr = s.mmr / 100;
  const allowLong = s.direction !== 'short';
  const allowShort = !spot && s.direction !== 'long';
  const execClose = s.execOn === 'close';
  const atr = (s.slType === 'atr' || s.tpType === 'atr' || s.trailType === 'atr') ? cachedAtr(d, s.atrLen || 14) : null;
  const fund = (!spot && s.funding && o.fundBar) ? o.fundBar : null;
  const liqOn = !spot && s.liquidation;
  const isolated = s.marginMode === 'isolated';
  const LE = sg.longEntry, LX = sg.longExit, SE = sg.shortEntry, SX = sg.shortExit;
  const T = d.t, O = d.o, H = d.h, Lw = d.l, C = d.c;
  const eq = o.equity ? new Float64Array(span) : scratch(span);
  const trades = res.trades;

  let cash = +s.capital;
  let pos = 0, qty = 0, entryPx = 0, entryIdx = -1, entryFee = 0, tradeFund = 0, eqAtEntry = 0, notional0 = 0, margin0 = 0;
  let sl = NaN, tp = NaN, trail = NaN, trailK = NaN, hiW = 0, loW = 0;
  let pendExit = false, pendEnter = 0, pendSig = -1;
  let totalFees = 0, totalFund = 0, barsIn = 0, ruined = false;

  const sell = (p) => p * (1 - slip), buy = (p) => p * (1 + slip);

  function openPos(dir, price, i, si) {
    if (cash <= 0) return;
    const px = dir > 0 ? buy(price) : sell(price);
    const a = atr ? atr[si] : NaN;
    let stop = NaN;
    if (s.slType === 'pct' && s.slValue > 0) stop = px * (1 - dir * s.slValue / 100);
    else if (s.slType === 'atr' && isNum(a) && s.slValue > 0) stop = px - dir * s.slValue * a;
    let notional;
    if (s.sizing === 'fixed') notional = +s.sizeValue;
    else if (s.sizing === 'risk') notional = (isNum(stop) && stop !== px) ? cash * (s.sizeValue / 100) / Math.abs(px - stop) * px : cash;
    else notional = cash * Math.min(100, Math.max(0, +s.sizeValue)) / 100 * Lev;
    notional = Math.min(notional, cash / (1 / Lev + fT));
    if (!(notional > 0)) return;
    let q = notional / px;
    if (s.qtyStep > 0) q = Math.floor(q / s.qtyStep + 1e-9) * s.qtyStep;
    if (!(q > 0) || (s.minQty > 0 && q < s.minQty - 1e-12)) return;
    notional = q * px;
    const fee = notional * fT;
    eqAtEntry = cash;
    cash -= fee; totalFees += fee;
    pos = dir; qty = q; entryPx = px; entryIdx = i; entryFee = fee; tradeFund = 0; notional0 = notional; margin0 = notional / Lev;
    sl = stop; tp = NaN; trail = NaN; trailK = NaN;
    if (s.tpType === 'pct' && s.tpValue > 0) tp = px * (1 + dir * s.tpValue / 100);
    else if (s.tpType === 'atr' && isNum(a) && s.tpValue > 0) tp = px + dir * s.tpValue * a;
    else if (s.tpType === 'rr' && isNum(stop) && s.tpValue > 0) tp = px + dir * s.tpValue * Math.abs(px - stop);
    if (s.trailType === 'pct' && s.trailValue > 0) { trailK = s.trailValue / 100; trail = px * (1 - dir * trailK); }
    else if (s.trailType === 'atr' && isNum(a) && s.trailValue > 0) { trailK = s.trailValue; trail = px - dir * trailK * a; }
    hiW = px; loW = px;
  }

  function closePos(px, i, reason, maker) {
    const gross = (px - entryPx) * qty * pos;
    const fee = px * qty * (maker ? fM : fT);
    cash += gross - fee; totalFees += fee;
    pushTrade(px, i, reason, fee);
  }

  function liquidate(i, px) {
    const coll = isolated ? margin0 : cash;
    cash -= Math.max(0, coll);
    res.liq++;
    pushTrade(px, i, 'liq', 0);
  }

  function pushTrade(px, i, reason, exitFee) {
    const pnl = cash - eqAtEntry;
    const mae = pos > 0 ? (loW / entryPx - 1) * 100 : (1 - hiW / entryPx) * 100;
    const mfe = pos > 0 ? (hiW / entryPx - 1) * 100 : (1 - loW / entryPx) * 100;
    trades.push({
      dir: pos, ei: entryIdx, et: T[entryIdx], ep: entryPx, xi: i, xt: T[i], xp: px, qty, notional: notional0,
      pnl, pct: eqAtEntry > 0 ? pnl / eqAtEntry * 100 : 0, fees: entryFee + exitFee, fund: tradeFund,
      reason, bars: i - entryIdx, mae: Math.min(0, mae), mfe: Math.max(0, mfe),
    });
    pos = 0; qty = 0; sl = NaN; tp = NaN; trail = NaN;
  }

  function liqPrice() {
    const coll = isolated ? margin0 : cash;
    return entryPx - pos * (coll - mmr * notional0) / qty;
  }

  function checkExits(i) {
    const o_ = O[i], h_ = H[i], l_ = Lw[i];
    let stop = sl, why = 'sl';
    if (isNum(trail) && (!isNum(stop) || (pos > 0 ? trail > stop : trail < stop))) { stop = trail; why = 'trail'; }
    const liq = liqOn ? liqPrice() : NaN;
    if (pos > 0) {
      const liqFirst = isNum(liq) && (!isNum(stop) || liq >= stop);
      if (liqFirst && l_ <= liq) { liquidate(i, Math.min(o_, liq)); return true; }
      if (isNum(stop) && o_ <= stop) { if (isNum(liq) && o_ <= liq) liquidate(i, o_); else closePos(sell(o_), i, why, false); return true; }
      if (isNum(tp) && o_ >= tp) { closePos(o_, i, 'tp', s.tpMaker); return true; }
      if (isNum(stop) && l_ <= stop) { closePos(sell(stop), i, why, false); return true; }
      if (isNum(liq) && l_ <= liq) { liquidate(i, liq); return true; }
      if (isNum(tp) && h_ >= tp) { closePos(tp, i, 'tp', s.tpMaker); return true; }
    } else {
      const liqFirst = isNum(liq) && (!isNum(stop) || liq <= stop);
      if (liqFirst && h_ >= liq) { liquidate(i, Math.max(o_, liq)); return true; }
      if (isNum(stop) && o_ >= stop) { if (isNum(liq) && o_ >= liq) liquidate(i, o_); else closePos(buy(o_), i, why, false); return true; }
      if (isNum(tp) && o_ <= tp) { closePos(o_, i, 'tp', s.tpMaker); return true; }
      if (isNum(stop) && h_ >= stop) { closePos(buy(stop), i, why, false); return true; }
      if (isNum(liq) && h_ >= liq) { liquidate(i, liq); return true; }
      if (isNum(tp) && l_ <= tp) { closePos(tp, i, 'tp', s.tpMaker); return true; }
    }
    return false;
  }

  for (let i = from; i <= to; i++) {
    // 1) фандинг на открытии бара (для позиции, удерживаемой через отметку)
    if (pos !== 0 && fund !== null) {
      const r = fund[i];
      if (r !== 0) { const pay = pos * qty * O[i] * r; cash -= pay; tradeFund -= pay; totalFund -= pay; }
    }
    // 2) отложенные рыночные ордера по открытию
    if (pendExit && pos !== 0) closePos(pos > 0 ? sell(O[i]) : buy(O[i]), i, 'signal', false);
    if (pendEnter !== 0 && pos === 0 && !ruined) openPos(pendEnter, O[i], i, pendSig);
    pendExit = false; pendEnter = 0;
    // 3) внутрибарные выходы
    if (pos !== 0) {
      if (H[i] > hiW) hiW = H[i];
      if (Lw[i] < loW) loW = Lw[i];
      if (!checkExits(i)) {
        if (isNum(trailK)) {
          if (s.trailType === 'pct') trail = pos > 0 ? Math.max(trail, hiW * (1 - trailK)) : Math.min(trail, loW * (1 + trailK));
          else if (atr && isNum(atr[i])) trail = pos > 0 ? Math.max(trail, hiW - trailK * atr[i]) : Math.min(trail, loW + trailK * atr[i]);
        }
        if (s.maxBars > 0 && i - entryIdx >= s.maxBars) closePos(pos > 0 ? sell(C[i]) : buy(C[i]), i, 'time', false);
      }
    }
    // 4) сигналы на закрытии бара
    if (!ruined && (execClose || i < to)) {
      let wantExit = false, enter = 0;
      if (pos > 0 && (LX[i] || (s.reverse && SE[i]))) wantExit = true;
      else if (pos < 0 && (SX[i] || (s.reverse && LE[i]))) wantExit = true;
      if ((pos === 0 || wantExit) && !(LE[i] && SE[i])) {
        if (LE[i] && allowLong && pos <= 0) enter = 1;
        else if (SE[i] && allowShort && pos >= 0) enter = -1;
      }
      if (execClose) {
        if (wantExit) closePos(pos > 0 ? sell(C[i]) : buy(C[i]), i, 'signal', false);
        if (enter !== 0 && pos === 0) openPos(enter, C[i], i, i);
      } else { pendExit = wantExit; pendEnter = enter; pendSig = i; }
    }
    if (pos !== 0) barsIn++;
    eq[i - from] = cash + (pos !== 0 ? (C[i] - entryPx) * qty * pos : 0);
    if (cash <= 1e-9 && pos === 0) ruined = true;
  }
  if (pos !== 0) { closePos(pos > 0 ? sell(C[to]) : buy(C[to]), to, 'end', false); eq[span - 1] = cash; }

  res.eq = eq; res.fees = totalFees; res.funding = totalFund; res.exposure = barsIn / span; res.final = cash; res.ruined = ruined;
  return res;
}

/* ================================ МЕТРИКИ ================================ */
function computeMetrics(bt, d, st, iv) {
  const s = Object.assign({}, DEFAULTS, st);
  const cap = +s.capital, eq = bt.eq, span = bt.span;
  const ivMin = intervalMinutes(iv || '60');
  const bpy = 525600 / ivMin;
  let peak = cap, maxDD = 0, maxDDAbs = 0, peakIdx = -1, maxDur = 0, prev = cap;
  let sum = 0, sum2 = 0, dsum2 = 0, ulc = 0;
  for (let k = 0; k < span; k++) {
    const e = eq[k];
    const r = prev > 0 ? e / prev - 1 : 0;
    sum += r; sum2 += r * r; if (r < 0) dsum2 += r * r;
    prev = e;
    if (e >= peak) { peak = e; peakIdx = k; }
    else if (k - peakIdx > maxDur) maxDur = k - peakIdx;
    const dd = peak > 0 ? (peak - e) / peak : 0;
    if (dd > maxDD) maxDD = dd;
    if (peak - e > maxDDAbs) maxDDAbs = peak - e;
    ulc += dd * dd;
  }
  const final = span ? eq[span - 1] : cap;
  const mean = span ? sum / span : 0;
  const sd = span ? Math.sqrt(Math.max(0, sum2 / span - mean * mean)) : 0;
  const dsd = span ? Math.sqrt(dsum2 / span) : 0;
  const t0 = d.t[bt.from], t1 = d.t[bt.to] + ivMin * 60000;
  const years = Math.max(1e-9, (t1 - t0) / (365 * 86400000));
  const totRet = final / cap - 1;
  const cagr = final > 0 ? Math.pow(final / cap, 1 / years) - 1 : -1;

  const tr = bt.trades, N = tr.length;
  let gp = 0, gl = 0, wins = 0, sumW = 0, sumL = 0, best = -Infinity, worst = Infinity;
  let cw = 0, cl = 0, mcw = 0, mcl = 0, bars = 0, pS = 0, pS2 = 0;
  let lN = 0, lW = 0, lP = 0, sN = 0, sW = 0, sP = 0;
  for (let k = 0; k < N; k++) {
    const t = tr[k], p = t.pnl;
    if (p > 0) { gp += p; wins++; sumW += p; cw++; cl = 0; if (cw > mcw) mcw = cw; }
    else { gl -= p; sumL += p; cl++; cw = 0; if (cl > mcl) mcl = cl; }
    if (t.pct > best) best = t.pct;
    if (t.pct < worst) worst = t.pct;
    bars += t.bars; pS += t.pct; pS2 += t.pct * t.pct;
    if (t.dir > 0) { lN++; lP += p; if (p > 0) lW++; } else { sN++; sP += p; if (p > 0) sW++; }
  }
  const losses = N - wins;
  const avgW = wins ? sumW / wins : 0, avgL = losses ? sumL / losses : 0;
  const winRate = N ? wins / N : 0;
  const payoff = avgL < 0 ? avgW / -avgL : (avgW > 0 ? 99 : 0);
  const pm = N ? pS / N : 0, psd = N > 1 ? Math.sqrt(Math.max(0, (pS2 - N * pm * pm) / (N - 1))) : 0;
  const c0 = d.c[bt.from], c1 = d.c[bt.to];
  const bh = c0 > 0 ? (c1 / c0 - 1) * 100 : 0;
  const days = (t1 - t0) / 86400000;
  return {
    final, netProfit: final - cap, netPct: totRet * 100, cagr: cagr * 100,
    maxDD: maxDD * 100, maxDDAbs, maxDDDays: maxDur * ivMin / 1440,
    sharpe: sd > 0 ? mean / sd * Math.sqrt(bpy) : 0,
    sortino: dsd > 0 ? mean / dsd * Math.sqrt(bpy) : 0,
    calmar: maxDD > 0 ? cagr / maxDD : (cagr > 0 ? 99 : 0),
    ulcer: span ? Math.sqrt(ulc / span) * 100 : 0,
    retDD: maxDD > 0 ? totRet / maxDD : (totRet > 0 ? 99 : 0),
    recovery: maxDDAbs > 0 ? (final - cap) / maxDDAbs : 0,
    trades: N, wins, losses, winRate: winRate * 100,
    pf: gl > 0 ? gp / gl : (gp > 0 ? 99 : 0), grossProfit: gp, grossLoss: gl,
    avgWin: avgW, avgLoss: avgL, payoff, expectancy: N ? (gp - gl) / N : 0, expectancyPct: pm,
    best: N ? best : 0, worst: N ? worst : 0, maxConsW: mcw, maxConsL: mcl,
    avgBars: N ? bars / N : 0, avgHoldH: N ? bars / N * ivMin / 60 : 0,
    exposure: bt.exposure * 100, fees: bt.fees, funding: bt.funding,
    longN: lN, longWin: lN ? lW / lN * 100 : 0, longPnl: lP, shortN: sN, shortWin: sN ? sW / sN * 100 : 0, shortPnl: sP,
    sqn: psd > 0 ? Math.sqrt(Math.min(N, 100)) * pm / psd : 0,
    kelly: payoff > 0 ? (winRate - (1 - winRate) / payoff) * 100 : 0,
    bhPct: bh, alpha: totRet * 100 - bh, liq: bt.liq, days, tradesPerMonth: days > 0 ? N / days * 30.44 : 0,
    ruined: bt.ruined,
  };
}

const OBJECTIVES = {
  sharpe: { label: 'Шарп', get: (m) => m.sharpe, mid: 0 },
  netPct: { label: 'Доходность, %', get: (m) => m.netPct, mid: 0 },
  retDD: { label: 'Доходность / просадка', get: (m) => m.retDD, mid: 0 },
  calmar: { label: 'Калмар', get: (m) => m.calmar, mid: 0 },
  sortino: { label: 'Сортино', get: (m) => m.sortino, mid: 0 },
  pf: { label: 'Профит-фактор', get: (m) => m.pf, mid: 1 },
  sqn: { label: 'SQN', get: (m) => m.sqn, mid: 0 },
  expectancyPct: { label: 'Матожидание сделки, %', get: (m) => m.expectancyPct, mid: 0 },
  winRate: { label: 'Доля прибыльных, %', get: (m) => m.winRate, mid: 50 },
};

/* ======================== ЗАПУСК СТРАТЕГИИ ЦЕЛИКОМ ======================== */
function prepare(d, fundT, fundR, iv) {
  const step = intervalMinutes(iv) * 60000;
  return { fundBar: fundT && fundT.length ? fundingPerBar(d.t, fundT, fundR, step) : null };
}

function paramsWithDefaults(strat, p) {
  const out = {};
  for (const q of strat.params || []) out[q.key] = p && p[q.key] != null && p[q.key] !== '' ? +p[q.key] : q.default;
  if (p) for (const k in p) if (!(k in out)) out[k] = p[k];
  return out;
}

/** Полный прогон: сигналы + бэктест + метрики (+ ряды для графиков) */
function run(d, strat, params, settings, o) {
  o = o || {};
  const p = paramsWithDefaults(strat, params);
  const n = d.c.length;
  const sg = normalizeSignals(strat.signals(d, p, ta), n);
  const bt = backtest(d, sg, settings, { from: o.from, to: o.to, fundBar: o.fundBar, equity: true });
  const m = computeMetrics(bt, d, settings, o.iv);
  return { params: p, signals: sg, plots: sg.plots || [], bt, m };
}

/** Быстрая оценка для оптимизатора: только метрики */
function evaluate(d, strat, params, settings, o) {
  o = o || {};
  const p = paramsWithDefaults(strat, params);
  if (strat.valid && !strat.valid(p)) return null;
  const sg = normalizeSignals(strat.signals(d, p, ta), d.c.length);
  const bt = backtest(d, sg, settings, { from: o.from, to: o.to, fundBar: o.fundBar, equity: false });
  return computeMetrics(bt, d, settings, o.iv);
}

/* ============================ ПАРАМЕТРЫ / СЕТКИ ============================ */
function rangeValues(r) {
  const out = [];
  const isInt = r.type === 'int' || r.type === 'bool';
  const min = +r.min, max = +r.max, step = +r.step;
  if (!(step > 0) || !(max > min)) return [isInt ? Math.round(min) : min];
  for (let k = 0; ; k++) {
    const v = min + k * step;
    if (v > max + step * 1e-6) break;
    out.push(isInt ? Math.round(v) : +v.toFixed(8));
    if (out.length > 100000) break;
  }
  return Array.from(new Set(out));
}

function countCombos(ranges) {
  let c = 1;
  for (const r of ranges) c *= rangeValues(r).length;
  return c;
}

function gridCombos(base, ranges, limit) {
  const lists = ranges.map(rangeValues);
  const out = [];
  const idx = new Array(ranges.length).fill(0);
  limit = limit || 2e6;
  if (!ranges.length) return [Object.assign({}, base)];
  for (;;) {
    const p = Object.assign({}, base);
    for (let k = 0; k < ranges.length; k++) p[ranges[k].key] = lists[k][idx[k]];
    out.push(p);
    if (out.length >= limit) break;
    let k = ranges.length - 1;
    while (k >= 0) { idx[k]++; if (idx[k] < lists[k].length) break; idx[k] = 0; k--; }
    if (k < 0) break;
  }
  return out;
}

function mulberry32(a) {
  return function () {
    a |= 0; a = a + 0x6D2B79F5 | 0;
    let t = Math.imul(a ^ a >>> 15, 1 | a);
    t = t + Math.imul(t ^ t >>> 7, 61 | t) ^ t;
    return ((t ^ t >>> 14) >>> 0) / 4294967296;
  };
}

function randomCombos(base, ranges, count, seed) {
  const lists = ranges.map(rangeValues);
  const total = lists.reduce((a, l) => a * l.length, 1);
  if (total <= count) return gridCombos(base, ranges);
  const rnd = mulberry32(seed || 7), seen = new Set(), out = [];
  let guard = 0;
  while (out.length < count && guard++ < count * 20) {
    const p = Object.assign({}, base), key = [];
    for (let k = 0; k < ranges.length; k++) { const v = lists[k][Math.floor(rnd() * lists[k].length)]; p[ranges[k].key] = v; key.push(v); }
    const ks = key.join('|');
    if (seen.has(ks)) continue;
    seen.add(ks); out.push(p);
  }
  return out;
}

/* ============================== МОНТЕ-КАРЛО ============================== */
function percentile(sorted, q) {
  if (!sorted.length) return NaN;
  const pos = (sorted.length - 1) * q, lo = Math.floor(pos), hi = Math.ceil(pos);
  return sorted[lo] + (sorted[hi] - sorted[lo]) * (pos - lo);
}

function monteCarlo(pcts, opt) {
  opt = opt || {};
  const sims = Math.max(10, opt.sims | 0 || 1000), method = opt.method || 'bootstrap';
  const skip = Math.max(0, Math.min(0.9, (opt.skip || 0) / 100));
  const rnd = mulberry32(opt.seed || 12345);
  const N = pcts.length, rets = pcts.map((p) => p / 100);
  const finals = new Float64Array(sims), dds = new Float64Array(sims);
  const pts = Math.min(N, 250);
  const xIdx = []; for (let k = 0; k <= pts; k++) xIdx.push(Math.round(k * N / Math.max(1, pts)));
  const paths = xIdx.map(() => new Float64Array(sims));
  const arr = new Float64Array(N);
  for (let sIdx = 0; sIdx < sims; sIdx++) {
    if (method === 'shuffle') {
      for (let k = 0; k < N; k++) arr[k] = rets[k];
      for (let k = N - 1; k > 0; k--) { const j = Math.floor(rnd() * (k + 1)); const t = arr[k]; arr[k] = arr[j]; arr[j] = t; }
    } else for (let k = 0; k < N; k++) arr[k] = rets[Math.floor(rnd() * N)];
    let e = 1, peak = 1, mdd = 0, xi = 0;
    if (xIdx[0] === 0) { paths[0][sIdx] = 1; xi = 1; }
    for (let k = 0; k < N; k++) {
      const r = skip > 0 && rnd() < skip ? 0 : arr[k];
      e = Math.max(0, e * (1 + r));
      if (e > peak) peak = e;
      const dd = peak > 0 ? (peak - e) / peak : 1;
      if (dd > mdd) mdd = dd;
      while (xi < xIdx.length && xIdx[xi] === k + 1) { paths[xi][sIdx] = e; xi++; }
    }
    finals[sIdx] = (e - 1) * 100; dds[sIdx] = mdd * 100;
  }
  const qs = [0.05, 0.25, 0.5, 0.75, 0.95];
  const bands = { x: xIdx, p5: [], p25: [], p50: [], p75: [], p95: [] };
  for (const col of paths) {
    const srt = Array.from(col).sort((a, b) => a - b);
    bands.p5.push(percentile(srt, 0.05)); bands.p25.push(percentile(srt, 0.25)); bands.p50.push(percentile(srt, 0.5));
    bands.p75.push(percentile(srt, 0.75)); bands.p95.push(percentile(srt, 0.95));
  }
  const fs = Array.from(finals).sort((a, b) => a - b), ds = Array.from(dds).sort((a, b) => a - b);
  const ruin = opt.ruinDD || 50;
  return {
    finals, dds, bands,
    finalQ: qs.map((q) => percentile(fs, q)), ddQ: qs.map((q) => percentile(ds, q)),
    probLoss: fs.filter((v) => v < 0).length / sims * 100,
    probRuin: ds.filter((v) => v >= ruin).length / sims * 100,
    meanFinal: fs.reduce((a, b) => a + b, 0) / sims,
  };
}

/* ========================= ПОЛЬЗОВАТЕЛЬСКИЕ СТРАТЕГИИ ========================= */
function compileCustom(code) {
  const fn = new Function('ta', 'Engine', '"use strict";\n' + code + '\n;return (typeof strategy !== "undefined") ? strategy : null;');
  const s = fn(ta, api);
  if (!s || typeof s.signals !== 'function') throw new Error('Код должен объявить: const strategy = { name, params: [...], signals(d, p, ta) { ... } }');
  s.params = (s.params || []).map((q) => Object.assign({ type: 'float', min: q.default, max: q.default, step: 1, label: q.key }, q));
  s.custom = true;
  return s;
}

const api = {
  ta, STRATEGIES, DEFAULTS, OBJECTIVES, intervalMinutes, fundingPerBar, prepare, backtest, computeMetrics, run, evaluate,
  rangeValues, countCombos, gridCombos, randomCombos, monteCarlo, percentile, compileCustom, normalizeSignals, paramsWithDefaults,
  getBuiltin: (id) => STRATEGIES.find((s) => s.id === id) || null,
};
root.Engine = api;
if (typeof module !== 'undefined' && module.exports) module.exports = api;
})(typeof globalThis !== 'undefined' ? globalThis : (typeof self !== 'undefined' ? self : this));
