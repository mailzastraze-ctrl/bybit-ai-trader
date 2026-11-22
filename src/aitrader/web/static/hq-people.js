// AI Trader HQ — the staff. Each person is one rigidly skinned mesh (no downloaded models),
// posed procedurally every frame: legs and spine by hand-tuned curves, arms by two-bone IK so
// hands land on the keyboard and mouse, and the mouse hand follows the cursor on their screen.
import * as THREE from "three";
import { mergeGeometries } from "three/addons/utils/BufferGeometryUtils.js";
import { RoundedBoxGeometry } from "three/addons/geometries/RoundedBoxGeometry.js";
import { S, D, fmt, coin } from "./hq-data.js";

export const ROSTER = [
  {id: "viktor", name: "Виктор", role: "Управляющий", zone: "ceo", app: "report", color: "#ffc15e", duty: "Читает отчёты, принимает решения о повышении стратегий и следит, чтобы компания зарабатывала доверие доказательствами.",
    look: {skin: 0xe8b896, hair: "side", hairC: 0x55504b, shirt: 0xf4f1ea, jacket: 0x23324a, tie: 0x8a2f3a, pants: 0x262a33, shoes: 0x1b1512, glasses: true, beard: "short"}},
  {id: "anna", name: "Анна", role: "Новостной аналитик", zone: "analysts", app: "news", color: "#6aa8ff", duty: "Смотрит новостной эфир и собирает главное: макро-календарь, настроения, делистинги — всё, что может сдвинуть рынок.",
    look: {skin: 0xf1c7a5, hair: "bob", hairC: 0x7a3b24, shirt: 0xe36f5a, pants: 0x2f3b52, shoes: 0x3a2a22, female: true}},
  {id: "mark", name: "Марк", role: "Макро-аналитик", zone: "analysts", app: "macro", color: "#ff9f43", duty: "Следит за мировыми индексами — S&P 500, Nasdaq, DAX, золотом и ставками — и за календарём ФРС.",
    look: {skin: 0xc98e6a, hair: "short", hairC: 0x1e1a18, shirt: 0x4a6b8a, pants: 0xb9a585, shoes: 0x3b2b20, glasses: true}},
  {id: "leya", name: "Лея", role: "Аналитик настроений", zone: "analysts", app: "sentiment", color: "#a78bfa", duty: "Читает соцсети и меряет толпу: индекс страха и жадности, лонг/шорт на Bybit, опционная волатильность.",
    look: {skin: 0xf3d0b5, hair: "long", hairC: 0xd9b56b, shirt: 0x8f6ad8, pants: 0x2b2f3a, shoes: 0xe9e6e1, female: true}},
  {id: "ivan", name: "Иван", role: "Трейдер", zone: "trading", app: "trader", color: "#3ddc97", duty: "Ведёт половину стратегий: смотрит свечи, вход, стоп и цель по каждой позиции. Стоп всегда стоит на бирже.",
    look: {skin: 0xe9be98, hair: "buzz", hairC: 0x5a3a26, shirt: 0xf1f3f5, vest: 0x1f2c44, pants: 0x2a2e36, shoes: 0x1b1b1b, headset: true, rolled: true}},
  {id: "sofia", name: "София", role: "Трейдер", zone: "trading", app: "dom", color: "#5ad1e6", duty: "Ведёт вторую половину стратегий: стакан, лента сделок и журнал сигналов — почему сигнал исполнен или пропущен.",
    look: {skin: 0xd5a07c, hair: "pony", hairC: 0x2a1a14, shirt: 0x1fa38a, pants: 0x2a2e36, shoes: 0xf1eee8, female: true}},
  {id: "oleg", name: "Олег", role: "Трейдер · портфель", zone: "trading", app: "blotter", color: "#4ee6c4", duty: "Держит в голове весь портфель: каждая позиция, её результат в R и сколько на самом деле независимых ставок.",
    look: {skin: 0xeac3a0, hair: "curly", hairC: 0xa45a2a, shirt: 0x3e7a5a, pants: 0x3a3f4a, shoes: 0x2b1d14, beard: "full"}},
  {id: "mila", name: "Мила", role: "Разбор сделок", zone: "trading", app: "sheet", color: "#c5e17a", duty: "Разбирает каждую закрытую сделку: был ли стоп прав, что было после выхода. Выводы — только от 30 случаев.",
    look: {skin: 0xf2cdb0, hair: "bun", hairC: 0x3a2418, shirt: 0xe0a83a, pants: 0x2f3547, shoes: 0x2b2b2b, glasses: true, female: true}},
  {id: "artem", name: "Артём", role: "Исследователь", zone: "research", app: "lab", color: "#b79cff", duty: "Запускает эксперименты в лаборатории на GitHub: hyperopt, walk-forward, стресс-тесты, Монте-Карло.",
    look: {skin: 0xe0b18c, hair: "short", hairC: 0x4b3020, shirt: 0x6b7280, pants: 0x34507a, shoes: 0xe9e6e1, glasses: true}},
  {id: "dina", name: "Дина", role: "Квант-разработчик", zone: "research", app: "code", color: "#f48fb1", duty: "Пишет код стратегий и проверок и прогоняет тесты. Утка на столе помогает с отладкой.",
    look: {skin: 0xc48b65, hair: "curly", hairC: 0x161210, shirt: 0x22252b, pants: 0x4a5568, shoes: 0xd9d4cc, headset: "phones", female: true}},
  {id: "nika", name: "Ника", role: "Риск-менеджер", zone: "risk", app: "risk", color: "#ff8f70", duty: "Пропускает кандидата только через все строгие ворота и следит за готовностью к реальным деньгам.",
    look: {skin: 0xf0c9a8, hair: "bob", hairC: 0x15110f, shirt: 0x22252b, jacket: 0xece8e1, pants: 0x2a2e36, shoes: 0x1b1b1b, female: true}},
  {id: "gleb", name: "Глеб", role: "DevOps / SRE", zone: "ops", app: "ops", color: "#7fe8ff", duty: "Отвечает за сервер на Railway: бот, память, диск, журналы. Тяжёлые расчёты живут на GitHub, не здесь.",
    look: {skin: 0xdcae8a, hair: "buzz", hairC: 0x3a2a20, shirt: 0x2b3445, pants: 0x5b5a48, shoes: 0x2b2b2b, beard: "full"}},
];

// ------------------------------------------------------------------ rig
const BONES = ["hips", "spine", "chest", "neck", "head", "jaw", "eyes", "uaL", "faL", "haL", "uaR", "faR", "haR", "thL", "shL", "ftL", "thR", "shR", "ftR", "mug", "phone", "paper"];
const PARENT = {spine: "hips", chest: "spine", neck: "chest", head: "neck", jaw: "head", eyes: "head", uaL: "chest", faL: "uaL", haL: "faL", uaR: "chest", faR: "uaR", haR: "faR",
  thL: "hips", shL: "thL", ftL: "shL", thR: "hips", shR: "thR", ftR: "shR", mug: "haR", phone: "haR", paper: "haL"};
const REST = {hips: [0, 0.92, 0], spine: [0, 1.01, 0], chest: [0, 1.21, 0], neck: [0, 1.42, 0], head: [0, 1.5, 0], jaw: [0, 1.572, 0.108], eyes: [0, 1.642, 0.1],
  uaL: [0.19, 1.38, 0], faL: [0.19, 1.1, 0], haL: [0.19, 0.85, 0], uaR: [-0.19, 1.38, 0], faR: [-0.19, 1.1, 0], haR: [-0.19, 0.85, 0],
  thL: [0.095, 0.87, 0], shL: [0.095, 0.45, 0], ftL: [0.095, 0.06, 0], thR: [-0.095, 0.87, 0], shR: [-0.095, 0.45, 0], ftR: [-0.095, 0.06, 0],
  mug: [-0.19, 0.8, 0], phone: [-0.19, 0.8, 0], paper: [0.19, 0.8, 0]};
const BI = Object.fromEntries(BONES.map((b, i) => [b, i]));
const L1 = 0.28, L2 = 0.25;

const _mm = new THREE.Matrix4(), _qq = new THREE.Quaternion(), _ee = new THREE.Euler(), _pp = new THREE.Vector3(), _ss = new THREE.Vector3(), _cc = new THREE.Color();
const geoCache = new Map();
const cg = (k, make) => { if (!geoCache.has(k)) geoCache.set(k, make()); return geoCache.get(k); };
const rbox = (w, h, d, r) => cg(`r${w}${h}${d}${r}`, () => new RoundedBoxGeometry(w, h, d, 2, Math.min(r, w / 2, h / 2, d / 2) * 0.99));
const caps = (r, l) => cg(`c${r}${l}`, () => new THREE.CapsuleGeometry(r, l, 3, 10));
const sph = (n = 14, m = 10) => cg(`s${n}${m}`, () => new THREE.SphereGeometry(1, n, m));
const cyl = (a, b, h, n = 12) => cg(`y${a}${b}${h}${n}`, () => new THREE.CylinderGeometry(a, b, h, n));
const tor = (r, t, arc) => cg(`t${r}${t}${arc}`, () => new THREE.TorusGeometry(r, t, 6, 16, arc));

function buildBody(look) {
  const parts = [];
  const add = (geo, color, bone, x, y, z, o = {}) => {
    const g = geo.clone();
    for (const k of Object.keys(g.attributes)) if (k !== "position" && k !== "normal") g.deleteAttribute(k);
    if (!g.index) g.setIndex([...Array(g.attributes.position.count).keys()]);
    _ee.set(o.rx || 0, o.ry || 0, o.rz || 0); _qq.setFromEuler(_ee); _pp.set(x, y, z); _ss.set(o.sx ?? 1, o.sy ?? 1, o.sz ?? 1);
    g.applyMatrix4(_mm.compose(_pp, _qq, _ss));
    const n = g.attributes.position.count, col = new Float32Array(n * 3), si = new Uint16Array(n * 4), sw = new Float32Array(n * 4);
    _cc.setHex(color);
    for (let i = 0; i < n; i++) { col[i * 3] = _cc.r; col[i * 3 + 1] = _cc.g; col[i * 3 + 2] = _cc.b; si[i * 4] = BI[bone]; sw[i * 4] = 1; }
    g.setAttribute("color", new THREE.BufferAttribute(col, 3)); g.setAttribute("skinIndex", new THREE.BufferAttribute(si, 4)); g.setAttribute("skinWeight", new THREE.BufferAttribute(sw, 4));
    parts.push(g);
  };
  const L = look, top = L.jacket || L.vest || L.shirt, sleeve = L.jacket || L.shirt, fem = L.female, shW = fem ? 0.33 : 0.37;
  // torso
  add(rbox(0.3, 0.2, 0.2, 0.08), L.pants, "hips", 0, 0.93, 0);
  add(rbox(fem ? 0.27 : 0.29, 0.24, 0.19, 0.08), top, "spine", 0, 1.08, 0);
  add(rbox(shW, 0.28, 0.21, 0.09), top, "chest", 0, 1.28, 0);
  for (const s of [1, -1]) add(sph(), sleeve, "chest", s * (shW / 2 - 0.02), 1.37, 0, {sx: 0.065, sy: 0.06, sz: 0.07});
  if (L.jacket || L.vest) { add(rbox(0.1, 0.2, 0.02, 0.01), L.shirt, "chest", 0, 1.3, 0.1); if (L.tie) add(rbox(0.035, 0.18, 0.012, 0.005), L.tie, "chest", 0, 1.28, 0.112); }
  else add(rbox(0.12, 0.03, 0.04, 0.012), L.shirt, "chest", 0, 1.41, 0.07);
  add(cyl(0.048, 0.052, 0.1), L.skin, "neck", 0, 1.46, 0);
  // head
  add(sph(16, 12), L.skin, "head", 0, 1.63, 0, {sx: 0.112, sy: 0.128, sz: 0.118});
  add(sph(8, 6), L.skin, "head", 0, 1.615, 0.118, {sx: 0.02, sy: 0.022, sz: 0.02});
  for (const s of [1, -1]) {
    add(sph(8, 6), L.skin, "head", s * 0.112, 1.625, -0.005, {sx: 0.02, sy: 0.03, sz: 0.022});
    add(sph(8, 6), 0x1a1614, "eyes", s * 0.04, 1.642, 0.104, {sx: 0.016, sy: 0.018, sz: 0.01});
    add(rbox(0.042, 0.011, 0.012, 0.004), L.hairC, "head", s * 0.042, 1.675, 0.11, {rz: s * -0.12});
  }
  add(rbox(0.04, 0.012, 0.012, 0.005), 0x9c4a4a, "jaw", 0, 1.572, 0.108);
  const H = L.hairC, hair = L.hair;
  if (hair !== "bald") {
    if (hair === "buzz") add(sph(16, 10), H, "head", 0, 1.665, -0.008, {sx: 0.117, sy: 0.092, sz: 0.122});
    else add(sph(16, 10), H, "head", 0, 1.672, -0.012, {sx: 0.124, sy: 0.1, sz: 0.128});
    if (hair === "short" || hair === "side") { add(sph(12, 8), H, "head", 0, 1.62, -0.04, {sx: 0.118, sy: 0.1, sz: 0.1}); add(rbox(0.16, 0.04, 0.06, 0.02), H, "head", hair === "side" ? 0.02 : 0, 1.735, 0.07, {rz: hair === "side" ? -0.15 : 0, rx: -0.3}); }
    const shell = (z = -0.03, sy = 0.118) => add(sph(16, 12), H, "head", 0, 1.618, z, {sx: 0.128, sy, sz: 0.118});
    if (hair === "bob") { shell(); add(rbox(0.19, 0.05, 0.05, 0.022), H, "head", 0, 1.722, 0.085, {rx: -0.35}); for (const s of [1, -1]) add(sph(12, 8), H, "head", s * 0.1, 1.56, -0.01, {sx: 0.045, sy: 0.07, sz: 0.09}); }
    if (hair === "long") { shell(); add(rbox(0.21, 0.3, 0.07, 0.034), H, "head", 0, 1.5, -0.085, {rx: 0.08}); for (const s of [1, -1]) add(rbox(0.05, 0.24, 0.09, 0.024), H, "head", s * 0.1, 1.53, -0.02); add(rbox(0.18, 0.05, 0.05, 0.022), H, "head", 0.02, 1.722, 0.085, {rx: -0.35, rz: -0.12}); }
    if (hair === "pony") { shell(-0.04, 0.11); add(sph(10, 8), H, "head", 0, 1.68, -0.125, {sx: 0.045, sy: 0.045, sz: 0.045}); add(caps(0.032, 0.17), H, "head", 0, 1.57, -0.15, {rx: 0.22}); }
    if (hair === "bun") { shell(-0.04, 0.11); add(sph(12, 10), H, "head", 0, 1.765, -0.06, {sx: 0.062, sy: 0.058, sz: 0.062}); }
    if (hair === "curly") for (let k = 0; k < 18; k++) { const th = k * 2.39996, el = 0.25 + (k % 6) * 0.2, R = 0.118; if (Math.sin(th) > 0.2 && el < 0.85) continue; add(sph(8, 6), H, "head", Math.cos(th) * Math.cos(el) * R, 1.63 + Math.sin(el) * R * 0.95, Math.sin(th) * Math.cos(el) * R - 0.02, {sx: 0.042, sy: 0.042, sz: 0.042}); }
  }
  if (L.beard) { add(rbox(0.17, L.beard === "full" ? 0.09 : 0.06, 0.09, 0.03), H, "head", 0, L.beard === "full" ? 1.545 : 1.555, 0.065); add(rbox(0.07, 0.015, 0.02, 0.006), H, "head", 0, 1.59, 0.118); }
  if (L.glasses) { for (const s of [1, -1]) add(tor(0.026, 0.004, Math.PI * 2), 0x1b1d22, "head", s * 0.042, 1.643, 0.118); add(rbox(0.03, 0.006, 0.006, 0.002), 0x1b1d22, "head", 0, 1.648, 0.12); for (const s of [1, -1]) add(rbox(0.006, 0.006, 0.11, 0.002), 0x1b1d22, "head", s * 0.07, 1.648, 0.065); }
  if (L.headset) {
    add(tor(0.13, 0.012, Math.PI), 0x2a2d33, "head", 0, 1.64, -0.01, {rz: 0});
    for (const s of [1, -1]) add(cyl(0.04, 0.04, 0.03, 12), L.headset === "phones" ? 0xf48fb1 : 0x2a2d33, "head", s * 0.122, 1.63, 0, {rz: Math.PI / 2});
    if (L.headset === true) add(caps(0.006, 0.12), 0x2a2d33, "head", -0.11, 1.57, 0.06, {rx: 1.2, rz: 0.4});
  }
  // arms (+ props bound to the hands)
  for (const [s, side] of [[1, "L"], [-1, "R"]]) {
    add(caps(0.048, 0.19), sleeve, "ua" + side, s * 0.19, 1.24, 0);
    add(caps(0.04, 0.17), L.rolled ? L.skin : sleeve, "fa" + side, s * 0.19, 0.975, 0);
    if (L.rolled) add(cyl(0.047, 0.047, 0.04), L.shirt, "fa" + side, s * 0.19, 1.07, 0);
    add(rbox(0.04, 0.1, 0.075, 0.018), L.skin, "ha" + side, s * 0.19, 0.8, 0.005);
    add(rbox(0.025, 0.05, 0.025, 0.01), L.skin, "ha" + side, s * 0.19 - s * 0.015, 0.825, 0.045, {rx: 0.3});
  }
  add(cyl(0.04, 0.036, 0.1, 12), 0xf4f1ea, "mug", -0.19 + 0.055, 0.77, 0, {rx: Math.PI / 2});
  add(tor(0.025, 0.008, Math.PI * 2), 0xf4f1ea, "mug", -0.19 + 0.055, 0.77 + 0.0, -0.0, {ry: Math.PI / 2, rz: 0});
  add(rbox(0.01, 0.14, 0.07, 0.006), 0x15171b, "phone", -0.19 + 0.022, 0.76, 0);
  add(rbox(0.004, 0.29, 0.21, 0.001), 0xf7f4ee, "paper", 0.19 - 0.012, 0.73, -0.1);
  for (let k = 0; k < 6; k++) add(rbox(0.002, 0.008, 0.15, 0.001), 0x9aa3b0, "paper", 0.19 - 0.016, 0.82 - k * 0.035, -0.11);
  // legs
  for (const [s, side] of [[1, "L"], [-1, "R"]]) {
    add(caps(0.07, 0.28), L.pants, "th" + side, s * 0.095, 0.66, 0);
    add(caps(0.055, 0.3), L.pants, "sh" + side, s * 0.095, 0.26, 0);
    add(rbox(0.1, 0.07, 0.24, 0.03), L.shoes, "ft" + side, s * 0.095, 0.035, 0.045);
  }
  const g = mergeGeometries(parts, false); parts.forEach(p => p.dispose());
  return g;
}

const DOWN = new THREE.Vector3(0, -1, 0), UP = new THREE.Vector3(0, 1, 0);
const clamp = (v, a, b) => Math.max(a, Math.min(b, v)), lerp = (a, b, t) => a + (b - a) * t;
const damp = (a, b, k, dt) => lerp(a, b, 1 - Math.exp(-k * dt));
const rand = (a, b) => a + Math.random() * (b - a), pick = a => a[Math.floor(Math.random() * a.length)];
const angDiff = (a, b) => { let d = (b - a) % (Math.PI * 2); if (d > Math.PI) d -= Math.PI * 2; if (d < -Math.PI) d += Math.PI * 2; return d; };
const smooth = t => t * t * (3 - 2 * t);
const V = () => new THREE.Vector3();
const _a = V(), _b = V(), _c = V(), _d = V(), _e2 = V(), _sh = V(), _el = V(), _wr = V(), _pole = V(), _x = V(), _y = V(), _z = V();
const _qc = new THREE.Quaternion(), _qi = new THREE.Quaternion(), _qU = new THREE.Quaternion(), _qF = new THREE.Quaternion(), _qH = new THREE.Quaternion(), _qUW = new THREE.Quaternion(), _qFW = new THREE.Quaternion(), _qHW = new THREE.Quaternion(), _m4 = new THREE.Matrix4();
function handQuat(s, F, N, out) {
  _y.copy(F).negate().normalize();
  _x.copy(N).multiplyScalar(-s); _x.addScaledVector(_y, -_x.dot(_y)); if (_x.lengthSq() < 1e-6) _x.set(1, 0, 0); _x.normalize();
  _z.crossVectors(_x, _y);
  return out.setFromRotationMatrix(_m4.makeBasis(_x, _y, _z));
}

// ------------------------------------------------------------------ a person
const MAT = new THREE.MeshStandardMaterial({vertexColors: true, roughness: 0.7, metalness: 0});
export class Person {
  constructor(def, world, apps, ui) {
    Object.assign(this, {def, id: def.id, name: def.name, role: def.role, world, ui});
    this.app = apps[def.id]; this.app2 = apps[def.id + "#2"];
    this.desk = world.desks[def.id];
    const mesh = new THREE.SkinnedMesh(buildBody(def.look), MAT);
    const b = {};
    for (const n of BONES) { b[n] = new THREE.Bone(); b[n].name = n; }
    for (const n of BONES) { const p = PARENT[n], r = REST[n]; if (p) { b[p].add(b[n]); b[n].position.set(r[0] - REST[p][0], r[1] - REST[p][1], r[2] - REST[p][2]); } else b[n].position.set(...r); }
    mesh.add(b.hips); mesh.updateMatrixWorld(true);
    mesh.bind(new THREE.Skeleton(BONES.map(n => b[n])));
    mesh.frustumCulled = false; mesh.castShadow = false; mesh.receiveShadow = true;
    b.head.rotation.order = b.neck.rotation.order = "YXZ";
    this.mesh = mesh; this.b = b;
    this.pos = V(); this.yaw = 0; this.sit = 1; this.seat = null; this.walkW = 0; this.phase = Math.random() * 6; this.speed = rand(1.1, 1.3);
    this.queue = []; this.act = null; this.activity = "work"; this.target = null; this.lookAt = null; this.lookUntil = 0;
    this.hand = {L: V(), R: V()}; this.ikW = {L: 0, R: 0}; this.lean = 0; this.hy = 0; this.hp = 0;
    this.prop = {mug: 0, phone: 0, paper: 0}; this.propS = {mug: 0, phone: 0, paper: 0};
    this.speakUntil = 0; this.blinkAt = rand(1, 4); this.saccade = V(); this.saccadeAt = 0; this.glance2 = 0; this.legVar = rand(-0.12, 0.12); this.cross = Math.random() < 0.4;
    this.typeJ = {L: V(), R: V(), at: 0}; this.line = ""; this.label = "работает"; this.away = false; this.busyErrand = false;
    this.nextErrand = rand(25, 80); this.mugOut = false; this.coffees = 0;
    for (const k of ["mug", "phone", "paper"]) b[k].scale.setScalar(0.0001);
  }
  // ---------------- seats
  deskSeat() { const d = this.desk; return {pos: d.seat, dock: d.dock, yaw: d.yaw, hipsY: 0.555, chair: d.chair, kind: "desk"}; }
  placeAtDesk() { const s = this.deskSeat(); this.seat = s; this.pos.copy(s.pos); this.yaw = s.yaw; this.sit = 1; this.world.setChair(s.chair, 0, 0); this.hand.L.copy(this.desk.keyboard); this.hand.R.copy(this.desk.mouse); this.ikW.L = this.ikW.R = 1; }
  get atDesk() { return this.seat?.kind === "desk" && this.sit > 0.99 && !this.act; }
  get forward() { return _a.set(Math.sin(this.yaw), 0, Math.cos(this.yaw)); }
  get idle() { return !this.busyErrand && !this.act && !this.queue.length && this.seat?.kind === "desk"; }
  // ---------------- action queue
  push(...acts) { this.queue.push(...acts); return this; }
  clear() { this.queue = []; this.act = null; }
  say(text, ms = 5200) { this.line = text; this.speakUntil = performance.now() + Math.min(ms, 2200 + text.length * 55); this.ui.bubble(this, text, this.speakUntil - performance.now()); }
  // ---------------- per frame
  update(dt, t) {
    // behaviour: run the current action
    if (!this.act && this.queue.length) { this.act = this.queue.shift(); this.act.t = 0; this.act.start?.(this); }
    if (this.act) { this.act.t += dt; if (this.act.update(this, dt) !== false) { this.act.end?.(this); this.act = null; } }
    else if (this.seat?.kind === "desk") this.activity = "work";
    const away = !(this.seat?.kind === "desk" && this.sit > 0.5);
    if (this.app) this.app.away = away && !this.app.keepAlive; if (this.app2) this.app2.away = away;
    this.pose(dt, t);
  }
  // ---------------- pose solver
  pose(dt, t) {
    const b = this.b, sit = smooth(clamp(this.sit, 0, 1)), w = this.walkW * (1 - sit), ph = this.phase, a = this.activity;
    this.mesh.position.copy(this.pos); this.mesh.rotation.y = this.yaw;
    const fwd = _a.set(Math.sin(this.yaw), 0, Math.cos(this.yaw)), left = _b.set(Math.cos(this.yaw), 0, -Math.sin(this.yaw));
    const right = _c.copy(left).negate();
    const working = a === "work" && this.seat?.kind === "desk" && this.app && !this.app.away;
    const mode = working ? this.app.mode : a;
    // lean
    let leanT = 0.02;
    if (sit > 0.5) leanT = mode === "type" || mode === "type-pause" ? 0.1 : mode === "mouse" ? 0.07 : mode === "read" ? -0.07 : mode === "scroll" ? 0.02 : a === "stretch" ? -0.22 : a === "paper" ? -0.12 : a === "sofa" ? -0.18 : 0.03;
    else if (a === "point") leanT = 0.08; else if (a === "coffee") leanT = 0.06;
    this.lean = damp(this.lean, leanT, 3, dt);
    // hips + legs
    const breathe = Math.sin(t * 1.7 + this.phase) * 0.012;
    const hipsStand = 0.92 - 0.018 * w + 0.022 * w * Math.abs(Math.cos(ph));
    b.hips.position.set(0, lerp(hipsStand, this.seat?.hipsY ?? 0.555, sit), 0);
    b.hips.rotation.set(0, 0.07 * Math.sin(ph) * w, a === "idle" || a === "window" ? Math.sin(t * 0.5 + this.phase) * 0.02 : 0);
    for (const [s, sd, p] of [[1, "L", ph], [-1, "R", ph + Math.PI]]) {
      const thW = -0.48 * Math.sin(p) * w, shW = 0.85 * Math.max(0, Math.cos(p)) ** 1.6 * w;
      const thS = -1.42 + this.legVar * s * 0.5 + (a === "sofa" ? 0.15 : 0), shS = 1.36 + (this.cross && sit > 0.5 ? (s > 0 ? 0.25 : 0.05) : 0) - this.legVar * 0.4;
      b["th" + sd].rotation.set(lerp(thW, thS, sit), 0, lerp(0, s * 0.04 + (this.cross ? s * -0.04 : 0), sit));
      b["sh" + sd].rotation.set(lerp(shW, shS, sit), 0, this.cross && sit > 0.5 ? s * -0.08 : 0);
      b["ft" + sd].rotation.set(-(b["th" + sd].rotation.x + b["sh" + sd].rotation.x) + (sit > 0.5 ? 0.1 : 0.15 * w * Math.sin(p + 0.8)), 0, 0);
    }
    // spine
    b.spine.rotation.set(this.lean * 0.45 + breathe * 0.3, -0.05 * Math.sin(ph) * w, 0);
    b.chest.rotation.set(this.lean * 0.55 + breathe, -0.08 * Math.sin(ph) * w + (a === "talk" ? Math.sin(t * 1.3) * 0.05 : 0), a === "cheer" ? Math.sin(t * 9) * 0.06 : 0);
    // FK arms (rest / walk / cheer / talk) — IK blends on top
    for (const [s, sd] of [[1, "L"], [-1, "R"]]) {
      const swing = 0.42 * Math.sin(ph) * w * s;
      let ux = 0.05 + swing, uz = s * (0.08 + 0.02 * w), fx = -0.2 - 0.25 * w;
      if (a === "cheer") { ux = -2.6 + Math.sin(t * 10 + s) * 0.15; uz = s * 0.35; fx = -0.25; }
      else if (a === "talk" && this.speaking) { ux = -0.35 + Math.sin(t * 2.6 + s * 1.3) * 0.18 * (s < 0 ? 1 : 0.5); fx = -1.25 + Math.sin(t * 3.1 + s) * 0.2; uz = s * 0.1; }
      else if (a === "talk") { ux = -0.15; fx = -0.9; uz = s * 0.05; }
      b["ua" + sd].rotation.set(ux, 0, uz); b["fa" + sd].rotation.set(fx, 0, 0); b["ha" + sd].rotation.set(0, 0, 0);
    }
    b.neck.rotation.set(0, 0, 0); b.head.rotation.set(0, 0, 0);
    this.mesh.updateMatrixWorld(true);
    // ---------- look
    let look = null;
    if (this.lookAt && performance.now() < this.lookUntil) look = this.lookAt.isVector3 ? this.lookAt : _d.copy(this.lookAt.headPos());
    else if (working) {
      const scr = this.desk.screen;
      if (this.app2 && this.glance2 > 0) look = this.desk.screen2.center;
      else if (mode === "type" && Math.sin(t * 0.7 + this.phase * 3) > 0.92) look = this.desk.keyboard;
      else { const c = this.app.cursorN; look = _d.set(mode === "type" || mode === "type-pause" ? 0 : c.x - 0.5, mode === "type" || mode === "type-pause" ? -0.1 : 0.5 - c.y, 0).applyMatrix4(scr.mesh.matrix); }
    } else if (this.target?.look) look = this.target.look;
    if (t > this.saccadeAt) { this.saccade.set(rand(-1, 1), rand(-1, 1), rand(-1, 1)).multiplyScalar(0.04); this.saccadeAt = t + rand(0.3, 1.4); if (this.app2 && Math.random() < 0.06) this.glance2 = rand(1.5, 3); }
    this.glance2 = Math.max(0, this.glance2 - dt);
    _qc.setFromRotationMatrix(b.chest.matrixWorld); _qi.copy(_qc).invert();
    let yaw = 0, pitch = 0.05;
    if (look) {
      _e2.setFromMatrixPosition(b.head.matrixWorld); _e2.y += 0.14;
      const dir = _d.copy(look).add(this.saccade).sub(_e2).applyQuaternion(_qi);
      yaw = clamp(Math.atan2(dir.x, dir.z), -1.2, 1.2); pitch = clamp(Math.atan2(-dir.y, Math.hypot(dir.x, dir.z)), -0.5, 0.75);
    } else if (a === "idle" || a === "window") { yaw = Math.sin(t * 0.3 + this.phase) * 0.4; pitch = -0.05; }
    if (a === "facepalm") pitch = 0.45; if (a === "paper") pitch = 0.4; if (a === "stretch") pitch = -0.35;
    this.hy = damp(this.hy, yaw, 7, dt); this.hp = damp(this.hp, pitch, 7, dt);
    b.neck.rotation.set(this.hp * 0.35, this.hy * 0.35, 0); b.head.rotation.set(this.hp * 0.65, this.hy * 0.65, Math.sin(t * 0.8 + this.phase) * 0.03);
    b.neck.updateMatrixWorld(true);
    // face: blink + talk
    if (t > this.blinkAt) { this.blinkAt = t + rand(2, 5.5); this.blinkEnd = t + 0.12; }
    b.eyes.scale.y = t < this.blinkEnd ? 0.15 : 1;
    this.speaking = performance.now() < this.speakUntil;
    b.jaw.scale.y = this.speaking ? 1 + Math.abs(Math.sin(t * 13)) * 2.6 : 1;
    // ---------- arm targets
    _e2.setFromMatrixPosition(b.head.matrixWorld); _e2.y += 0.13; // eye level
    const head = _e2, tgt = {L: null, R: null}, F = {L: V(), R: V()}, N = {L: V(), R: V()};
    const typing = (s) => { F[s].copy(fwd).multiplyScalar(0.8).addScaledVector(DOWN, 0.6); N[s].copy(DOWN); };
    if (sit > 0.3 && this.seat?.kind === "desk" && (a === "work" || a === "sip" || a === "phone" || a === "think")) {
      const kb = this.desk.keyboard, ms = this.desk.mouse;
      if (t > this.typeJ.at) { this.typeJ.at = t + rand(0.09, 0.2); this.typeJ.L.set(rand(-0.04, 0.03), 0, rand(-0.02, 0.02)); this.typeJ.R.set(rand(-0.03, 0.04), 0, rand(-0.02, 0.02)); }
      const typingNow = mode === "type";
      tgt.L = V().copy(kb).addScaledVector(left, 0.11).addScaledVector(fwd, 0.01); typing("L");
      if (typingNow) { tgt.L.addScaledVector(left, this.typeJ.L.x).addScaledVector(fwd, this.typeJ.L.z); tgt.L.y += Math.max(0, Math.sin(t * 23)) * 0.02; }
      if (mode === "type" || mode === "type-pause") {
        tgt.R = V().copy(kb).addScaledVector(right, 0.1).addScaledVector(fwd, 0.01); typing("R");
        if (typingNow) { tgt.R.addScaledVector(right, this.typeJ.R.x).addScaledVector(fwd, this.typeJ.R.z); tgt.R.y += Math.max(0, Math.sin(t * 23 + 1.7)) * 0.02; }
      } else {
        const c = this.app && !this.app.away ? this.app.cursorN : {x: 0.5, y: 0.5, down: 0};
        tgt.R = V().copy(ms).addScaledVector(right, (c.x - 0.5) * 0.09).addScaledVector(fwd, -(c.y - 0.5) * 0.06 - 0.02);
        tgt.R.y += 0.012 - c.down * 0.008 + (mode === "scroll" ? Math.sin(t * 18) * 0.003 : 0); typing("R");
        if (mode === "read" && Math.sin(t * 0.21 + this.phase) > 0.55) { tgt.L = V().copy(this.desk.deskLeft).addScaledVector(fwd, -0.05); tgt.L.y += 0.02; }
      }
      if (a === "sip") { tgt.R = V().copy(head).addScaledVector(fwd, 0.08).addScaledVector(right, 0.05); tgt.R.y -= 0.12; F.R.copy(fwd).addScaledVector(UP, 0.3); N.R.copy(left); }
      if (a === "phone") { tgt.R = V().copy(head).addScaledVector(right, 0.1).addScaledVector(fwd, 0.0); tgt.R.y -= 0.12; F.R.copy(UP).addScaledVector(fwd, 0.2); N.R.copy(left); }
      if (a === "think") { tgt.L = V().copy(head).addScaledVector(fwd, 0.11).addScaledVector(left, 0.02); tgt.L.y -= 0.17; F.L.copy(UP).addScaledVector(fwd, 0.4); N.L.copy(right); }
    } else if (sit > 0.3 && a === "stretch") {
      for (const [s, sd, dir] of [[1, "L", left], [-1, "R", right]]) { tgt[sd] = V().copy(head).addScaledVector(fwd, -0.12).addScaledVector(dir, 0.08); tgt[sd].y += 0.02; F[sd].copy(fwd).negate().addScaledVector(UP, 0.5); N[sd].copy(fwd).negate(); }
    } else if (sit > 0.3 && a === "paper") {
      const base = V().copy(head).addScaledVector(fwd, 0.34); base.y -= 0.3;
      tgt.L = V().copy(base).addScaledVector(left, 0.1); F.L.copy(UP).addScaledVector(fwd, 0.15); N.L.copy(fwd).negate();
      tgt.R = V().copy(base).addScaledVector(right, 0.12); tgt.R.y -= 0.02; F.R.copy(UP); N.R.copy(fwd);
    } else if (sit > 0.3 && (this.seat?.kind === "meet" || this.seat?.kind === "visitor")) {
      const tb = this.seat.table || V().copy(this.pos).addScaledVector(fwd, 0.45).setY(0.78);
      tgt.L = V().copy(tb).addScaledVector(left, 0.14); typing("L"); tgt.R = V().copy(tb).addScaledVector(right, 0.14); typing("R");
      if (this.speaking) { tgt.R.y += 0.12 + Math.sin(t * 3) * 0.05; tgt.R.addScaledVector(fwd, 0.05); F.R.copy(fwd).addScaledVector(UP, 0.4); N.R.copy(left); }
    } else if (sit > 0.3 && this.seat?.kind === "sofa") {
      for (const [s, sd, dir] of [[1, "L", left], [-1, "R", right]]) { tgt[sd] = V().copy(this.pos).addScaledVector(fwd, 0.3).addScaledVector(dir, 0.13); tgt[sd].y = (this.seat.hipsY || 0.6) + 0.06; typing(sd); }
      if (this.prop.mug) { tgt.R = V().copy(this.pos).addScaledVector(fwd, 0.3).addScaledVector(right, 0.05); tgt.R.y = (this.seat.hipsY || 0.6) + 0.22; F.R.copy(fwd); N.R.copy(left); if (Math.sin(t * 0.5 + this.phase) > 0.85) { tgt.R.copy(head).addScaledVector(fwd, 0.08).addScaledVector(right, 0.05); tgt.R.y -= 0.12; F.R.copy(fwd).addScaledVector(UP, 0.3); } }
    } else if (sit < 0.5) {
      // standing activities
      if (a === "coffee" && this.target?.press) { tgt.R = V().copy(this.target.press); F.R.copy(fwd); N.R.copy(left); }
      if (a === "point" && this.target?.point) { _d.copy(this.target.point).sub(head).normalize(); tgt.R = V().copy(head).addScaledVector(right, 0.12).addScaledVector(_d, 0.48); tgt.R.y -= 0.18; F.R.copy(_d); N.R.copy(DOWN); }
      if (a === "window") for (const [s, sd, dir] of [[1, "L", left], [-1, "R", right]]) { tgt[sd] = V().copy(this.pos).addScaledVector(fwd, -0.2).addScaledVector(dir, 0.06); tgt[sd].y = 0.92; F[sd].copy(DOWN).addScaledVector(fwd, -0.4); N[sd].copy(fwd).negate(); }
      if (a === "facepalm") { tgt.R = V().copy(head).addScaledVector(fwd, 0.13); tgt.R.y += 0.0; F.R.copy(UP).addScaledVector(left, 0.3); N.R.copy(fwd).negate(); }
      if (a === "phone") { tgt.R = V().copy(head).addScaledVector(right, 0.1); tgt.R.y -= 0.12; F.R.copy(UP).addScaledVector(fwd, 0.2); N.R.copy(left); }
      if (a === "foos" && this.target?.rods) { const k = Math.sin(t * 7 + this.phase) * 0.12, k2 = Math.sin(t * 6.3 + 1) * 0.12; tgt.L = V().copy(this.target.rods[0]).addScaledVector(fwd, 0).addScaledVector(left, 0).add(_d.set(0, 0, 0)); tgt.L.addScaledVector(fwd, -0.05).addScaledVector(right, k); tgt.R = V().copy(this.target.rods[1]).addScaledVector(fwd, -0.05).addScaledVector(right, k2); typing("L"); typing("R"); }
      if (this.prop.mug && !tgt.R && a !== "coffee") { tgt.R = V().copy(this.pos).addScaledVector(fwd, 0.28).addScaledVector(right, 0.12); tgt.R.y = 1.02; F.R.copy(fwd); N.R.copy(left); if (a === "sip" || (a === "idle" && Math.sin(t * 0.6 + this.phase) > 0.9)) { tgt.R.copy(head).addScaledVector(fwd, 0.08).addScaledVector(right, 0.05); tgt.R.y -= 0.12; F.R.copy(fwd).addScaledVector(UP, 0.3); } }
      if (this.prop.paper && !tgt.L) { tgt.L = V().copy(this.pos).addScaledVector(fwd, 0.25).addScaledVector(left, 0.16); tgt.L.y = 1.0; F.L.copy(fwd).addScaledVector(DOWN, 0.2); N.L.copy(right); }
    }
    // ---------- IK with smoothing (hands glide between targets)
    for (const [s, sd] of [[1, "L"], [-1, "R"]]) {
      const want = tgt[sd] ? 1 : 0;
      this.ikW[sd] = damp(this.ikW[sd], want, 6, dt);
      if (tgt[sd]) this.hand[sd].lerp(tgt[sd], 1 - Math.exp(-(this.ikW[sd] > 0.9 ? 16 : 9) * dt));
      if (this.ikW[sd] > 0.01) this.solveArm(s, sd, this.hand[sd], F[sd].lengthSq() ? F[sd].normalize() : _d.copy(fwd), N[sd].lengthSq() ? N[sd].normalize() : DOWN, smooth(this.ikW[sd]));
      else this.hand[sd].setFromMatrixPosition(b["ha" + sd].matrixWorld);
    }
    // props: scale in and out
    for (const k of ["mug", "phone", "paper"]) { this.propS[k] = damp(this.propS[k], this.prop[k], 10, dt); b[k].scale.setScalar(Math.max(0.0001, this.propS[k])); }
    // chair follows the sitter
    if (this.seat?.chair !== undefined && this.seat.kind !== "sofa") this.world.setChair(this.seat.chair, (1 - sit) * 0.38, sit > 0.9 && working ? Math.sin(t * 0.4 + this.phase) * 0.05 : 0);
  }
  solveArm(s, sd, target, F, N, w) {
    const b = this.b, ua = b["ua" + sd], fa = b["fa" + sd], ha = b["ha" + sd];
    _sh.setFromMatrixPosition(ua.matrixWorld);
    _d.subVectors(target, _sh); const len = clamp(_d.length(), 0.1, L1 + L2 - 0.003); _d.normalize();
    const a = (L1 * L1 - L2 * L2 + len * len) / (2 * len), h = Math.sqrt(Math.max(0, L1 * L1 - a * a));
    _pole.set(0.55 * s, -1, -0.45).applyAxisAngle(UP, this.yaw); _pole.addScaledVector(_d, -_pole.dot(_d)).normalize();
    _el.copy(_sh).addScaledVector(_d, a).addScaledVector(_pole, h); _wr.copy(_sh).addScaledVector(_d, len);
    _qU.setFromUnitVectors(DOWN, _e2.subVectors(_el, _sh).normalize().applyQuaternion(_qi));
    _qUW.multiplyQuaternions(_qc, _qU);
    _qF.setFromUnitVectors(DOWN, _e2.subVectors(_wr, _el).normalize().applyQuaternion(_qFW.copy(_qUW).invert()));
    _qFW.multiplyQuaternions(_qUW, _qF);
    handQuat(s, F, N, _qHW); _qH.copy(_qFW).invert().multiply(_qHW);
    ua.quaternion.slerp(_qU, w); fa.quaternion.slerp(_qF, w); ha.quaternion.slerp(_qH, w);
  }
  headPos() { return _x.setFromMatrixPosition(this.b.head.matrixWorld).setY(_x.y + 0.13); }
  // ---------------- what to tell the viewer
  describe() {
    const a = this.activity, ap = this.app, m = ap?.mode;
    if (this.act?.label) return this.act.label;
    if (a !== "work") return {sip: "пьёт кофе", phone: "говорит по телефону", think: "думает", stretch: "потягивается", paper: "читает распечатку отчёта", cheer: "радуется", facepalm: "переживает", talk: "разговаривает", idle: "стоит"}[a] || "занят";
    const L = {
      report: {read: "читает отчёт", scroll: "листает отчёт", mouse: "выделяет главное в отчёте"},
      news: {read: "смотрит новостной эфир", mouse: "выбирает новость"},
      macro: {read: `изучает график ${ap?.sel !== undefined ? ["S&P 500", "Nasdaq 100", "Dow Jones", "DAX", "Nikkei 225", "золота", "нефти Brent", "индекса доллара", "UST 10Y", "BTC"][ap.sel] : ""}`, mouse: "водит курсором по графику индекса"},
      sentiment: {read: "читает ленту соцсетей", scroll: "листает ленту", mouse: "смотрит индекс страха и жадности"},
      trader: {read: "следит за свечами", mouse: "переключает пары на графике"},
      dom: {read: "смотрит стакан", mouse: "кликает по уровням стакана"},
      blotter: {read: "проверяет позиции", mouse: "открывает позицию в портфеле"},
      sheet: {type: "пишет выводы по сделке", "type-pause": "формулирует вывод", mouse: "выбирает сделку для разбора"},
      lab: {read: "смотрит прогресс эксперимента", mouse: "запускает ячейку", type: "пишет код эксперимента"},
      code: {type: "пишет код", "type-pause": "обдумывает код", mouse: "запускает тесты", read: "смотрит на результаты тестов"},
      risk: {read: "проверяет ворота кандидата", mouse: "отмечает проверку"},
      ops: {read: "смотрит мониторинг", mouse: "листает журнал", scroll: "листает журнал"},
    }[this.def.app] || {};
    return L[m] || L.read || "работает";
  }
}

// ------------------------------------------------------------------ actions
const A = {
  call: fn => ({update: p => { fn(p); }}),
  wait: (sec, activity = "idle", label) => ({label, start: p => { p.activity = activity; }, update: (p, dt) => p.act.t >= sec ? undefined : false}),
  hold: (sec, activity, target, label) => ({label, start: p => { p.activity = activity; p.target = target; }, update: p => p.act.t >= sec ? undefined : false, end: p => { p.target = null; }}),
  until: (cond, activity = "idle", label, max = 60) => ({label, start: p => { p.activity = activity; }, update: p => (cond(p) || p.act.t > max) ? undefined : false}),
  standUp: () => ({start: p => { p.activity = "idle"; p.from = p.pos.clone(); }, update: (p, dt) => {
    const s = p.seat; if (!s) return; const k = clamp(p.act.t / 0.85, 0, 1);
    p.sit = 1 - smooth(k); if (s.dock) p.pos.lerpVectors(s.pos, s.dock, smooth(k));
    if (k >= 1) { p.seat = s.kind === "desk" ? {...s, left: true, kind: "left"} : null; p.sit = 0; if (s.chair !== undefined) p.world.setChair(s.chair, 0.38, 0); return; }
    return false;
  }}),
  sitDown: seat => ({start: p => { p.activity = "idle"; p.seat = seat; }, update: (p, dt) => {
    const k = clamp(p.act.t / 0.9, 0, 1);
    p.yaw += angDiff(p.yaw, seat.yaw) * Math.min(1, dt * 10);
    p.sit = smooth(k); if (seat.dock) p.pos.lerpVectors(seat.dock, seat.pos, smooth(k)); else p.pos.lerp(seat.pos, 0.2);
    return k >= 1 ? undefined : false;
  }}),
  walk: (to, label) => ({label, start: p => { p.activity = "idle"; p.path = p.world.nav.route(p.pos, to); p.goal = to.clone ? to.clone() : new THREE.Vector3(to.x, 0, to.z); }, update: (p, dt) => {
    const path = p.path; if (!path?.length) { p.walkW = damp(p.walkW, 0, 8, dt); return p.walkW < 0.05 ? undefined : false; }
    const tgt = path[0], dx = tgt.x - p.pos.x, dz = tgt.z - p.pos.z, dist = Math.hypot(dx, dz);
    const want = Math.atan2(dx, dz); p.yaw += angDiff(p.yaw, want) * Math.min(1, dt * 7);
    const facing = Math.cos(angDiff(p.yaw, want));
    p.walkW = damp(p.walkW, facing > 0.3 ? 1 : 0.3, 5, dt);
    const step = Math.min(dist, p.speed * dt * p.walkW * Math.max(0.2, facing));
    if (dist > 1e-4) { p.pos.x += (dx / dist) * step; p.pos.z += (dz / dist) * step; }
    p.phase += (dt * p.speed * p.walkW * Math.PI * 2) / 1.25;
    if (dist < (path.length > 1 ? 0.25 : 0.04)) path.shift();
    return false;
  }, end: p => { p.walkW = 0; }}),
  turn: yaw => ({update: (p, dt) => { const d = angDiff(p.yaw, yaw); p.yaw += d * Math.min(1, dt * 8); p.walkW = damp(p.walkW, 0, 8, dt); return Math.abs(d) < 0.03 ? undefined : false; }}),
};

// ------------------------------------------------------------------ the director: errands, reactions, stand-ups
export function createStaff(scene, world, apps, ui) {
  const people = ROSTER.map(def => new Person(def, world, apps, ui));
  const byId = Object.fromEntries(people.map(p => [p.id, p]));
  people.forEach(p => { p.placeAtDesk(); scene.add(p.mesh); });
  const taken = new Set();
  const awayCount = () => people.filter(p => p.busyErrand).length;
  let clock = 0, nextStandup = 240, meeting = null;

  function backToDesk(p) {
    const s = p.deskSeat();
    p.push(A.walk(s.dock, "возвращается за стол"), A.turn(s.yaw), A.sitDown(s), A.call(q => { q.busyErrand = false; q.activity = "work"; }));
  }
  function leave(p, label) { p.busyErrand = true; p.push(A.standUp()); }
  function spotFree(list) { return list.find(s => !taken.has(s)); }
  const errands = {
    coffee(p) {
      const spot = spotFree(world.spots.coffee); if (!spot) return false;
      taken.add(spot);
      leave(p);
      p.push(A.call(q => { world.setMug(q.desk.mugIdx, false); q.prop.mug = 1; }),
        A.walk(new THREE.Vector3(spot.x, 0, spot.z), "идёт за кофе"), A.turn(spot.yaw),
        A.call(q => { q.prop.mug = 0; }),
        A.hold(rand(4, 6), "coffee", {press: spot.faceTo.clone().add(new THREE.Vector3(0, -0.1, 0)), look: spot.faceTo}, "варит кофе"),
        A.call(q => { taken.delete(spot); q.prop.mug = 1; q.coffees++; if (Math.random() < 0.3) q.say(pick(["Кофе — тоже часть риск-менеджмента ☕", "Капучино, и обратно к графикам", "Кто последний брал молоко?.."])); }));
      backToDesk(p);
      p.push(A.hold(2.4, "sip", null, "пьёт кофе"), A.hold(rand(10, 25), "work"), A.hold(2.2, "sip", null, "пьёт кофе"), A.call(q => { q.prop.mug = 0; world.setMug(q.desk.mugIdx, true); }));
      return true;
    },
    visit(p) {
      const q = pick(people.filter(x => x !== p && x.idle && x.desk)); if (!q) return false;
      const spot = q.desk.visit.find(v => world.nav.free(v.x, v.z)) || q.desk.visit[0];
      const [ask, reply] = dialogue(p, q);
      leave(p);
      p.push(A.walk(spot, `идёт к коллеге — ${q.name}`),
        A.turn(Math.atan2(q.desk.screen.center.x - spot.x, q.desk.screen.center.z - spot.z)),
        A.call(x => { if (q.atDesk) { x.say(ask, 5200); q.lookAt = x; q.lookUntil = performance.now() + 4500; } else x.say(`${q.name} ещё не вернулась… Ладно, позже.`.replace("вернулась", q.def.look.female ? "вернулась" : "вернулся"), 3500); }),
        A.hold(3.2, "point", {point: q.desk.screen.center, look: q.desk.screen.center}, `обсуждает экран с ${q.name}`),
        A.call(() => { if (q.atDesk) q.say(reply, 5200); }), A.hold(3.6, "talk", {look: q.headPos().clone()}, `разговаривает с ${q.name}`));
      backToDesk(p);
      return true;
    },
    window(p) {
      const spot = spotFree(world.spots.window); if (!spot) return false; taken.add(spot);
      const phone = Math.random() < 0.5;
      leave(p);
      p.push(A.walk(new THREE.Vector3(spot.x, 0, spot.z), "идёт к окну"), A.turn(spot.yaw),
        phone ? A.call(q => { q.prop.phone = 1; q.say(pick(["Да, всё по плану — пока только демо-счёт.", "Нет, деньги не трогаем, пока нет доказательств.", "Перезвоню после стендапа, ок?"])); }) : A.call(() => {}),
        A.hold(rand(7, 12), phone ? "phone" : "window", {look: spot.faceTo}, phone ? "говорит по телефону у окна" : "смотрит в окно"),
        A.call(q => { q.prop.phone = 0; taken.delete(spot); }));
      backToDesk(p);
      return true;
    },
    board(p) {
      const spot = world.spots.board; if (!spot || taken.has(spot)) return false; taken.add(spot);
      leave(p);
      const st = D.stageCounts();
      p.push(A.walk(new THREE.Vector3(spot.x, 0, spot.z), "идёт к доске стратегий"), A.turn(Math.atan2(spot.faceTo.x - spot.x, spot.faceTo.z - spot.z)),
        A.call(q => q.say(`В разведке ${D.sleeves().filter(s => s.stage === "exploration").length}, в инкубации ${st.incubation || 0}, боевых ${st.production || 0}. Повышаем только по доказательствам.`)),
        A.hold(4.5, "point", {point: spot.faceTo, look: spot.faceTo}, "разбирает конвейер стратегий"), A.call(() => taken.delete(spot)));
      backToDesk(p);
      return true;
    },
    sofa(p) {
      const spot = spotFree(world.spots.sofa); if (!spot) return false; taken.add(spot);
      leave(p);
      const seat = {pos: new THREE.Vector3(spot.x, 0, spot.z), dock: new THREE.Vector3(spot.x, 0, spot.z - 0.55), yaw: spot.yaw, hipsY: 0.565, kind: "sofa"};
      p.push(A.call(q => { world.setMug(q.desk.mugIdx, false); q.prop.mug = 1; }), A.walk(seat.dock, "идёт на диван"), A.turn(spot.yaw), A.sitDown(seat),
        A.hold(rand(12, 20), "sofa", null, "отдыхает на диване с кофе"), A.standUp(), A.call(q => { taken.delete(spot); }));
      backToDesk(p);
      p.push(A.call(q => { q.prop.mug = 0; world.setMug(q.desk.mugIdx, true); }));
      return true;
    },
    foosball(p) {
      const q = pick(people.filter(x => x !== p && x.idle && x.id !== "viktor")); const [s1, s2] = world.spots.foos;
      if (!q || taken.has(s1)) return false; taken.add(s1);
      let ready = 0;
      for (const [x, s] of [[p, s1], [q, s2]]) {
        leave(x);
        x.push(A.walk(new THREE.Vector3(s.x, 0, s.z), "идёт играть в настольный футбол"), A.turn(s.yaw), A.call(() => { ready++; }), A.until(() => ready >= 2, "idle", "ждёт соперника", 40),
          A.hold(rand(16, 22), "foos", {rods: s.rods, look: new THREE.Vector3(13.2, 0.95, 7.6)}, "играет в настольный футбол"));
        backToDesk(x);
      }
      p.push(A.call(() => taken.delete(s1)));
      setTimeout(() => { if (Math.random() < 0.6) (Math.random() < 0.5 ? p : q).say(pick(["Гол! 3:2 ⚽", "Это была тренировка.", "Реванш после стендапа!"])); }, 14000);
      return true;
    },
    deskBreak(p) {
      const a = pick(["stretch", "phone", "think"]);
      p.busyErrand = true;
      if (a === "phone") p.push(A.call(q => { q.prop.phone = 1; q.say(pick(["Алло? Да, на месте.", "Да, выгрузка уже на GitHub.", "Давай в пять, сейчас стендап."])); }));
      p.push(A.hold(a === "stretch" ? 3.2 : rand(5, 8), a), A.call(q => { q.prop.phone = 0; q.busyErrand = false; q.activity = "work"; }));
      return true;
    },
  };

  // CEO's own habits: a printed report, a walk past the trading floor
  function ceoHabit(p) {
    if (Math.random() < 0.5) {
      p.busyErrand = true;
      p.push(A.call(q => { q.prop.paper = 1; }), A.hold(rand(9, 14), "paper", null, "читает распечатку отчёта"), A.call(q => { q.prop.paper = 0; q.busyErrand = false; }));
      return true;
    }
    leave(p);
    const spot = new THREE.Vector3(rand(-2.5, 2.5), 0, -5.3), cap = D.capital(), open = D.open();
    p.push(A.walk(spot, "обходит торговый зал"), A.turn(Math.PI),
      A.call(q => q.say(cap ? `Капитал ${fmt.n(cap, 0)} USDT, позиций ${open.length}. Главное — стоп на бирже у каждой.` : "Как там рынок? Только по правилам, без героизма.")),
      A.hold(6, "window", {look: new THREE.Vector3(0, 2.1, -11.9)}, "смотрит на видеостену"));
    backToDesk(p);
    return true;
  }
  // researcher brings results to the CEO (on a lab import, or now and then)
  function deliverReport(text) {
    const r = byId.artem, ceo = byId.viktor; if (!r.idle || !ceo.idle) return false;
    const spot = world.spots.visitor;
    leave(r);
    r.push(A.call(q => { q.prop.paper = 1; }), A.walk(new THREE.Vector3(spot.x, 0, spot.z), "несёт результаты управляющему"), A.turn(spot.yaw),
      A.call(q => { q.say(text, 6000); ceo.lookAt = q; ceo.lookUntil = performance.now() + 7000; }), A.hold(3.2, "talk", {look: spot.faceTo}, "докладывает управляющему"),
      A.call(q => { q.prop.paper = 0; ceo.say(pick(["Хорошо. В демо — только с маленьким риском, дальше решит форвард-тест.", "Отлично. Без доказательств на вне выборки — никаких повышений.", "Принято. Пусть Ника прогонит через все ворота."]), 5000); }),
      A.hold(2.8, "talk", {look: spot.faceTo}, "слушает управляющего"));
    backToDesk(r);
    return true;
  }
  function dialogue(p, q) {
    const pos = D.open()[0], run = D.running(), ev = D.nextEvent(), mem = D.mem();
    const byPair = {
      "ivan>nika": pos ? [`Ника, по ${coin(pos.pair)} всё в рамках риска?`, `Да, стоп на бирже, риск 0,1%. Держим по плану.`] : null,
      "sofia>oleg": [`Олег, сколько у нас реально независимых ставок?`, S.ov?.exposure?.eff_bets != null ? `Около ${fmt.n(S.ov.exposure.eff_bets, 1)} — позиции сильно связаны.` : "Пока считать нечего, позиций мало."],
      "anna>mark": ev ? [`Марк, ${ev.name.toLowerCase()} через ${fmt.until(ev.ts)}. Готовы?`, "Да, стратегии с фильтром событий не войдут рядом с релизом."] : null,
      "artem>dina": run ? [`Дина, идёт ${run.family}, эпоха ${run.progress?.epoch ?? "—"}. Тесты зелёные?`, "Все зелёные. Посмотрю, что даст walk-forward."] : ["Дина, когда новый прогон?", "Скоро, допишу проверку и запущу."],
      "gleb>viktor": [`Виктор, бот ${S.hl?.bot_up ? "работает" : "не отвечает"}${mem ? `, свободной памяти ${fmt.n(mem)} МБ` : ""}.`, "Спасибо. Главное — стабильность."],
      "mila>ivan": ["Иван, по последним стопам: цена потом шла к цели?", "Не всегда. Нужны 30 случаев, тогда будет вывод."],
    };
    return byPair[`${p.id}>${q.id}`] || pick([[`${q.name}, глянь на это.`, "Интересно. Давай проверим на данных, а не на ощущениях."], [`${q.name}, что думаешь?`, "Похоже на шум. Подождём выборку побольше."], [`${q.name}, кофе?`, "Через пять минут, дописываю."]]);
  }

  // ---------------- stand-up: every line is real data
  function standup() {
    if (meeting || !S.ov) return false;
    const cast = ["viktor", "artem", "nika", "ivan", "gleb"].map(id => byId[id]).filter(p => p.idle);
    if (cast.length < 4) return false;
    const rd = D.readiness(), run = D.running(), last = D.lastDone(), hl = S.hl || {}, ex = S.ov?.exposure || {};
    const lines = {
      viktor: `Стендап. Капитал ${fmt.n(D.capital(), 0)} USDT, готовность к реальным деньгам ${rd.passed ?? 0}/${rd.total ?? 10}. Позиций ${D.open().length}.`,
      artem: run ? `В лаборатории идёт ${run.family}: ${run.progress?.stage || "работа"}.` : last ? `Последний результат: ${last.variant || last.family} — ${({validated: "валидирована", exploratory: "разведка", rejected: "отклонена"})[last.summary?.verdict] || last.status}.` : "Ждём следующий прогон на GitHub.",
      nika: ex.eff_bets != null ? `Независимых ставок около ${fmt.n(ex.eff_bets, 1)}, ${fmt.pct(ex.one_side_share, 0)} риска в одну сторону. Лимиты соблюдены.` : "Риск в рамках лимитов. Ворота строгие, без исключений.",
      ivan: `${D.sleeves().length} стратегий торгуют на демо, у каждой сделки стоп на бирже.`,
      gleb: `Бот ${hl.bot_up ? "работает" : "НЕ ОТВЕЧАЕТ"}, тест ордеров ${hl.exec_test?.ok ? "пройден" : "ждёт"}${hl.disk ? `, на диске ${fmt.n(hl.disk.free / 1e9, 1)} ГБ` : ""}.`,
    };
    const seats = world.spots.meeting;
    meeting = {cast, arrived: 0, i: -1, at: 0};
    cast.forEach((p, k) => {
      const s = seats[k], seat = {pos: new THREE.Vector3(s.x, 0, s.z), dock: new THREE.Vector3(s.x, 0, s.z).addScaledVector(new THREE.Vector3(Math.sin(s.yaw), 0, Math.cos(s.yaw)), -0.6), yaw: s.yaw, hipsY: 0.555, chair: s.chair, kind: "meet", table: s.table};
      leave(p);
      p.push(A.walk(seat.dock, "идёт на стендап"), A.turn(s.yaw), A.sitDown(seat), A.call(() => { meeting.arrived++; }),
        A.until(() => meeting.done, "work", "на стендапе", 90), A.standUp());
      backToDesk(p);
    });
    meeting.lines = cast.map(p => [p, lines[p.id]]);
    return true;
  }
  function runMeeting(dt) {
    if (!meeting) return;
    if (meeting.arrived < meeting.cast.length) { meeting.wait = (meeting.wait || 0) + dt; if (meeting.wait > 80) meeting.done = true; }
    else {
      meeting.at -= dt;
      if (meeting.at <= 0) {
        meeting.i++;
        if (meeting.i >= meeting.lines.length) { meeting.done = true; }
        else { const [sp, text] = meeting.lines[meeting.i]; sp.say(text, 6000); ui.feed(sp, text); meeting.at = 6.2; for (const p of meeting.cast) if (p !== sp) { p.lookAt = sp; p.lookUntil = performance.now() + 6000; } }
      }
    }
    if (meeting.done && meeting.cast.every(p => p.seat?.kind !== "meet")) { meeting = null; nextStandup = clock + rand(260, 360); }
  }

  // ---------------- reactions to the real system
  function traderFor(tag) { const i = D.sleeves().findIndex(s => s.id === tag); return i >= 0 && i % 2 ? byId.sofia : byId.ivan; }
  function onData(type, payload) {
    if (type === "opened") {
      const t = payload, tr = traderFor(t.enter_tag), msg = `Открыл ${t.is_short ? "шорт" : "лонг"} ${coin(t.pair)} по ${fmt.price(t.open_rate)} — стоп уже на бирже.`;
      tr.say(msg); ui.feed(tr, msg);
    } else if (type === "closed") {
      const t = payload, tr = traderFor(t.enter_tag), pnl = Number(t.profit_abs || 0), win = pnl >= 0;
      const msg = win ? `${coin(t.pair)} закрыта: ${fmt.signed(pnl, 2)} $. По плану!` : `${coin(t.pair)} закрыта по стопу: ${fmt.signed(pnl, 2)} $. Риск был заложен.`;
      tr.say(msg); ui.feed(tr, msg);
      if (tr.idle) { tr.busyErrand = true; tr.push(A.hold(win ? 2.2 : 1.8, win ? "cheer" : "facepalm"), A.call(q => { q.busyErrand = false; q.activity = "work"; })); }
      setTimeout(() => { const m = byId.mila; const x = `Добавлю ${coin(t.pair)} в разбор: что было после выхода.`; m.say(x); ui.feed(m, x); }, 2500);
    } else if (type === "events") {
      for (const e of payload.slice(-3)) {
        const m = e.message || "", src = e.source;
        let who = byId.viktor, text = null;
        if (src === "research" && /^lab: .*run .* started/.test(m)) { who = byId.artem; text = "Новый прогон лаборатории на GitHub запущен — тяжёлые расчёты не на нашем сервере."; }
        else if (src === "research" && /imported/.test(m)) { who = byId.artem; text = "Результаты из лаборатории пришли — несу Виктору."; setTimeout(() => deliverReport(`Свежая партия из лаборатории: ${S.rs?.counts?.done ?? "—"} экспериментов всего. Кандидаты — к Нике на ворота.`), 1500); }
        else if (src === "research" && /experiment .* started/.test(m)) { who = pick([byId.artem, byId.dina]); text = `Стартовал эксперимент: ${(/— (\w+)/.exec(m) || [])[1] || "новое семейство"}.`; }
        else if (src === "research") { who = byId.artem; text = /validated/.test(m) ? "Кандидат прошёл все ворота! В инкубацию с малым риском." : /rejected/.test(m) ? "Отклонено — подгонку не торгуем." : null; }
        else if (src === "lifecycle") { who = byId.viktor; text = /production/.test(m) ? "Стратегия повышена до боевой — следим вдвойне." : /retired/.test(m) ? "Стратегию снимаем: доказательств не хватило." : "Обновили состав стратегий."; }
        else if (src === "risk") { who = byId.nika; text = "Риск-событие — проверяю лимиты."; }
        else if (["supervisor", "selftest", "manager", "memory"].includes(src)) { who = byId.gleb; text = /fail|error|exited|stale/i.test(m) ? "Вижу ошибку в сервисе — разбираюсь." : "Сервисы в порядке."; }
        else if (src === "learner") { who = byId.mila; text = "Новый вывод из сделок — поставим на A/B-тест."; }
        else if (src === "scanner") { who = byId.leya; text = "Обновили вселенную монет."; }
        if (text) who.say(text);
        ui.feed(who, text || m, m);
      }
    }
  }

  function update(dt, t) {
    clock += dt;
    for (const p of people) p.update(dt, t);
    runMeeting(dt);
    if (clock > nextStandup && !meeting) { if (!standup()) nextStandup = clock + 30; }
    for (const p of people) {
      if (!p.idle || meeting?.cast.includes(p)) continue;
      p.nextErrand -= dt; if (p.nextErrand > 0) continue;
      p.nextErrand = rand(35, 95);
      if (p.id === "viktor") { ceoHabit(p); continue; }
      if (awayCount() >= 3) continue;
      const r = Math.random();
      const ok = r < 0.3 ? errands.coffee(p) : r < 0.5 ? errands.visit(p) : r < 0.6 ? errands.window(p) : r < 0.68 ? errands.board(p) : r < 0.75 ? errands.sofa(p) : r < 0.8 ? errands.foosball(p) : errands.deskBreak(p);
      if (!ok) errands.deskBreak(p);
    }
    if (clock > 30 && Math.random() < dt / 400) deliverReport(D.lastDone() ? `Последний результат: ${D.lastDone().variant || D.lastDone().family}. Решение — за форвард-тестом.` : "Лаборатория ждёт следующий прогон.");
  }
  return {people, byId, update, onData, standup, errands, meeting: () => meeting};
}
