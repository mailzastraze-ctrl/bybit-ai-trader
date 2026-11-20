// AI Trader HQ — a living 3D office driven by the real system state.
// Departments are real components; characters act out real events (research results,
// risk verdicts, lifecycle moves, trades, learnings, health) with dialogue built from data.
import * as THREE from "three";
import { OrbitControls } from "three/addons/controls/OrbitControls.js";
import { RoomEnvironment } from "three/addons/environments/RoomEnvironment.js";
import { GLTFLoader } from "three/addons/loaders/GLTFLoader.js";
import * as SkeletonUtils from "three/addons/utils/SkeletonUtils.js";

// ============================================================== utils
const $ = s => document.querySelector(s);
const esc = s => String(s ?? "").replace(/[&<>"]/g, c => ({"&": "&amp;", "<": "&lt;", ">": "&gt;", "\"": "&quot;"}[c]));
const num = (v, d = 2) => (v === null || v === undefined || isNaN(v)) ? "–" : Number(v).toLocaleString(undefined, {minimumFractionDigits: d, maximumFractionDigits: d});
const pct = (v, d = 1) => (v === null || v === undefined || isNaN(v)) ? "–" : (v * 100).toFixed(d) + "%";
const signed = v => `<span class="${v >= 0 ? "pos" : "neg"}">${num(v)}</span>`;
const rand = (a, b) => a + Math.random() * (b - a);
const pick = a => a[Math.floor(Math.random() * a.length)];
const clamp = (v, a, b) => Math.max(a, Math.min(b, v));
const lerp = (a, b, t) => a + (b - a) * t;
const damp = (a, b, k, dt) => lerp(a, b, 1 - Math.exp(-k * dt));
async function api(p) { const r = await fetch(p, {credentials: "same-origin"}); if (!r.ok) throw new Error(p + " " + r.status); return r.json(); }

// ============================================================== renderer / scene
const host = $("#scene");
const renderer = new THREE.WebGLRenderer({antialias: true, powerPreference: "high-performance"});
renderer.setPixelRatio(Math.min(devicePixelRatio, 1.75));
renderer.setSize(innerWidth, innerHeight);
renderer.shadowMap.enabled = true;
renderer.shadowMap.type = THREE.PCFShadowMap;
renderer.toneMapping = THREE.ACESFilmicToneMapping;
renderer.toneMappingExposure = 1.05;
renderer.outputColorSpace = THREE.SRGBColorSpace;
host.appendChild(renderer.domElement);

const scene = new THREE.Scene();
const pmrem = new THREE.PMREMGenerator(renderer);
scene.environment = pmrem.fromScene(new RoomEnvironment(), 0.04).texture;
scene.environmentIntensity = 0.55;
const SKY_DAY = new THREE.Color(0x9ec3e6), SKY_NIGHT = new THREE.Color(0x0b1424);
scene.background = SKY_DAY.clone();
scene.fog = new THREE.Fog(scene.background, 60, 150);

const camera = new THREE.PerspectiveCamera(34, innerWidth / innerHeight, 0.1, 500);
const HOME_POS = new THREE.Vector3(30, 31, 36), HOME_TGT = new THREE.Vector3(0, 0, 0);
camera.position.set(70, 70, 90);
const controls = new OrbitControls(camera, renderer.domElement);
controls.target.copy(HOME_TGT); controls.enableDamping = true; controls.dampingFactor = 0.08;
controls.maxPolarAngle = Math.PI * 0.46; controls.minDistance = 8; controls.maxDistance = 120;

const hemi = new THREE.HemisphereLight(0xf2f6ff, 0x3a3128, 0.9); scene.add(hemi);
const sun = new THREE.DirectionalLight(0xfff1dc, 2.2);
sun.position.set(-30, 45, 22); sun.castShadow = true; sun.shadow.mapSize.set(2048, 2048);
Object.assign(sun.shadow.camera, {left: -34, right: 34, top: 30, bottom: -30, near: 5, far: 140});
sun.shadow.bias = -0.0004; sun.shadow.normalBias = 0.02;
scene.add(sun);
const fill = new THREE.DirectionalLight(0xcfe0ff, 0.35); fill.position.set(30, 20, 30); scene.add(fill);

// ============================================================== materials & textures
function canvasTex(w, h, draw, repeat) {
  const c = document.createElement("canvas"); c.width = w; c.height = h; draw(c.getContext("2d"), w, h);
  const t = new THREE.CanvasTexture(c); t.colorSpace = THREE.SRGBColorSpace; t.anisotropy = 4;
  if (repeat) { t.wrapS = t.wrapT = THREE.RepeatWrapping; t.repeat.set(...repeat); }
  return t;
}
const woodTex = canvasTex(512, 512, (g, w, h) => {
  g.fillStyle = "#a07850"; g.fillRect(0, 0, w, h);
  for (let y = 0; y < h; y += 32) {
    const off = (y / 32) % 2 ? 128 : 0;
    for (let x = -off; x < w; x += 256) {
      const tone = 140 + Math.random() * 40;
      g.fillStyle = `rgb(${tone + 25},${tone - 10},${tone - 55})`; g.fillRect(x, y, 254, 30);
      g.strokeStyle = "rgba(60,35,15,.18)";
      for (let k = 0; k < 6; k++) { g.beginPath(); g.moveTo(x, y + 5 + k * 4 + Math.random() * 2); g.bezierCurveTo(x + 80, y + Math.random() * 30, x + 170, y + Math.random() * 30, x + 254, y + 4 + k * 4); g.stroke(); }
    }
  }
}, [6, 6]);
const carpetTex = (hex) => canvasTex(128, 128, (g, w, h) => {
  g.fillStyle = hex; g.fillRect(0, 0, w, h);
  for (let i = 0; i < 2500; i++) { g.fillStyle = `rgba(${Math.random() > .5 ? 255 : 0},${Math.random() > .5 ? 255 : 0},255,0.035)`; g.fillRect(Math.random() * w, Math.random() * h, 1, 1); }
}, [3, 3]);
const M = {
  wood: new THREE.MeshStandardMaterial({map: woodTex, roughness: 0.55, metalness: 0}),
  wall: new THREE.MeshStandardMaterial({color: 0xe9e6df, roughness: 0.9}),
  wallDark: new THREE.MeshStandardMaterial({color: 0x3a3d44, roughness: 0.7}),
  deskTop: new THREE.MeshStandardMaterial({color: 0xf2efe9, roughness: 0.35}),
  deskWood: new THREE.MeshStandardMaterial({color: 0x8a6243, roughness: 0.5}),
  metal: new THREE.MeshStandardMaterial({color: 0x7d838c, roughness: 0.3, metalness: 0.85}),
  black: new THREE.MeshStandardMaterial({color: 0x17181b, roughness: 0.4, metalness: 0.2}),
  chair: new THREE.MeshStandardMaterial({color: 0x22252b, roughness: 0.65}),
  glass: new THREE.MeshPhysicalMaterial({color: 0xcfe6ff, roughness: 0.05, metalness: 0, transmission: 0.0, transparent: true, opacity: 0.18, depthWrite: false}),
  frame: new THREE.MeshStandardMaterial({color: 0x2b2e34, roughness: 0.4, metalness: 0.6}),
  plantPot: new THREE.MeshStandardMaterial({color: 0xd9d4ca, roughness: 0.8}),
  leaf: new THREE.MeshStandardMaterial({color: 0x3f7d3a, roughness: 0.8}),
  leaf2: new THREE.MeshStandardMaterial({color: 0x5a9a48, roughness: 0.8}),
  sofa: new THREE.MeshStandardMaterial({color: 0x52607a, roughness: 0.85}),
  rack: new THREE.MeshStandardMaterial({color: 0x15171b, roughness: 0.35, metalness: 0.6}),
  paper: new THREE.MeshStandardMaterial({color: 0xfbfaf6, roughness: 0.9}),
  ceilLight: new THREE.MeshStandardMaterial({color: 0xffffff, emissive: 0xfff3e0, emissiveIntensity: 1.2}),
};
function at(o, x, y, z) { o.position.set(x, y, z); return o; }
function mesh(geo, mat, cast = true, recv = true) { const m = new THREE.Mesh(geo, mat); m.castShadow = cast; m.receiveShadow = recv; return m; }
function boxM(w, h, d, mat, x = 0, y = 0, z = 0) { const m = mesh(new THREE.BoxGeometry(w, h, d), mat); m.position.set(x, y, z); return m; }
function rbox(w, h, d, r, mat) { // rounded box via extruded rounded rect
  const s = new THREE.Shape(), x = -w / 2, y = -h / 2;
  s.moveTo(x + r, y); s.lineTo(x + w - r, y); s.quadraticCurveTo(x + w, y, x + w, y + r); s.lineTo(x + w, y + h - r);
  s.quadraticCurveTo(x + w, y + h, x + w - r, y + h); s.lineTo(x + r, y + h); s.quadraticCurveTo(x, y + h, x, y + h - r);
  s.lineTo(x, y + r); s.quadraticCurveTo(x, y, x + r, y);
  const g = new THREE.ExtrudeGeometry(s, {depth: d - 2 * Math.min(r, d / 2.2), bevelEnabled: true, bevelThickness: Math.min(r, d / 2.2), bevelSize: Math.min(r, d / 2.2) * 0.9, bevelSegments: 3, curveSegments: 6});
  g.center(); return mesh(g, mat);
}

// ============================================================== building
const W = 44, D = 30; // interior x ∈ [-22,22], z ∈ [-15,15]
const floor = mesh(new THREE.BoxGeometry(W, 0.3, D), M.wood, false, true); floor.position.y = -0.15; scene.add(floor);
const ground = mesh(new THREE.PlaneGeometry(400, 400), new THREE.MeshStandardMaterial({color: 0x5b6a52, roughness: 1}), false, true);
ground.rotation.x = -Math.PI / 2; ground.position.y = -0.31; scene.add(ground);
// plaza around the building
const plaza = mesh(new THREE.BoxGeometry(W + 10, 0.2, D + 10), new THREE.MeshStandardMaterial({color: 0xb8b2a6, roughness: 0.95}), false, true);
plaza.position.y = -0.25; scene.add(plaza);

// window walls (north z=-15, west x=-22) with mullions and glass; low walls elsewhere (cut-away)
function windowWall(len, axis, at) {
  const g = new THREE.Group();
  g.add(boxM(len, 0.9, 0.3, M.wall, 0, 0.45, 0));
  g.add(boxM(len, 0.35, 0.3, M.wall, 0, 3.32, 0));
  const pane = mesh(new THREE.BoxGeometry(len, 2.1, 0.04), M.glass, false, false); pane.position.y = 2.0; g.add(pane);
  for (let x = -len / 2; x <= len / 2 + 0.01; x += 2.2) g.add(boxM(0.08, 2.1, 0.12, M.frame, x, 2.0, 0));
  g.add(boxM(len, 0.06, 0.14, M.frame, 0, 0.93, 0));
  if (axis === "x") g.position.set(0, 0, at); else { g.rotation.y = Math.PI / 2; g.position.set(at, 0, 0); }
  scene.add(g); return g;
}
windowWall(W, "x", -D / 2); windowWall(D, "z", -W / 2);
scene.add(boxM(W, 0.5, 0.25, M.wall, 0, 0.25, D / 2)); scene.add(boxM(0.25, 0.5, D, M.wall, W / 2, 0.25, 0));

// city skyline outside the windows (instanced towers with lit windows)
const winTex = canvasTex(64, 128, (g, w, h) => {
  g.fillStyle = "#1d232c"; g.fillRect(0, 0, w, h);
  for (let y = 4; y < h; y += 8) for (let x = 4; x < w; x += 8) { g.fillStyle = Math.random() > 0.55 ? "#ffd99a" : "#29313c"; g.fillRect(x, y, 4, 5); }
}, [1, 1]);
const towerMat = new THREE.MeshStandardMaterial({color: 0x9aa4b2, map: winTex, emissiveMap: winTex, emissive: 0xffffff, emissiveIntensity: 0.0, roughness: 0.6, metalness: 0.3});
const towers = new THREE.InstancedMesh(new THREE.BoxGeometry(1, 1, 1), towerMat, 70);
{
  const m4 = new THREE.Matrix4(); let i = 0;
  for (; i < 70; i++) {
    const side = i % 2, h = rand(6, 24), w = rand(4, 9), d = rand(4, 9);
    const x = side ? rand(-100, 80) : rand(-115, -55), z = side ? rand(-115, -55) : rand(-80, 70);
    m4.compose(new THREE.Vector3(x, h / 2 - 0.3, z), new THREE.Quaternion(), new THREE.Vector3(w, h, d)); towers.setMatrixAt(i, m4);
  }
  towers.castShadow = false; towers.receiveShadow = true; scene.add(towers);
}

// ============================================================== nav grid (A*)
const CELL = 0.5, GX = Math.round(W / CELL), GZ = Math.round(D / CELL);
const blocked = new Uint8Array(GX * GZ);
const toCell = (x, z) => [clamp(Math.floor((x + W / 2) / CELL), 0, GX - 1), clamp(Math.floor((z + D / 2) / CELL), 0, GZ - 1)];
const toWorld = (cx, cz) => new THREE.Vector3(-W / 2 + (cx + 0.5) * CELL, 0, -D / 2 + (cz + 0.5) * CELL);
function block(x0, z0, x1, z1) {
  const [a, b] = toCell(Math.min(x0, x1), Math.min(z0, z1)), [c, d] = toCell(Math.max(x0, x1), Math.max(z0, z1));
  for (let i = a; i <= c; i++) for (let j = b; j <= d; j++) blocked[j * GX + i] = 1;
}
function blockObj(obj, pad = 0.15) { obj.updateMatrixWorld(true); const bb = new THREE.Box3().setFromObject(obj); block(bb.min.x - pad, bb.min.z - pad, bb.max.x + pad, bb.max.z + pad); }
block(-W / 2, -D / 2, W / 2, -D / 2 + 0.6); block(-W / 2, -D / 2, -W / 2 + 0.6, D / 2);
function findPath(from, to) {
  let [sx, sz] = toCell(from.x, from.z), [tx, tz] = toCell(to.x, to.z);
  const free = (x, z) => x >= 0 && z >= 0 && x < GX && z < GZ && !blocked[z * GX + x];
  const nearestFree = (x, z) => { if (free(x, z)) return [x, z]; for (let r = 1; r < 8; r++) for (let dx = -r; dx <= r; dx++) for (let dz = -r; dz <= r; dz++) if (free(x + dx, z + dz)) return [x + dx, z + dz]; return [x, z]; };
  [sx, sz] = nearestFree(sx, sz); [tx, tz] = nearestFree(tx, tz);
  const key = (x, z) => z * GX + x, open = [[0, sx, sz]], g = new Map([[key(sx, sz), 0]]), came = new Map();
  const h = (x, z) => Math.hypot(x - tx, z - tz);
  const dirs = [[1, 0, 1], [-1, 0, 1], [0, 1, 1], [0, -1, 1], [1, 1, 1.414], [1, -1, 1.414], [-1, 1, 1.414], [-1, -1, 1.414]];
  let guard = 0;
  while (open.length && guard++ < 20000) {
    let bi = 0; for (let i = 1; i < open.length; i++) if (open[i][0] < open[bi][0]) bi = i;
    const [, x, z] = open.splice(bi, 1)[0];
    if (x === tx && z === tz) break;
    for (const [dx, dz, c] of dirs) {
      const nx = x + dx, nz = z + dz;
      if (!free(nx, nz) || (dx && dz && (!free(x + dx, z) || !free(x, z + dz)))) continue;
      const ng = g.get(key(x, z)) + c, k = key(nx, nz);
      if (ng < (g.get(k) ?? Infinity)) { g.set(k, ng); came.set(k, key(x, z)); open.push([ng + h(nx, nz), nx, nz]); }
    }
  }
  const pts = []; let k = key(tx, tz);
  if (!came.has(k) && k !== key(sx, sz)) return [to.clone()];
  while (k !== undefined && k !== key(sx, sz)) { pts.push(toWorld(k % GX, Math.floor(k / GX))); k = came.get(k); }
  pts.reverse();
  // string-pull: drop points with line of sight
  const los = (a, b) => { const n = Math.ceil(a.distanceTo(b) / (CELL * 0.5)); for (let i = 1; i < n; i++) { const p = a.clone().lerp(b, i / n); const [cx, cz] = toCell(p.x, p.z); if (blocked[cz * GX + cx]) return false; } return true; };
  const out = []; let cur = from.clone();
  for (let i = 0; i < pts.length; i++) { if (i === pts.length - 1 || !los(cur, pts[i + 1])) { out.push(pts[i]); cur = pts[i]; } }
  out.push(to.clone()); return out;
}

// ============================================================== screens (live canvases)
const screens = [];
function screen(w, h, pw = 256, ph = 160) {
  const c = document.createElement("canvas"); c.width = pw; c.height = ph;
  const tex = new THREE.CanvasTexture(c); tex.colorSpace = THREE.SRGBColorSpace;
  const m = new THREE.Mesh(new THREE.PlaneGeometry(w, h), new THREE.MeshBasicMaterial({map: tex, toneMapped: false}));
  const s = {c, g: c.getContext("2d"), tex, mesh: m, draw: null}; screens.push(s); return s;
}
function drawSpark(g, x, y, w, h, pts, color) {
  if (pts.length < 2) return; const lo = Math.min(...pts), hi = Math.max(...pts), r = hi - lo || 1;
  g.strokeStyle = color; g.lineWidth = 2; g.beginPath();
  pts.forEach((v, i) => { const px = x + i / (pts.length - 1) * w, py = y + h - (v - lo) / r * h; i ? g.lineTo(px, py) : g.moveTo(px, py); }); g.stroke();
}

// ============================================================== furniture
const seats = {}; // name -> {pos, face, desk}
function chair() {
  const g = new THREE.Group();
  const seat = rbox(0.5, 0.08, 0.48, 0.04, M.chair); seat.position.y = 0.47; g.add(seat);
  const back = rbox(0.48, 0.55, 0.07, 0.04, M.chair); back.position.set(0, 0.8, 0.22); back.rotation.x = -0.1; g.add(back);
  g.add(boxM(0.05, 0.4, 0.05, M.metal, 0, 0.25, 0));
  for (let i = 0; i < 5; i++) { const a = i / 5 * Math.PI * 2; const leg = boxM(0.3, 0.03, 0.04, M.metal, Math.cos(a) * 0.15, 0.05, Math.sin(a) * 0.15); leg.rotation.y = -a; g.add(leg); }
  return g;
}
function plant(x, z, s = 1) {
  const g = new THREE.Group();
  const pot = mesh(new THREE.CylinderGeometry(0.22 * s, 0.17 * s, 0.42 * s, 16), M.plantPot); pot.position.y = 0.21 * s; g.add(pot);
  for (let i = 0; i < 9; i++) {
    const leaf = mesh(new THREE.SphereGeometry(0.16 * s, 8, 6), i % 2 ? M.leaf : M.leaf2);
    const a = i / 9 * Math.PI * 2; leaf.position.set(Math.cos(a) * 0.14 * s, (0.6 + Math.random() * 0.5) * s, Math.sin(a) * 0.14 * s);
    leaf.scale.set(1, 1.6, 0.6); leaf.rotation.set(rand(-.4, .4), a, rand(-.4, .4)); g.add(leaf);
  }
  g.position.set(x, 0, z); scene.add(g); blockObj(pot, 0.1); return g;
}
function desk(name, x, z, rot = 0, opts = {}) {
  const g = new THREE.Group();
  const top = rbox(1.6, 0.05, 0.8, 0.02, opts.dark ? M.deskWood : M.deskTop); top.position.y = 0.74; g.add(top);
  g.add(boxM(0.05, 0.72, 0.7, M.metal, -0.75, 0.36, 0)); g.add(boxM(0.05, 0.72, 0.7, M.metal, 0.75, 0.36, 0));
  g.add(boxM(1.45, 0.3, 0.02, M.metal, 0, 0.55, 0.3));
  const mon = rbox(0.62, 0.38, 0.03, 0.012, M.black); mon.position.set(0, 1.1, 0.22); g.add(mon);
  g.add(boxM(0.04, 0.22, 0.04, M.black, 0, 0.86, 0.25)); g.add(boxM(0.22, 0.015, 0.16, M.black, 0, 0.77, 0.25));
  const scr = screen(0.58, 0.34); scr.mesh.position.set(0, 1.1, 0.202); scr.mesh.rotation.y = Math.PI; g.add(scr.mesh);
  g.add(boxM(0.42, 0.02, 0.14, M.black, 0, 0.775, -0.05)); // keyboard
  if (opts.second) { const m2 = rbox(0.5, 0.32, 0.03, 0.012, M.black); m2.position.set(0.55, 1.07, 0.18); m2.rotation.y = -0.35; g.add(m2);
    const s2 = screen(0.46, 0.28); s2.mesh.position.set(0.545, 1.07, 0.163); s2.mesh.rotation.y = Math.PI - 0.35; g.add(s2.mesh); scr.second = s2; }
  if (Math.random() > 0.5) { const mug = mesh(new THREE.CylinderGeometry(0.04, 0.035, 0.09, 12), new THREE.MeshStandardMaterial({color: pick([0xe66767, 0x3987e5, 0xfab219, 0xffffff])})); mug.position.set(-0.55, 0.81, -0.1); g.add(mug); }
  if (Math.random() > 0.6) { const p = boxM(0.21, 0.01, 0.3, M.paper, 0.45, 0.77, -0.1); p.rotation.y = 0.3; g.add(p); }
  const ch = chair(); ch.position.set(0, 0, -0.7); ch.rotation.y = Math.PI; g.add(ch);
  g.position.set(x, 0, z); g.rotation.y = rot; scene.add(g);
  blockObj(top, 0.1);
  const seatPos = new THREE.Vector3(0, 0, -0.62).applyAxisAngle(new THREE.Vector3(0, 1, 0), rot).add(g.position);
  const approach = new THREE.Vector3(0, 0, -1.35).applyAxisAngle(new THREE.Vector3(0, 1, 0), rot).add(g.position);
  seats[name] = {pos: seatPos, approach, face: rot, desk: g, screen: scr, chair: ch, taken: null};
  return seats[name];
}
function rug(x, z, w, d, hex) { const r = mesh(new THREE.BoxGeometry(w, 0.02, d), new THREE.MeshStandardMaterial({map: carpetTex(hex), roughness: 1}), false, true); r.position.set(x, 0.01, z); scene.add(r); return r; }
function glassWall(x0, z0, x1, z1) {
  const len = Math.hypot(x1 - x0, z1 - z0), g = new THREE.Group();
  const pane = mesh(new THREE.BoxGeometry(len, 2.5, 0.04), M.glass, false, false); pane.position.y = 1.25; g.add(pane);
  g.add(boxM(len, 0.05, 0.08, M.frame, 0, 2.5, 0)); g.add(boxM(len, 0.05, 0.08, M.frame, 0, 0.03, 0));
  g.position.set((x0 + x1) / 2, 0, (z0 + z1) / 2); g.rotation.y = -Math.atan2(z1 - z0, x1 - x0); scene.add(g);
  block(x0 - 0.1, z0 - 0.1, x1 + 0.1, z1 + 0.1);
}

// ============================================================== departments
const departments = {};
function dept(key, name, x, z, color, info = "") { departments[key] = {key, name, pos: new THREE.Vector3(x, 0, z), anchor: new THREE.Vector3(x, 4.4, z), color, info, status: "good"}; }

// --- Trading floor (center north): 8 desks, two rows, dual monitors
dept("trading", "Trading Floor", 0, -7.5, 0xe8e6e0);
rug(0, -7.5, 15, 8, "#3b4250");
const tradeSeats = [];
for (let i = 0; i < 8; i++) { const r = Math.floor(i / 4), c = i % 4; tradeSeats.push(desk("trade" + i, -5.4 + c * 3.6, r ? -5.2 : -9.6, r ? 0 : Math.PI, {second: true})); }
// video wall on north wall
const wall = screen(13, 3.2, 1300, 320); wall.mesh.position.set(0, 2.15, -14.78); scene.add(wall.mesh);
scene.add(boxM(13.4, 3.5, 0.12, M.black, 0, 2.15, -14.86));

// --- Research lab (north-west), whiteboard
dept("research", "Research Lab", -15.5, -8.5, 0x3987e5);
rug(-15.5, -8.5, 9, 9, "#2e4462");
const labSeats = [desk("lab0", -17.8, -10.5, Math.PI), desk("lab1", -14.2, -10.5, Math.PI), desk("lab2", -17.8, -6.4, 0), desk("lab3", -14.2, -6.4, 0)];
const board = screen(5.5, 2.2, 660, 264); board.mesh.position.set(-21.75, 1.85, -8.5); board.mesh.rotation.y = Math.PI / 2; scene.add(board.mesh);
scene.add(boxM(0.08, 2.4, 5.8, M.frame, -21.8, 1.85, -8.5));
glassWall(-10.5, -14.6, -10.5, -10); glassWall(-10.5, -7, -10.5, -3.6); glassWall(-22, -3.6, -13.5, -3.6);

// --- Market radar (south-west): dish on a plinth + world map screen
dept("scanner", "Market Radar", -15.5, 7.5, 0x1baf7a);
rug(-15.5, 7.5, 9, 9, "#244a3c");
const scanSeats = [desk("scan0", -17, 9.6, 0), desk("scan1", -13.4, 9.6, 0)];
const dish = new THREE.Group();
dish.add(at(mesh(new THREE.CylinderGeometry(0.5, 0.7, 0.5, 20), M.metal), 0, 0.25, 0));
dish.add(at(mesh(new THREE.CylinderGeometry(0.08, 0.12, 1.6, 12), M.metal), 0, 1.1, 0));
const dishHead = new THREE.Group();
const bowl = mesh(new THREE.SphereGeometry(0.9, 28, 12, 0, Math.PI * 2, 0, Math.PI * 0.32), new THREE.MeshStandardMaterial({color: 0xe8ecf1, metalness: 0.5, roughness: 0.25, side: THREE.DoubleSide}));
bowl.rotation.x = Math.PI; dishHead.add(bowl);
dishHead.add(at(mesh(new THREE.CylinderGeometry(0.02, 0.02, 0.8, 6), M.metal), 0, -0.4, 0));
const beacon = mesh(new THREE.SphereGeometry(0.06, 10, 8), new THREE.MeshBasicMaterial({color: 0x1baf7a})); beacon.position.y = -0.8; dishHead.add(beacon);
dishHead.position.y = 2.0; dishHead.rotation.x = -0.9; dish.add(dishHead);
dish.position.set(-19.5, 0, 4.5); scene.add(dish); blockObj(dish.children[0], 0.2);
const mapScr = screen(4.6, 1.9, 552, 228); mapScr.mesh.position.set(-21.75, 1.8, 8.5); mapScr.mesh.rotation.y = Math.PI / 2; scene.add(mapScr.mesh);
scene.add(boxM(0.08, 2.1, 4.9, M.frame, -21.8, 1.8, 8.5));
glassWall(-22, 3.6, -13.5, 3.6); glassWall(-10.5, 3.6, -10.5, 7); glassWall(-10.5, 10, -10.5, 14.6);

// --- Validation & Risk (south center): glass room, gate lamp panel, meeting table
dept("risk", "Validation & Risk", 0, 9.5, 0xeda100);
rug(0, 9.5, 9, 7.5, "#5a4a2a");
const riskSeat = desk("risk", 2.4, 11.5, 0, {dark: true});
const table = new THREE.Group();
const tTop = rbox(2.6, 0.06, 1.2, 0.3, M.deskWood); tTop.position.y = 0.74; table.add(tTop);
table.add(boxM(0.12, 0.72, 0.12, M.metal, 0, 0.36, 0));
table.position.set(-1.8, 0, 8.6); scene.add(table); blockObj(tTop, 0.15);
const meetSpots = [new THREE.Vector3(-3.6, 0, 8.6), new THREE.Vector3(0, 0, 8.6), new THREE.Vector3(-1.8, 0, 7.4), new THREE.Vector3(-1.8, 0, 9.8)];
const lampBar = new THREE.Group(), lamps = [];
lampBar.add(boxM(6.8, 0.9, 0.12, M.black, 0, 0, 0));
for (let i = 0; i < 10; i++) { const l = mesh(new THREE.SphereGeometry(0.2, 18, 12), new THREE.MeshStandardMaterial({color: 0x333333, emissive: 0x000000})); l.position.set(-3.06 + i * 0.68, 0, 0.1); lampBar.add(l); lamps.push(l); }
lampBar.position.set(0, 2.5, 14.7); lampBar.rotation.y = Math.PI; scene.add(lampBar);
glassWall(-5, 5.2, -1.2, 5.2); glassWall(1.2, 5.2, 5, 5.2); glassWall(-5, 5.2, -5, 14.6); glassWall(5, 5.2, 5, 14.6);

// --- Learning library (south-east): shelves, books, sofa, reading desk
dept("learning", "Learning Library", 15.5, 9, 0x9085e9);
rug(15.5, 9, 9, 8, "#3c3560");
const shelves = new THREE.Group();
for (let s = 0; s < 3; s++) { const sh = new THREE.Group(); sh.add(boxM(2.6, 2.4, 0.4, M.deskWood, 0, 1.2, 0)); for (let k = 0; k < 4; k++) sh.add(boxM(2.5, 0.04, 0.38, M.deskTop, 0, 0.3 + k * 0.6, 0.02)); sh.position.set(13.2 + s * 2.8, 0, 13.9); shelves.add(sh); }
scene.add(shelves); shelves.children.forEach(s => blockObj(s.children[0], 0.1));
const books = new THREE.Group(); scene.add(books);
const learnSeat = desk("learn", 14.5, 7.4, Math.PI / 2, {dark: true});
const sofa = new THREE.Group(); sofa.add(rbox(2.2, 0.45, 0.9, 0.12, M.sofa)); sofa.children[0].position.y = 0.3;
const sb = rbox(2.2, 0.6, 0.25, 0.1, M.sofa); sb.position.set(0, 0.7, -0.35); sofa.add(sb);
sofa.position.set(19.3, 0, 8.2); sofa.rotation.y = -Math.PI / 2; scene.add(sofa); blockObj(sofa.children[0], 0.1);
glassWall(10.5, 5, 10.5, 7.2); glassWall(10.5, 10.4, 10.5, 14.6);

// --- Server room (north-east)
dept("ops", "Server Room", 15.5, -9, 0x8d8c84);
rug(15.5, -9, 9, 9, "#2a2c31");
const racks = [], leds = [];
for (let r = 0; r < 5; r++) {
  const rack = new THREE.Group(); rack.add(boxM(0.9, 2.3, 1.1, M.rack, 0, 1.15, 0));
  for (let k = 0; k < 10; k++) { const led = mesh(new THREE.BoxGeometry(0.05, 0.03, 0.01), new THREE.MeshBasicMaterial({color: 0x29d36a})); led.position.set(-0.3 + (k % 5) * 0.15, 0.4 + Math.floor(k / 5) * 1.2 + rand(0, .6), 0.556); rack.add(led); leds.push(led); }
  rack.position.set(12.2 + r * 1.3, 0, -13.2); scene.add(rack); racks.push(rack); blockObj(rack.children[0], 0.1);
}
const opsSeat = desk("ops", 16, -7.2, Math.PI, {second: true});
const sysScr = screen(3.6, 1.6, 432, 192); sysScr.mesh.position.set(21.75, 1.8, -8.5); sysScr.mesh.rotation.y = -Math.PI / 2; scene.add(sysScr.mesh);
glassWall(10.5, -14.6, 10.5, -11); glassWall(10.5, -8, 10.5, -3.6); glassWall(10.5, -3.6, 22, -3.6);

// --- Kitchen / coffee point (east, middle)
const kitchen = new THREE.Group();
kitchen.add(boxM(3.2, 0.9, 0.7, M.deskTop, 0, 0.45, 0));
const coffee = new THREE.Group(); coffee.add(boxM(0.45, 0.55, 0.4, M.black, 0, 1.18, 0)); coffee.add(boxM(0.3, 0.05, 0.2, M.metal, 0, 0.95, 0.12));
const coffeeLed = mesh(new THREE.SphereGeometry(0.025, 8, 6), new THREE.MeshBasicMaterial({color: 0xff6b3d})); coffeeLed.position.set(0.15, 1.35, 0.205); coffee.add(coffeeLed);
coffee.position.x = -0.9; kitchen.add(coffee);
kitchen.position.set(18.8, 0, 0); kitchen.rotation.y = -Math.PI / 2; scene.add(kitchen); blockObj(kitchen.children[0], 0.1);
const coffeeSpots = [new THREE.Vector3(17.4, 0, 0.9), new THREE.Vector3(16.6, 0, -0.4), new THREE.Vector3(17.6, 0, -1.4)];
// lifecycle manager (CEO) desk in the middle
dept("ceo", "Lifecycle Office", 6.5, 0.5, 0xd55181);
const ceoSeat = desk("ceo", 6.5, 0.8, -Math.PI / 2, {dark: true, second: true});
// plants
[[-21, -14], [-11.2, -4.3], [-11.2, 4.3], [-21, 14.2], [9.8, -4.3], [9.8, 4.3], [21, 14.2], [21, -2.6], [-5.6, 4.6], [5.6, 4.6], [-8.6, -13.8], [8.6, -13.8]].forEach(([x, z]) => plant(x, z, rand(0.9, 1.3)));

// --- Mission board (atrium): company goals measured from real data
const missionScr = screen(6.4, 2.25, 1024, 360);
{
  const mb = new THREE.Group();
  mb.add(boxM(6.7, 2.5, 0.14, M.black, 0, 0, -0.08));
  missionScr.mesh.position.z = 0.0; mb.add(missionScr.mesh);
  for (const x of [-3.2, 3.2]) { const post = boxM(0.12, 3.3, 0.12, M.metal, x, -1.95 + 0.35, -0.1); mb.add(post); }
  mb.position.set(0, 3.25, 1.6); mb.rotation.x = -0.1; scene.add(mb);
  block(-3.4, 1.4, -3.0, 1.8); block(3.0, 1.4, 3.4, 1.8);
}
dept("mission", "Company Mission", 0, 1.6, 0xffffff);
departments.mission.anchor.set(0, 4.9, 1.6);

// --- GitHub research lab: the off-site compute cloud (all hyperopt/backtests run there)
const cloud = new THREE.Group();
const cloudMat = new THREE.MeshStandardMaterial({color: 0xf4f7fb, roughness: 0.95, emissive: 0x9fb8d8, emissiveIntensity: 0.15, transparent: true, opacity: 0.94});
for (let i = 0; i < 16; i++) { const r = rand(0.9, 1.7); const puff = mesh(new THREE.SphereGeometry(r, 20, 14), cloudMat, false, false); puff.position.set(rand(-3.6, 3.6), rand(-0.2, 0.8) * (1 - Math.abs(i % 4 - 1.5) * 0.2), rand(-1.8, 1.8)); puff.scale.y = 0.72; cloud.add(puff); }
const coreMat = new THREE.MeshBasicMaterial({color: 0x3987e5, toneMapped: false, transparent: true, opacity: 0.9});
const cloudCore = new THREE.Mesh(new THREE.IcosahedronGeometry(0.6, 1), coreMat); cloudCore.position.y = -2.3; cloud.add(cloudCore);
const cloudRing = new THREE.Mesh(new THREE.TorusGeometry(1.2, 0.05, 8, 48), new THREE.MeshBasicMaterial({color: 0x7fb6ff, toneMapped: false})); cloudRing.position.y = -2.3; cloudRing.rotation.x = Math.PI / 2; cloud.add(cloudRing);
const cloudRing2 = cloudRing.clone(); cloudRing2.scale.setScalar(0.7); cloud.add(cloudRing2);
const CLOUD_Y = 21; cloud.position.set(-20, CLOUD_Y, -26); scene.add(cloud);
dept("cloud", "GitHub Research Lab", -20, -26, 0x3987e5);
departments.cloud.anchor.set(-20, CLOUD_Y + 2.4, -26);
const beamFrom = new THREE.Vector3(-20, CLOUD_Y - 2.9, -26), beamTo = new THREE.Vector3(-15.5, 3.2, -8.5);
const beamCurve = new THREE.QuadraticBezierCurve3(beamFrom, new THREE.Vector3(-19, 13, -15), beamTo);
const beam = new THREE.Mesh(new THREE.TubeGeometry(beamCurve, 60, 0.03, 6, false), new THREE.MeshBasicMaterial({color: 0x7fb6ff, transparent: true, opacity: 0.0, toneMapped: false}));
scene.add(beam);
const NB = 26, beamParts = new THREE.InstancedMesh(new THREE.SphereGeometry(0.09, 8, 6), new THREE.MeshBasicMaterial({color: 0xbfe0ff, toneMapped: false}), NB);
const beamT = Array.from({length: NB}, (_, i) => i / NB); scene.add(beamParts);
let labActive = false;
const packets = [];
function flyPacket(from, to, color = 0x7fb6ff, ms = 3200) {
  const m = new THREE.Mesh(new THREE.BoxGeometry(0.35, 0.35, 0.35), new THREE.MeshBasicMaterial({color, toneMapped: false}));
  const mid = from.clone().lerp(to, 0.5); mid.y = Math.max(from.y, to.y) + 4;
  packets.push({m, curve: new THREE.QuadraticBezierCurve3(from.clone(), mid, to.clone()), s: performance.now(), ms}); scene.add(m);
}

// ============================================================== pipeline particles
const pipeline = new THREE.CatmullRomCurve3([
  new THREE.Vector3(-19.5, 2.6, 4.5), new THREE.Vector3(-15, 3.2, 0), new THREE.Vector3(-15.5, 3.0, -6),
  new THREE.Vector3(-6, 3.4, 2), new THREE.Vector3(0, 3.0, 8.5), new THREE.Vector3(4, 3.4, 2), new THREE.Vector3(0, 3.0, -7)]);
const NP = 90, partGeo = new THREE.SphereGeometry(0.07, 8, 6);
const parts = new THREE.InstancedMesh(partGeo, new THREE.MeshBasicMaterial({color: 0x7fb6ff, transparent: true, opacity: 0.85, toneMapped: false}), NP);
const partT = Array.from({length: NP}, (_, i) => i / NP); scene.add(parts);
const pipeLine = new THREE.Mesh(new THREE.TubeGeometry(pipeline, 200, 0.015, 6, false), new THREE.MeshBasicMaterial({color: 0x3987e5, transparent: true, opacity: 0.25}));
scene.add(pipeLine);
let flowSpeed = 0.02;

// ============================================================== characters
const SKIN = [0xf3cfa9, 0xe5b88f, 0xc68e5e, 0x8d5a3a, 0xf6d9c2, 0xb07a4f];
const HAIR = [0x2b2018, 0x5a3b22, 0x0f0f10, 0xa4774c, 0xd9b26a, 0x8a8a8a, 0x6e2b1d];
const OUTFIT = {trader: [0xe8e6e0, 0xcfd6e2], research: [0xf6f6f2], risk: [0x2f3a52], scanner: [0x1baf7a], learn: [0x7a6fd6], ops: [0x3b3f47], ceo: [0x1f2433]};
const PANTS = [0x2a2f3a, 0x3b3b40, 0x24364f, 0x403527];
const chars = [];
const UP = new THREE.Vector3(0, 1, 0);

// ---- mocap character (skinned, motion-captured idle/walk + procedural office poses).
// Loaded at runtime from the three.js repository; falls back to the procedural rig.
const XBOT_URL = "https://raw.githubusercontent.com/mrdoob/three.js/r170/examples/models/gltf/Xbot.glb";
let XBOT = null;
try {
  const lm = document.getElementById("lmsg"); if (lm) lm.textContent = "loading motion-captured staff…";
  XBOT = await Promise.race([new GLTFLoader().loadAsync(XBOT_URL), new Promise((_, rej) => setTimeout(() => rej(new Error("timeout")), 12000))]);
  for (const name of ["agree", "headShake", "sad_pose"]) {
    const c = XBOT.animations.find(a => a.name === name); if (c) THREE.AnimationUtils.makeClipAdditive(c);
  }
} catch (e) { console.warn("mocap staff unavailable, using procedural rig:", e.message); XBOT = null; }
// Clothing shader: the mannequin's single surface is painted as skin, hair, shirt/jacket,
// trousers, belt, shoes (and lab coat / tie) by bind-pose height, so staff read as people.
function outfitMaterial(geo, o) {
  geo.computeBoundingBox();
  const bb = geo.boundingBox, H = bb.max.y - bb.min.y;
  const mat = new THREE.MeshStandardMaterial({color: 0xffffff, roughness: 0.62, metalness: 0.0});
  const U = {uMinY: {value: bb.min.y}, uH: {value: H}, uMidX: {value: (bb.min.x + bb.max.x) / 2}, uFrontZ: {value: (bb.min.z + bb.max.z) / 2},
    uSkin: {value: new THREE.Color(o.skin)}, uHair: {value: new THREE.Color(o.hair)}, uShirt: {value: new THREE.Color(o.shirt)},
    uPants: {value: new THREE.Color(o.pants)}, uShoes: {value: new THREE.Color(0x15151a)}, uTie: {value: new THREE.Color(o.tie ?? o.shirt)},
    uCoat: {value: o.coat ? 1 : 0}, uLongHair: {value: o.longHair ? 1 : 0}, uBald: {value: o.bald ? 1 : 0}};
  mat.onBeforeCompile = sh => {
    Object.assign(sh.uniforms, U);
    sh.vertexShader = "varying vec3 vBind;\n" + sh.vertexShader.replace("#include <begin_vertex>", "#include <begin_vertex>\nvBind = position;");
    sh.fragmentShader = `varying vec3 vBind;
uniform float uMinY, uH, uMidX, uFrontZ, uCoat, uLongHair, uBald;
uniform vec3 uSkin, uHair, uShirt, uPants, uShoes, uTie;
` + sh.fragmentShader.replace("vec4 diffuseColor = vec4( diffuse, opacity );", `
float y = (vBind.y - uMinY) / uH; float ax = abs(vBind.x - uMidX) / uH; float fz = (vBind.z - uFrontZ) / uH;
vec3 col = uShirt;
float pantsTop = uCoat > 0.5 ? 0.33 : 0.535;
col = mix(col, uPants, 1.0 - smoothstep(pantsTop - 0.006, pantsTop + 0.006, y));
col = mix(col, uShoes, 1.0 - smoothstep(0.045, 0.055, y));
float belt = (1.0 - uCoat) * smoothstep(0.528, 0.532, y) * (1.0 - smoothstep(0.546, 0.55, y));
col = mix(col, vec3(0.09), belt);
float tie = step(ax, 0.011) * step(0.6, y) * step(y, 0.81) * step(0.0, fz);
col = mix(col, uTie, tie);
float skin = max(smoothstep(0.826, 0.836, y), smoothstep(0.36, 0.37, ax) * step(0.62, y));
col = mix(col, uSkin, skin);
float hair = (1.0 - uBald) * smoothstep(0.94, 0.95, y) + (1.0 - uBald) * smoothstep(0.895, 0.905, y) * (1.0 - smoothstep(0.0, 0.02, fz + 0.01))
           + uLongHair * smoothstep(0.80, 0.82, y) * step(ax, 0.06) * (1.0 - smoothstep(-0.01, 0.01, fz + 0.025));
col = mix(col, uHair, clamp(hair, 0.0, 1.0) * step(0.8, y));
vec4 diffuseColor = vec4( col, opacity );`);
  };
  mat.customProgramCacheKey = () => "outfit";
  return mat;
}
const ROLE_SUIT = {trader: [0x2f4a6d, 0x3b5d86, 0x24364f], research: [0xf4f4f0], risk: [0x2b2f3a], scanner: [0x1f8a63], learn: [0x6a5fc4], ops: [0x3b3f47], ceo: [0x5a1f3a]};
const _q1 = new THREE.Quaternion(), _q2 = new THREE.Quaternion(), _v1 = new THREE.Vector3(), _v2 = new THREE.Vector3();
function rotWorld(bone, axis, angle) {
  // rotate a bone about a WORLD axis, independent of the rig's local bone axes
  if (!bone || !angle) return;
  bone.parent.getWorldQuaternion(_q1);
  _q2.setFromAxisAngle(axis, angle);
  const d = _q1.clone().invert().multiply(_q2).multiply(_q1);
  bone.quaternion.premultiply(d);
  bone.updateMatrixWorld(true);
}

class Person {
  constructor(name, role, home, opts = {}) {
    this.name = name; this.role = role; this.homeSeat = home; this.state = "idle"; this.queue = [];
    this.speed = rand(1.15, 1.45); this.phase = rand(0, 10); this.talkT = 0; this.mood = 0; this.speaking = false;
    this.blinkT = rand(1, 4); this.lookTarget = null; this.carryObj = null; this.sitBlend = 0; this.line = "";
    const skin = new THREE.MeshStandardMaterial({color: pick(SKIN), roughness: 0.6});
    const top = new THREE.MeshStandardMaterial({color: pick(OUTFIT[role] || [0xdddddd]), roughness: 0.75});
    const pants = new THREE.MeshStandardMaterial({color: pick(PANTS), roughness: 0.8});
    const hairM = new THREE.MeshStandardMaterial({color: pick(HAIR), roughness: 0.7});
    const shoeM = new THREE.MeshStandardMaterial({color: 0x1a1a1c, roughness: 0.5});
    const R = new THREE.Group(); this.root = R;
    // shadow blob
    const blob = new THREE.Mesh(new THREE.CircleGeometry(0.32, 20), new THREE.MeshBasicMaterial({color: 0x000000, transparent: true, opacity: 0.22, depthWrite: false}));
    blob.rotation.x = -Math.PI / 2; blob.position.y = 0.015; R.add(blob); this.blob = blob;
    const hips = new THREE.Group(); hips.position.y = 0.92; R.add(hips); this.hips = hips;
    { const pelvis = mesh(new THREE.CapsuleGeometry(0.13, 0.12, 4, 10), pants); pelvis.scale.set(1.25, 1, 0.8); hips.add(pelvis); }
    const torso = new THREE.Group(); torso.position.y = 0.08; hips.add(torso); this.torso = torso;
    const chest = mesh(new THREE.CapsuleGeometry(0.17, 0.3, 4, 12), top); chest.scale.set(1.15, 1, 0.72); chest.position.y = 0.27; torso.add(chest);
    const collar = mesh(new THREE.TorusGeometry(0.068, 0.02, 6, 18), new THREE.MeshStandardMaterial({color: new THREE.Color(top.color).multiplyScalar(0.82), roughness: 0.7}));
    collar.rotation.x = Math.PI / 2; collar.position.y = 0.515; collar.scale.set(1, 0.8, 1); torso.add(collar);
    const belt = mesh(new THREE.CylinderGeometry(0.168, 0.168, 0.045, 18), new THREE.MeshStandardMaterial({color: 0x2a2320, roughness: 0.5})); belt.scale.z = 0.78; belt.position.y = 0.075; hips.add(belt);
    const buckle = boxM(0.04, 0.03, 0.01, M.metal, 0, 0.075, 0.132); hips.add(buckle);
    if (role === "research") { const coat = mesh(new THREE.CylinderGeometry(0.21, 0.25, 0.62, 14, 1, true), new THREE.MeshStandardMaterial({color: 0xfdfdfb, roughness: 0.8, side: THREE.DoubleSide})); coat.position.y = 0.12; coat.scale.z = 0.75; torso.add(coat); }
    if (role === "ceo" || role === "risk") { const tie = boxM(0.045, 0.24, 0.02, new THREE.MeshStandardMaterial({color: role === "ceo" ? 0xd55181 : 0xeda100}), 0, 0.33, 0.125); torso.add(tie); }
    if (opts.badge) { const b = boxM(0.06, 0.08, 0.01, new THREE.MeshStandardMaterial({color: 0x3987e5, emissive: 0x3987e5, emissiveIntensity: .4}), 0.09, 0.36, 0.126); torso.add(b); }
    const neck = mesh(new THREE.CylinderGeometry(0.05, 0.055, 0.09, 10), skin); neck.position.y = 0.55; torso.add(neck);
    const head = new THREE.Group(); head.position.y = 0.6; torso.add(head); this.head = head;
    const skull = mesh(new THREE.SphereGeometry(0.115, 20, 16), skin); skull.scale.set(0.95, 1.1, 1.0); skull.position.y = 0.11; head.add(skull);
    const nose = mesh(new THREE.SphereGeometry(0.02, 8, 6), skin); nose.position.set(0, 0.1, 0.11); head.add(nose);
    const white = new THREE.MeshStandardMaterial({color: 0xf7f5f0, roughness: 0.35});
    const eyeM = new THREE.MeshStandardMaterial({color: 0x1b1a1f, roughness: 0.2});
    this.eyes = [-0.042, 0.042].map(x => { const g = new THREE.Group(); g.position.set(x, 0.135, 0.097);
      const w = mesh(new THREE.SphereGeometry(0.019, 12, 8), white, false); w.scale.set(1, 0.85, 0.55); g.add(w);
      const pu = mesh(new THREE.SphereGeometry(0.0105, 10, 8), eyeM, false); pu.position.z = 0.0085; g.add(pu); g.userData.pupil = pu; head.add(g); return g; });
    this.brows = [-0.043, 0.043].map((x, i) => { const b = boxM(0.042, 0.009, 0.012, hairM, x, 0.172, 0.104); b.castShadow = false; b.userData.side = i ? -1 : 1; head.add(b); return b; });
    this.mouth = new THREE.Group(); this.mouth.position.set(0, 0.06, 0.104); head.add(this.mouth);
    this.smile = mesh(new THREE.TorusGeometry(0.021, 0.0048, 6, 14, Math.PI), new THREE.MeshStandardMaterial({color: 0x8a3f37, roughness: 0.6}), false);
    this.smile.rotation.z = Math.PI; this.mouth.add(this.smile);
    this.mouthOpen = mesh(new THREE.SphereGeometry(0.016, 10, 8), new THREE.MeshStandardMaterial({color: 0x3a1512}), false);
    this.mouthOpen.scale.set(1.15, 0.15, 0.4); this.mouthOpen.position.y = 0.002; this.mouth.add(this.mouthOpen);
    [-1, 1].forEach(sd => { const e = mesh(new THREE.SphereGeometry(0.027, 10, 8), skin); e.scale.set(0.45, 1, 0.8); e.position.set(sd * 0.111, 0.118, -0.005); head.add(e); });
    const style = opts.hair ?? Math.floor(Math.random() * 4);
    const cap = mesh(new THREE.SphereGeometry(0.122, 20, 12, 0, Math.PI * 2, 0, Math.PI * 0.55), hairM); cap.position.y = 0.125; cap.scale.set(1, 1.1, 1.05); head.add(cap);
    if (style === 1) { const pony = mesh(new THREE.CapsuleGeometry(0.04, 0.14, 4, 8), hairM); pony.position.set(0, 0.08, -0.12); pony.rotation.x = 0.4; head.add(pony); }
    if (style === 2) { const bun = mesh(new THREE.SphereGeometry(0.06, 12, 10), hairM); bun.position.set(0, 0.23, -0.06); head.add(bun); }
    if (style === 3) { const long = mesh(new THREE.CylinderGeometry(0.12, 0.13, 0.22, 16, 1, true, Math.PI * 0.6, Math.PI * 0.8), hairM); long.position.set(0, 0.04, 0); long.rotation.y = Math.PI; head.add(long); }
    if (role === "trader") { const hs = mesh(new THREE.TorusGeometry(0.125, 0.012, 6, 20, Math.PI), M.black); hs.position.y = 0.13; hs.rotation.z = 0; head.add(hs);
      const mic = boxM(0.012, 0.012, 0.1, M.black, 0.1, 0.06, 0.06); mic.rotation.y = 0.5; head.add(mic); }
    if (role === "research" && Math.random() > .4) { const gl = mesh(new THREE.TorusGeometry(0.03, 0.006, 6, 14), M.black); [-0.04, 0.04].forEach(x => { const g2 = gl.clone(); g2.position.set(x, 0.13, 0.108); head.add(g2); }); }
    const arm = (side) => {
      const sh = new THREE.Group(); sh.position.set(side * 0.215, 0.43, 0); torso.add(sh);
      const cap = mesh(new THREE.SphereGeometry(0.062, 12, 10), top); cap.scale.set(1, 0.9, 0.9); sh.add(cap);
      const upper = mesh(new THREE.CapsuleGeometry(0.048, 0.2, 4, 8), top); upper.position.y = -0.13; sh.add(upper);
      const el = new THREE.Group(); el.position.y = -0.27; sh.add(el);
      const fore = mesh(new THREE.CapsuleGeometry(0.042, 0.19, 4, 8), role === "research" ? top : skin); fore.position.y = -0.12; el.add(fore);
      const hand = mesh(new THREE.SphereGeometry(0.047, 10, 8), skin); hand.position.y = -0.26; hand.scale.set(0.9, 1.15, 0.7); el.add(hand);
      sh.rotation.z = side * 0.08; return {sh, el, hand};
    };
    this.armL = arm(1); this.armR = arm(-1);
    // hand props (right hand): coffee cup, phone, tablet
    const cupM = new THREE.MeshStandardMaterial({color: pick([0xffffff, 0xe66767, 0x3987e5, 0xfab219]), roughness: 0.4});
    const cup = mesh(new THREE.CylinderGeometry(0.036, 0.03, 0.085, 14), cupM); cup.position.set(0, -0.3, 0.045);
    const phone = rbox(0.055, 0.11, 0.012, 0.008, M.black); phone.position.set(0, -0.3, 0.035); phone.rotation.x = 0.2;
    const tablet = new THREE.Group(); tablet.add(rbox(0.22, 0.3, 0.014, 0.015, M.black));
    const tScr = mesh(new THREE.PlaneGeometry(0.19, 0.26), new THREE.MeshBasicMaterial({color: 0x3987e5, toneMapped: false}), false, false); tScr.position.z = 0.008; tablet.add(tScr);
    tablet.position.set(0.02, -0.34, 0.08); tablet.rotation.set(-1.2, 0, 0);
    this.props = {cup, phone, tablet}; for (const o of Object.values(this.props)) { o.visible = false; this.armR.el.add(o); }
    const leg = (side) => {
      const hp = new THREE.Group(); hp.position.set(side * 0.09, 0, 0); hips.add(hp);
      const thigh = mesh(new THREE.CapsuleGeometry(0.068, 0.32, 4, 8), pants); thigh.position.y = -0.21; hp.add(thigh);
      const kn = new THREE.Group(); kn.position.y = -0.43; hp.add(kn);
      const shin = mesh(new THREE.CapsuleGeometry(0.058, 0.32, 4, 8), pants); shin.position.y = -0.2; kn.add(shin);
      const an = new THREE.Group(); an.position.y = -0.42; kn.add(an);
      const shoe = rbox(0.11, 0.07, 0.25, 0.03, shoeM); shoe.position.set(0, -0.02, 0.045); an.add(shoe);
      return {hp, kn, an};
    };
    this.legL = leg(1); this.legR = leg(-1);
    if (XBOT) this.attachModel(role, opts);
    this.pos = (home?.approach || home?.pos || new THREE.Vector3()).clone();
    R.position.copy(this.pos); this.yaw = 0; scene.add(R);
    R.traverse(o => { o.userData.person = this; });
    // DOM: bubble + nametag
    this.bubble = document.createElement("div"); this.bubble.className = "bubble"; $("#labels").appendChild(this.bubble);
    this.tagEl = document.createElement("div"); this.tagEl.className = "nametag"; this.tagEl.textContent = `${name} · ${roleName(role)}`; $("#labels").appendChild(this.tagEl);
    this.bubbleUntil = 0; chars.push(this);
  }
  attachModel(role, opts) {
    this.root.remove(this.hips);
    const m = SkeletonUtils.clone(XBOT.scene);
    const look = {skin: pick(SKIN), hair: pick(HAIR), shirt: pick(ROLE_SUIT[role] || [0x888888]), pants: pick(PANTS),
      tie: role === "ceo" ? 0xd55181 : role === "risk" ? 0xeda100 : null, coat: role === "research",
      longHair: (opts.hair ?? 0) % 4 === 3 || (opts.hair ?? 0) % 4 === 1, bald: (opts.hair ?? 0) === 0 && Math.random() < 0.25};
    if (role === "research") look.shirt = 0xf6f6f2;
    let bodyGeo = null;
    m.traverse(o => { if (o.isMesh && !/joint/i.test(o.material?.name || o.name)) bodyGeo = o.geometry; });
    m.traverse(o => {
      if (o.isMesh) {
        o.castShadow = true; o.receiveShadow = true; o.frustumCulled = false;
        o.material = outfitMaterial(bodyGeo || o.geometry, look);
      }
    });
    this.root.add(m); this.model = m;
    this.bones = {}; m.traverse(o => { if (o.isBone) this.bones[o.name.replace(/^mixamorig:?/, "")] = o; });
    this.mixer = new THREE.AnimationMixer(m);
    const clip = n => XBOT.animations.find(a => a.name === n);
    this.act = {};
    for (const n of ["idle", "walk"]) { const a = this.mixer.clipAction(clip(n)); a.play(); a.setEffectiveWeight(n === "idle" ? 1 : 0); this.act[n] = a; }
    for (const n of ["agree", "headShake", "sad_pose"]) { const c = clip(n); if (!c) continue; const a = this.mixer.clipAction(c); a.blendMode = THREE.AdditiveAnimationBlending; a.play(); a.setEffectiveWeight(0); this.act[n] = a; }
    this.act.idle.time = rand(0, 3); this.act.walk.time = rand(0, 1);
    this.w = {walk: 0, agree: 0, headShake: 0, sad_pose: 0};
    m.updateMatrixWorld(true);
    this.hipH = this.bones.Hips ? this.bones.Hips.getWorldPosition(new THREE.Vector3()).y - this.root.position.y : 1.0;
    this.pose3 = {};
    // accessories on bones
    const head = this.bones.Head, hand = this.bones.RightHand;
    const attach = (bone, obj, x, y, z) => { // place in metres regardless of the bone's unit scale
      const k = 1 / (bone.getWorldScale(new THREE.Vector3()).x || 1); bone.add(obj); obj.scale.setScalar(k); obj.position.set(x * k, y * k, z * k); };
    if (head && role === "trader") attach(head, mesh(new THREE.TorusGeometry(0.1, 0.011, 8, 24, Math.PI), M.black), 0, 0.1, 0);
    if (head && (role === "research" || opts.glasses)) { const gl = new THREE.Group(); [-1, 1].forEach(sd => { const r = mesh(new THREE.TorusGeometry(0.025, 0.004, 6, 16), M.black, false); r.position.set(sd * 0.033, 0, 0); gl.add(r); }); gl.add(boxM(0.02, 0.004, 0.004, M.black)); attach(head, gl, 0, 0.09, 0.095); }
    if (hand) for (const o of Object.values(this.props)) { this.armR.el.remove(o); o.rotation.set(0, 0, 0); attach(hand, o, 0, 0.09, 0.03); }
    this.restQ = {}; for (const [k, bn] of Object.entries(this.bones)) this.restQ[k] = bn.quaternion.clone();
  }
  animateModel(dt, t, walking) {
    const R = this.root, seated = !!this.seat && !walking, b = this.bones;
    if (!seated) this.sitBlend = damp(this.sitBlend, 0, 6, dt); else this.sitBlend = damp(this.sitBlend, 1, 6, dt);
    R.position.set(this.pos.x, 0, this.pos.z); R.rotation.y = this.yaw;
    const pose = walking ? "walk" : this.pose, sb = this.sitBlend;
    // clip weights: walk vs idle; additive nod / head-shake / slump layered on top
    this.w.walk = damp(this.w.walk, walking ? 1 : 0, 8, dt);
    this.act.walk.setEffectiveWeight(this.w.walk); this.act.idle.setEffectiveWeight(1 - this.w.walk);
    this.act.walk.timeScale = this.speed / 1.25;
    const listening = pose === "talk" && !this.speaking;
    const tgt = {agree: listening && Math.sin(t * 0.7 + this.phase) > 0.2 ? 1 : 0, headShake: pose === "facepalm" ? 1 : 0, sad_pose: this.mood < -0.4 && !walking ? 0.7 : 0};
    for (const k of ["agree", "headShake", "sad_pose"]) if (this.act[k]) { this.w[k] = damp(this.w[k], tgt[k], 4, dt); this.act[k].setEffectiveWeight(this.w[k]); }
    for (const k of ["LeftUpLeg", "RightUpLeg", "LeftLeg", "RightLeg", "Spine1", "RightArm", "RightForeArm", "LeftArm", "LeftForeArm", "Neck", "Head"])
      if (b[k]) b[k].quaternion.copy(this.restQ[k]); // clips overwrite; reset guards against drift
    this.mixer.update(dt);
    this.model.position.y = -sb * (this.hipH - 0.56); this.model.position.z = -0.12 * sb;
    this.model.updateMatrixWorld(true);
    // procedural layer (world-axis rotations, rig independent)
    const f = _v1.set(Math.sin(this.yaw), 0, Math.cos(this.yaw)), right = _v2.set(-Math.cos(this.yaw), 0, Math.sin(this.yaw)).clone();
    const P = this.pose3, ks = 1 - Math.exp(-10 * dt);
    const want = {thigh: 1.5 * sb, knee: -1.55 * sb, uarm: 0, farm: 0, uarmL: 0, farmL: 0, inR: 0, inL: 0, spine: 0, headY: 0, headX: 0, raise: 0};
    if (seated) { want.uarm = want.uarmL = 0.55; want.farm = want.farmL = 0.85; want.inR = 0.35; want.inL = -0.35; want.spine = 0.08;
      if (this.role !== "ceo" || Math.sin(t * 0.3) > 0) { const fast = this.typingFast ? 1.8 : 1; want.farm += Math.sin(t * 16 * fast + this.phase) * 0.06; want.farmL += Math.sin(t * 14 * fast + this.phase * 2) * 0.06; }
      if (Math.sin(t * 0.13 + this.phase) > 0.97) { want.uarm = want.uarmL = 2.6; want.farm = want.farmL = 0.2; } }
    if (pose === "talk" && this.speaking) { const g = Math.sin(t * 3.1 + this.phase), g2 = Math.sin(t * 2.2 + this.phase * 1.7); want.uarm = 0.45 + Math.max(0, g) * 0.5; want.farm = 1.0 + g * 0.35; want.inR = 0.25; want.uarmL = 0.2 + Math.max(0, g2) * 0.4; want.farmL = 0.8 + Math.max(0, g2) * 0.4; want.inL = -0.2; }
    if (pose === "coffee") { want.uarm = 0.55; want.farm = 1.9 + Math.max(0, Math.sin(t * 0.8 + this.phase)) * 0.35; want.inR = 0.3; }
    if (pose === "phone") { want.uarm = 0.35; want.farm = 2.35; want.inR = 0.8; want.headY = 0.15; }
    if (pose === "cheer") { want.uarm = want.uarmL = 2.9 + Math.sin(t * 9) * 0.1; want.farm = want.farmL = 0.15; }
    if (pose === "clap") { const c = Math.sin(t * 16) * 0.15; want.uarm = want.uarmL = 0.75; want.farm = want.farmL = 1.25; want.inR = 0.75 + c; want.inL = -0.75 - c; }
    if (pose === "highfive") { want.uarm = 2.6; want.farm = 0.1; }
    if (pose === "facepalm") { want.uarm = 0.9; want.farm = 2.3; want.inR = 0.9; want.headX = 0.25; }
    if (pose === "think") { want.uarm = 0.6; want.farm = 2.2; want.inR = 0.7; want.uarmL = 0.4; want.farmL = 1.4; want.inL = -0.9; }
    if (pose === "point") { want.uarm = 1.45; want.farm = 0.05; want.inR = 0.15; }
    if (pose === "present") { want.uarm = 1.2 + Math.sin(t * 1.3) * 0.12; want.farm = 0.25; want.inR = -0.3; want.uarmL = 0.4; want.farmL = 0.9; }
    if (pose === "write") { const w = t * 5 + this.phase; want.uarm = 1.75 + Math.sin(w) * 0.12; want.farm = 0.6 + Math.cos(w * 1.3) * 0.15; want.inR = 0.2 + Math.sin(w * 0.7) * 0.1; }
    if (this.carryObj || this.carryTablet) { want.uarm = want.uarmL = 0.6; want.farm = want.farmL = 1.0; want.inR = 0.4; want.inL = -0.4; }
    if (this.lookTarget) { const lt = this.lookTarget.pos || this.lookTarget; want.headY = clamp(angDiff(this.yaw, Math.atan2(lt.x - this.pos.x, lt.z - this.pos.z)), -1.0, 1.0); }
    else if (seated && Math.sin(t * 0.37 + this.phase * 2) > 0.93) want.headY = 0.6;
    else if (!walking && !seated && pose === "stand") want.headY = Math.sin(t * 0.5 + this.phase) * 0.4;
    if (seated) want.headX += 0.12;
    for (const k in want) P[k] = (P[k] ?? 0) + (want[k] - (P[k] ?? 0)) * ks;
    // legs (sitting): thighs forward, shins down
    rotWorld(b.LeftUpLeg, right, P.thigh); rotWorld(b.RightUpLeg, right, P.thigh);
    rotWorld(b.LeftLeg, right, P.knee); rotWorld(b.RightLeg, right, P.knee);
    rotWorld(b.Spine1, right, -P.spine); // a negative angle about the right axis leans the torso forward
    // arms: forward about the right axis, then inward about the vertical
    rotWorld(b.RightArm, right, P.uarm); rotWorld(b.RightArm, UP, P.inR);
    rotWorld(b.RightForeArm, right, P.farm);
    rotWorld(b.LeftArm, right, P.uarmL); rotWorld(b.LeftArm, UP, P.inL);
    rotWorld(b.LeftForeArm, right, P.farmL);
    rotWorld(b.Neck, UP, P.headY * 0.5); rotWorld(b.Head, UP, P.headY * 0.5); rotWorld(b.Head, right, -P.headX);
    if (this.speaking) rotWorld(b.Head, f, Math.sin(t * 2.6 + this.phase) * 0.05);
    this.props.cup.visible = pose === "coffee"; this.props.phone.visible = pose === "phone"; this.props.tablet.visible = !!this.carryTablet;
    if (this.carryObj) this.carryObj.position.set(0, 1.08, 0.32);
  }
  // ---- task queue
  do(task) { this.queue.push(task); return this; }
  clear() { this.queue = []; this.task = null; return this; }
  busy() { return !!this.task || this.queue.length > 0 || this.locked; }
  say(text, ms = 5000) {
    this.line = text; clearTimeout(this._sayT);
    this.bubble.innerHTML = `<span class="who">${esc(this.name)}</span><span class="dots"><i></i><i></i><i></i></span>`;
    this.bubble.classList.add("on"); this.speaking = false; this.bubbleUntil = performance.now() + ms + 600;
    this._sayT = setTimeout(() => { this.bubble.innerHTML = `<span class="who">${esc(this.name)}</span>${esc(text)}`; this.speaking = true; }, 600);
  }
  emote(sym, ms = 2800) {
    if (!this.emoteEl) { this.emoteEl = document.createElement("div"); this.emoteEl.className = "emote"; $("#labels").appendChild(this.emoteEl); }
    this.emoteEl.textContent = sym; this.emoteEl.classList.remove("on"); void this.emoteEl.offsetWidth; this.emoteEl.classList.add("on");
    this.emoteUntil = performance.now() + ms;
  }
  feel(m) { this.mood = clamp(m, -1, 1); }
  goTo(p) { return this.do({type: "walk", to: p.clone()}); }
  sitAt(seat) { return this.do({type: "walk", to: seat.approach}).do({type: "sit", seat}); }
  wait(ms, pose = "stand") { return this.do({type: "wait", ms, pose}); }
  face(target) { return this.do({type: "face", target}); }
  // ---- update
  update(dt, t) {
    if (!this.task && this.queue.length) this.startTask(this.queue.shift());
    const k = this.task;
    let walking = false;
    if (k) {
      if (k.type === "walk") {
        if (!k.path) { this.standUp(); k.path = findPath(this.pos, k.to); }
        const tgt = k.path[0];
        if (!tgt) { this.task = null; }
        else {
          const d = new THREE.Vector3(tgt.x - this.pos.x, 0, tgt.z - this.pos.z), dist = d.length();
          if (dist < 0.06) { k.path.shift(); if (!k.path.length) this.task = null; }
          else { d.normalize(); this.pos.addScaledVector(d, Math.min(dist, this.speed * dt)); this.turnTo(Math.atan2(d.x, d.z), dt, 10); walking = true; }
        }
      } else if (k.type === "sit") {
        const s = k.seat; if (s.taken && s.taken !== this) { this.task = null; }
        else { s.taken = this; this.seat = s; this.pos.lerp(s.pos, 1 - Math.exp(-8 * dt)); this.turnTo(s.face, dt, 8); this.sitBlend = damp(this.sitBlend, 1, 6, dt);
          if (this.sitBlend > 0.97 && this.pos.distanceTo(s.pos) < 0.03) this.task = null; }
      } else if (k.type === "wait") {
        k.left -= dt * 1000; if (k.left <= 0) this.task = null;
      } else if (k.type === "face") {
        const tp = k.target.pos ? k.target.pos : k.target; const a = Math.atan2(tp.x - this.pos.x, tp.z - this.pos.z);
        this.turnTo(a, dt, 8); if (Math.abs(angDiff(this.yaw, a)) < 0.05) this.task = null;
      } else if (k.type === "call") { k.fn(this); this.task = null; }
    }
    this.animate(dt, t, walking);
  }
  startTask(k) { this.task = k; if (k.type === "wait") k.left = k.ms; this.pose = k.type === "wait" ? k.pose : this.pose; }
  standUp() { if (this.seat) { this.seat.taken = null; this.seat = null; } }
  turnTo(a, dt, rate) { this.yaw += angDiff(this.yaw, a) * (1 - Math.exp(-rate * dt)); }
  animate(dt, t, walking) {
    if (this.model) return this.animateModel(dt, t, walking);
    const R = this.root, seated = !!this.seat && !walking;
    if (!seated) this.sitBlend = damp(this.sitBlend, 0, 6, dt);
    const sb = this.sitBlend, pose = walking ? "walk" : this.pose;
    R.position.set(this.pos.x, 0, this.pos.z);
    const prevYaw = R.rotation.y; R.rotation.y = this.yaw;
    const turnRate = Math.abs(angDiff(prevYaw, this.yaw)) / Math.max(dt, 1e-3);
    const stepping = !walking && !seated && turnRate > 1.2;
    this.phase += dt * (walking ? this.speed * 5.6 : stepping ? 7 : 1);
    const p = this.phase, sw = walking ? Math.sin(p) : stepping ? Math.sin(p) * 0.35 : 0, sw2 = walking ? Math.sin(p * 2) : 0;
    // legs: hip swing, knee lift on the swing phase, heel-toe roll at the ankle
    const hipSit = -1.45 * sb, kneeSit = 1.5 * sb, stand = 1 - sb;
    const idleShift = !walking && !seated ? Math.sin(t * 0.45 + this.phase) : 0;
    this.legL.hp.rotation.x = hipSit + sw * 0.55 * stand; this.legR.hp.rotation.x = hipSit - sw * 0.55 * stand;
    this.legL.kn.rotation.x = kneeSit + (walking || stepping ? Math.max(0, -Math.sin(p - 0.6)) * 0.95 : Math.max(0, idleShift) * 0.12);
    this.legR.kn.rotation.x = kneeSit + (walking || stepping ? Math.max(0, Math.sin(p - 0.6)) * 0.95 : Math.max(0, -idleShift) * 0.12);
    this.legL.an.rotation.x = walking ? -Math.sin(p + 0.9) * 0.35 : -0.15 * sb;
    this.legR.an.rotation.x = walking ? Math.sin(p + 0.9) * 0.35 : -0.15 * sb;
    this.hips.position.y = lerp(0.92 + (walking ? Math.abs(sw2) * 0.035 : 0) - (walking ? 0.012 : 0), 0.52, sb);
    this.hips.position.z = lerp(0, -0.05, sb);
    this.hips.position.x = idleShift * 0.018;
    this.hips.rotation.z = idleShift * 0.035; this.hips.rotation.y = walking ? sw * 0.12 : 0;
    // torso: breathing, counter-rotation, lean
    const breath = Math.sin(t * 1.6 + this.phase) * 0.012;
    let lean = walking ? 0.07 : 0; if (pose === "write" || pose === "present") lean = -0.04; if (pose === "lean") lean = 0.32;
    this.torso.rotation.x = lerp(lean, 0.1, sb) + breath;
    this.torso.rotation.y = walking ? -sw * 0.16 : Math.sin(t * 0.4 + this.phase) * 0.03;
    this.torso.rotation.z = -idleShift * 0.03;
    // arms
    const L = this.armL, Rr = this.armR;
    let lSh = 0, lEl = -0.08, rSh = 0, rEl = -0.08, lZ = 0.08, rZ = -0.08;
    if (walking) { lSh = -sw * 0.55; rSh = sw * 0.55; lEl = -0.3 - Math.max(0, -sw) * 0.35; rEl = -0.3 - Math.max(0, sw) * 0.35; }
    if (this.carryObj) { lSh = rSh = -0.75; lEl = rEl = -0.9; }
    if (seated) {
      const typing = this.role !== "ceo" || Math.sin(t * 0.3) > 0, fast = this.typingFast ? 1.8 : 1;
      lSh = rSh = -0.62; lEl = rEl = -1.0; lZ = 0.18; rZ = -0.18;
      if (typing) { lEl += Math.sin(t * 17 * fast + this.phase) * 0.07; rEl += Math.sin(t * 15 * fast + this.phase * 2) * 0.07; lSh += Math.sin(t * 3 + this.phase) * 0.03; }
      if (Math.sin(t * 0.21 + this.phase * 3) > 0.985) { rSh = -1.2; rEl = -0.4; } // reach for the mouse / screen
      if (Math.sin(t * 0.13 + this.phase) > 0.97) { lSh = rSh = -2.6; lEl = rEl = -0.6; } // stretch
    }
    const talking = this.speaking && !walking;
    if (pose === "talk") {
      if (talking) { const g = Math.sin(t * 3.2 + this.phase), g2 = Math.sin(t * 2.1 + this.phase * 1.7); rSh = -0.55 - Math.max(0, g) * 0.6; rEl = -1.15 + g * 0.3; rZ = -0.3 - g2 * 0.1; lSh = -0.25 + Math.max(0, g2) * 0.4; lEl = -0.6 - Math.max(0, g2) * 0.4; lZ = 0.2; }
      else { lSh = rSh = -0.08; lEl = rEl = -0.2; if (this.mood < -0.3) { lSh = rSh = -0.5; lEl = rEl = -1.9; lZ = 0.55; rZ = -0.55; } } // arms crossed when unhappy
    }
    if (pose === "coffee") { rSh = -1.25 + Math.max(0, Math.sin(t * 0.8 + this.phase)) * -0.35; rEl = -1.75; rZ = -0.25; }
    if (pose === "phone") { rSh = -1.05; rEl = -2.45; rZ = -0.9; lSh = -0.2; lEl = -1.3; lZ = 0.6; }
    if (pose === "cheer") { lSh = rSh = -2.9 + Math.sin(t * 9) * 0.15; lEl = rEl = -0.2; lZ = 0.3; rZ = -0.3; }
    if (pose === "clap") { const c = Math.sin(t * 16) * 0.12; lSh = rSh = -1.15; lEl = rEl = -1.25; lZ = -0.55 + c; rZ = 0.55 - c; }
    if (pose === "highfive") { rSh = -2.6; rEl = -0.15; rZ = -0.35; }
    if (pose === "facepalm") { rSh = -2.2; rEl = -2.1; rZ = -0.5; }
    if (pose === "think") { rSh = -1.6; rEl = -2.3; rZ = -0.35; lSh = -0.3; lEl = -1.4; lZ = 0.5; }
    if (pose === "point") { rSh = -1.45; rEl = -0.1; rZ = -0.2; }
    if (pose === "present") { rSh = -1.3 + Math.sin(t * 1.3) * 0.15; rEl = -0.25; rZ = -0.55; lSh = -0.6; lEl = -0.9; lZ = 0.4; }
    if (pose === "write") { const w = t * 5 + this.phase; rSh = -2.0 + Math.sin(w) * 0.12; rEl = -0.5 + Math.cos(w * 1.3) * 0.15; rZ = -0.25 + Math.sin(w * 0.7) * 0.12; lSh = -0.1; lEl = -0.5; }
    if (pose === "lean") { lSh = rSh = -0.9; lEl = rEl = -0.25; lZ = 0.15; rZ = -0.15; }
    const ks = 1 - Math.exp(-12 * dt);
    L.sh.rotation.x += (lSh - L.sh.rotation.x) * ks; L.el.rotation.x += (lEl - L.el.rotation.x) * ks; L.sh.rotation.z += (lZ - L.sh.rotation.z) * ks;
    Rr.sh.rotation.x += (rSh - Rr.sh.rotation.x) * ks; Rr.el.rotation.x += (rEl - Rr.el.rotation.x) * ks; Rr.sh.rotation.z += (rZ - Rr.sh.rotation.z) * ks;
    // props
    this.props.cup.visible = pose === "coffee"; this.props.phone.visible = pose === "phone"; this.props.tablet.visible = !!this.carryTablet;
    // head: look at partner / screen, nod while listening, head shake when upset, glance around when idle
    let hy = 0, hx = seated ? 0.14 : 0;
    if (this.lookTarget) { const lt = this.lookTarget.pos || this.lookTarget; const a = Math.atan2(lt.x - this.pos.x, lt.z - this.pos.z); hy = clamp(angDiff(this.yaw, a), -1.1, 1.1); hx = -0.05; }
    if (pose === "talk" && !this.speaking) hx += Math.max(0, Math.sin(t * 2.4 + this.phase)) * 0.13;
    if (pose === "facepalm") hy += Math.sin(t * 7) * 0.25;
    if (pose === "write" || pose === "present") hx = -0.12;
    if (!walking && !seated && pose === "stand" && !this.lookTarget) hy += Math.sin(t * 0.5 + this.phase) * 0.4;
    if (walking) hx = 0.05 - sw2 * 0.02;
    if (seated && Math.sin(t * 0.37 + this.phase * 2) > 0.93) hy = 0.6; // glance at the neighbour
    this.head.rotation.y += (hy - this.head.rotation.y) * ks; this.head.rotation.x += (hx - this.head.rotation.x) * ks;
    this.head.rotation.z = talking ? Math.sin(t * 2.6 + this.phase) * 0.06 : 0;
    // face: mouth opens with speech, smile/frown with mood, brows follow emotion, blink, eyes dart
    this.mood = damp(this.mood, 0, 0.08, dt);
    const m = this.mood + (pose === "cheer" || pose === "highfive" || pose === "clap" ? 0.8 : 0) - (pose === "facepalm" ? 0.8 : 0);
    this.mouthOpen.scale.y = talking ? 0.25 + Math.abs(Math.sin(t * 13 + Math.sin(t * 5))) * 0.9 : (pose === "cheer" ? 0.8 : 0.12);
    this.smile.rotation.z = m >= 0 ? Math.PI : 0; this.smile.scale.y = 0.25 + Math.min(1, Math.abs(m)) * 0.75;
    this.smile.position.y = m >= 0 ? 0.004 : -0.012;
    const browLift = (talking ? Math.max(0, Math.sin(t * 2.2 + this.phase)) * 0.01 : 0) + (pose === "think" ? 0.008 : 0);
    this.brows.forEach(b => { b.position.y = 0.172 + browLift; b.rotation.z = b.userData.side * (m < -0.2 ? -0.35 : m > 0.4 ? 0.12 : 0) * Math.min(1, Math.abs(m) + 0.3); });
    this.blinkT -= dt; const blink = this.blinkT < 0.12; if (this.blinkT < 0) this.blinkT = rand(2, 5);
    const dart = Math.sin(t * 0.7 + this.phase * 5) > 0.8 ? 0.004 : 0;
    this.eyes.forEach(e => { e.scale.y = blink ? 0.1 : 1; e.userData.pupil.position.x = dart; });
    if (this.carryObj) { this.carryObj.position.set(0, 1.08, 0.32); }
  }
}
function angDiff(a, b) { let d = b - a; while (d > Math.PI) d -= 2 * Math.PI; while (d < -Math.PI) d += 2 * Math.PI; return d; }
function roleName(r) { return {trader: "Trader", research: "Quant researcher", risk: "Risk officer", scanner: "Market scanner", learn: "Learning analyst", ops: "Site reliability", ceo: "Lifecycle manager"}[r] || r; }

// ---- cast (names are fixed so they stay recognisable)
const ceo = new Person("Mila", "ceo", ceoSeat, {hair: 2, badge: true});
const scout = new Person("Ravi", "scanner", seats.scan0);
const scout2 = new Person("Ines", "scanner", seats.scan1, {hair: 1});
const researchers = [["Ada", 3], ["Kenji", 0], ["Lena", 1], ["Omar", 0]].map(([n, h], i) => new Person(n, "research", labSeats[i], {hair: h}));
const risk = new Person("Viktor", "risk", riskSeat, {hair: 0, badge: true});
const analyst = new Person("Noor", "learn", learnSeat, {hair: 3});
const sre = new Person("Sam", "ops", opsSeat, {hair: 0});
const traderNames = ["Jonas", "Priya", "Marco", "Sofia", "Eli", "Hana", "Tom", "Zara"];
const traders = traderNames.map((n, i) => new Person(n, "trader", tradeSeats[i], {hair: i % 4}));
for (const c of chars) { c.pos.copy(c.homeSeat.approach); c.sitAt(c.homeSeat); }

// ============================================================== director (behaviour from data)
const feedEl = $("#feed");
function feed(who, text) {
  const d = document.createElement("div"); d.className = "ev";
  d.innerHTML = `<span class="t">${new Date().toLocaleTimeString().slice(0, 5)}</span><b>${esc(who)}</b> ${esc(text)}`;
  feedEl.insertBefore(d, feedEl.children[1] || null);
  while (feedEl.children.length > 9) feedEl.removeChild(feedEl.lastChild);
}
function conversation(a, b, lines, at = null, after = null) {
  // a walks to b (or both to a spot), they face each other, exchange lines, return to desks
  if (a.busy() || b.busy()) { feed(lines[0][0].name, lines[0][1]); return false; }
  const meet = at || b.pos.clone().add(new THREE.Vector3(Math.sin(b.yaw), 0, Math.cos(b.yaw)).multiplyScalar(1.0));
  const bSpot = at ? at.clone().add(new THREE.Vector3(0.9, 0, 0)) : null;
  a.goTo(at ? at : meet).face(b);
  if (bSpot) b.goTo(bSpot); b.face(a);
  let delay = 0;
  const speak = (who, other, text, ms) => {
    who.do({type: "call", fn: () => { who.pose = "talk"; who.lookTarget = other; who.say(text, ms); feed(who.name, text); }}).wait(ms, "talk");
    other.wait(ms, "talk");
  };
  // synchronise: both wait until a has arrived
  b.do({type: "call", fn: () => { b.pose = "talk"; b.lookTarget = a; }});
  for (const [who, text] of lines) { const other = who === a ? b : a; const ms = clamp(1800 + text.length * 45, 2500, 7000); speak(who, other, text, ms); delay += ms; }
  for (const p of [a, b]) p.do({type: "call", fn: () => { p.pose = "stand"; p.lookTarget = null; p.speaking = false; }}).sitAt(p.homeSeat);
  if (after) a.do({type: "call", fn: after});
  return true;
}
function deliverDoc(from, to, text) {
  if (from.busy()) return;
  const doc = boxM(0.24, 0.02, 0.32, M.paper); from.root.add(doc); from.carryObj = doc;
  conversation(from, to, [[from, text[0]], [to, text[1]]]);
  from.queue.splice(2, 0, {type: "call", fn: () => { from.root.remove(doc); from.carryObj = null; }});
}
function coffeeBreak() {
  const idle = chars.filter(c => !c.busy() && c.role !== "ceo");
  if (idle.length < 2) return;
  const a = pick(idle), b = pick(idle.filter(x => x !== a));
  const lines = pick([
    [[a, "Coffee? The hyperopt queue isn't going anywhere."], [b, "Always. Any signals on your sleeves?"], [a, "Waiting for a clean 1h close — no forcing trades."]],
    [[a, "Did you see the gate failures today?"], [b, "Deflated Sharpe is brutal with more trials. Good — no overfitting."]],
    [[a, "Memory looks stable since the watchdog."], [b, "Nice. The bot has priority, research yields first."]],
    [[a, "Stops are on the exchange, right?"], [b, "Every position — we verified it with a real demo order."]],
  ]);
  const spot = pick(coffeeSpots);
  a.goTo(spot).do({type: "call", fn: () => { a.pose = "coffee"; }}).wait(4000, "coffee");
  b.goTo(spot.clone().add(new THREE.Vector3(-0.9, 0, 0.4))).do({type: "call", fn: () => { b.pose = "coffee"; }}).wait(2500, "coffee");
  setTimeout(() => conversation(a, b, lines, spot.clone().add(new THREE.Vector3(-0.5, 0, 0.9))), 9000);
}
function wanderSomeone() {
  const idle = chars.filter(c => !c.busy());
  if (!idle.length) return;
  const c = pick(idle);
  const spots = {research: [board.mesh.position.clone().setY(0).setX(-20.6)], trader: [new THREE.Vector3(rand(-4, 4), 0, -13.3)], scanner: [dish.position.clone().add(new THREE.Vector3(1.4, 0, 0))],
    ops: [racks[2].position.clone().add(new THREE.Vector3(0, 0, 1.2))], learn: [new THREE.Vector3(15, 0, 13.1)], risk: [lampBar.position.clone().setZ(13.2).setY(0)], ceo: [new THREE.Vector3(0, 0, -3)]}[c.role] || [];
  if (!spots.length) return;
  const s = pick(spots);
  const target = {research: board.mesh.position, trader: wall.mesh.position, risk: lampBar.position, ceo: new THREE.Vector3(0, 3, 1.6)}[c.role];
  const pose = c.role === "research" ? "write" : c.role === "ceo" ? "present" : pick(["think", "point", "stand"]);
  if (c.role === "ceo") s.set(rand(-2, 2), 0, 3.6);
  c.goTo(s);
  if (target) c.face(target.clone().setY(0));
  c.do({type: "call", fn: () => { c.pose = pose; if (pose === "write") c.say(pick(boardNotes()), 4200); }}).wait(rand(4000, 7000), pose)
   .do({type: "call", fn: () => { c.pose = "stand"; }}).sitAt(c.homeSeat);
}
function boardNotes() {
  const rs = S.rs || {}, lab = rs.lab || {}, ex = (rs.experiments || []).find(e => e.oos);
  const out = ["Note to self: only out-of-sample numbers count.", "Writing down the fold windows — no peeking at the test data."];
  if (ex) out.push(`${ex.variant || ex.family}: OOS PF ${num(ex.oos.profit_factor)} — ${ex.summary?.verdict || ex.status}.`);
  if (ex?.summary?.n_trials) out.push(`Deflated Sharpe now penalises ${ex.summary.n_trials} trials. Bar keeps rising.`);
  const gf = Object.entries(rs.gate_failures || {}).sort((a, b) => b[1] - a[1])[0];
  if (gf) out.push(`Most failed gate lately: ${gf[0]} (${gf[1]}×). Adding that to the hypothesis list.`);
  if (lab.runs) out.push(`GitHub lab: ${lab.runs} runs so far, ${lab.experiments_total || 0} experiments imported.`);
  return out;
}
setInterval(() => { if (Math.random() < 0.45) wanderSomeone(); }, 7000);
setInterval(() => { if (Math.random() < 0.5) coffeeBreak(); }, 26000);
setInterval(() => { if (!meetingOn) standup(); }, 270000);
setTimeout(() => standup(), 75000);
setInterval(() => { const c = pick(chars.filter(x => x.root.visible && !x.busy() && x.role !== "trader")); if (!c) return;
  c.do({type: "call", fn: () => { c.pose = "phone"; c.say(pick(["Yes — demo account only, no real money.", "The GitHub runner is on it, results in a couple of hours.", "Stops are always on the exchange.", "We'll know more after the forward test."]), 5000); }}).wait(6000, "phone").do({type: "call", fn: () => { c.pose = "stand"; }}).sitAt(c.homeSeat); }, 95000);

// ============================================================== data → scenes
const S = {ov: null, rs: null, hl: null, ln: null, goals: null, market: null, strats: null, candles: {}, flash: {}, lossHist: {}, lock: {}, lastEventId: null, openIds: new Set(), first: true};
function onEvent(e) {
  const m = e.message || "";
  if (e.source === "research" && /^lab: /.test(m)) { onLabEvent(e, m); return; }
  if (e.source === "research") {
    const r = pick(researchers);
    const verdict = /: (validated|exploratory|rejected)/.exec(m)?.[1] || /imported as (\w+)/.exec(m)?.[1];
    if (verdict === "validated") setTimeout(() => celebrate(r, "✅"), 1500);
    if (verdict) {
      const reply = verdict === "validated" ? "All gates passed. Send it to incubation — small risk, forward test on Bybit Demo."
        : verdict === "exploratory" ? "Close, but not robust enough for incubation. Exploration lane at 0.1% risk."
        : "Rejected. I won't trade a curve-fit. Back to the lab.";
      deliverDoc(r, risk, [m.replace(/^\S+ /, "").slice(0, 130), reply]);
      if (verdict === "rejected") setTimeout(() => { r.pose = "facepalm"; }, 200);
    } else if (/failed/.test(m)) { r.say("Experiment crashed — watchdog will retry with a lighter load."); r.pose = "facepalm"; feed(r.name, m.slice(0, 120)); }
    else { r.say(m.slice(0, 120)); feed(r.name, m.slice(0, 120)); }
  } else if (e.source === "lifecycle") {
    const tr = pick(traders.filter(t => !t.busy())) || traders[0];
    const to = /→ (\w+)/.exec(m)?.[1];
    conversation(ceo, tr, [[ceo, m.slice(0, 140)], [tr, to === "production" ? "Production risk it is. I'll watch it closely." : to === "retired" ? "Understood, closing it down cleanly." : "Got it — updating the sleeve."]]);
  } else if (e.source === "learner") {
    conversation(analyst, pick(researchers), [[analyst, m.replace("new learning ", "").slice(0, 150)], [researchers[0], "Good catch. I'll A/B test that adjustment in the next experiments."]]);
  } else if (["selftest", "supervisor", "memory", "manager"].includes(e.source)) {
    sre.say(m.slice(0, 140), 7000); feed(sre.name, m.slice(0, 140));
    if (/FAILED|error|stale|exited/i.test(m)) { sre.pose = "facepalm"; }
  } else if (e.source === "risk") {
    conversation(risk, ceo, [[risk, m.slice(0, 140)], [ceo, "Agreed. Capital protection first."]]);
  } else if (e.source === "scanner") {
    scout.say(m.slice(0, 140), 6000); feed(scout.name, m.slice(0, 140));
  } else { ceo.say(m.slice(0, 140)); feed(e.source, m.slice(0, 140)); }
}
function onTrades(open, sleeves) {
  const ids = new Set(open.map(t => t.trade_id));
  if (!S.first) {
    for (const t of open) if (!S.openIds.has(t.trade_id)) {
      const tr = traderFor(t.enter_tag, sleeves);
      tr.say(`Opened ${t.is_short ? "short" : "long"} ${t.pair.split(":")[0]} @ ${num(t.open_rate, 4)} — stop ${num(t.stop_loss_abs, 4)} sits on the exchange.`, 7000);
      tr.emote(t.is_short ? "📉" : "📈"); feed(tr.name, `opened ${t.is_short ? "short" : "long"} ${t.pair}`);
      S.flash[t.enter_tag] = performance.now();
    }
    const gone = [...S.openIds].filter(id => !ids.has(id));
    if (gone.length) api("/api/trades?limit=20").then(d => {
      for (const id of gone) {
        const ct = (d.closed || []).find(x => x.trade_id === id); if (!ct) continue;
        const tr = traderFor(ct.sleeve_id, sleeves), pnl = Number(ct.profit_abs || 0);
        const txt = `Closed ${ct.pair.split(":")[0]} by ${ct.exit_reason}: ${pnl >= 0 ? "+" : ""}${num(pnl)} USDT (${pct(ct.profit_ratio, 2)}).`;
        feed(tr.name, txt);
        if (pnl >= 0) { tr.say(txt + " Logging it.", 6500); celebrate(tr, "💰"); }
        else { tr.say(txt + " Stop did its job.", 6500); tr.feel(-0.7); tr.emote("🩹");
          conversation(analyst, tr, [[analyst, `Loss on ${ct.pair.split("/")[0]} — I'll add it to the post-mortem: entry context, MFE, exit reason.`], [tr, "Thanks. If it repeats on this pair, exclude it for a while."]]); }
      }
    }).catch(() => {});
  }
  S.openIds = ids;
}
function celebrate(p, sym = "🎉") {
  p.emote(sym); p.feel(1);
  const near = chars.filter(c => c !== p && c.root.visible && !c.busy() && c.pos.distanceTo(p.pos) < 6).slice(0, 2);
  if (!p.busy()) p.do({type: "call", fn: () => { p.pose = "cheer"; }}).wait(2200, "cheer").do({type: "call", fn: () => { p.pose = "stand"; }}).sitAt(p.homeSeat);
  near.forEach(n => { n.feel(0.8); n.do({type: "call", fn: () => { n.pose = "clap"; n.lookTarget = p; }}).wait(2000, "clap").do({type: "call", fn: () => { n.pose = "stand"; n.lookTarget = null; }}); });
}

// ---- lab (GitHub research runs) → scenes
function onLabEvent(e, m) {
  const lead = researchers[0];
  if (/run .* started/.test(m)) {
    sre.say(m.replace("lab: ", "").slice(0, 140) + " Heavy compute stays off our server.", 7000); sre.emote("☁️");
    feed(sre.name, m.slice(5, 140)); researchers.forEach(r => r.emote("🧪", 2000));
  } else if (/experiment .* started/.test(m)) {
    const r = pick(researchers); r.say(m.slice(5, 150), 6500); r.emote("🧪"); feed(r.name, m.slice(5, 150));
  } else if (/imported/.test(m)) {
    flyPacket(beamFrom, new THREE.Vector3(-15.5, 1.2, -8.5), 0x29d36a);
    setTimeout(() => flyPacket(new THREE.Vector3(-15.5, 1.2, -8.5), new THREE.Vector3(0, 1.2, 9.5), 0xfab219), 3300);
    lead.say("Results package from GitHub just landed — sending candidates to risk.", 6000); lead.emote("📦"); feed(lead.name, m.slice(5, 160));
  } else if (/failed/.test(m)) { const r = pick(researchers); r.say(m.slice(5, 140), 6000); r.emote("⚠️"); r.feel(-0.5); feed(r.name, m.slice(5, 140)); }
  else { lead.say(m.slice(5, 140)); feed(lead.name, m.slice(5, 140)); }
}
let lastNarr = 0, lastNarrKey = "";
function narrateLab() {
  const run = (S.rs?.experiments || []).find(e => e.status === "running");
  for (const r of researchers) r.typingFast = !!run;
  if (!run) return;
  const pg = run.progress || {}; const key = `${run.id}|${pg.stage}|${pg.epoch}`;
  if (pg.best_loss !== undefined) { const h = S.lossHist[run.id] ||= []; if (h.at(-1) !== pg.best_loss) h.push(pg.best_loss); }
  if (key === lastNarrKey || Date.now() - lastNarr < 40000) return;
  lastNarrKey = key; lastNarr = Date.now();
  const r = researchers.find(x => !x.busy()) || researchers[0];
  let txt;
  if (String(pg.stage || "").startsWith("hyperopt") && pg.epoch) txt = `${pg.stage}: epoch ${pg.epoch}/${pg.epochs || "?"}, best so far ${pct(pg.best_profit)} on ${pg.best_trades ?? "–"} trades (in-sample — doesn't count yet).`;
  else if (String(pg.stage || "").startsWith("oos")) txt = `${pg.stage}: testing the winner on data it has never seen.`;
  else if (pg.stage === "robustness") txt = "Robustness check: jiggling every parameter ±10% — a real edge survives that.";
  else if (pg.stage === "download") txt = `Fetching fresh candles for ${run.pairs} pairs on the GitHub runner…`;
  else txt = `${run.family}: ${pg.stage || "working"}…`;
  r.say(txt, 7000); feed(r.name, txt);
}

// ---- daily stand-up at the meeting table: every line is real data
let meetingOn = false;
function meeting(people, lines) {
  const ps = people.filter(p => p && p.root.visible);
  if (meetingOn || ps.some(p => p.busy())) return false;
  meetingOn = true;
  const center = table.position.clone();
  const spots = [new THREE.Vector3(-4.1, 0, 8.6), new THREE.Vector3(0.5, 0, 8.6), new THREE.Vector3(-2.6, 0, 7.15), new THREE.Vector3(-1.0, 0, 7.15), new THREE.Vector3(-2.6, 0, 10.05), new THREE.Vector3(-1.0, 0, 10.05)];
  ps.forEach((p, i) => { p.arrived = false; p.goTo(spots[i]).face(center).do({type: "call", fn: () => { p.pose = "stand"; p.arrived = true; }}); });
  let started = false;
  const start = () => {
    if (started) return; started = true; ps.forEach(p => { p.locked = true; });
    let t = 0;
    for (const [who, text] of lines) {
      const ms = clamp(1500 + text.length * 42, 2600, 8000);
      setTimeout(() => { ps.forEach(p => { p.pose = "talk"; p.lookTarget = p === who ? center : who; }); who.say(text, ms); feed(who.name, text); }, t);
      t += ms + 500;
    }
    setTimeout(() => { ps.forEach(p => { p.locked = false; p.pose = "stand"; p.lookTarget = null; p.speaking = false; p.sitAt(p.homeSeat); }); meetingOn = false; }, t + 400);
  };
  const poll = setInterval(() => { if (ps.every(p => p.arrived)) { clearInterval(poll); start(); } }, 300);
  setTimeout(() => { clearInterval(poll); start(); }, 30000);
  return true;
}
function standup() {
  const G = S.goals?.goals || [], rs = S.rs || {}, hl = S.hl || {}, ln = S.ln || {};
  if (!G.length) return;
  const g = id => G.find(x => x.id === id) || {};
  const ex = (rs.experiments || []).find(e => e.oos), running = (rs.experiments || []).find(e => e.status === "running");
  const gf = Object.entries(rs.gate_failures || {}).sort((a, b) => b[1] - a[1])[0];
  const mem = (hl.heartbeats || []).find(h => h.service === "manager")?.detail?.mem_headroom_mb;
  const act = (ln.learnings || []).filter(l => l.active);
  const lr = researchers.find(r => !r.busy()) || researchers[0];
  const lines = [
    [ceo, `Stand-up. Real-money readiness: ${g("readiness").value ?? 0}/${g("readiness").target ?? 8} checks. Evidence: ${g("evidence").value ?? 0}/100 demo trades. Research: ${g("research").value ?? 0}/${g("research").target ?? "–"} experiments this week. Validated strategies: ${g("validated").value ?? 0}.`],
    [lr, ex ? `Latest result: ${ex.variant || ex.family} — OOS PF ${num(ex.oos.profit_factor)}, Sharpe ${num(ex.oos.sharpe)}, ${ex.summary?.verdict || ex.status}. ${running ? `GitHub run live: ${running.progress?.stage || "working"}.` : "Next GitHub run is queued."}` : "No finished experiments yet — the GitHub lab is warming up."],
    [risk, gf ? `Top failing gate: ${gf[0]} (${gf[1]}×). Deflated Sharpe counts ${ex?.summary?.n_trials ?? "all"} trials — no shortcuts.` : "No candidates to judge yet. Gates stay strict."],
    [analyst, act.length ? `${act.length} active learnings. Newest: ${act[0].insight.slice(0, 110)}` : "No lessons yet — I need closed trades and finished experiments."],
    [sre, `Bot ${hl.bot_up ? "up" : "DOWN"}, ${mem ? mem + " MB memory headroom" : "memory fine"}, order test ${hl.exec_test?.ok ? "passing" : "pending"}. Research runs on GitHub, not here.`],
    [ceo, (g("validated").value || 0) < 1 ? "Priority unchanged: one strategy that passes every strict gate, then prove it live. Back to work." : "We have a validated strategy — now let the forward test speak. Back to work."],
  ];
  meeting([ceo, lr, risk, analyst, sre], lines);
}
function lockedPnl(t) {
  const st = Number(t.stop_loss_abs), o = Number(t.open_rate), notional = Number(t.stake_amount || 0) * Number(t.leverage || 1);
  if (!st || !o || !notional) return null;
  return (t.is_short ? (o - st) : (st - o)) / o * notional;
}
function watchProtection(open, sleeves) {
  for (const t of open) {
    const lk = lockedPnl(t); if (lk === null) continue;
    const prev = S.lock[t.trade_id];
    if (lk >= 0 && (prev === undefined || prev < 0)) { const tr = traderFor(t.enter_tag, sleeves); if (!S.first) { tr.say(`${t.pair.split(":")[0]}: stop moved to break-even — this trade can no longer turn into a loss.`, 6500); tr.emote("🔒"); feed(tr.name, `break-even stop on ${t.pair}`); } }
    else if (prev !== undefined && prev >= 0 && lk > prev + Math.max(1, Math.abs(prev) * 0.25)) { const tr = traderFor(t.enter_tag, sleeves); if (!S.first) { tr.say(`Ratcheting the stop on ${t.pair.split(":")[0]}: +${num(lk)} USDT is now locked in.`, 6000); tr.emote("📈"); feed(tr.name, `locked +${num(lk)} on ${t.pair}`); } }
    S.lock[t.trade_id] = lk;
  }
}
function traderFor(tag, sleeves) { const i = Math.max(0, sleeves.findIndex(s => s.id === tag)); return traders[i % traders.length]; }

// ============================================================== screens content (real data)
const C = {bg: "#0d1420", text: "#f0efec", muted: "#8d8c84", dim: "#5a6372", blue: "#3987e5", lblue: "#7fb6ff", green: "#29d36a", red: "#e66767", amber: "#fab219"};
function clr(sc, bg = C.bg) { const {g, c} = sc; g.fillStyle = bg; g.fillRect(0, 0, c.width, c.height); g.textAlign = "left"; return [g, c]; }
function txt(g, s, x, y, col = C.text, font = "13px monospace") { g.fillStyle = col; g.font = font; g.fillText(String(s), x, y); }
function bar(g, x, y, w, h, frac, col, bg = "#ffffff14") { g.fillStyle = bg; g.fillRect(x, y, w, h); g.fillStyle = col; g.fillRect(x, y, w * clamp(frac || 0, 0, 1), h); }
function wrap(g, s, x, y, maxW, lh, maxLines = 4) {
  const words = String(s).split(" "); let line = "", n = 0;
  for (const w of words) { const t = line ? line + " " + w : w; if (g.measureText(t).width > maxW && line) { g.fillText(line, x, y + n * lh); line = w; if (++n >= maxLines) return; } else line = t; }
  if (line) g.fillText(line, x, y + n * lh);
}
function drawCandles(g, x, y, w, h, rows, lines = []) {
  if (!rows || rows.length < 5) { txt(g, "loading candles…", x + 4, y + h / 2, C.dim); return null; }
  const lo0 = Math.min(...rows.map(r => r[3]), ...lines.map(l => l.v)), hi0 = Math.max(...rows.map(r => r[2]), ...lines.map(l => l.v));
  const pad = (hi0 - lo0) * 0.06 || 1, lo = lo0 - pad, hi = hi0 + pad, Y = v => y + h - (v - lo) / (hi - lo) * h;
  const cw = w / rows.length;
  g.strokeStyle = "#ffffff10"; g.lineWidth = 1; for (let k = 1; k < 4; k++) { g.beginPath(); g.moveTo(x, y + k * h / 4); g.lineTo(x + w, y + k * h / 4); g.stroke(); }
  rows.forEach((r, i) => {
    const [, o, hh, l, c] = r, up = c >= o, cx = x + i * cw + cw / 2;
    g.strokeStyle = up ? "#4fa3ff" : "#ff7b7b"; g.beginPath(); g.moveTo(cx, Y(hh)); g.lineTo(cx, Y(l)); g.stroke();
    g.fillStyle = up ? "#3987e5" : "#e66767"; const yo = Y(Math.max(o, c)), hb = Math.max(1, Math.abs(Y(o) - Y(c))); g.fillRect(cx - cw * 0.35, yo, Math.max(1, cw * 0.7), hb);
  });
  for (const l of lines) { g.strokeStyle = l.col; g.setLineDash([4, 3]); g.beginPath(); g.moveTo(x, Y(l.v)); g.lineTo(x + w, Y(l.v)); g.stroke(); g.setLineDash([]);
    g.fillStyle = l.col; g.font = "bold 10px monospace"; g.textAlign = "right"; g.fillText(l.label, x + w - 2, Y(l.v) - 2); g.textAlign = "left"; }
  return rows.at(-1)[4];
}
function sleevePair(sl, ov) { const t = ov.open_trades.find(x => x.enter_tag === sl.id); return t ? t.pair : sl.pairs[0]; }
function stratOf(id) { return (S.strats?.strategies || []).find(x => x.id === id) || {}; }

function drawAll(t) {
  const {ov, rs, hl} = S; if (!ov) return;
  const live = ov.manifest.sleeves.filter(s => s.stage !== "closing");
  // --- traders: real 1h candles of their pair with entry / stop / target, sleeve stats on the 2nd screen
  tradeSeats.forEach((s, i) => {
    const sl = live[i]; const [g, c] = clr(s.screen);
    if (!sl) { txt(g, "— desk free —", 70, 85, "#3a4250", "bold 18px monospace"); s.screen.tex.needsUpdate = true; if (s.screen.second) { clr(s.screen.second); s.screen.second.tex.needsUpdate = true; } return; }
    const col = sl.stage === "production" ? C.green : sl.stage === "incubation" ? C.blue : C.amber;
    const flash = performance.now() - (S.flash[sl.id] || 0) < 4000 && Math.sin(t * 12) > 0;
    g.fillStyle = flash ? "#ffffff" : col; g.fillRect(0, 0, c.width, 20);
    txt(g, `${sl.stage.toUpperCase()} · risk ${(sl.risk * 100).toFixed(2)}%`, 6, 15, C.bg, "bold 12px monospace");
    const pair = sleevePair(sl, ov), pos = ov.open_trades.find(x => x.enter_tag === sl.id);
    const lines = [];
    if (pos) {
      const dir = pos.is_short ? -1 : 1, isl = Number(pos.initial_stop_loss_abs || pos.stop_loss_abs), rr = Number(sl.params?.tp_rr || 2);
      lines.push({v: pos.open_rate, col: C.lblue, label: "entry"}, {v: pos.stop_loss_abs, col: C.red, label: "stop"});
      if (isl && pos.open_rate) lines.push({v: pos.open_rate + dir * rr * Math.abs(pos.open_rate - isl), col: C.green, label: "target"});
    }
    const last = drawCandles(g, 4, 46, 248, 92, S.candles[pair]?.rows, lines);
    txt(g, pair.replace(":USDT", ""), 6, 38, C.text, "bold 13px monospace");
    if (last) { g.textAlign = "right"; txt(g, num(last, last < 1 ? 5 : last < 100 ? 3 : 1), 250, 38, C.muted, "12px monospace"); g.textAlign = "left"; }
    if (pos) { txt(g, `${pos.is_short ? "SHORT" : "LONG"} ${pos.profit_abs >= 0 ? "+" : ""}${num(pos.profit_abs)} USDT`, 6, 154, pos.profit_abs >= 0 ? C.lblue : C.red, "bold 13px monospace");
      const lk = lockedPnl(pos); if (lk !== null) txt(g, lk >= 0 ? `🔒 +${num(lk)}` : `stop −${num(-lk)}`, 168, 154, lk >= 0 ? C.green : C.muted, "bold 12px monospace"); }
    else txt(g, "no position · waiting for a 1h signal" + ".".repeat(1 + Math.floor(t * 2) % 3), 6, 154, C.dim, "11px monospace");
    s.screen.tex.needsUpdate = true;
    if (s.screen.second) {
      const [g2] = clr(s.screen.second), st = stratOf(sl.id), lv = st.live || {}, oo = st.oos || {}, pp = sl.params || {};
      txt(g2, sl.id.slice(0, 26), 6, 16, C.text, "bold 12px monospace");
      txt(g2, (oo.variant || sl.family).slice(0, 30), 6, 32, C.muted, "11px monospace");
      txt(g2, `LIVE  ${lv.trades || 0} trades · PF ${lv.trades ? num(lv.profit_factor) : "–"}`, 6, 54, C.text, "12px monospace");
      txt(g2, `      P&L ${lv.trades ? num(lv.pnl) : "–"} · win ${lv.trades ? pct(lv.win_rate, 0) : "–"}`, 6, 70, C.text, "12px monospace");
      txt(g2, `OOS   PF ${num(oo.profit_factor)} · Sharpe ${num(oo.sharpe)}`, 6, 92, C.muted, "12px monospace");
      txt(g2, `stop ${pp.sl_atr ?? "–"}×ATR  target ${pp.tp_rr ?? "–"}R  trail ${pp.trail_rr ?? "–"}R`, 6, 114, C.dim, "11px monospace");
      txt(g2, `max hold ${pp.max_hold ?? "–"}h  pairs ${sl.pairs.map(p => p.split("/")[0]).join(" ")}`.slice(0, 34), 6, 130, C.dim, "11px monospace");
      s.screen.second.tex.needsUpdate = true;
    }
  });
  // --- research lab screens
  const exps = rs.experiments || [], running = exps.find(e => e.status === "running"), done = exps.filter(e => e.oos);
  labSeats.forEach((s, i) => {
    const [g] = clr(s.screen);
    if (i === 0) {
      txt(g, running ? (running.progress?.remote ? "GITHUB LAB · LIVE" : "LIVE EXPERIMENT") : "LAB · WAITING FOR RUN", 6, 16, C.blue, "bold 12px monospace");
      if (running) {
        const pg = running.progress || {};
        txt(g, `${running.family} · ${running.pairs} pairs`, 6, 34); txt(g, String(pg.stage || "").slice(0, 30), 6, 50, C.amber);
        if (pg.epoch) { txt(g, `epoch ${pg.epoch}/${pg.epochs || "?"}`, 6, 68, C.muted, "12px monospace"); bar(g, 110, 60, 140, 8, pg.epoch / (pg.epochs || 80), C.blue); }
        if (pg.best_profit !== undefined) txt(g, `best IS ${pct(pg.best_profit)} · ${pg.best_trades ?? "–"} trades`, 6, 84, C.text, "12px monospace");
        const h = S.lossHist[running.id] || []; if (h.length > 1) drawSpark(g, 6, 92, 244, 44, h.map(v => -v), C.lblue);
        if (pg.budget_left_min !== undefined) txt(g, `run budget left ${Math.round(pg.budget_left_min)} min`, 6, 152, C.dim, "11px monospace");
      } else { const lab = rs.lab || {}; txt(g, `runs ${lab.runs || 0} · imported ${lab.experiments_total || 0}`, 6, 40); txt(g, `last ${lab.last_batch || "–"}`.slice(0, 32), 6, 58, C.muted, "11px monospace"); }
    } else if (i === 1) {
      const e = done[0]; txt(g, "WALK-FORWARD FOLDS (OOS)", 6, 16, C.blue, "bold 12px monospace");
      if (e) { txt(g, (e.variant || e.family).slice(0, 30), 6, 34, C.text, "12px monospace");
        const fs = e.folds || []; const mx = Math.max(0.01, ...fs.map(f => Math.abs(f.ret || 0)));
        fs.forEach((f, k) => { const v = f.ret || 0, hgt = Math.abs(v) / mx * 46, x = 20 + k * 110; g.fillStyle = v >= 0 ? C.blue : C.red; g.fillRect(x, v >= 0 ? 100 - hgt : 100, 70, hgt);
          txt(g, `fold ${k + 1}: ${pct(v)}`, x - 6, 124, C.text, "11px monospace"); txt(g, `${f.trades ?? 0} tr · PF ${num(f.pf)}`, x - 6, 140, C.muted, "10px monospace"); });
        g.strokeStyle = "#ffffff30"; g.beginPath(); g.moveTo(10, 100); g.lineTo(250, 100); g.stroke(); }
    } else if (i === 2) {
      const e = done[0]; txt(g, "GATES · LAST RESULT", 6, 16, C.blue, "bold 12px monospace");
      Object.entries(e?.gates || {}).slice(0, 8).forEach(([k, v], j) => { txt(g, `${v.pass ? "✓" : "✗"} ${k}`.slice(0, 18), 6, 36 + j * 15, v.pass ? C.green : C.red, "11px monospace"); txt(g, `${typeof v.value === "number" ? num(v.value) : v.value} / ${v.threshold}`, 150, 36 + j * 15, C.muted, "11px monospace"); });
      if (!e) txt(g, "no result yet", 6, 50, C.dim);
    } else {
      txt(g, "FAMILY BANDIT (UCB)", 6, 16, C.blue, "bold 12px monospace");
      const fsx = Object.entries(rs.family_stats || {}); const mx = Math.max(0.01, ...fsx.map(([, v]) => v[1]));
      fsx.forEach(([f, [n, r]], j) => { txt(g, f.slice(0, 16), 6, 40 + j * 28, C.text, "11px monospace"); bar(g, 6, 45 + j * 28, 180, 7, r / mx, C.green); txt(g, `n=${n}`, 196, 52 + j * 28, C.muted, "11px monospace"); });
    }
    s.screen.tex.needsUpdate = true;
  });
  // --- whiteboard: the lab's real state
  { const g = board.g, c = board.c; g.fillStyle = "#f7f6f2"; g.fillRect(0, 0, c.width, c.height);
    const lab = rs.lab || {};
    g.fillStyle = "#1f3b73"; g.font = "bold 24px sans-serif"; g.fillText("Research lab — runs on GitHub Actions", 18, 34);
    g.font = "16px sans-serif"; g.fillStyle = "#333";
    g.fillText(`runs ${lab.runs || 0} · ${lab.cpus || "–"} CPUs · budget ${lab.budget_min || "–"} min · status ${lab.status || "–"}`, 18, 62);
    g.fillText(`experiments: ${rs.counts?.done || 0} done · ${rs.counts?.running || 0} running · ${rs.counts?.failed || 0} failed`, 18, 86);
    g.fillText("walk-forward → 2× costs → ±10% params → Monte Carlo → Deflated Sharpe", 18, 110);
    const gf = Object.entries(rs.gate_failures || {}).sort((a, b) => b[1] - a[1]).slice(0, 5), mx = Math.max(1, ...gf.map(x => x[1]));
    g.fillStyle = "#b03030"; g.font = "bold 15px sans-serif"; g.fillText("Most failed gates", 18, 140);
    gf.forEach(([k, v], j) => { g.fillStyle = "#b0303055"; g.fillRect(170, 128 + j * 24, 300 * v / mx, 16); g.fillStyle = "#333"; g.font = "14px sans-serif"; g.fillText(`${k} ×${v}`, 176, 141 + j * 24); });
    g.strokeStyle = "#1f3b73"; g.lineWidth = 2; g.strokeRect(500, 128, 140, 110); g.fillStyle = "#1f3b73"; g.font = "bold 13px sans-serif"; g.fillText("hypotheses", 512, 146);
    g.font = "12px sans-serif"; ["trend > breakout", "funding / basis?", "4h & 1d horizons", "maker entries"].forEach((h, j) => g.fillText("• " + h, 512, 168 + j * 18));
    board.tex.needsUpdate = true; }
  // --- market radar: universe on a trend × mean-reversion map
  { const [g, c] = clr(mapScr, "#06120e");
    const ang = t * 1.2; g.strokeStyle = "#1baf7a22"; for (let r = 30; r < 300; r += 40) { g.beginPath(); g.arc(120, 114, r, 0, Math.PI * 2); g.stroke(); }
    g.strokeStyle = "#1baf7a"; g.beginPath(); g.moveTo(120, 114); g.lineTo(120 + Math.cos(ang) * 105, 114 + Math.sin(ang) * 105); g.stroke();
    const mk = (S.market?.pairs || []).filter(m => m.data && m.data.trend_score !== undefined);
    const X0 = 250, Y0 = 30, PW = 280, PH = 170;
    g.strokeStyle = "#1baf7a55"; g.strokeRect(X0, Y0, PW, PH); txt(g, "trend →", X0 + PW - 60, Y0 + PH + 16, "#8fd9b6", "11px monospace"); txt(g, "↑ mean-revert", X0, Y0 - 8, "#8fd9b6", "11px monospace");
    if (mk.length) { const tx = mk.map(m => m.data.trend_score), ry = mk.map(m => m.data.revert_score); const [a0, a1] = [Math.min(...tx), Math.max(...tx)], [b0, b1] = [Math.min(...ry), Math.max(...ry)];
      mk.forEach(m => { const x = X0 + 8 + (m.data.trend_score - a0) / ((a1 - a0) || 1) * (PW - 16), y = Y0 + PH - 8 - (m.data.revert_score - b0) / ((b1 - b0) || 1) * (PH - 16);
        const vol = clamp((m.data.vol_annual || 0.5) * 3, 2, 6); g.fillStyle = (m.data.ret_30d || 0) >= 0 ? "#29d36a" : "#e66767"; g.beginPath(); g.arc(x, y, vol, 0, 7); g.fill();
        txt(g, m.pair.split("/")[0], x + 6, y + 3, "#d8f5e8", "10px monospace"); }); }
    txt(g, `UNIVERSE ${(rs.universe?.pairs || []).length} PAIRS · ${rs.universe?.source || ""}`, 12, 218, "#d8f5e8", "bold 13px monospace");
    mapScr.tex.needsUpdate = true; }
  // scanner desks: top trend / top mean-reversion pairs
  scanSeats.forEach((s, i) => { const [g] = clr(s.screen, "#06120e"); const key = i ? "revert_score" : "trend_score";
    txt(g, i ? "TOP MEAN-REVERSION" : "TOP TREND", 6, 16, "#29d36a", "bold 12px monospace");
    (S.market?.pairs || []).filter(m => m.data?.[key] !== undefined).sort((a, b) => b.data[key] - a.data[key]).slice(0, 7)
      .forEach((m, j) => { txt(g, m.pair.split("/")[0], 6, 36 + j * 17, C.text, "12px monospace"); bar(g, 80, 28 + j * 17, 120, 8, m.data[key], "#1baf7a"); txt(g, num(m.data[key], 2), 206, 36 + j * 17, C.muted, "11px monospace"); });
    s.screen.tex.needsUpdate = true; });
  // risk desk: last verdict
  { const [g] = clr(riskSeat.screen); const e = done[0]; txt(g, "VALIDATION DESK", 6, 16, C.amber, "bold 12px monospace");
    if (e) { const v = e.summary?.verdict || e.status; txt(g, (e.variant || e.family).slice(0, 30), 6, 36); txt(g, v.toUpperCase(), 6, 58, v === "validated" ? C.green : v === "exploratory" ? C.amber : C.red, "bold 16px monospace");
      txt(g, `DSR ${num(e.summary?.dsr)} · N trials ${e.summary?.n_trials ?? "–"}`, 6, 80, C.muted, "12px monospace"); txt(g, `WFE ${num(e.summary?.wfe)} · robust ${pct(e.summary?.robust_frac, 0)}`, 6, 98, C.muted, "12px monospace");
      const p = Object.values(e.gates || {}).filter(x => x.pass).length, n = Object.keys(e.gates || {}).length; bar(g, 6, 112, 244, 10, n ? p / n : 0, p === n ? C.green : C.amber); txt(g, `${p}/${n} gates`, 6, 140, C.text, "12px monospace"); }
    riskSeat.screen.tex.needsUpdate = true; }
  // learning desk
  { const [g] = clr(learnSeat.screen); txt(g, "LEARNINGS", 6, 16, "#9085e9", "bold 12px monospace"); const L = (S.ln?.learnings || []).filter(l => l.active).slice(0, 3);
    g.font = "11px monospace"; g.fillStyle = C.text; L.forEach((l, j) => wrap(g, "• " + l.insight, 6, 36 + j * 42, 244, 13, 3));
    if (!L.length) txt(g, "waiting for evidence…", 6, 40, C.dim, "12px monospace"); learnSeat.screen.tex.needsUpdate = true; }
  // CEO: goals + lifecycle funnel
  { const [g] = clr(ceoSeat.screen); txt(g, "GOALS", 6, 16, "#d55181", "bold 12px monospace");
    (S.goals?.goals || []).slice(0, 6).forEach((x, j) => { txt(g, x.title.slice(0, 26), 6, 34 + j * 21, C.text, "10px monospace"); bar(g, 6, 37 + j * 21, 200, 5, x.progress, x.progress >= 1 ? C.green : "#d55181"); txt(g, `${x.value}${x.unit === "%" ? "%" : ""}/${x.target}`, 210, 42 + j * 21, C.muted, "10px monospace"); });
    ceoSeat.screen.tex.needsUpdate = true;
    if (ceoSeat.screen.second) { const [g2] = clr(ceoSeat.screen.second); txt(g2, "STRATEGY FUNNEL", 6, 16, "#d55181", "bold 12px monospace");
      const cnt = {}; (S.strats?.strategies || []).forEach(x => cnt[x.stage] = (cnt[x.stage] || 0) + 1);
      ["exploratory", "exploration", "validated", "incubation", "production", "retired", "rejected"].forEach((k, j) => { const n = cnt[k] || 0; bar(g2, 100, 26 + j * 15, 100, 9, n / Math.max(1, ...Object.values(cnt)), k === "production" ? C.green : k === "rejected" || k === "retired" ? "#5a6372" : C.blue); txt(g2, k, 6, 34 + j * 15, C.muted, "10px monospace"); txt(g2, n, 206, 34 + j * 15, C.text, "10px monospace"); });
      ceoSeat.screen.second.tex.needsUpdate = true; } }
  // ops
  { const [g] = clr(sysScr, "#0d1117"); txt(g, "SYSTEM HEALTH", 12, 24, C.muted, "bold 16px monospace");
    const mem = (hl.heartbeats || []).find(h => h.service === "manager")?.detail?.mem_headroom_mb;
    const rows = [["bot", hl.bot_up ? "UP" : "DOWN", hl.bot_up], ["self-test", hl.selftest?.ok ? "PASS" : "–", !!hl.selftest?.ok], ["order test", hl.exec_test?.ok ? "PASS" : "–", !!hl.exec_test?.ok], ["mem headroom", mem ? mem + " MB" : "–", !mem || mem > 150], ["research", rs.mode === "remote" ? "GitHub lab" : "local", true]];
    (hl.heartbeats || []).forEach(h => rows.push([h.service, `${h.status} · ${h.age_s}s`, h.status !== "error" && ((h.age_s ?? 0) < 900 || h.detail?.remote)]));
    rows.slice(0, 8).forEach(([k, v, ok], i) => { txt(g, k, 12, 50 + i * 18, "#c3c2b7", "14px monospace"); txt(g, v, 210, 50 + i * 18, ok ? C.green : C.red, "14px monospace"); });
    sysScr.tex.needsUpdate = true;
    { const [g2] = clr(opsSeat.screen); txt(g2, "PROCESSES", 6, 16, C.muted, "bold 12px monospace");
      Object.entries(hl.supervisor?.processes || {}).forEach(([k, v], j) => { txt(g2, k, 6, 38 + j * 18, C.text, "12px monospace"); txt(g2, `${v.running ? "running" : "down"} · ${Math.round((v.uptime_s || 0) / 60)}m`, 110, 38 + j * 18, v.running ? C.green : C.red, "12px monospace"); });
      opsSeat.screen.tex.needsUpdate = true;
      if (opsSeat.screen.second) { const [g3] = clr(opsSeat.screen.second); txt(g3, "DISK / LAB", 6, 16, C.muted, "bold 12px monospace"); if (hl.disk) { bar(g3, 6, 26, 200, 8, hl.disk.used / hl.disk.total, C.blue); txt(g3, `${num(hl.disk.free / 1e9, 1)} GB free`, 6, 50, C.text, "12px monospace"); }
        txt(g3, `lab run ${(rs.lab || {}).run_id || "–"}`, 6, 72, C.text, "11px monospace"); txt(g3, `${(rs.lab || {}).status || "idle"}`, 6, 88, C.muted, "11px monospace"); opsSeat.screen.second.tex.needsUpdate = true; } } }
  drawMission(t);
  drawWall(t);
}
function drawMission(t) {
  const [g, c] = clr(missionScr, "#0a0f1a"), Gs = S.goals;
  const grd = g.createLinearGradient(0, 0, c.width, 0); grd.addColorStop(0, "#3987e522"); grd.addColorStop(1, "#d5518122"); g.fillStyle = grd; g.fillRect(0, 0, c.width, 56);
  txt(g, "MISSION", 24, 36, "#d55181", "bold 26px sans-serif");
  g.font = "18px sans-serif"; g.fillStyle = C.text; wrap(g, Gs?.mission || "loading…", 150, 34, 850, 20, 1);
  (Gs?.goals || []).slice(0, 8).forEach((x, j) => {
    const col = j % 2, row = Math.floor(j / 2), X = 24 + col * 500, Y = 84 + row * 68;
    txt(g, x.title, X, Y, C.text, "17px sans-serif");
    bar(g, X, Y + 14, 340, 16, x.progress, x.progress >= 1 ? C.green : x.warning ? C.red : "#3987e5", "#ffffff12");
    const shimmer = (t * 120 + j * 70) % 420 - 40; g.fillStyle = "#ffffff18"; g.fillRect(X + clamp(shimmer, 0, 340 * clamp(x.progress, 0, 1)), Y + 14, 14, 16);
    txt(g, `${x.value}${x.unit === "%" ? "%" : ""} / ${x.target}${x.unit === "%" ? "%" : ""}`, X + 352, Y + 28, C.muted, "bold 15px monospace");
  });
  missionScr.tex.needsUpdate = true;
}
function drawWall(t) {
  const {ov} = S, g = wall.g, c = wall.c;
  const grd = g.createLinearGradient(0, 0, 0, c.height); grd.addColorStop(0, "#0b1424"); grd.addColorStop(1, "#060a12"); g.fillStyle = grd; g.fillRect(0, 0, c.width, c.height);
  g.fillStyle = "#8d8c84"; g.font = "bold 22px monospace"; g.fillText("BYBIT DEMO · EQUITY", 24, 36);
  const pts = ov.equity.map(r => r.equity).filter(v => v > 0);
  if (pts.length > 1) {
    const lo = Math.min(...pts), hi = Math.max(...pts), pad = (hi - lo) * 0.12 || 1, X = i => 24 + i / (pts.length - 1) * 760, Y = v => 290 - (v - lo + pad) / (hi - lo + 2 * pad) * 220;
    g.strokeStyle = "#ffffff12"; for (let k = 0; k < 5; k++) { g.beginPath(); g.moveTo(24, 70 + k * 55); g.lineTo(784, 70 + k * 55); g.stroke(); }
    const area = g.createLinearGradient(0, 70, 0, 290); area.addColorStop(0, "#3987e555"); area.addColorStop(1, "#3987e500");
    g.beginPath(); pts.forEach((v, i) => i ? g.lineTo(X(i), Y(v)) : g.moveTo(X(i), Y(v))); g.lineTo(X(pts.length - 1), 290); g.lineTo(24, 290); g.fillStyle = area; g.fill();
    g.strokeStyle = "#3987e5"; g.lineWidth = 3.5; g.beginPath(); pts.forEach((v, i) => i ? g.lineTo(X(i), Y(v)) : g.moveTo(X(i), Y(v))); g.stroke();
    const lx = X(pts.length - 1), ly = Y(pts.at(-1)); g.fillStyle = "#7fb6ff"; g.beginPath(); g.arc(lx, ly, 5 + Math.sin(t * 4) * 1.5, 0, 7); g.fill();
    g.fillStyle = "#f0efec"; g.font = "bold 30px monospace"; g.textAlign = "right"; g.fillText(num(pts.at(-1), 0) + " USDT", 784, 36); g.textAlign = "left";
  } else { g.fillStyle = "#c3c2b7"; g.font = "22px monospace"; g.fillText("collecting equity snapshots…", 24, 170); }
  // right side: positions + events
  g.fillStyle = "#8d8c84"; g.font = "bold 18px monospace"; g.fillText("OPEN POSITIONS", 830, 36);
  ov.open_trades.slice(0, 5).forEach((p, k) => { g.fillStyle = p.profit_abs >= 0 ? "#7fb6ff" : "#ff8a8a"; g.font = "17px monospace"; g.fillText(`${p.is_short ? "SHORT" : "LONG "} ${p.pair.split(":")[0].padEnd(10)} ${p.profit_abs >= 0 ? "+" : ""}${num(p.profit_abs)}`, 830, 66 + k * 24); });
  if (!ov.open_trades.length) { g.fillStyle = "#5a6372"; g.font = "17px monospace"; g.fillText("none — waiting for signals", 830, 66); }
  const lab = S.rs?.lab || {}; g.fillStyle = "#8d8c84"; g.font = "bold 18px monospace"; g.fillText(`LATEST · GitHub lab ${lab.status === "start" ? "RUNNING" : lab.status || "idle"}`, 830, 200);
  (ov.events || []).slice(0, 4).forEach((e, k) => { g.fillStyle = "#c3c2b7"; g.font = "14px monospace"; g.fillText(`${e.ts.slice(11, 16)} ${e.message}`.slice(0, 50), 830, 226 + k * 22); });
  wall.tex.needsUpdate = true;
}

// ============================================================== department tags / HUD / panels
const tags = {};
for (const d of Object.values(departments)) {
  const el = document.createElement("div"); el.className = "tag glass";
  el.innerHTML = `<b><span class="dot"></span>${d.name}</b><i>…</i>`; el.onclick = () => focusDept(d.key);
  $("#labels").appendChild(el); tags[d.key] = el;
}
function setTag(key, info, status) {
  const d = departments[key]; if (!d || !tags[key]) return; d.info = info; d.status = status; tags[key].querySelector("i").textContent = info;
  const col = {good: "#0ca30c", warn: "#fab219", crit: "#d03b3b"}[status]; const dot = tags[key].querySelector(".dot"); dot.style.background = col; dot.style.color = col;
}
function applyData() {
  const {ov, rs, hl, ln} = S, bal = ov.balance || {}, pr = ov.profit || {};
  $("#hEq").textContent = num(bal.total_bot ?? bal.total, 0); $("#hEqS").textContent = ov.bot_up ? "bot running" : "BOT DOWN";
  $("#hPnl").innerHTML = pr.profit_closed_coin !== undefined ? signed(pr.profit_closed_coin) : "–"; $("#hPnlS").textContent = `${pr.closed_trade_count ?? 0} closed trades`;
  $("#hPos").textContent = ov.open_trades.length; const up = ov.open_trades.reduce((a, t) => a + (t.profit_abs || 0), 0);
  $("#hPosS").innerHTML = ov.open_trades.length ? `unrealised ${num(up)}` : "waiting for signals";
  const live = ov.manifest.sleeves.filter(s => s.stage !== "closing");
  $("#hSl").textContent = live.length; $("#hSlS").textContent = Object.entries(live.reduce((a, s) => (a[s.stage] = (a[s.stage] || 0) + 1, a), {})).map(([k, v]) => `${v} ${k}`).join(" · ") || "none";
  const running = rs.experiments.filter(e => e.status === "running");
  const lab = rs.lab || {};
  labActive = running.length > 0 || lab.status === "start" || lab.status === "scan";
  $("#hRs").textContent = rs.paused ? "paused" : labActive ? "GitHub lab ▶" : "idle"; $("#hRsS").textContent = `${rs.counts.done || 0} done · ${rs.counts.failed || 0} failed · ${lab.runs || 0} runs`;
  flowSpeed = labActive ? 0.05 : 0.015;
  setTag("cloud", labActive ? `running · ${lab.cpus || "?"} CPUs · ${running[0]?.progress?.stage || lab.status}`.slice(0, 46) : `idle · ${lab.runs || 0} runs · next run queued`, labActive ? "good" : "warn");
  const G = S.goals?.goals || []; if (G.length) setTag("mission", `${G.filter(x => x.progress >= 1).length}/${G.length} goals reached`, "good");
  const uni = rs.universe?.pairs?.length || 0;
  setTag("scanner", `${uni} pairs in universe`, uni >= 4 ? "good" : "warn");
  setTag("research", running.length ? `${running[0].family} · ${running[0].progress?.stage || ""}`.slice(0, 44) : `${rs.counts.done || 0} experiments done`, "good");
  const lastG = rs.experiments.find(e => e.gates)?.gates, gates = lastG ? Object.values(lastG) : [];
  lamps.forEach((l, i) => { const g = gates[i], c = !g ? 0x333333 : g.pass ? 0x2bd16a : 0xe0443c; l.material.color.setHex(c); l.material.emissive.setHex(c); l.material.emissiveIntensity = g ? 1.4 : 0; });
  const passed = gates.filter(g => g.pass).length;
  setTag("risk", lastG ? `last candidate ${passed}/${gates.length} gates` : "no candidate yet", lastG ? (passed === gates.length ? "good" : "warn") : "warn");
  setTag("trading", `${live.length} strategies · ${ov.open_trades.length} positions`, ov.bot_up ? "good" : "crit");
  setTag("learning", `${(ln.learnings || []).filter(l => l.active).length} active learnings`, "good");
  const hbs = hl.heartbeats || [], bad = hbs.filter(h => (h.age_s ?? 0) > 900 || h.status === "error");
  setTag("ops", `${hl.bot_up ? "bot up" : "bot DOWN"} · order test ${hl.exec_test?.ok ? "✓" : "–"}`, !hl.bot_up || bad.length ? "crit" : "good");
  setTag("ceo", `${live.length} live sleeves · kill-switch ${ov.kill_switch ? "ON" : "off"}`, ov.kill_switch ? "crit" : "good");
  // traders: active desks for live sleeves, others away
  traders.forEach((tr, i) => { const on = i < Math.max(live.length, 2); tr.root.visible = on; tr.bubble.style.display = on ? "" : "none"; });
  // books
  books.clear(); const nL = (ln.learnings || []).length;
  for (let i = 0; i < Math.min(nL + 6, 80); i++) {
    const sh = Math.floor(i / 26) % 3, row = Math.floor((i % 26) / 13), k = i % 13;
    const b = boxM(0.12, rand(0.36, 0.48), 0.28, new THREE.MeshStandardMaterial({color: pick([0x3987e5, 0xe66767, 0xfab219, 0x1baf7a, 0x9085e9, 0xd55181]), roughness: 0.7}), 12.1 + sh * 2.8 + k * 0.17, 0.55 + row * 0.6, 13.85);
    b.rotation.z = rand(-0.05, 0.05); books.add(b);
  }
  $("#track").textContent = (ov.events || []).slice().reverse().map(e => `[${e.ts.slice(11, 16)}] ${e.source}: ${e.message}`).join("     •     ") || "quiet";
  // events → scenes (skip history on first load except the latest few)
  const evs = (ov.events || []).slice().reverse();
  if (S.lastEventId === null) { S.lastEventId = evs.length ? evs.at(-1).id : 0; evs.slice(-3).forEach(e => feed(e.source, e.message.slice(0, 110))); }
  else for (const e of evs) if (e.id > S.lastEventId) { S.lastEventId = e.id; onEvent(e); }
  onTrades(ov.open_trades, live); watchProtection(ov.open_trades, live); S.first = false;
}
async function refresh() {
  try {
    const [ov, rs, hl, ln] = await Promise.all([api("/api/overview"), api("/api/research"), api("/api/health"), api("/api/learnings")]);
    Object.assign(S, {ov, rs, hl, ln}); applyData(); narrateLab();
  } catch (e) { $("#track").textContent = "data error: " + e.message; }
}
let lastSlow = 0;
async function refreshSlow(force = false) {
  if (!force && Date.now() - lastSlow < 55000) return; lastSlow = Date.now();
  try {
    const [goals, market, strats] = await Promise.all([api("/api/goals"), api("/api/market"), api("/api/strategies")]);
    Object.assign(S, {goals, market, strats}); renderGoals();
  } catch (e) { /* keep last */ }
  if (!S.ov) return;
  const pairs = [...new Set(S.ov.manifest.sleeves.filter(s => s.stage !== "closing").slice(0, 8).map(sl => sleevePair(sl, S.ov)))];
  for (const p of pairs) { try { const d = await api("/api/candles?limit=72&pair=" + encodeURIComponent(p)); if (d.candles?.length) S.candles[p] = {ts: Date.now(), rows: d.candles}; } catch (e) { /* ignore */ } }
}
function renderGoals() {
  const G = S.goals; if (!G) return;
  setTag("mission", `${G.goals.filter(x => x.progress >= 1).length}/${G.goals.length} goals reached`, "good");
  $("#goals").innerHTML = `<div class="h">Company goals · measured live</div>` + G.goals.map(x => `<div class="g"><div class="gt"><span title="${esc(x.note || "")}">${esc(x.title)}</span><b>${esc(x.value)}${x.unit === "%" ? "%" : ""}<i>/${esc(x.target)}${x.unit === "%" ? "%" : ""}</i></b></div><div class="gb"><i style="width:${Math.round(clamp(x.progress, 0, 1) * 100)}%;background:${x.progress >= 1 ? "var(--good)" : x.warning ? "var(--crit)" : "var(--blue)"}"></i></div></div>`).join("");
}

// ---- panels
function openPanel(key) {
  const {ov, rs, hl, ln} = S; if (!ov) return; const d = departments[key];
  let h = `<h2>${d.name}</h2><div class="sub">${esc(d.info)}</div>`;
  const staff = chars.filter(c => ({trading: "trader", research: "research", risk: "risk", learning: "learn", ops: "ops", scanner: "scanner", ceo: "ceo"})[key] === c.role && c.root.visible);
  if (staff.length) h += `<div class="sub">Team: ${staff.map(s => esc(s.name)).join(", ")}</div>`;
  if (key === "trading") {
    h += `<table><tr><th>Sleeve</th><th>Stage</th><th>Risk</th><th>Pairs</th></tr>${ov.manifest.sleeves.map(s => `<tr><td>${esc(s.id)}</td><td>${esc(s.stage)}</td><td>${pct(s.risk, 3)}</td><td>${esc(s.pairs.map(p => p.split("/")[0]).join(" "))}</td></tr>`).join("")}</table>`;
    h += `<h2 style="margin-top:14px">Open positions</h2><table><tr><th>Pair</th><th>Side</th><th>Entry</th><th>Stop</th><th>P&L</th></tr>${ov.open_trades.map(t => `<tr><td>${esc(t.pair)}</td><td>${t.is_short ? "short" : "long"}</td><td>${num(t.open_rate, 4)}</td><td>${num(t.stop_loss_abs, 4)}</td><td>${signed(t.profit_abs)}</td></tr>`).join("") || "<tr><td colspan=5>none</td></tr>"}</table>`;
  } else if (key === "research") {
    h += `<div class="kv"><span>load level</span><span>${rs.scale?.level ?? "default"}</span><span>done / failed</span><span>${rs.counts.done || 0} / ${rs.counts.failed || 0}</span></div>`;
    h += `<table><tr><th>Exp</th><th>Variant</th><th>Status</th><th>PF</th><th>Sharpe</th></tr>${rs.experiments.slice(0, 15).map(e => `<tr><td>${esc(e.id.slice(0, 8))}</td><td>${esc(e.family)}</td><td>${esc(e.summary?.verdict || e.status)}</td><td>${num(e.oos?.profit_factor)}</td><td>${num(e.oos?.sharpe)}</td></tr>`).join("")}</table>`;
  } else if (key === "risk") {
    const g = rs.experiments.find(e => e.gates)?.gates || {};
    h += `<table><tr><th>Gate</th><th>Value</th><th>Need</th><th></th></tr>${Object.entries(g).map(([k, v]) => `<tr><td>${esc(k)}</td><td>${v.value}</td><td>${v.threshold}</td><td>${v.pass ? "✓" : "✗"}</td></tr>`).join("") || "<tr><td colspan=4>no candidate yet</td></tr>"}</table>`;
  } else if (key === "learning") {
    h += (ln.learnings || []).slice(0, 20).map(l => `<p style="margin:6px 0">${l.active ? "●" : "○"} <b>${esc(l.scope)}:${esc(l.key)}</b> — ${esc(l.insight)}</p>`).join("") || "<p>No learnings yet — they come from live trades and research results.</p>";
  } else if (key === "scanner") { h += `<p style="font-family:var(--mono);font-size:12px">${esc((rs.universe?.pairs || []).join(", "))}</p>`;
  } else if (key === "ops") {
    h += `<table><tr><th>Service</th><th>Status</th><th>Heartbeat</th></tr>${(hl.heartbeats || []).map(x => `<tr><td>${esc(x.service)}</td><td>${esc(x.status)}</td><td>${x.age_s}s ago</td></tr>`).join("")}</table>`;
    h += `<div class="kv"><span>self-test</span><span>${hl.selftest?.ok ? "passed" : "–"}</span><span>order execution test</span><span>${hl.exec_test?.ok ? "passed" : "–"}</span><span>disk free</span><span>${hl.disk ? num(hl.disk.free / 1e9, 1) + " GB" : "–"}</span></div>`;
  } else if (key === "cloud") {
    const lab = rs.lab || {};
    h += `<p>All heavy research — hyperopt, walk-forward backtests, cost stress, robustness, Monte Carlo — runs on GitHub Actions runners. The trading server only receives the compact, gate-checked results.</p>`;
    h += `<div class="kv"><span>status</span><span>${esc(lab.status || "–")}</span><span>runs</span><span>${lab.runs || 0}</span><span>CPUs / budget</span><span>${lab.cpus || "–"} / ${lab.budget_min || "–"} min</span><span>experiments imported</span><span>${lab.experiments_total || 0}</span><span>last batch</span><span>${esc(lab.last_batch || "–")}</span><span>last import</span><span>${esc((lab.last_import || "–").slice(0, 16))}</span></div>`;
    h += `<a class="btn" target="_blank" rel="noopener" href="https://github.com/mailzastraze-ctrl/bybit-ai-trader/actions/workflows/research.yml">Open the runs on GitHub ↗</a>`;
  } else if (key === "mission") {
    const G = S.goals || {}; h += `<p>${esc(G.mission || "")}</p>` + (G.goals || []).map(x => `<div class="kv"><span>${esc(x.title)}</span><span>${esc(x.value)} / ${esc(x.target)}</span></div>`).join("");
    const rd = G.readiness || {};
    if (rd.checks) h += `<h2 style="margin-top:14px">Real-money readiness ${rd.passed}/${rd.total}</h2><div class="sub">${esc(rd.note || "")}</div><table><tr><th>Check</th><th>Now</th><th>Need</th><th></th></tr>${rd.checks.map(c => `<tr><td>${esc(c.title)}</td><td>${esc(c.value)}</td><td>${esc(c.need)}</td><td>${c.pass ? "✓" : "✗"}</td></tr>`).join("")}</table>`
      + `<div class="kv"><span>evidence P&L demo → realistic</span><span>${num(rd.evidence?.pnl_demo)} → ${num(rd.evidence?.pnl_real)}</span><span>slippage per fill</span><span>${pct(rd.slippage_per_side, 2)}</span></div>`;
    h += `<p style="color:var(--muted)">Drawdown from peak: ${pct(G.drawdown)} · all numbers come from the live registry, nothing is simulated.</p>`;
  } else if (key === "ceo") {
    h += `<div class="kv"><span>kill-switch</span><span>${ov.kill_switch ? "ACTIVE" : "off"}</span><span>entries</span><span>${ov.entries_paused ? "paused" : "enabled"}</span><span>closed trades</span><span>${ov.closed_count}</span><span>closed P&L</span><span>${num(ov.closed_pnl)}</span></div>`;
  }
  $("#pbody").innerHTML = h; $("#panel").style.display = "block"; $("#goals").style.display = "none";
}
function openPerson(p) {
  const act = p.locked ? "in the stand-up meeting" : p.task ? ({walk: "walking", sit: "sitting down", wait: p.pose, call: "busy"})[p.task.type] || p.task.type : p.seat ? "working at desk" : p.pose;
  $("#pbody").innerHTML = `<h2>${esc(p.name)}</h2><div class="sub">${roleName(p.role)}</div><div class="kv"><span>activity</span><span>${esc(act)}</span></div>${p.line ? `<p>“${esc(p.line)}”</p>` : ""}<button class="btn" id="follow">Follow ${esc(p.name)}</button>`;
  $("#panel").style.display = "block"; $("#follow").onclick = () => { follow = p; tour = false; };
}
$("#px").onclick = () => { $("#panel").style.display = "none"; $("#goals").style.display = ""; follow = null; };

// ============================================================== camera director
let camTween = null, follow = null, tour = false, tourT = 0;
function flyTo(pos, tgt, ms = 1600) { camTween = {p0: camera.position.clone(), t0: controls.target.clone(), p1: pos.clone(), t1: tgt.clone(), s: performance.now(), ms}; }
function focusDept(key) {
  const d = departments[key]; follow = null; tour = false;
  if (key === "cloud") flyTo(new THREE.Vector3(-5, 11, 3), new THREE.Vector3(-19, 18.5, -24));
  else if (key === "mission") flyTo(new THREE.Vector3(0, 4.5, 11), new THREE.Vector3(0, 3, 1.6));
  else flyTo(d.pos.clone().add(new THREE.Vector3(9, 11, 12)), d.pos.clone().setY(1));
  openPanel(key);
}
$("#bReset").onclick = () => { follow = null; tour = false; $("#bTour").classList.remove("on"); flyTo(HOME_POS, HOME_TGT); };
$("#bTour").onclick = () => { tour = !tour; follow = null; $("#bTour").classList.toggle("on", tour); };
renderer.domElement.addEventListener("pointerdown", () => { camTween = null; if (tour) { tour = false; $("#bTour").classList.remove("on"); } });

// picking: people (hover tag, click) and floor → department
const ray = new THREE.Raycaster(), mouse = new THREE.Vector2(); let hover = null;
const pickables = () => chars.filter(c => c.root.visible).map(c => c.root);
renderer.domElement.addEventListener("pointermove", e => {
  mouse.set((e.clientX / innerWidth) * 2 - 1, -(e.clientY / innerHeight) * 2 + 1); ray.setFromCamera(mouse, camera);
  const hit = ray.intersectObjects(pickables(), true)[0]; const p = hit?.object.userData.person || null;
  if (hover && hover !== p) hover.tagEl.style.display = "none"; hover = p; if (p) p.tagEl.style.display = "block";
  renderer.domElement.style.cursor = p ? "pointer" : "";
});
renderer.domElement.addEventListener("click", e => {
  mouse.set((e.clientX / innerWidth) * 2 - 1, -(e.clientY / innerHeight) * 2 + 1); ray.setFromCamera(mouse, camera);
  const hp = ray.intersectObjects(pickables(), true)[0]; if (hp) { openPerson(hp.object.userData.person); return; }
  const hit = ray.intersectObject(floor)[0]; if (!hit) return;
  let best = null, bd = 1e9; for (const d of Object.values(departments)) { const dd = d.pos.distanceTo(hit.point); if (dd < bd) { bd = dd; best = d; } }
  if (best && bd < 6) openPanel(best.key);
});

// ============================================================== main loop
const clock = new THREE.Clock(), v3 = new THREE.Vector3(), m4 = new THREE.Matrix4();
function project(p, el, dy = 0) {
  v3.copy(p); v3.y += dy; v3.project(camera);
  const vis = v3.z < 1 && Math.abs(v3.x) < 1.15 && Math.abs(v3.y) < 1.15; el.style.display = vis ? "" : "none";
  if (vis) el.style.transform = `translate(${(v3.x + 1) / 2 * innerWidth}px, ${(1 - v3.y) / 2 * innerHeight}px) translate(-50%, -100%)`;
}
let lastScreens = 0, introDone = false;
function tick() {
  const dt = Math.min(clock.getDelta(), 0.05), t = clock.elapsedTime, now = performance.now();
  // environment: day/night
  const d = new Date(), hr = d.getHours() + d.getMinutes() / 60, day = clamp(Math.sin((hr - 6.5) / 13 * Math.PI) * 1.4, 0, 1);
  scene.background.copy(SKY_NIGHT).lerp(SKY_DAY, day); scene.fog.color.copy(scene.background);
  sun.intensity = 0.25 + 2.0 * day; hemi.intensity = 0.45 + 0.5 * day; towerMat.emissiveIntensity = 0.9 * (1 - day) + 0.05;
  // props
  dishHead.parent.rotation.y += dt * 0.35; beacon.material.color.setHSL(0.42, 0.8, 0.35 + 0.25 * Math.sin(t * 4));
  leds.forEach((l, i) => l.visible = Math.sin(t * (2 + i % 5) + i * 1.7) > -0.5);
  coffeeLed.material.color.setHSL(0.03, 1, 0.45 + 0.15 * Math.sin(t * 2));
  for (let i = 0; i < NP; i++) { partT[i] = (partT[i] + dt * flowSpeed) % 1; const p = pipeline.getPointAt(partT[i]); m4.makeTranslation(p.x, p.y + Math.sin(t * 3 + i) * 0.04, p.z); parts.setMatrixAt(i, m4); }
  parts.instanceMatrix.needsUpdate = true;
  cloud.position.y = CLOUD_Y + Math.sin(t * 0.4) * 0.35; cloudRing.rotation.z += dt * (labActive ? 1.6 : 0.3); cloudRing2.rotation.z -= dt * (labActive ? 2.2 : 0.4);
  cloudCore.rotation.y += dt * (labActive ? 1.2 : 0.2); coreMat.color.setHSL(0.6, 0.75, labActive ? 0.55 + 0.12 * Math.sin(t * 5) : 0.35);
  beam.material.opacity = damp(beam.material.opacity, labActive ? 0.45 : 0.0, 2, dt); beamParts.visible = beam.material.opacity > 0.05;
  for (let i = 0; i < NB; i++) { beamT[i] = (beamT[i] + dt * 0.18) % 1; const bp = beamCurve.getPointAt(beamT[i]); m4.makeTranslation(bp.x, bp.y, bp.z); beamParts.setMatrixAt(i, m4); }
  beamParts.instanceMatrix.needsUpdate = true;
  for (let i = packets.length - 1; i >= 0; i--) { const pk = packets[i], k = (now - pk.s) / pk.ms; if (k >= 1) { scene.remove(pk.m); packets.splice(i, 1); continue; }
    pk.m.position.copy(pk.curve.getPoint(k)); pk.m.rotation.x += dt * 3; pk.m.rotation.y += dt * 2; }
  // people
  for (const c of chars) {
    if (!c.root.visible) continue;
    c.update(dt, t);
    if (c.bubbleUntil && now > c.bubbleUntil) { c.bubble.classList.remove("on"); c.bubbleUntil = 0; c.speaking = false; }
    project(c.root.position, c.bubble, 2.15); if (hover === c) project(c.root.position, c.tagEl, 2.0);
    if (c.emoteEl) { if (now > c.emoteUntil) c.emoteEl.style.display = "none"; else project(c.root.position, c.emoteEl, c.bubbleUntil ? 2.75 : 2.05); }
  }
  for (const dd of Object.values(departments)) project(dd.anchor, tags[dd.key]);
  if (now - lastScreens > 700) { drawAll(t); lastScreens = now; }
  // camera
  if (camTween) {
    const k = clamp((now - camTween.s) / camTween.ms, 0, 1), e = k < 0.5 ? 4 * k * k * k : 1 - Math.pow(-2 * k + 2, 3) / 2;
    camera.position.lerpVectors(camTween.p0, camTween.p1, e); controls.target.lerpVectors(camTween.t0, camTween.t1, e);
    if (k >= 1) { camTween = null; if (!introDone) introDone = true; }
  } else if (follow) {
    const tp = follow.root.position.clone().setY(1.2); controls.target.lerp(tp, 1 - Math.exp(-5 * dt));
    const want = tp.clone().add(new THREE.Vector3(2.6, 1.9, 3.3)); camera.position.lerp(want, 1 - Math.exp(-3 * dt));
  } else if (tour) {
    tourT += dt * 0.05; const r = 34, a = tourT * Math.PI * 2;
    camera.position.lerp(new THREE.Vector3(Math.sin(a) * r, 22 + Math.sin(tourT * 3) * 6, Math.cos(a) * r * 0.85), 1 - Math.exp(-1.2 * dt));
    controls.target.lerp(new THREE.Vector3(Math.sin(a * 2) * 6, 0.5, Math.cos(a * 3) * 4), 1 - Math.exp(-1 * dt));
  }
  controls.update(); renderer.render(scene, camera); requestAnimationFrame(tick);
}
addEventListener("resize", () => { camera.aspect = innerWidth / innerHeight; camera.updateProjectionMatrix(); renderer.setSize(innerWidth, innerHeight); });

// ============================================================== start
await refresh(); await refreshSlow(true);
setInterval(refresh, 12000); setInterval(() => refreshSlow(), 15000);
$("#loader").style.opacity = 0; setTimeout(() => $("#loader").remove(), 900);
flyTo(HOME_POS, HOME_TGT, 3200);
setTimeout(() => ceo.say("Morning, team. Demo account only — we earn trust with evidence, not hope.", 6500), 2600);
setTimeout(() => conversation(researchers[1], researchers[0], [[researchers[1], "Walk-forward fold two is running. Train on 300 days, test on the next 60."], [researchers[0], "Good. Remember: we only trust the out-of-sample numbers."]]), 9000);
tick();
window.__hq = {chars, follow: (i, instant) => { follow = chars[i]; tour = false; camTween = null;
  if (instant) { const tp = follow.root.position.clone().setY(1.2); controls.target.copy(tp); camera.position.copy(tp.clone().add(new THREE.Vector3(2.6, 1.9, 3.3))); } }};
window.__hqReady = true;
