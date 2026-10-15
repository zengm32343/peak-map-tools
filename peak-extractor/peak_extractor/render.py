"""Top-down map rendering from PEAK level MeshColliders (our own drawing)."""
from __future__ import annotations

import os
import re

import numpy as np
import UnityPy
from UnityPy.helpers.MeshHelper import MeshHandler

BIOME_RE = re.compile(r"^Biome_(\d+)$")

MARKER_STYLE = {
    ("luggage", "normal"): ((200, 160, 90), 4, "o"),
    ("luggage", "big"): ((230, 130, 40), 5, "o"),
    ("luggage", "explorer"): ((60, 200, 230), 6, "o"),
    ("luggage", "ancient"): ((190, 90, 230), 7, "o"),
    ("luggage", "clown"): ((255, 80, 160), 6, "o"),
    ("luggage", "trick"): ((255, 255, 255), 5, "o"),
    ("belltower", "belltower"): ((255, 230, 60), 8, "d"),
    ("campfire", None): ((255, 70, 30), 9, "^"),
    ("respawn_statue", None): ((120, 255, 140), 7, "s"),
    ("amulet_statue", None): ((240, 240, 240), 7, "s"),
    ("tomb", None): ((150, 150, 150), 9, "s"),
    ("critter", None): ((160, 255, 60), 5, "d"),
}
BIOME_TINT = {
    "Shore": (214, 200, 150), "Tropics": (90, 160, 80), "Roots": (110, 120, 70),
    "Alpine": (215, 225, 235), "Mesa": (200, 130, 80), "Volcano": (150, 70, 50),
    "Swamp": (110, 120, 120),
}


def _load_env(data_dir: str, scene_file: str):
    files = [os.path.join(data_dir, scene_file)]
    for fn in sorted(os.listdir(data_dir)):
        if re.fullmatch(r"sharedassets\d+\.assets", fn) or fn == "resources.assets":
            files.append(os.path.join(data_dir, fn))
    return UnityPy.load(*files)


def _mesh_arrays(mesh_obj, cache: dict):
    key = (mesh_obj.assets_file.name, mesh_obj.path_id)
    if key in cache:
        return cache[key]
    res = None
    try:
        h = MeshHandler(mesh_obj.read())
        h.process()
        v = np.asarray(h.m_Vertices, dtype=np.float32).reshape(-1, 3)
        tris = [t for sub in h.get_triangles() for t in sub]
        t = np.asarray(tris, dtype=np.int64).reshape(-1, 3)
        if len(v) and len(t):
            res = (v, t)
    except Exception:  # noqa: BLE001
        res = None
    cache[key] = res
    return res


def collect_triangles(data_dir: str, scene_file: str, scene):
    env = _load_env(data_dir, scene_file)
    cache: dict = {}
    out = []
    for o in env.objects:
        if o.type.name != "MeshCollider" or o.assets_file.name != scene_file:
            continue
        d = o.read_typetree(check_read=False)
        if d.get("m_IsTrigger") or not d.get("m_Enabled", 1):
            continue
        gid = d["m_GameObject"]["m_PathID"]
        if gid not in scene.nodes:
            continue
        path = scene.path_of(gid)
        if len(path) < 2 or path[0] != "Map" or path[1] == "VOID":
            continue
        if not scene.active_in_hierarchy(gid):
            continue
        mb = BIOME_RE.match(path[1])
        slot = int(mb.group(1)) if mb else 0
        try:
            mesh = o.read().m_Mesh.deref()
        except Exception:  # noqa: BLE001
            continue
        arr = _mesh_arrays(mesh, cache)
        if arr is None:
            continue
        v, t = arr
        M = np.asarray(scene.world_matrix(scene.nodes[gid].tf_id), dtype=np.float64)
        wv = v @ M[:, :3].T + M[:, 3]
        out.append((wv[t].astype(np.float32), slot))
    return out


def rasterize(tri_list, bounds, res: float):
    x0, x1 = bounds["x"]; z0, z1 = bounds["z"]
    W = int(np.ceil((x1 - x0) / res)); H = int(np.ceil((z1 - z0) / res))
    height = np.full(H * W, -np.inf, dtype=np.float32)
    slot = np.zeros(H * W, dtype=np.int8)
    for tris, s in tri_list:
        a, b, c = tris[:, 0], tris[:, 1], tris[:, 2]
        ext = np.maximum.reduce([
            np.abs(a - b)[:, [0, 2]].max(1),
            np.abs(b - c)[:, [0, 2]].max(1),
            np.abs(a - c)[:, [0, 2]].max(1),
        ])
        k = np.clip(np.ceil(ext / res * 1.5).astype(int), 1, 300)
        for kk in np.unique(k):
            sel = k == kk
            A, B, C = a[sel], b[sel], c[sel]
            i, j = np.meshgrid(np.arange(kk + 1), np.arange(kk + 1), indexing="ij")
            m = (i + j) <= kk
            u = (i[m] / kk).astype(np.float32); w = (j[m] / kk).astype(np.float32)
            chunk = max(1, 2_000_000 // max(len(u), 1))
            for start in range(0, len(A), chunk):
                Ab, Bb, Cb = A[start:start + chunk], B[start:start + chunk], C[start:start + chunk]
                P = (Ab[:, None, :] * (1 - u - w)[None, :, None]
                     + Bb[:, None, :] * u[None, :, None]
                     + Cb[:, None, :] * w[None, :, None]).reshape(-1, 3)
                px = ((P[:, 0] - x0) / res).astype(np.int64)
                pz = ((P[:, 2] - z0) / res).astype(np.int64)
                ok = (px >= 0) & (px < W) & (pz >= 0) & (pz < H)
                idx = pz[ok] * W + px[ok]; y = P[ok, 1]
                np.maximum.at(height, idx, y)
                top = height[idx] == y
                slot[idx[top]] = s
    return height.reshape(H, W), slot.reshape(H, W)


def _style(o):
    return MARKER_STYLE.get((o["category"], o["type"])) or MARKER_STYLE.get((o["category"], None)) \
        or ((255, 0, 255), 5, "o")


def shade(height: np.ndarray, slot: np.ndarray, biomes: list[str], res: float) -> np.ndarray:
    valid = np.isfinite(height)
    if valid.any():
        fill = float(np.nanmin(np.where(valid, height, np.nan)))
    else:
        fill = 0.0
    h = np.where(valid, height, fill)
    gz, gx = np.gradient(h, res)
    az, alt = np.radians(315), np.radians(45)
    slope = np.arctan(np.hypot(gx, gz)); aspect = np.arctan2(-gx, gz)
    hs = np.sin(alt) * np.cos(slope) + np.cos(alt) * np.sin(slope) * np.cos(az - aspect)
    hs = np.clip(0.35 + 0.75 * hs, 0, 1.2)
    tint = np.zeros(h.shape + (3,), np.float32)
    for s in np.unique(slot):
        name = biomes[s - 1] if 1 <= s <= len(biomes) else "Shore"
        tint[slot == s] = BIOME_TINT.get(name, (180, 180, 180))
    img = tint * hs[..., None]
    contour = (np.floor(h / 25.0) != np.floor(np.roll(h, 1, 0) / 25.0)) | \
              (np.floor(h / 25.0) != np.floor(np.roll(h, 1, 1) / 25.0))
    img[contour & valid] *= 0.6
    img[~valid] = (28, 52, 80)
    return np.clip(img, 0, 255).astype(np.uint8)[::-1]


def draw_markers(im, objects, bounds, res, legend=True):
    from PIL import ImageDraw
    d = ImageDraw.Draw(im)
    x0, z1 = bounds["x"][0], bounds["z"][1]
    for o in sorted(objects, key=lambda o: o["category"] == "luggage", reverse=True):
        x, _, z = o["world"]
        u = (x - x0) / res; v = (z1 - z) / res
        col, r, shp = _style(o)
        box = [u - r, v - r, u + r, v + r]
        if shp == "o":
            d.ellipse(box, fill=col, outline=(0, 0, 0))
        elif shp == "s":
            d.rectangle(box, fill=col, outline=(0, 0, 0))
        elif shp == "^":
            d.polygon([(u, v - r), (u - r, v + r), (u + r, v + r)], fill=col, outline=(0, 0, 0))
        else:
            d.polygon([(u, v - r), (u + r, v), (u, v + r), (u - r, v)], fill=col, outline=(0, 0, 0))
    if legend:
        y = 8
        for (cat, typ), (col, r, _) in MARKER_STYLE.items():
            d.rectangle([8, y, 20, y + 12], fill=col, outline=(0, 0, 0))
            d.text((26, y), f"{cat}{':' + typ if typ else ''}", fill=(255, 255, 255))
            y += 16
    return im


def render_level(level_json: dict, height, slot, bounds, res, out_dir: str, pad_m: float = 60.0):
    from PIL import Image
    os.makedirs(out_dir, exist_ok=True)
    name = level_json["level"]
    rgb = shade(height, slot, level_json.get("biomes", []), res)
    full = draw_markers(Image.fromarray(rgb), level_json["objects"], bounds, res)
    paths = []
    p = os.path.join(out_dir, f"{name}_full.png"); full.save(p, optimize=True); paths.append(p)
    camps = sorted(c[2] for c in level_json.get("campfires", []))
    edges = [bounds["z"][0]] + camps + [bounds["z"][1]]
    for seg in range(len(edges) - 1):
        objs = [o for o in level_json["objects"] if o.get("segment") == seg]
        zs = [o["world"][2] for o in objs] or [edges[seg], edges[seg + 1]]
        za = max(bounds["z"][0], min(min(zs), edges[seg]) - pad_m)
        zb = min(bounds["z"][1], max(max(zs), edges[seg + 1]) + pad_m)
        top = int((bounds["z"][1] - zb) / res); bot = int((bounds["z"][1] - za) / res)
        crop = rgb[top:bot].copy()
        seg_img = Image.fromarray(crop)
        # markers: image top corresponds to world z = bounds.z[1] - top*res
        draw_markers(seg_img, objs, {"x": bounds["x"], "z": [za, bounds["z"][1] - top * res]}, res, legend=(seg == 0))
        p = os.path.join(out_dir, f"{name}_seg{seg}.png"); seg_img.save(p, optimize=True); paths.append(p)
    return paths
