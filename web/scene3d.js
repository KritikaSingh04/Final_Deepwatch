/* 3D digital twin — subsea pipeline scene (three.js).
   World scale: the pipeline always spans x ∈ [-50, +50] world units,
   whatever its physical length; segments are built dynamically from the
   active configuration and rebuilt when the mode changes. */

import * as THREE from "three";
import { OrbitControls } from "three/addons/controls/OrbitControls.js";
import { leakCardHtml } from "/static/leakcard.js";

const TIER_HEX = { GREEN: 0x0ca30c, YELLOW: 0xfab219, ORANGE: 0xec835a, RED: 0xd03b3b };
const PIPE_Y = 1.35, SPAN = 100, X0 = -50;

export function initScene(container, cfg0) {
  let cfg = { ...cfg0 };            // {length_m, segment_len_m, num_segments}
  let segBounds = [];               // [[lo,hi], ...] metres
  let segMeshes = [];
  let lineGroup = null;

  const scene = new THREE.Scene();
  scene.fog = new THREE.FogExp2(0x07182b, 0.0115);

  const camera = new THREE.PerspectiveCamera(48, 1, 0.1, 600);
  camera.position.set(-8, 19, 48);

  const renderer = new THREE.WebGLRenderer({ antialias: true, alpha: true });
  renderer.setPixelRatio(Math.min(window.devicePixelRatio, 2));
  container.appendChild(renderer.domElement);

  const controls = new OrbitControls(camera, renderer.domElement);
  controls.target.set(0, 1.2, 0);
  controls.enableDamping = true;
  controls.dampingFactor = 0.06;
  controls.maxPolarAngle = Math.PI * 0.49;
  controls.minDistance = 14;
  controls.maxDistance = 160;
  let userMoved = false;
  controls.addEventListener("start", () => { userMoved = true; });

  // ---- lights ------------------------------------------------------
  scene.add(new THREE.HemisphereLight(0xa8d8ff, 0x08192e, 0.95));
  const sun = new THREE.DirectionalLight(0xbfe0ff, 0.7);
  sun.position.set(30, 80, 40);
  scene.add(sun);

  // ---- seabed ------------------------------------------------------
  const bedGeo = new THREE.PlaneGeometry(420, 220, 96, 48);
  {
    const pos = bedGeo.attributes.position;
    for (let i = 0; i < pos.count; i++) {
      const x = pos.getX(i), y = pos.getY(i);
      pos.setZ(i, Math.sin(x * 0.11) * Math.cos(y * 0.13) * 0.9
                 + Math.sin(x * 0.53 + y * 0.31) * 0.28);
    }
    bedGeo.computeVertexNormals();
  }
  const bed = new THREE.Mesh(bedGeo, new THREE.MeshStandardMaterial({
    color: 0x152e49, roughness: 1, metalness: 0 }));
  bed.rotation.x = -Math.PI / 2;
  scene.add(bed);

  // ---- dynamic pipeline line (segments + flanges + km markers) -----
  const flangeMat = new THREE.MeshStandardMaterial({
    color: 0x2c3b57, metalness: 0.8, roughness: 0.32 });
  const supMat = new THREE.MeshStandardMaterial({ color: 0x1d2c42, roughness: 0.9 });

  function buildLine() {
    const n = cfg.num_segments;
    segBounds = [];
    for (let i = 0; i < n; i++) {
      const lo = i * cfg.segment_len_m;
      const hi = i === n - 1 ? cfg.length_m
        : Math.min((i + 1) * cfg.segment_len_m, cfg.length_m);
      segBounds.push([lo, hi]);
    }
    const g = new THREE.Group();
    segMeshes = [];
    const toWorld = (m) => X0 + (m / cfg.length_m) * SPAN;
    for (const [lo, hi] of segBounds) {
      const w0 = toWorld(lo), w1 = toWorld(hi);
      const geo = new THREE.CylinderGeometry(1.25, 1.25, Math.max(w1 - w0 - 0.9, 0.5), 28);
      const mat = new THREE.MeshStandardMaterial({
        color: TIER_HEX.GREEN, metalness: 0.55, roughness: 0.38,
        emissive: TIER_HEX.GREEN, emissiveIntensity: 0.16 });
      const m = new THREE.Mesh(geo, mat);
      m.rotation.z = Math.PI / 2;
      m.position.set((w0 + w1) / 2, PIPE_Y, 0);
      g.add(m);
      segMeshes.push(m);
    }
    for (let i = 0; i <= n; i++) {
      const m = i === n ? cfg.length_m : Math.min(i * cfg.segment_len_m, cfg.length_m);
      const f = new THREE.Mesh(
        new THREE.CylinderGeometry(1.58, 1.58, 1.0, 24), flangeMat);
      f.rotation.z = Math.PI / 2;
      f.position.set(toWorld(m), PIPE_Y, 0);
      g.add(f);
    }
    for (let x = X0 + 5; x < 50; x += 10) {
      const s = new THREE.Mesh(new THREE.BoxGeometry(1.6, PIPE_Y, 1.9), supMat);
      s.position.set(x, PIPE_Y / 2 - 0.55, 0);
      g.add(s);
    }
    // boundary distance markers, thinned when there are many segments
    const step = Math.max(1, Math.ceil((n + 1) / 11));
    for (let i = 0; i <= n; i += 1) {
      if (i % step !== 0 && i !== n) continue;
      const m = i === n ? cfg.length_m : Math.min(i * cfg.segment_len_m, cfg.length_m);
      const spr = textSprite(`${+(m / 1000).toFixed(1)} km`, "#7e8ea6", 44);
      spr.position.set(toWorld(m), 0.55, 6.4);
      g.add(spr);
    }
    return g;
  }

  function disposeGroup(g) {
    g.traverse((o) => {
      if (o.geometry) o.geometry.dispose();
      if (o.material && !(o.material === flangeMat || o.material === supMat)) {
        if (o.material.map) o.material.map.dispose();
        o.material.dispose();
      }
    });
  }

  lineGroup = buildLine();
  scene.add(lineGroup);

  // ---- platforms ---------------------------------------------------
  scene.add(platform(X0 - 1.8, "INLET MANIFOLD", 0x3987e5));
  scene.add(platform(50 + 1.8, "OUTLET TERMINAL", 0xd95926));

  function platform(x, label, dotHex) {
    const g = new THREE.Group();
    const steel = new THREE.MeshStandardMaterial({
      color: 0x33445f, metalness: 0.65, roughness: 0.4 });
    const deck = new THREE.Mesh(new THREE.BoxGeometry(7, 1.1, 7), steel);
    deck.position.y = 8.6;
    g.add(deck);
    for (const [lx, lz] of [[-2.6, -2.6], [2.6, -2.6], [-2.6, 2.6], [2.6, 2.6]]) {
      const leg = new THREE.Mesh(new THREE.CylinderGeometry(0.42, 0.55, 8.6, 10), steel);
      leg.position.set(lx, 4.3, lz);
      g.add(leg);
    }
    const house = new THREE.Mesh(new THREE.BoxGeometry(4.2, 2.6, 3.4),
      new THREE.MeshStandardMaterial({ color: 0x46597a, metalness: 0.4, roughness: 0.5 }));
    house.position.y = 10.4;
    g.add(house);
    const riser = new THREE.Mesh(new THREE.CylinderGeometry(0.62, 0.62, 8.0, 12),
      new THREE.MeshStandardMaterial({ color: 0x2c3b57, metalness: 0.7, roughness: 0.35 }));
    riser.position.set(0, 4.6, 0);
    g.add(riser);
    const beacon = new THREE.PointLight(dotHex, 8, 26);
    beacon.position.set(0, 12.4, 0);
    g.add(beacon);
    const lamp = new THREE.Mesh(new THREE.SphereGeometry(0.34, 12, 12),
      new THREE.MeshBasicMaterial({ color: dotHex }));
    lamp.position.set(0, 12.4, 0);
    g.add(lamp);
    const spr = textSprite(label, "#cfe0f5", 60);
    spr.position.set(0, 14.6, 0);
    g.add(spr);
    g.position.x = x;
    beacons.push(beacon);
    return g;
  }

  // ---- leak marker + bubble plume ----------------------------------
  const leakGroup = new THREE.Group();
  const ringGeo = new THREE.TorusGeometry(2.2, 0.09, 10, 40);
  const ringMat = new THREE.MeshBasicMaterial({ color: 0xd03b3b, transparent: true });
  const ring = new THREE.Mesh(ringGeo, ringMat);
  ring.rotation.x = Math.PI / 2;
  ring.position.y = PIPE_Y;
  leakGroup.add(ring);

  const pin = new THREE.Mesh(new THREE.ConeGeometry(0.9, 2.4, 16),
    new THREE.MeshStandardMaterial({ color: 0xd03b3b, emissive: 0xd03b3b,
      emissiveIntensity: 0.55 }));
  pin.rotation.x = Math.PI;
  pin.position.y = PIPE_Y + 4.4;
  leakGroup.add(pin);
  const leakLight = new THREE.PointLight(0xd03b3b, 14, 30);
  leakLight.position.y = PIPE_Y + 2;
  leakGroup.add(leakLight);
  const leakLabel = textSprite("LEAK", "#ff9d9d", 58);
  leakLabel.position.y = PIPE_Y + 7.0;
  leakGroup.add(leakLabel);

  const N_BUB = 160;
  const bubGeo = new THREE.BufferGeometry();
  const bubPos = new Float32Array(N_BUB * 3);
  const bubSeed = new Float32Array(N_BUB * 2);
  for (let i = 0; i < N_BUB; i++) {
    bubSeed[i * 2] = Math.random();
    bubSeed[i * 2 + 1] = Math.random() * Math.PI * 2;
    bubPos[i * 3 + 1] = -100;
  }
  bubGeo.setAttribute("position", new THREE.BufferAttribute(bubPos, 3));
  const bubbles = new THREE.Points(bubGeo, new THREE.PointsMaterial({
    color: 0xbfe6ff, size: 0.55, transparent: true, opacity: 0.85,
    sizeAttenuation: true, depthWrite: false }));
  leakGroup.add(bubbles);
  leakGroup.visible = false;
  scene.add(leakGroup);

  // ---- isolation valves --------------------------------------------
  const valveMat = new THREE.MeshStandardMaterial({
    color: 0xd03b3b, emissive: 0xd03b3b, emissiveIntensity: 0.4,
    metalness: 0.5, roughness: 0.4 });
  const valves = [makeValve(), makeValve()];
  function makeValve() {
    const g = new THREE.Group();
    const body = new THREE.Mesh(new THREE.BoxGeometry(1.7, 3.4, 3.4), valveMat);
    body.position.y = PIPE_Y;
    g.add(body);
    const stem = new THREE.Mesh(new THREE.CylinderGeometry(0.22, 0.22, 2.6, 10), valveMat);
    stem.position.y = PIPE_Y + 2.8;
    g.add(stem);
    const wheel = new THREE.Mesh(new THREE.TorusGeometry(0.85, 0.14, 8, 22), valveMat);
    wheel.rotation.x = Math.PI / 2;
    wheel.position.y = PIPE_Y + 4.1;
    g.add(wheel);
    g.visible = false;
    g.scale.y = 0.01;
    scene.add(g);
    return g;
  }

  // ---- ambient particulates ----------------------------------------
  const dustGeo = new THREE.BufferGeometry();
  const N_DUST = 350;
  const dustPos = new Float32Array(N_DUST * 3);
  for (let i = 0; i < N_DUST; i++) {
    dustPos[i * 3] = (Math.random() - 0.5) * 220;
    dustPos[i * 3 + 1] = Math.random() * 30;
    dustPos[i * 3 + 2] = (Math.random() - 0.5) * 90;
  }
  dustGeo.setAttribute("position", new THREE.BufferAttribute(dustPos, 3));
  scene.add(new THREE.Points(dustGeo, new THREE.PointsMaterial({
    color: 0x8fb4d9, size: 0.16, transparent: true, opacity: 0.35,
    depthWrite: false })));

  // ---- leak info card (dual-ended tooltip, anchored to the marker) --
  const leakCard = document.createElement("div");
  leakCard.className = "leak-card";
  leakCard.hidden = true;
  container.appendChild(leakCard);
  const _proj = new THREE.Vector3();

  // ---- state -------------------------------------------------------
  let isolatedSeg = null, valveProgress = 0, alarm = false;

  // ---- animate -----------------------------------------------------
  const clock = new THREE.Clock();
  let idleAngle = 0;
  function animate() {
    requestAnimationFrame(animate);
    const dt = Math.min(clock.getDelta(), 0.05);
    const t = clock.elapsedTime;

    if (!userMoved) {           // slow cinematic drift until the user grabs it
      idleAngle += dt * 0.045;
      camera.position.x = Math.sin(idleAngle) * 13 - 6;
      camera.position.z = Math.cos(idleAngle * 0.7) * 7 + 46;
      camera.position.y = 19;
    }
    controls.update();

    for (const b of beacons) b.intensity = 5 + Math.sin(t * 3.1) * 3;

    if (leakGroup.visible) {
      const s = 1 + 0.55 * Math.sin(t * 4.2);
      ring.scale.setScalar(Math.max(0.3, s));
      ringMat.opacity = 0.75 - 0.35 * Math.sin(t * 4.2);
      pin.position.y = PIPE_Y + 4.4 + Math.sin(t * 2.4) * 0.35;
      leakLight.intensity = 10 + Math.sin(t * 6) * 6;
      const pos = bubGeo.attributes.position;
      for (let i = 0; i < N_BUB; i++) {
        const life = ((t * (0.25 + bubSeed[i * 2] * 0.4)) + bubSeed[i * 2]) % 1;
        const h = life * 16;
        pos.setX(i, Math.sin(bubSeed[i * 2 + 1] + h * 0.7) * (0.4 + life * 1.7));
        pos.setY(i, PIPE_Y + 0.8 + h);
        pos.setZ(i, Math.cos(bubSeed[i * 2 + 1] * 2 + h * 0.5) * (0.4 + life * 1.4));
      }
      pos.needsUpdate = true;
      bubbles.material.opacity = 0.85;
    }

    if (isolatedSeg != null && valveProgress < 1) {
      valveProgress = Math.min(1, valveProgress + dt * 0.8);
      const sy = 0.01 + valveProgress * 0.99;
      for (const v of valves) { v.scale.y = sy; }
    }
    if (alarm) {
      const k = 0.4 + 0.25 * (Math.sin(t * 5) > 0 ? 1 : 0);
      for (const v of valves) v.children[0].material.emissiveIntensity = k;
    }

    if (leakGroup.visible && !leakCard.hidden) {
      _proj.set(leakGroup.position.x, PIPE_Y + 8.6, 0).project(camera);
      if (_proj.z < 1) {
        leakCard.style.left = ((_proj.x * 0.5 + 0.5) * container.clientWidth) + "px";
        leakCard.style.top = ((-_proj.y * 0.5 + 0.5) * container.clientHeight) + "px";
        leakCard.style.visibility = "visible";
      } else {
        leakCard.style.visibility = "hidden";   // marker behind the camera
      }
    }

    renderer.render(scene, camera);
  }

  function resize() {
    const w = container.clientWidth, h = container.clientHeight;
    if (!w || !h) return;
    renderer.setSize(w, h);
    camera.aspect = w / h;
    camera.updateProjectionMatrix();
  }
  new ResizeObserver(resize).observe(container);
  resize();
  animate();

  // ---- public API --------------------------------------------------
  return {
    rebuild(newCfg) {
      cfg = { ...newCfg };
      scene.remove(lineGroup);
      disposeGroup(lineGroup);
      lineGroup = buildLine();
      scene.add(lineGroup);
      this.setLeak(null);
      this.setIsolation(null);
    },
    setSegments(tiers) {   // ["GREEN", ...] — length matches active config
      tiers.forEach((tier, i) => {
        if (!segMeshes[i]) return;
        const hex = TIER_HEX[tier] ?? TIER_HEX.GREEN;
        segMeshes[i].material.color.setHex(hex);
        segMeshes[i].material.emissive.setHex(hex);
      });
    },
    setLeak(xM, info = null) {
      if (xM == null) {
        leakGroup.visible = false; leakCard.hidden = true;
        return;
      }
      leakGroup.position.x = X0 + (xM / cfg.length_m) * SPAN;
      leakGroup.visible = true;
      if (info) {
        const html = leakCardHtml(info);
        if (leakCard.innerHTML !== html) leakCard.innerHTML = html;
        leakCard.hidden = false;
      } else {
        leakCard.hidden = true;
      }
    },
    setIsolation(segment) {
      if (segment == null) {
        isolatedSeg = null; valveProgress = 0; alarm = false;
        for (const v of valves) { v.visible = false; v.scale.y = 0.01; }
        return;
      }
      if (isolatedSeg === segment) return;
      isolatedSeg = segment; valveProgress = 0; alarm = true;
      const [lo, hi] = segBounds[segment - 1] || [0, cfg.length_m];
      valves[0].position.x = X0 + (lo / cfg.length_m) * SPAN;
      valves[1].position.x = X0 + (hi / cfg.length_m) * SPAN;
      for (const v of valves) v.visible = true;
    },
  };

  // ---- helpers -----------------------------------------------------
  function textSprite(text, cssColor, px) {
    const pad = 14, cv = document.createElement("canvas");
    const ctx = cv.getContext("2d");
    ctx.font = `700 ${px}px system-ui, sans-serif`;
    const tw = ctx.measureText(text).width;
    cv.width = Math.ceil(tw + pad * 2);
    cv.height = px + pad * 2;
    const c2 = cv.getContext("2d");
    c2.font = `700 ${px}px system-ui, sans-serif`;
    c2.fillStyle = cssColor;
    c2.textBaseline = "middle";
    c2.shadowColor = "rgba(0,0,0,.7)"; c2.shadowBlur = 8;
    c2.fillText(text, pad, cv.height / 2);
    const tex = new THREE.CanvasTexture(cv);
    tex.colorSpace = THREE.SRGBColorSpace;
    const spr = new THREE.Sprite(new THREE.SpriteMaterial({
      map: tex, transparent: true, depthWrite: false }));
    const scale = 0.045;
    spr.scale.set(cv.width * scale, cv.height * scale, 1);
    return spr;
  }
}

// module-level list filled by platform(); declared here for hoisting clarity
const beacons = [];
