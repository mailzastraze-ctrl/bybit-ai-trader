import * as THREE from "three";

export function officeGlass() {
  const glass = new THREE.MeshPhysicalMaterial({
    color: 0x96bed0, roughness: 0.16, metalness: 0.12, transparent: true,
    opacity: 0.105, depthWrite: false, clearcoat: 0.38,
  });
  glass.onBeforeCompile = shader => {
    shader.fragmentShader = shader.fragmentShader.replace("#include <opaque_fragment>", `
      vec3 eye = normalize(vViewPosition);
      vec3 reflected = inverseTransformDirection(reflect(-eye, normal), viewMatrix);
      float rim = pow(1.0 - abs(dot(eye, normal)), 3.5);
      float softReflection = exp(-18.0 * abs(reflected.y - 0.27));
      float strip = exp(-115.0 * abs(reflected.y - 0.29));
      float reflection = rim * (softReflection * 0.24 + strip * 0.36);
      outgoingLight = mix(outgoingLight, vec3(0.56, 0.72, 0.83), reflection);
      diffuseColor.a = 0.074 + rim * 0.15 + reflection * 0.27;
      #include <opaque_fragment>
    `);
  };
  return glass;
}

export function curvedDisplay(width, height, thickness, bend) {
  const geometry = thickness
    ? new THREE.BoxGeometry(width, height, thickness, 20, 1, 1)
    : new THREE.PlaneGeometry(width, height, 20, 1);
  const vertices = geometry.getAttribute("position");
  for (let i = 0; i < vertices.count; i++) {
    const across = 2 * vertices.getX(i) / width;
    vertices.setZ(i, vertices.getZ(i) + bend * across * across);
  }
  geometry.computeVertexNormals();
  return geometry;
}

export function createInterior(scene, M, box, rounded, batch, canvasTex) {
  const fixtures = new THREE.Group();
  scene.add(fixtures);
  const steel = new THREE.MeshStandardMaterial({color:0x32383d, roughness:0.40, metalness:0.65});
  const bronze = new THREE.MeshStandardMaterial({color:0x6f5135, roughness:0.35, metalness:0.75});
  const stone = new THREE.MeshStandardMaterial({color:0x2b3236, roughness:0.74});
  const diffused = new THREE.MeshBasicMaterial({color:0xffe3be, toneMapped:false});
  const cups = [0x9d693b,0x344755,0x65756c,0xc3b5a4].map(color =>
    new THREE.MeshStandardMaterial({color,roughness:0.42,metalness:0.09}));
  const notebookCovers = [0x202f42,0x61443b,0x373b38,0x8f806c].map(color =>
    new THREE.MeshStandardMaterial({color,roughness:0.77}));

  function section(parts, parent = fixtures) {
    parent.add(...parts);
    batch(parent, parts);
  }

  function suspendedLight(x, z, length) {
    const ceiling = 3.68;
    const frame = [
      box(length, 0.105, 0.24, steel, x, ceiling, z),
      box(length * 0.96, 0.022, 0.127, diffused, x, ceiling - 0.058, z - 0.007),
      box(length * 0.985, 0.027, 0.024, bronze, x, ceiling - 0.035, z + 0.12),
    ];
    for (const side of [-1, 1]) {
      frame.push(box(0.058, 0.12, 0.26, bronze, x + side * length * 0.49, ceiling, z));
      frame.push(box(0.013, 0.44, 0.013, steel, x + side * length * 0.37, ceiling + 0.24, z));
    }
    frame.forEach(part => { part.castShadow = false; });
    section(frame);
  }

  function wallJoinery(x, z, width, direction = 0) {
    const cabinet = new THREE.Group();
    cabinet.position.set(x, 0, z);
    cabinet.rotation.y = direction;
    scene.add(cabinet);
    const body = box(width, 0.67, 0.40, stone, 0, 0.39, 0);
    const parts = [
      body,
      box(width + 0.06, 0.049, 0.48, M.deskWood, 0, 0.75, 0),
      box(width - 0.10, 0.074, 0.3, steel, 0, 0.055, -0.027),
    ];
    for (let i = 0; i < 3; i++) {
      const center = (i - 1) * width / 3;
      parts.push(box(width/3 - 0.025, 0.53, 0.051, M.deskWood, center, 0.39, 0.216));
      parts.push(box(Math.min(width*0.22,0.48), 0.014, 0.028, bronze, center, 0.60, 0.248));
    }
    section(parts, cabinet);
    return cabinet;
  }

  function galleryFloor() {
    const tileMap = canvasTex(512,128,(g,w,h) => {
      g.fillStyle="#353b43"; g.fillRect(0,0,w,h);
      for (let i=0;i<8;i++) {
        const x=i*64;
        g.fillStyle=i%3===1?"#42464c":"#3b4249"; g.fillRect(x+1,1,62,h-2);
        g.fillStyle="#4a535814"; g.fillRect(x+3,0,1,h);
      }
      for (let i=0;i<7800;i++) {
        g.fillStyle=i%4 ? "#edf2fa06" : "#12151a22";
        g.fillRect((i*113.317)%w,(i*179.541)%h,i%4?1:2,1);
      }
    },[4.4,6]);
    const stoneFloor = new THREE.MeshStandardMaterial({map:tileMap, roughness:0.51, metalness:0.09});
    const slab = new THREE.Mesh(new THREE.PlaneGeometry(42.3,5.92),stoneFloor);
    slab.rotation.x = -Math.PI/2; slab.position.y = 0.002; slab.receiveShadow = true;
    fixtures.add(slab);
  }

  function brassFloorTrim() {
    galleryFloor();
    const panels = [];
    // Inlaid strips trace the main cross-corridor and the approaches to the trading gallery.
    for (const z of [-2.97, 2.95]) {
      panels.push(box(42.3, 0.003, 0.025, bronze, 0, 0.007, z));
    }
    for (const x of [-8.35,8.35]) {
      panels.push(box(0.025,0.003,10.7,bronze,x,0.007,-8.37));
    }
    panels.forEach(panel => { panel.castShadow = false; panel.receiveShadow = false; });
    section(panels);
  }

  function consoleStand(parent, screens, dual) {
    const columnX = dual ? 0.08 : 0;
    const plate = rounded(0.38, 0.27, 0.020, 0.026, steel);
    plate.rotation.x = -Math.PI / 2;
    plate.position.set(columnX, 0.766, 0.235);
    parent.add(plate, box(0.055, 0.30, 0.067, steel, columnX, 0.918, 0.269));
    parent.add(box(0.045, 0.030, 0.072, bronze, columnX, 1.071, 0.269));
    for (const [x,y,z] of screens) {
      const joint = new THREE.Vector3(x, y, z);
      const elbow = new THREE.Vector3(x * 0.77 + columnX * 0.23, 1.044, 0.292);
      const base = new THREE.Vector3(columnX, 1.065, 0.269);
      link(base, elbow);
      link(elbow, joint);
      parent.add(box(0.074,0.080,0.036,steel,joint.x,joint.y,joint.z - 0.007));
    }
    function link(a,b) {
      if (a.distanceToSquared(b) < 0.0004) return;
      const arm = box(0.038,0.036,a.distanceTo(b),steel);
      arm.position.copy(a).lerp(b,0.5);
      arm.quaternion.setFromUnitVectors(new THREE.Vector3(0,0,1),b.clone().sub(a).normalize());
      parent.add(arm);
    }
  }

  function dressDesk(parent, index) {
    const cupMat = cups[index % cups.length];
    const cup = new THREE.Mesh(new THREE.LatheGeometry([
      new THREE.Vector2(0,0),new THREE.Vector2(0.035,0),new THREE.Vector2(0.043,0.084),
      new THREE.Vector2(0.039,0.084),new THREE.Vector2(0.030,0.009),new THREE.Vector2(0,0.009),
    ],22),cupMat);
    cup.position.set(-0.568,0.757,-0.112); cup.castShadow = true;
    const handle = new THREE.Mesh(new THREE.TorusGeometry(0.025,0.006,7,14),cupMat);
    handle.position.set(-0.617,0.804,-0.112);
    const notebookCover = notebookCovers[index % notebookCovers.length];
    const notebook = new THREE.Group();
    notebook.add(box(0.22,0.019,0.286,notebookCover,0,0.009,0));
    notebook.add(box(0.207,0.009,0.267,M.paper,0.002,0.013,0));
    notebook.add(box(0.218,0.004,0.284,notebookCover,0,0.019,0));
    notebook.add(box(0.007,0.006,0.152,bronze,0.058,0.025,0.068));
    notebook.rotation.y = 0.15 + (index % 4) * 0.09;
    notebook.position.set(0.557,0.758,-0.135);
    parent.add(cup,handle,notebook);
    if (index%3===1) {
      const phone = rounded(0.084,0.155,0.012,0.013,steel);
      phone.rotation.x = -Math.PI/2; phone.rotation.z = -0.13;
      phone.position.set(-0.551,0.763,0.088); parent.add(phone);
    }
  }

  function perforatedMetal() {
    const map = canvasTex(192,368,(g,w,h) => {
      g.fillStyle = "#282f35"; g.fillRect(0,0,w,h);
      for (let y=3; y<h; y+=6) for (let x=(y%12===3?4:7);x<w;x+=6) {
        g.fillStyle = "#464e53"; g.fillRect(x,y+2,3,2);
        g.fillStyle = "#111921"; g.fillRect(x,y,3,3);
      }
    });
    return new THREE.MeshStandardMaterial({map,roughness:0.61,metalness:0.53});
  }
  const perforated = perforatedMetal();

  function rackDoor(rack) {
    const shell = [
      box(0.058,2.25,0.10,steel,-0.415,1.155,0.545),
      box(0.058,2.25,0.10,steel,0.415,1.155,0.545),
      box(0.86,0.095,0.089,steel,0,2.246,0.548),
      box(0.86,0.089,0.089,steel,0,0.065,0.548),
      box(0.14,2.05,0.023,perforated,-0.312,1.158,0.578),
      box(0.065,2.05,0.023,perforated,0.338,1.158,0.578),
      box(0.038,0.34,0.034,bronze,0.377,1.26,0.623),
    ];
    section(shell,rack);
  }

  return {suspendedLight, wallJoinery, brassFloorTrim, consoleStand, dressDesk, rackDoor};
}
