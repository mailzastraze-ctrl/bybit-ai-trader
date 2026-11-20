// The sit/stand clip plants the feet and lowers the hips behind them. Keep that origin
// for sitting, rising and walking so all three motions share the same floor.
import * as THREE from "three";

export const deskLayout = {
  seatZ: -0.72, feetZ: -0.375, pullback: 0.235, keyboardZ: -0.22, mouseX: -0.302,
  floorY: 0.024,
};

const X = new THREE.Vector3(1, 0, 0), Y = new THREE.Vector3(0, 1, 0);
const smooth = THREE.MathUtils.smoothstep;
const position = bone => bone.getWorldPosition(new THREE.Vector3());
const rotation = bone => bone.getWorldQuaternion(new THREE.Quaternion());

function setWorldRotation(bone, q) {
  bone.quaternion.copy(rotation(bone.parent).invert().multiply(q)).normalize();
}
function rotate(bone, axis, angle) {
  setWorldRotation(bone, new THREE.Quaternion().setFromAxisAngle(axis, angle).multiply(rotation(bone)));
}
function aim(bone, child, target) {
  const origin = position(bone);
  const from = position(child).sub(origin).normalize(), to = target.clone().sub(origin).normalize();
  setWorldRotation(bone, new THREE.Quaternion().setFromUnitVectors(from, to).multiply(rotation(bone)));
}

// A two-joint reach. The elbow bends down and away from the rib cage. Both arm
// lengths are measured on this particular character in metres.
function reach(shoulder, elbow, wrist, target, side) {
  const origin = position(shoulder), upper = origin.distanceTo(position(elbow)), lower = position(elbow).distanceTo(position(wrist));
  const direction = target.clone().sub(origin);
  const length = THREE.MathUtils.clamp(direction.length(), Math.abs(upper - lower) + 0.001, upper + lower - 0.001);
  direction.normalize();
  const pole = new THREE.Vector3(side * 0.58, -1, -0.44);
  pole.addScaledVector(direction, -pole.dot(direction)).normalize();
  const along = (upper * upper - lower * lower + length * length) / (2 * length);
  const bend = Math.sqrt(Math.max(0, upper * upper - along * along));
  aim(shoulder, elbow, origin.clone().addScaledVector(direction, along).addScaledVector(pole, bend));
  aim(elbow, wrist, origin.clone().addScaledVector(direction, length));
}

function basis(across, forward) {
  const z = forward.normalize(), y = z.clone().cross(across).normalize(), x = y.clone().cross(z);
  return new THREE.Quaternion().setFromRotationMatrix(new THREE.Matrix4().makeBasis(x, y, z));
}
function layHand(flat, side, yaw, slope) {
  const across = position(flat.pinky).sub(position(flat.index)), forward = position(flat.middle).sub(position(flat.hand));
  const target = basis(new THREE.Vector3(side, 0, 0), new THREE.Vector3(yaw, slope, 1));
  setWorldRotation(flat.hand, target.multiply(basis(across, forward).invert()).multiply(rotation(flat.hand)));
}

// Three binds all actions targeting one bone to the same PropertyMixer. Imported
// cubic tracks store in/value/out triples, while authored desk tracks store one
// quaternion. Use consistent four-component rotations before blending any actions.
export function prepareStaffClips(asset) {
  asset.animations = asset.animations.map(clip => {
    const tracks = clip.tracks.map(track => {
      if (!track.createInterpolant.isInterpolantFactoryMethodGLTFCubicSpline) return track;
      const size = track.getValueSize() / 3;
      const values = new Float32Array(track.times.length * size);
      const sample = new THREE.Quaternion(), previous = new THREE.Quaternion();
      for (let i = 0; i < track.times.length; i++) {
        const start = (3*i + 1)*size, offset = i*size;
        values.set(track.values.subarray(start, start + size), offset);
        if (size === 4) {
          sample.fromArray(values, offset).normalize();
          if (i && previous.dot(sample) < 0) sample.set(-sample.x,-sample.y,-sample.z,-sample.w);
          sample.toArray(values, offset); previous.copy(sample);
        }
      }
      return new track.constructor(track.name, track.times, values).optimize();
    });
    return new THREE.AnimationClip(clip.name, clip.duration, tracks);
  });
  asset.sitPose = workstationClip(asset);
  // Static local positions, scales and unused finger channels need no mixer
  // bindings. Keep every path that differs from the bind pose in any action.
  const clips = [...asset.animations,asset.sitPose].filter(Boolean), dynamic = new Set();
  for (const clip of clips) for (const track of clip.tracks) {
    if (dynamic.has(track.name)) continue;
    const dot = track.name.lastIndexOf("."), node = asset.scene.getObjectByName(track.name.slice(0,dot));
    const rest = node?.[track.name.slice(dot+1)]?.toArray();
    if (!rest || track.values.some((value,i) => Math.abs(value - rest[i % rest.length]) > 0.00003)) {
      dynamic.add(track.name);
    }
  }
  for (const clip of clips) clip.tracks = clip.tracks.filter(track => dynamic.has(track.name));
}

// Bake the workstation action once per shared rig from its original seated posture.
function workstationClip(asset) {
  const sit = asset.animations.find(c => c.name === "Sit_Stand");
  if (!sit) return null;
  const body = asset.scene, bones = {};
  body.traverse(o => { if (o.isBone) bones[o.name] = o; });
  const tracks = sit.tracks.map(track => new track.constructor(track.name, [0], track.createInterpolant().evaluate(3).slice()));
  const anchor = new THREE.AnimationClip("Chair anchor", 1, tracks);
  const mixer = new THREE.AnimationMixer(body);
  mixer.clipAction(anchor).play(); mixer.update(0); body.updateMatrixWorld(true);
  const arms = ["l", "r"].map(s => ({
    shoulder: bones["upperarm_" + s], elbow: bones["lowerarm_" + s], hand: bones["hand_" + s],
    index: bones["index_01_" + s], middle: bones["middle_01_" + s], pinky: bones["pinky_01_" + s],
    fingers: ["index", "middle", "ring", "pinky"].map(name => [bones[name + "_01_" + s], bones[name + "_02_" + s]]),
    fingertips: ["index","middle","ring","pinky"].map(name => bones[name + "_03_" + s]),
  }));
  const moving = [bones.spine_02, bones.neck_01, bones.head,
    ...arms.flatMap(a => [a.shoulder, a.elbow, a.hand, ...a.fingers.flat()])];
  const rest = moving.map(b => b.quaternion.clone()), keys = moving.map(() => []);
  const duration = 8, fps = 20, times = [];
  for (let i = 0; i <= duration * fps; i++) {
    moving.forEach((b, n) => b.quaternion.copy(rest[n]));
    const t = i / fps, phase = 2 * Math.PI * t / duration;
    times.push(t);
    const mouse = smooth(t, 3.05, 3.82) * (1 - smooth(t, 6.52, 7.35));
    const reading = smooth(t, 1.55, 1.85) * (1 - smooth(t, 2.5, 2.8));
    rotate(bones.spine_02, X, 0.115 + 0.018 * Math.sin(phase));
    rotate(bones.neck_01, X, 0.025 + 0.045 * reading);
    rotate(bones.head, Y, 0.064 * mouse - 0.025 * Math.sin(phase));
    arms.forEach((a, n) => {
      const side = n === 0 ? 1 : -1, m = n === 1 ? mouse : 0;
      const working = (1 - reading) * (1 - m);
      const travel = Math.sin(phase * (n === 0 ? 5 : 4));
      const wristX = THREE.MathUtils.lerp(side * (0.104 + 0.020 * travel), deskLayout.mouseX, m);
      const wristZ = deskLayout.keyboardZ - deskLayout.feetZ - 0.113 + 0.016 * Math.cos(phase * (3 + n));
      const wristY = 0.813 + m * 0.013 + working * 0.003 * Math.sin(phase * (17 + n));
      reach(a.shoulder, a.elbow, a.hand, new THREE.Vector3(wristX, wristY - deskLayout.floorY, wristZ), side);
      layHand(a, side, -side * (0.13 - m * 0.10), -0.115 - m * 0.035);
      a.fingers.forEach(([first, second], idx) => {
        const press = Math.max(0, Math.sin(phase * (11 + idx + 2 * n) + idx * 1.8)) ** 3 * working;
        rotate(first, X, 0.07 + 0.10 * press + 0.16 * m);
        rotate(second, X, 0.14 + 0.10 * press + 0.15 * m);
      });
      // Estimate fingertip pads from the last phalanx, then place the lowest pad on
      // the key cap or mouse shell. Wrist height stays constant through the stroke.
      const wrist = position(a.hand);
      const tips = a.fingertips.map(tip => {
        const end = position(tip);
        return end.addScaledVector(end.clone().sub(position(tip.parent)), 0.72);
      });
      const low = tips.reduce((p,q) => p.y < q.y ? p : q);
      const keyHeight = 0.785 - deskLayout.floorY + 0.010 * m + 0.004 * (1 + Math.cos(phase * (12+n)));
      rotate(a.hand, X, -Math.atan2(keyHeight - low.y, Math.max(0.09,low.z - wrist.z)));
    });
    moving.forEach((b, n) => {
      const q = b.quaternion, a = keys[n], k = a.length - 4;
      const flip = k >= 0 && a[k]*q.x + a[k+1]*q.y + a[k+2]*q.z + a[k+3]*q.w < 0 ? -1 : 1;
      a.push(q.x * flip, q.y * flip, q.z * flip, q.w * flip);
    });
  }
  mixer.stopAllAction(); mixer.uncacheRoot(body);
  const names = new Set(moving.map(b => b.name + ".quaternion"));
  return new THREE.AnimationClip("Desk work", duration, [
    ...tracks.filter(tr => !names.has(tr.name)),
    ...moving.map((b, n) => new THREE.QuaternionKeyframeTrack(b.name + ".quaternion", times, keys[n])),
  ]);
}
