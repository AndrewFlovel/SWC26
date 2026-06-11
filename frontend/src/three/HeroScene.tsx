import { useMemo, useRef } from 'react';
import { Canvas, useFrame } from '@react-three/fiber';
import * as THREE from 'three';

function BloodBall() {
  const outer = useRef<THREE.Mesh>(null);
  const inner = useRef<THREE.Mesh>(null);

  useFrame((state, delta) => {
    if (outer.current) {
      outer.current.rotation.y += delta * 0.12;
      outer.current.rotation.x += delta * 0.04;
    }
    if (inner.current) {
      inner.current.rotation.y -= delta * 0.2;
      const breathe = 1 + Math.sin(state.clock.elapsedTime * 0.8) * 0.04;
      inner.current.scale.setScalar(breathe);
    }
  });

  return (
    <group position={[0, 0.4, 0]}>
      <mesh ref={outer}>
        <icosahedronGeometry args={[2.4, 1]} />
        <meshStandardMaterial
          color="#d90429"
          emissive="#8a0303"
          emissiveIntensity={0.7}
          wireframe
          transparent
          opacity={0.85}
        />
      </mesh>
      <mesh ref={inner}>
        <icosahedronGeometry args={[1.55, 0]} />
        <meshStandardMaterial
          color="#1a060a"
          emissive="#d90429"
          emissiveIntensity={0.25}
          roughness={0.2}
          metalness={0.8}
          flatShading
        />
      </mesh>
    </group>
  );
}

function BloodMist({ count = 900 }: { count?: number }) {
  const points = useRef<THREE.Points>(null);

  const positions = useMemo(() => {
    const arr = new Float32Array(count * 3);
    const rng = (spread: number) => (Math.random() - 0.5) * spread;
    for (let i = 0; i < count; i += 1) {
      arr[i * 3] = rng(26);
      arr[i * 3 + 1] = rng(16);
      arr[i * 3 + 2] = rng(18) - 4;
    }
    return arr;
  }, [count]);

  useFrame((state, delta) => {
    if (points.current) {
      points.current.rotation.y += delta * 0.012;
      points.current.position.y = Math.sin(state.clock.elapsedTime * 0.18) * 0.5;
    }
  });

  return (
    <points ref={points}>
      <bufferGeometry>
        <bufferAttribute attach="attributes-position" args={[positions, 3]} />
      </bufferGeometry>
      <pointsMaterial
        color="#d90429"
        size={0.045}
        sizeAttenuation
        transparent
        opacity={0.55}
        depthWrite={false}
        blending={THREE.AdditiveBlending}
      />
    </points>
  );
}

function ParallaxRig() {
  useFrame((state) => {
    const targetX = state.pointer.x * 0.9;
    const targetY = 0.4 + state.pointer.y * 0.45;
    state.camera.position.x = THREE.MathUtils.lerp(state.camera.position.x, targetX, 0.04);
    state.camera.position.y = THREE.MathUtils.lerp(state.camera.position.y, targetY, 0.04);
    state.camera.lookAt(0, 0.4, 0);
  });
  return null;
}

function webglAvailable(): boolean {
  try {
    const canvas = document.createElement('canvas');
    return Boolean(
      canvas.getContext('webgl2') ?? canvas.getContext('webgl'),
    );
  } catch {
    return false;
  }
}

export default function HeroScene() {
  if (!webglAvailable()) {
    return <div className="hero-fallback" />;
  }
  return (
    <div className="hero-canvas">
      <Canvas
        camera={{ position: [0, 0.4, 8.5], fov: 50 }}
        gl={{ antialias: true, alpha: true }}
        dpr={[1, 1.8]}
      >
        <color attach="background" args={['#050406']} />
        <fog attach="fog" args={['#050406', 7, 24]} />
        <ambientLight intensity={0.18} />
        <pointLight position={[6, 5, 6]} intensity={60} color="#d90429" />
        <pointLight position={[-7, -3, 4]} intensity={28} color="#5a0a14" />
        <pointLight position={[0, 8, -6]} intensity={18} color="#ffffff" />
        <BloodBall />
        <BloodMist />
        <ParallaxRig />
      </Canvas>
    </div>
  );
}
