// AI Trader HQ — a living 3D office driven by the real system state.
// Departments are real components; characters act out real events (research results,
// risk verdicts, lifecycle moves, trades, learnings, health) with dialogue built from data.
import * as THREE from "three";
import { OrbitControls } from "three/addons/controls/OrbitControls.js";
import { RoomEnvironment } from "three/addons/environments/RoomEnvironment.js";
import { GLTFLoader } from "three/addons/loaders/GLTFLoader.js";
import * as SkeletonUtils from "three/addons/utils/SkeletonUtils.js";
import { buildAtmosphere, buildSurroundings, tileTexture } from "./hq-architecture.js";
import { createInterior, curvedDisplay, officeGlass } from "./hq-interior.js";
import { deskLayout, prepareStaffClips } from "./hq-staff-motion.js";
import { Footsteps } from "./hq-footsteps.js";
import { officeNavigation, PERSON_CLEARANCE, PASSING_DISTANCE } from "./hq-navigation.js";
import { mergeGeometries } from "three/addons/utils/BufferGeometryUtils.js";
import { fittedProp, loadSurface, officeModels, staffBones } from "./hq-visual-assets.js";

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
const nativeScale = Math.min(devicePixelRatio, 1.6);
let renderScale = nativeScale, frameTime = 1 / 60, lastScaleChange = 0;
renderer.setPixelRatio(renderScale);
renderer.setSize(innerWidth, innerHeight);
renderer.shadowMap.enabled = true;
renderer.shadowMap.type = THREE.PCFShadowMap;
renderer.shadowMap.autoUpdate = false;
renderer.shadowMap.needsUpdate = true;
renderer.toneMapping = THREE.ACESFilmicToneMapping;
renderer.toneMappingExposure = 1.12;
renderer.outputColorSpace = THREE.SRGBColorSpace;
host.appendChild(renderer.domElement);

const scene = new THREE.Scene();
const pmrem = new THREE.PMREMGenerator(renderer);
const studio = new RoomEnvironment();
scene.environment = pmrem.fromScene(studio, 0.04).texture;
studio.dispose(); pmrem.dispose();
scene.environmentIntensity = 0.68;
const atmosphere = buildAtmosphere(scene);
const SKY_DAY = new THREE.Color(0x708790), SKY_NIGHT = new THREE.Color(0x253b4c);
scene.background = SKY_DAY.clone();
scene.fog = new THREE.Fog(scene.background, 65, 148);

const reducedMotion = matchMedia("(prefers-reduced-motion: reduce)");
const camera = new THREE.PerspectiveCamera(37, innerWidth / innerHeight, 0.1, 500);
const HOME_POS = new THREE.Vector3(17, 32, 43), HOME_TGT = new THREE.Vector3(-0.7, 0.78, -1.9);
const homePosition = () => HOME_POS.clone().multiplyScalar(clamp(1.45 / camera.aspect, 1, 2.1));
camera.position.copy(homePosition()).multiplyScalar(reducedMotion.matches ? 1 : 1.18);
const controls = new OrbitControls(camera, renderer.domElement);
controls.target.copy(HOME_TGT); controls.enableDamping = true; controls.dampingFactor = 0.08;
controls.maxPolarAngle = Math.PI * 0.46; controls.minDistance = 4; controls.maxDistance = 140;

const hemi = new THREE.HemisphereLight(0xd1e1fc, 0x47404a, 1.0); scene.add(hemi);
const sun = new THREE.DirectionalLight(0xd9eaff, 2.15);
sun.position.set(-18, 32, 16); sun.castShadow = true; sun.shadow.mapSize.setScalar(Math.min(innerWidth,innerHeight) < 650 ? 1024 : 2048);
Object.assign(sun.shadow.camera, {left: -28, right: 28, top: 24, bottom: -24, near: 3, far: 100});
sun.shadow.bias = -0.0004; sun.shadow.normalBias = 0.02;
scene.add(sun);
const fill = new THREE.DirectionalLight(0xffdab5, 0.61); fill.position.set(13, 18, -25); scene.add(fill);
const galleryLight = new THREE.PointLight(0xffc28b,22,14,2); galleryLight.position.set(-3.3,3.53,-8.65);
const screenBounce = new THREE.PointLight(0x85c3fa,15,10,2); screenBounce.position.set(2.1,2.70,-13.1);
scene.add(galleryLight,screenBounce);
const lobbyLight = new THREE.PointLight(0xffd8a7, 29, 17, 2);
lobbyLight.position.set(7, 4.7, 1.1); scene.add(lobbyLight);

// ============================================================== materials & textures
function canvasTex(w, h, draw, repeat) {
  const c = document.createElement("canvas"); c.width = w; c.height = h; draw(c.getContext("2d"), w, h);
  const t = new THREE.CanvasTexture(c); t.colorSpace = THREE.SRGBColorSpace; t.anisotropy = 4;
  if (repeat) { t.wrapS = t.wrapT = THREE.RepeatWrapping; t.repeat.set(...repeat); }
  return t;
}
const woodTex = canvasTex(384, 128, (g, w, h) => {
  g.fillStyle = "#725241"; g.fillRect(0, 0, w, h);
  for (let i = 0; i < 220; i++) {
    const y = (i * 13.67) % h, curve = Math.sin(i * 7.16) * 6;
    g.strokeStyle = i % 3 ? "#3d29212b" : "#dbc4a620";
    g.beginPath(); g.moveTo(0, y); g.bezierCurveTo(w * 0.35, y + curve, w * 0.66, y - curve, w, y); g.stroke();
  }
});
const carpetTex = (hex) => canvasTex(128, 128, (g, w, h) => {
  g.fillStyle = hex; g.fillRect(0, 0, w, h);
  for (let y = 1; y < h; y += 2) {
    for (let x = (y % 4); x < w; x += 2) {
      g.fillStyle = Math.sin((y * 53 + x * 68) * 7.04) > 0 ? "#f1e8d913" : "#09101924";
      g.fillRect(x, y, 2, 1);
    }
  }
}, [7, 7]);
const M = {
  floor: new THREE.MeshStandardMaterial({map: tileTexture(canvasTex), roughness: 0.45, metalness: 0.08}),
  wall: new THREE.MeshStandardMaterial({color: 0x2f4152, roughness: 0.61, metalness: 0.18}),
  wallDark: new THREE.MeshStandardMaterial({color: 0x182a3a, roughness: 0.76}),
  deskTop: new THREE.MeshStandardMaterial({color: 0x958a79, roughness: 0.57, metalness: 0.035}),
  deskWood: new THREE.MeshStandardMaterial({map: woodTex, roughness: 0.51}),
  metal: new THREE.MeshStandardMaterial({color: 0x7d9ba6, roughness: 0.34, metalness: 0.72}),
  black: new THREE.MeshStandardMaterial({color: 0x15202b, roughness: 0.46, metalness: 0.29}),
  chair: new THREE.MeshStandardMaterial({color: 0x283a4a, roughness: 0.76}),
  glass: officeGlass(),
  frame: new THREE.MeshStandardMaterial({color: 0x475d70, roughness: 0.43, metalness: 0.68}),
  plantPot: new THREE.MeshStandardMaterial({color: 0x899fa5, roughness: 0.68}),
  leaf: new THREE.MeshStandardMaterial({color: 0x2b6151, roughness: 0.64}),
  leaf2: new THREE.MeshStandardMaterial({color: 0x518467, roughness: 0.53}),
  sofa: new THREE.MeshStandardMaterial({color: 0x456070, roughness: 0.85}),
  rack: new THREE.MeshStandardMaterial({color: 0x223140, roughness: 0.44, metalness: 0.56}),
  paper: new THREE.MeshStandardMaterial({color: 0xdfd4bb, roughness: 0.9}),
  brass: new THREE.MeshStandardMaterial({color: 0x97826b, roughness: 0.29, metalness: 0.79}),
  warmLight: new THREE.MeshBasicMaterial({color: 0xffd6a8, toneMapped: false}),
  coolLight: new THREE.MeshBasicMaterial({color: 0x84d7e3, toneMapped: false}),
};
loadSurface(M.floor, "terrazzo", 9, 6, 0x888992, 0.15);
loadSurface(M.deskWood, "oak", 1, 1, 0xcbbba5, 0.23);
const [planterAsset, sofaAsset] = await Promise.all([officeModels.planter, officeModels.sofa]);
function at(o, x, y, z) { o.position.set(x, y, z); return o; }
function mesh(geo, mat, cast = true, recv = true) { const m = new THREE.Mesh(geo, mat); m.castShadow = cast; m.receiveShadow = recv; return m; }
function boxM(w, h, d, mat, x = 0, y = 0, z = 0) {
  const m = mesh(new THREE.BoxGeometry(w, h, d), mat, Math.min(w, h, d) >= 0.04);
  m.position.set(x, y, z); return m;
}
function rbox(w, h, d, r, mat) { // rounded box via extruded rounded rect
  r = Math.min(r, w * 0.49, h * 0.49);
  const s = new THREE.Shape(), x = -w / 2, y = -h / 2;
  s.moveTo(x + r, y); s.lineTo(x + w - r, y); s.quadraticCurveTo(x + w, y, x + w, y + r); s.lineTo(x + w, y + h - r);
  s.quadraticCurveTo(x + w, y + h, x + w - r, y + h); s.lineTo(x + r, y + h); s.quadraticCurveTo(x, y + h, x, y + h - r);
  s.lineTo(x, y + r); s.quadraticCurveTo(x, y, x + r, y);
  const g = new THREE.ExtrudeGeometry(s, {depth: d - 2 * Math.min(r, d / 2.2), bevelEnabled: true, bevelThickness: Math.min(r, d / 2.2), bevelSize: Math.min(r, d / 2.2) * 0.9, bevelSegments: 3, curveSegments: 6});
  g.center(); return mesh(g, mat);
}

// ============================================================== building
const W = 44, D = 30; // interior x ∈ [-22,22], z ∈ [-15,15]
const floor = mesh(new THREE.BoxGeometry(W, 0.3, D), M.floor, false, true); floor.position.y = -0.15; scene.add(floor);
const cityMaterials = buildSurroundings(scene, W, D, canvasTex);
const interior = createInterior(scene,M,boxM,rbox,batchSolids,canvasTex);

// window walls (north z=-15, west x=-22) with mullions and glass; low walls elsewhere (cut-away)
function windowWall(len, axis, at) {
  const g = new THREE.Group();
  g.add(boxM(len, 0.62, 0.25, M.wall, 0, 0.31, 0));
  g.add(boxM(len, 0.26, 0.48, M.frame, 0, 3.44, 0));
  const pane = mesh(new THREE.BoxGeometry(len, 2.7, 0.04), M.glass, false, false); pane.position.y = 1.96; g.add(pane);
  const bays = Math.ceil(len / 2.8);
  for (let i = 0; i <= bays; i++) {
    const post = i % 4 === 0 ? 0.18 : 0.043;
    g.add(boxM(post, 2.7, post + 0.065, M.frame, -len / 2 + i * len / bays, 1.96, 0));
  }
  g.add(boxM(len, 0.064, 0.25, M.metal, 0, 0.65, 0));
  g.add(boxM(len, 0.035, 0.19, M.black, 0, 0.085, 0.15));
  g.add(boxM(len - 0.25, 0.025, 0.035, M.warmLight, 0, 3.30, 0.215));
  g.add(boxM(len,0.033,0.25,M.brass,0,0.604,0.088));
  batchSolids(g,g.children.filter(child => child.material !== M.glass));
  if (axis === "x") g.position.set(0, 0, at); else { g.rotation.y = Math.PI / 2; g.position.set(at, 0, 0); }
  scene.add(g); return g;
}
windowWall(W, "x", -D / 2); windowWall(D, "z", -W / 2);
scene.add(boxM(W, 0.22, 0.28, M.wall, 0, 0.11, D / 2), boxM(0.28, 0.22, D, M.wall, W / 2, 0.11, 0));
scene.add(boxM(W, 0.026, 0.04, M.coolLight, 0, 0.224, D / 2), boxM(0.04, 0.026, D, M.coolLight, W / 2, 0.224, 0));

// ============================================================== navigation
const nav = officeNavigation(W,D);
const block = nav.add;
function blockObj(obj, pad = 0.06) {
  obj.updateWorldMatrix(true,true);
  const box = new THREE.Box3().setFromObject(obj);
  block(box.min.x-pad,box.min.z-pad,box.max.x+pad,box.max.z+pad);
}
block(-W/2,-D/2,W/2,-D/2+0.3);
block(-W/2,-D/2,-W/2+0.3,D/2);
const findPath = nav.route;
const rugs = [];
function groundAt(x,z) {
  return rugs.some(r => Math.abs(x-r.x) < r.halfWidth && Math.abs(z-r.z) < r.halfDepth) ? 0.025 : 0;
}

// ============================================================== screens (live canvases)
const screens = [];
function screen(w, h, pw = 256, ph = 160) {
  const c = document.createElement("canvas"); c.width = pw; c.height = ph;
  const tex = new THREE.CanvasTexture(c); tex.colorSpace = THREE.SRGBColorSpace; tex.anisotropy = 4;
  const m = new THREE.Mesh(new THREE.PlaneGeometry(w, h), new THREE.MeshBasicMaterial({map: tex, toneMapped: false}));
  const s = {c, g: c.getContext("2d"), tex, mesh: m, draw: null}; screens.push(s); return s;
}
function drawSpark(g, x, y, w, h, pts, color) {
  if (pts.length < 2) return; const lo = Math.min(...pts), hi = Math.max(...pts), r = hi - lo || 1;
  g.strokeStyle = color; g.lineWidth = 2; g.beginPath();
  pts.forEach((v, i) => { const px = x + i / (pts.length - 1) * w, py = y + h - (v - lo) / r * h; i ? g.lineTo(px, py) : g.moveTo(px, py); }); g.stroke();
}

// ============================================================== furniture
const UP_AXIS = new THREE.Vector3(0, 1, 0);
const seats = {};
const deskSolids = [];
// Furniture shares materials. Batch the rigid pieces while keeping screens and
// moving chairs addressable; across the floor, hundreds of submissions become a few.
function batchSolids(parent, pieces) {
  parent.updateWorldMatrix(true, false);
  const inverse = parent.matrixWorld.clone().invert(), groups = new Map();
  for (const piece of pieces) {
    const key = [piece.material.uuid, piece.castShadow, piece.receiveShadow].join("/");
    if (!groups.has(key)) groups.set(key, []);
    groups.get(key).push(piece);
  }
  for (const group of groups.values()) {
    if (group.length < 2) continue;
    const parts = group.map(piece => {
      piece.updateWorldMatrix(true, false);
      const g = piece.geometry.index ? piece.geometry.toNonIndexed() : piece.geometry.clone();
      return g.applyMatrix4(new THREE.Matrix4().multiplyMatrices(inverse, piece.matrixWorld));
    });
    const combined = mergeGeometries(parts);
    parts.forEach(part => part.dispose());
    if (!combined) continue;
    const first = group[0], solid = mesh(combined, first.material, first.castShadow, first.receiveShadow);
    group.forEach(part => part.removeFromParent()); parent.add(solid);
  }
}
M.chair.map = carpetTex("#39434a");
M.chair.map.repeat.set(1, 2);
M.chair.color.setHex(0xacaeaf);
const keyboardTex = canvasTex(256, 96, (g, w, h) => {
  g.fillStyle = "#121d26"; g.fillRect(0, 0, w, h);
  for (let row = 0; row < 5; row++) {
    for (let col = 0; col < 14; col++) {
      const x = 10 + col * 17, y = 7 + row * 17;
      g.fillStyle = row === 4 ? "#385360" : "#2d3e4b";
      g.fillRect(x, y, 14, 13);
      g.fillStyle = "#91aec0"; g.fillRect(x + 5, y + 4, 3, 1);
    }
  }
  g.fillStyle = "#324c5b"; g.fillRect(78, 75, 99, 13);
});
const keyboardMat = new THREE.MeshStandardMaterial({map: keyboardTex, roughness: 0.7});
const softDisc = canvasTex(64, 64, (g, w, h) => {
  const glow = g.createRadialGradient(w / 2, h / 2, 0, w / 2, h / 2, w / 2);
  glow.addColorStop(0, "#ffffff"); glow.addColorStop(0.33, "#ffffff7a"); glow.addColorStop(1, "#ffffff00");
  g.fillStyle = glow; g.fillRect(0, 0, w, h);
});
const poolGeo = new THREE.PlaneGeometry(1, 1);
const workstationShadows = [];
function lightPool(color, x, y, z, w, h, opacity) {
  const glow = new THREE.Mesh(poolGeo, new THREE.MeshBasicMaterial({map: softDisc, color, transparent: true,
    depthWrite: false, opacity, blending: THREE.AdditiveBlending, toneMapped: false, polygonOffset: true, polygonOffsetFactor: -3}));
  glow.rotation.x = -Math.PI / 2; glow.position.set(x, y, z); glow.scale.set(w, h, 1);
  scene.add(glow);
  return glow;
}
let chairTemplate;
function chair() {
  if (chairTemplate) return chairTemplate.clone();
  const g = new THREE.Group();
  const cushion = rbox(0.50, 0.46, 0.068, 0.095, M.chair);
  cushion.rotation.x = -Math.PI / 2; cushion.position.y = 0.484; g.add(cushion);
  const backGeo = new THREE.PlaneGeometry(1, 1, 16, 16);
  const vertices = backGeo.attributes.position;
  for (let i = 0; i < vertices.count; i++) {
    const u = vertices.getX(i) * 2, v = vertices.getY(i) + 0.5;
    const width = 0.219 + 0.025 * Math.sin(v * Math.PI) - 0.033 * v ** 3;
    vertices.setXYZ(i, u * width, 0.56 + v * 0.50 - 0.032 * u*u * v**4,
      0.184 + v * 0.095 - 0.065 * u*u - 0.025 * Math.sin(v * 2 * Math.PI));
  }
  backGeo.computeVertexNormals();
  const textile = M.chair.clone(); textile.side = THREE.DoubleSide;
  g.add(mesh(backGeo, textile));
  const lumbar = rbox(0.30, 0.107, 0.039, 0.046, M.frame);
  lumbar.position.set(0, 0.71, 0.234); g.add(lumbar);
  g.add(boxM(0.051, 0.36, 0.044, M.frame, 0, 0.58, 0.238));
  const piston = mesh(new THREE.CylinderGeometry(0.028, 0.035, 0.34, 12), M.metal);
  piston.position.y = 0.25; g.add(piston);
  for (const x of [-0.259, 0.259]) {
    g.add(boxM(0.028, 0.14, 0.032, M.frame, x, 0.55, 0.039));
    const pad = rbox(0.059, 0.027, 0.205, 0.015, M.black);
    pad.position.set(x, 0.621, 0.018); g.add(pad);
  }
  for (let i = 0; i < 5; i++) {
    const a = i / 5 * Math.PI * 2;
    const leg = boxM(0.30, 0.028, 0.037, M.metal, Math.cos(a) * 0.15, 0.076, Math.sin(a) * 0.15);
    leg.rotation.y = -a; g.add(leg);
    const wheel = mesh(new THREE.CylinderGeometry(0.036, 0.036, 0.048, 12), M.black, false);
    wheel.rotation.set(Math.PI / 2, 0, -a); wheel.position.set(Math.cos(a) * 0.283, 0.036, Math.sin(a) * 0.283); g.add(wheel);
  }
  batchSolids(g, g.children.slice()); chairTemplate = g;
  return g.clone();
}
function plant(x, z, s = 1) {
  const g = new THREE.Group();
  const model = fittedProp(planterAsset, 1.12 * s, 1.12 * s, 1.45 * s);
  if (model) {
    g.add(model);
    g.position.set(x, 0, z); g.rotation.y = (x + z) * 0.3; scene.add(g);
    block(x - 0.28 * s, z - 0.28 * s, x + 0.28 * s, z + 0.28 * s);
    return g;
  }
  const pot = mesh(new THREE.CylinderGeometry(0.22 * s, 0.17 * s, 0.42 * s, 16), M.plantPot); pot.position.y = 0.21 * s; g.add(pot);
  for (let i = 0; i < 9; i++) {
    const leaf = mesh(new THREE.SphereGeometry(0.16 * s, 8, 6), i % 2 ? M.leaf : M.leaf2);
    const a = i / 9 * Math.PI * 2; leaf.position.set(Math.cos(a) * 0.14 * s, (0.6 + Math.random() * 0.5) * s, Math.sin(a) * 0.14 * s);
    leaf.scale.set(1, 1.6, 0.6); leaf.rotation.set(rand(-.4, .4), a, rand(-.4, .4)); g.add(leaf);
  }
  g.position.set(x, 0, z); scene.add(g); blockObj(pot, 0.1); return g;
}
function desk(name, x, z, rot = 0, opts = {}) {
  const g = new THREE.Group(), displayMounts = [];
  const activeConsole = opts.trade || name.startsWith("lab");
  workstationShadows.push([x, z, rot]);
  const top = rbox(1.6, 0.80, 0.046, activeConsole ? 0.112 : 0.048, opts.dark ? M.deskWood : M.deskTop);
  top.rotation.x = -Math.PI / 2; top.position.y = 0.733; g.add(top);
  g.add(boxM(1.54, 0.025, 0.68, M.frame, 0, 0.699, 0));
  g.add(boxM(1.46, 0.012, 0.021, opts.dark ? M.brass : M.metal, 0, 0.705, 0.313));
  for (const dx of [-0.72, 0.72]) {
    const column = boxM(0.068,0.64,0.108,M.black,dx,0.365,0.06);
    column.rotation.x = 0.13; g.add(column);
    g.add(boxM(0.112,0.036,0.58,M.frame,dx,0.039,0.028));
    g.add(boxM(0.082,0.020,0.052,M.black,dx,0.014,-0.20));
    g.add(boxM(0.082,0.020,0.052,M.black,dx,0.014,0.246));
  }
  g.add(boxM(1.38, 0.145, 0.033, M.black, 0, 0.60, 0.27));
  g.add(boxM(1.34,0.012,0.008,M.brass,0,0.645,0.291));
  function monitor(w, h, posX, posY, posZ, angle) {
    const mount = new THREE.Group();
    mount.position.set(posX, posY, posZ); mount.rotation.y = angle;
    const curve = activeConsole && w > 0.7 ? 0.036 : 0;
    if (curve) {
      mount.add(mesh(curvedDisplay(w+0.025,h+0.025,0.042,-curve),M.black));
    } else {
      mount.add(rbox(w+0.026,h+0.026,0.042,0.018,M.black));
    }
    const rear = rbox(w*0.61,h*0.41,0.019,0.028,M.frame);
    rear.position.z = 0.024; mount.add(rear);
    mount.add(boxM(w*0.43,0.009,0.010,M.metal,0,0.049,0.036));
    mount.add(boxM(0.012,0.008,0.008,M.coolLight,w*0.40,-h*0.469,-0.021-curve*0.64));
    const display = screen(w,h);
    if (curve) {
      display.mesh.geometry.dispose();
      display.mesh.geometry = curvedDisplay(w,h,0,curve * (w / (w+0.025))**2);
    }
    display.mesh.position.z = -0.024; display.mesh.rotation.y = Math.PI;
    displayMounts.push([posX + Math.sin(angle)*0.052,posY - 0.016,posZ + Math.cos(angle)*0.052]);
    mount.add(display.mesh); g.add(mount);
    return display;
  }
  const scr = monitor(opts.second ? 0.72 : 0.82, 0.40, opts.second ? -0.19 : 0, 1.125, 0.21, 0);
  if (opts.second) scr.second = monitor(0.49,0.31,0.455,1.08,0.14,-0.32);
  interior.consoleStand(g,displayMounts,opts.second);
  const keyboard = new THREE.Mesh(new THREE.PlaneGeometry(0.43, 0.15), keyboardMat);
  g.add(boxM(0.77, 0.008, 0.29, M.chair, -0.040, 0.762, deskLayout.keyboardZ));
  g.add(boxM(0.444, 0.012, 0.155, M.black, 0.018, 0.772, deskLayout.keyboardZ));
  keyboard.position.set(0.018, 0.780, deskLayout.keyboardZ); keyboard.rotation.x = -Math.PI / 2; g.add(keyboard);
  const mouse = mesh(new THREE.SphereGeometry(1, 12, 8), M.black, false, false);
  mouse.scale.set(0.036, 0.018, 0.066); mouse.position.set(deskLayout.mouseX, 0.776, deskLayout.keyboardZ - 0.008); g.add(mouse);
  const number = (Math.round((x+22)*3.3) + Math.round((z+15)*2.7)) % 12;
  interior.dressDesk(g,number);
  g.traverse(o => { if (o.isMesh && o !== scr.mesh && o !== scr.second?.mesh) deskSolids.push(o); });
  const ch = chair(); ch.position.set(0, deskLayout.floorY, deskLayout.seatZ); ch.rotation.y = Math.PI; g.add(ch);
  g.position.set(x, 0, z); g.rotation.y = rot; scene.add(g);
  blockObj(top, 0.1);
  const mark = (x, z) => new THREE.Vector3(x, 0, z).applyAxisAngle(UP_AXIS, rot).add(g.position);
  const seatPos = mark(0, deskLayout.feetZ), dock = mark(0, deskLayout.feetZ - deskLayout.pullback);
  const approach = mark(1.35, -0.97);
  const chairBack = mark(0,deskLayout.seatZ - deskLayout.pullback - 0.31);
  const chairFront = mark(0,deskLayout.seatZ + 0.30);
  block(Math.min(chairFront.x,chairBack.x) - 0.30*Math.abs(Math.cos(rot)),
    Math.min(chairFront.z,chairBack.z) - 0.30*Math.abs(Math.sin(rot)),
    Math.max(chairFront.x,chairBack.x) + 0.30*Math.abs(Math.cos(rot)),
    Math.max(chairFront.z,chairBack.z) + 0.30*Math.abs(Math.sin(rot)),ch);
  seats[name] = {pos: seatPos, dock, approach, face: rot, desk: g, screen: scr, chair: ch, taken: null};
  return seats[name];
}
function rug(x, z, width, depth, hex, accent) {
  rugs.push({x,z,halfWidth:width/2,halfDepth:depth/2});
  const fabric = canvasTex(256,256,(ctx,size) => {
    ctx.fillStyle = hex; ctx.fillRect(0,0,size,size);
    for (let row=0; row<4; row++) for (let col=0; col<4; col++) {
      const left = col*64, top = row*64, turned = (row+col)%2;
      ctx.fillStyle = (row*7+col)%3 ? "#e6e5ec08" : "#09101915";
      ctx.fillRect(left,top,64,64);
      for (let line=1; line<64; line+=3) {
        ctx.fillStyle = line%5 ? "#eef1ff07" : "#060c1824";
        if (turned) ctx.fillRect(left+line,top,1,64);
        else ctx.fillRect(left,top+line,64,1);
      }
      ctx.fillStyle = "#11151c45";
      ctx.fillRect(left,top,64,1); ctx.fillRect(left,top,1,64);
    }
  }, [Math.round(width/2.15),Math.round(depth/2.15)]);
  const carpet = new THREE.MeshStandardMaterial({map:fabric,roughness:0.95});
  const tile = mesh(new THREE.BoxGeometry(width,0.025,depth),carpet,false,true);
  tile.position.set(x,0.0125,z); scene.add(tile);

  const trim = new THREE.MeshStandardMaterial({color:accent,roughness:0.52,metalness:0.55});
  trim.color.multiplyScalar(0.37);
  const rails = [];
  for (const side of [-1,1]) {
    rails.push(boxM(width-0.06,0.005,0.023,trim,x,0.026,z+side*(depth/2-0.025)));
    rails.push(boxM(0.023,0.005,depth-0.06,trim,x+side*(width/2-0.025),0.026,z));
  }
  scene.add(...rails); batchSolids(scene,rails);
}
const frostedGlass = new THREE.MeshBasicMaterial({color:0x9eb8c4, transparent:true, opacity:0.32, depthWrite:false});
function glassWall(x0, z0, x1, z1) {
  const len = Math.hypot(x1 - x0, z1 - z0), g = new THREE.Group();
  const pane = mesh(new THREE.BoxGeometry(len, 2.5, 0.04), M.glass, false, false); pane.position.y = 1.25; g.add(pane);
  g.add(boxM(len,0.055,0.090,M.black,0,2.5,0),boxM(len,0.079,0.105,M.frame,0,0.04,0));
  g.add(boxM(len-0.04,0.011,0.015,M.brass,0,2.479,0.052));
  for (const y of [1.03,1.12]) {
    const tape = boxM(len-0.12,0.012,0.005,frostedGlass,0,y,0.023);
    tape.receiveShadow = false; g.add(tape);
  }
  for (const x of [-len / 2, len / 2]) g.add(boxM(0.048, 2.5, 0.062, M.frame, x, 1.25, 0));
  g.position.set((x0 + x1) / 2, 0, (z0 + z1) / 2); g.rotation.y = -Math.atan2(z1 - z0, x1 - x0); scene.add(g);
  block(x0 - 0.1, z0 - 0.1, x1 + 0.1, z1 + 0.1);
}
const doors = [];
function slidingDoors(x, z, width, rot = 0) {
  const doorway = new THREE.Group(), height = 2.48;
  doorway.position.set(x, 0, z); doorway.rotation.y = rot;
  doorway.add(boxM(width + 0.1, 0.115, 0.18, M.frame, 0, height + 0.047, 0));
  doorway.add(boxM(width + 0.1, 0.023, 0.16, M.brass, 0, 0.025, 0));
  for (const side of [-1, 1]) doorway.add(boxM(0.081, height, 0.12, M.frame, side * (width / 2 + 0.016), height / 2, 0));
  const panels = [-1, 1].map(side => {
    const panel = new THREE.Group(), length = width / 2 - 0.047;
    panel.position.set(side * width / 4, 0, 0.052);
    panel.add(mesh(new THREE.BoxGeometry(length, height - 0.10, 0.021), M.glass, false, false));
    panel.children[0].position.y = height / 2;
    panel.add(boxM(length, 0.04, 0.053, M.frame, 0, height - 0.037, 0));
    for (const edge of [-1, 1]) panel.add(boxM(0.032, height - 0.09, 0.044, M.frame, edge * length / 2, height / 2, 0));
    panel.add(boxM(0.025, 0.29, 0.024, M.brass, -side * (length / 2 - 0.074), 1.19, 0.028));
    doorway.add(panel);
    return panel;
  });
  // Even when fully open the leaves occupy the outer halves of the doorway.
  // Route to the actual clear aperture, rather than through the leaf pockets.
  const aperture = width*0.24 + 0.02;
  for (const side of [-1,1]) {
    const sweep = at(new THREE.Object3D(),side*(aperture + width/2)*0.5,0,0.052);
    doorway.add(sweep); sweep.updateWorldMatrix(true,false);
    const position = sweep.getWorldPosition(new THREE.Vector3());
    const length = (width/2-aperture)/2;
    const hx = Math.abs(Math.cos(rot))*length + Math.abs(Math.sin(rot))*0.028;
    const hz = Math.abs(Math.sin(rot))*length + Math.abs(Math.cos(rot))*0.028;
    block(position.x-hx,position.z-hz,position.x+hx,position.z+hz); doorway.remove(sweep);
  }
  doors.push({x, z, width, rotation:rot, panels, open:0, waiting:new Map()});
  scene.add(doorway);
}
function doorClear(x,z,radius) {
  for (const door of doors) {
    const dx = x-door.x, dz = z-door.z;
    if (Math.abs(dx) > 2.1 || Math.abs(dz) > 2.1) continue;
    const co = Math.cos(door.rotation), si = Math.sin(door.rotation);
    const across = Math.abs(co*dx - si*dz), depth = Math.abs(si*dx + co*dz - 0.052);
    if (depth > radius + 0.025 || across > door.width/2 + radius) continue;
    const leafGap = door.width*door.open*0.24 + 0.018;
    if (across + Math.sqrt(Math.max(0,radius*radius-Math.max(0,depth-0.025)**2)) > leafGap) return false;
  }
  return true;
}
function doorLocal(door,pos) {
  const x = pos.x-door.x, z = pos.z-door.z, co = Math.cos(door.rotation), si = Math.sin(door.rotation);
  return {along:co*x-si*z, side:si*x+co*z-0.052};
}
function approachingDoor(actor,path) {
  for (const door of doors) {
    const at = doorLocal(door,actor.pos);
    if (Math.abs(at.side) > 2.75 || Math.abs(at.along) > door.width/2+1.8) continue;
    let before = at;
    for (const step of path) {
      const after = doorLocal(door,step);
      if (before.side*after.side <= 0 && Math.abs(after.side-before.side) > 0.0001) {
        const along = lerp(before.along,after.along,before.side/(before.side-after.side));
        if (Math.abs(along) <= door.width*0.30) return {door,side:Math.sign(at.side) || -Math.sign(after.side)};
      }
      if (Math.abs(after.side) > 4.7 || Math.abs(after.along) > 4.7) break;
      before = after;
    }
  }
  return null;
}
function doorDetour(actor,task) {
  if (!task.passage) task.passage = approachingDoor(actor,task.path);
  if (!task.passage) return null;
  const {door,side} = task.passage, local = doorLocal(door,actor.pos);
  if (local.side*side < -0.9) {
    task.passage = null;
    return null;
  }
  if (!door.crossing || door.crossing.actor === actor) {
    if (!door.crossing) door.crossing = {actor,side,task};
    if (door.waiting.delete(actor)) {
      task.path = findPath(actor.pos,task.to); task.detour = null;
    }
    return null;
  }
  if (door.waiting.has(actor)) return door.waiting.get(actor).point;
  const co = Math.cos(door.rotation), si = Math.sin(door.rotation), bays = [];
  for (const depth of [1.52,2.12,2.62]) for (const along of [-1.22,1.22]) {
    const n = depth*side+0.052;
    const mark = point(door.x+co*along+si*n,door.z-si*along+co*n);
    if (!nav.segment(actor.pos,mark) || !isClearOfPeople(actor,mark.x,mark.z)) continue;
    if ([...door.waiting.values()].some(other => other.point.distanceToSquared(mark) < PASSING_DISTANCE**2)) continue;
    bays.push(mark);
  }
  bays.sort((a,b) => a.distanceToSquared(actor.pos)-b.distanceToSquared(actor.pos));
  const mark = bays[0] || actor.pos.clone();
  door.waiting.set(actor,{point:mark,task});
  return mark;
}
function moveDoors(dt) {
  for (const door of doors) {
    const crossing = door.crossing;
    if (crossing && (!crossing.actor.root.visible || crossing.actor.task !== crossing.task ||
        doorLocal(door,crossing.actor.pos).side*crossing.side < -1.18)) door.crossing = null;
    for (const [person,bay] of door.waiting) if (!person.root.visible || person.task !== bay.task) door.waiting.delete(person);
    const near = chars.some(c => c.root.visible && Math.hypot(c.pos.x-door.x,c.pos.z-door.z) < 2.28);
    door.open = reducedMotion.matches ? Number(near) : damp(door.open,Number(near),near ? 8 : 4,dt);
    const gap = door.width * (0.25 + door.open*0.24);
    door.panels[0].position.x = -gap; door.panels[1].position.x = gap;
  }
}
function acousticPanel(x, width, tint) {
  const h = 3.2, z = -14.73;
  scene.add(boxM(width, h, 0.10, M.wallDark, x, h / 2, z - 0.015));
  const strips = new THREE.InstancedMesh(new THREE.BoxGeometry(0.037, h - 0.14, 0.053), M.deskWood, Math.floor(width / 0.077));
  const matrix = new THREE.Matrix4();
  for (let i = 0; i < strips.count; i++) {
    matrix.makeTranslation(x - width / 2 + 0.055 + i * 0.077, h / 2, z + 0.063);
    strips.setMatrixAt(i, matrix);
  }
  scene.add(strips);
  scene.add(boxM(width, 0.039, 0.067, M.brass, x, 3.22, z + 0.02));
  lightPool(tint, x, 0.009, z + 0.5, width * 1.9, 2, 0.16);
}
// ============================================================== departments
function mountDisplay(display, x, width, height, sign, tone) {
  const wallY = 2.23, z = -14.76;
  const surround = [];
  surround.push(boxM(width+0.84,height+0.82,0.28,M.wallDark,x,wallY,z));
  surround.push(boxM(width+0.18,height+0.15,0.16,M.black,x,wallY-0.14,z+0.16));
  surround.push(boxM(width+0.60,0.07,0.24,M.brass,x,wallY-height/2-0.29,z+0.136));
  const strip = boxM(width+0.43,0.022,0.018,tone,x,wallY-height/2-0.25,z+0.26);
  surround.push(boxM(width+0.82,0.042,0.29,M.brass,x,wallY+height/2+0.413,z+0.012));
  surround.push(boxM(width+0.57,0.020,0.025,M.warmLight,x,wallY+height/2+0.30,z+0.156));
  surround.push(strip);
  for (const side of [-1,1]) {
    surround.push(boxM(0.105,height+0.76,0.31,M.frame,x+side*(width/2+0.4),wallY,z));
    surround.push(boxM(0.016,height+0.55,0.04,M.brass,x+side*(width/2+0.365),wallY,z+0.18));
  }
  scene.add(...surround); batchSolids(scene,surround);
  block(x-width/2-0.42,z-0.12,x+width/2+0.42,z+0.25);
  display.mesh.position.set(x,wallY-0.14,z+0.25); scene.add(display.mesh);

  const mark = canvasTex(1024,64,(ctx,w,h) => {
    ctx.clearRect(0,0,w,h); ctx.font = "600 33px system-ui";
    ctx.textBaseline = "middle"; ctx.textAlign = "center"; ctx.fillStyle = "#dee3e9";
    ctx.letterSpacing = "6px";
    ctx.fillText(sign,w*0.5,h*0.5);
  });
  const label = new THREE.Mesh(new THREE.PlaneGeometry(Math.min(width*0.78,6.5),0.406),
    new THREE.MeshBasicMaterial({map:mark,transparent:true, depthWrite:false}));
  label.position.set(x,wallY+height/2+0.12,z+0.151); scene.add(label);
}
const departments = {};
function dept(key, name, x, z, color, info = "") { departments[key] = {key, name, pos: new THREE.Vector3(x, 0, z), anchor: new THREE.Vector3(x, 3.85, z), color, info, status: "good"}; }

// --- Trading floor (center north): 8 desks, two rows, dual monitors
dept("trading", "Trading Floor", 0, -7.5, 0x8badff);
rug(0, -7.5, 15, 8, "#2b363f", departments.trading.color);
const tradeSeats = [];
for (let i = 0; i < 8; i++) { const r = Math.floor(i / 4), c = i % 4; tradeSeats.push(desk("trade" + i, -5.4 + c * 3.6, r ? -5.2 : -9.6, r ? 0 : Math.PI, {second: true,dark:true,trade:true})); }
// video wall on north wall
const wall = screen(13,3.20,1600,394);
mountDisplay(wall,0,13,3.20,"TRADING FLOOR",M.coolLight);
lightPool(0x53a8fa, 0, 0.006, -13.15, 16, 4.8, 0.34);
acousticPanel(-7.27, 1.15, 0xe4bd8d); acousticPanel(7.27, 1.15, 0xe4bd8d);
for (const x of [-3.85,3.85]) {
  interior.suspendedLight(x,-11.15,3.90);
  interior.suspendedLight(x,-4.55,3.35);
}
for (const x of [-8.68,8.68]) blockObj(interior.wallJoinery(x,-14.55,2.05));
for (const x of [-3.9,3.9]) lightPool(0xffc26f,x,0.027,-4.85,7.8,4.1,0.095);
interior.brassFloorTrim();

// --- Research lab (north-west), whiteboard
dept("research", "Research Lab", -15.5, -8.5, 0x78e7d1);
rug(-15.5, -8.5, 9, 9, "#3d4745", departments.research.color);
const labSeats = [desk("lab0", -17.8, -10.5, Math.PI), desk("lab1", -14.2, -10.5, Math.PI), desk("lab2", -17.8, -6.4, 0), desk("lab3", -14.2, -6.4, 0)];
const board = screen(7.55,3.02,660,264);
mountDisplay(board,-15.5,7.55,3.02,"RESEARCH LAB",M.warmLight);
lightPool(0x65e7c4, -15.5, 0.006, -13.43, 9.3, 4.2, 0.31);
acousticPanel(-20.48, 1.43, 0xe4bd8d); acousticPanel(-11.27, 0.59, 0xe4bd8d);
glassWall(-10.5, -14.6, -10.5, -10); glassWall(-10.5, -7, -10.5, -3.6); glassWall(-22, -3.6, -13.5, -3.6);
slidingDoors(-10.5, -8.5, 3, -Math.PI / 2);
interior.suspendedLight(-16.1,-11.6,5.8);
interior.suspendedLight(-16.1,-5.65,4.35);
blockObj(interior.wallJoinery(-21.62,-10.13,4.18,Math.PI/2));
lightPool(0xffbd78,-17.2,0.027,-10.1,7,6.5,0.10);

// --- Market radar (south-west): dish on a plinth + world map screen
dept("scanner", "Market Radar", -15.5, 7.5, 0x86cca2);
rug(-15.5, 7.5, 9, 9, "#414741", departments.scanner.color);
const scanSeats = [desk("scan0", -17, 9.6, 0), desk("scan1", -13.4, 9.6, 0)];
const dish = new THREE.Group();
dish.add(at(mesh(new THREE.CylinderGeometry(0.58, 0.7, 0.32, 32), M.black), 0, 0.16, 0));
dish.add(at(mesh(new THREE.CylinderGeometry(0.46, 0.53, 0.19, 32), M.frame), 0, 0.384, 0));
dish.add(at(mesh(new THREE.CylinderGeometry(0.08, 0.12, 1.6, 12), M.metal), 0, 1.1, 0));
const dishHead = new THREE.Group();
const bowl = mesh(new THREE.SphereGeometry(0.9, 28, 12, 0, Math.PI * 2, 0, Math.PI * 0.32), new THREE.MeshStandardMaterial({color: 0xe8ecf1, metalness: 0.5, roughness: 0.25, side: THREE.DoubleSide}));
bowl.rotation.x = Math.PI; dishHead.add(bowl);
dishHead.add(at(mesh(new THREE.CylinderGeometry(0.02, 0.02, 0.8, 6), M.metal), 0, -0.4, 0));
const beacon = mesh(new THREE.SphereGeometry(0.076, 12, 8), new THREE.MeshBasicMaterial({color: 0x77e8bc, toneMapped: false})); beacon.position.y = -0.8; dishHead.add(beacon);
const dishRim = new THREE.Mesh(new THREE.TorusGeometry(0.76, 0.023, 8, 40), M.frame);
dishRim.rotation.x = Math.PI / 2; dishRim.position.y = -0.48; dishHead.add(dishRim);
dishHead.position.y = 2.0; dishHead.rotation.x = -0.9; dish.add(dishHead);
dish.position.set(-19.5, 0, 4.5); scene.add(dish); blockObj(dish.children[0], 0.2);
lightPool(0x37b88f, -19.5, 0.032, 4.5, 4.15, 4.15, 0.25);
const radarPulses = [0, 1].map(() => {
  const pulse = new THREE.Mesh(new THREE.RingGeometry(0.97, 1, 64), new THREE.MeshBasicMaterial({color: 0x83e5bd, transparent: true, depthWrite: false, toneMapped: false}));
  pulse.rotation.x = -Math.PI / 2; pulse.position.set(-19.5, 0.04, 4.5); scene.add(pulse);
  return pulse;
});
const mapScr = screen(4.6, 1.9, 552, 228); mapScr.mesh.position.set(-21.75, 1.8, 8.5); mapScr.mesh.rotation.y = Math.PI / 2; scene.add(mapScr.mesh);
scene.add(boxM(0.08, 2.1, 4.9, M.frame, -21.8, 1.8, 8.5));
glassWall(-22, 3.6, -13.5, 3.6); glassWall(-10.5, 3.6, -10.5, 7); glassWall(-10.5, 10, -10.5, 14.6);

// --- Validation & Risk (south center): glass room, gate lamp panel, meeting table
dept("risk", "Validation & Risk", 0, 9.5, 0xe9bb84);
rug(0, 9.5, 9, 7.5, "#4b423c", departments.risk.color);
const riskSeat = desk("risk", 2.4, 11.5, 0, {dark: true});
const table = new THREE.Group();
const tTop = rbox(2.6, 1.2, 0.068, 0.23, M.deskWood); tTop.rotation.x = -Math.PI / 2; tTop.position.y = 0.74; table.add(tTop);
table.add(boxM(1.95, 0.07, 0.65, M.black, 0, 0.667, 0));
for (const x of [-0.85, 0.85]) table.add(boxM(0.075, 0.66, 0.61, M.frame, x, 0.34, 0));
table.add(boxM(0.72, 0.02, 0.38, M.frame, 0.32, 0.785, -0.035));
table.position.set(-1.8, 0, 8.6); scene.add(table); blockObj(tTop, 0.15);
for (const x of [-4.28, 0.65]) {
  const seat = chair();
  seat.position.set(x, 0, 8.62); seat.rotation.y = x < -1 ? -Math.PI / 2 : Math.PI / 2;
  scene.add(seat); block(x - 0.26, 8.36, x + 0.26, 8.88);
}

const lampBar = new THREE.Group(), lamps = [];
lampBar.add(boxM(6.83, 0.54, 0.14, M.frame, 0, 0, 0));
lampBar.add(boxM(6.68, 0.392, 0.05, M.black, 0, 0, 0.086));
for (let i = 0; i < 10; i++) {
  const x = -3.06 + i * 0.68;
  lampBar.add(boxM(0.46, 0.21, 0.042, M.rack, x, 0, 0.118));
  const l = boxM(0.34, 0.075, 0.04, new THREE.MeshStandardMaterial({color: 0x333333, emissive: 0x000000}), x, 0, 0.142);
  lampBar.add(l); lamps.push(l);
}
lampBar.position.set(0, 2.5, 14.7); lampBar.rotation.y = Math.PI; scene.add(lampBar);
glassWall(-5, 5.2, -1.2, 5.2); glassWall(1.2, 5.2, 5, 5.2); glassWall(-5, 5.2, -5, 14.6); glassWall(5, 5.2, 5, 14.6);
slidingDoors(0, 5.2, 2.4);
interior.suspendedLight(-1.68,8.55,3.3);
blockObj(interior.wallJoinery(-1.4,14.45,3.8,Math.PI));
lightPool(0xf6bf8c,-1.7,0.032,8.44,5.8,4.5,0.145);

// --- Learning library (south-east): shelves, books, sofa, reading desk
dept("learning", "Learning Library", 15.5, 9, 0xb9a3e8);
rug(15.5, 9, 9, 8, "#413f47", departments.learning.color);
const shelves = new THREE.Group();
for (let s = 0; s < 3; s++) {
  const sh = new THREE.Group();
  sh.add(boxM(2.6, 2.4, 0.47, M.deskWood, 0, 1.2, 0.18));
  sh.add(boxM(2.58, 2.32, 0.014, M.black, 0, 1.23, -0.07));
  sh.add(boxM(2.61, 0.09, 0.53, M.frame, 0, 2.369, -0.01));
  for (const side of [-1, 1]) sh.add(boxM(0.049, 2.34, 0.46, M.deskWood, side * 1.27, 1.2, -0.14));
  for (let k = 0; k < 4; k++) {
    sh.add(boxM(2.53, 0.04, 0.48, M.deskWood, 0, 0.30 + k * 0.60, -0.165));
    sh.add(boxM(2.47, 0.01, 0.012, M.warmLight, 0, 0.277 + k * 0.60, -0.387));
  }
  sh.position.set(13.2 + s * 2.8, 0, 13.9); shelves.add(sh);
}
scene.add(shelves); shelves.children.forEach(s => blockObj(s.children[0], 0.1));
const books = new THREE.Group(); scene.add(books);
let booksShown = 0;
const bookMat = [0x365971, 0x743f39, 0xa38151, 0x49645d, 0x554e6c, 0x5b3b49].map(color =>
  new THREE.MeshStandardMaterial({color, roughness: 0.72}));
const bookGeo = new THREE.BoxGeometry(0.12, 0.43, 0.25);
function paintBooks(count) {
  const visible = Math.min(count + 6, 80);
  while (booksShown < visible) {
    const i = booksShown++;
    const sh = Math.floor(i / 27), row = Math.floor((i % 27) / 9), k = i % 9;
    const b = mesh(bookGeo, bookMat[(i * 7 + row) % bookMat.length], false);
    b.scale.y = 0.83 + (i % 4) * 0.051;
    b.position.set(12.13 + sh * 2.8 + k * 0.214, 0.302 + row * 0.6 + b.scale.y * 0.215, 13.64);
    b.rotation.z = i % 9 === 8 ? 0.13 : 0;
    books.add(b);
  }
  books.children.forEach((book, i) => { book.visible = i < visible; });
}
const learnSeat = desk("learn", 14.5, 7.4, Math.PI / 2, {dark: true});
const sofa = new THREE.Group();
const sofaModel = fittedProp(sofaAsset, 2.34, 0.93, 1.08);
if (sofaModel) {
  sofaModel.rotation.y = Math.PI;
  sofa.add(sofaModel);
} else {
  const seat = rbox(2.2, 0.45, 0.9, 0.12, M.sofa); seat.position.y = 0.3;
  const back = rbox(2.2, 0.6, 0.25, 0.1, M.sofa); back.position.set(0, 0.7, -0.35);
  sofa.add(seat, back);
}
sofa.position.set(19.3, 0, 8.2); sofa.rotation.y = -Math.PI / 2; scene.add(sofa); blockObj(sofa.children[0], 0.1);
glassWall(10.5, 5, 10.5, 7.2); glassWall(10.5, 10.4, 10.5, 14.6);

// --- Server room (north-east)
dept("ops", "Server Room", 15.5, -9, 0x82ccd9);
rug(15.5, -9, 9, 9, "#344047", departments.ops.color);
const racks = [], leds = [];
const rackTex = canvasTex(128, 288, (g, w, h) => {
  g.fillStyle = "#101a26"; g.fillRect(0, 0, w, h);
  for (let i = 0; i < 12; i++) {
    const y = 9 + i * 22;
    g.fillStyle = "#2a3c4d"; g.fillRect(7, y, 114, 17);
    g.fillStyle = "#121f2b"; g.fillRect(13, y + 4, 69, 9);
    g.fillStyle = "#455e6c";
    for (let k = 0; k < 20; k++) g.fillRect(15 + k * 3.2, y + 6, 1, 5);
    g.fillStyle = "#527486"; g.fillRect(92, y + 5, 17, 2);
  }
});
const rackFront = new THREE.MeshStandardMaterial({map: rackTex, roughness: 0.48, metalness: 0.23});
for (let r = 0; r < 5; r++) {
  const rack = new THREE.Group(); rack.add(boxM(0.9, 2.3, 1.1, M.rack, 0, 1.15, 0));
  rack.add(at(mesh(new THREE.PlaneGeometry(0.79, 2.19), rackFront, false), 0, 1.15, 0.552));
  rack.add(boxM(0.82, 0.025, 0.05, M.coolLight, 0, 2.222, 0.54));
  for (let k = 0; k < 8; k++) {
    const led = boxM(0.044, 0.022, 0.01, new THREE.MeshBasicMaterial({color: k % 5 ? 0x86dbc5 : 0xefc28d, toneMapped: false,
      transparent: true, depthWrite: false}), 0.235, 0.23 + k * 0.23, 0.565);
    led.castShadow = false; rack.add(led); leds.push(led);
  }
  interior.rackDoor(rack);
  rack.position.set(12.2+r*1.3,0,-13.2);
  scene.add(rack); racks.push(rack); blockObj(rack,0.071);
}
lightPool(0x6dcce1, 14.8, 0.032, -11.92, 9.6, 5, 0.38);
const opsSeat = desk("ops", 16, -7.2, Math.PI, {second: true});
const sysScr = screen(3.6, 1.6, 432, 192); sysScr.mesh.position.set(21.75, 1.8, -8.5); sysScr.mesh.rotation.y = -Math.PI / 2; scene.add(sysScr.mesh);
glassWall(10.5, -14.6, 10.5, -11); glassWall(10.5, -8, 10.5, -3.6); glassWall(10.5, -3.6, 22, -3.6);
slidingDoors(10.5, -9.5, 3, -Math.PI / 2);

// --- Kitchen / coffee point (east, middle)
const kitchen = new THREE.Group();
kitchen.add(boxM(3.2, 0.91, 0.70, M.deskWood, 0, 0.46, 0));
kitchen.add(boxM(3.34, 0.051, 0.82, M.deskTop, 0, 0.937, -0.014));
for (const x of [-1.05, 0, 1.05]) {
  kitchen.add(boxM(0.99, 0.73, 0.027, M.deskWood, x, 0.47, 0.36));
  kitchen.add(boxM(0.29, 0.026, 0.033, M.brass, x, 0.75, 0.391));
}
kitchen.add(boxM(0.68, 0.014, 0.53, M.black, 0.73, 0.967, 0.05));
kitchen.add(boxM(0.5, 0.012, 0.37, M.metal, 0.73, 0.977, 0.05));
const tap = new THREE.Mesh(new THREE.TorusGeometry(0.108, 0.014, 7, 18, Math.PI), M.metal);
tap.position.set(0.73, 1.025, -0.175); tap.rotation.y = Math.PI / 2; kitchen.add(tap);
const coffee = new THREE.Group(); coffee.add(boxM(0.45, 0.55, 0.4, M.black, 0, 1.18, 0)); coffee.add(boxM(0.3, 0.05, 0.2, M.metal, 0, 0.95, 0.12));
const coffeeLed = mesh(new THREE.SphereGeometry(0.025, 8, 6), new THREE.MeshBasicMaterial({color: 0xff6b3d})); coffeeLed.position.set(0.15, 1.35, 0.205); coffee.add(coffeeLed);
coffee.position.x = -0.9; kitchen.add(coffee);
kitchen.position.set(18.8, 0, 0); kitchen.rotation.y = -Math.PI / 2; scene.add(kitchen); blockObj(kitchen.children[0], 0.1);

// lifecycle manager (CEO) desk in the middle
dept("ceo", "Lifecycle Office", 6.5, 0.5, 0xe1a0ac);
departments.ceo.anchor.set(7.8, 3.3, 0.5);
lightPool(0xe5ae80, 6.5, 0.007, 0.7, 6.2, 5.1, 0.15);
const ceoSeat = desk("ceo", 6.5, 0.8, -Math.PI / 2, {dark: true, second: true});
batchSolids(scene, deskSolids);
{
  const shadowMat = new THREE.MeshBasicMaterial({map: softDisc, color: 0x162331, transparent: true, opacity: 0.43, depthWrite: false});
  const shadows = new THREE.InstancedMesh(poolGeo, shadowMat, workstationShadows.length);
  const stamp = new THREE.Object3D();
  stamp.rotation.order = "YXZ"; stamp.rotation.x = -Math.PI / 2; stamp.scale.set(2.15, 1.75, 1);
  workstationShadows.forEach(([x, z, angle], i) => {
    stamp.position.set(x, 0.026, z); stamp.rotation.y = angle; stamp.updateMatrix();
    shadows.setMatrixAt(i, stamp.matrix);
  });
  scene.add(shadows);
}
// plants
[[-21, -14], [-11.2, -4.3], [-11.2, 4.3], [-21, 14.2], [9.8, -4.3], [9.8, 4.3], [21, 14.2], [21, -2.6], [-5.6, 4.6], [5.6, 4.6], [-8.6, -13.8], [8.6, -13.8]].forEach(([x, z]) => plant(x, z, rand(0.9, 1.3)));

// --- Mission board (atrium): company goals measured from real data
const missionScr = screen(6.4, 2.25, 1024, 360);
{
  const mb = new THREE.Group();
  mb.add(rbox(6.7, 2.5, 0.17, 0.075, M.black));
  mb.children[0].position.z = -0.11;
  missionScr.mesh.position.z = 0.0; mb.add(missionScr.mesh);
  const reverse = new THREE.Mesh(missionScr.mesh.geometry, missionScr.mesh.material);
  reverse.rotation.y = Math.PI; reverse.position.z = -0.205; mb.add(reverse);
  mb.add(boxM(6.45, 0.025, 0.044, M.coolLight, 0, -1.165, -0.011));
  for (const x of [-3.2, 3.2]) {
    mb.add(boxM(0.27,3.30,0.238,M.black,x,-1.62,-0.10));
    mb.add(boxM(0.025,2.12,0.017,M.brass,x,-2.11,0.027));
    mb.add(boxM(0.36,0.055,0.39,M.frame,x,-3.21,-0.10));
  }
  mb.position.set(0,3.25,1.6); scene.add(mb);
  block(-3.4, 1.4, -3.0, 1.8); block(3.0, 1.4, 3.4, 1.8);
}
dept("mission", "Company Mission", 0, 1.6, 0xbdcee0);
departments.mission.anchor.set(-1.3, 4.65, 2.9);

// --- GitHub research lab: the off-site compute cloud (all hyperopt/backtests run there)
const cloud = new THREE.Group();
const coreMat = new THREE.MeshStandardMaterial({color: 0x418caa, emissive: 0x5deddd, emissiveIntensity: 0.55, roughness: 0.29, metalness: 0.45, flatShading: true});
const coreGeo = new THREE.IcosahedronGeometry(0.88, 0);
const cloudCore = new THREE.Mesh(coreGeo, coreMat); cloud.add(cloudCore);
const outline = new THREE.LineSegments(new THREE.EdgesGeometry(coreGeo), new THREE.LineBasicMaterial({color: 0xb8fbec, transparent: true, opacity: 0.78}));
outline.scale.setScalar(1.025); cloudCore.add(outline);
const coreGlow = new THREE.Sprite(new THREE.SpriteMaterial({map: softDisc, color: 0x56dfdf, blending: THREE.AdditiveBlending,
  transparent: true, opacity: 0.42, depthWrite: false, toneMapped: false}));
coreGlow.scale.set(4.8, 4.8, 1); cloud.add(coreGlow);
const ringMat = new THREE.MeshBasicMaterial({color: 0x63dfd1, toneMapped: false, transparent: true, opacity: 0.82, depthWrite: false});
const cloudRing = new THREE.Mesh(new THREE.TorusGeometry(2.23, 0.026, 6, 76, Math.PI * 1.57), ringMat);
cloudRing.rotation.set(1.13, 0.2, 0); cloud.add(cloudRing);
const cloudRing2 = new THREE.Mesh(new THREE.TorusGeometry(1.63, 0.022, 6, 66, Math.PI * 1.27), ringMat);
cloudRing2.rotation.set(0.7, -0.42, Math.PI); cloud.add(cloudRing2);
const orbGeo = new THREE.SphereGeometry(0.105, 10, 8);
for (const [ring, r] of [[cloudRing, 2.23], [cloudRing2, 1.63]]) {
  const point = new THREE.Mesh(orbGeo, M.coolLight); point.position.x = r; ring.add(point);
}
const CLOUD_Y = 5.6;
cloud.position.set(-20.3, CLOUD_Y, -11.6); cloud.scale.setScalar(0.70); scene.add(cloud);
dept("cloud", "GitHub Research Lab", -20, -26, 0x78dbe5);
departments.cloud.anchor.set(-20.3, CLOUD_Y + 1.56, -11.6);
const beamFrom = new THREE.Vector3(-20.3, CLOUD_Y - 0.55, -11.6), beamTo = new THREE.Vector3(-15.5, 2.7, -8.5);
const beamCurve = new THREE.QuadraticBezierCurve3(beamFrom, new THREE.Vector3(-18, 4.7, -10.4), beamTo);
const beam = new THREE.Mesh(new THREE.TubeGeometry(beamCurve, 48, 0.02, 6, false), new THREE.MeshBasicMaterial({color: 0x77e9d6, transparent: true, opacity: 0.0, depthWrite: false, toneMapped: false}));
scene.add(beam);
const streamGeo = new THREE.CapsuleGeometry(0.032, 0.15, 3, 6);
const NB = 14, beamParts = new THREE.InstancedMesh(streamGeo, new THREE.MeshBasicMaterial({color: 0xb3f6e6, toneMapped: false}), NB);
beamParts.frustumCulled = false; scene.add(beamParts);
let labActive = false;
const packets = [];
const packetGeo = new THREE.CapsuleGeometry(0.069, 0.46, 4, 9);
function flyPacket(from, to, color = 0x7fb6ff, ms = 3200) {
  const m = new THREE.Mesh(packetGeo, new THREE.MeshBasicMaterial({color, toneMapped: false}));
  const mid = from.clone().lerp(to, 0.5); mid.y = Math.max(from.y, to.y) + 4;
  packets.push({m, curve: new THREE.QuadraticBezierCurve3(from.clone(), mid, to.clone()), s: performance.now(), ms}); scene.add(m);
}

// ============================================================== pipeline particles
const pipeline = new THREE.CatmullRomCurve3([
  new THREE.Vector3(-19.5, 2.6, 4.5), new THREE.Vector3(-15, 3.2, 0), new THREE.Vector3(-15.5, 3.0, -6),
  new THREE.Vector3(-6, 3.4, 2), new THREE.Vector3(0, 3.0, 8.5), new THREE.Vector3(4, 3.4, 2), new THREE.Vector3(0, 3.0, -7)]);
const NP = 33;
const parts = new THREE.InstancedMesh(streamGeo, new THREE.MeshBasicMaterial({color: 0x83d2d1, transparent: true, opacity: 0.48, depthWrite: false, toneMapped: false}), NP);
parts.frustumCulled = false; scene.add(parts);
const pipeLine = new THREE.Mesh(new THREE.TubeGeometry(pipeline, 156, 0.013, 6, false), new THREE.MeshBasicMaterial({color: 0x79cad5, transparent: true, opacity: 0.20, depthWrite: false, toneMapped: false}));
scene.add(pipeLine);
let flowSpeed = 0.02;

// Door openings and furniture in the route planner use the same world bounds
// as movement. The final step to a chair uses its own side entrance.
nav.finish();
for (const seat of Object.values(seats)) {
  const dockZ = deskLayout.feetZ - deskLayout.pullback;
  for (const [side,width,z] of [[1,1.30,dockZ],[-1,1.30,dockZ],[1,1.42,dockZ],[-1,1.42,dockZ],
      [1,1.42,dockZ-0.19],[-1,1.42,dockZ-0.19],[1,1.57,dockZ-0.31],[-1,1.57,dockZ-0.31]]) {
    const candidate = seat.desk.localToWorld(new THREE.Vector3(side*width,0,z));
    if (nav.clear(candidate.x,candidate.z) && nav.segment(candidate,seat.dock,0.245,seat.chair)) {
      seat.approach.copy(candidate); break;
    }
  }
}

// ============================================================== characters
const SKIN = [0xf3cfa9, 0xe5b88f, 0xc68e5e, 0x8d5a3a, 0xf6d9c2, 0xb07a4f];
const HAIR = [0x2b2018, 0x5a3b22, 0x0f0f10, 0xa4774c, 0xd9b26a, 0x8a8a8a, 0x6e2b1d];
const OUTFIT = {trader: [0xe8e6e0, 0xcfd6e2], research: [0xf6f6f2], risk: [0x2f3a52], scanner: [0x1baf7a], learn: [0x7a6fd6], ops: [0x3b3f47], ceo: [0x1f2433]};
const PANTS = [0x2a2f3a, 0x3b3b40, 0x24364f, 0x403527];
const chars = [];
const UP = UP_AXIS;

// ---- skinned office cast. The lightweight rigs remain as fallbacks for failed asset loads.
const staff = await Promise.all([officeModels["staff-sam"], officeModels["staff-maya"], officeModels["staff-harper"]]);
const [maleStaff, femaleStaff, suitedStaff] = staff;
for (const model of staff) if (model) prepareStaffClips(model);
const XBOT_URL = "https://raw.githubusercontent.com/mrdoob/three.js/r170/examples/models/gltf/Xbot.glb";
let XBOT = null;
if (!staff.some(Boolean)) try {
  const lm = document.getElementById("lmsg"); if (lm) lm.textContent = "loading motion-captured staff…";
  XBOT = await Promise.race([new GLTFLoader().loadAsync(XBOT_URL), new Promise((_, rej) => setTimeout(() => rej(new Error("timeout")), 12000))]);
  for (const name of ["agree", "headShake", "sad_pose"]) {
    const c = XBOT.animations.find(a => a.name === name); if (c) THREE.AnimationUtils.makeClipAdditive(c);
  }
} catch (e) { console.warn("mocap staff unavailable, using procedural rig:", e.message); XBOT = null; }

const officeCast = {
  Mila: suitedStaff, Ada: suitedStaff, Lena: femaleStaff, Ines: femaleStaff, Noor: femaleStaff,
  Priya: femaleStaff, Sofia: suitedStaff, Hana: femaleStaff, Zara: femaleStaff,
};
const garmentColors = {Jonas: 0x60748b, Marco: 0x996f5c, Eli: 0x71978a, Tom: 0x7491a0, Priya: 0x76648c, Hana: 0xbc9287, Zara: 0x98abb4, Lena: 0x638d8a, Ines: 0xbc996d, Noor: 0x838aa4, Sam: 0x596871, Ravi: 0x6e8e7d, Kenji: 0x92a4b2, Omar: 0x976e62, Viktor: 0x606978};
const suitTints = {trader: 0xc1d7ef, research: 0xc3d9d6, risk: 0xb5bfc4, scanner: 0xc9e2c9, learn: 0xdad0eb, ops: 0xabbaca, ceo: 0xf0dad0};
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
float lapelX = mix(0.015, 0.079, smoothstep(0.64, 0.83, y));
float lapel = step(0.63, y) * step(y, 0.83) * step(0.036, fz) * (1.0 - smoothstep(0.017, 0.020, abs(ax - lapelX)));
col = mix(col, uShirt * (uCoat > 0.5 ? 1.24 : 0.74), lapel);
float seam = (1.0 - smoothstep(0.0017, 0.004, ax)) * step(0.55, y) * step(y, 0.75) * step(0.05, fz);
col = mix(col, col * 0.73, seam);
float pocket = step(0.042, ax) * step(ax, 0.082) * step(0.705, y) * step(y, 0.722) * step(0.063, fz) * step(0.0, vBind.x - uMidX);
col = mix(col, uShirt * 0.68, pocket);
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
const ROLE_SUIT = {trader: [0x34526e, 0x526f85, 0x333f55], research: [0xa3bdc5, 0xabc3c8, 0x91abb5], risk: [0x4b4542], scanner: [0x377865], learn: [0x675e87], ops: [0x3b5261], ceo: [0x51445b]};
const hitShape = new THREE.CapsuleGeometry(0.23, 1.15, 3, 7);
const hitMat = new THREE.MeshBasicMaterial({visible: false});
const _q1 = new THREE.Quaternion(), _q2 = new THREE.Quaternion(), _delta = new THREE.Quaternion();
const _v1 = new THREE.Vector3(), _v2 = new THREE.Vector3();
function rotWorld(bone, axis, angle) {
  // rotate a bone about a WORLD axis, independent of the rig's local bone axes
  if (!bone || Math.abs(angle) < 0.00001) return;
  bone.parent.getWorldQuaternion(_q1);
  _q2.setFromAxisAngle(axis, angle);
  _delta.copy(_q1).invert().multiply(_q2).multiply(_q1);
  bone.quaternion.premultiply(_delta);
  bone.updateWorldMatrix(false, false);
}

class Person {
  constructor(name, role, home, opts = {}) {
    this.name = name; this.role = role; this.homeSeat = home; this.state = "idle"; this.queue = [];
    this.speed = rand(1.05, 1.22); this.phase = rand(0, 10); this.talkT = 0; this.mood = 0; this.speaking = false;
    this.blinkT = rand(1, 4); this.lookTarget = null; this.sitBlend = 0; this.line = "";
    const model = officeCast[name] || maleStaff || staff.find(Boolean) || XBOT;
    const R = new THREE.Group(); this.root = R;
    this.hitArea = new THREE.Mesh(hitShape, hitMat); this.hitArea.position.y = 0.825; R.add(this.hitArea);
    const blob = new THREE.Mesh(poolGeo, new THREE.MeshBasicMaterial({map: softDisc, color: 0x101820, transparent: true, opacity: 0.48, depthWrite: false}));
    blob.rotation.x = -Math.PI / 2; blob.position.y = 0.032; blob.scale.set(0.86, 0.65, 1); R.add(blob); this.blob = blob;
    const cup = mesh(new THREE.CylinderGeometry(0.04, 0.033, 0.085, 12), M.paper);
    const phone = rbox(0.055, 0.11, 0.014, 0.008, M.black);
    const tablet = new THREE.Group(); tablet.add(rbox(0.16, 0.21, 0.014, 0.015, M.black));
    const tScr = mesh(new THREE.PlaneGeometry(0.14, 0.18), M.coolLight, false, false);
    tScr.position.z = 0.008; tablet.add(tScr);
    this.props = {cup, phone, tablet};
    for (const o of Object.values(this.props)) o.visible = false;
    if (model) this.attachModel(model, role, opts);
    else {
      const skin = new THREE.MeshStandardMaterial({color: pick(SKIN), roughness: 0.6});
      const top = new THREE.MeshStandardMaterial({color: pick(OUTFIT[role] || [0xdddddd]), roughness: 0.75});
      const pants = new THREE.MeshStandardMaterial({color: pick(PANTS), roughness: 0.8});
      const hairM = new THREE.MeshStandardMaterial({color: pick(HAIR), roughness: 0.7});
      const shoeM = new THREE.MeshStandardMaterial({color: 0x1a1a1c, roughness: 0.5});
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
      for (const o of Object.values(this.props)) { o.position.set(0, -0.3, 0.04); this.armR.el.add(o); }
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
    }
    this.pos = (home?.approach || home?.pos || new THREE.Vector3()).clone();
    R.position.copy(this.pos); this.yaw = 0; scene.add(R);
    this.hitArea.userData.person = this;
    // DOM: bubble + nametag
    this.bubble = document.createElement("div"); this.bubble.className = "bubble"; $("#labels").appendChild(this.bubble);
    this.tagEl = document.createElement("div"); this.tagEl.className = "nametag"; this.tagEl.textContent = `${name} · ${roleName(role)}`; $("#labels").appendChild(this.tagEl);
    this.bubbleUntil = 0; chars.push(this);
  }
  attachModel(asset, role, opts) {
    const m = SkeletonUtils.clone(asset.scene);
    const detailed = asset !== XBOT;
    this.detailedModel = detailed;
    const look = {skin: pick(SKIN), hair: pick(HAIR), shirt: pick(ROLE_SUIT[role] || [0x888888]), pants: pick(PANTS),
      tie: role === "ceo" ? 0xd55181 : role === "risk" ? 0xeda100 : null, coat: role === "research",
      longHair: (opts.hair ?? 0) % 4 === 3 || (opts.hair ?? 0) % 4 === 1, bald: (opts.hair ?? 0) === 0 && Math.random() < 0.25};
    let bodyGeo = null;
    if (!detailed) m.traverse(o => { if (o.isMesh && !/joint/i.test(o.material?.name || o.name)) bodyGeo = o.geometry; });
    m.updateWorldMatrix(true,true);
    m.traverse(o => {
      if (o.isMesh) {
        o.castShadow = !detailed || /base|suit|ponytail|short/i.test(o.name);
        o.receiveShadow = true;
        if (o.isSkinnedMesh) {
          const scale = o.getWorldScale(new THREE.Vector3());
          const center = o.worldToLocal(new THREE.Vector3(0,0.91,0));
          o.boundingSphere = new THREE.Sphere(center,1.5 / Math.min(scale.x,scale.y,scale.z));
        }
        if (!detailed) {
          o.material = outfitMaterial(bodyGeo || o.geometry, look);
        } else if (/original top|full-length top/i.test(o.material.name) && garmentColors[this.name]) {
          o.material = o.material.clone();
          o.material.color.setHex(garmentColors[this.name]); o.material.roughness = 0.78;
          // Keep the folds and weave in the source texture while varying the fabric dye.
          o.material.onBeforeCompile = shader => {
            shader.fragmentShader = shader.fragmentShader.replace("#include <map_fragment>", `
              #ifdef USE_MAP
                vec4 fabric = texture2D(map, vMapUv);
                float weave = clamp(dot(fabric.rgb, vec3(0.26, 0.54, 0.20)) * 5.8, 0.13, 1.28);
                diffuseColor *= vec4(vec3(weave), fabric.a);
              #endif`);
          };
        } else if (/casualsuit|elegantsuit/i.test(o.name)) {
          o.material = o.material.clone();
          o.material.color.multiply(new THREE.Color(suitTints[role] ?? 0xdfdfdf)).multiplyScalar(0.88 + (this.phase % 1) * 0.26);
        }
      }
    });
    this.root.add(m); this.model = m;
    this.bones = detailed ? staffBones(m) : {};
    if (!detailed) m.traverse(o => { if (o.isBone) this.bones[o.name.replace(/^mixamorig:?/, "")] = o; });
    this.mixer = new THREE.AnimationMixer(m);
    const clip = n => asset.animations.find(a => a.name === n);
    this.act = {};
    const idle = clip(detailed ? "Idle_Standing" : "idle"), walk = clip(detailed ? "Walk_Relaxed" : "walk");
    for (const [name, animation] of [["idle", idle], ["walk", walk], ["sit", asset.sitPose], ["dock", detailed && clip("Sit_Stand")]]) {
      if (!animation) continue;
      this.act[name] = this.mixer.clipAction(animation).play().setEffectiveWeight(name === "idle" ? 1 : 0);
    }
    for (const n of ["agree", "headShake", "sad_pose"]) { const c = clip(n); if (!c) continue; const a = this.mixer.clipAction(c); a.blendMode = THREE.AdditiveAnimationBlending; a.play(); a.setEffectiveWeight(0); this.act[n] = a; }
    if (this.act.dock) this.act.dock.paused = true;
    if (this.act.sit) this.act.sit.time = this.phase % this.act.sit.getClip().duration;
    this.act.idle.time = rand(0, 3); this.act.walk.time = rand(0, 1);
    this.w = {walk: 0, agree: 0, headShake: 0, sad_pose: 0};
    m.updateMatrixWorld(true);
    this.hipH = this.bones.Hips ? this.bones.Hips.getWorldPosition(new THREE.Vector3()).y - this.root.position.y : 1.0;
    this.pose3 = {};
    // accessories on bones
    const head = this.bones.Head, hand = this.bones.RightHand;
    const attach = (bone, obj, x, y, z) => { // place in metres regardless of the bone's unit scale
      const k = 1 / (bone.getWorldScale(new THREE.Vector3()).x || 1); bone.add(obj); obj.scale.setScalar(k); obj.position.set(x * k, y * k, z * k); };
    if (!detailed && head && role === "trader") attach(head, mesh(new THREE.TorusGeometry(0.1, 0.011, 8, 24, Math.PI), M.black), 0, 0.1, 0);
    if (!detailed && head && (role === "research" || opts.glasses)) { const gl = new THREE.Group(); [-1, 1].forEach(sd => { const r = mesh(new THREE.TorusGeometry(0.025, 0.004, 6, 16), M.black, false); r.position.set(sd * 0.033, 0, 0); gl.add(r); }); gl.add(boxM(0.02, 0.004, 0.004, M.black)); attach(head, gl, 0, 0.09, 0.095); }
    if (hand) for (const o of Object.values(this.props)) {
      o.rotation.set(0, 0, 0);
      attach(hand, o, 0, detailed ? 0.047 : 0.09, 0.03);
    }
    this.layerBones = ["LeftUpLeg", "RightUpLeg", "LeftLeg", "RightLeg", "Spine1", "RightArm", "RightForeArm", "LeftArm", "LeftForeArm", "Neck", "Head"]
      .map(k => this.bones[k]).filter(Boolean);
    this.baseQ = this.layerBones.map(bone => bone.quaternion.clone());
    if (detailed) this.footsteps = new Footsteps(m);
  }
  animateModel(dt, t, walking) {
    const R = this.root, seated = !!this.seat && !walking, b = this.bones;

    R.position.set(this.pos.x, 0, this.pos.z); R.rotation.y = this.yaw;
    const pose = walking ? "walk" : t < this.reactionUntil ? this.reaction : this.pose, sb = this.sitBlend;
    // clip weights: walk vs idle; additive nod / head-shake / slump layered on top
    const motionWeight = this.footsteps ? 0 : 1;
    this.w.walk = damp(this.w.walk, !seated && walking ? motionWeight * clamp(this.pace / this.speed,0,1) : 0, 9, dt);
    const dockWeight = this.act.dock ? THREE.MathUtils.smoothstep(sb, 0, 0.2) * (1 - this.w.walk) : 0;
    const sitWeight = this.act.sit ? dockWeight * this.workReach : 0;
    this.act.walk.setEffectiveWeight(this.w.walk);
    this.act.idle.setEffectiveWeight(1 - this.w.walk - dockWeight);
    this.act.sit?.setEffectiveWeight(sitWeight);
    if (this.act.dock) {
      this.act.dock.setEffectiveWeight(dockWeight - sitWeight);
      this.act.dock.time = 0.68 + 1.65 * sb;
      this.act.sit.timeScale = this.typingFast ? 1.14 : 0.98;
    }
    this.act.walk.timeScale = this.pace / 1.25;
    const listening = pose === "talk" && !this.speaking;
    const tgt = {agree: listening && Math.sin(t * 0.7 + this.phase) > 0.2 ? 1 : 0, headShake: pose === "facepalm" ? 1 : 0, sad_pose: this.mood < -0.4 && !walking ? 0.7 : 0};
    for (const k of ["agree", "headShake", "sad_pose"]) if (this.act[k]) { this.w[k] = damp(this.w[k], tgt[k], 4, dt); this.act[k].setEffectiveWeight(this.w[k]); }
    // Three skips writes for unchanged mixer tracks. Restore the previous mixed
    // pose, advance it, then retain that exact result before layering gestures.
    this.layerBones.forEach((bone, i) => bone.quaternion.copy(this.baseQ[i]));
    this.footsteps?.restoreMixerInput();
    this.mixer.update(dt);
    this.footsteps?.saveMixerOutput();
    this.layerBones.forEach((bone, i) => this.baseQ[i].copy(bone.quaternion));
    this.model.position.y = this.detailedModel ? (this.seat ? deskLayout.floorY : groundAt(this.pos.x,this.pos.z)) : -sb * (this.hipH - 0.56);
    this.model.position.x = 0;
    this.model.position.z = this.detailedModel ? 0 : (deskLayout.seatZ - deskLayout.feetZ) * sb;
    R.updateWorldMatrix(true, false);
    if (this.seat) this.footsteps?.reset();
    else if (this.footsteps) {
      const people = nearbyCentres(this,1.65);
      this.footsteps.update(dt,this.pos,this.yaw,this.pace,groundAt,
        (x,z) => nav.clear(x,z,0.11,this.chairAccess?.chair) && doorClear(x,z,0.11)
          && people.every(p => (p.x-x)**2+(p.z-z)**2 > 0.32**2),
        this.motionGoal,!!this.chairAccess);
    }
    // procedural layer (world-axis rotations, rig independent)
    const f = _v1.set(Math.sin(this.yaw), 0, Math.cos(this.yaw)), right = _v2.set(-Math.cos(this.yaw), 0, Math.sin(this.yaw));
    const P = this.pose3, ks = 1 - Math.exp(-10 * dt);
    const want = {thigh: this.act.sit ? 0 : 1.5 * sb, knee: this.act.sit ? 0 : -1.55 * sb, uarm: 0, farm: 0, uarmL: 0, farmL: 0, inR: 0, inL: 0, spine: 0, headY: 0, headX: 0};
    if (!seated && this.footsteps) {
      const swing = this.footsteps.armSwing, weight = this.footsteps.weight;
      want.uarmL = -0.32*swing; want.uarm = 0.32*swing;
      want.farmL = 0.13*weight - 0.10*swing; want.farm = 0.13*weight + 0.10*swing;
      want.spine = 0.035*weight;
      rotWorld(b.Spine1,UP,-0.068*swing);
    }
    if (seated && !this.act.sit) {
      const shift = Math.sin(t * 0.72 + this.phase);
      const type = (this.typingFast ? 1.7 : 1) * t;
      const reach = 0.5 + Math.sin(t * 0.47 + this.phase) * 0.5;
      want.uarm = 0.52 + reach * 0.08; want.uarmL = 0.55;
      want.farm = 0.82 + Math.sin(type * 14 + this.phase) * 0.043;
      want.farmL = 0.85 + Math.sin(type * 12 + this.phase * 1.62) * 0.048;
      want.inR = 0.34 - reach * 0.10; want.inL = -0.33;
      want.spine = 0.094 + shift * 0.024;
    }
    if (pose === "talk" && this.speaking) { const g = Math.sin(t * 1.9 + this.phase), g2 = Math.sin(t * 1.3 + this.phase * 1.7); want.uarm = 0.26 + Math.max(0, g) * 0.32; want.farm = 0.86 + g * 0.18; want.inR = 0.25; want.uarmL = 0.14 + Math.max(0, g2) * 0.13; want.farmL = 0.4 + Math.max(0, g2) * 0.13; want.inL = -0.2; }
    if (pose === "coffee") { want.uarm = 0.55; want.farm = 1.9 + Math.max(0, Math.sin(t * 0.8 + this.phase)) * 0.35; want.inR = 0.3; }
    if (pose === "phone") { want.uarm = 0.35; want.farm = 2.35; want.inR = 0.8; want.headY = 0.15; }
    if (pose === "cheer" && !seated) { want.uarm = 0.89; want.farm = 1.07; want.inR = 0.15; }
    if (pose === "clap") { const c = Math.sin(t * 16) * 0.15; want.uarm = want.uarmL = 0.75; want.farm = want.farmL = 1.25; want.inR = 0.75 + c; want.inL = -0.75 - c; }
    if (pose === "highfive") { want.uarm = 2.6; want.farm = 0.1; }
    if (pose === "facepalm") { want.headX = 0.12; if (!seated) { want.uarm = 0.65; want.farm = 1.45; want.inR = 0.26; } }
    if (pose === "think") { want.uarm = 0.6; want.farm = 2.2; want.inR = 0.7; want.uarmL = 0.4; want.farmL = 1.4; want.inL = -0.9; }
    if (pose === "point") { want.uarm = 1.45; want.farm = 0.05; want.inR = 0.15; }
    if (pose === "present") { want.uarm = 1.2 + Math.sin(t * 1.3) * 0.12; want.farm = 0.25; want.inR = -0.3; want.uarmL = 0.4; want.farmL = 0.9; }
    if (pose === "write") { const w = t * 5 + this.phase; want.uarm = 1.75 + Math.sin(w) * 0.12; want.farm = 0.6 + Math.cos(w * 1.3) * 0.15; want.inR = 0.2 + Math.sin(w * 0.7) * 0.1; }
    if (pose === "handoff") {
      want.uarm = 1.06; want.farm = 0.53; want.inR = 0.28;
      want.uarmL = 0.27; want.farmL = 0.58; want.inL = -0.18;
    } else if (this.carryTablet) {
      want.uarm = 0.32; want.farm = 1.12; want.inR = 0.18;
      if (!walking) { want.uarmL = 0.25; want.farmL = 0.86; want.inL = -0.18; }
    }
    if (this.lookTarget) { const lt = this.lookTarget.pos || this.lookTarget; want.headY = clamp(angDiff(this.yaw, Math.atan2(lt.x - this.pos.x, lt.z - this.pos.z)), -1.0, 1.0); }
    else if (seated) want.headY = Math.sin(t * 0.52 + this.phase) * 0.13 + Math.sin(t * 0.19 + this.phase * 1.3) * 0.16;
    else if (!walking && !seated && pose === "stand") want.headY = Math.sin(t * 0.5 + this.phase) * 0.4;
    if (seated && !this.act.sit) want.headX += 0.09;
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
    if (this.speaking && !walking) rotWorld(b.Head, f, Math.sin(t * 2.6 + this.phase) * 0.05);
    this.props.cup.visible = pose === "coffee"; this.props.phone.visible = pose === "phone"; this.props.tablet.visible = !!this.carryTablet && !this.interaction?.pass && this.sitBlend < 0.18;

  }
  // ---- task queue
  do(task) { this.queue.push(task); return this; }
  clear() { this.queue = []; this.task = null; return this; }
  busy() { return !!this.task || this.queue.length > 0 || !!this.interaction; }
  say(text, ms = 5000) {
    this.line = text; this.lineAt = officeTime + 0.30;
    this.bubble.innerHTML = `<span class="who">${esc(this.name)}</span><span class="dots"><i></i><i></i><i></i></span>`;
    this.bubble.classList.add("on"); this.speaking = false; this.bubbleUntil = this.lineAt + ms / 1000;
  }
  updateSpeech(t) {
    if (!this.bubbleUntil) return;
    if (t >= this.bubbleUntil) {
      this.bubble.classList.remove("on"); this.speaking = false; this.bubbleUntil = 0;
    } else if (this.lineAt && t >= this.lineAt) {
      this.bubble.innerHTML = `<span class="who">${esc(this.name)}</span>${esc(this.line)}`;
      this.speaking = true; this.lineAt = 0;
    }
  }
  emote(sym, ms = 2800) {
    if (!this.emoteEl) { this.emoteEl = document.createElement("div"); this.emoteEl.className = "emote"; $("#labels").appendChild(this.emoteEl); }
    this.emoteEl.textContent = sym; this.emoteEl.classList.remove("on"); void this.emoteEl.offsetWidth; this.emoteEl.classList.add("on");
    this.emoteUntil = performance.now() + ms;
  }
  resetAtDesk() {
    this.clear(); this.seat = this.homeSeat; this.seat.taken = this;
    this.seat.chair.position.z = deskLayout.seatZ; this.pos.copy(this.seat.pos); this.yaw = this.seat.face;
    this.gaitSpeed = 0; this.pace = 0; this.motionGoal = null; this.chairAccess = null; this.workReach = 1; this.sitBlend = 1; this.pose = "work";
    this.lookTarget = null; this.carryTablet = false; this.speaking = false;
    this.bubbleUntil = 0; this.lineAt = 0; this.bubble.classList.remove("on");
    this.animate(0,0,false);
  }
  react(pose, seconds = 2.5) { this.reaction = pose; this.reactionUntil = officeTime + seconds; }
  feel(m) { this.mood = clamp(m, -1, 1); }
  goTo(p) { return this.do({type: "walk", to: p.clone()}); }
  sitAt(seat) {
    if (this.seat === seat && !this.queue.some(k => k.type === "walk") && this.task?.type !== "leave") return this;
    return this.goTo(seat.approach).do({type: "walk", to: seat.dock, access: seat})
      .face(seat.desk.position).do({type: "sit", seat});
  }
  wait(ms, pose = "stand") { return this.do({type: "wait", ms, pose}); }
  face(target) { return this.do({type: "face", target}); }
  stepAlong(k, dt) {
    this.chairAccess = k.access || null;
    const radius = k.access ? 0.245 : PERSON_CLEARANCE;
    const hallClear = (x,z) => nav.clear(x,z,radius,k.access?.chair) && doorClear(x,z,radius);
    if (!k.path) k.path = k.access ? [k.to.clone()] : findPath(this.pos,k.to);
    const waitingBay = !k.access && k.path.length ? doorDetour(this,k) : null;
    const target = waitingBay || k.detour || k.path[0];
    if (!target) {
      if ((k.retry || 0) <= officeTime) { k.retry = officeTime + 0.9; k.path = null; }
      return false;
    }
    const dist = this.pos.distanceTo(target);
    this.motionGoal = target;
    if (dist < 0.009 && isClearOfPeople(this,target.x,target.z) && hallClear(target.x,target.z)) {
      this.pos.copy(target);
      if (waitingBay) this.gaitSpeed = 0;
      else if (k.detour) k.detour = null;
      else { k.path.shift(); if (!k.path.length) this.task = null; }
      return dist > 0.002;
    }

    const dx = target.x-this.pos.x, dz = target.z-this.pos.z, ux = dx/Math.max(dist,0.001), uz = dz/Math.max(dist,0.001);
    const desired = Math.atan2(dx,dz), turn = Math.abs(angDiff(this.yaw,desired));
    this.turnTo(desired,dt,7);
    const corner = !waitingBay && (k.path.length > 1 || k.detour);
    const stoppingSpeed = Math.sqrt(2*2.2*Math.max(0,dist-(corner ? 0 : 0.035)));
    const course = clamp(Math.cos(turn),0,1);
    const pace = Math.min(k.access ? 0.69 : this.speed, Math.max(0.11,stoppingSpeed)) * course;
    this.gaitSpeed = this.gaitSpeed + clamp(pace - this.gaitSpeed,-3.8*dt,2.25*dt);
    const step = Math.min(dist,this.gaitSpeed*dt) * (turn > 0.9 ? 0 : course);
    const nextX = this.pos.x+ux*step, nextZ = this.pos.z+uz*step;
    const blockedByPerson = !isClearOfPeople(this,nextX,nextZ);
    if (step <= 0.0001) return false;
    if (!blockedByPerson && hallClear(nextX,nextZ)) {
      this.pos.set(nextX,0,nextZ); k.waited = 0;
      return true;
    }
    this.gaitSpeed = Math.max(0,this.gaitSpeed - 5*dt);
    k.waited = (k.waited || 0) + dt;
    if (!waitingBay && !k.access && k.waited > 0.37) {
      if (blockedByPerson) {
        const people = nearbyCentres(this,2.8);
        for (const side of [-1,1]) {
          const bypass = point(this.pos.x + ux*0.24 + uz*side*0.86,this.pos.z + uz*0.24 - ux*side*0.86);
          if (nav.segment(this.pos,bypass) && doorClear(bypass.x,bypass.z,radius) && isClearOfPeople(this,bypass.x,bypass.z)) {
            k.detour = bypass; break;
          }
        }
        if (!k.detour) {
          const path = findPath(this.pos,k.to,people);
          if (path.length) k.path = path;
        }
      } else if (doorClear(nextX,nextZ,radius)) {
        const path = findPath(this.pos,k.to);
        if (path.length) k.path = path;
      }
      k.waited = 0.06;
    }
    return false;
  }
  chairMotion(k, dt) {
    const seat = k.seat, entering = k.type === "sit";
    if (seat.taken && seat.taken !== this) { this.task = null; return; }
    seat.taken = this; this.seat = seat;
    const elapsed = Math.min(2.75, (k.elapsed || 0) + dt);
    const sequence = entering ? elapsed : 2.75 - elapsed;
    // Bend with planted feet, roll the occupied chair in, then reach for the keys.
    const blend = clamp(sequence / 1.45, 0, 1);
    const tucked = THREE.MathUtils.smoothstep(sequence, 1.45, 2.20);
    const x = lerp(seat.dock.x,seat.pos.x,tucked), z = lerp(seat.dock.z,seat.pos.z,tucked);
    if (!isClearOfPeople(this,x,z,blend)) return;
    k.elapsed = elapsed; this.sitBlend = blend;
    this.workReach = THREE.MathUtils.smoothstep(sequence, 2.02, 2.75);
    seat.chair.position.z = deskLayout.seatZ - deskLayout.pullback * (1 - tucked);
    this.pos.lerpVectors(seat.dock, seat.pos, tucked);
    this.yaw = seat.face;
    this.chairAccess = seat;
    if (k.elapsed >= 2.75) {
      this.task = null; this.pose = entering ? "work" : "stand";
      if (!entering) { this.seat = null; seat.taken = null; }
    }
  }
  startTask(k) {
    if (k.type === "walk" && this.seat) {
      this.queue.unshift({type:"walk", to:this.seat.approach, access:this.seat}, k);
      k = {type:"leave", seat:this.seat};
    }
    this.task = k;
    if (k.type === "wait") { k.left = k.ms; this.pose = k.pose; }
    if (k.type === "walk" || k.type === "leave" || k.type === "sit") this.pose = "stand";
  }
  update(dt, t) {
    this.updateSpeech(t);
    if (!this.task && this.queue.length) this.startTask(this.queue.shift());
    const k = this.task, x = this.pos.x, z = this.pos.z;
    this.motionGoal = null;
    let walking = false;
    if (k?.type === "walk") walking = this.stepAlong(k, dt);
    else if (k?.type === "leave" || k?.type === "sit") this.chairMotion(k, dt);
    else if (k?.type === "wait") { k.left -= dt * 1000; if (k.left <= 0) this.task = null; }
    else if (k?.type === "face") {
      const p = k.target.pos || k.target, angle = Math.atan2(p.x-this.pos.x, p.z-this.pos.z);
      this.turnTo(angle,dt,8);
      if (Math.abs(angDiff(this.yaw,angle)) < 0.022 && (!this.footsteps || this.footsteps.settled)) this.task = null;
    } else if (k?.type === "call") { this.task = null; k.fn(this); }
    if (!walking) this.gaitSpeed = damp(this.gaitSpeed,0,10,dt);
    this.pace = dt > 0 && walking ? Math.min(this.speed,Math.hypot(this.pos.x-x,this.pos.z-z)/dt) : 0;
    this.animate(dt,t,walking);
  }
  turnTo(a, dt, rate) { this.yaw += clamp(angDiff(this.yaw,a)*(1-Math.exp(-rate*dt)),-2.08*dt,2.08*dt); }
  animate(dt, t, walking) {
    if (this.model) return this.animateModel(dt, t, walking);
    const R = this.root, seated = !!this.seat && !walking;
    const sb = this.sitBlend, pose = walking ? "walk" : t < this.reactionUntil ? this.reaction : this.pose;
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
    this.hips.position.z = (deskLayout.seatZ - deskLayout.feetZ) * sb;
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
    this.props.cup.visible = pose === "coffee"; this.props.phone.visible = pose === "phone"; this.props.tablet.visible = !!this.carryTablet && !this.interaction?.pass && this.sitBlend < 0.18;
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

  }
}
function angDiff(a, b) { let d = b - a; while (d > Math.PI) d -= 2 * Math.PI; while (d < -Math.PI) d += 2 * Math.PI; return d; }
function roleName(r) { return {trader: "Trader", research: "Quant researcher", risk: "Risk officer", scanner: "Market scanner", learn: "Learning analyst", ops: "Site reliability", ceo: "Lifecycle manager"}[r] || r; }

function bodyCentre(actor,x=actor.pos.x,z=actor.pos.z,sit=actor.sitBlend) {
  return {x:x - Math.sin(actor.yaw)*sit*0.32, z:z - Math.cos(actor.yaw)*sit*0.32};
}
function nearbyCentres(actor,radius) {
  return chars.filter(other => other !== actor && other.root.visible && actor.pos.distanceToSquared(other.pos) < radius*radius)
    .map(other => bodyCentre(other));
}
function isClearOfPeople(actor,x,z,sit=actor.sitBlend) {
  const before = bodyCentre(actor), after = bodyCentre(actor,x,z,sit);
  for (const p of nearbyCentres(actor,1.65)) {
    const next = (p.x-after.x)**2 + (p.z-after.z)**2;
    if (next < PASSING_DISTANCE**2 && next < (p.x-before.x)**2 + (p.z-before.z)**2 - 1e-7) return false;
  }
  return true;
}

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
for (const c of chars) c.resetAtDesk();

const footStamp = new THREE.Object3D(), footPosition = new THREE.Vector3();
const footShadows = new THREE.InstancedMesh(poolGeo, new THREE.MeshBasicMaterial({
  map:softDisc, color:0x111820, opacity:0.64, transparent:true, depthWrite:false,
}), chars.length * 2);
footShadows.frustumCulled = false;
footStamp.rotation.order = "YXZ";
footStamp.rotation.x = -Math.PI / 2;
scene.add(footShadows);
for (const c of chars) c.soles = c.detailedModel ? ["ball_l","ball_r"].map(n => c.model.getObjectByName(n)) : [];
function drawFootShadows() {
  let count = 0;
  for (const c of chars) if (c.root.visible) {
    for (const sole of c.soles) {
      sole.getWorldPosition(footPosition);
      const lift = clamp((footPosition.y - 0.035) * 4.4, 0, 0.68);
      footStamp.position.set(footPosition.x - 0.055*Math.sin(c.yaw), groundAt(footPosition.x,footPosition.z)+0.006, footPosition.z - 0.055*Math.cos(c.yaw));
      footStamp.rotation.y = c.yaw;
      footStamp.scale.set(0.20*(1-lift),0.33*(1-lift),1);
      footStamp.updateMatrix(); footShadows.setMatrixAt(count++,footStamp.matrix);
    }
  }
  footShadows.count = count; footShadows.instanceMatrix.needsUpdate = true;
}

// ============================================================== director (behaviour from data)
const feedEl = $("#feed");
function feed(who, text) {
  const d = document.createElement("div"); d.className = "ev";
  d.innerHTML = `<span class="t">${new Date().toLocaleTimeString().slice(0, 5)}</span><b>${esc(who)}</b> ${esc(text)}`;
  feedEl.insertBefore(d, feedEl.children[1] || null);
  while (feedEl.children.length > 9) feedEl.removeChild(feedEl.lastChild);
}
const point = (x,z) => new THREE.Vector3(x,0,z);
const roomAisles = {
  trader: point(0,-7.45), research: point(-16,-8.52), scanner: point(-15.4,6.9),
  risk: point(0.1,3.65), learn: point(13.3,9.45), ops: point(14.6,-9.65), ceo: point(4.25,-0.7),
};
const exchanges = new Set(), pendingEncounters = [];
let officeTime = 0;
function beginExchange(people, places, lines, options = {}) {
  if (people.some(p => !p?.root.visible || p.busy()) || !lines.length) return false;
  const group = {people, places, lines, ...options, next: 0, remaining: 0, arrived: new Set()};
  people.forEach((p,i) => {
    p.interaction = group; p.lastOut = officeTime;
    // Stand at separate marks, then turn towards the mark that the partner will occupy.
    p.goTo(places[i]).face(options.center || places[1-i]).do({type:"call", fn: () => {
      group.arrived.add(p); p.pose = "stand";
    }});
  });
  if (options.document) people[0].carryTablet = true;
  exchanges.add(group); return true;
}
function finishExchange(group) {
  if (group.pass) group.pass.mesh.removeFromParent();
  exchanges.delete(group);
  for (const p of group.people) {
    p.interaction = null; p.carryTablet = false; p.locked = false; p.lookTarget = null;
    p.speaking = false; p.pose = "stand"; p.sitAt(p.homeSeat);
  }
  group.after?.();
}
function passTablet(group, dt) {
  const [giver,receiver] = group.people;
  if (!group.pass) {
    const tablet = giver.props.tablet.clone(); tablet.visible = true; scene.add(tablet);
    group.pass = {mesh:tablet, age:0};
    for (const p of group.people) {
      p.props.tablet.visible = false; p.pose = "handoff";
      p.lookTarget = p === giver ? receiver : giver;
    }
  }
  const pass = group.pass;
  pass.age += dt;
  const blend = THREE.MathUtils.smoothstep(pass.age,0.52,1.04);
  const source = giver.props.tablet, target = receiver.props.tablet, q = new THREE.Quaternion();
  source.getWorldPosition(pass.mesh.position); pass.mesh.position.lerp(target.getWorldPosition(_v1),blend);
  source.getWorldQuaternion(pass.mesh.quaternion); pass.mesh.quaternion.slerp(target.getWorldQuaternion(q),blend);
  source.getWorldScale(pass.mesh.scale);
  if (pass.age >= 1.37) {
    pass.mesh.removeFromParent(); group.pass = null; group.delivered = true;
    giver.carryTablet = false; receiver.carryTablet = true;
  }
}
function updateExchanges(dt) {
  for (const g of exchanges) {
    if (g.people.some(p => !p.root.visible)) {
      for (const p of g.people) if (!p.root.visible) p.resetAtDesk();
      finishExchange(g); continue;
    }
    if (g.arrived.size !== g.people.length) continue;
    g.remaining -= dt;
    if (g.remaining > 0) continue;
    if (g.document && g.next === 1 && !g.delivered) { passTablet(g,dt); continue; }
    if (g.next >= g.lines.length) { finishExchange(g); continue; }
    const [speaker, line] = g.lines[g.next];
    const ms = clamp(1550 + line.length * 40, 2300, 7200);
    for (const p of g.people) {
      p.pose = g.coffee && p !== speaker ? "coffee" : "talk"; p.speaking = false;
      p.locked = !!g.center;
      p.lookTarget = p === speaker ? g.people[(g.people.indexOf(p) + 1) % g.people.length] : speaker;
    }
    speaker.say(line,ms); feed(speaker.name,line); g.next++; g.remaining = (ms + 680) / 1000;
  }
}
function conversation(a,b,lines,at = null,options = {}) {
  const center = at || roomAisles[b.role];
  const spacing = options.document ? 0.48 : 0.64;
  const marks = [center.clone().add(point(-spacing,-0.18)), center.clone().add(point(spacing,0.18))];
  const started = beginExchange([a,b],marks,lines,options);
  if (!started && !options.ambient) {
    feed(lines[0][0].name, lines[0][1]);
    if (a.root.visible && b.root.visible && !pendingEncounters.some(e => e.lines[0][1] === lines[0][1])) {
      pendingEncounters.push({people:[a,b], marks, lines, options, expires:officeTime + 100});
      if (pendingEncounters.length > 8) pendingEncounters.shift();
    }
  }
  return started;
}
function deliverDoc(from,to,text) {
  return conversation(from,to,[[from,text[0]],[to,text[1]]],null,{document:true});
}
function coffeeBreak() {
  const idle = eligibleStaff().filter(c => c.role !== "ceo");
  if (idle.length < 2) return false;
  const a = idle[0], b = idle.find(c => c !== a && c.pos.distanceTo(a.pos) < 18) || idle[1];
  return conversation(a,b,[[a,"Coffee while we compare notes?"],[b,"Sure. Let's look at the same chart when we're back at our desks."]],
    point(16.85,0.80), {coffee:true,ambient:true});
}
function availableForRoutine(c) {
  return c.root.visible && !c.busy() && !pendingEncounters.some(e => e.people.includes(c));
}
function eligibleStaff() {
  return chars.filter(c => availableForRoutine(c) && c.seat)
    .sort((a,b) => (a.lastOut ?? -1) - (b.lastOut ?? -1));
}
function wanderSomeone(preferred) {
  const c = preferred && availableForRoutine(preferred) ? preferred : eligibleStaff()[0];
  if (!c) return false;
  const job = {
    research: [point(-16.5,-13.88),board.mesh.position,"write"],
    trader: [point(-2.1,-13.30),wall.mesh.position,"point"],
    scanner: [point(-18.2,5.04),dish.position,"think"],
    ops: [point(14.8,-11.85),racks[2].position,"think"],
    learn: [point(15.2,12.85),point(15.2,13.85),"stand"],
    risk: [point(1.25,13.15),lampBar.position,"think"],
    ceo: [point(0.4,3.65),point(0,1.6),"present"],
  }[c.role];
  c.lastOut = officeTime;
  c.goTo(job[0]).face(job[1]).do({type:"call",fn:() => {
    if (job[2] === "write") c.say(pick(boardNotes()),3600);
  }}).wait(rand(3700,5500),job[2]).sitAt(c.homeSeat);
  return true;
}
let nextVisit = 0.55, nextWalk = 4.4, nextStandup = 76, standupPending = false, visitTurn = 0, walkTurn = 0;
function directOffice(dt) {
  officeTime += dt;
  updateExchanges(dt);
  for (let i = 0; i < pendingEncounters.length;) {
    const e = pendingEncounters[i];
    if (e.expires < officeTime || e.people.some(p => !p.root.visible) || beginExchange(e.people,e.marks,e.lines,e.options)) {
      pendingEncounters.splice(i,1);
    } else i++;
  }
  if (officeTime >= nextStandup && !meetingOn) {
    if (standup()) { nextStandup = officeTime + 200; standupPending = false; }
    else { nextStandup = officeTime + 4; standupPending = !!S.goals?.goals?.length; }
  }
  if (standupPending) return;
  if (officeTime >= nextVisit && !meetingOn) {
    const trading = traders.filter(availableForRoutine);
    let started = false;
    if (visitTurn % 3 === 0 && trading.length >= 2) {
      started = conversation(trading[0],trading[1],[[trading[0],"Can we compare these two charts?"],[trading[1],"Yes. Let's start with the last closed candle."]],
        roomAisles.trader,{ambient:true});
    } else if (visitTurn % 3 === 1) {
      const free = researchers.filter(availableForRoutine);
      if (free.length >= 2) started = conversation(free[0],free[1],[[free[0],"Let's review the experiment together."],[free[1],"I'll bring the validation notes."]],
        roomAisles.research,{ambient:true});
    } else started = coffeeBreak();
    if (started) { visitTurn++; nextVisit = officeTime + 19; } else { visitTurn++; nextVisit = officeTime + 3; }
  }
  if (officeTime >= nextWalk && !meetingOn) {
    const movers = chars.filter(c => c.root.visible && c.busy()).length;
    if (movers < 4) {
      const order = [researchers[2],sre,scout,traders[2],analyst,ceo,risk];
      wanderSomeone(order[walkTurn++ % order.length]);
    }
    nextWalk = officeTime + 9;
  }
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
      if (verdict === "rejected") r.react("facepalm");
    } else if (/failed/.test(m)) { r.say("Experiment crashed — watchdog will retry with a lighter load."); r.react("facepalm"); feed(r.name, m.slice(0, 120)); }
    else { r.say(m.slice(0, 120)); feed(r.name, m.slice(0, 120)); }
  } else if (e.source === "lifecycle") {
    const tr = pick(traders.filter(t => !t.busy())) || traders[0];
    const to = /→ (\w+)/.exec(m)?.[1];
    conversation(ceo, tr, [[ceo, m.slice(0, 140)], [tr, to === "production" ? "Production risk it is. I'll watch it closely." : to === "retired" ? "Understood, closing it down cleanly." : "Got it — updating the sleeve."]]);
  } else if (e.source === "learner") {
    const colleague = pick(researchers);
    conversation(analyst, colleague, [[analyst, m.replace("new learning ", "").slice(0, 150)], [colleague, "Good catch. I'll A/B test that adjustment in the next experiments."]]);
  } else if (["selftest", "supervisor", "memory", "manager"].includes(e.source)) {
    sre.say(m.slice(0, 140), 7000); feed(sre.name, m.slice(0, 140));
    if (/FAILED|error|stale|exited/i.test(m)) { sre.react("facepalm"); }
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
  if (meetingOn) return false;
  const places = [point(-3.10,7.12),point(-1.8,7.12),point(-0.48,7.12),point(-2.68,10.12),point(-1.13,10.12)];
  const started = beginExchange(people,places,lines,{center:table.position,after:() => { meetingOn = false; }});
  if (started) meetingOn = true;
  return started;
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
  return meeting([ceo, lr, risk, analyst, sre], lines);
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
const C = {bg: "#0b1824", text: "#e6edf1", muted: "#a0b4c4", dim: "#8196a8", blue: "#67aed4", lblue: "#9fdbf1", green: "#6cdbaf", red: "#f1848d", amber: "#ebbe87"};
function clr(sc, bg = C.bg) {
  const {g, c} = sc;
  g.fillStyle = bg; g.fillRect(0, 0, c.width, c.height);
  const glow = g.createLinearGradient(0, 0, c.width, c.height);
  glow.addColorStop(0, "#8bcbe015"); glow.addColorStop(1, "#8bcbe000");
  g.fillStyle = glow; g.fillRect(0, 0, c.width, c.height);
  g.textAlign = "left";
  return [g, c];
}
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
  // --- research wall display: the lab's real state
  { const [g, c] = clr(board, "#10242d");
    const lab = rs.lab || {};
    g.fillStyle = "#68d8c52b"; g.fillRect(0, 0, c.width, 47);
    g.fillStyle = "#8fe7d8"; g.fillRect(0, 46, c.width, 1);
    g.font = "bold 24px sans-serif"; g.fillText("Research lab — runs on GitHub Actions", 18, 32);
    g.font = "16px sans-serif"; g.fillStyle = C.text;
    g.fillText(`runs ${lab.runs || 0} · ${lab.cpus || "–"} CPUs · budget ${lab.budget_min || "–"} min · status ${lab.status || "–"}`, 18, 70);
    g.fillText(`experiments: ${rs.counts?.done || 0} done · ${rs.counts?.running || 0} running · ${rs.counts?.failed || 0} failed`, 18, 94);
    g.fillStyle = C.muted; g.fillText("walk-forward → 2× costs → ±10% params → Monte Carlo → Deflated Sharpe", 18, 118);
    const gf = Object.entries(rs.gate_failures || {}).sort((a, b) => b[1] - a[1]).slice(0, 5), mx = Math.max(1, ...gf.map(x => x[1]));
    g.fillStyle = C.amber; g.font = "bold 15px sans-serif"; g.fillText("Most failed gates", 18, 151);
    gf.forEach(([k, v], j) => { g.fillStyle = "#da949045"; g.fillRect(170, 135 + j * 23, 300 * v / mx, 16); g.fillStyle = C.text; g.font = "14px sans-serif"; g.fillText(`${k} ×${v}`, 176, 148 + j * 23); });
    g.strokeStyle = "#6ac4c657"; g.lineWidth = 1; g.strokeRect(500, 134, 140, 110); g.fillStyle = "#8fe7d8"; g.font = "bold 13px sans-serif"; g.fillText("hypotheses", 512, 151);
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
  const base = g.createLinearGradient(0, 0, c.width, c.height);
  base.addColorStop(0,"#142638"); base.addColorStop(0.63,"#0a1725"); base.addColorStop(1,"#111a25");
  g.fillStyle = base; g.fillRect(0,0,c.width,c.height);
  g.fillStyle = "#395267"; g.fillRect(1027,26,1,341); g.fillRect(1050,206,519,1);
  g.fillStyle = "#e2ae77"; g.fillRect(34,36,4,23);
  txt(g,"PORTFOLIO EQUITY  /  BYBIT DEMO",49,53,"#b4c9d5","600 19px sans-serif");

  const points = ov.equity.map(row => Number(row.equity)).filter(value => value > 0);
  if (points.length) {
    txt(g,num(points.at(-1),0) + " USDT",39,108,"#f6f4ed","600 47px sans-serif");
  }
  if (points.length > 1) {
    const min = Math.min(...points), max = Math.max(...points), padding = (max-min)*0.14 || 1;
    const low = min - padding, high = max + padding, top = 134, bottom = 358, left = 39, width = 858;
    const x = i => left + width*i / (points.length-1);
    const y = value => bottom - (value-low)/(high-low)*(bottom-top);
    g.lineWidth = 1; g.strokeStyle = "#a1c2d328";
    for (let i = 0; i < 4; i++) {
      const f = i/3, row = lerp(top,bottom,f);
      g.beginPath(); g.moveTo(left,row); g.lineTo(904,row); g.stroke();
      txt(g,num(lerp(high,low,f),0),919,row+5,"#a0b5c8","15px monospace");
    }
    const trace = () => points.forEach((value,i) => i ? g.lineTo(x(i),y(value)) : g.moveTo(x(i),y(value)));
    const shade = g.createLinearGradient(0,top,0,bottom);
    shade.addColorStop(0,"#69b9e873"); shade.addColorStop(1,"#69b9e802");
    g.beginPath(); trace(); g.lineTo(x(points.length-1),bottom); g.lineTo(left,bottom); g.closePath();
    g.fillStyle = shade; g.fill();
    const line = g.createLinearGradient(left,0,left+width,0);
    line.addColorStop(0,"#6485f5"); line.addColorStop(1,"#81ebdd");
    g.strokeStyle = line; g.lineWidth = 4; g.lineJoin = "round";
    g.beginPath(); trace(); g.stroke();
    const lx = x(points.length-1), ly = y(points.at(-1));
    g.fillStyle = "#9ee9dc30"; g.beginPath(); g.arc(lx,ly,10 + 2*Math.sin(t*2.6),0,2*Math.PI); g.fill();
    g.fillStyle = "#bcf5e9"; g.beginPath(); g.arc(lx,ly,5,0,2*Math.PI); g.fill();
  } else {
    txt(g,"Waiting for equity snapshots",40,225,"#9bb0c2","21px sans-serif");
  }

  txt(g,"OPEN POSITIONS",1055,54,"#c1d8e5","600 21px sans-serif");
  g.textAlign = "right"; txt(g,String(ov.open_trades.length),1564,54,"#e2ae77","600 22px monospace"); g.textAlign = "left";
  ov.open_trades.slice(0,5).forEach((row,i) => {
    const y = 79 + i*24;
    txt(g,row.is_short ? "SHORT" : "LONG",1055,y,row.is_short ? "#e8a377" : "#96ceff","600 17px monospace");
    txt(g,row.pair.split(":")[0],1148,y,"#e4ecf2","19px monospace");
    g.textAlign = "right";
    txt(g,(row.profit_abs >= 0 ? "+" : "") + num(row.profit_abs),1564,y,row.profit_abs >= 0 ? "#81dbbb" : "#f397a1","600 19px monospace");
    g.textAlign = "left";
  });
  if (!ov.open_trades.length) txt(g,"Waiting for signals",1055,93,"#a0b5c7","19px sans-serif");
  const lab = S.rs?.lab || {};
  txt(g,"RESEARCH ACTIVITY",1055,245,"#c1d8e5","600 20px sans-serif");
  g.textAlign = "right"; txt(g,lab.status === "start" ? "RUNNING" : String(lab.status || "idle").toUpperCase(),1564,245,"#81dbbb","16px monospace"); g.textAlign = "left";
  const events = (ov.events || []).slice(0,4);
  events.forEach((event,i) => {
    const y = 279 + i*24;
    txt(g,event.ts.slice(11,16),1055,y,"#8ea9bb","15px monospace");
    g.save(); g.beginPath(); g.rect(1128,y-17,440,22); g.clip();
    txt(g,event.message,1128,y,"#ccd8e2","16px sans-serif"); g.restore();
  });
  wall.tex.needsUpdate = true;
}

// ============================================================== department tags / HUD / panels
const tags = {};
for (const d of Object.values(departments)) {
  const el = document.createElement("button"); el.type = "button"; el.className = "tag glass";
  el.dataset.room = d.key;
  el.style.setProperty("--department", `#${d.color.toString(16).padStart(6, "0")}`);
  el.innerHTML = `<b><span class="dot"></span>${d.name}</b><i>…</i>`; el.onclick = () => focusDept(d.key);
  $("#labels").appendChild(el); tags[d.key] = el;
}
function setTag(key, info, status) {
  const d = departments[key]; if (!d || !tags[key]) return; d.info = info; d.status = status; tags[key].querySelector("i").textContent = info;
  if (tour && tourViews[tourIndex]?.room === key) $("#tourCaption span").textContent = info;
  const col = {good: "#65d7ac", warn: "#edba77", crit: "#f17b86"}[status]; const dot = tags[key].querySelector(".dot"); dot.style.background = col; dot.style.color = col;
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
  traders.forEach((tr, i) => {
    const on = i < Math.max(live.length, 2);
    if (!on && tr.root.visible) tr.resetAtDesk();
    tr.root.visible = on; tr.bubble.style.display = on ? "" : "none";
  });
  paintBooks((ln.learnings || []).length);
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
  $("#goalRows").innerHTML = G.goals.map(x => `<div class="g"><div class="gt"><span title="${esc(x.note || "")}">${esc(x.title)}</span><b>${esc(x.value)}${x.unit === "%" ? "%" : ""}<i>/${esc(x.target)}${x.unit === "%" ? "%" : ""}</i></b></div><div class="gb"><i style="width:${Math.round(clamp(x.progress, 0, 1) * 100)}%;background:${x.progress >= 1 ? "var(--good)" : x.warning ? "var(--crit)" : "var(--blue)"}"></i></div></div>`).join("");
}

// ---- panels
let selectedPerson = null;
function openPanel(key) {
  selectedPerson = null;
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
  $("#pbody").innerHTML = h;
  $("#panel").style.setProperty("--panel-accent", tags[key].style.getPropertyValue("--department"));
  $("#panel").style.display = "block"; $("#goals").style.display = "none";
}
function refreshPersonCard() {
  const p = selectedPerson;
  if (!p) return;
  const activity = p.locked ? "in the stand-up meeting" : p.task ? ({
    walk: "walking", leave: "getting up", sit: "sitting down", face: "turning", wait: p.pose, call: "busy",
  })[p.task.type] : p.interaction?.arrived.has(p) ? (p.speaking ? "speaking" : "listening") : p.seat ? "working at desk" : p.pose;
  const label = $("#personActivity"), quote = $("#personQuote");
  if (label.textContent !== activity) label.textContent = activity;
  if (quote.dataset.line !== p.line) {
    quote.textContent = p.line ? "“" + p.line + "”" : ""; quote.hidden = !p.line; quote.dataset.line = p.line;
  }
}
function openPerson(p) {
  selectedPerson = p;
  $("#pbody").innerHTML = `<h2>${esc(p.name)}</h2><div class="sub">${roleName(p.role)}</div><div class="kv"><span>activity</span><span id="personActivity"></span></div><p id="personQuote" hidden></p><button class="btn" id="follow">Follow ${esc(p.name)}</button>`;
  refreshPersonCard();
  $("#panel").style.removeProperty("--panel-accent");
  $("#panel").style.display = "block"; $("#follow").onclick = () => { follow = p; setTour(false); };
}
$("#px").onclick = () => { selectedPerson = null; $("#panel").style.display = "none"; $("#goals").style.display = ""; follow = null; };

// ============================================================== camera director
let camTween = null, follow = null, tour = false, tourIndex = -1, tourNext = 0;
const tourViews = [
  {room:"trading", eye:[7.1,2.42,-6.22], focus:[-0.12,1.4,-11.4]},
  {room:"research", eye:[-12.2,2.42,-4.68], focus:[-15.82,1.5,-12.06]},
  {room:"scanner", eye:[-11.52,2.35,6.0], focus:[-17.8,1.34,7.94]},
  {room:"risk", eye:[-3.62,2.27,6.17], focus:[-0.19,1.31,11.21]},
  {room:"learning", eye:[12.0,2.28,11.26], focus:[17.05,1.27,8.64]},
  {room:"ops", eye:[19.58,2.27,-7.45], focus:[15.51,1.45,-11.08]},
];
function flyTo(pos, tgt, ms = 1550, rise = 0) {
  if (reducedMotion.matches) {
    camTween = null; camera.position.copy(pos); controls.target.copy(tgt); return;
  }
  camTween = {p0:camera.position.clone(),t0:controls.target.clone(),p1:pos.clone(),t1:tgt.clone(),
    s:performance.now(),ms,rise};
}
function setTour(active) {
  tour = active;
  $("#bTour").classList.toggle("on",active);
  $("#bTour").setAttribute("aria-pressed",String(active));
  document.body.classList.toggle("in-tour",active);
  $("#tourCaption").hidden = !active;
  if (!active) tourIndex = -1;
}
function tourView(index, now) {
  tourIndex = (index + tourViews.length) % tourViews.length;
  const view = tourViews[tourIndex], room = departments[view.room];
  const eye = new THREE.Vector3().fromArray(view.eye), target = new THREE.Vector3().fromArray(view.focus);
  const travel = eye.distanceTo(camera.position);
  const time = clamp(1800 + travel*61,2200,3900);
  $("#tourCaption strong").textContent = room.name;
  $("#tourCaption span").textContent = room.info;
  $("#tourCaption").style.setProperty("--department",`#${room.color.toString(16).padStart(6,"0")}`);
  const rise = camera.position.y < 4.35 && travel > 7 ? 4.6 : 0;
  flyTo(eye,target,time,rise);
  tourNext = now + time + 6400;
}
function frameTradingFloor() {
  const eye = new THREE.Vector3(0.45,0.68,0.88).normalize();
  const right = UP.clone().cross(eye).normalize(), up = eye.clone().cross(right);
  const center = new THREE.Vector3(0,0.92,-8.4);
  const tanY = Math.tan(THREE.MathUtils.degToRad(camera.fov * 0.5)), tanX = tanY*camera.aspect;
  const panel = $("#panel").getBoundingClientRect();
  const sidebar = innerWidth > 840 ? (panel.width + 20)/innerWidth : 0;
  const bottom = innerWidth <= 840 ? (innerHeight - panel.top)/innerHeight : 0;
  let distance = 8;
  for (const x of [-6.45,6.45]) for (const z of [-10.7,-4.65]) for (const y of [0,1.8]) {
    const diff = new THREE.Vector3(x,y,z).sub(center);
    distance = Math.max(distance, diff.dot(eye) + Math.max(
      Math.abs(diff.dot(right)) / (tanX * (0.91-sidebar)), Math.abs(diff.dot(up)) / (tanY * (0.85-bottom))));
  }
  center.addScaledVector(right,sidebar * tanX*distance);
  center.addScaledVector(up,-bottom * tanY*distance);
  flyTo(center.clone().addScaledVector(eye,distance),center);
}
function focusDept(key) {
  const d = departments[key]; follow = null; setTour(false); openPanel(key);
  if (key === "cloud") flyTo(new THREE.Vector3(-14.4, 9.9, 0.8), cloud.position.clone().add(new THREE.Vector3(0.4, -0.25, 0)));
  else if (key === "trading") frameTradingFloor();
  else if (key === "mission") flyTo(new THREE.Vector3(0, 4.5, 11), new THREE.Vector3(0, 3, 1.6));
  else flyTo(d.pos.clone().add(new THREE.Vector3(7.2, 9.2, 12.8)), d.pos.clone().setY(1.25));
}
$("#bReset").onclick = () => { follow = null; setTour(false); flyTo(homePosition(), HOME_TGT); };
$("#bTour").onclick = () => {
  if (tour && !reducedMotion.matches) { setTour(false); camTween = null; return; }
  $("#px").onclick();
  camTween = null; setTour(true);
  tourView(tourIndex+1,performance.now());
};
function interruptTour() { if (tour) { setTour(false); camTween = null; } }
renderer.domElement.addEventListener("pointerdown", () => { camTween = null; interruptTour(); });
renderer.domElement.addEventListener("wheel",interruptTour,{passive:true});
addEventListener("keydown",e => { if (e.key === "Escape") interruptTour(); });

// picking: people (hover tag, click) and floor → department
const ray = new THREE.Raycaster(), mouse = new THREE.Vector2(); let hover = null;
const pickables = () => chars.filter(c => c.root.visible).map(c => c.hitArea);
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
const clock = new THREE.Clock(), v3 = new THREE.Vector3();
const streak = new THREE.Object3D(), direction = new THREE.Vector3();
function drawStream(stream, curve, offset) {
  for (let i = 0; i < stream.count; i++) {
    const f = (i / stream.count + offset) % 1;
    curve.getPointAt(f, streak.position);
    curve.getTangentAt(f, direction);
    streak.quaternion.setFromUnitVectors(UP, direction);
    streak.scale.y = i % 7 === 0 ? 2.5 : 1;
    streak.updateMatrix(); stream.setMatrixAt(i, streak.matrix);
  }
  stream.instanceMatrix.needsUpdate = true;
}
function project(p, el, dy = 0) {
  v3.copy(p); v3.y += dy; v3.project(camera);
  const vis = v3.z >= -1 && v3.z < 1 && Math.abs(v3.x) < 1.13 && Math.abs(v3.y) < 1.13;
  el.style.display = vis ? "" : "none";
  if (vis) {
    el.style.setProperty("--scene-x", `${Math.round((v3.x + 1) / 2 * innerWidth)}px`);
    el.style.setProperty("--scene-y", `${Math.round((1 - v3.y) / 2 * innerHeight)}px`);
  }
}
function adjustResolution(delta, now) {
  frameTime = lerp(frameTime, Math.min(delta, 0.13), 0.08);
  if (now - lastScaleChange < 2300) return;
  let next = renderScale;
  if (frameTime > 0.057) next = Math.max(0.70, renderScale * 0.83);
  else if (frameTime < 0.028) next = Math.min(nativeScale, renderScale + 0.13);
  if (Math.abs(next - renderScale) < 0.01) return;
  renderScale = next; lastScaleChange = now; renderer.setPixelRatio(renderScale);
}
let lastScreens = 0, lastShadow = 0, pipeOffset = 0, beamOffset = 0;
function tick() {
  const delta = clock.getDelta(), dt = document.hidden ? 0 : clamp(delta,0,0.075), now = performance.now();
  directOffice(dt);
  const t = officeTime;
  adjustResolution(delta, now);
  const moving = reducedMotion.matches ? 0 : dt, ambientTime = reducedMotion.matches ? 0 : t;
  // environment: day/night
  const d = new Date(), hr = d.getHours() + d.getMinutes() / 60, day = clamp(Math.sin((hr - 6.5) / 13 * Math.PI) * 1.4, 0, 1);
  scene.background.copy(SKY_NIGHT).lerp(SKY_DAY,day); scene.fog.color.copy(scene.background);
  atmosphere.value = day;
  galleryLight.intensity = lerp(25,11,day); screenBounce.intensity = lerp(17,9,day);
  sun.intensity = 0.99 + 1.04 * day; hemi.intensity = 0.64 + 0.33 * day;
  for (const mat of cityMaterials) mat.emissiveIntensity = 0.39 - day * 0.22;
  // props
  dish.rotation.y += moving * 0.41; beacon.material.color.setHSL(0.42, 0.72, 0.57 + 0.09 * Math.sin(ambientTime * 2.3));
  radarPulses.forEach((pulse, i) => {
    const phase = (ambientTime * 0.32 + i * 0.5) % 1;
    pulse.scale.setScalar(0.68 + phase * 1.28); pulse.material.opacity = (1 - phase) * 0.41;
  });
  leds.forEach((l, i) => { l.material.opacity = 0.64 + 0.3 * Math.sin(ambientTime * (1.6 + i % 4) + i * 1.7); });
  coffeeLed.material.color.setHSL(0.09, 0.7, 0.57 + 0.08 * Math.sin(ambientTime * 1.4));
  pipeOffset = (pipeOffset + moving * flowSpeed) % 1;
  drawStream(parts, pipeline, pipeOffset);
  cloud.position.y = CLOUD_Y + Math.sin(ambientTime * 0.75) * 0.16;
  cloudRing.rotation.z += moving * (labActive ? 0.68 : 0.23); cloudRing2.rotation.z -= moving * (labActive ? 0.97 : 0.31);
  cloudCore.rotation.y += moving * (labActive ? 0.72 : 0.27); cloudCore.rotation.x = Math.sin(ambientTime * 0.57) * 0.15;
  coreMat.emissiveIntensity = labActive ? 0.72 + 0.16 * Math.sin(ambientTime * 2.8) : 0.29;
  coreGlow.material.opacity = labActive ? 0.40 + 0.06 * Math.sin(ambientTime * 2.8) : 0.22;
  beam.material.opacity = damp(beam.material.opacity, labActive ? 0.55 : 0, 2, dt);
  beamParts.visible = beam.material.opacity > 0.05;
  if (beamParts.visible) {
    beamOffset = (beamOffset + moving * 0.21) % 1;
    drawStream(beamParts, beamCurve, beamOffset);
  }
  for (let i = packets.length - 1; i >= 0; i--) {
    const pk = packets[i], k = (now - pk.s) / pk.ms;
    if (k >= 1) { scene.remove(pk.m); pk.m.material.dispose(); packets.splice(i, 1); continue; }
    pk.curve.getPoint(k, pk.m.position); pk.curve.getTangent(k, direction);
    pk.m.quaternion.setFromUnitVectors(UP, direction);
  }
  // people
  moveDoors(dt);
  for (const c of chars) {
    if (!c.root.visible) continue;
    c.update(dt, t);
    c.hitArea.position.z = -0.32 * c.sitBlend; c.blob.position.z = -0.12 * c.sitBlend;
    c.hitArea.scale.y = 1 - c.sitBlend * 0.24; c.hitArea.position.y = 0.825 * c.hitArea.scale.y;

  }
  drawFootShadows();
  if (now - lastScreens > 700) { drawAll(t); refreshPersonCard(); lastScreens = now; }
  // camera
  if (camTween) {
    const k = clamp((now - camTween.s) / camTween.ms, 0, 1), e = k < 0.5 ? 4 * k * k * k : 1 - Math.pow(-2 * k + 2, 3) / 2;
    camera.position.lerpVectors(camTween.p0,camTween.p1,e);
    camera.position.y += Math.sin(Math.PI*e)*camTween.rise;
    controls.target.lerpVectors(camTween.t0,camTween.t1,e);
    if (k >= 1) camTween = null;
  } else if (follow) {
    const tp = follow.root.position.clone().setY(1.2); controls.target.lerp(tp, 1 - Math.exp(-5 * dt));
    const want = tp.clone().add(new THREE.Vector3(2.6, 1.9, 3.3)); camera.position.lerp(want, 1 - Math.exp(-3 * dt));
  } else if (tour && !reducedMotion.matches && now >= tourNext) {
    tourView(tourIndex+1,now);
  }
  controls.update(); camera.updateMatrixWorld();
  for (const dd of Object.values(departments)) project(dd.anchor, tags[dd.key]);
  for (const c of chars) {
    if (!c.root.visible) continue;
    if (c.bubbleUntil) project(c.root.position, c.bubble, c.seat ? 1.59 : 2.13);
    if (hover === c) project(c.root.position, c.tagEl, c.seat ? 1.44 : 1.98);
    if (c.emoteEl) {
      if (now > c.emoteUntil) c.emoteEl.style.display = "none";
      else project(c.root.position, c.emoteEl, c.bubbleUntil ? 2.75 : 2.05);
    }
  }
  if (now - lastShadow >= (frameTime > 0.052 ? 350 : 130)) { renderer.shadowMap.needsUpdate = true; lastShadow = now; }
  renderer.render(scene, camera); requestAnimationFrame(tick);
}
function resizeView() {
  camera.aspect = innerWidth / innerHeight;
  camera.fov = camera.aspect < 0.85 ? 48 : 37;
  camera.updateProjectionMatrix(); renderer.setSize(innerWidth, innerHeight);
  scene.fog.near = Math.max(62, homePosition().length() - 23);
  scene.fog.far = scene.fog.near + 90;
}
addEventListener("resize", resizeView);
resizeView();

// ============================================================== start
await refresh(); await refreshSlow(true);
setInterval(refresh, 12000); setInterval(() => refreshSlow(), 15000);
$("#loader").style.opacity = 0; setTimeout(() => $("#loader").remove(), 900);
flyTo(homePosition(), HOME_TGT, 2050);
setTimeout(() => ceo.say("Morning, team. Demo account only — we earn trust with evidence, not hope.", 6500), 2600);

tick();
window.__hq = {chars, follow: (i, instant) => { follow = chars[i]; setTour(false); camTween = null;
  if (instant) { const tp = follow.root.position.clone().setY(1.2); controls.target.copy(tp); camera.position.copy(tp.clone().add(new THREE.Vector3(2.6, 1.9, 3.3))); } }};
window.__hqReady = true;
