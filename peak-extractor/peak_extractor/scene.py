"""Read a built Unity scene (PEAK `levelN` file) and compute world transforms.

Only Unity engine objects (GameObject / Transform / MonoBehaviour headers) are
read; MonoBehaviour field data is not needed because objects are identified by
their script class (resolved through MonoScript objects) and GameObject name.
"""
from __future__ import annotations

import os
from dataclasses import dataclass, field

import UnityPy


def _quat_mat(q):
    x, y, z, w = q["x"], q["y"], q["z"], q["w"]
    return (
        (1 - 2 * (y * y + z * z), 2 * (x * y - w * z), 2 * (x * z + w * y)),
        (2 * (x * y + w * z), 1 - 2 * (x * x + z * z), 2 * (y * z - w * x)),
        (2 * (x * z - w * y), 2 * (y * z + w * x), 1 - 2 * (x * x + y * y)),
    )


def _local(tf):
    p, r, s = tf["m_LocalPosition"], tf["m_LocalRotation"], tf["m_LocalScale"]
    R = _quat_mat(r)
    sc = (s["x"], s["y"], s["z"])
    pos = (p["x"], p["y"], p["z"])
    return [[R[i][0] * sc[0], R[i][1] * sc[1], R[i][2] * sc[2], pos[i]] for i in range(3)]


def _mul(A, B):
    # 3x4 affine matrices
    out = []
    for i in range(3):
        row = []
        for j in range(4):
            v = A[i][0] * B[0][j] + A[i][1] * B[1][j] + A[i][2] * B[2][j]
            if j == 3:
                v += A[i][3]
            row.append(v)
        out.append(row)
    return out


@dataclass
class Node:
    go_id: int
    name: str
    active: bool
    tf_id: int | None = None
    parent_go: int | None = None
    scripts: list[str] = field(default_factory=list)


class ScriptIndex:
    """Map (external file name, path_id) of MonoScript objects -> class name."""

    def __init__(self, data_dir: str, files=("globalgamemanagers.assets",)):
        self.by_file: dict[str, dict[int, str]] = {}
        for fn in files:
            path = os.path.join(data_dir, fn)
            if not os.path.exists(path):
                continue
            env = UnityPy.load(path)
            m = {}
            for o in env.objects:
                if o.type.name == "MonoScript":
                    d = o.read_typetree(check_read=False)
                    ns = d.get("m_Namespace") or ""
                    cls = d.get("m_ClassName") or d.get("m_Name")
                    m[o.path_id] = f"{ns}.{cls}" if ns else cls
            self.by_file[fn] = m

    def lookup(self, ext_name: str, path_id: int) -> str | None:
        return self.by_file.get(os.path.basename(ext_name), {}).get(path_id)


class Scene:
    def __init__(self, path: str, scripts: ScriptIndex, wanted_scripts: set[str] | None = None):
        self.path = path
        env = UnityPy.load(path)
        sf = next(iter(env.files.values()))
        externals = [e.path for e in sf.externals]
        self.transforms: dict[int, dict] = {}
        self.nodes: dict[int, Node] = {}
        tf_owner: dict[int, int] = {}
        mbs = []
        for o in env.objects:
            t = o.type.name
            if t in ("Transform", "RectTransform"):
                self.transforms[o.path_id] = o.read_typetree(check_read=False)
            elif t == "GameObject":
                d = o.read_typetree(check_read=False)
                self.nodes[o.path_id] = Node(o.path_id, d["m_Name"], bool(d.get("m_IsActive", 1)))
            elif t == "MonoBehaviour":
                mbs.append(o)
        for tid, tf in self.transforms.items():
            gid = tf["m_GameObject"]["m_PathID"]
            tf_owner[tid] = gid
            if gid in self.nodes:
                self.nodes[gid].tf_id = tid
        for tid, tf in self.transforms.items():
            father = (tf.get("m_Father") or {}).get("m_PathID", 0)
            gid = tf_owner[tid]
            if father and father in tf_owner and gid in self.nodes:
                self.nodes[gid].parent_go = tf_owner[father]
        for o in mbs:
            d = o.read_typetree(check_read=False)
            s = d["m_Script"]
            fid = s["m_FileID"]
            if fid <= 0 or fid > len(externals):
                continue
            cls = scripts.lookup(externals[fid - 1], s["m_PathID"])
            if cls is None:
                continue
            if wanted_scripts is not None and cls.split(".")[-1] not in wanted_scripts:
                continue
            gid = d["m_GameObject"]["m_PathID"]
            if gid in self.nodes:
                self.nodes[gid].scripts.append(cls.split(".")[-1])
        self._wm: dict[int, list] = {}

    # --- hierarchy helpers -------------------------------------------------
    def ancestors(self, gid: int):
        seen = 0
        while gid is not None and gid in self.nodes and seen < 256:
            yield self.nodes[gid]
            gid = self.nodes[gid].parent_go
            seen += 1

    def path_of(self, gid: int) -> list[str]:
        return [n.name for n in self.ancestors(gid)][::-1]

    def active_in_hierarchy(self, gid: int) -> bool:
        return all(n.active for n in self.ancestors(gid))

    def world_matrix(self, tid: int):
        if tid in self._wm:
            return self._wm[tid]
        chain = []
        cur = tid
        while cur and cur in self.transforms and cur not in self._wm:
            chain.append(cur)
            cur = (self.transforms[cur].get("m_Father") or {}).get("m_PathID", 0)
        base = self._wm.get(cur) if cur in self._wm else None
        for t in reversed(chain):
            L = _local(self.transforms[t])
            base = L if base is None else _mul(base, L)
            self._wm[t] = base
        return self._wm[tid]

    def world_pos(self, gid: int):
        n = self.nodes[gid]
        if n.tf_id is None:
            return None
        m = self.world_matrix(n.tf_id)
        return (m[0][3], m[1][3], m[2][3])
