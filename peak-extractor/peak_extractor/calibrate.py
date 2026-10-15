"""Calibrate the model palette against in-game screenshots (PeakShot captures).

For every captured view the level is re-rendered offscreen from the exact
PeakShot camera with each material as a flat ID, plus the world-space "up-ness"
of the visible face. Pixels where the ID is stable (not on an edge) are paired
with the screenshot, and the median screenshot colour per material and face
class (side / top) becomes the palette. Only colours leave this step.
"""
from __future__ import annotations

import collections
import json
import math
import os

import numpy as np

RES = (1920, 1080)
TOP_NY, SIDE_NY = 0.75, 0.45
MAX_DIST = 900.0
MAX_SAMPLES = 20000
SKY_DIST, SKY_FRAC = 40.0, 0.25

VS = """
#version 330
in vec3 pos;
in vec4 r0; in vec4 r1; in vec4 r2;
uniform mat4 uVP;
out vec3 vWorld;
void main() {
    vec4 p = vec4(pos, 1.0);
    vWorld = vec3(dot(r0, p), dot(r1, p), dot(r2, p));
    gl_Position = uVP * vec4(vWorld, 1.0);
}
"""
FS = """
#version 330
in vec3 vWorld;
uniform float uId;
uniform vec3 uCam;
out vec4 o;
void main() {
    vec3 n = normalize(cross(dFdx(vWorld), dFdy(vWorld)));
    if (dot(n, uCam - vWorld) < 0.0) n = -n;
    o = vec4(uId, n.y, distance(uCam, vWorld), 1.0);
}
"""


def _euler(e):
    """Unity Quaternion.Euler (degrees): rotate Z, then X, then Y."""
    x, y, z = (math.radians(a) for a in e)
    Rx = np.array([[1, 0, 0], [0, math.cos(x), -math.sin(x)], [0, math.sin(x), math.cos(x)]])
    Ry = np.array([[math.cos(y), 0, math.sin(y)], [0, 1, 0], [-math.sin(y), 0, math.cos(y)]])
    Rz = np.array([[math.cos(z), -math.sin(z), 0], [math.sin(z), math.cos(z), 0], [0, 0, 1]])
    return Ry @ Rx @ Rz


def view_proj(cam: dict, aspect: float, near=1.0, far=6000.0) -> np.ndarray:
    R = _euler(cam["euler"])
    c = np.asarray(cam["pos"], dtype=float)
    V = np.eye(4)
    V[:3, :3] = R.T
    V[:3, 3] = -R.T @ c
    f = 1 / math.tan(math.radians(cam["fov"]) / 2)
    P = np.zeros((4, 4))
    P[0, 0] = f / aspect
    P[1, 1] = f
    P[2, 2] = (far + near) / (far - near)
    P[2, 3] = -2 * far * near / (far - near)
    P[3, 2] = 1
    return P @ V


def project(VP, world, size):
    p = VP @ np.array([*world, 1.0])
    return ((p[0] / p[3] + 1) / 2 * size[0], (1 - (p[1] / p[3] + 1) / 2) * size[1])


class Renderer:
    def __init__(self, instances, meshes):
        import moderngl
        self.ctx = moderngl.create_standalone_context(require=330)
        self.prog = self.ctx.program(vertex_shader=VS, fragment_shader=FS)
        self.fbo = self.ctx.framebuffer(
            color_attachments=[self.ctx.texture(RES, 4, dtype="f4")],
            depth_attachment=self.ctx.depth_renderbuffer(RES))
        groups = collections.defaultdict(list)
        for i in instances:
            for si in range(len(meshes[i["mesh"]]["subs"])):
                name = i["mats"][min(si, len(i["mats"]) - 1)]
                if name:
                    groups[(i["mesh"], si, name)].append(i["M"])
        self.names = sorted({k[2] for k in groups})
        ids = {n: k + 1 for k, n in enumerate(self.names)}
        self.draws = []
        vbos = {}
        for (mk, si, name), Ms in groups.items():
            mesh = meshes[mk]
            if not len(mesh["subs"][si]) or not len(mesh["v"]):
                continue
            if mk not in vbos:
                vbos[mk] = self.ctx.buffer(mesh["v"].astype("f4").tobytes())
            ibo = self.ctx.buffer(mesh["subs"][si].astype("u4").tobytes())
            inst = self.ctx.buffer(np.asarray(Ms, dtype="f4").reshape(len(Ms), 12).tobytes())
            vao = self.ctx.vertex_array(self.prog, [(vbos[mk], "3f", "pos"), (inst, "4f 4f 4f/i", "r0", "r1", "r2")],
                                        index_buffer=ibo, index_element_size=4)
            self.draws.append((vao, ids[name], len(Ms)))

    def render(self, cam):
        VP = view_proj(cam, RES[0] / RES[1])
        self.fbo.use()
        self.ctx.enable(self.ctx.DEPTH_TEST)
        self.ctx.disable(self.ctx.CULL_FACE)
        self.fbo.clear(0, 0, 0, 0, depth=1.0)
        self.prog["uVP"].write(VP.T.astype("f4").tobytes())
        self.prog["uCam"].value = tuple(float(v) for v in cam["pos"])
        for vao, mid, n in self.draws:
            self.prog["uId"].value = float(mid)
            vao.render(instances=n)
        buf = np.frombuffer(self.fbo.color_attachments[0].read(), dtype="f4").reshape(RES[1], RES[0], 4)
        return buf[::-1], VP


def sample_view(renderer, cam, image_path, rng):
    """{material: {"side": [rgb...], "top": [rgb...]}} for one screenshot."""
    from PIL import Image
    buf, VP = renderer.render(cam)
    shot = np.asarray(Image.open(image_path).convert("RGB").resize(RES, Image.BOX), dtype=np.uint8)
    mid = buf[..., 0].astype(np.int32)
    stable = mid > 0
    for dy in (-1, 0, 1):
        for dx in (-1, 0, 1):
            stable &= np.roll(np.roll(mid, dy, 0), dx, 1) == mid
    stable &= buf[..., 2] < MAX_DIST
    ny = buf[..., 1]
    # Objects hidden at runtime still render here; where the screenshot shows sky instead, drop the material.
    sky = np.median(shot[mid == 0], axis=0) if (mid == 0).any() else np.array([999.0] * 3)
    skylike = np.linalg.norm(shot.astype(np.float32) - sky, axis=-1) < SKY_DIST
    absent = {k for k in np.unique(mid[stable]) if k and skylike[stable & (mid == k)].mean() > SKY_FRAC}
    out = collections.defaultdict(dict)
    for cls, mask in (("top", ny > TOP_NY), ("side", np.abs(ny) < SIDE_NY)):
        sel = stable & mask
        ids, cols = mid[sel], shot[sel]
        for k in np.unique(ids):
            if k in absent:
                continue
            c = cols[ids == k]
            if len(c) > MAX_SAMPLES:
                c = c[rng.choice(len(c), MAX_SAMPLES, replace=False)]
            out[renderer.names[k - 1]][cls] = c
    return out, VP


def check_alignment(VP, markers, size):
    """Median pixel error between projected marker world positions and PeakShot's own px."""
    errs = [math.dist(project(VP, m["world"], size), m["px"]) for m in markers if "world" in m and "px" in m]
    return float(np.median(errs)) if errs else float("nan")


def collect_samples(level_dir, instances, meshes, rng):
    with open(os.path.join(level_dir, "level.json")) as fh:
        shot = json.load(fh)
    r = Renderer(instances, meshes)
    samples = collections.defaultdict(lambda: collections.defaultdict(list))
    report = []
    for seg in shot["segments"]:
        for view in seg["views"]:
            img = os.path.join(level_dir, view["image"])
            if not os.path.exists(img) or "camera" not in view:
                continue
            s, VP = sample_view(r, view["camera"], img, rng)
            err = check_alignment(VP, view["markers"], (shot["width"], shot["height"]))
            report.append({"image": view["image"], "medianMarkerErrorPx": round(err, 1)})
            if not err < shot["width"] * 0.01:
                continue
            for name, d in s.items():
                for cls, c in d.items():
                    samples[name][cls].append(c)
    r.ctx.release()
    return samples, report


def palette_from(samples, fallback: dict, min_px=200) -> dict:
    out = {}
    for name, fb in fallback.items():
        got = {}
        for cls in ("side", "top"):
            arr = samples.get(name, {}).get(cls)
            if arr is not None and len(arr) >= min_px:
                med = np.median(arr, axis=0)
                got[cls] = "#%02x%02x%02x" % tuple(int(round(v)) for v in med)
        if not got:
            out[name] = dict(fb)
        elif len(got) == 1:
            out[name] = {"side": next(iter(got.values()))}
        else:
            out[name] = got
    return out
