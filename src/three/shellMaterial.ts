// Soap-bubble shell material for the heliosphere surfaces.
//
// A filled translucent shell reads as fog; a rim (fresnel) term makes the
// edge glow and the face nearly clear, which is how a bubble reads. Built as
// a ShaderMaterial that includes three's own morph/color chunks so the GLB's
// morph targets (comet/croissant/bubble/breathe) and RGBA vertex colors keep
// working.
//
// WWT note (sol footgun 20): view-space z is POSITIVE in front of the camera
// here, so never assume a sign on mvPosition.z; the rim uses abs(dot(n, v)).
// No WWT imports (sol footgun 12).

import { AdditiveBlending, DoubleSide, ShaderMaterial } from "three";

export function createShellMaterial(opts: { opacity?: number; power?: number; floor?: number } = {}): ShaderMaterial {
  return new ShaderMaterial({
    uniforms: {
      uOpacity: { value: opts.opacity ?? 1 },
      uPower: { value: opts.power ?? 2.2 },
      uFloor: { value: opts.floor ?? 0.12 },
    },
    vertexColors: true,
    transparent: true,
    depthWrite: false,
    depthTest: false,
    blending: AdditiveBlending,
    side: DoubleSide,
    vertexShader: /* glsl */ `
      #include <common>
      #include <color_pars_vertex>
      #include <morphtarget_pars_vertex>
      #include <logdepthbuf_pars_vertex>
      uniform float uPower;
      varying float vRim;
      void main() {
        #include <color_vertex>
        #include <morphcolor_vertex>
        #include <beginnormal_vertex>
        #include <morphnormal_vertex>
        #include <begin_vertex>
        #include <morphtarget_vertex>
        #include <project_vertex>
        #include <logdepthbuf_vertex>
        vec3 n = normalize(normalMatrix * objectNormal);
        vec3 v = normalize(-mvPosition.xyz);
        vRim = pow(1.0 - abs(dot(n, v)), uPower);
      }`,
    fragmentShader: /* glsl */ `
      #include <common>
      #include <color_pars_fragment>
      #include <logdepthbuf_pars_fragment>
      uniform float uOpacity;
      uniform float uFloor;
      varying float vRim;
      void main() {
        #include <logdepthbuf_fragment>
        float a = vColor.a * (uFloor + (1.0 - uFloor) * vRim) * uOpacity;
        gl_FragColor = vec4(vColor.rgb, a);
        #include <colorspace_fragment>
      }`,
  });
}
