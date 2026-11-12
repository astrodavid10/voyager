// Oort cloud point cloud (synthetic, PREDICTED; see pipeline/oort.py).
// Input: float32 n x 4 = (x, y, z, kind), ecliptic J2000 au.
// Fixed pixel size (no size attenuation), additive. No WWT imports.

import { AdditiveBlending, BufferGeometry, Float32BufferAttribute, Points, ShaderMaterial } from "three";

export function createOortPoints(data: Float32Array, dpr: number): Points {
  const n = data.length / 4;
  const pos = new Float32Array(n * 3);
  const kind = new Float32Array(n);
  for (let i = 0; i < n; i++) {
    pos[i * 3] = data[i * 4]; pos[i * 3 + 1] = data[i * 4 + 1]; pos[i * 3 + 2] = data[i * 4 + 2];
    kind[i] = data[i * 4 + 3];
  }
  const geom = new BufferGeometry();
  geom.setAttribute("position", new Float32BufferAttribute(pos, 3));
  geom.setAttribute("kind", new Float32BufferAttribute(kind, 1));
  const mat = new ShaderMaterial({
    uniforms: { uSize: { value: 1.6 * dpr }, uOpacity: { value: 0.32 } },
    transparent: true, depthWrite: false, depthTest: false, blending: AdditiveBlending,
    vertexShader: /* glsl */ `
      attribute float kind;
      uniform float uSize;
      varying vec3 vCol;
      void main() {
        vCol = kind > 1.5 ? vec3(1.0, 0.93, 0.75) : (kind > 0.5 ? vec3(0.78, 0.88, 1.0) : vec3(0.62, 0.8, 1.0));
        gl_Position = projectionMatrix * modelViewMatrix * vec4(position, 1.0);
        gl_PointSize = uSize * (kind > 0.5 ? 1.25 : 1.0);
      }`,
    fragmentShader: /* glsl */ `
      uniform float uOpacity;
      varying vec3 vCol;
      void main() {
        vec2 d = gl_PointCoord - 0.5;
        float a = smoothstep(0.5, 0.15, length(d)) * uOpacity;
        gl_FragColor = vec4(vCol, a);
      }`,
  });
  const pts = new Points(geom, mat);
  pts.frustumCulled = false;
  pts.renderOrder = 3;
  return pts;
}
