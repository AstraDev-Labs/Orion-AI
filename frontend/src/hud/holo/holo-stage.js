import * as THREE from 'three';
import { getVoiceLevel } from '../../lib/voiceLevel';
import { CORE_RADIUS, LATTICE_NODES } from './lattice';

let Composer = null, RenderPass = null, BloomPass = null, OutputPass = null;

// Kept as a promise rather than top-level await. TLA is not available in the
// es2020 build target, so `await` at module scope worked in dev (esbuild
// targets esnext there) while failing `npm run build` outright. Bloom is an
// enhancement, so the scene simply renders unbloomed until this resolves.
const postFxReady = (async () => {
  try {
    ({ EffectComposer: Composer } = await import('three/addons/postprocessing/EffectComposer.js'));
    ({ RenderPass } = await import('three/addons/postprocessing/RenderPass.js'));
    ({ UnrealBloomPass: BloomPass } = await import('three/addons/postprocessing/UnrealBloomPass.js'));
    ({ OutputPass } = await import('three/addons/postprocessing/OutputPass.js'));
  } catch (e) { /* bloom is an enhancement */ }
})();

const GOLD = 0xb68235, HOT = 0xfacb8d, MID = 0xe1ad66, DEEP = 0x7d5411, GROUND = 0x100e0b;

// The core is a sphere, not the two-lobe brain this started as. CORE_RADIUS of
// 1.2 is chosen so the volume (~7.2) matches the old brain's (~6.8): the lattice
// keeps the same point density at LATTICE_NODES samples, so the 0.34
// edge-linking threshold below still produces a comparable mesh and needed no
// retuning. Both constants live in ./lattice.ts so the HUD label can quote the
// real figure with real types instead of repeating a literal that goes stale.

function inside(x, y, z) {
  return x * x + y * y + z * z < CORE_RADIUS * CORE_RADIUS;
}

function sampleVolume(n) {
  // Sampling the bounding cube of the sphere rather than the old brain's wider
  // box lifts the rejection-sampling hit rate to ~52%, so this converges fast.
  const pts = []; let guard = 0;
  while (pts.length < n && guard++ < n * 200) {
    const x = (Math.random() * 2 - 1) * CORE_RADIUS,
          y = (Math.random() * 2 - 1) * CORE_RADIUS,
          z = (Math.random() * 2 - 1) * CORE_RADIUS;
    if (inside(x, y, z)) pts.push(new THREE.Vector3(x, y, z));
  }
  return pts;
}

/**
 * The whole room, not just the object: a fogged holo-chamber with a receding
 * grid deck, a caged gyro assembly, drifting dust, and the core lattice
 * suspended at its centre. The HTML panels float in front of this.
 */
class HoloStage extends HTMLElement {
  connectedCallback() {
    if (this._built) return;
    this._built = true;
    this.style.display = 'block';
    if (!this.style.width) this.style.width = '100%';
    if (!this.style.height) this.style.height = '100%';

    const renderer = new THREE.WebGLRenderer({ alpha: true, antialias: true, powerPreference: 'high-performance' });
    renderer.setPixelRatio(Math.min(devicePixelRatio, 2));
    renderer.domElement.style.cssText = 'display:block;width:100%;height:100%';
    this.appendChild(renderer.domElement);

    const scene = new THREE.Scene();
    scene.fog = new THREE.FogExp2(GROUND, 0.052);
    const camera = new THREE.PerspectiveCamera(42, 1, 0.1, 200);
    camera.position.set(0, 0.4, 9.2);

    scene.add(new THREE.AmbientLight(0xffffff, 0.55));
    const key = new THREE.PointLight(MID, 45); key.position.set(4, 4, 5); scene.add(key);
    const fill = new THREE.PointLight(DEEP, 26); fill.position.set(-4, -2, 2); scene.add(fill);

    // ---- the chamber ------------------------------------------------------
    const deck = new THREE.GridHelper(90, 60, GOLD, GOLD);
    deck.material.transparent = true; deck.material.opacity = 0.16;
    deck.position.y = -3.6; scene.add(deck);

    const deckFine = new THREE.GridHelper(30, 60, MID, MID);
    deckFine.material.transparent = true; deckFine.material.opacity = 0.07;
    deckFine.position.y = -3.58; scene.add(deckFine);

    const vault = new THREE.GridHelper(90, 40, GOLD, GOLD);
    vault.material.transparent = true; vault.material.opacity = 0.05;
    vault.position.y = 4.4; scene.add(vault);

    const dome = new THREE.LineSegments(
      new THREE.WireframeGeometry(new THREE.IcosahedronGeometry(14, 2)),
      new THREE.LineBasicMaterial({ color: GOLD, transparent: true, opacity: 0.045 }),
    );
    scene.add(dome);

    const DUST = 900;
    const dustPos = new Float32Array(DUST * 3);
    for (let i = 0; i < DUST; i++) {
      dustPos[i * 3] = (Math.random() - 0.5) * 34;
      dustPos[i * 3 + 1] = (Math.random() - 0.5) * 16;
      dustPos[i * 3 + 2] = (Math.random() - 0.5) * 26;
    }
    const dustGeo = new THREE.BufferGeometry();
    dustGeo.setAttribute('position', new THREE.BufferAttribute(dustPos, 3));
    const dust = new THREE.Points(dustGeo, new THREE.PointsMaterial({
      color: MID, size: 0.035, transparent: true, opacity: 0.5, blending: THREE.AdditiveBlending, depthWrite: false,
    }));
    scene.add(dust);

    // ---- the lattice ------------------------------------------------------
    const rig = new THREE.Group();
    scene.add(rig);

    const pts = sampleVolume(LATTICE_NODES);
    const nodePos = new Float32Array(pts.length * 3), nodeCol = new Float32Array(pts.length * 3);
    const base = new THREE.Color(GOLD), hotC = new THREE.Color(HOT), deepC = new THREE.Color(DEEP);
    pts.forEach((p, i) => { nodePos.set([p.x, p.y, p.z], i * 3); nodeCol.set([base.r, base.g, base.b], i * 3); });
    const nodeGeo = new THREE.BufferGeometry();
    nodeGeo.setAttribute('position', new THREE.BufferAttribute(nodePos, 3));
    nodeGeo.setAttribute('color', new THREE.BufferAttribute(nodeCol, 3));
    rig.add(new THREE.Points(nodeGeo, new THREE.PointsMaterial({
      size: 0.032, vertexColors: true, transparent: true, opacity: 0.85,
      blending: THREE.AdditiveBlending, depthWrite: false,
    })));

    const edges = [];
    for (let i = 0; i < pts.length; i++) {
      let linked = 0;
      for (let j = i + 1; j < pts.length && linked < 3; j++) {
        if (pts[i].distanceTo(pts[j]) < 0.34) { edges.push([i, j]); linked++; }
      }
    }
    const edgePos = new Float32Array(edges.length * 6), edgeCol = new Float32Array(edges.length * 6);
    edges.forEach(([a, b], e) => {
      edgePos.set([pts[a].x, pts[a].y, pts[a].z, pts[b].x, pts[b].y, pts[b].z], e * 6);
      edgeCol.set([deepC.r, deepC.g, deepC.b, deepC.r, deepC.g, deepC.b], e * 6);
    });
    const edgeGeo = new THREE.BufferGeometry();
    edgeGeo.setAttribute('position', new THREE.BufferAttribute(edgePos, 3));
    edgeGeo.setAttribute('color', new THREE.BufferAttribute(edgeCol, 3));
    rig.add(new THREE.LineSegments(edgeGeo, new THREE.LineBasicMaterial({
      vertexColors: true, transparent: true, opacity: 0.28, blending: THREE.AdditiveBlending, depthWrite: false,
    })));

    const PULSES = 110;
    const pulses = Array.from({ length: PULSES }, () => ({ e: (Math.random() * edges.length) | 0, t: Math.random(), v: 0.35 + Math.random() * 0.9 }));
    const pulsePos = new Float32Array(PULSES * 3);
    const pulseGeo = new THREE.BufferGeometry();
    pulseGeo.setAttribute('position', new THREE.BufferAttribute(pulsePos, 3));
    const pulseMat = new THREE.PointsMaterial({
      color: HOT, size: 0.055, transparent: true, opacity: 0.9, blending: THREE.AdditiveBlending, depthWrite: false,
    });
    rig.add(new THREE.Points(pulseGeo, pulseMat));

    const core = new THREE.Mesh(
      new THREE.IcosahedronGeometry(0.26, 1),
      new THREE.MeshStandardMaterial({ color: HOT, emissive: HOT, emissiveIntensity: 1.5, roughness: 0.2, metalness: 0.6 }),
    );
    rig.add(core);
    const halo = new THREE.Mesh(
      new THREE.SphereGeometry(0.55, 24, 24),
      new THREE.MeshBasicMaterial({ color: MID, transparent: true, opacity: 0.08, blending: THREE.AdditiveBlending, depthWrite: false }),
    );
    rig.add(halo);
    rig.add(new THREE.LineSegments(
      new THREE.WireframeGeometry(new THREE.IcosahedronGeometry(2.05, 2)),
      new THREE.LineBasicMaterial({ color: GOLD, transparent: true, opacity: 0.08 }),
    ));

    // ---- caged gyro assembly ---------------------------------------------
    const cage = new THREE.Group();
    scene.add(cage);
    const rings = [2.3, 2.62, 2.94, 4.3, 5.1].map((r, i) => {
      const ring = new THREE.Mesh(
        new THREE.TorusGeometry(r, i > 2 ? 0.008 : 0.005, 6, 240),
        new THREE.MeshBasicMaterial({ color: i === 1 ? MID : GOLD, transparent: true, opacity: i > 2 ? 0.28 : 0.5 }),
      );
      ring.rotation.set(i * 0.5 + 0.3, i * 0.7, i * 0.4);
      cage.add(ring);
      return ring;
    });

    const tickPts = [];
    for (let i = 0; i < 96; i++) {
      const a = (i / 96) * Math.PI * 2, long = i % 8 === 0;
      const r0 = 3.1, r1 = r0 + (long ? 0.2 : 0.08);
      tickPts.push(Math.cos(a) * r0, Math.sin(a) * r0, 0, Math.cos(a) * r1, Math.sin(a) * r1, 0);
    }
    const bezelGeo = new THREE.BufferGeometry();
    bezelGeo.setAttribute('position', new THREE.Float32BufferAttribute(tickPts, 3));
    const bezel = new THREE.LineSegments(bezelGeo, new THREE.LineBasicMaterial({ color: GOLD, transparent: true, opacity: 0.45 }));
    scene.add(bezel);

    // ---- shockwave on click ----------------------------------------------
    const waves = [];
    const waveGeo = new THREE.TorusGeometry(1, 0.012, 4, 180);
    this._down = () => {
      const w = new THREE.Mesh(waveGeo, new THREE.MeshBasicMaterial({ color: HOT, transparent: true, opacity: 0.85 }));
      w.rotation.x = Math.PI / 2;
      w.position.y = -3.55;
      w.userData.age = 0;
      scene.add(w); waves.push(w);
      if (waves.length > 5) { const old = waves.shift(); scene.remove(old); old.material.dispose(); }
    };
    window.addEventListener('pointerdown', this._down);

    // Built twice-safe: once now in case the postprocessing chunk already
    // resolved, and again when it does. Every later use is null-guarded
    // (`composer?.setSize`, `if (composer) ... else renderer.render`), so the
    // first frames simply render without bloom.
    let composer = null;
    const buildComposer = () => {
      if (composer || !(Composer && RenderPass && BloomPass)) return;
      composer = new Composer(renderer);
      composer.addPass(new RenderPass(scene, camera));
      composer.addPass(new BloomPass(new THREE.Vector2(1, 1), 0.42, 0.5, 0.4));
      if (OutputPass) composer.addPass(new OutputPass());
      composer.setSize(this.clientWidth || 1200, this.clientHeight || 700);
    };
    buildComposer();
    postFxReady.then(buildComposer);

    const resize = () => {
      const w = this.clientWidth || 1200, h = this.clientHeight || 700;
      renderer.setSize(w, h, false);
      composer?.setSize(w, h);
      camera.aspect = w / h;
      camera.updateProjectionMatrix();
    };
    resize();
    new ResizeObserver(resize).observe(this);

    let px = 0, py = 0;
    this._move = (e) => {
      px = (e.clientX / innerWidth - 0.5) * 2;
      py = (e.clientY / innerHeight - 0.5) * 2;
    };
    window.addEventListener('pointermove', this._move);

    const clock = new THREE.Clock();
    const colAttr = nodeGeo.getAttribute('color'), edgeAttr = edgeGeo.getAttribute('color');
    const tmp = new THREE.Color();

    // The lattice is dark and inert until the backend link is up: charge eases
    // toward the phase's ceiling, so connecting reads as an ignition rather
    // than a state flag flipping.
    const CHARGE = { offline: 0.05, dialing: 0.16, handshake: 0.34, loading: 0.62, live: 1, lost: 0.1 };
    let charge = 0.05, lastPhase = 'offline';
    let voiceEase = 0;

    const tick = () => {
      this._raf = requestAnimationFrame(tick);
      const d = Math.min(clock.getDelta(), 0.05), t = clock.elapsedTime;
      const state = this.getAttribute('activity') || 'thinking';
      const phase = this.getAttribute('link') || 'offline';

      if (phase !== lastPhase) {
        if (phase === 'live') this._down();
        lastPhase = phase;
      }
      const ceiling = CHARGE[phase] ?? 0.05;
      charge += (ceiling - charge) * Math.min(1, d * 2.2);

      const activityLoad = state === 'idle' ? 0.25 : state === 'listening' ? 0.6 : 1;

      // Real amplitude of the TTS audio currently playing (see lib/voiceLevel.ts),
      // so the core moves with the actual speech rather than a decorative loop.
      // If the analyser can't read the stream -- audio context still suspended,
      // or a browser that blocked it -- fall back to a gentle synthetic breath so
      // 'speaking' never looks identical to 'thinking'.
      let voice = 0;
      if (state === 'speaking') {
        voice = getVoiceLevel();
        if (voice < 0.01) voice = 0.18 + 0.12 * Math.sin(t * 7.5);
      }
      voiceEase += (voice - voiceEase) * Math.min(1, d * 14);

      const load = Math.min(1, activityLoad + voiceEase * 0.55) * charge;

      camera.position.x += (px * 1.5 - camera.position.x) * 0.035;
      camera.position.y += (0.4 - py * 1.1 - camera.position.y) * 0.035;
      camera.position.z = 9.2 + Math.sin(t * 0.12) * 0.35;
      camera.lookAt(0, 0, 0);

      rig.rotation.y += d * 0.12;
      rig.rotation.x = Math.sin(t * 0.18) * 0.09;
      cage.rotation.y -= d * 0.03;
      rings.forEach((ring, i) => {
        ring.rotation.z += d * (0.2 + i * 0.1) * (i % 2 ? -1 : 1) * (0.4 + load);
        ring.rotation.x += d * 0.04 * (i === 1 ? -1 : 1);
      });
      bezel.rotation.z -= d * 0.055;
      dome.rotation.y += d * 0.006;
      dust.rotation.y += d * 0.012;
      deck.position.z = ((deck.position.z + d * 0.5) % 1.5);
      deckFine.position.z = ((deckFine.position.z + d * 0.5) % 0.5);

      const beat = 1 + Math.sin(t * (2.2 + load * 3)) * 0.09 * load;
      rig.scale.setScalar(1 + voiceEase * 0.14);
      core.scale.setScalar(beat * (0.55 + charge * 0.45) * (1 + voiceEase * 0.35));
      core.rotation.y += d * 0.6; core.rotation.x += d * 0.25;
      core.material.emissiveIntensity = 0.15 + charge * 1.5;
      halo.scale.setScalar(beat * (1 + load * 0.18));
      halo.material.opacity = (0.05 + load * 0.06) * charge;
      key.intensity = 8 + charge * 37;
      dust.material.opacity = 0.14 + charge * 0.36;
      pulseMat.opacity = charge * 0.9;
      rings.forEach((ring, i) => { ring.material.opacity = (i > 2 ? 0.28 : 0.5) * (0.28 + charge * 0.72); });

      const scanY = Math.sin(t * 0.45) * 1.5;
      for (let i = 0; i < pts.length; i++) {
        const near = 1 - Math.min(1, Math.abs(pts[i].y - scanY) / 0.22);
        const flick = 0.5 + 0.5 * Math.sin(t * (3 + (i % 11)) + i);
        tmp.copy(deepC).lerp(base, 0.25 + charge * 0.75)
          .lerp(hotC, Math.min(1, near * 1.1 + flick * 0.35 * load) * charge);
        colAttr.setXYZ(i, tmp.r, tmp.g, tmp.b);
      }
      colAttr.needsUpdate = true;

      for (let i = 0; i < PULSES; i++) {
        const p = pulses[i];
        p.t += d * p.v * (0.4 + load);
        if (p.t > 1) { p.t = 0; p.e = (Math.random() * edges.length) | 0; }
        const [a, b] = edges[p.e] || [0, 0];
        const A = pts[a], B = pts[b];
        pulsePos[i * 3] = A.x + (B.x - A.x) * p.t;
        pulsePos[i * 3 + 1] = A.y + (B.y - A.y) * p.t;
        pulsePos[i * 3 + 2] = A.z + (B.z - A.z) * p.t;
        const e6 = p.e * 6, g = 0.35 + 0.65 * load;
        edgeAttr.array[e6] = deepC.r + (hotC.r - deepC.r) * g;
        edgeAttr.array[e6 + 1] = deepC.g + (hotC.g - deepC.g) * g;
        edgeAttr.array[e6 + 2] = deepC.b + (hotC.b - deepC.b) * g;
      }
      pulseGeo.getAttribute('position').needsUpdate = true;
      edgeAttr.needsUpdate = true;

      for (let i = waves.length - 1; i >= 0; i--) {
        const w = waves[i];
        w.userData.age += d;
        const s = 1 + w.userData.age * 9;
        w.scale.setScalar(s);
        w.material.opacity = Math.max(0, 0.85 - w.userData.age * 0.7);
        if (w.material.opacity <= 0.01) { scene.remove(w); w.material.dispose(); waves.splice(i, 1); }
      }

      if (composer) composer.render(); else renderer.render(scene, camera);
    };
    tick();
  }
  disconnectedCallback() {
    if (this._raf) cancelAnimationFrame(this._raf);
    if (this._move) window.removeEventListener('pointermove', this._move);
    if (this._down) window.removeEventListener('pointerdown', this._down);
  }
}
// Guard against redefinition, not a behavior change: Vite HMR re-executes
// this module on edits, and customElements.define() throws if the name is
// already registered -- without this guard, any dev-mode file save anywhere
// in the app crashes the whole page.
if (!customElements.get('holo-stage')) {
  customElements.define('holo-stage', HoloStage);
}
