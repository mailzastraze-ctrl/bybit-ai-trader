import * as THREE from "three";
import { GLTFLoader } from "three/addons/loaders/GLTFLoader.js";
import { MeshoptDecoder } from "three/addons/libs/meshopt_decoder.module.js";

// Staff and locomotion from the Innerscene CC0 Parts Library, based on MakeHuman.
// Terrazzo, oak veneer, plant and sofa scans from Poly Haven (CC0).
const modelFiles = ["staff-sam", "staff-maya", "staff-harper", "planter", "sofa"];
const modelLoader = new GLTFLoader().setMeshoptDecoder(MeshoptDecoder);
const textureLoader = new THREE.TextureLoader();
const localFile = name => new URL(`./hq-${name}`, import.meta.url).href;

export const officeModels = Object.fromEntries(modelFiles.map(name => [
  name, modelLoader.loadAsync(localFile(`${name}.glb`)).catch(() => null),
]));

export function loadSurface(material, name, sx, sy, tint, normalStrength) {
  return Promise.all([
    textureLoader.loadAsync(localFile(`${name}.webp`)),
    textureLoader.loadAsync(localFile(`${name}-normal.webp`)),
  ]).then(([color, normal]) => {
    for (const map of [color, normal]) {
      map.wrapS = map.wrapT = THREE.RepeatWrapping;
      map.repeat.set(sx, sy);
      map.anisotropy = 4;
    }
    color.colorSpace = THREE.SRGBColorSpace;
    material.map?.dispose();
    material.map = color;
    material.color.setHex(tint);
    material.normalMap = normal;
    material.normalScale.setScalar(normalStrength);
    material.needsUpdate = true;
  }).catch(() => {});
}

export function fittedProp(asset, xSize, zSize, ySize) {
  if (!asset) return null;
  const prop = asset.scene.clone();
  const limit = new THREE.Box3().setFromObject(prop);
  const size = limit.getSize(new THREE.Vector3()), center = limit.getCenter(new THREE.Vector3());
  const scale = Math.min(xSize / size.x, zSize / size.z, ySize / size.y);
  prop.position.sub(center.multiplyScalar(scale));
  prop.position.y = -limit.min.y * scale;
  prop.scale.setScalar(scale);
  prop.traverse(node => {
    if (node.isMesh) { node.castShadow = true; node.receiveShadow = true; }
  });
  return prop;
}

const boneMap = {
  Hips: "pelvis", Spine1: "spine_02", Neck: "neck_01", Head: "head",
  LeftUpLeg: "thigh_l", RightUpLeg: "thigh_r", LeftLeg: "calf_l", RightLeg: "calf_r",
  LeftArm: "upperarm_l", RightArm: "upperarm_r", LeftForeArm: "lowerarm_l", RightForeArm: "lowerarm_r",
  RightHand: "hand_r",
};

export function staffBones(model) {
  const all = {};
  model.traverse(node => { if (node.isBone) all[node.name] = node; });
  return Object.fromEntries(Object.entries(boneMap).map(([k, name]) => [k, all[name]]));
}

export function seatedClip(model) {
  const clip = model.animations.find(a => a.name === "Sit_Stand");
  if (!clip) return null;
  const tracks = clip.tracks.map(track => {
    const values = track.createInterpolant().evaluate(3.03);
    return new track.constructor(track.name, [0], values);
  });
  return new THREE.AnimationClip("Seated", 1, tracks);
}
