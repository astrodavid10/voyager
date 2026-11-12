"""Minimal glTF 2.0 binary (GLB) writer: no dependencies beyond numpy.

Supports what these models need, and nothing more:
  * triangle meshes with POSITION, NORMAL, COLOR_0 (RGBA float, linear) and uint32 indices
  * morph targets (POSITION and NORMAL deltas) with names (mesh.extras.targetNames)
  * POINTS primitives (mode 0) with COLOR_0
  * unlit, alpha-blended, double-sided materials (KHR_materials_unlit)
  * one node per mesh, with name and extras, under a root node
  * optional animations of morph weights (LINEAR)

Coordinates are written exactly as given. These models are authored in
heliocentric ecliptic J2000 AU (x toward the vernal equinox, z toward ecliptic
north), NOT glTF's conventional Y-up meters; the root node's extras record that
so a consumer (three.js scene, Digistar import) can apply its own conversion.

Gotchas from the glTF spec that bit others:
  - Chunks must be 4-byte aligned (JSON padded with spaces, BIN with zeros).
  - POSITION accessors, including morph-target deltas, MUST carry min/max.
  - COLOR_0 is LINEAR, not sRGB (see srgb_to_linear).
"""

from __future__ import annotations

import json
import struct
from typing import Dict, List, Optional, Sequence

import numpy as np

FLOAT, UINT = 5126, 5125
ARRAY_BUFFER, ELEMENT_ARRAY_BUFFER = 34962, 34963


def srgb_to_linear(c):
    c = np.asarray(c, dtype=float)
    return np.where(c <= 0.04045, c / 12.92, ((c + 0.055) / 1.055) ** 2.4)


class GLB:
    def __init__(self, generator: str = "voyager pipeline"):
        self.bin = bytearray()
        self.j: Dict = {
            "asset": {"version": "2.0", "generator": generator},
            "extensionsUsed": ["KHR_materials_unlit"],
            "buffers": [], "bufferViews": [], "accessors": [], "materials": [],
            "meshes": [], "nodes": [], "scenes": [{"nodes": [0]}], "scene": 0,
        }
        self.j["nodes"].append({"name": "root", "children": []})
        self._mat_cache: Dict[str, int] = {}

    # ── buffers ─────────────────────────────────────────────────────────
    def _view(self, data: bytes, target: Optional[int]) -> int:
        while len(self.bin) % 4:
            self.bin.append(0)
        off = len(self.bin)
        self.bin.extend(data)
        bv = {"buffer": 0, "byteOffset": off, "byteLength": len(data)}
        if target:
            bv["target"] = target
        self.j["bufferViews"].append(bv)
        return len(self.j["bufferViews"]) - 1

    def accessor(self, arr: np.ndarray, kind: str, target: Optional[int] = ARRAY_BUFFER,
                 minmax: bool = False) -> int:
        if kind == "SCALAR" and arr.dtype.kind in "ui":
            a = np.ascontiguousarray(arr, dtype="<u4")
            ctype = UINT
        else:
            a = np.ascontiguousarray(arr, dtype="<f4")
            ctype = FLOAT
        bv = self._view(a.tobytes(), target)
        acc = {"bufferView": bv, "componentType": ctype,
               "count": int(a.shape[0]), "type": kind}
        if minmax:
            acc["min"] = [float(v) for v in np.atleast_1d(a.min(axis=0))]
            acc["max"] = [float(v) for v in np.atleast_1d(a.max(axis=0))]
        self.j["accessors"].append(acc)
        return len(self.j["accessors"]) - 1

    def material(self, name: str, double_sided: bool = True, blend: bool = True) -> int:
        if name in self._mat_cache:
            return self._mat_cache[name]
        m = {"name": name, "doubleSided": double_sided,
             "pbrMetallicRoughness": {"baseColorFactor": [1, 1, 1, 1],
                                      "metallicFactor": 0.0, "roughnessFactor": 1.0},
             "extensions": {"KHR_materials_unlit": {}}}
        if blend:
            m["alphaMode"] = "BLEND"
        self.j["materials"].append(m)
        self._mat_cache[name] = len(self.j["materials"]) - 1
        return self._mat_cache[name]

    # ── meshes ──────────────────────────────────────────────────────────
    def add_mesh(self, name: str, pos: np.ndarray, faces: Optional[np.ndarray] = None,
                 color: Optional[np.ndarray] = None, normals: Optional[np.ndarray] = None,
                 targets: Sequence[Dict] = (), material: str = "shell",
                 extras: Optional[Dict] = None, points: bool = False) -> int:
        """targets: [{"name": str, "pos": abs positions, "normals": abs normals?}]
        (absolute; converted to deltas here)."""
        attrs = {"POSITION": self.accessor(pos, "VEC3", minmax=True)}
        if normals is not None:
            attrs["NORMAL"] = self.accessor(normals, "VEC3")
        if color is not None:
            attrs["COLOR_0"] = self.accessor(color, "VEC4")
        prim = {"attributes": attrs, "material": self.material(material)}
        if points:
            prim["mode"] = 0
        else:
            prim["indices"] = self.accessor(faces.reshape(-1).astype(np.uint32), "SCALAR",
                                            target=ELEMENT_ARRAY_BUFFER, minmax=False)
        if targets:
            tl = []
            for t in targets:
                ta = {"POSITION": self.accessor(t["pos"] - pos, "VEC3", minmax=True)}
                if normals is not None and t.get("normals") is not None:
                    ta["NORMAL"] = self.accessor(t["normals"] - normals, "VEC3")
                tl.append(ta)
            prim["targets"] = tl
        mesh = {"name": name, "primitives": [prim]}
        if targets:
            mesh["weights"] = [0.0] * len(targets)
            mesh["extras"] = {"targetNames": [t["name"] for t in targets]}
        self.j["meshes"].append(mesh)
        node = {"name": name, "mesh": len(self.j["meshes"]) - 1}
        if extras:
            node["extras"] = extras
        self.j["nodes"].append(node)
        nid = len(self.j["nodes"]) - 1
        self.j["nodes"][0]["children"].append(nid)
        return nid

    def animate_weights(self, name: str, node: int, times: np.ndarray, weights: np.ndarray):
        """weights: (n_keys, n_targets)."""
        self.j.setdefault("animations", []).append({
            "name": name,
            "samplers": [{"input": self.accessor(times.astype(float), "SCALAR", target=None, minmax=True),
                          "output": self.accessor(weights.reshape(-1).astype(float), "SCALAR", target=None),
                          "interpolation": "LINEAR"}],
            "channels": [{"sampler": 0, "target": {"node": node, "path": "weights"}}],
        })

    def save(self, path, root_extras: Optional[Dict] = None):
        if root_extras:
            self.j["nodes"][0]["extras"] = root_extras
        while len(self.bin) % 4:
            self.bin.append(0)
        self.j["buffers"] = [{"byteLength": len(self.bin)}]
        js = json.dumps(self.j, separators=(",", ":")).encode("utf-8")
        js += b" " * ((4 - len(js) % 4) % 4)
        total = 12 + 8 + len(js) + 8 + len(self.bin)
        with open(path, "wb") as f:
            f.write(struct.pack("<III", 0x46546C67, 2, total))
            f.write(struct.pack("<II", len(js), 0x4E4F534A)); f.write(js)
            f.write(struct.pack("<II", len(self.bin), 0x004E4942)); f.write(bytes(self.bin))
        return total


def grid_faces(n_rings: int, n_phi: int, cap_start: bool = False) -> np.ndarray:
    """Quads between consecutive rings of an (n_rings x n_phi) grid, wrapped in phi."""
    i = np.arange(n_rings - 1)[:, None]
    j = np.arange(n_phi)[None, :]
    a = i * n_phi + j
    b = i * n_phi + (j + 1) % n_phi
    c = (i + 1) * n_phi + j
    d = (i + 1) * n_phi + (j + 1) % n_phi
    f = np.concatenate([np.stack([a, c, b], -1).reshape(-1, 3),
                        np.stack([b, c, d], -1).reshape(-1, 3)])
    return f


def vertex_normals(pos: np.ndarray, faces: np.ndarray) -> np.ndarray:
    n = np.zeros_like(pos)
    fn = np.cross(pos[faces[:, 1]] - pos[faces[:, 0]], pos[faces[:, 2]] - pos[faces[:, 0]])
    for k in range(3):
        np.add.at(n, faces[:, k], fn)
    ln = np.linalg.norm(n, axis=1, keepdims=True)
    ln[ln == 0] = 1
    return n / ln
