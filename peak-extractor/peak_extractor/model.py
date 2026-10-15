"""Stylized 3D level model from PEAK's visual meshes (MeshRenderer + MeshFilter).

Geometry comes from the game's own meshes; no textures or shaders are exported.
Each material is reduced to two colours (side / top) that the web viewer blends
by surface orientation, so the look is ours while the shapes match the game.

Size control:
  * LODGroup / *_AutoLOD children: big objects keep a finer LOD, small ones the coarsest.
  * every unique mesh is simplified to a cap based on its world size and instance count.
  * identical meshes are written once and drawn with GPU instancing (gltfpack -mi).
"""
from __future__ import annotations

import collections
import colorsys
import os
import re
import shutil
import subprocess
import tempfile

import numpy as np
from UnityPy.helpers.MeshHelper import MeshHandler

from . import render

SKIP_SHADERS = {"Decal", "DarkFade", "W/Character", "GD/Face Cards", "LavaPost", "W/Peak_Mirage"}
LOD_RE = re.compile(r"LOD_?(\d+)$", re.I)
TEX_KEYS = ("_BaseMap", "_MainTex", "_Albedo", "_Texture", "_TopTexture")
# Per unique mesh: drawn triangles summed over all its instances stay under this.
MESH_BUDGET = 120_000


def _key(pptr):
    return (pptr.m_FileID, pptr.m_PathID, pptr.assetsfile.name)


class _Reader:
    def __init__(self):
        self.mats: dict = {}
        self.meshes: dict = {}

    def material(self, pptr):
        k = _key(pptr)
        if k in self.mats:
            return self.mats[k]
        info = None
        try:
            mat = pptr.deref_parse_as_object()
            try:
                shader = mat.m_Shader.deref_parse_as_object().m_ParsedForm.m_Name
            except Exception:  # noqa: BLE001
                shader = "?"
            cols = {name: (c.r, c.g, c.b) for name, c in mat.m_SavedProperties.m_Colors}
            tex = None
            for name, te in mat.m_SavedProperties.m_TexEnvs:
                if name not in TEX_KEYS or not te.m_Texture.m_PathID:
                    continue
                try:
                    img = te.m_Texture.deref_parse_as_object().image.convert("RGBA").resize((32, 32))
                    a = np.asarray(img, dtype=np.float32) / 255
                    opaque = a[..., 3] > 0.5
                    if opaque.sum() > 10:
                        tex = tuple(a[opaque][:, :3].mean(0).tolist())
                        break
                except Exception:  # noqa: BLE001
                    pass
            info = {"name": mat.m_Name, "shader": shader, "colors": cols, "tex": tex}
        except Exception:  # noqa: BLE001
            info = None
        self.mats[k] = info
        return info

    def mesh(self, pptr):
        k = _key(pptr)
        if k not in self.meshes:
            res = None
            try:
                m = pptr.deref_parse_as_object()
                h = MeshHandler(m)
                h.process()
                v = np.asarray(h.m_Vertices, dtype=np.float32).reshape(-1, 3)
                subs = [np.asarray(s, dtype=np.uint32).reshape(-1, 3) for s in h.get_triangles()]
                if len(v):
                    res = {"name": m.m_Name, "v": v, "subs": subs}
            except Exception:  # noqa: BLE001
                res = None
            self.meshes[k] = res
        return k, self.meshes[k]


def collect(data_dir: str, scene_file: str, scene, coarsest_lod: int = 3):
    """Visible map renderers -> (instances, meshes, materials)."""
    env = render._load_env(data_dir, scene_file)
    filters, renderers, lod_rank = {}, [], {}
    for o in env.objects:
        if o.assets_file.name != scene_file:
            continue
        t = o.type.name
        if t == "LODGroup":
            d = o.read_typetree(check_read=False)
            for li, lod in enumerate(d.get("m_LODs") or []):
                for rr in lod.get("renderers") or []:
                    pid = (rr.get("renderer") or {}).get("m_PathID", 0)
                    if pid:
                        lod_rank[pid] = (o.path_id, li)
        elif t == "MeshFilter":
            d = o.read_typetree(check_read=False)
            filters[d["m_GameObject"]["m_PathID"]] = o
        elif t == "MeshRenderer":
            renderers.append(o)

    rd = _Reader()
    cands = []
    for o in renderers:
        d = o.read_typetree(check_read=False)
        gid = d["m_GameObject"]["m_PathID"]
        if gid not in scene.nodes or not d.get("m_Enabled", 1) or not scene.active_in_hierarchy(gid):
            continue
        path = scene.path_of(gid)
        if len(path) < 2 or path[0] != "Map" or path[1] == "VOID":
            continue
        if (d.get("m_StaticBatchInfo") or {}).get("subMeshCount", 0) or gid not in filters:
            continue
        mkey, arr = rd.mesh(filters[gid].read().m_Mesh)
        if arr is None:
            continue
        M = np.asarray(scene.world_matrix(scene.nodes[gid].tf_id), dtype=np.float64)
        ext = (arr["v"].max(0) - arr["v"].min(0)) * np.linalg.norm(M[:, :3], axis=0)
        name = scene.nodes[gid].name
        par = scene.nodes[gid].parent_go
        m = LOD_RE.search(name)
        if o.path_id in lod_rank:
            group, lod = lod_rank[o.path_id]
        elif m and par in scene.nodes and "_AutoLOD" in scene.nodes[par].name:
            group, lod = scene.nodes[par].parent_go, int(m.group(1))
        else:
            group, lod = gid, 0
        mb = render.BIOME_RE.match(path[1])
        cands.append({"obj": o, "mesh": mkey, "M": M, "r": float(np.linalg.norm(ext)) / 2,
                      "group": group, "lod": lod, "slot": int(mb.group(1)) if mb else 0})

    max_lod = collections.defaultdict(int)
    radius = collections.defaultdict(float)
    for c in cands:
        max_lod[c["group"]] = max(max_lod[c["group"]], c["lod"])
        radius[c["group"]] = max(radius[c["group"]], c["r"])

    def wanted(g):
        r = radius[g]
        lod = 0 if r > 40 else 1 if r > 15 else 2 if r > 6 else coarsest_lod
        return min(lod, max_lod[g])

    instances = []
    for c in cands:
        if c["lod"] != wanted(c["group"]):
            continue
        mats = [rd.material(mp) for mp in c["obj"].read().m_Materials]
        if not mats or all(mi is None or mi["shader"] in SKIP_SHADERS for mi in mats):
            continue
        instances.append({"mesh": c["mesh"], "M": c["M"], "r": c["r"], "slot": c["slot"],
                          "mats": [mi["name"] if mi and mi["shader"] not in SKIP_SHADERS else None for mi in mats]})
    meshes = {k: v for k, v in rd.meshes.items() if v is not None}
    materials = {mi["name"]: mi for mi in rd.mats.values() if mi}
    return instances, meshes, materials


def _hex(c, lmin, lmax, sat):
    c = np.clip(np.asarray(c, dtype=float)[:3], 0, 1)
    h, l, s = colorsys.rgb_to_hls(*c)
    r, g, b = colorsys.hls_to_rgb(h, min(lmax, max(lmin, l * 1.15)), min(1.0, s * sat))
    return "#%02x%02x%02x" % (round(r * 255), round(g * 255), round(b * 255))


def palette(materials: dict) -> dict:
    """Two-tone stylized colours per material name: {"side": "#rrggbb", "top": "#rrggbb"?}."""
    out = {}
    for name, m in sorted(materials.items()):
        cols, sh, tex = m["colors"], m["shader"], m["tex"]
        if "Peak_Rock" in sh:
            side = np.asarray(cols.get("_BaseColor", (0.3, 0.3, 0.3)))
            if tex is not None:
                side = side * 0.5 + np.asarray(tex) * np.asarray(cols.get("_Tint", (1, 1, 1))) * 0.5
            top = cols.get("_TopColor")
            entry = {"side": _hex(side, 0.4, 0.8, 0.9)}
            if top is not None and min(top) < 0.95:
                entry["top"] = _hex(top, 0.4, 0.82, 1.15)
        elif "Foliage" in sh:
            base = np.asarray(cols.get("_BaseColor") or tex or (0.3, 0.6, 0.3))[:3]
            sec = np.asarray(cols.get("_TopColorSecondary", base))[:3]
            if colorsys.rgb_to_hls(*np.clip(base, 0, 1))[2] < 0.2:
                base = sec * 0.8
            entry = {"side": _hex(base, 0.28, 0.7, 1.2), "top": _hex(sec, 0.3, 0.7, 1.1)}
        else:
            base = np.asarray(cols.get("_BaseColor") or cols.get("_Color") or (1, 1, 1))
            if tex is not None:
                base = base * np.asarray(tex)
            entry = {"side": _hex(base, 0.32, 0.82, 1.15)}
        out[name] = entry
    return out


def _simplify(v, t, target):
    if len(t) <= target:
        return v, t
    import pyfqmr
    s = pyfqmr.Simplify()
    s.setMesh(v.astype(np.float64), t.astype(np.int32))
    s.simplify_mesh(target_count=target, aggressiveness=7, preserve_border=False, verbose=False)
    nv, nt, _ = s.getMesh()
    return nv.astype(np.float32), nt.astype(np.uint32)


def build_glb(instances, meshes, colors: dict, out_path: str) -> dict:
    """Write an instanced, meshopt-compressed GLB (Unity left-handed -> glTF right-handed)."""
    import trimesh

    count = collections.Counter(i["mesh"] for i in instances)
    rmax = collections.defaultdict(float)
    for i in instances:
        rmax[i["mesh"]] = max(rmax[i["mesh"]], i["r"])

    def cap(k):
        r = rmax[k]
        c = 300 if r < 3 else 800 if r < 8 else 2500 if r < 20 else 8000 if r < 50 else 20000
        return max(150, min(c, MESH_BUDGET // count[k]))

    S = np.diag([-1.0, 1, 1, 1])
    scene = trimesh.Scene()
    pbr = {}
    geoms: dict = {}
    drawn = 0
    for n, i in enumerate(instances):
        mesh = meshes[i["mesh"]]
        for si, tris in enumerate(mesh["subs"]):
            mname = i["mats"][min(si, len(i["mats"]) - 1)]
            if mname is None:
                continue
            gk = (i["mesh"], si, mname)
            if gk not in geoms:
                v, t = _simplify(mesh["v"], tris, cap(i["mesh"]))
                if len(t) == 0:
                    geoms[gk] = None
                    continue
                used = np.unique(t)
                remap = np.zeros(len(v), np.int64)
                remap[used] = np.arange(len(used))
                v2 = v[used].copy()
                v2[:, 0] *= -1
                if mname not in pbr:
                    rgb = colors.get(mname, {}).get("side", "#999999")
                    pbr[mname] = trimesh.visual.material.PBRMaterial(
                        name=mname, baseColorFactor=[int(rgb[1:3], 16), int(rgb[3:5], 16), int(rgb[5:7], 16), 255],
                        metallicFactor=0.0, roughnessFactor=1.0, doubleSided=True)
                tm = trimesh.Trimesh(vertices=v2, faces=remap[t][:, ::-1], process=False)
                tm.visual = trimesh.visual.TextureVisuals(material=pbr[mname])
                name = f"g{len(geoms)}"
                scene.geometry[name] = tm
                geoms[gk] = (name, len(t))
            g = geoms[gk]
            if g is None:
                continue
            M = np.eye(4)
            M[:3, :4] = i["M"]
            scene.graph.update(frame_to=f"n{n}_{si}", matrix=S @ M @ S, geometry=g[0])
            drawn += g[1]

    with tempfile.TemporaryDirectory() as tmp:
        raw = os.path.join(tmp, "raw.glb")
        scene.export(raw)
        gltfpack = shutil.which("gltfpack")
        cmd = [gltfpack] if gltfpack else ["npx", "-y", "gltfpack"]
        subprocess.run(cmd + ["-i", raw, "-o", out_path, "-cc", "-mi", "-vpf", "-km"],
                       check=True, capture_output=True)
    return {"instances": len(instances), "uniqueTriangles": sum(g[1] for g in geoms.values() if g),
            "drawnTriangles": drawn, "materials": len(pbr), "bytes": os.path.getsize(out_path)}
