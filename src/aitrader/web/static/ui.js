"use strict";
// Общее для всех страниц: сортировка любой таблицы по клику на заголовок и имена стратегий
// (код + метод). Таблицы перерисовываются каждые несколько секунд – выбранная сортировка
// сохраняется и применяется к новой таблице сама.
(() => {
  const STATE = {};  // ключ таблицы → {col, dir}
  const style = document.createElement("style");
  style.textContent = `
    table thead tr:last-child th:not(.nosort) { cursor: pointer; user-select: none; }
    table thead tr:last-child th:not(.nosort):hover { color: var(--text, #e8edf3); }
    th.sort-asc::after { content: " ▲"; font-size: 9px; } th.sort-desc::after { content: " ▼"; font-size: 9px; }`;
  document.head.appendChild(style);

  const keyOf = (table) => table.id || table.closest("[id]")?.id || "";
  const value = (td) => {
    if (!td) return null;
    const raw = (td.dataset.v ?? td.textContent).trim();
    if (raw === "" || raw === "—" || raw === "-") return null;
    const t = raw.replace(/−/g, "-").replace(/[\s $%+×#]/g, "").replace(",", ".");
    const m = t.match(/^-?\d+(?:\.\d+)?/);
    if (m && !/\d/.test(t.slice(m[0].length))) return parseFloat(m[0]);
    if (t === "∞") return Infinity;
    return raw.toLowerCase();
  };
  function apply(table) {
    const st = STATE[keyOf(table)];
    const head = table.tHead?.rows[table.tHead.rows.length - 1];
    const body = table.tBodies[0];
    if (!st || !head || !body) return;
    const sig = `${st.col}:${st.dir}:${body.rows.length}`;
    if (table.dataset.sorted === sig && body.dataset.sorted === sig) return;
    [...head.cells].forEach((th, i) => { th.classList.toggle("sort-asc", i === st.col && st.dir > 0); th.classList.toggle("sort-desc", i === st.col && st.dir < 0); });
    const rows = [...body.rows].filter((r) => r.cells.length > 1);
    rows.sort((a, b) => {
      const x = value(a.cells[st.col]), y = value(b.cells[st.col]);
      if (x === null && y === null) return 0;
      if (x === null) return 1;
      if (y === null) return -1;
      if (typeof x === "number" && typeof y === "number") return (x - y) * st.dir;
      return String(x).localeCompare(String(y), "ru", {numeric: true}) * st.dir;
    });
    rows.forEach((r) => body.appendChild(r));
    table.dataset.sorted = sig; body.dataset.sorted = sig;
  }
  document.addEventListener("click", (e) => {
    const th = e.target.closest("th");
    if (!th || th.classList.contains("nosort") || e.target.closest("input,button,a,select")) return;
    const table = th.closest("table"), head = table?.tHead;
    if (!head || th.parentElement !== head.rows[head.rows.length - 1]) return;
    const key = keyOf(table), col = th.cellIndex, cur = STATE[key];
    STATE[key] = {col, dir: cur && cur.col === col ? -cur.dir : (th.classList.contains("r") ? -1 : 1)};  // числа – сначала большие
    delete table.dataset.sorted;
    apply(table);
  });
  let queued = false;
  new MutationObserver(() => {
    if (queued) return;
    queued = true;
    requestAnimationFrame(() => {
      queued = false;
      for (const key of Object.keys(STATE)) {
        const el = document.getElementById(key);
        const table = el?.tagName === "TABLE" ? el : el?.querySelector("table");
        if (table) apply(table);
      }
    });
  }).observe(document.body, {childList: true, subtree: true});

  // ------------------------------------------------------------------ имена стратегий
  const UI = window.UI = {names: {}, async loadNames() {
    try { const r = await fetch("/api/names", {cache: "no-store"}); if (r.ok) UI.names = await r.json(); } catch (e) { /* остаётся прежнее */ }
    return UI.names;
  }};
  // «1047» – код (имя стратегии), «RSI: возврат к среднему · 2h» – метод
  UI.code = (id) => { const n = UI.names[id]; return n?.code ? String(n.code) : (n?.lane || ""); };
  UI.method = (id, fallback) => UI.names[id]?.method || fallback || id || "—";
  UI.label = (id, fallback) => { const c = UI.code(id); return (c ? `#${c} · ` : "") + UI.method(id, fallback); };
})();
