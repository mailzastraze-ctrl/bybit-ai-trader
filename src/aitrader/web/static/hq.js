// AI Trader HQ — a living 3D office driven by the real system state.
// Modules: hq-world (the floor, merged into a few meshes), hq-people (procedural staff, IK hands),
// hq-screens (each desk's app + a redraw scheduler), hq-data (polling, only while visible).
import * as THREE from "three";
import { OrbitControls } from "three/addons/controls/OrbitControls.js";
import { RoomEnvironment } from "three/addons/environments/RoomEnvironment.js";
import { buildWorld, ZONES } from "./hq-world.js";
import { makeApps, Screens, goalTitle, goalValue, goalTarget } from "./hq-screens.js";
import { createStaff, ROSTER } from "./hq-people.js";
import { S, D, fmt, coin, esc, start, onData, setActive, STAGE_RU, VERDICT_RU, fgRu, headlines } from "./hq-data.js";

const $ = s => document.querySelector(s);
const clamp = (v, a, b) => Math.max(a, Math.min(b, v)), lerp = (a, b, t) => a + (b - a) * t;
const loadStep = (k, msg) => { $("#lbar").style.width = `${k * 100}%`; $("#lmsg").textContent = msg; };
const store = {get: k => { try { return localStorage.getItem("hq." + k); } catch { return null; } }, set: (k, v) => { try { localStorage.setItem("hq." + k, v); } catch { /* private mode */ } }};
const reduced = matchMedia("(prefers-reduced-motion: reduce)").matches;
const mobile = matchMedia("(max-width: 900px), (pointer: coarse)").matches;

// ------------------------------------------------------------------ quality
let quality = store.get("quality") || "auto";
const Q = {
  eco: {dpr: 1, shadows: false, fps: 30, screens: 0.5, people: false},
  auto: {dpr: mobile ? 1.25 : 1.5, shadows: true, fps: 60, screens: 1, people: false},
  high: {dpr: 2, shadows: true, fps: 60, screens: 1.3, people: true},
};
const q = () => Q[quality];

// ------------------------------------------------------------------ renderer
loadStep(0.1, "Строим офис…");
const renderer = new THREE.WebGLRenderer({antialias: quality !== "eco", alpha: true, powerPreference: "high-performance"});
const maxDpr = () => Math.min(devicePixelRatio || 1, q().dpr);
let dpr = maxDpr();
renderer.setPixelRatio(dpr); renderer.setSize(innerWidth, innerHeight);
renderer.outputColorSpace = THREE.SRGBColorSpace; renderer.toneMapping = THREE.ACESFilmicToneMapping; renderer.toneMappingExposure = 1.05;
renderer.shadowMap.enabled = q().shadows; renderer.shadowMap.type = THREE.PCFSoftShadowMap; renderer.shadowMap.autoUpdate = false;
$("#scene").appendChild(renderer.domElement);
const scene = new THREE.Scene();
{ const pm = new THREE.PMREMGenerator(renderer); const env = new RoomEnvironment(); scene.environment = pm.fromScene(env, 0.04).texture; env.dispose(); pm.dispose(); }
scene.environmentIntensity = 0.45;
const camera = new THREE.PerspectiveCamera(34, innerWidth / innerHeight, 0.1, 400);
const hemi = new THREE.HemisphereLight(0xdfe9ff, 0x6b5a4d, 1.05); scene.add(hemi);
const sun = new THREE.DirectionalLight(0xfff1de, 2.3);
sun.position.set(-14, 30, 20); sun.target.position.set(0, 0, -1); scene.add(sun, sun.target);
sun.castShadow = true; sun.shadow.mapSize.setScalar(mobile ? 1024 : 2048);
Object.assign(sun.shadow.camera, {left: -24, right: 24, top: 17, bottom: -17, near: 5, far: 80});
sun.shadow.bias = -0.0005; sun.shadow.normalBias = 0.03; sun.shadow.radius = 3;

// ------------------------------------------------------------------ world, apps, people
const world = buildWorld(scene);
loadStep(0.35, "Включаем мониторы…");
const apps = makeApps(ROSTER);
const screens = new Screens(world.displays, apps);
loadStep(0.55, "Рассаживаем команду…");
const ui = {bubble: () => {}, feed: () => {}};
const staff = createStaff(scene, world, apps, ui);
const people = staff.people;
if (q().people) people.forEach(p => { p.mesh.castShadow = true; });
// soft contact shadows under everyone (one instanced mesh)
const blobTex = (() => { const c = document.createElement("canvas"); c.width = c.height = 64; const g = c.getContext("2d"), r = g.createRadialGradient(32, 32, 0, 32, 32, 32); r.addColorStop(0, "rgba(0,0,0,.55)"); r.addColorStop(1, "rgba(0,0,0,0)"); g.fillStyle = r; g.fillRect(0, 0, 64, 64); return new THREE.CanvasTexture(c); })();
const blobs = new THREE.InstancedMesh(new THREE.PlaneGeometry(1, 1).rotateX(-Math.PI / 2), new THREE.MeshBasicMaterial({map: blobTex, transparent: true, depthWrite: false, opacity: 0.8}), people.length);
blobs.renderOrder = 1; scene.add(blobs);
const _bm = new THREE.Matrix4(), _bq = new THREE.Quaternion(), _bs = new THREE.Vector3(), _bp = new THREE.Vector3();
function updateBlobs() { people.forEach((p, i) => { const s = p.sit > 0.5 ? 0.85 : 0.62; _bp.set(p.pos.x, 0.045, p.pos.z); _bs.set(s, 1, s); blobs.setMatrixAt(i, _bm.compose(_bp, _bq, _bs)); }); blobs.instanceMatrix.needsUpdate = true; }

// ------------------------------------------------------------------ day and night from the viewer's clock
const SKY = {day: ["#8fb6d9", "#dbe7f2", "#f3e6d8"], dusk: ["#3a4b7a", "#c88aa0", "#f2b58a"], night: ["#060b18", "#111c33", "#1f2a44"]};
const mix = (a, b, t) => { const A = new THREE.Color(a), B = new THREE.Color(b); return "#" + A.lerp(B, t).getHexString(); };
let lastSky = -1;
function daylight(force = false) {
  const d = new Date(), h = d.getHours() + d.getMinutes() / 60;
  const day = clamp(Math.sin(((h - 6.5) / 13) * Math.PI) * 1.5, 0, 1), dusk = clamp(1 - Math.abs(day - 0.25) * 4, 0, 1) * (day < 0.6 ? 1 : 0);
  const key = Math.round(day * 40);
  if (key === lastSky && !force) return; lastSky = key;
  const base = SKY.night.map((n, i) => mix(n, SKY.day[i], day)).map((c, i) => mix(c, SKY.dusk[i], dusk * 0.7));
  const st = document.documentElement.style; st.setProperty("--sky-a", base[0]); st.setProperty("--sky-b", base[1]); st.setProperty("--sky-c", base[2]); st.setProperty("--stars", String(clamp(1 - day * 2, 0, 1)));
  sun.intensity = 0.35 + 2.0 * day; sun.color.set(mix("#9bb4ff", dusk > 0.3 ? "#ffcf9e" : "#fff1de", day));
  hemi.intensity = 0.45 + 0.6 * day; hemi.color.set(mix("#6a7fb0", "#dfe9ff", day));
  scene.environmentIntensity = 0.25 + 0.2 * day; renderer.toneMappingExposure = 0.95 + 0.12 * day;
  world.setNight(clamp(1 - day * 1.6, 0, 1), new THREE.Color(mix("#2b3655", "#ffffff", day)), new THREE.Color(mix(base[0], base[1], 0.62)));
  renderer.shadowMap.needsUpdate = true;
}
daylight(true);

// ------------------------------------------------------------------ camera + controls
const controls = new OrbitControls(camera, renderer.domElement);
controls.enableDamping = true; controls.dampingFactor = 0.08; controls.maxPolarAngle = 1.32; controls.minDistance = 1.6; controls.maxDistance = 95; controls.zoomSpeed = 0.9;
const HOME = {eye: new THREE.Vector3(23, 25, 31), target: new THREE.Vector3(0, 0, -0.6)};
const homeEye = () => HOME.eye.clone().sub(HOME.target).multiplyScalar(camera.aspect < 0.8 ? 1.32 : clamp(1.55 / camera.aspect, 0.92, 1.6)).add(HOME.target);
camera.position.copy(homeEye()).multiplyScalar(1.35); controls.target.copy(HOME.target);
let tween = null, follow = null, shoulder = false;
function fly(eye, target, ms = 1500) {
  if (reduced) { camera.position.copy(eye); controls.target.copy(target); tween = null; return; }
  tween = {p0: camera.position.clone(), t0: controls.target.clone(), p1: eye.clone(), t1: target.clone(), s: performance.now(), ms, arc: Math.min(5, camera.position.distanceTo(eye) * 0.12)};
}
// keep the subject centred in the part of the screen the side panel does not cover
function besidePanel(v) {
  if (innerWidth <= 900) return v;
  const share = Math.min(420, innerWidth * 0.3) / innerWidth / 2, dist = v.eye.distanceTo(v.target);
  const fwd = v.target.clone().sub(v.eye).normalize(), right = new THREE.Vector3().crossVectors(fwd, new THREE.Vector3(0, 1, 0)).normalize();
  const shift = share * 2 * dist * Math.tan((camera.fov * Math.PI) / 360) * camera.aspect;
  v.eye.addScaledVector(right, shift); v.target.addScaledVector(right, shift); return v;
}
function zoneView(z) {
  const [x0, z0, x1, z1] = z.rect, c = new THREE.Vector3((x0 + x1) / 2, 0.7, (z0 + z1) / 2), size = Math.max(x1 - x0, (z1 - z0) * 1.3);
  const dir = new THREE.Vector3(0.52, 0.62, 0.78).normalize(), dist = clamp(size * 1.25, 9, 22) * clamp(1.4 / camera.aspect, 1, 1.5);
  return besidePanel({eye: c.clone().addScaledVector(dir, dist), target: c});
}
function shoulderView(p) {
  const d = p.desk, fwd = new THREE.Vector3(Math.sin(d.yaw), 0, Math.cos(d.yaw)), right = new THREE.Vector3(-Math.cos(d.yaw), 0, Math.sin(d.yaw));
  const eye = d.seat.clone().addScaledVector(fwd, -1.45).addScaledVector(right, 0.95); eye.y = 1.9;
  const target = d.screen.center.clone().addScaledVector(fwd, -0.05).addScaledVector(right, 0.12); target.y -= 0.08;
  return besidePanel({eye, target});
}
function goHome() { follow = null; shoulder = false; setTour(false); fly(homeEye(), HOME.target, 1600); markDock(); }

// ------------------------------------------------------------------ labels, bubbles, hover tags
const labelsEl = $("#labels"), zoneLabels = {}, bubbles = new Map();
for (const z of ZONES) {
  const el = document.createElement("button"); el.className = "zl"; el.type = "button"; el.style.setProperty("--c", z.color);
  el.innerHTML = `<i></i>${z.name}<span></span>`; el.onclick = () => focusZone(z.key);
  labelsEl.appendChild(el); zoneLabels[z.key] = {el, pos: new THREE.Vector3(...z.label), sub: el.querySelector("span")};
}
const tagEl = document.createElement("div"); tagEl.className = "tag"; labelsEl.appendChild(tagEl);
const _pv = new THREE.Vector3();
function toScreen(v, out) { _pv.copy(v).project(camera); out.x = (_pv.x + 1) / 2 * innerWidth; out.y = (1 - _pv.y) / 2 * innerHeight; out.ok = _pv.z < 1 && _pv.z > -1 && Math.abs(_pv.x) < 1.1 && Math.abs(_pv.y) < 1.1; return out; }
const color = p => p.def.color;
ui.bubble = (p, text, ms) => {
  let b = bubbles.get(p);
  if (!b) { const el = document.createElement("div"); el.className = "bubble"; el.style.setProperty("--c", color(p)); labelsEl.appendChild(el); b = {el, until: 0}; bubbles.set(p, b); }
  b.el.innerHTML = `<b><i></i>${esc(p.name)} · ${esc(p.role)}</b>${esc(text)}`; b.until = performance.now() + ms; b.el.classList.add("on");
};
const feedList = $("#feedList");
ui.feed = (p, text, raw) => {
  const li = document.createElement("li");
  li.innerHTML = `<span class="av" style="--c:${color(p)}">${esc(p.name[0])}</span><span><span class="who">${esc(p.name)}</span><time>${fmt.time(new Date())}</time><br>${esc(text)}</span>`;
  if (raw && raw !== text) li.title = raw;
  feedList.prepend(li); while (feedList.children.length > 6) feedList.lastChild.remove();
};
$("#feedMin").onclick = () => { $("#feed").classList.toggle("min"); $("#feedMin").textContent = $("#feed").classList.contains("min") ? "развернуть" : "свернуть"; };

// ------------------------------------------------------------------ dock: zones + team
const zoneRow = $("#zoneRow"), teamRow = $("#teamRow");
for (const z of ZONES) { const b = document.createElement("button"); b.className = "zb"; b.type = "button"; b.dataset.zone = z.key; b.style.setProperty("--c", z.color); b.innerHTML = `<i></i>${z.name}`; b.onclick = () => focusZone(z.key); zoneRow.appendChild(b); }
for (const p of people) {
  const b = document.createElement("button"); b.className = "pb"; b.type = "button"; b.dataset.person = p.id;
  b.innerHTML = `<span class="av" style="--c:${color(p)}">${esc(p.name[0])}</span><span><b>${esc(p.name)}</b><small>${esc(p.role)}</small></span>`;
  b.onclick = () => focusPerson(p, true); teamRow.appendChild(b); p.dockEl = b; p.dockSub = b.querySelector("small");
}
function markDock(kind, key) { document.querySelectorAll(".zb, .pb").forEach(el => el.classList.toggle("on", (kind === "zone" && el.dataset.zone === key) || (kind === "person" && el.dataset.person === key))); }

// ------------------------------------------------------------------ panel
const panel = $("#panel"), ph = $("#ph"), pbody = $("#pbody");
let panelKind = null, panelKey = null, preview = null;
function closePanel() { panel.classList.remove("open"); panelKind = panelKey = null; preview = null; markDock(); }
function openPanel(kind, key) { panelKind = kind; panelKey = key; panel.classList.add("open"); renderPanel(true); markDock(kind, key); }
const LIVE = {true: ["live", "живые данные"], mixed: ["mixed", "живые данные + иллюстрация рынков"], false: ["illus", "иллюстрация работы"]};
function personPanel(p, first) {
  if (first) {
    ph.innerHTML = `<span class="av" style="--c:${color(p)}">${esc(p.name[0])}</span><div><h2>${esc(p.name)}</h2><p>${esc(p.role)}</p></div><button class="x" type="button" aria-label="Закрыть">✕</button>`;
    const [cls, txt] = LIVE[String(p.app?.live ?? true)];
    pbody.innerHTML = `<div class="now"><i class="dot good"></i><span id="pNow"></span></div>
      <figure class="screen"><canvas id="pScreen" width="768" height="480"></canvas><figcaption><span>Экран: ${esc(p.app?.title || "")}</span><span class="badge ${cls}">${txt}</span></figcaption></figure>
      <p class="duty">${esc(p.def.duty)}</p><blockquote id="pLine" style="--c:${color(p)}" hidden></blockquote>
      <div class="btns"><button class="btn" id="pShoulder" type="button">Через плечо</button><button class="btn" id="pFollow" type="button">Следовать</button><button class="btn" id="pZone" type="button">${esc(ZONES.find(z => z.key === p.def.zone)?.name || "Зона")}</button></div>
      <p class="note">${S.demo ? "Демо-режим: данные сгенерированы для предпросмотра." : "Экран рисуется в реальном времени — то же, что сейчас видно на мониторе в офисе."}</p>`;
    ph.querySelector(".x").onclick = closePanel;
    $("#pShoulder").onclick = () => focusPerson(p, true); $("#pFollow").onclick = () => { follow = p; shoulder = false; setTour(false); };
    $("#pZone").onclick = () => focusZone(p.def.zone);
    preview = {p, g: $("#pScreen").getContext("2d"), last: 0};
  }
  $("#pNow").textContent = p.describe()[0].toUpperCase() + p.describe().slice(1);
  const ln = $("#pLine"); if (p.line && ln.dataset.l !== p.line) { ln.hidden = false; ln.textContent = "«" + p.line + "»"; ln.dataset.l = p.line; }
}
function drawPreview(now) {
  if (!preview || now - preview.last < 90) return; preview.last = now;
  const app = preview.p.app; if (!app) return;
  const g = preview.g, k = 768 / app.W; g.setTransform(k, 0, 0, k, 0, 0); app.paint(g);
}
const chipS = (stage) => `<span class="chip" style="--c:${stage === "production" ? "#3ddc97" : stage === "incubation" ? "#6aa8ff" : stage === "rejected" || stage === "retired" ? "#8e9db1" : "#ffc15e"}">${esc(STAGE_RU[stage] || stage)}</span>`;
const verdictChip = v => v ? `<span class="chip" style="--c:${v === "validated" ? "#3ddc97" : v === "exploratory" ? "#ffc15e" : "#ff6b7a"}">${esc(VERDICT_RU[v] || v)}</span>` : "";
function zonePanel(key, first) {
  const z = ZONES.find(x => x.key === key);
  if (first) { ph.innerHTML = `<span class="zi" style="--c:${z.color}"><i></i></span><div><h2>${esc(z.name)}</h2><p id="zSub"></p></div><button class="x" type="button" aria-label="Закрыть">✕</button>`; ph.querySelector(".x").onclick = closePanel; }
  $("#zSub").textContent = zoneInfo(key);
  const here = people.filter(p => p.def.zone === key);
  let h = here.length ? `<div class="who">${here.map(p => `<button type="button" data-p="${p.id}"><span class="av" style="--c:${color(p)}">${esc(p.name[0])}</span>${esc(p.name)} · ${esc(p.describe())}</button>`).join("")}</div>` : "";
  const open = D.open(), sl = D.sleeves(), rs = S.rs || {}, lab = rs.lab || {}, hl = S.hl || {}, rd = D.readiness();
  if (key === "trading") {
    const up = D.unrealised(), ex = S.ov?.exposure || {}, sg = S.ov?.signals;
    h += `<div class="sec">Сейчас</div><div class="grid2"><div class="stat"><span>Капитал</span><b>${fmt.n(D.capital(), 0)}</b></div><div class="stat"><span>Нереализованный P&L</span><b class="${up >= 0 ? "pos" : "neg"}">${fmt.signed(up, 2)} $</b></div>
      <div class="stat"><span>Стратегий торгует</span><b>${sl.length}</b></div><div class="stat"><span>Независимых ставок</span><b>${ex.eff_bets != null ? "≈" + fmt.n(ex.eff_bets, 1) : "—"}</b></div></div>`;
    h += `<div class="sec">Открытые позиции · ${open.length}</div>` + (open.length ? `<table class="t"><tr><th>Монета</th><th>Сторона</th><th class="r">Вход</th><th class="r">Стоп</th><th class="r">P&L</th></tr>${open.slice(0, 14).map(t => `<tr><td><b>${esc(coin(t.pair))}</b></td><td class="${t.is_short ? "neg" : "pos"}">${t.is_short ? "шорт" : "лонг"}</td><td class="r">${fmt.price(t.open_rate)}</td><td class="r">${fmt.price(t.stop_loss_abs)}</td><td class="r ${t.profit_abs >= 0 ? "pos" : "neg"}">${fmt.signed(t.profit_abs, 2)}</td></tr>`).join("")}</table>` : `<p class="duty">Позиций нет — стратегии ждут своих сигналов.</p>`);
    if (sg?.signals) h += `<p class="note">Сигналы за 7 дней: ${sg.signals}, исполнено ${sg.executed} (${Math.round(100 * sg.executed / sg.signals)}%).</p>`;
  } else if (key === "research") {
    const run = D.running();
    h += `<div class="sec">GitHub-лаборатория</div><div class="grid2"><div class="stat"><span>Статус</span><b>${D.labActive() ? "идёт прогон" : "ожидание"}</b></div><div class="stat"><span>Запусков</span><b>${lab.runs ?? "—"}</b></div><div class="stat"><span>Готово экспериментов</span><b>${rs.counts?.done ?? "—"}</b></div><div class="stat"><span>Последний импорт</span><b style="font-size:13px">${lab.last_import ? fmt.ago(lab.last_import) : "—"}</b></div></div>`;
    if (run) { const pg = run.progress || {}; h += `<div class="sec">Сейчас: ${esc(run.family)}</div><div class="li"><span>${esc(pg.stage || "работа")}</span><b>${pg.epoch ?? "—"}/${pg.epochs ?? "—"}</b></div><div class="bar" style="--c:#a78bfa"><i style="width:${pg.epochs ? Math.round(100 * pg.epoch / pg.epochs) : 0}%"></i></div>`; }
    h += `<div class="sec">Последние эксперименты</div><table class="t"><tr><th>Семейство</th><th>Вердикт</th><th class="r">PF</th><th class="r">Sharpe</th></tr>${(rs.experiments || []).filter(e => e.oos || e.summary?.verdict).slice(0, 9).map(e => `<tr><td>${esc(e.family)}${e.timeframe ? ` <span style="color:var(--muted)">${esc(e.timeframe)}</span>` : ""}</td><td>${verdictChip(e.summary?.verdict) || esc(e.status)}</td><td class="r">${fmt.n(e.oos?.profit_factor, 2)}</td><td class="r">${fmt.n(e.oos?.sharpe, 2)}</td></tr>`).join("")}</table>`;
  } else if (key === "analysts") {
    const ctx = S.ctx || {}, fg = ctx.fear_greed, dv = ctx.dvol, ls = ctx.long_short || {};
    h += `<div class="sec">Биржи мира</div>${D.markets().map(m => `<div class="li"><span><i class="dot ${m.open ? "good" : ""}" style="display:inline-block;margin-right:7px"></i>${esc(m.name)}</span><b>${esc(m.local)} · ${m.open ? "открыта" : "закрыта"}</b></div>`).join("")}`;
    h += `<div class="sec">Ближайшие макро-события США</div>${(ctx.events || []).slice(0, 4).map(e => `<div class="li"><span>${esc(e.name)}</span><b>${new Date(e.ts) > new Date() ? "через " + fmt.until(e.ts) : "вышли"}</b></div>`).join("") || `<p class="duty">Нет данных.</p>`}`;
    h += `<div class="sec">Толпа и волатильность</div><div class="grid2"><div class="stat"><span>Страх и жадность</span><b>${fg ? `${fg.value} · ${esc(fgRu(fg.label))}` : "—"}</b></div><div class="stat"><span>DVOL BTC</span><b>${dv ? fmt.n(dv.value, 1) : "—"}</b></div><div class="stat"><span>Лонг BTC на Bybit</span><b>${ls.BTC ? fmt.n(ls.BTC, 0) + "%" : "—"}</b></div><div class="stat"><span>Лонг ETH на Bybit</span><b>${ls.ETH ? fmt.n(ls.ETH, 0) + "%" : "—"}</b></div></div>`;
    h += `<div class="sec">Заголовки дня (из данных)</div>${headlines().slice(0, 6).map(x => `<div class="li"><span>${esc(x.text)}</span><b>${esc(x.tag)}</b></div>`).join("")}`;
  } else if (key === "ceo" || key === "meeting") {
    if (key === "meeting") h += `<div class="sec">Миссия</div><p class="duty">Найти, доказать и масштабировать настоящие торговые преимущества на Bybit Demo — без подгонки и фальшивых результатов.</p>`;
    h += `<div class="sec">Цели компании</div>${(S.goals?.goals || []).map(g => `<div class="goal"><div><span>${esc(goalTitle(g))}</span><b>${esc(goalValue(g))}${g.unit === "%" ? "%" : ""} / ${esc(goalTarget(g))}</b></div><div class="bar" style="--c:${g.warning ? "#ff6b7a" : g.progress >= 1 ? "#3ddc97" : "#6aa8ff"}"><i style="width:${Math.round(clamp(g.progress || 0, 0, 1) * 100)}%"></i></div></div>`).join("")}`;
    if (key === "ceo") h += `<div class="sec">Управление</div><div class="li"><span>Аварийный стоп (kill-switch)</span><b>${S.ov?.kill_switch ? "СРАБОТАЛ" : "не срабатывал"}</b></div><div class="li"><span>Новые входы</span><b>${S.ov?.entries_paused ? "на паузе" : "разрешены"}</b></div><div class="li"><span>Закрытых сделок / результат</span><b>${fmt.n(S.ov?.closed_count)} · ${fmt.signed(S.ov?.closed_pnl, 2)} $</b></div><div class="li"><span>Просадка от пика</span><b>${fmt.pct(S.goals?.drawdown, 1)}</b></div>`;
    else { const m = staff.meeting(); h += `<p class="note">${m ? "Сейчас идёт стендап — каждая реплика собрана из живых данных." : "Стендап собирается каждые 4–6 минут: управляющий, лаборатория, риск, трейдинг и сервер."}</p>`; }
  } else if (key === "risk") {
    const e = D.lastGated();
    h += `<div class="sec">Последний кандидат${e ? ": " + esc(e.variant || e.family) : ""}</div>` + (e ? `<table class="t"><tr><th>Ворота</th><th class="r">Значение</th><th class="r">Нужно</th><th></th></tr>${Object.entries(e.gates).map(([k, v]) => `<tr><td>${esc(k)}</td><td class="r">${typeof v.value === "number" ? fmt.n(v.value, 2) : esc(v.value)}</td><td class="r">${esc(v.threshold)}</td><td class="${v.pass ? "pos" : "neg"}">${v.pass ? "✓" : "✗"}</td></tr>`).join("")}</table><p class="note">Вердикт: ${verdictChip(e.summary?.verdict)}</p>` : `<p class="duty">Кандидатов пока нет.</p>`);
    h += `<div class="sec">Готовность к реальным деньгам · ${rd.passed ?? 0}/${rd.total ?? 10}</div>${(rd.checks || []).map(c => `<div class="li"><span>${c.pass ? "✓" : "✗"} ${esc(c.title)}</span><b>${esc(typeof c.value === "number" ? fmt.n(c.value, 2) : c.value)}</b></div>`).join("") || `<p class="duty">Проверки начнутся с первой боевой стратегией.</p>`}`;
  } else if (key === "ops") {
    h += `<div class="sec">Сервер</div><div class="grid2"><div class="stat"><span>Бот</span><b class="${hl.bot_up ? "pos" : "neg"}">${hl.bot_up ? "работает" : "не отвечает"}</b></div><div class="stat"><span>Тест ордеров</span><b>${hl.exec_test?.ok ? "пройден" : "—"}</b></div><div class="stat"><span>Свободная память</span><b>${D.mem() ? fmt.n(D.mem()) + " МБ" : "—"}</b></div><div class="stat"><span>Диск свободен</span><b>${hl.disk ? fmt.n(hl.disk.free / 1e9, 1) + " ГБ" : "—"}</b></div></div>`;
    h += `<div class="sec">Пульс сервисов</div><table class="t"><tr><th>Сервис</th><th>Статус</th><th class="r">Сигнал</th></tr>${(hl.heartbeats || []).map(x => `<tr><td>${esc(x.service)}</td><td>${esc(x.status)}</td><td class="r">${x.age_s ?? "—"} с назад</td></tr>`).join("")}</table>`;
  } else if (key === "lounge") {
    const resting = people.filter(p => /кофе|диван|футбол|окн/.test(p.describe()));
    h += `<p class="duty">Короткие перерывы держат команду в форме. Бот торгует на сервере, а не за столом — от перерывов сделки не зависят.</p><div class="grid2"><div class="stat"><span>Чашек кофе за сессию</span><b>${people.reduce((a, p) => a + p.coffees, 0)}</b></div><div class="stat"><span>Сейчас на перерыве</span><b>${resting.length}</b></div></div>`;
  }
  h += `<p class="note">${S.demo ? "Демо-режим: данные сгенерированы для предпросмотра." : `Цифры из живого реестра компании · обновлено ${fmt.time(new Date(S.updated || Date.now()))}`}</p>`;
  pbody.innerHTML = h;
  pbody.querySelectorAll("[data-p]").forEach(b => { b.onclick = () => focusPerson(staff.byId[b.dataset.p], true); });
}
function renderPanel(first = false) {
  if (panelKind === "person") personPanel(staff.byId[panelKey], first);
  else if (panelKind === "zone") zonePanel(panelKey, first);
}
function zoneInfo(key) {
  const open = D.open(), lab = S.rs?.lab || {}, hl = S.hl || {}, rd = D.readiness();
  return {
    trading: `${D.sleeves().length} стратегий · ${open.length} позиций`, research: D.labActive() ? `идёт прогон · ${D.running()?.progress?.stage || "работа"}` : `ожидание · ${lab.runs ?? 0} запусков`,
    analysts: (() => { const m = D.markets().filter(x => x.open).map(x => x.name); return m.length ? `открыты: ${m.join(", ")}` : "фондовые биржи закрыты"; })(),
    ceo: `готовность ${rd.passed ?? 0}/${rd.total ?? 10} · ${S.ov?.kill_switch ? "стоп сработал" : "аварийный стоп не срабатывал"}`,
    risk: (() => { const e = D.lastGated(); if (!e) return "кандидатов нет"; const g = Object.values(e.gates), p = g.filter(x => x.pass).length; return `кандидат: ${p}/${g.length} ворот`; })(),
    ops: `бот ${hl.bot_up ? "работает" : "не отвечает"}${hl.disk ? ` · диск ${fmt.n(hl.disk.free / 1e9, 1)} ГБ` : ""}`,
    meeting: staff.meeting() ? "идёт стендап" : "стендап каждые ~5 минут", lounge: "кофе, диван, настольный футбол",
  }[key] || "";
}
function focusZone(key) {
  const z = ZONES.find(x => x.key === key); follow = null; shoulder = false; setTour(false);
  const v = zoneView(z); fly(v.eye, v.target); openPanel("zone", key);
}
function focusPerson(p, shoulderCam) {
  setTour(false);
  if (shoulderCam && p.seat?.kind === "desk") { const v = shoulderView(p); fly(v.eye, v.target, 1500); follow = null; shoulder = true; }
  else { follow = p; shoulder = false; }
  openPanel("person", p.id);
}

// ------------------------------------------------------------------ tour
let tour = false, tourI = -1, tourNext = 0, idleSince = performance.now();
const tourStops = () => [{zone: "trading"}, {person: "ivan"}, {zone: "analysts"}, {person: "anna"}, {zone: "research"}, {person: "dina"}, {zone: "ceo"}, {person: "viktor"}, {zone: "risk"}, {zone: "ops"}, {zone: "meeting"}, {zone: "lounge"}, {home: true}];
function setTour(on) { tour = on; $("#bTour").classList.toggle("on", on); $("#bTour").setAttribute("aria-pressed", String(on)); document.body.classList.toggle("in-tour", on); $("#caption").classList.toggle("on", on); if (!on) tourI = -1; }
function tourStep(now) {
  const stops = tourStops(); tourI = (tourI + 1) % stops.length; const s = stops[tourI], cap = $("#caption");
  if (s.home) { fly(homeEye(), HOME.target, 2600); cap.querySelector("b").textContent = "AI TRADER HQ"; cap.querySelector("span").textContent = "Весь этаж: исследования, риск, исполнение — на живых данных."; }
  else if (s.zone) { const z = ZONES.find(x => x.key === s.zone), v = zoneView(z); fly(v.eye, v.target, 2600); cap.querySelector("b").textContent = z.name; cap.querySelector("span").textContent = zoneInfo(z.key); }
  else { const p = staff.byId[s.person]; if (p.seat?.kind !== "desk") return tourStep(now); const v = shoulderView(p); fly(v.eye, v.target, 2600); cap.querySelector("b").textContent = `${p.name} · ${p.role}`; cap.querySelector("span").textContent = p.describe(); }
  tourNext = now + 9000;
}
$("#bTour").onclick = () => { if (tour) { setTour(false); return; } closePanel(); follow = null; setTour(true); tourStep(performance.now()); };
$("#bHome").onclick = () => { closePanel(); goHome(); };
const interrupt = () => { idleSince = performance.now(); if (tour) setTour(false); tween = null; if (shoulder) shoulder = false; };
renderer.domElement.addEventListener("pointerdown", interrupt);
renderer.domElement.addEventListener("wheel", interrupt, {passive: true});
addEventListener("keydown", e => { idleSince = performance.now(); if (e.key === "Escape") { if (tour) setTour(false); else closePanel(); } });
addEventListener("pointermove", () => { idleSince = performance.now(); }, {passive: true});

// ------------------------------------------------------------------ picking people (screen space, no raycasts)
let hover = null; const _sp = {x: 0, y: 0, ok: false}, _sp2 = {x: 0, y: 0, ok: false}, _hp = new THREE.Vector3();
function personAt(x, y) {
  let best = null, bd = 1e9;
  for (const p of people) {
    _hp.copy(p.pos); _hp.y = p.sit > 0.5 ? 1.25 : 1.62; toScreen(_hp, _sp); _hp.y = p.sit > 0.5 ? 0.55 : 0.4; toScreen(_hp, _sp2);
    if (!_sp.ok) continue;
    const r = Math.max(14, Math.abs(_sp2.y - _sp.y) * 0.45), cx = (_sp.x + _sp2.x) / 2, cy = (_sp.y + _sp2.y) / 2, d = Math.hypot((x - cx) * 1.6, y - cy);
    if (d < Math.max(r, Math.abs(_sp2.y - _sp.y) * 0.6) && d < bd) { bd = d; best = p; }
  }
  return best;
}
renderer.domElement.addEventListener("pointermove", e => { const p = personAt(e.clientX, e.clientY); if (p !== hover) { hover = p; tagEl.style.display = p ? "block" : "none"; if (p) tagEl.innerHTML = `<b>${esc(p.name)}</b><small>${esc(p.describe())}</small>`; renderer.domElement.style.cursor = p ? "pointer" : ""; } });
let downAt = null;
renderer.domElement.addEventListener("pointerdown", e => { downAt = [e.clientX, e.clientY]; });
renderer.domElement.addEventListener("click", e => {
  if (downAt && Math.hypot(e.clientX - downAt[0], e.clientY - downAt[1]) > 6) return;
  const p = personAt(e.clientX, e.clientY); if (p) focusPerson(p, true);
});

// ------------------------------------------------------------------ HUD (top KPIs)
document.querySelectorAll(".kpi").forEach(k => { k.onclick = () => focusZone(k.dataset.zone); });
function hud() {
  const cap = D.capital(), eq = D.equity(), pr = S.ov?.profit || {}, open = D.open(), up = D.unrealised(), rd = D.readiness(), lab = S.rs?.lab || {};
  const bot = S.ov?.bot_up;
  $("#botDot").className = "dot " + (S.error ? "warn" : bot ? "good" : "bad");
  $("#botTxt").textContent = S.error ? "нет связи с сервером" : bot ? "бот работает" : "бот не отвечает";
  $("#kCap").innerHTML = cap ? `${fmt.n(cap, 0)}<small>USDT</small>` : "—";
  const ret = eq.length > 1 ? eq.at(-1) / eq[0] - 1 : null;
  $("#kCapS").innerHTML = ret === null ? "демо-счёт Bybit" : `<span class="${ret >= 0 ? "pos" : "neg"}">${fmt.spct(ret, 2)}</span> с начала`;
  if (eq.length > 1) { const pts = eq.slice(-120), lo = Math.min(...pts), hi = Math.max(...pts) || 1; const d = pts.map((v, i) => `${(i / (pts.length - 1)) * 100},${28 - ((v - lo) / (hi - lo || 1)) * 24}`).join(" "); $("#kSpark").innerHTML = `<polyline points="${d}" fill="none" stroke="${ret >= 0 ? "#4ee6c4" : "#ff6b7a"}" stroke-width="1.6" vector-effect="non-scaling-stroke"/>`; }
  const pnl = pr.profit_closed_coin ?? S.ov?.closed_pnl;
  $("#kPnl").innerHTML = pnl != null ? `<span class="${pnl >= 0 ? "pos" : "neg"}">${fmt.signed(pnl, 2)}</span><small>$</small>` : "—";
  $("#kPnlS").textContent = `${fmt.n(pr.closed_trade_count ?? S.ov?.closed_count ?? 0)} закрытых сделок`;
  $("#kPos").textContent = String(open.length);
  $("#kPosS").innerHTML = open.length ? `нереализ. <span class="${up >= 0 ? "pos" : "neg"}">${fmt.signed(up, 2)} $</span>` : `${D.sleeves().length} стратегий ждут сигнала`;
  const run = D.running();
  $("#kLab").textContent = S.rs?.paused ? "на паузе" : D.labActive() ? "идёт прогон" : "ожидание";
  $("#kLabS").textContent = run ? `${run.family} · ${run.progress?.stage || ""}` : `${S.rs?.counts?.done ?? 0} экспериментов · ${lab.runs ?? 0} запусков`;
  $("#kRd").innerHTML = `${rd.passed ?? 0}<small>/ ${rd.total ?? 10}</small>`;
  $("#kRing").setAttribute("stroke-dasharray", `${Math.round(100 * (rd.passed ?? 0) / (rd.total || 10))} 100`);
  for (const z of ZONES) zoneLabels[z.key].sub.textContent = zoneInfo(z.key).slice(0, 34);
  document.body.classList.toggle("is-demo", S.demo);
}

// ------------------------------------------------------------------ settings menu
const menu = $("#menu");
$("#bMenu").onclick = e => { e.stopPropagation(); menu.classList.toggle("open"); };
addEventListener("click", e => { if (!menu.contains(e.target) && e.target !== $("#bMenu")) menu.classList.remove("open"); });
function markQ() { document.querySelectorAll("#qSeg button").forEach(b => b.classList.toggle("on", b.dataset.q === quality)); }
document.querySelectorAll("#qSeg button").forEach(b => b.onclick = () => {
  quality = b.dataset.q; store.set("quality", quality); markQ(); document.body.classList.toggle("q-high", quality === "high");
  dpr = maxDpr(); renderer.setPixelRatio(dpr); renderer.shadowMap.enabled = q().shadows; renderer.shadowMap.needsUpdate = true;
  people.forEach(p => { p.mesh.castShadow = q().people; });
  scene.traverse(o => { if (o.material) o.material.needsUpdate = true; });
});
markQ(); document.body.classList.toggle("q-high", quality === "high");
$("#fpsBox").onchange = e => { $("#fps").style.display = e.target.checked ? "block" : "none"; };
$("#autoTour").checked = store.get("autotour") !== "0";
$("#autoTour").onchange = e => store.set("autotour", e.target.checked ? "1" : "0");

// ------------------------------------------------------------------ pause when not visible (tab hidden or the office iframe hidden in the control room)
let visible = true;
new IntersectionObserver(es => { visible = es[0].isIntersecting; setActive(visible && !document.hidden); }).observe($("#scene"));
document.addEventListener("visibilitychange", () => setActive(visible && !document.hidden));

// ------------------------------------------------------------------ main loop
const clock = {t: 0, last: performance.now(), lastFrame: 0, frames: 0, fpsAt: performance.now(), ft: 16, lastAdapt: 0, lastShadow: 0, lastHud: 0, lastPanel: 0, lastSky: 0};
const _lp = {x: 0, y: 0, ok: false}, _bv = new THREE.Vector3();
function frame(now) {
  requestAnimationFrame(frame);
  if (!visible || document.hidden) { clock.last = now; return; }
  const calm = !tween && !follow && !tour && now - idleSince > 8000;
  const cap = calm && quality !== "high" ? Math.min(30, q().fps) : q().fps;
  if (cap < 60 && now - clock.lastFrame < 1000 / cap - 2) return;
  const dt = Math.min(0.05, (now - clock.last) / 1000); clock.last = now; clock.lastFrame = now; clock.t += dt;
  const t = clock.t;
  staff.update(dt, t);
  world.updateLeds(t, D.labActive()); world.updateClouds(t);
  updateBlobs();
  // camera
  if (tween) {
    const k = clamp((now - tween.s) / tween.ms, 0, 1), e = k < 0.5 ? 4 * k * k * k : 1 - (-2 * k + 2) ** 3 / 2;
    camera.position.lerpVectors(tween.p0, tween.p1, e); camera.position.y += Math.sin(Math.PI * e) * tween.arc;
    controls.target.lerpVectors(tween.t0, tween.t1, e);
    if (k >= 1) tween = null;
  } else if (follow) {
    const tp = follow.pos.clone(); tp.y = follow.sit > 0.5 ? 1.0 : 1.2;
    controls.target.lerp(tp, 1 - Math.exp(-4 * dt));
    const back = new THREE.Vector3(Math.sin(follow.yaw), 0, Math.cos(follow.yaw)).multiplyScalar(-3.2);
    camera.position.lerp(tp.clone().add(back).add(new THREE.Vector3(1.2, 2.2, 1.2)), 1 - Math.exp(-2 * dt));
  } else if (tour && now > tourNext) tourStep(now);
  if (!tour && !follow && !panelKind && $("#autoTour").checked && !reduced && now - idleSince > 120000) { setTour(true); tourStep(now); }
  controls.update();
  screens.update(dt, camera, innerHeight, q().screens);
  if (q().people && now - clock.lastShadow > 90) { renderer.shadowMap.needsUpdate = true; clock.lastShadow = now; }
  if (now - clock.lastSky > 60000) { clock.lastSky = now; daylight(); }
  renderer.render(scene, camera);
  // labels
  const dist = camera.position.distanceTo(controls.target), showZones = dist > 24 && !tour && !(innerWidth < 600 && panelKind);
  for (const z of ZONES) { const L = zoneLabels[z.key]; toScreen(L.pos, _lp); const on = showZones && _lp.ok; L.el.classList.toggle("hidden", !on); if (on) L.el.style.transform = `translate3d(${_lp.x | 0}px, ${_lp.y | 0}px, 0)`; }
  for (const [p, b] of bubbles) {
    if (now > b.until) { if (b.el.classList.contains("on")) b.el.classList.remove("on"); continue; }
    _bv.copy(p.pos); _bv.y = p.sit > 0.5 ? 1.55 : 1.95; toScreen(_bv, _lp);
    b.el.style.display = _lp.ok ? "" : "none"; if (_lp.ok) b.el.style.transform = `translate3d(${clamp(_lp.x, 130, innerWidth - 130) | 0}px, ${_lp.y | 0}px, 0)`;
  }
  if (hover) { _bv.copy(hover.pos); _bv.y = hover.sit > 0.5 ? 1.45 : 1.9; toScreen(_bv, _lp); tagEl.style.transform = `translate3d(${_lp.x | 0}px, ${_lp.y | 0}px, 0)`; }
  drawPreview(now);
  if (now - clock.lastPanel > 1500) { clock.lastPanel = now; if (panelKind === "person") renderPanel(); for (const p of people) { const d = p.describe(); if (p.dockSub.textContent !== d) p.dockSub.textContent = d; } }
  // adaptive resolution: hold ~50+ fps
  clock.frames++; clock.ft = lerp(clock.ft, dt * 1000, 0.05);
  if (now - clock.fpsAt > 1000) { $("#fps").textContent = `${clock.frames} fps · ${renderer.info.render.calls} вызовов · ×${dpr.toFixed(2)}`; clock.frames = 0; clock.fpsAt = now; }
  if (now - clock.lastAdapt > 2500 && quality !== "high") {
    let next = dpr;
    if (clock.ft > 24) next = Math.max(0.75, dpr * 0.85); else if (clock.ft < 14) next = Math.min(maxDpr(), dpr + 0.1);
    if (Math.abs(next - dpr) > 0.02) { dpr = next; renderer.setPixelRatio(dpr); clock.lastAdapt = now; }
  }
}
function resize() {
  camera.aspect = innerWidth / innerHeight; camera.fov = camera.aspect < 0.8 ? 46 : 34; camera.updateProjectionMatrix();
  renderer.setSize(innerWidth, innerHeight);
}
addEventListener("resize", resize); resize();

// ------------------------------------------------------------------ start
loadStep(0.7, "Подключаемся к данным компании…");
onData((type, payload) => {
  if (type === "fast" || type === "slow" || type === "ready" || type === "strats") hud();
  if (type === "slow" && panelKind === "zone") renderPanel();
  if (type === "fast" && panelKind === "zone") renderPanel();
  if (type === "error") { const t = $("#toast"); t.textContent = "Нет связи с сервером — показываю последние данные"; t.classList.add("on"); setTimeout(() => t.classList.remove("on"), 5000); hud(); }
  staff.onData(type, payload);
});
await document.fonts?.ready?.catch?.(() => {});
await start();
loadStep(1, "Готово");
renderer.shadowMap.needsUpdate = true;
hud();
$("#loader").style.opacity = 0; setTimeout(() => $("#loader").remove(), 900);
fly(homeEye(), HOME.target, reduced ? 0 : 2200);
setTimeout(() => { const v = staff.byId.viktor; v.say(S.demo ? "Это демо-просмотр офиса: данные сгенерированы. В рабочем режиме всё берётся из живого реестра." : "Доброе утро, команда. Демо-счёт, малый риск — доверие зарабатываем доказательствами.", 6500); ui.feed(v, "Офис открыт. Все на местах."); }, 2600);
requestAnimationFrame(frame);

// hooks for previews / screenshots (scripts/hq_preview.py)
window.__hq = {
  people: () => people.map(p => `${p.name}: ${p.describe()}`),
  view: (cx, cy, cz, tx, ty, tz) => { tween = null; follow = null; setTour(false); camera.position.set(cx, cy, cz); controls.target.set(tx, ty, tz); controls.update(); },
  zone: key => focusZone(key), person: id => focusPerson(staff.byId[id], true), home: () => goHome(), close: () => closePanel(),
  standup: () => staff.standup(), errand: (id, kind) => staff.errands[kind](staff.byId[id]),
  // advance the office at a fixed 30 Hz without rendering (previews on slow software GL)
  profile: (n = 120) => { const t0 = performance.now(); for (let k = 0; k < n; k++) { clock.t += 1 / 60; staff.update(1 / 60, clock.t); } const t1 = performance.now(); for (let k = 0; k < n; k++) screens.update(1 / 60, camera, innerHeight, 1); const t2 = performance.now();
    return {staffMs: +((t1 - t0) / n).toFixed(3), screensMs: +((t2 - t1) / n).toFixed(3)}; },
  sim: seconds => { for (let k = 0; k < seconds * 30; k++) { clock.t += 1 / 30; staff.update(1 / 30, clock.t); for (const a of Object.values(apps)) a.update(1 / 30); } },
  S, D, apps, scene, renderer,
  stats: () => ({calls: renderer.info.render.calls, triangles: renderer.info.render.triangles, textures: renderer.info.memory.textures, geometries: renderer.info.memory.geometries}),
};
window.__hqReady = true;
