import { useEffect, useMemo, useRef, useState } from 'react';
import { Canvas, useFrame, useThree } from '@react-three/fiber';
import * as THREE from 'three';

/**
 * The home page hero: Orion's mark (a four-point star inside a diamond, ringed
 * by an orbit) floating in a slowly turning constellation, like the banner.
 * Scrolling eases the camera back through the scene.
 *
 * Not rendered on small screens, without WebGL, or with reduced motion: the
 * static banner behind it (in index.astro) is the fallback and the LCP image.
 */
export default function HeroScene() {
  const [enabled, setEnabled] = useState(false);

  useEffect(() => {
    const reduced = window.matchMedia('(prefers-reduced-motion: reduce)').matches;
    const small = window.matchMedia('(max-width: 767px)').matches;
    let webgl = false;
    try {
      webgl = Boolean(document.createElement('canvas').getContext('webgl2'));
    } catch {
      webgl = false;
    }
    setEnabled(!reduced && !small && webgl);
  }, []);

  if (!enabled) return null;

  return (
    <Canvas
      className="hero-canvas"
      dpr={[1, 1.75]}
      camera={{ position: [0, 0, 7.5], fov: 45 }}
      gl={{ antialias: true, alpha: true, powerPreference: 'high-performance' }}
      onCreated={({ gl }) => gl.setClearColor(0x000000, 0)}
    >
      <ScrollCamera />
      <Constellation />
      <OrionMark />
    </Canvas>
  );
}

function ScrollCamera() {
  const { camera, pointer } = useThree();
  useFrame(() => {
    const progress = Math.min(1, window.scrollY / Math.max(1, window.innerHeight));
    const targetZ = 7.5 + progress * 4;
    camera.position.z += (targetZ - camera.position.z) * 0.08;
    camera.position.x += (pointer.x * 0.6 - camera.position.x) * 0.04;
    camera.position.y += (pointer.y * 0.4 - progress * 1.2 - camera.position.y) * 0.04;
    camera.lookAt(0, 0, 0);
  });
  return null;
}

function OrionMark() {
  const group = useRef<THREE.Group>(null);
  const ring = useRef<THREE.Mesh>(null);
  const core = useRef<THREE.Mesh>(null);

  // A four-point "sparkle" star in the XY plane.
  const starGeometry = useMemo(() => {
    const shape = new THREE.Shape();
    const points = 4;
    const outer = 0.62;
    const inner = 0.12;
    for (let i = 0; i < points * 2; i++) {
      const r = i % 2 === 0 ? outer : inner;
      const a = (i / (points * 2)) * Math.PI * 2 + Math.PI / 2;
      const x = Math.cos(a) * r;
      const y = Math.sin(a) * r;
      if (i === 0) shape.moveTo(x, y);
      else shape.lineTo(x, y);
    }
    shape.closePath();
    return new THREE.ShapeGeometry(shape);
  }, []);

  // The curved diamond outline around the star.
  const diamondGeometry = useMemo(() => {
    const curve = new THREE.CatmullRomCurve3(
      [
        new THREE.Vector3(0, 2.1, 0),
        new THREE.Vector3(0.55, 0.55, 0.15),
        new THREE.Vector3(1.35, 0, 0),
        new THREE.Vector3(0.55, -0.55, -0.15),
        new THREE.Vector3(0, -2.1, 0),
        new THREE.Vector3(-0.55, -0.55, 0.15),
        new THREE.Vector3(-1.35, 0, 0),
        new THREE.Vector3(-0.55, 0.55, -0.15),
      ],
      true,
      'centripetal',
    );
    return new THREE.TubeGeometry(curve, 240, 0.07, 16, true);
  }, []);

  useFrame((state, delta) => {
    const t = state.clock.elapsedTime;
    if (group.current) {
      group.current.rotation.y = Math.sin(t * 0.35) * 0.35;
      group.current.position.y = Math.sin(t * 0.8) * 0.06;
    }
    if (ring.current) ring.current.rotation.z += delta * 0.25;
    if (core.current) {
      const s = 1 + Math.sin(t * 2.2) * 0.06;
      core.current.scale.setScalar(s);
    }
  });

  return (
    <group ref={group}>
      <mesh geometry={diamondGeometry}>
        <meshBasicMaterial color="#9bdcff" toneMapped={false} />
      </mesh>
      <mesh geometry={diamondGeometry} scale={1.015}>
        <meshBasicMaterial color="#3b82f6" transparent opacity={0.25} toneMapped={false} blending={THREE.AdditiveBlending} depthWrite={false} />
      </mesh>

      <group rotation={[Math.PI / 2.35, 0.25, 0]}>
        <mesh ref={ring}>
          <torusGeometry args={[2.25, 0.06, 20, 200]} />
          <meshBasicMaterial color="#7dd3fc" toneMapped={false} />
        </mesh>
        <mesh>
          <torusGeometry args={[2.25, 0.16, 16, 200]} />
          <meshBasicMaterial color="#6366f1" transparent opacity={0.16} blending={THREE.AdditiveBlending} depthWrite={false} toneMapped={false} />
        </mesh>
      </group>

      <mesh ref={core} geometry={starGeometry}>
        <meshBasicMaterial color="#ffffff" toneMapped={false} side={THREE.DoubleSide} />
      </mesh>
      <Glow />
    </group>
  );
}

/** A soft radial glow sprite behind the star. */
function Glow() {
  const texture = useMemo(() => {
    const size = 256;
    const canvas = document.createElement('canvas');
    canvas.width = canvas.height = size;
    const ctx = canvas.getContext('2d')!;
    const g = ctx.createRadialGradient(size / 2, size / 2, 0, size / 2, size / 2, size / 2);
    g.addColorStop(0, 'rgba(255,255,255,1)');
    g.addColorStop(0.15, 'rgba(186,230,253,0.85)');
    g.addColorStop(0.45, 'rgba(56,189,248,0.25)');
    g.addColorStop(1, 'rgba(56,189,248,0)');
    ctx.fillStyle = g;
    ctx.fillRect(0, 0, size, size);
    return new THREE.CanvasTexture(canvas);
  }, []);
  return (
    <sprite scale={[3.2, 3.2, 1]}>
      <spriteMaterial map={texture} transparent depthWrite={false} blending={THREE.AdditiveBlending} toneMapped={false} />
    </sprite>
  );
}

function Constellation() {
  const group = useRef<THREE.Group>(null);

  const { points, lines } = useMemo(() => {
    const count = 150;
    const positions: THREE.Vector3[] = [];
    let seed = 7;
    const rand = () => {
      seed = (seed * 16807) % 2147483647;
      return (seed - 1) / 2147483646;
    };
    for (let i = 0; i < count; i++) {
      const v = new THREE.Vector3((rand() - 0.5) * 22, (rand() - 0.5) * 12, (rand() - 0.5) * 10 - 4);
      if (v.length() < 3.2) v.setLength(3.2 + rand() * 2);
      positions.push(v);
    }
    const pointArray = new Float32Array(count * 3);
    positions.forEach((p, i) => pointArray.set([p.x, p.y, p.z], i * 3));

    const segments: number[] = [];
    for (let i = 0; i < count; i++) {
      let links = 0;
      for (let j = i + 1; j < count && links < 3; j++) {
        if (positions[i].distanceTo(positions[j]) < 3.1) {
          segments.push(positions[i].x, positions[i].y, positions[i].z, positions[j].x, positions[j].y, positions[j].z);
          links++;
        }
      }
    }
    const pointsGeometry = new THREE.BufferGeometry();
    pointsGeometry.setAttribute('position', new THREE.BufferAttribute(pointArray, 3));
    const linesGeometry = new THREE.BufferGeometry();
    linesGeometry.setAttribute('position', new THREE.BufferAttribute(new Float32Array(segments), 3));
    return { points: pointsGeometry, lines: linesGeometry };
  }, []);

  useFrame((_, delta) => {
    if (group.current) group.current.rotation.y += delta * 0.02;
  });

  return (
    <group ref={group}>
      <points geometry={points}>
        <pointsMaterial color="#7dd3fc" size={0.07} sizeAttenuation transparent opacity={0.95} toneMapped={false} />
      </points>
      <lineSegments geometry={lines}>
        <lineBasicMaterial color="#2563eb" transparent opacity={0.28} toneMapped={false} />
      </lineSegments>
    </group>
  );
}
