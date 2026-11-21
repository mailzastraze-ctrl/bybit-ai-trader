import { MathUtils, Quaternion, Vector3 } from "three";

const UP = new Vector3(0,1,0);
const TAU = Math.PI * 2;
const angleDifference = (a,b) => MathUtils.euclideanModulo(b-a+Math.PI,TAU)-Math.PI;
const SOLE_MARGIN = 0.003;

function jointDirection(joint, direction, reference) {
  const parent = joint.parent.getWorldQuaternion(new Quaternion());
  const world = parent.clone().multiply(joint.quaternion);
  const alignment = new Quaternion().setFromUnitVectors(reference.clone().applyQuaternion(world),direction);
  joint.quaternion.copy(parent.invert().multiply(alignment).multiply(world)).normalize();
}

// The rigs animate each foot independently of its shin. Drive the independent
// foot and solve the entire thigh/shin chain together, keeping the shoe planted
// in world space even when the character changes direction or pauses.
export class Footsteps {
  constructor(model) {
    this.model = model;
    this.pelvis = model.getObjectByName("pelvis");
    this.legs = ["l","r"].map((side,i) => {
      const hip = model.getObjectByName("thigh_"+side), knee = model.getObjectByName("calf_"+side);
      const foot = model.getObjectByName("foot_"+side), toe = model.getObjectByName("ball_"+side);
      const ankle = foot.getWorldPosition(new Vector3()), mid = knee.getWorldPosition(new Vector3());
      const axis = ankle.clone().sub(mid);
      const shinLength = axis.length(), thighLength = mid.distanceTo(hip.getWorldPosition(new Vector3()));
      axis.normalize().applyQuaternion(knee.getWorldQuaternion(new Quaternion()).invert());
      const toeY = toe.getWorldPosition(new Vector3()).y;
      return {hip,knee,foot, side:i===0 ? 1 : -1, shinLength, thighLength, axis,
        rest:ankle, floorOffset:toeY,
        restRotation:foot.getWorldQuaternion(new Quaternion()), basePosition:foot.position.clone(),
        baseRotation:foot.quaternion.clone(),
        upperAxis:knee.position.clone().normalize(), pos:new Vector3(), yaw:0};
    });
    this.active = false;
    this.settled = true;
    this.lowering = 0;
    this.next = 0;
  }

  restoreMixerInput() {
    for (const leg of this.legs) {
      leg.foot.position.copy(leg.basePosition);
      leg.foot.quaternion.copy(leg.baseRotation);
    }
  }
  saveMixerOutput() {
    for (const leg of this.legs) {
      leg.basePosition.copy(leg.foot.position);
      leg.baseRotation.copy(leg.foot.quaternion);
    }
  }
  reset() {
    this.active = false; this.step = null; this.settled = true; this.lowering = 0;
  }
  update(dt, pos, yaw, pace, floor, canPlant) {
    if (!this.active) {
      for (const leg of this.legs) { leg.foot.getWorldPosition(leg.pos); leg.yaw = yaw; }
      this.active = true;
    }
    const speed = MathUtils.clamp(pace,0,1.3), stride = speed > 0.11;
    const facing = new Vector3(Math.sin(yaw),0,Math.cos(yaw));
    const sideways = new Vector3(facing.z,0,-facing.x);
    const stanceWidth = stride ? 0.117 : null;
    const duration = MathUtils.lerp(0.39,0.29,speed / 1.3);
    const balance = stride ? Math.min(0.28,speed * 0.245) : 0;
    const goals = this.legs.map(leg => {
      const foot = pos.clone().addScaledVector(sideways,stanceWidth === null ? leg.rest.x : leg.side * stanceWidth)
        .addScaledVector(facing,leg.rest.z+balance);

      // Shorten the foot placement near a wall or the edge of a workstation.
      for (const scale of [1,0.68,0.32,0]) {
        const x = MathUtils.lerp(pos.x,foot.x,scale), z = MathUtils.lerp(pos.z,foot.z,scale);
        if (canPlant(x,z)) { foot.x=x; foot.z=z; break; }
      }
      foot.y = floor(foot.x,foot.z) + leg.rest.y - leg.floorOffset + SOLE_MARGIN;
      return foot;
    });

    if (this.step) {
      const step = this.step, leg = this.legs[step.index];
      step.time += dt;
      const progress = Math.min(1,step.time/step.duration);
      const move = MathUtils.smoothstep(progress,0,1);
      leg.pos.lerpVectors(step.from,step.to,move);
      leg.pos.y += step.lift * Math.sin(Math.PI*progress)**1.35;
      leg.yaw = step.yaw + angleDifference(step.yaw,step.toYaw)*move;
      if (progress >= 1) { this.next = 1-step.index; this.step = null; }
    }
    const error = this.legs.map((leg,i) => Math.hypot(leg.pos.x-goals[i].x,leg.pos.z-goals[i].z) +
      Math.abs(angleDifference(leg.yaw,yaw))*0.12);
    if (!this.step && Math.max(...error) > (stride ? 0.125 : 0.031)) {
      const index = stride && error[this.next] > 0.114 ? this.next : Number(error[1] > error[0]);
      const leg = this.legs[index];
      this.step = {index,time:0,from:leg.pos.clone(),to:goals[index],yaw:leg.yaw,toYaw:yaw,
        duration:stride ? duration : 0.235, lift:stride ? 0.076 + speed*0.017 : 0.043};
    }
    this.settled = !this.step && Math.max(...error) <= 0.031;

    let drop = 0;
    for (const leg of this.legs) {
      const hip = leg.hip.getWorldPosition(new Vector3());
      const reach = leg.thighLength + leg.shinLength - 0.008;
      const spread = Math.hypot(leg.pos.x-hip.x,leg.pos.z-hip.z);
      const height = Math.sqrt(Math.max(0.018,reach*reach-spread*spread));
      drop = Math.max(drop,hip.y - leg.pos.y - height);
    }
    // Support the centre of mass above the planted foot without the large
    // vertical bounce from the source walk cycle.
    const comfort = stride ? 0.018 : 0;
    this.lowering = Math.max(drop,MathUtils.damp(this.lowering,Math.max(comfort,drop),12,dt));
    this.model.position.y -= this.lowering;
    this.model.updateWorldMatrix(true,false);

    for (const leg of this.legs) {
      const hip = leg.hip.getWorldPosition(new Vector3());
      const target = leg.pos.clone().sub(hip);
      const extension = target.length();
      const reach = MathUtils.clamp(extension,0.18,leg.thighLength+leg.shinLength-0.0002);
      const axis = target.normalize();
      const pole = facing.clone().addScaledVector(sideways,leg.side*0.12);
      pole.addScaledVector(axis,-pole.dot(axis)).normalize();
      const along = (reach*reach + leg.thighLength**2 - leg.shinLength**2)/(2*reach);
      const bend = Math.sqrt(Math.max(0,leg.thighLength**2-along*along));
      const knee = hip.clone().addScaledVector(axis,along).addScaledVector(pole,bend);
      jointDirection(leg.hip,knee.clone().sub(hip).normalize(),leg.upperAxis);
      jointDirection(leg.knee,leg.pos.clone().sub(knee).normalize(),leg.axis);
      leg.foot.position.copy(leg.foot.parent.worldToLocal(leg.pos.clone()));
      leg.foot.quaternion.copy(leg.foot.parent.getWorldQuaternion(new Quaternion()).invert())
        .multiply(new Quaternion().setFromAxisAngle(UP, leg.yaw)).multiply(leg.restRotation);
    }
  }
}
