import * as THREE from "three";

export function tileTexture(canvasTex) {
  return canvasTex(384, 384, (g, w, h) => {
    g.fillStyle = "#40444a";
    g.fillRect(0, 0, w, h);
    const shades = ["#55595b", "#585d60", "#585b60", "#555a5e", "#575c61"];
    for (let row = 0; row < 6; row++) {
      for (let col = -1; col < 4; col++) {
        const x = col * 128 + (row % 2) * 64, y = row * 64;
        g.fillStyle = shades[(col + row * 3 + 6) % shades.length];
        g.fillRect(x + 1, y + 1, 126, 62);
        g.fillStyle = "#c5d6df08";
        g.fillRect(x + 1, y + 1, 126, 1);
      }
    }
    for (let i = 0; i < 14000; i++) {
      g.fillStyle = i % 2 ? "#d5e3ee0a" : "#12243216";
      g.fillRect((i * 73.19) % w, (i * 127.31) % h, 1, 1);
    }
  }, [3, 3]);
}

function windowTexture(canvasTex, cols, rows, seed, facade = false) {
  return canvasTex(256, 256, (g, w, h) => {
    const dw = w / cols, dh = h / rows;
    const lit = ["#6f554b", "#ac8c71", "#c9af88", "#466987", "#708e9f"];
    const wall = g.createLinearGradient(0, 0, w, h);
    wall.addColorStop(0, facade ? "#222c38" : "#15232e");
    wall.addColorStop(1, "#0d1a27");
    g.fillStyle = wall;
    g.fillRect(0, 0, w, h);
    for (let row = 0; row < rows; row++) {
      for (let col = 0; col < cols; col++) {
        const x = col * dw, y = row * dh, id = (row * 17 + col * 11 + seed) * 1.62;
        const light = Math.sin(id) + Math.sin(id * 1.77) > (facade ? -0.50 : 0.74);
        g.fillStyle = light ? lit[Math.floor(Math.abs(Math.cos(id)) * 4.99)] : "#203345";
        const inset = facade ? 1.2 : dw * (seed % 2 ? 0.21 : 0.08);
        g.fillRect(x + inset, y + dh * 0.14, dw - inset * 2, dh * (facade ? 0.67 : 0.55));
        g.fillStyle = "#09121b39";
        g.fillRect(x + inset, y + dh * 0.42, dw - inset * 2, 1.5);
        if (facade) {
          g.fillStyle = "#394349";
          g.fillRect(x, y + dh * 0.85, dw, dh * 0.15);
          g.fillRect(x, y, 1.5, dh);
        }
      }
    }
  });
}

export function buildSurroundings(scene, width, depth, canvasTex) {
  const standard = params => new THREE.MeshStandardMaterial(params);
  const box = new THREE.BoxGeometry(1, 1, 1);
  function solid(material, w, h, d, x, y, z) {
    const m = new THREE.Mesh(box, material);
    m.scale.set(w, h, d);
    m.position.set(x, y, z);
    scene.add(m);
    return m;
  }
  const deck = standard({color: 0x293641, metalness: 0.59, roughness: 0.51});
  const trim = standard({color: 0x52616c, metalness: 0.67, roughness: 0.38});
  const led = new THREE.MeshBasicMaterial({color: 0x7bd2d8, toneMapped: false});
  const coolLed = new THREE.MeshBasicMaterial({color: 0x6d9cb6, toneMapped: false});
  const facadeTex = windowTexture(canvasTex, 25, 4, 47, true);
  const facade = standard({map: facadeTex, emissiveMap: facadeTex, emissive: 0xd9eaf5, emissiveIntensity: 0.18, roughness: 0.33, metalness: 0.47});
  solid([facade, facade, deck, deck, facade, facade], width + 0.55, 11.4, depth + 0.55, 0, -6.2, 0);
  solid(deck, width + 1.3, 0.52, depth + 1.3, 0, -0.32, 0);
  for (const y of [-0.78, -3.66, -6.44]) solid(trim, width + 0.76, 0.085, depth + 0.76, 0, y, 0);
  solid(led, width + 1.16, 0.018, depth + 1.16, 0, -0.49, 0);
  solid(deck, width + 6, 0.6, depth + 6, 0, -11.92, 0);

  const ground = new THREE.Mesh(new THREE.PlaneGeometry(450, 450), standard({color: 0x111d28, roughness: 0.64, metalness: 0.18}));
  ground.rotation.x = -Math.PI / 2;
  ground.position.y = -12.28;
  scene.add(ground);

  const asphalt = standard({color: 0x192a38, roughness: 0.52, metalness: 0.22});
  for (let i = -4; i <= 4; i++) {
    const k = i * 21 + 11;
    if (Math.abs(k) < 26) continue;
    solid(asphalt, 2.4, 0.02, 210, k, -12.25, 0);
    solid(asphalt, 210, 0.02, 2.4, 0, -12.25, k);
    solid(trim, 0.04, 0.016, 205, k - 1.16, -12.23, 0);
    solid(trim, 205, 0.016, 0.04, 0, -12.23, k - 1.16);
  }

  const positions = [];
  for (let row = -6; row <= 5; row++) {
    for (let col = -7; col <= 7; col++) {
      const id = row * 29 + col * 17;
      const x = col * 18 + Math.sin(id) * 4, z = row * 17 + Math.cos(id * 1.2) * 4;
      const distance = Math.hypot(x * 0.85, z);
      if (distance < 44 || (z > 22 && x > -34 && distance < 68)) continue;
      const span = distance > 58 && z < 24 ? 28 : 9;
      const height = 10 + Math.abs(Math.sin(id * 0.43)) * span;
      positions.push({x, z, height, w: 4 + 5 * Math.abs(Math.cos(id)), d: 4 + 6 * Math.abs(Math.sin(id * 1.7)), style: Math.abs(id) % 3});
    }
  }
  const cities = [windowTexture(canvasTex, 7, 20, 39), windowTexture(canvasTex, 4, 12, 24), windowTexture(canvasTex, 14, 23, 61)].map(map =>
    standard({map, emissiveMap: map, emissive: 0xabc4df, emissiveIntensity: 0.33, roughness: 0.63, metalness: 0.28}));
  const towers = cities.map((material, i) => new THREE.InstancedMesh(box, material, positions.filter(p => p.style === i).length));
  const roof = new THREE.InstancedMesh(box, deck, positions.length);
  const aerials = new THREE.InstancedMesh(box, coolLed, Math.ceil(positions.length / 6));
  const ledges = new THREE.InstancedMesh(box, trim, positions.length);
  const m = new THREE.Object3D(), tint = new THREE.Color();
  function place(target, index, w, h, d, x, y, z) {
    m.position.set(x, y, z);
    m.scale.set(w, h, d);
    m.updateMatrix();
    target.setMatrixAt(index, m.matrix);
  }
  const indices = [0, 0, 0];
  positions.forEach(({x, z, height, w, d, style}, i) => {
    const top = height - 12.25;
    const index = indices[style]++;
    place(towers[style], index, w, height, d, x, top - height / 2, z);
    towers[style].setColorAt(index, tint.setRGB(0.46 + (i % 4) * 0.1, 0.60 + (i % 3) * 0.08, 0.77));
    const crown = style === 1 ? height * 0.087 : 0.46;
    place(roof, i, w * 0.64, crown, d * 0.62, x, top + crown / 2, z);
    place(ledges, i, w + 0.17, 0.08, d + 0.17, x, top - (style === 2 ? 1.8 : 0.14), z);
    if (i % 6 === 0) place(aerials, i / 6, 0.07, 1.65, 0.07, x, top + 1.47, z);
  });
  scene.add(...towers, roof, ledges, aerials);
  return cities;
}
