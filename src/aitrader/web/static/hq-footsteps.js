import { MathUtils, Quaternion, Vector3 } from "three";

const UP = new Vector3(0, 1, 0);
const TAU = Math.PI * 2;
const angleDifference = (a,b) => MathUtils.euclideanModulo(b-a+Math.PI,TAU)-Math.PI;
const SOLE_MARGIN = 0.002;

function aimJoint(joint, direction, reference) {
  const parent = joint.parent.getWorldQuaternion(new Quaternion());
  const world = parent.clone().multiply(joint.quaternion);
  const alignment = new Quaternion().setFromUnitVectors(reference.clone().applyQuaternion(world),direction);
  joint.quaternion.copy(parent.invert().multiply(alignment).multiply(world)).normalize();
}

function groundPitch(leg, centre, yaw, weight) {
  const alignment = Math.cos(angleDifference(leg.yaw,yaw));
  const forward = (centre.x-leg.pos.x)*Math.sin(leg.yaw) + (centre.z-leg.pos.z)*Math.cos(leg.yaw);
  const heel = (1 - MathUtils.smoothstep(leg.age,0,0.10))*leg.strike;
  const toe = MathUtils.smoothstep(forward,0.14,0.34)*0.32*weight*Math.max(0,alignment);
  return toe - heel;
}

// Locomotion and the rig use the same world-space footprints. A leg keeps its
// contact throughout support. The swing aims ahead of the moving hip so the
// arriving heel can take weight in front of the body.
export class Footsteps {
  constructor(model) {
    this.model = model;
    this.legs = ["l","r"].map((side,i) => {
      const hip = model.getObjectByName("thigh_"+side), knee = model.getObjectByName("calf_"+side);
      const foot = model.getObjectByName("foot_"+side), toe = model.getObjectByName("ball_"+side);
      const ankle = foot.getWorldPosition(new Vector3()), ball = toe.getWorldPosition(new Vector3());
      const mid = knee.getWorldPosition(new Vector3()), axis = ankle.clone().sub(mid);
      const height = ankle.y - ball.y + SOLE_MARGIN;
      const shinLength = axis.length(), thighLength = mid.distanceTo(hip.getWorldPosition(new Vector3()));
      axis.normalize().applyQuaternion(knee.getWorldQuaternion(new Quaternion()).invert());
      return {hip,knee,foot,side:i===0 ? 1 : -1,height,shinLength,thighLength,axis,rest:ankle,
        toePivot:new Vector3(ball.x-ankle.x,-height,ball.z-ankle.z),heelPivot:new Vector3(0,-height,-0.054),
        restRotation:foot.getWorldQuaternion(new Quaternion()),basePosition:foot.position.clone(),baseRotation:foot.quaternion.clone(),
        upperAxis:knee.position.clone().normalize(),pos:new Vector3(),ankle:new Vector3(),orientation:new Quaternion(),
        yaw:0,pitch:0,age:1,strike:0};
    });
    this.centre = new Vector3();
    this.velocity = new Vector3();
    this.reset();
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
    this.active = false;
    this.step = null;
    this.settled = true;
    this.transfer = 0;
    this.lowering = 0;
    this.sway = 0;
    this.armSwing = 0;
    this.weight = 0;
    this.next = 0;
    this.contacts = 0;
    this.resting = 0;
    this.velocity.set(0,0,0);
  }

  update(dt, pos, yaw, pace, floor, canPlant, goal, atChair) {
    const heading = new Vector3(Math.sin(yaw),0,Math.cos(yaw));
    const right = new Vector3(heading.z,0,-heading.x);
    if (!this.active) {
      this.centre.copy(pos);
      for (const leg of this.legs) {
        leg.foot.getWorldPosition(leg.pos);
        leg.pos.y = floor(leg.pos.x,leg.pos.z) + leg.height;
        leg.age = 1; leg.strike = 0; leg.pitch = 0; leg.yaw = yaw;
      }
      this.active = true;
    }
    const measured = pos.clone().sub(this.centre);
    if (dt > 0) {
      this.velocity.lerp(measured.multiplyScalar(1/dt),1-Math.exp(-19*dt));
    }
    this.centre.copy(pos);
    const speed = MathUtils.clamp(pace,0,1.3);
    const walking = speed > 0.115;
    this.resting = walking ? 0 : this.resting + dt;
    if (this.resting > 0.7 && !this.step) this.contacts = 0;
    const firstStride = this.contacts === 0;
    const nominal = Math.max(speed,this.velocity.length()*0.85);
    this.weight = MathUtils.damp(this.weight,walking ? Math.min(1,speed/0.92) : 0,10,dt);
    const travel = this.velocity.clone();
    const direction = travel.lengthSq()>0.002 ? travel.normalize() : heading;
    const remaining = goal ? goal.distanceTo(pos) : 0;
    const stride = MathUtils.smoothstep(speed,0.10,0.79);
    const facing = Math.atan2(direction.x,direction.z);
    const landingYaw = yaw + angleDifference(yaw,facing)*stride*0.36;

    function footprint(leg,time) {
      const width = (atChair || firstStride) && !walking ? Math.abs(leg.rest.x) : MathUtils.lerp(0.131,0.112,stride);
      const advance = walking ? Math.min(remaining,nominal*(time+(firstStride ? 0.225 : 0.255))) : 0;
      const candidate = pos.clone().addScaledVector(direction,advance)
        .addScaledVector(right,leg.side*width).addScaledVector(heading,leg.rest.z);
      for (const scale of [1,0.72,0.44,0.23,0]) {
        const x = MathUtils.lerp(pos.x,candidate.x,scale), z = MathUtils.lerp(pos.z,candidate.z,scale);
        if (canPlant(x,z)) return new Vector3(x,floor(x,z)+leg.height,z);
      }
      return leg.pos.clone();
    }

    for (const leg of this.legs) leg.age += dt;
    this.transfer = Math.max(0,this.transfer-dt);
    if (this.step) {
      const step = this.step, leg = this.legs[step.index];
      step.elapsed += dt;
      const progress = Math.min(1,step.elapsed/step.duration);
      if (progress < 0.77) {
        const target = footprint(leg,Math.max(0,step.duration-step.elapsed));
        step.to.lerp(target,1-Math.exp(-17*dt));
        step.toYaw += angleDifference(step.toYaw,landingYaw)*(1-Math.exp(-10*dt));
      }
      const blend = MathUtils.smoothstep(progress,0,1);
      leg.pos.lerpVectors(step.from,step.to,blend);
      leg.pos.y += step.lift * Math.sin(Math.PI*progress)**1.35;
      leg.yaw = step.yaw + angleDifference(step.yaw,step.toYaw)*blend;
      leg.pitch = MathUtils.lerp(step.fromPitch,0.24*step.stride,MathUtils.smoothstep(progress,0,0.30));
      leg.pitch = MathUtils.lerp(leg.pitch,-step.strike,MathUtils.smoothstep(progress,0.28,0.97));
      if (progress >= 1) {
        leg.age = 0; leg.strike = step.strike;
        this.next = 1-step.index; this.step = null;
        const rear = this.legs[this.next].pos;
        const extension = (pos.x-rear.x)*direction.x + (pos.z-rear.z)*direction.z;
        this.transfer = walking ? MathUtils.lerp(0.095,0.012,MathUtils.smoothstep(extension,0.30,0.405)) : 0.042;
        if (walking) this.contacts++;
      }
    }

    const stance = this.legs.map(leg => footprint(leg,0));
    const errors = this.legs.map((leg,i) => Math.hypot(leg.pos.x-stance[i].x,leg.pos.z-stance[i].z)
      + Math.abs(angleDifference(leg.yaw,yaw))*0.12);
    const needsStep = walking && firstStride || Math.max(...errors) > (walking ? 0.078 : 0.036);
    if (!this.step && this.transfer === 0 && needsStep) {
      const index = walking && errors[this.next]>0.075 ? this.next : Number(errors[1]>errors[0]);
      const leg = this.legs[index];
      const distance = Math.hypot(leg.pos.x-stance[index].x,leg.pos.z-stance[index].z);
      const fullStride = MathUtils.lerp(0.32,0.397,stride);
      const duration = walking ? (firstStride ? 0.295 : fullStride)
        : MathUtils.lerp(0.245,0.36,MathUtils.smoothstep(distance,0.04,0.39));
      this.step = {index,duration,elapsed:0,from:leg.pos.clone(),to:footprint(leg,duration),yaw:leg.yaw,toYaw:landingYaw,
        fromPitch:groundPitch(leg,pos,yaw,this.weight),stride,strike:0.205*stride,
        lift:walking ? MathUtils.lerp(0.045,0.079,stride) : 0.043};
    }
    this.settled = !this.step && !needsStep;

    for (const [index,leg] of this.legs.entries()) {
      if (this.step?.index !== index) leg.pitch = groundPitch(leg,pos,yaw,this.weight);
      const roll = new Quaternion().setFromAxisAngle(new Vector3(1,0,0),leg.pitch);
      const pivot = leg.pitch > 0 ? leg.toePivot : leg.heelPivot;
      const turn = new Quaternion().setFromAxisAngle(UP,leg.yaw);
      leg.ankle.copy(leg.pos).add(pivot.clone().sub(pivot.clone().applyQuaternion(roll)).applyQuaternion(turn));
      leg.orientation.copy(turn).multiply(roll).multiply(leg.restRotation);
    }

    const left = this.legs[0].pos, rightFoot = this.legs[1].pos;
    const separation = (left.x-rightFoot.x)*heading.x + (left.z-rightFoot.z)*heading.z;
    this.armSwing = MathUtils.damp(this.armSwing,MathUtils.clamp(separation/0.55,-1,1)*this.weight,15,dt);
    this.sway = MathUtils.damp(this.sway, this.step ? -this.legs[this.step.index].side*this.weight*0.018 : 0,10,dt);
    // Translate only the rig. The route, collision envelope and seat anchor keep
    // their existing positions.
    this.model.position.x = this.sway;
    this.model.updateWorldMatrix(true,false);
    let required = 0;
    for (const leg of this.legs) {
      const hip = leg.hip.getWorldPosition(new Vector3());
      const reach = leg.thighLength+leg.shinLength-0.007;
      const spread = Math.hypot(leg.ankle.x-hip.x,leg.ankle.z-hip.z);
      const height = Math.sqrt(Math.max(0.025,reach*reach-spread*spread));
      required = Math.max(required,hip.y-leg.ankle.y-height);
    }
    this.lowering = Math.max(required, MathUtils.damp(this.lowering,Math.max(required,0.017*this.weight),18,dt));
    this.model.position.y -= this.lowering;
    this.model.updateWorldMatrix(true,false);

    for (const leg of this.legs) {
      const hip = leg.hip.getWorldPosition(new Vector3());
      const axis = leg.ankle.clone().sub(hip);
      const reach = MathUtils.clamp(axis.length(),0.18,leg.thighLength+leg.shinLength-0.0002);
      axis.normalize();
      const pole = heading.clone().addScaledVector(right,leg.side*0.085);
      pole.addScaledVector(axis,-pole.dot(axis)).normalize();
      const along = (reach*reach+leg.thighLength**2-leg.shinLength**2)/(2*reach);
      const bend = Math.sqrt(Math.max(0,leg.thighLength**2-along*along));
      const knee = hip.clone().addScaledVector(axis,along).addScaledVector(pole,bend);
      aimJoint(leg.hip,knee.clone().sub(hip).normalize(),leg.upperAxis);
      aimJoint(leg.knee,leg.ankle.clone().sub(knee).normalize(),leg.axis);
      leg.foot.position.copy(leg.foot.parent.worldToLocal(leg.ankle.clone()));
      leg.foot.quaternion.copy(leg.foot.parent.getWorldQuaternion(new Quaternion()).invert()).multiply(leg.orientation);
    }
  }
}
