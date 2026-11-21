import { Vector3 } from "three";

export const PERSON_CLEARANCE = 0.35;
export const PASSING_DISTANCE = 0.76;
const CELL = 0.30;
const PATH_CLEARANCE = PERSON_CLEARANCE + 0.04;
const DIRECTIONS = [[1,0],[-1,0],[0,1],[0,-1],[1,1],[1,-1],[-1,1],[-1,-1]];

export function officeNavigation(width, depth) {
  const cols = Math.ceil(width / CELL), rows = Math.ceil(depth / CELL);
  const ox = -width / 2, oz = -depth / 2;
  const cellX = x => Math.floor((x - ox) / CELL);
  const cellZ = z => Math.floor((z - oz) / CELL);
  const buckets = Array.from({length: cols * rows}, () => []);
  const blocked = new Uint8Array(cols * rows);
  const key = (x,z) => z * cols + x;
  const world = (x,z) => new Vector3(ox + (x + 0.5) * CELL, 0, oz + (z + 0.5) * CELL);
  const inside = (x,z) => x >= 0 && x < cols && z >= 0 && z < rows;

  function add(x0,z0,x1,z1,chair = null) {
    const shape = {minX:Math.min(x0,x1), maxX:Math.max(x0,x1), minZ:Math.min(z0,z1), maxZ:Math.max(z0,z1), chair};
    const lowX = Math.max(0,cellX(shape.minX - 0.58)), highX = Math.min(cols-1,cellX(shape.maxX + 0.58));
    const lowZ = Math.max(0,cellZ(shape.minZ - 0.58)), highZ = Math.min(rows-1,cellZ(shape.maxZ + 0.58));
    for (let z = lowZ; z <= highZ; z++) for (let x = lowX; x <= highX; x++) buckets[key(x,z)].push(shape);
  }
  function clear(x,z, radius = PERSON_CLEARANCE, chair = null) {
    const col = cellX(x), row = cellZ(z);
    if (!inside(col,row) || x < ox + radius || x > -ox - radius || z < oz + radius || z > -oz - radius) return false;
    for (const bounds of buckets[key(col,row)]) {
      if (chair && bounds.chair === chair) continue;
      const dx = Math.max(0,bounds.minX-x,x-bounds.maxX);
      const dz = Math.max(0,bounds.minZ-z,z-bounds.maxZ);
      if (dx * dx + dz * dz < radius * radius) return false;
    }
    return true;
  }
  function segment(a,b,radius = PERSON_CLEARANCE,chair = null) {
    const dx = b.x-a.x, dz = b.z-a.z, n = Math.max(1,Math.ceil(Math.hypot(dx,dz) / 0.105));
    for (let i = 0; i <= n; i++) {
      if (!clear(a.x + dx*i/n,a.z + dz*i/n,radius,chair)) return false;
    }
    return true;
  }
  function finish() {
    for (let z = 0; z < rows; z++) for (let x = 0; x < cols; x++) {
      blocked[key(x,z)] = Number(!clear(ox + (x+0.5)*CELL,oz + (z+0.5)*CELL,PATH_CLEARANCE));
    }
  }
  function route(from, to, occupied = []) {
    if (!clear(to.x,to.z)) return [];
    const apart = (x,z) => occupied.every(p => (x-p.x)**2 + (z-p.z)**2 >= PASSING_DISTANCE**2);
    const visible = (a,b) => {
      if (!segment(a,b)) return false;
      const dx = b.x-a.x, dz = b.z-a.z, n = dx*dx + dz*dz;
      return occupied.every(p => {
        const u = n ? Math.min(1, Math.max(0, ((p.x-a.x)*dx + (p.z-a.z)*dz)/n)) : 0;
        return (p.x-a.x-u*dx)**2 + (p.z-a.z-u*dz)**2 >= PASSING_DISTANCE**2;
      });
    };
    if (visible(from,to)) return [to.clone()];
    const free = (x,z) => inside(x,z) && !blocked[key(x,z)] && apart(ox+(x+0.5)*CELL,oz+(z+0.5)*CELL);
    function anchor(p) {
      const x = cellX(p.x), z = cellZ(p.z);
      for (let ring = 0; ring < 8; ring++) {
        let best, distance = Infinity;
        for (let dz=-ring;dz<=ring;dz++) for (let dx=-ring;dx<=ring;dx++) {
          if (Math.max(Math.abs(dx),Math.abs(dz)) !== ring || !free(x+dx,z+dz)) continue;
          const loc = world(x+dx,z+dz), metric = loc.distanceToSquared(p);
          if (metric < distance && visible(p,loc)) { best = [x+dx,z+dz]; distance = metric; }
        }
        if (best) return best;
      }
      return null;
    }
    const start = anchor(from), goal = anchor(to);
    if (!start || !goal) return [];
    const startId = key(...start), goalId = key(...goal);
    const open = [[0,...start]], costs = new Map([[startId,0]]), previous = new Map(), closed = new Set();
    while (open.length) {
      let best = 0;
      for (let j=1;j<open.length;j++) if (open[j][0] < open[best][0]) best = j;
      const [,x,z] = open.splice(best,1)[0], current = key(x,z);
      if (closed.has(current)) continue;
      if (current === goalId) {
        const path = [];
        for (let k = goalId; k !== undefined; k = previous.get(k)) path.push(world(k % cols,Math.floor(k/cols)));
        path.reverse(); path.push(to.clone());
        const waypoints = [];
        let at = from;
        for (let i=0;i<path.length;i++) {
          if (i<path.length-1 && visible(at,path[i+1])) continue;
          if (at.distanceToSquared(path[i]) > 1e-6) { waypoints.push(path[i]); at = path[i]; }
        }
        return waypoints;
      }
      closed.add(current);
      for (const [dx,dz] of DIRECTIONS) {
        const nx=x+dx, nz=z+dz, k=key(nx,nz);
        if (!free(nx,nz) || closed.has(k) || (dx && dz && (!free(x+dx,z) || !free(x,z+dz)))) continue;
        const g = costs.get(current) + (dx && dz ? Math.SQRT2 : 1);
        if (g >= (costs.get(k) ?? Infinity)) continue;
        costs.set(k,g); previous.set(k,current);
        open.push([g + Math.hypot(nx - goal[0], nz - goal[1]),nx,nz]);
      }
    }
    return [];
  }
  return {add, clear, segment, finish, route};
}
