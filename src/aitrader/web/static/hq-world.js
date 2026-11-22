// AI Trader HQ — the office floor as one stylised diorama.
// Everything static is merged by material into a handful of meshes (vertex colours, no
// downloaded textures); chairs, mugs and server LEDs are instanced. Shadows are rendered once.
import * as THREE from "three";
import { mergeGeometries } from "three/addons/utils/BufferGeometryUtils.js";
import { RoundedBoxGeometry } from "three/addons/geometries/RoundedBoxGeometry.js";

export const W = 36, D = 24;               // floor: x ∈ [-18, 18], z ∈ [-12, 12]
const HX = W / 2, HZ = D / 2;

// ------------------------------------------------------------------ palette
export const P = {
  concrete: 0xcac3b7, concrete2: 0xc2bbae, slab: 0x9aa1aa, slabDark: 0x5d6570,
  wall: 0xe8e3da, wallBase: 0xcfc7ba, frame: 0x262b33, frameLight: 0x8a939e,
  oak: 0xc39468, oakDark: 0x9c6f48, walnut: 0x6e4a33, white: 0xf3f0ea,
  carpetTrade: [0x3a4658, 0x34404f], carpetLab: [0x3d4150, 0x373b49], carpetAna: [0x4a4f5f, 0x434858],
  carpetMeet: [0x2d5b57, 0x285250], raised: [0xdfe3e8, 0xd3d8de],
  fabric: 0x2c323d, fabric2: 0x3a4250, metal: 0x9aa3ad, black: 0x16191e, bezel: 0x121418,
  leaf: [0x3f8f5b, 0x2f7a4c, 0x5aa86e, 0x467f3e], pot: [0xece6dc, 0x2f3540, 0xc0714f, 0xb8b2a8],
  teal: 0x1fb89a, coral: 0xff7a6b, mustard: 0xf2b84b, navy: 0x23395d, sky: 0xbfe3f2,
};
const BOOKS = [0x2f5d8a, 0xc65b3f, 0xe0b04c, 0x3f7f5f, 0x7a4f8f, 0xd9d3c7, 0x23395d, 0x9b3d4c, 0x4f8fa3, 0x8c6a4a];

// ------------------------------------------------------------------ deterministic random
let seed = 1337;
export const rnd = () => ((seed = (seed * 16807) % 2147483647) - 1) / 2147483646;
const jitter = (hex, amt) => { const c = new THREE.Color(hex); const k = 1 + (rnd() - 0.5) * amt; c.r *= k; c.g *= k; c.b *= k; return c; };

// ------------------------------------------------------------------ geometry buckets
const _col = new THREE.Color();
const _cache = new Map();
function cached(key, make) { if (!_cache.has(key)) _cache.set(key, make()); return _cache.get(key); }
const G = {
  box: () => cached("box", () => new THREE.BoxGeometry(1, 1, 1)),
  rbox: (w, h, d, r, s = 2) => cached(`rb${w}|${h}|${d}|${r}|${s}`, () => new RoundedBoxGeometry(w, h, d, s, Math.min(r, w / 2, h / 2, d / 2) * 0.999)),
  cyl: (rt, rb, h, n = 16) => cached(`cy${rt}|${rb}|${h}|${n}`, () => new THREE.CylinderGeometry(rt, rb, h, n)),
  sphere: (n = 12, m = 9) => cached(`sp${n}|${m}`, () => new THREE.SphereGeometry(1, n, m)),
  ico: (d = 0) => cached(`ic${d}`, () => indexed(new THREE.IcosahedronGeometry(1, d))),
  plane: () => cached("pl", () => new THREE.PlaneGeometry(1, 1)),
  torus: (r, t, a = Math.PI * 2) => cached(`to${r}|${t}|${a}`, () => new THREE.TorusGeometry(r, t, 6, 14, a)),
  cone: (n = 7) => cached(`co${n}`, () => new THREE.ConeGeometry(1, 1, n)),
};
function indexed(g) {
  if (!g.index) { const n = g.attributes.position.count; g.setIndex([...Array(n).keys()]); }
  return g;
}
export class Bucket {
  constructor(keepUV = false) { this.parts = []; this.keepUV = keepUV; }
  add(geo, color, m) {
    const g = geo.clone();
    for (const k of Object.keys(g.attributes)) if (k !== "position" && k !== "normal" && !(this.keepUV && k === "uv")) g.deleteAttribute(k);
    indexed(g);
    if (m) g.applyMatrix4(m);
    const n = g.attributes.position.count, c = new Float32Array(n * 3);
    if (color.isColor) _col.copy(color); else _col.setHex(color);
    for (let i = 0; i < n; i++) { c[i * 3] = _col.r; c[i * 3 + 1] = _col.g; c[i * 3 + 2] = _col.b; }
    g.setAttribute("color", new THREE.BufferAttribute(c, 3));
    this.parts.push(g);
  }
  geometry() {
    if (!this.parts.length) return null;
    const g = mergeGeometries(this.parts, false);
    this.parts.forEach(p => p.dispose()); this.parts = [];
    g.computeBoundingSphere();
    return g;
  }
}
const _m = new THREE.Matrix4(), _q = new THREE.Quaternion(), _e = new THREE.Euler(), _p = new THREE.Vector3(), _s = new THREE.Vector3();
function compose(x, y, z, ry = 0, sx = 1, sy = 1, sz = 1, rx = 0, rz = 0) {
  _e.set(rx, ry, rz, "YXZ"); _q.setFromEuler(_e); _p.set(x, y, z); _s.set(sx, sy, sz);
  return new THREE.Matrix4().compose(_p, _q, _s);
}

// ------------------------------------------------------------------ kit: placement with a frame stack
function makeKit(nav) {
  const B = {solid: new Bucket(), shiny: new Bucket(), glass: new Bucket(), glow: new Bucket(), night: new Bucket()};
  let parent = new THREE.Matrix4(); const stack = [];
  const K = {
    B,
    push(x, y, z, ry = 0) { stack.push(parent); parent = parent.clone().multiply(compose(x, y, z, ry)); },
    pop() { parent = stack.pop(); },
    at(x, z, ry, fn) { K.push(x, 0, z, ry); fn(); K.pop(); },
    world(x, y, z) { return new THREE.Vector3(x, y, z).applyMatrix4(parent); },
    mat() { return parent.clone(); },
    yaw() { _e.setFromRotationMatrix(parent, "YXZ"); return _e.y; },
    put(bucket, geo, color, x, y, z, o = {}) {
      const local = compose(x, y, z, o.ry || 0, o.sx ?? 1, o.sy ?? 1, o.sz ?? 1, o.rx || 0, o.rz || 0);
      B[bucket].add(geo, color, parent.clone().multiply(local));
    },
    box(w, h, d, x, y, z, color, o = {}) { K.put(o.b || "solid", G.box(), color, x, y, z, {...o, sx: w, sy: h, sz: d}); },
    rbox(w, h, d, r, x, y, z, color, o = {}) { K.put(o.b || "solid", G.rbox(w, h, d, r, o.seg || 2), color, x, y, z, o); },
    cyl(rt, rb, h, x, y, z, color, o = {}) { K.put(o.b || "solid", G.cyl(rt, rb, h, o.n || 16), color, x, y, z, o); },
    ball(r, x, y, z, color, o = {}) { K.put(o.b || "solid", o.ico !== undefined ? G.ico(o.ico) : G.sphere(o.n || 12, o.m || 9), color, x, y, z, {...o, sx: r * (o.kx || 1), sy: r * (o.ky || 1), sz: r * (o.kz || 1)}); },
    block(x0, z0, x1, z1) {
      const pts = [[x0, z0], [x1, z0], [x0, z1], [x1, z1]].map(([x, z]) => K.world(x, 0, z));
      nav.block(Math.min(...pts.map(p => p.x)), Math.min(...pts.map(p => p.z)), Math.max(...pts.map(p => p.x)), Math.max(...pts.map(p => p.z)));
    },
  };
  return K;
}

// ------------------------------------------------------------------ navigation grid (A* + string pulling)
function makeNav() {
  const CELL = 0.25, NX = Math.ceil(W / CELL), NZ = Math.ceil(D / CELL), PAD = 0.24;
  const grid = new Uint8Array(NX * NZ);
  const ix = x => Math.floor((x + HX) / CELL), iz = z => Math.floor((z + HZ) / CELL);
  const cx = i => -HX + (i + 0.5) * CELL, cz = j => -HZ + (j + 0.5) * CELL;
  const ok = (i, j) => i >= 0 && j >= 0 && i < NX && j < NZ && !grid[j * NX + i];
  function block(x0, z0, x1, z1, pad = PAD) {
    for (let j = Math.max(0, iz(z0 - pad)); j <= Math.min(NZ - 1, iz(z1 + pad)); j++)
      for (let i = Math.max(0, ix(x0 - pad)); i <= Math.min(NX - 1, ix(x1 + pad)); i++) grid[j * NX + i] = 1;
  }
  function nearestFree(i, j) {
    if (ok(i, j)) return [i, j];
    for (let r = 1; r < 14; r++) for (let dj = -r; dj <= r; dj++) for (let di = -r; di <= r; di++)
      if ((Math.abs(di) === r || Math.abs(dj) === r) && ok(i + di, j + dj)) return [i + di, j + dj];
    return [i, j];
  }
  function los(a, b) {
    const [x0, z0] = a, [x1, z1] = b, n = Math.ceil(Math.hypot(x1 - x0, z1 - z0) / (CELL * 0.5));
    for (let k = 1; k < n; k++) { const t = k / n; if (!ok(ix(x0 + (x1 - x0) * t), iz(z0 + (z1 - z0) * t))) return false; }
    return true;
  }
  function route(from, to) {
    const [si, sj] = nearestFree(ix(from.x), iz(from.z)), [ti, tj] = nearestFree(ix(to.x), iz(to.z));
    const N = NX * NZ, g = new Float32Array(N).fill(Infinity), came = new Int32Array(N).fill(-1), closed = new Uint8Array(N);
    const open = [[0, sj * NX + si]]; g[sj * NX + si] = 0;
    const h = (i, j) => { const dx = Math.abs(i - ti), dz = Math.abs(j - tj); return (dx + dz) + (1.4142 - 2) * Math.min(dx, dz); };
    let found = false, guard = 0;
    while (open.length && guard++ < 40000) {
      let bi = 0; for (let k = 1; k < open.length; k++) if (open[k][0] < open[bi][0]) bi = k;
      const [, cur] = open[bi]; open[bi] = open[open.length - 1]; open.pop();
      if (closed[cur]) continue; closed[cur] = 1;
      const ci = cur % NX, cj = (cur / NX) | 0;
      if (ci === ti && cj === tj) { found = true; break; }
      for (let dj = -1; dj <= 1; dj++) for (let di = -1; di <= 1; di++) {
        if (!di && !dj) continue;
        const ni = ci + di, nj = cj + dj; if (!ok(ni, nj)) continue;
        if (di && dj && (!ok(ci + di, cj) || !ok(ci, cj + dj))) continue;
        const nk = nj * NX + ni, ng = g[cur] + (di && dj ? 1.4142 : 1);
        if (ng < g[nk]) { g[nk] = ng; came[nk] = cur; open.push([ng + h(ni, nj), nk]); }
      }
    }
    if (!found) return [new THREE.Vector3(to.x, 0, to.z)];
    const cells = []; for (let k = tj * NX + ti; k !== -1; k = came[k]) cells.push([cx(k % NX), cz((k / NX) | 0)]);
    cells.reverse();
    const pts = [[from.x, from.z]];
    let anchor = pts[0];
    for (let k = 1; k < cells.length; k++) if (!los(anchor, cells[k])) { anchor = cells[k - 1]; pts.push(anchor); }
    pts.push([to.x, to.z]);
    return pts.slice(1).map(([x, z]) => new THREE.Vector3(x, 0, z));
  }
  return {block, route, free: (x, z) => ok(ix(x), iz(z))};
}

// ------------------------------------------------------------------ small textures (canvas, generated once)
function canvasTexture(w, h, draw) {
  const c = document.createElement("canvas"); c.width = w; c.height = h; draw(c.getContext("2d"), w, h);
  const t = new THREE.CanvasTexture(c); t.colorSpace = THREE.SRGBColorSpace; t.anisotropy = 4; return t;
}
const radialTex = () => canvasTexture(64, 64, (g, w) => {
  const r = g.createRadialGradient(w / 2, w / 2, 0, w / 2, w / 2, w / 2);
  r.addColorStop(0, "#fff"); r.addColorStop(0.35, "rgba(255,255,255,.55)"); r.addColorStop(1, "rgba(255,255,255,0)");
  g.fillStyle = r; g.fillRect(0, 0, w, w);
});
function logoTexture() {
  return canvasTexture(512, 128, (g, w, h) => {
    g.fillStyle = "#0f1622"; g.fillRect(0, 0, w, h);
    const grd = g.createLinearGradient(0, 0, w, 0); grd.addColorStop(0, "#4ee6c4"); grd.addColorStop(1, "#6aa8ff");
    g.strokeStyle = grd; g.lineWidth = 7; g.beginPath(); // mark: a rising candle line
    g.moveTo(40, 88); g.lineTo(62, 66); g.lineTo(78, 76); g.lineTo(104, 40); g.stroke();
    g.fillStyle = grd; g.beginPath(); g.arc(104, 40, 7, 0, 7); g.fill();
    g.fillStyle = "#f3f6fa"; g.font = "700 52px Inter, system-ui, sans-serif"; g.textBaseline = "middle";
    g.fillText("AI TRADER", 132, 58);
    g.fillStyle = "#8fa3b8"; g.font = "500 18px Inter, system-ui, sans-serif"; g.fillText("исследования · риск · исполнение", 134, 98);
  });
}

// ------------------------------------------------------------------ the floor plan
export const ZONES = [
  {key: "trading", name: "Торговый зал", color: "#4ee6c4", rect: [-7.2, -11.9, 7.2, -3.6], label: [0, 3.8, -9.2]},
  {key: "research", name: "Лаборатория", color: "#a78bfa", rect: [-17.9, -11.9, -8.8, -5.2], label: [-13.4, 3.4, -9.6]},
  {key: "analysts", name: "Аналитики", color: "#6aa8ff", rect: [-17.9, -3.8, -9.6, 4.4], label: [-13.6, 2.6, 0.6]},
  {key: "ceo", name: "Кабинет управляющего", color: "#ffc15e", rect: [8.8, -11.9, 17.9, -3.6], label: [13.4, 3.2, -8]},
  {key: "risk", name: "Риск и валидация", color: "#ff8f70", rect: [-6, -1.8, 6.2, 4.4], label: [0, 2.6, 1.2]},
  {key: "ops", name: "Серверная", color: "#7fe8ff", rect: [9.2, -1.6, 17.9, 4.6], label: [13.6, 3.0, 1.4]},
  {key: "meeting", name: "Переговорная", color: "#f48fb1", rect: [-17.9, 5.4, -9.4, 11.9], label: [-13.6, 2.6, 8.6]},
  {key: "lounge", name: "Кухня и лаунж", color: "#c5e17a", rect: [6.5, 5.6, 17.9, 11.9], label: [12, 2.4, 9]},
];

export function buildWorld(scene, opts = {}) {
  seed = 1337;
  const nav = makeNav();
  const K = makeKit(nav);
  const desks = {}, displays = [], chairSlots = [], mugSlots = [], ledSlots = [], spots = {coffee: [], window: [], sofa: [], meeting: [], foos: [], visitor: null, board: null};

  // ---------------- building slab + the two floors below (cut-away diorama)
  K.box(W + 0.8, 0.5, D + 0.8, 0, -0.25, 0, P.slab);
  K.box(W + 0.82, 0.06, D + 0.82, 0, -0.03, 0, 0x8f897e);
  for (let f = 1; f <= 2; f++) {
    const y0 = -0.5 - (f - 1) * 3.2;
    K.box(W + 0.4, 0.5, D + 0.4, 0, y0 - 2.95, 0, P.slab);
    K.box(W, 2.45, D, 0, y0 - 1.47, 0, 0x2b3a4d);               // glass band
    for (let x = -HX; x <= HX + 0.01; x += 2.4) { K.box(0.12, 2.45, 0.12, x, y0 - 1.47, HZ + 0.05, P.frameLight); K.box(0.12, 2.45, 0.12, x, y0 - 1.47, -HZ - 0.05, P.frameLight); }
    for (let z = -HZ; z <= HZ + 0.01; z += 2.4) { K.box(0.12, 2.45, 0.12, HX + 0.05, y0 - 1.47, z, P.frameLight); K.box(0.12, 2.45, 0.12, -HX - 0.05, y0 - 1.47, z, P.frameLight); }
    for (let k = 0; k < 26; k++) { // lit windows on the floors below (glow at night)
      const side = k % 2, along = -HX + 1.2 + Math.floor(rnd() * 15) * 2.4, wy = y0 - 1.47 + (rnd() - 0.5) * 0.6;
      const c = jitter(0xffd9a0, 0.3);
      if (side) K.box(2.2, 1.6, 0.02, along, wy, HZ + 0.03, c, {b: "night"}); else K.box(0.02, 1.6, 2.2, HX + 0.03, wy, -HZ + 1.2 + Math.floor(rnd() * 10) * 2.4, c, {b: "night"});
    }
  }
  K.box(W + 0.4, 0.35, D + 0.4, 0, -7.1, 0, P.slabDark);

  // ---------------- floor: concrete tiles, then carpets and wood by zone
  const tile = 1.2;
  for (let x = -HX; x < HX - 0.01; x += tile) for (let z = -HZ; z < HZ - 0.01; z += tile)
    K.box(tile - 0.012, 0.02, tile - 0.012, x + tile / 2, 0.01, z + tile / 2, jitter(rnd() < 0.5 ? P.concrete : P.concrete2, 0.05));
  function carpet(x0, z0, x1, z1, [a, b], size = 0.6) {
    for (let x = x0; x < x1 - 0.01; x += size) for (let z = z0; z < z1 - 0.01; z += size) {
      const w = Math.min(size, x1 - x), d = Math.min(size, z1 - z), checker = (Math.round((x - x0) / size) + Math.round((z - z0) / size)) % 2;
      K.box(w - 0.006, 0.012, d - 0.006, x + w / 2, 0.026, z + d / 2, jitter(checker ? a : b, 0.04));
    }
  }
  function planks(x0, z0, x1, z1, base = P.oak) {
    for (let z = z0; z < z1 - 0.01; z += 0.22) {
      let x = x0 + (Math.round(z * 10) % 3) * -0.5;
      while (x < x1) { const len = 1.2 + rnd() * 1.4, a = Math.max(x, x0), b = Math.min(x + len, x1); if (b - a > 0.05) K.box(b - a - 0.008, 0.014, Math.min(0.22, z1 - z) - 0.008, (a + b) / 2, 0.027, z + Math.min(0.22, z1 - z) / 2, jitter(base, 0.14)); x += len; }
    }
  }
  carpet(-7, -11.8, 7, -3.8, P.carpetTrade);
  carpet(-17.8, -11.8, -8.9, -5.4, P.carpetLab);
  carpet(-17.8, -3.6, -9.8, 4.2, P.carpetAna);
  carpet(-17.8, 5.5, -9.5, 11.8, P.carpetMeet);
  carpet(9.3, -1.5, 17.8, 4.5, P.raised, 0.6);
  planks(8.9, -11.8, 17.8, -3.7);
  planks(6.6, 5.7, 17.8, 11.8, 0xb88a5c);

  // ---------------- walls: north + west tall with windows (sky shows through), south + east low (cut-away)
  const WH = 3.5;
  function wallSpan(axis, a0, a1, kind) {
    const len = a1 - a0, mid = (a0 + a1) / 2;
    const at = (along, y, h, depth, color, b = "solid") => axis === "x"
      ? K.box(len, h, depth, mid, y, -HZ + 0.1, color, {b})
      : K.box(depth, h, len, -HX + 0.1, y, mid, color, {b});
    if (kind === "solid") { at(0, WH / 2, WH, 0.2, P.wall); at(0, 0.06, 0.12, 0.24, P.wallBase); return; }
    at(0, 0.45, 0.9, 0.2, P.wall); at(0, 0.92, 0.05, 0.3, P.frameLight);
    at(0, 3.35, 0.3, 0.22, P.wall);
    at(0, 2.05, 2.3, 0.03, P.sky, "glass");
    const n = Math.max(1, Math.round(len / 2.2));
    for (let k = 0; k <= n; k++) {
      const p = a0 + (len * k) / n;
      if (axis === "x") K.box(0.07, 2.3, 0.12, p, 2.05, -HZ + 0.1, P.frame); else K.box(0.12, 2.3, 0.07, -HX + 0.1, 2.05, p, P.frame);
    }
    if (axis === "x") K.box(len, 0.05, 0.12, mid, 3.18, -HZ + 0.1, P.frame); else K.box(0.12, 0.05, len, -HX + 0.1, 3.18, mid, P.frame);
  }
  for (const [a, b, k] of [[-18, -16.1, "w"], [-16.1, -9.9, "solid"], [-9.9, -6.1, "w"], [-6.1, 6.1, "solid"], [6.1, 8.7, "w"], [8.7, 16.6, "solid"], [16.6, 18, "w"]]) wallSpan("x", a, b, k);
  for (const [a, b, k] of [[-12, -1.8, "w"], [-1.8, 3, "solid"], [3, 6.6, "w"], [6.6, 10.6, "solid"], [10.6, 12, "w"]]) wallSpan("z", a, b, k);
  nav.block(-HX, -HZ, HX, -HZ + 0.25, 0.2); nav.block(-HX, -HZ, -HX + 0.25, HZ, 0.2);
  // accent panels: each department gets its own colour on the wall behind its display
  for (const [x0, x1, c] of [[-16.1, -9.9, 0x2c2546], [-6.1, 6.1, 0x173345], [8.7, 16.6, 0x5a3f2e]]) K.box(x1 - x0 - 0.04, WH - 0.02, 0.02, (x0 + x1) / 2, WH / 2, -HZ + 0.21, c);
  for (const [z0, z1, c] of [[-1.8, 3, 0x1d2f4d], [6.6, 10.6, 0x3a2638]]) K.box(0.02, WH - 0.02, z1 - z0 - 0.04, -HX + 0.21, WH / 2, (z0 + z1) / 2, c);
  for (const [x0, x1] of [[-6.1, 6.1]]) for (let k = 0; k < 2; k++) K.box(x1 - x0 - 0.3, 0.02, 0.03, (x0 + x1) / 2, 0.55 + k * 3.02, -HZ + 0.23, 0x4ee6c4, {b: "glow"});
  // low parapets with a light strip (south, east), entrance gap on the south side
  for (const [x0, x1] of [[-18, -1.7], [1.7, 18]]) { K.box(x1 - x0, 0.42, 0.2, (x0 + x1) / 2, 0.21, HZ - 0.1, P.wall); K.box(x1 - x0, 0.025, 0.05, (x0 + x1) / 2, 0.43, HZ - 0.02, 0xfff1d6, {b: "glow"}); nav.block(x0, HZ - 0.25, x1, HZ, 0.2); }
  K.box(0.2, 0.42, D, HX - 0.1, 0.21, 0, P.wall); K.box(0.05, 0.025, D, HX - 0.02, 0.43, 0, 0xfff1d6, {b: "glow"}); nav.block(HX - 0.25, -HZ, HX, HZ, 0.2);

  // ---------------- glass partitions (frames + panes); door gaps stay walkable
  function partition(x0, z0, x1, z1, doors = [], h = 2.7) {
    const horiz = Math.abs(z1 - z0) < 0.01, a0 = horiz ? x0 : z0, a1 = horiz ? x1 : z1;
    const cuts = [a0, ...doors.flat(), a1];
    for (let k = 0; k < cuts.length; k += 2) {
      const s = cuts[k], e = cuts[k + 1], len = e - s, mid = (s + e) / 2; if (len < 0.05) continue;
      if (horiz) {
        K.box(len, h - 0.1, 0.025, mid, h / 2, z0, P.sky, {b: "glass"}); K.box(len, 0.06, 0.07, mid, h, z0, P.frame); K.box(len, 0.08, 0.07, mid, 0.04, z0, P.frame);
        for (let p = s; p <= e + 0.01; p += len / Math.max(1, Math.round(len / 1.8))) K.box(0.05, h, 0.07, p, h / 2, z0, P.frame);
        nav.block(s, z0 - 0.05, e, z0 + 0.05, 0.2);
      } else {
        K.box(0.025, h - 0.1, len, x0, h / 2, mid, P.sky, {b: "glass"}); K.box(0.07, 0.06, len, x0, h, mid, P.frame); K.box(0.07, 0.08, len, x0, 0.04, mid, P.frame);
        for (let p = s; p <= e + 0.01; p += len / Math.max(1, Math.round(len / 1.8))) K.box(0.07, h, 0.05, x0, h / 2, p, P.frame);
        nav.block(x0 - 0.05, s, x0 + 0.05, e, 0.2);
      }
    }
  }
  partition(8.8, -11.9, 8.8, -3.6, [[-5.4, -4.3]]);     // CEO west
  partition(8.8, -3.6, 17.9, -3.6);                      // CEO south
  partition(9.2, -1.6, 17.9, -1.6);                      // ops north
  partition(9.2, -1.6, 9.2, 4.6, [[2.2, 3.4]]);          // ops west with door
  partition(9.2, 4.6, 17.9, 4.6);                        // ops south
  partition(-17.9, 5.4, -9.4, 5.4);                      // meeting north
  partition(-9.4, 5.4, -9.4, 11.9, [[5.9, 7.0]]);        // meeting east with door

  // ---------------- props
  function plant(x, z, kind = 0, s = 1) {
    K.at(x, z, rnd() * 6, () => {
      const pot = P.pot[kind % P.pot.length];
      K.cyl(0.22 * s, 0.17 * s, 0.42 * s, 0, 0.21 * s, 0, pot, {n: 14});
      K.cyl(0.2 * s, 0.2 * s, 0.02, 0, 0.42 * s, 0, 0x4a3a2c, {n: 14});
      if (kind % 3 === 0) { // fiddle-leaf: trunk + leaf clusters
        K.cyl(0.025 * s, 0.03 * s, 0.9 * s, 0, 0.85 * s, 0, 0x5c4632, {n: 6});
        for (let k = 0; k < 7; k++) { const a = k * 2.4, r = 0.16 * s; K.ball(0.2 * s, Math.cos(a) * r, (0.95 + k * 0.1) * s, Math.sin(a) * r, jitter(P.leaf[k % 4], 0.2), {ico: 0, ky: 0.8}); }
      } else if (kind % 3 === 1) { // snake plant: blades
        for (let k = 0; k < 9; k++) { const a = k * 0.7; K.box(0.06 * s, (0.55 + rnd() * 0.4) * s, 0.015, Math.cos(a) * 0.08 * s, (0.65 + rnd() * 0.1) * s, Math.sin(a) * 0.08 * s, jitter(0x3c7a48, 0.25), {ry: a, rz: (rnd() - 0.5) * 0.3}); }
      } else { // round bush
        for (let k = 0; k < 6; k++) { const a = k * 1.1; K.ball(0.2 * s, Math.cos(a) * 0.12 * s, (0.6 + (k % 3) * 0.1) * s, Math.sin(a) * 0.12 * s, jitter(P.leaf[k % 4], 0.2), {ico: 0}); }
      }
      K.block(-0.24 * s, -0.24 * s, 0.24 * s, 0.24 * s);
    });
  }
  function rug(x, z, w, d, color, border) {
    K.rbox(w, 0.012, d, 0.004, x, 0.04, z, border, {seg: 1});
    K.rbox(w - 0.2, 0.014, d - 0.2, 0.004, x, 0.042, z, color, {seg: 1});
  }
  function bookshelf(x, z, ry, w = 3.2, h = 2.2) {
    K.at(x, z, ry, () => {
      K.box(w, h, 0.36, 0, h / 2, 0, P.walnut);
      for (let r = 0; r < 4; r++) {
        const y0 = 0.12 + r * (h - 0.2) / 4;
        K.box(w - 0.1, (h - 0.2) / 4 - 0.04, 0.3, 0, y0 + (h - 0.2) / 8, 0.04, 0x3d2a1e);
        let bx = -w / 2 + 0.12;
        while (bx < w / 2 - 0.2) {
          if (rnd() < 0.12) { bx += 0.18; continue; }
          const bw = 0.03 + rnd() * 0.04, bh = 0.2 + rnd() * 0.14;
          K.box(bw, bh, 0.22, bx + bw / 2, y0 + bh / 2 + 0.01, 0.06, BOOKS[Math.floor(rnd() * BOOKS.length)], {rz: rnd() < 0.08 ? 0.25 : 0});
          bx += bw + 0.004;
        }
      }
      K.block(-w / 2, -0.2, w / 2, 0.2);
    });
  }
  function frameArt(x, y, z, ry, w, h, seedColors) {
    K.at(x, z, ry, () => {
      K.box(w, h, 0.03, 0, y, 0.015, P.frame);
      K.box(w - 0.08, h - 0.08, 0.01, 0, y, 0.032, 0xf6f2ea);
      for (let k = 0; k < 4; k++) K.box((w - 0.2) * (0.2 + rnd() * 0.4), (h - 0.2) * (0.2 + rnd() * 0.4), 0.006, (rnd() - 0.5) * (w - 0.5), y + (rnd() - 0.5) * (h - 0.5), 0.04, seedColors[k % seedColors.length]);
    });
  }
  function sofa(x, z, ry, color, w = 2.2) {
    K.at(x, z, ry, () => {
      K.rbox(w, 0.34, 0.9, 0.08, 0, 0.23, 0, color, {seg: 2});
      K.rbox(w, 0.5, 0.22, 0.08, 0, 0.62, -0.36, color, {seg: 2});
      K.rbox(0.2, 0.36, 0.9, 0.07, -w / 2 + 0.1, 0.55, 0, color, {seg: 2}); K.rbox(0.2, 0.36, 0.9, 0.07, w / 2 - 0.1, 0.55, 0, color, {seg: 2});
      for (const sx of [-w / 4, w / 4]) K.rbox(w / 2 - 0.22, 0.1, 0.62, 0.05, sx, 0.44, 0.08, jitter(color, 0.1), {seg: 2});
      K.rbox(0.36, 0.3, 0.12, 0.05, w / 2 - 0.42, 0.72, -0.2, P.mustard, {seg: 2, rx: -0.2});
      for (const sx of [-w / 2 + 0.1, w / 2 - 0.1]) K.cyl(0.025, 0.02, 0.08, sx, 0.04, 0.3, P.black, {n: 6});
      K.block(-w / 2, -0.45, w / 2, 0.45);
    });
  }
  function chairGeometry(kind = "office") {
    const b = new Bucket(), put = (geo, col, x, y, z, o = {}) => b.add(geo, col, compose(x, y, z, o.ry || 0, o.sx ?? 1, o.sy ?? 1, o.sz ?? 1, o.rx || 0, o.rz || 0));
    if (kind === "office") {
      put(G.rbox(0.5, 0.08, 0.48, 0.035), P.fabric, 0, 0.44, 0.02);
      put(G.rbox(0.46, 0.56, 0.06, 0.04), P.fabric2, 0, 0.8, -0.23, {rx: -0.12});
      put(G.box(), P.black, 0, 0.6, -0.25, {sx: 0.05, sy: 0.3, sz: 0.04, rx: -0.12});
      put(G.cyl(0.03, 0.035, 0.3, 10), P.metal, 0, 0.26, 0);
      for (let k = 0; k < 5; k++) { const a = (k / 5) * Math.PI * 2; put(G.box(), P.black, Math.sin(a) * 0.15, 0.07, Math.cos(a) * 0.15, {ry: a, sx: 0.04, sy: 0.035, sz: 0.3}); put(G.sphere(8, 6), P.black, Math.sin(a) * 0.29, 0.035, Math.cos(a) * 0.29, {sx: 0.035, sy: 0.035, sz: 0.035}); }
      for (const sx of [-0.26, 0.26]) { put(G.box(), P.black, sx, 0.56, 0, {sx: 0.03, sy: 0.18, sz: 0.04}); put(G.rbox(0.06, 0.03, 0.24, 0.012), P.black, sx, 0.65, 0.02); }
    } else if (kind === "meet") {
      put(G.rbox(0.48, 0.07, 0.46, 0.03), 0xe9e3d8, 0, 0.45, 0.02);
      put(G.rbox(0.46, 0.4, 0.05, 0.03), 0xe9e3d8, 0, 0.72, -0.22, {rx: -0.1});
      for (const [sx, sz] of [[-0.2, -0.18], [0.2, -0.18], [-0.2, 0.2], [0.2, 0.2]]) put(G.cyl(0.015, 0.015, 0.44, 6), P.oakDark, sx, 0.22, sz);
    }
    return b.geometry();
  }

  // ---------------- desks: the people's workplaces (person faces local -Z; screens face +Z)
  function monitor(id, x, y, z, ry, w, h, tilt = 0, big = false, top = 0.74) {
    K.push(x, 0, z, ry);
    K.rbox(w + 0.035, h + 0.035, 0.03, 0.012, 0, y, 0, P.bezel, {b: "shiny", rx: tilt});
    K.rbox(w * 0.5, h * 0.45, 0.03, 0.01, 0, y, -0.03, 0x22262d, {b: "shiny", rx: tilt});
    const standTop = y - h * 0.2;
    K.box(0.045, standTop - top, 0.03, 0, (standTop + top) / 2, -0.05, 0x2a2f37, {b: "shiny"});
    K.rbox(big ? 0.3 : 0.22, 0.012, 0.16, 0.006, 0, top + 0.006, -0.03, 0x2a2f37, {b: "shiny"});
    if (rnd() < 0.35) K.box(0.035, 0.035, 0.002, w / 2 - 0.02, y + h / 2 - 0.03, 0.017, [0xffe27a, 0xff9bb5, 0x9be7ff][Math.floor(rnd() * 3)]);
    const mesh = new THREE.Mesh(G.plane(), null);
    mesh.matrixAutoUpdate = false;
    mesh.matrix.copy(K.mat().multiply(compose(0, y, 0.0165, 0, w, h, 1, tilt)));
    K.pop();
    const center = new THREE.Vector3().setFromMatrixPosition(mesh.matrix);
    const d = {id, mesh, w, h, center, normal: new THREE.Vector3(0, 0, 1).transformDirection(mesh.matrix)};
    displays.push(d);
    return d;
  }

  function desk(id, x, z, rot, o = {}) {
    const wide = o.wide || 1.6, deep = o.deep || 0.8, top = 0.74;
    const d = {id, rot};
    K.at(x, z, rot, () => {
      const wood = o.top || (o.dark ? P.walnut : rnd() < 0.5 ? P.white : P.oak);
      K.rbox(wide, 0.04, deep, 0.015, 0, top - 0.02, 0, wood);
      K.box(wide - 0.08, 0.02, deep - 0.08, 0, top - 0.05, 0, 0x2a2f37);
      for (const sx of [-wide / 2 + 0.07, wide / 2 - 0.07]) {
        K.box(0.05, top - 0.06, 0.05, sx, (top - 0.06) / 2, -deep / 2 + 0.12, 0x2a2f37);
        K.box(0.05, top - 0.06, 0.05, sx, (top - 0.06) / 2, deep / 2 - 0.12, 0x2a2f37);
        K.box(0.06, 0.03, deep - 0.1, sx, 0.015, 0, 0x2a2f37);
      }
      K.box(wide - 0.3, 0.32, 0.02, 0, 0.5, -deep / 2 + 0.06, 0x2a2f37);
      // keyboard, mouse, pad
      K.rbox(0.44, 0.018, 0.14, 0.008, -0.04, top + 0.009, 0.25, 0x23272e, {b: "shiny"});
      K.box(0.41, 0.004, 0.11, -0.04, top + 0.019, 0.25, 0x59606b);
      K.rbox(0.3, 0.004, 0.24, 0.004, 0.36, top + 0.002, 0.24, 0x2f3540);
      K.rbox(0.06, 0.024, 0.1, 0.02, 0.36, top + 0.012, 0.25, 0x23272e, {b: "shiny"});
      // personal props
      const props = o.props || [];
      if (props.includes("notebook")) { K.box(0.2, 0.015, 0.27, -0.55, top + 0.008, 0.12, [0xc65b3f, 0x2f5d8a, 0x3f7f5f][Math.floor(rnd() * 3)], {ry: 0.2}); K.box(0.19, 0.004, 0.26, -0.55, top + 0.017, 0.12, 0xf3efe6, {ry: 0.2}); }
      if (props.includes("papers")) for (let k = 0; k < 3; k++) K.box(0.21, 0.003, 0.29, -0.5 + k * 0.03, top + 0.003 + k * 0.003, 0.0 + k * 0.02, 0xf7f4ee, {ry: -0.15 + k * 0.12});
      if (props.includes("duck")) { K.ball(0.04, 0.62, top + 0.04, -0.12, 0xffd23f); K.ball(0.026, 0.62, top + 0.085, -0.1, 0xffd23f); K.box(0.02, 0.01, 0.03, 0.62, top + 0.083, -0.07, 0xff8c1a); }
      if (props.includes("cans")) for (let k = 0; k < 3; k++) K.cyl(0.03, 0.03, 0.12, -0.62 + k * 0.08, top + 0.06, -0.15 + (k % 2) * 0.06, [0x1fb89a, 0x111111, 0x1fb89a][k], {n: 10});
      if (props.includes("plant")) { K.cyl(0.06, 0.05, 0.1, -0.66, top + 0.05, -0.2, P.pot[0], {n: 10}); for (let k = 0; k < 4; k++) K.ball(0.055, -0.66 + Math.cos(k * 1.6) * 0.04, top + 0.14 + (k % 2) * 0.03, -0.2 + Math.sin(k * 1.6) * 0.04, P.leaf[k], {ico: 0}); }
      if (props.includes("lamp")) { K.cyl(0.07, 0.08, 0.02, -0.66, top + 0.01, -0.22, P.black); K.box(0.02, 0.4, 0.02, -0.66, top + 0.2, -0.22, P.black, {rx: 0.25}); K.cyl(0.04, 0.09, 0.1, -0.66, top + 0.4, -0.12, P.black, {rx: 0.6}); K.ball(0.03, -0.66, top + 0.36, -0.08, 0xfff1c4, {b: "glow"}); }
      if (props.includes("frame")) { K.box(0.14, 0.11, 0.015, 0.62, top + 0.065, -0.25, P.frame, {rx: -0.2, ry: -0.4}); K.box(0.12, 0.09, 0.005, 0.62, top + 0.066, -0.242, 0x6fb0d8, {rx: -0.2, ry: -0.4}); }
      if (props.includes("headphones")) { K.put("solid", G.torus(0.08, 0.012, Math.PI), P.black, 0.62, top + 0.02, 0.02, {rx: -Math.PI / 2}); }
      if (props.includes("nameplate")) { K.box(0.26, 0.06, 0.04, 0.45, top + 0.03, -0.3, 0x2b2b2b, {rx: -0.3}); K.box(0.22, 0.03, 0.002, 0.45, top + 0.035, -0.278, 0xd8b56a, {rx: -0.3}); }
      // monitors
      const mw = o.mw || 0.62, mh = mw * 0.625;
      if (o.second) {
        d.screen = monitor(id, -0.2, 1.06, -0.2, 0, mw, mh, -0.04);
        d.screen2 = monitor(id + "#2", 0.46, 1.03, -0.12, -0.42, 0.46, 0.46 * 0.625, -0.04);
      } else d.screen = monitor(id, 0, 1.06 + (mw > 0.7 ? 0.04 : 0), -0.2, 0, mw, mh, -0.04, mw > 0.7);
      K.block(-wide / 2, -deep / 2, wide / 2, deep / 2);
      d.seat = K.world(0, 0, 0.72); d.dock = K.world(0.0, 0, 1.4);
      d.keyboard = K.world(-0.04, top + 0.03, 0.25); d.mouse = K.world(0.36, top + 0.03, 0.25);
      d.mug = K.world(-0.42, top, 0.18); d.deskLeft = K.world(-0.5, top + 0.01, 0.3);
      d.visit = [K.world(1.08, 0, 0.8), K.world(-1.08, 0, 0.8)];
      d.yaw = K.yaw() + Math.PI; d.top = top;
      d.chair = chairSlots.length; chairSlots.push({kind: "office", x: d.seat.x, z: d.seat.z, yaw: d.yaw});
      d.mugIdx = mugSlots.length; mugSlots.push(d.mug.clone());
      K.block(-0.32, 0.45, 0.32, 1.0);
    });
    desks[id] = d;
    return d;
  }

  // ---------------- TRADING FLOOR: four desks face the video wall
  desk("ivan", -4.6, -7.6, 0, {second: true, props: ["notebook", "headphones"]});
  desk("sofia", -1.55, -7.6, 0, {second: true, props: ["plant", "frame"]});
  desk("oleg", 1.55, -7.6, 0, {props: ["papers", "cans"]});
  desk("mila", 4.6, -7.6, 0, {props: ["notebook", "plant"]});
  K.box(10.6, 0.06, 0.12, 0, 3.55, -11.7, P.frame);
  // ---------------- RESEARCH LAB
  desk("artem", -15, -8.6, 0, {second: true, props: ["papers", "lamp"]});
  desk("dina", -11.6, -8.6, 0, {props: ["duck", "notebook", "headphones"]});
  // GitHub runners: four glowing towers (LEDs light up while the lab runs)
  for (let k = 0; k < 4; k++) {
    const z = -10.9 + k * 1.05;
    K.rbox(0.55, 1.5, 0.75, 0.04, -17.25, 0.75, z, 0x1b1f27, {b: "shiny"});
    K.box(0.02, 1.3, 0.55, -16.97, 0.8, z, 0x2a3040);
    for (let j = 0; j < 6; j++) ledSlots.push({x: -16.95, y: 0.3 + j * 0.2, z: z, kind: "lab", k, sx: 1, sy: 4, sz: 18});
  }
  nav.block(-17.6, -11.4, -16.9, -6.9);
  plant(-9.6, -11.2, 0, 1.1);
  // ---------------- ANALYSTS: three desks face the news wall
  desk("anna", -13.2, -2.0, Math.PI / 2, {props: ["notebook", "papers"]});
  desk("mark", -13.2, 0.6, Math.PI / 2, {second: false, props: ["frame", "lamp"]});
  desk("leya", -13.2, 3.2, Math.PI / 2, {props: ["plant", "notebook"]});
  plant(-17.2, -3.4, 1); plant(-10.2, 4.0, 2, 0.9);
  // ---------------- CEO OFFICE
  desk("viktor", 14.6, -8.2, Math.PI / 2, {wide: 2.1, deep: 0.95, dark: true, mw: 0.78, props: ["papers", "nameplate", "lamp"]});
  bookshelf(11.2, -11.5, 0, 3.6, 2.4);
  rug(13.6, -6.2, 5.6, 4.2, 0x8a3e3a, 0xd9c7a8);
  sofa(16.6, -5.3, -Math.PI / 2, 0x6b4a3a, 2.0);
  K.rbox(0.9, 0.38, 0.6, 0.04, 15.3, 0.19, -5.3, P.walnut); K.cyl(0.07, 0.06, 0.12, 15.3, 0.44, -5.2, 0xe9e3d8, {n: 10}); nav.block(14.8, -5.6, 15.8, -5.0);
  plant(17.3, -11.2, 0, 1.15); plant(9.4, -11.2, 1);
  frameArt(14.9, 1.9, -11.75, 0, 1.6, 1.1, [P.coral, P.navy, P.mustard, P.teal]);
  spots.visitor = {x: 13.05, z: -8.2, yaw: Math.PI / 2, faceTo: new THREE.Vector3(14.6, 1.2, -8.2)};
  chairSlots.push({kind: "meet", x: 12.75, z: -8.2, yaw: Math.PI / 2});
  // ---------------- RISK + strategy pipeline board
  desk("nika", -1.6, 1.3, 0, {second: true, props: ["papers", "plant"]});
  K.at(3.6, 0.9, -0.35, () => {
    K.box(0.08, 1.2, 0.08, -0.9, 0.6, 0, P.frame); K.box(0.08, 1.2, 0.08, 0.9, 0.6, 0, P.frame);
    K.box(0.6, 0.04, 0.5, -0.9, 0.02, 0, P.frame); K.box(0.6, 0.04, 0.5, 0.9, 0.02, 0, P.frame);
    K.rbox(2.15, 1.3, 0.07, 0.03, 0, 1.75, 0, P.bezel, {b: "shiny"});
    K.block(-1.2, -0.3, 1.2, 0.3);
    const mesh = new THREE.Mesh(G.plane(), null); mesh.matrixAutoUpdate = false;
    mesh.matrix.copy(K.mat().multiply(compose(0, 1.75, 0.037, 0, 2.05, 1.2, 1)));
    displays.push({id: "board", mesh, w: 2.05, h: 1.2, center: new THREE.Vector3().setFromMatrixPosition(mesh.matrix), normal: new THREE.Vector3(0, 0, 1).transformDirection(mesh.matrix)});
    spots.board = {x: K.world(-0.5, 0, 1.0).x, z: K.world(-0.5, 0, 1.0).z, yaw: K.yaw(), faceTo: K.world(0, 1.6, 0)};
  });
  plant(-5.4, -1.2, 2); plant(5.8, 3.8, 1, 0.9);
  // ---------------- OPS / server room
  desk("gleb", 13.2, 2.7, 0, {second: true, props: ["cans", "headphones"]});
  for (let k = 0; k < 6; k++) {
    const x = 10.3 + k * 1.15;
    K.rbox(0.95, 2.1, 0.9, 0.03, x, 1.05, -0.9, 0x1a1e26, {b: "shiny"});
    K.box(0.85, 1.9, 0.02, x, 1.05, -0.44, 0x252b36);
    for (let j = 0; j < 9; j++) { K.box(0.8, 0.012, 0.01, x, 0.2 + j * 0.2, -0.43, 0x39414f); for (let l = 0; l < 3; l++) ledSlots.push({x: x - 0.34 + l * 0.05 + (j % 2) * 0.4, y: 0.24 + j * 0.2, z: -0.425, kind: "rack", k: k * 9 + j}); }
  }
  nav.block(9.8, -1.4, 17.3, -0.4);
  K.box(0.5, 2.0, 0.6, 17.4, 1.0, 3.6, 0xe6e9ee); K.box(0.02, 0.5, 0.3, 17.14, 1.4, 3.6, 0x7fe8ff, {b: "glow"}); nav.block(17.1, 3.2, 17.8, 4.0);
  // ---------------- MEETING ROOM
  K.at(-13.6, 8.6, 0, () => {
    K.rbox(3.6, 0.06, 1.4, 0.03, 0, 0.75, 0, P.oak);
    K.box(0.12, 0.72, 0.9, -1.2, 0.36, 0, P.frame); K.box(0.12, 0.72, 0.9, 1.2, 0.36, 0, P.frame);
    K.cyl(0.08, 0.08, 0.02, 0.9, 0.79, 0.1, 0xe8e2d8, {n: 10}); K.box(0.21, 0.003, 0.29, -0.6, 0.785, -0.2, 0xf7f4ee, {ry: 0.3});
    K.block(-1.8, -0.7, 1.8, 0.7);
    for (const [sx, sz, ry] of [[-1.1, -1.05, 0], [0, -1.05, 0], [1.1, -1.05, 0], [-1.1, 1.05, Math.PI], [0, 1.05, Math.PI], [1.1, 1.05, Math.PI]]) {
      const p = K.world(sx, 0, sz), yaw = K.yaw() + ry;
      spots.meeting.push({x: p.x, z: p.z, yaw, chair: chairSlots.length, table: K.world(sx * 0.95, 0.78, sz * 0.45)});
      chairSlots.push({kind: "meet", x: p.x, z: p.z, yaw});
    }
  });
  plant(-17.2, 11.2, 0, 1.1); plant(-10.0, 11.2, 2);
  frameArt(-9.55, 1.8, 9.4, -Math.PI / 2, 1.4, 0.9, [P.teal, P.mustard, P.navy]);
  // ---------------- LOUNGE + KITCHEN
  rug(9.8, 9.4, 4.4, 3.2, 0x3e5c6e, 0xe4dccd);
  sofa(9.6, 10.9, Math.PI, 0x2f6f6a, 2.6);
  for (const sx of [-0.8, 0, 0.8]) spots.sofa.push({x: 9.6 + sx, z: 10.75, yaw: Math.PI, sofa: true});
  K.rbox(1.3, 0.36, 0.7, 0.05, 9.6, 0.18, 9.2, P.oak); K.cyl(0.06, 0.05, 0.1, 9.3, 0.41, 9.2, P.coral, {n: 10}); K.box(0.25, 0.02, 0.18, 9.9, 0.37, 9.1, 0x2f5d8a); nav.block(8.9, 8.8, 10.3, 9.6);
  K.at(12.1, 9.1, -Math.PI / 2, () => { K.rbox(0.9, 0.4, 0.8, 0.08, 0, 0.25, 0, P.mustard); K.rbox(0.9, 0.5, 0.2, 0.08, 0, 0.6, -0.33, P.mustard); K.rbox(0.18, 0.3, 0.8, 0.06, -0.38, 0.5, 0, P.mustard); K.rbox(0.18, 0.3, 0.8, 0.06, 0.38, 0.5, 0, P.mustard); K.block(-0.45, -0.4, 0.45, 0.4); });
  K.at(15.4, 11.45, Math.PI, () => {   // kitchen counter against the south parapet, faces north
    K.box(4.4, 0.9, 0.7, 0, 0.45, 0, 0xf1eee8); K.box(4.44, 0.04, 0.74, 0, 0.92, 0, 0x3a3f47);
    for (let k = 0; k < 5; k++) K.box(0.02, 0.6, 0.002, -2 + k * 0.88 + 0.44, 0.5, 0.351, 0xc9c3b8);
    K.rbox(0.38, 0.5, 0.4, 0.04, -0.9, 1.19, 0.05, 0x2b2f36, {b: "shiny"}); K.box(0.2, 0.06, 0.02, -0.9, 1.33, 0.26, 0xffc15e, {b: "glow"}); K.box(0.1, 0.02, 0.12, -0.9, 0.95, 0.16, 0x111111);
    K.rbox(0.5, 0.3, 0.38, 0.03, 0.6, 1.09, 0.05, 0xd9d4cc); K.box(0.28, 0.18, 0.01, 0.55, 1.09, 0.245, 0x222222);
    for (let k = 0; k < 4; k++) K.cyl(0.04, 0.035, 0.1, 1.3 + k * 0.12, 0.99, 0.15, [0xffffff, P.coral, P.teal, P.mustard][k], {n: 10});
    K.block(-2.2, -0.35, 2.2, 0.35);
    const p = K.world(-0.9, 0, 0.85); spots.coffee.push({x: p.x, z: p.z, yaw: K.yaw() + Math.PI, faceTo: K.world(-0.9, 1.1, 0)});
    const p2 = K.world(0.6, 0, 0.85); spots.coffee.push({x: p2.x, z: p2.z, yaw: K.yaw() + Math.PI, faceTo: K.world(0.6, 1.1, 0)});
  });
  K.rbox(0.8, 2.0, 0.7, 0.05, 17.35, 1.0, 11.4, 0xdfe3e8, {b: "shiny"}); K.box(0.02, 0.6, 0.04, 17.0, 1.3, 11.15, 0x8a939e); nav.block(16.9, 11.0, 17.8, 11.8);
  K.cyl(0.16, 0.16, 0.9, 17.4, 0.45, 7.2, 0xe9edf1); K.cyl(0.13, 0.13, 0.4, 17.4, 1.1, 7.2, 0x7cc4f0, {b: "glass"}); nav.block(17.1, 6.9, 17.7, 7.5);
  K.at(13.2, 7.6, 0, () => {           // foosball
    K.box(1.3, 0.25, 0.72, 0, 0.8, 0, 0x2a2f37); K.box(1.2, 0.02, 0.62, 0, 0.93, 0, 0x2f8a4e);
    for (const sx of [-0.5, 0.5]) for (const sz of [-0.28, 0.28]) K.box(0.06, 0.68, 0.06, sx, 0.34, sz, 0x2a2f37);
    for (let k = 0; k < 4; k++) { const x = -0.45 + k * 0.3; K.cyl(0.012, 0.012, 1.1, x, 0.97, 0, P.metal, {rx: Math.PI / 2, n: 6}); for (let j = 0; j < 3; j++) K.box(0.03, 0.09, 0.03, x, 0.95, -0.2 + j * 0.2, k % 2 ? P.coral : 0x3d7bd9); }
    K.block(-0.7, -0.6, 0.7, 0.6);
    spots.foos.push({x: K.world(-1.05, 0, 0).x, z: K.world(-1.05, 0, 0).z, yaw: K.yaw() + Math.PI / 2, rods: [K.world(-0.62, 0.97, -0.25), K.world(-0.62, 0.97, 0.25)]});
    spots.foos.push({x: K.world(1.05, 0, 0).x, z: K.world(1.05, 0, 0).z, yaw: K.yaw() - Math.PI / 2, rods: [K.world(0.62, 0.97, 0.25), K.world(0.62, 0.97, -0.25)]});
  });
  plant(7.0, 11.3, 0, 1.2); plant(17.3, 6.0, 1); plant(7.0, 6.1, 2);
  // ---------------- RECEPTION with the logo
  K.at(0, 9.6, 0, () => {
    K.rbox(3.4, 1.05, 0.8, 0.12, 0, 0.525, 0, 0xf1eee8);
    K.rbox(3.5, 0.05, 0.9, 0.02, 0, 1.07, 0, P.oak);
    K.box(3.0, 0.04, 0.02, 0, 0.08, 0.41, 0x4ee6c4, {b: "glow"});
    K.block(-1.75, -0.45, 1.75, 0.45);
  });
  plant(-2.6, 10.8, 0, 1.25); plant(2.6, 10.8, 0, 1.25);
  // ---------------- window spots and a few more plants along the corridors
  spots.window.push({x: -7.8, z: -11.2, yaw: Math.PI, faceTo: new THREE.Vector3(-7.8, 1.6, -14)});
  spots.window.push({x: 7.4, z: -11.2, yaw: Math.PI, faceTo: new THREE.Vector3(7.4, 1.6, -14)});
  spots.window.push({x: -17.1, z: -4.6, yaw: -Math.PI / 2, faceTo: new THREE.Vector3(-20, 1.6, -4.6)});
  plant(-7.6, -4.4, 1); plant(7.6, -4.4, 2); plant(-6.4, 4.6, 0); plant(6.2, -2.6, 1, 0.9);

  // ---------------- night glow: light pools on the floor (additive, one draw call)
  const pools = [[0, -6, 9, 5, 0x9fd8ff], [-13.4, -8.4, 6, 4, 0xc8b5ff], [-13.6, 0.6, 5, 7, 0x9fc4ff], [13.4, -7.8, 7, 6, 0xffd9a0], [13.6, 1.4, 7, 5, 0x9ff0ff],
    [-13.6, 8.6, 6, 5, 0xffd9a0], [11.5, 9, 9, 5, 0xffd2a0], [0, 1.4, 8, 5, 0xffc9a8], [0, 9.6, 6, 3, 0x9ff5df]];
  const poolBucket = new Bucket(true);
  for (const [x, z, w, d, c] of pools) poolBucket.add(G.plane(), c, compose(x, 0.06, z, 0, w, d, 1, -Math.PI / 2));

  // ---------------- materials + meshes
  const mats = {
    solid: new THREE.MeshStandardMaterial({vertexColors: true, roughness: 0.82, metalness: 0}),
    shiny: new THREE.MeshStandardMaterial({vertexColors: true, roughness: 0.32, metalness: 0.35}),
    glass: new THREE.MeshStandardMaterial({vertexColors: true, roughness: 0.08, metalness: 0.1, transparent: true, opacity: 0.16, depthWrite: false}),
    glow: new THREE.MeshBasicMaterial({vertexColors: true, toneMapped: false}),
    night: new THREE.MeshBasicMaterial({vertexColors: true, toneMapped: false, transparent: true, opacity: 0, blending: THREE.AdditiveBlending, depthWrite: false}),
    pool: new THREE.MeshBasicMaterial({vertexColors: true, map: radialTex(), toneMapped: false, transparent: true, opacity: 0, blending: THREE.AdditiveBlending, depthWrite: false}),
  };
  const group = new THREE.Group(); group.name = "office";
  for (const key of ["solid", "shiny", "glass", "glow", "night"]) {
    const g = K.B[key].geometry(); if (!g) continue;
    const m = new THREE.Mesh(g, mats[key]);
    m.castShadow = key === "solid" || key === "shiny"; m.receiveShadow = key !== "glow" && key !== "night";
    if (key === "glass") m.renderOrder = 2;
    group.add(m);
  }
  const poolMesh = new THREE.Mesh(poolBucket.geometry(), mats.pool); poolMesh.renderOrder = 3; group.add(poolMesh);
  scene.add(group);

  // logo panel on the reception desk (canvas texture, drawn once)
  const logo = new THREE.Mesh(new THREE.PlaneGeometry(2.4, 0.6), new THREE.MeshBasicMaterial({map: logoTexture(), toneMapped: false}));
  logo.position.set(0, 0.6, 10.011); scene.add(logo);

  // the walls' big displays
  function wallDisplay(id, w, h, x, y, z, ry) {
    const mesh = new THREE.Mesh(G.plane(), null); mesh.matrixAutoUpdate = false;
    mesh.matrix.copy(compose(x, y, z, ry, w, h, 1));
    const bezel = new THREE.Mesh(cached("bezelBox", () => { const b = new Bucket(); b.add(G.box(), P.bezel); return b.geometry(); }), mats.shiny);
    bezel.position.set(x, y, z); bezel.rotation.y = ry; bezel.scale.set(w + 0.12, h + 0.12, 0.06);
    bezel.position.add(new THREE.Vector3(0, 0, -0.035).applyAxisAngle(new THREE.Vector3(0, 1, 0), ry));
    scene.add(bezel);
    displays.push({id, mesh, w, h, center: new THREE.Vector3(x, y, z), normal: new THREE.Vector3(0, 0, 1).applyAxisAngle(new THREE.Vector3(0, 1, 0), ry)});
  }
  wallDisplay("videowall", 10.2, 2.75, 0, 2.12, -11.72, 0);
  wallDisplay("labwall", 5.2, 1.95, -13.0, 2.0, -11.72, 0);
  wallDisplay("newswall", 3.9, 2.2, -17.72, 1.95, 0.6, Math.PI / 2);
  wallDisplay("meetwall", 3.4, 1.9, -17.72, 1.75, 8.6, Math.PI / 2);
  for (const d of displays) { d.mesh.matrixWorldNeedsUpdate = true; scene.add(d.mesh); }

  // ---------------- instanced chairs
  const chairGeo = {office: chairGeometry("office"), meet: chairGeometry("meet")};
  const chairs = {};
  for (const kind of ["office", "meet"]) {
    const list = chairSlots.map((c, i) => ({...c, i})).filter(c => c.kind === kind);
    const im = new THREE.InstancedMesh(chairGeo[kind], mats.solid, list.length);
    im.receiveShadow = true; im.castShadow = false;
    chairs[kind] = {im, list};
    scene.add(im);
  }
  const chairState = chairSlots.map(c => ({x: c.x, z: c.z, yaw: c.yaw, base: {...c}}));
  const _mat = new THREE.Matrix4(), _quat = new THREE.Quaternion(), _one = new THREE.Vector3(1, 1, 1), _pos = new THREE.Vector3(), _up = new THREE.Vector3(0, 1, 0);
  function writeChair(i) {
    const s = chairState[i], kind = chairSlots[i].kind, ch = chairs[kind], k = ch.list.findIndex(c => c.i === i);
    _quat.setFromAxisAngle(_up, s.yaw); _pos.set(s.x, 0, s.z); _mat.compose(_pos, _quat, _one);
    ch.im.setMatrixAt(k, _mat); ch.im.instanceMatrix.needsUpdate = true;
  }
  chairSlots.forEach((_, i) => writeChair(i));
  // chairs slide back when someone stands up and swivel a little while they work
  function setChair(i, pull = 0, swivel = 0) {
    const s = chairState[i], b = s.base;
    const yaw = b.yaw + swivel, bx = Math.sin(b.yaw), bz = Math.cos(b.yaw);
    s.x = b.x - bx * pull; s.z = b.z - bz * pull; s.yaw = yaw; writeChair(i);
  }

  // ---------------- instanced desk mugs (one disappears while its owner holds it)
  const mugGeo = (() => { const b = new Bucket(); b.add(G.cyl(0.04, 0.036, 0.1, 12), 0xffffff, compose(0, 0.05, 0)); b.add(G.torus(0.028, 0.008), 0xffffff, compose(0.045, 0.055, 0, Math.PI / 2)); b.add(G.cyl(0.035, 0.035, 0.005, 10), 0x4a2c1d, compose(0, 0.095, 0)); return b.geometry(); })();
  const mugs = new THREE.InstancedMesh(mugGeo, new THREE.MeshStandardMaterial({vertexColors: true, roughness: 0.5}), mugSlots.length);
  const mugColors = [0xffffff, P.coral, P.teal, P.mustard, 0x6aa8ff, 0xf48fb1];
  mugSlots.forEach((p, i) => { mugs.setColorAt(i, new THREE.Color(mugColors[i % mugColors.length])); });
  function setMug(i, visible) { _pos.copy(mugSlots[i]); _mat.compose(_pos, _quat.identity(), visible ? _one : new THREE.Vector3(0.001, 0.001, 0.001)); mugs.setMatrixAt(i, _mat); mugs.instanceMatrix.needsUpdate = true; }
  mugSlots.forEach((_, i) => setMug(i, true));
  scene.add(mugs);

  // ---------------- instanced LEDs (server racks + GitHub runners)
  const leds = new THREE.InstancedMesh(new THREE.BoxGeometry(0.025, 0.015, 0.01), new THREE.MeshBasicMaterial({toneMapped: false}), ledSlots.length);
  ledSlots.forEach((l, i) => { _mat.compose(_pos.set(l.x, l.y, l.z), _quat.identity(), new THREE.Vector3(l.sx || 1, l.sy || 1, l.sz || 1)); leds.setMatrixAt(i, _mat); leds.setColorAt(i, new THREE.Color(0x2bd67b)); });
  scene.add(leds);
  const _c = new THREE.Color();
  let ledClock = 0;
  function updateLeds(t, labActive, labProgress = 0) {
    if (t - ledClock < 0.16) return; ledClock = t;
    ledSlots.forEach((l, i) => {
      if (l.kind === "rack") {
        const h = Math.sin(i * 12.9898 + Math.floor(t * (3 + (i % 5))) * 78.233) * 43758.5453 % 1;
        _c.setHex(h > 0.35 ? (i % 11 === 0 ? 0xffb347 : 0x2bd67b) : 0x0d3320);
      } else {
        const lit = labActive ? (((Math.floor(t * 6) + l.k * 2 + i) % 6) < 4) : (i % 6 === 0);
        _c.setHex(labActive ? (lit ? 0xb79cff : 0x2c2148) : (lit ? 0x5a4a8a : 0x1d1830));
      }
      leds.setColorAt(i, _c);
    });
    leds.instanceColor.needsUpdate = true;
  }

  // ---------------- clouds drifting around the floating floor (one instanced mesh)
  const puff = (() => { const b = new Bucket(); for (let k = 0; k < 7; k++) b.add(G.sphere(10, 8), 0xffffff, compose((k - 3) * 0.9, Math.sin(k * 1.7) * 0.25, Math.cos(k * 2.1) * 0.5, 0, 1 + (k % 3) * 0.35, 0.8 + (k % 2) * 0.3, 1)); return b.geometry(); })();
  const cloudMat = new THREE.MeshStandardMaterial({vertexColors: true, roughness: 1, transparent: true, opacity: 0.9});
  const clouds = new THREE.InstancedMesh(puff, cloudMat, 7);
  const cloudData = [[-46, 9, -30, 3.0], [-52, 4, 22, 2.4], [40, 12, -44, 3.2], [58, 6, 4, 2.2], [14, 3, 52, 2.0], [-24, 14, -62, 3.6], [30, 18, -70, 4.0]];
  scene.add(clouds);
  function updateClouds(t) {
    cloudData.forEach(([x, y, z, s], i) => { _pos.set(x + Math.sin(t * 0.02 + i) * 3, y + Math.sin(t * 0.05 + i * 2) * 0.4, z); _mat.compose(_pos, _quat.identity(), new THREE.Vector3(s, s, s)); clouds.setMatrixAt(i, _mat); });
    clouds.instanceMatrix.needsUpdate = true;
  }
  updateClouds(0);
  const city = buildCity(scene);

  return {
    desks, displays, spots, nav, mats, setChair, setMug, updateLeds, updateClouds,
    chairOf: id => desks[id]?.chair,
    meetingChair: i => spots.meeting[i]?.chair,
    setNight(n, cloudTint, haze) {
      mats.night.opacity = n * 0.9; mats.pool.opacity = 0.05 + n * 0.5;
      cloudMat.color.copy(cloudTint);
      city.set(n, haze || cloudTint);
    },
  };
}

// ------------------------------------------------------------------ the city below: the office is the top floor of a tower
// ~500 towers in ONE instanced draw call + one ground plane. Windows, night lights and haze are
// computed in the shader (no textures); towers on the camera side stay low so they never hide the office.
const CITY_Y = -42;
const CITY_VS = `
varying vec3 vW; varying vec3 vN; varying vec3 vC; varying float vSeed;
void main() {
  mat4 m = modelMatrix;
  #ifdef USE_INSTANCING
  m = m * instanceMatrix;
  #endif
  vec4 w = m * vec4(position, 1.0);
  vW = w.xyz; vN = normalize(mat3(m) * normal);
  #ifdef USE_INSTANCING_COLOR
  vC = instanceColor;
  #else
  vC = vec3(0.55, 0.6, 0.66);
  #endif
  vSeed = fract(sin(float(gl_InstanceID) * 12.9898) * 43758.5453);
  gl_Position = projectionMatrix * viewMatrix * w;
}`;
const CITY_COMMON = `
uniform float uNight; uniform vec3 uHaze; uniform vec3 uSun;
float h21(vec2 p) { return fract(sin(dot(p, vec2(127.1, 311.7))) * 43758.5453); }
vec4 haze(vec3 c, vec3 w) {
  float r = length(w.xz);
  float k = clamp(smoothstep(20.0, 160.0, r) * 0.95 + clamp((-6.0 - w.y) / 70.0, 0.0, 0.5), 0.0, 0.94);
  return vec4(mix(c, uHaze, k), 1.0 - smoothstep(150.0, 205.0, r));
}`;
const CITY_FS = CITY_COMMON + `
varying vec3 vW; varying vec3 vN; varying vec3 vC; varying float vSeed;
void main() {
  vec3 n = normalize(vN), c;
  float lam = 0.74 + 0.3 * max(dot(n, uSun), 0.0);
  if (n.y > 0.5) {                                   // roofs: plant rooms and the odd red beacon at night
    vec2 g = fract(vW.xz / 3.0);
    c = vC * mix(0.92, 0.18, uNight) * (0.92 + 0.08 * step(0.5, g.x));
  } else if (n.y < -0.5) { c = vC * 0.2; }
  else {
    float u = abs(n.x) > 0.5 ? vW.z : vW.x;
    vec2 cell = floor(vec2(u / 1.6, vW.y / 3.2)), f = fract(vec2(u / 1.6, vW.y / 3.2));
    float win = step(0.12, f.x) * step(f.x, 0.88) * step(0.22, f.y) * step(f.y, 0.86);
    float r = h21(cell + vSeed * 97.0);
    float lit = step(0.7 - 0.12 * vSeed, r) * win;
    float aa = 1.0 - smoothstep(0.22, 0.55, max(fwidth(u / 1.6), fwidth(vW.y / 3.2)));   // far away: average, no shimmering
    win = mix(0.52, win, aa); lit = mix(0.12, lit, aa);
    vec3 dayGlass = mix(vC * 0.78, vec3(0.7, 0.8, 0.9), 0.5 + 0.22 * r);
    vec3 dayC = mix(vC * 1.06, dayGlass, win) * lam;
    vec3 warm = mix(vec3(1.0, 0.78, 0.5), vec3(0.75, 0.88, 1.0), step(0.85, h21(cell.yx + 3.1)));
    vec3 nightC = mix(vC * 0.07, mix(vC * 0.1, warm * (0.75 + 0.5 * r), lit), win);
    c = mix(dayC, nightC, uNight);
  }
  gl_FragColor = haze(c, vW);
}`;
const GROUND_VS = `varying vec3 vW; void main() { vec4 w = modelMatrix * vec4(position, 1.0); vW = w.xyz; gl_Position = projectionMatrix * viewMatrix * w; }`;
const GROUND_FS = CITY_COMMON + `
varying vec3 vW;
void main() {
  vec2 q = fract(vW.xz / 16.0), id = floor(vW.xz / 16.0);
  float road = 1.0 - step(0.16, q.x) * step(0.16, q.y);
  float mid = (1.0 - step(0.006, abs(q.x - 0.08))) * step(0.16, q.y) + (1.0 - step(0.006, abs(q.y - 0.08))) * step(0.16, q.x);
  float park = step(0.86, h21(id));
  vec3 day = mix(mix(vec3(0.62, 0.62, 0.6), vec3(0.45, 0.6, 0.42), park), vec3(0.32, 0.34, 0.37), road);
  day = mix(day, vec3(0.9), mid * 0.6);
  vec3 night = mix(vec3(0.03, 0.035, 0.05), vec3(0.06, 0.055, 0.05), road) + vec3(1.0, 0.7, 0.35) * road * 0.22 + vec3(1.0, 0.85, 0.6) * mid * 0.5;
  gl_FragColor = haze(mix(day, night, uNight), vW);
}`;
function buildCity(scene) {
  const uniforms = {uNight: {value: 0}, uHaze: {value: new THREE.Color(0xc9d9e8)}, uSun: {value: new THREE.Vector3(-0.4, 0.75, 0.55).normalize()}};
  const mat = new THREE.ShaderMaterial({uniforms, vertexShader: CITY_VS, fragmentShader: CITY_FS, transparent: true});
  const towers = [];
  const TINT = [0xa9b6c4, 0xbcc4cc, 0xcfc4b2, 0x90a0b2, 0xc2ccd4, 0x9fae9f, 0xd8cdbb, 0x8293a6];
  // our own tower under the office floor
  towers.push([0, (CITY_Y - 7.2) / 2, 0, W + 0.5, -7.2 - CITY_Y, D + 0.5, 0x41526a]);
  for (let bx = -160; bx <= 160; bx += 16) for (let bz = -160; bz <= 160; bz += 16) {
    const cx = bx + 8, cz = bz + 8, r = Math.hypot(cx, cz);
    if (Math.abs(cx) < 30 && Math.abs(cz) < 22) continue;          // plaza around our tower
    if (r > 190 || rnd() < 0.12) continue;
    const front = cx * 0.6 + cz * 0.8;                                // toward the default camera
    const n = rnd() < 0.35 ? 2 : 1;
    for (let k = 0; k < n; k++) {
      const w = n === 2 ? 4.5 + rnd() * 2 : 7 + rnd() * 5, d = n === 2 ? 9 + rnd() * 3 : 7 + rnd() * 5;
      const ox = n === 2 ? (k ? 3.2 : -3.2) : (rnd() - 0.5) * 2, oz = (rnd() - 0.5) * 2;
      let hgt = Math.min(14 + rnd() ** 1.6 * 62 * (r < 70 ? 1 : 0.75), r < 50 ? 50 : 99);
      if (front > 6) hgt = Math.min(hgt, 26 + rnd() * 6);              // keep the view onto the office open
      towers.push([cx + ox, CITY_Y + hgt / 2, cz + oz, w, hgt, d, TINT[Math.floor(rnd() * TINT.length)]]);
    }
  }
  const im = new THREE.InstancedMesh(new THREE.BoxGeometry(1, 1, 1), mat, towers.length);
  const m4 = new THREE.Matrix4(), col = new THREE.Color();
  towers.forEach(([x, y, z, w, h, d, c], i) => { m4.makeScale(w, h, d).setPosition(x, y, z); im.setMatrixAt(i, m4); im.setColorAt(i, col.setHex(c)); });
  im.frustumCulled = false; im.renderOrder = -2;
  const ground = new THREE.Mesh(new THREE.PlaneGeometry(420, 420).rotateX(-Math.PI / 2), new THREE.ShaderMaterial({uniforms, vertexShader: GROUND_VS, fragmentShader: GROUND_FS, transparent: true, depthWrite: false}));
  ground.position.y = CITY_Y; ground.renderOrder = -3;
  scene.add(ground, im);
  return {set(n, hz) { uniforms.uNight.value = n; uniforms.uHaze.value.copy(hz); }};
}
