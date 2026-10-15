"""Command line entry point.

  python -m peak_extractor unpack   --bundle ~/PEAK/PEAK_Data/data.unity3d --out work/unpacked
  python -m peak_extractor extract  --data work/unpacked --out out/
  python -m peak_extractor schedule --data work/unpacked --start 2026-10-01 --days 30
  python -m peak_extractor fetch-day --data work/unpacked --out out/day
  python -m peak_extractor render   --data work/unpacked --extract out --out out/maps
  python -m peak_extractor verify   --data work/unpacked --extract out --out out/verify/report.md
"""
from __future__ import annotations

import argparse
import json
import os
from collections import Counter
from datetime import date, datetime, timezone

from . import __version__
from .extract import extract_level, normalize
from .mapbaker import decode_biome_id, read_mapbaker
from .scene import ScriptIndex
from .schedule import level_index_at, schedule
from .unpack import unpack

# Fixed world-space frame for every level so maps line up day to day.
# Observed extents over Level_0..Level_20 (PEAK 2.6.b) with margin.
DEFAULT_BOUNDS = {"x": [-250.0, 250.0], "z": [-450.0, 2350.0]}


def _scene_file_map(data_dir: str) -> dict[str, str]:
    """Build-settings index -> levelN file. Uses globalgamemanagers BuildSettings."""
    import UnityPy
    env = UnityPy.load(os.path.join(data_dir, "globalgamemanagers"))
    for o in env.objects:
        if o.type.name == "BuildSettings":
            scenes = o.read_typetree(check_read=False)["scenes"]
            return {os.path.splitext(os.path.basename(p))[0]: f"level{i}" for i, p in enumerate(scenes)}
    raise RuntimeError("BuildSettings not found")


def cmd_unpack(a):
    files = unpack(os.path.expanduser(a.bundle), a.out)
    print(f"wrote {len(files)} files to {a.out}")


def cmd_extract(a):
    scenes, biome_ids = read_mapbaker(a.data)
    files = _scene_file_map(a.data)
    scripts = ScriptIndex(a.data)
    os.makedirs(a.out, exist_ok=True)
    names = [os.path.splitext(os.path.basename(p))[0] for p in scenes]
    only = set(a.levels.split(",")) if a.levels else None
    summary = []
    for i, name in enumerate(names):
        if only and name not in only:
            continue
        lvl = extract_level(os.path.join(a.data, files[name]), scripts, name)
        lvl["rotationIndex"] = i
        lvl["biomeId"] = biome_ids[i] if i < len(biome_ids) else None
        lvl["biomes"] = decode_biome_id(lvl["biomeId"] or "")
        lvl["generator"] = f"peak-extractor {__version__}"
        normalize(lvl, DEFAULT_BOUNDS)
        with open(os.path.join(a.out, f"{name}.json"), "w") as fh:
            json.dump(lvl, fh, indent=1, ensure_ascii=False)
        c = Counter(f'{o["category"]}:{o["type"]}' for o in lvl["objects"])
        summary.append({"level": name, "biomes": lvl["biomes"], "counts": dict(sorted(c.items()))})
        print(name, lvl["biomeId"], dict(sorted(c.items())))
    with open(os.path.join(a.out, "levels.json"), "w") as fh:
        json.dump({"scenePaths": scenes, "biomeIds": biome_ids, "levels": summary}, fh, indent=1)


def cmd_schedule(a):
    scenes, biome_ids = read_mapbaker(a.data)
    names = [os.path.splitext(os.path.basename(p))[0] for p in scenes]
    start = date.fromisoformat(a.start) if a.start else datetime.now(timezone.utc).date()
    out = list(schedule(start, a.days, names, biome_ids))
    for e in out:
        e["biomes"] = decode_biome_id(e["biomeId"])
    print(json.dumps({
        "source": "offline fallback formula from NextLevelService (server may override)",
        "currentIndexNow": level_index_at(datetime.now(timezone.utc)),
        "days": out,
    }, indent=1))


def cmd_fetch_day(a):
    from .fetch import build_day_record, write_day
    rec = build_day_record(data_dir=a.data, version=a.version, beta=a.beta,
                           timeout=a.timeout, force_fallback=a.offline)
    path = write_day(rec, a.out)
    print(json.dumps({k: rec[k] for k in ("source", "mapDayDate", "levelIndex", "level", "biomeId",
                                          "offlineLevelIndex", "offlineMatchesServer", "versionOkay", "error")}))
    print("wrote", path)
    # non-zero exit only if server was expected and failed AND --strict
    if a.strict and rec["source"] != "server":
        raise SystemExit(2)


def cmd_render(a):
    import numpy as np
    from . import render
    from .scene import Scene, ScriptIndex
    scenes, _ = read_mapbaker(a.data)
    files = _scene_file_map(a.data)
    names = [os.path.splitext(os.path.basename(p))[0] for p in scenes]
    only = set(a.levels.split(",")) if a.levels else None
    bounds = {"x": [-300.0, 300.0], "z": [-480.0, 2400.0]}
    si = ScriptIndex(a.data)
    for name in names:
        if only and name not in only:
            continue
        lj_path = os.path.join(a.extract, f"{name}.json")
        if not os.path.exists(lj_path):
            print("skip (no extract)", name); continue
        with open(lj_path) as fh:
            lj = json.load(fh)
        sc = Scene(os.path.join(a.data, files[name]), si, set())
        tl = render.collect_triangles(a.data, files[name], sc)
        h, s = render.rasterize(tl, bounds, a.res)
        if a.save_grid:
            os.makedirs(os.path.join(a.out, "grids"), exist_ok=True)
            np.savez_compressed(os.path.join(a.out, "grids", f"{name}.npz"), height=h, slot=s,
                                x=np.array(bounds["x"]), z=np.array(bounds["z"]), res=a.res)
        paths = render.render_level(lj, h, s, bounds, a.res, os.path.join(a.out, name))
        print(name, f"tris={sum(len(t) for t, _ in tl)} coverage={np.isfinite(h).mean():.2f}", paths[0])


def cmd_verify(a):
    from .verify import build_report
    day = None
    if a.day and os.path.exists(a.day):
        with open(a.day) as fh:
            day = json.load(fh)
    p = build_report(extract_dir=a.extract, data_dir=a.data, day_record=day, peakmap_dir=a.peakmap,
                     site_cache_dir=a.site_cache, out_path=a.out)
    print("wrote", p)


def main(argv=None):
    p = argparse.ArgumentParser(prog="peak_extractor")
    sub = p.add_subparsers(dest="cmd", required=True)
    u = sub.add_parser("unpack"); u.add_argument("--bundle", required=True); u.add_argument("--out", required=True)
    u.set_defaults(fn=cmd_unpack)
    e = sub.add_parser("extract"); e.add_argument("--data", required=True); e.add_argument("--out", required=True)
    e.add_argument("--levels", help="comma separated, e.g. Level_0,Level_3"); e.set_defaults(fn=cmd_extract)
    s = sub.add_parser("schedule"); s.add_argument("--data", required=True); s.add_argument("--start")
    s.add_argument("--days", type=int, default=21); s.set_defaults(fn=cmd_schedule)
    f = sub.add_parser("fetch-day", help="today's LevelIndex from server, fallback to offline formula")
    f.add_argument("--data", required=True); f.add_argument("--out", default="out/day")
    f.add_argument("--version", default="2.6.b", help="value for ?version= (PlayerSettings.bundleVersion)")
    f.add_argument("--beta", action="store_true"); f.add_argument("--timeout", type=float, default=15.0)
    f.add_argument("--offline", action="store_true", help="skip network, formula only")
    f.add_argument("--strict", action="store_true", help="exit 2 if server unavailable")
    f.set_defaults(fn=cmd_fetch_day)
    r = sub.add_parser("render", help="top-down PNG maps from MeshColliders")
    r.add_argument("--data", required=True); r.add_argument("--extract", required=True)
    r.add_argument("--out", required=True); r.add_argument("--levels"); r.add_argument("--res", type=float, default=1.0)
    r.add_argument("--save-grid", action="store_true"); r.set_defaults(fn=cmd_render)
    v = sub.add_parser("verify", help="compare against PeakMap/site data; writes a report (read-only)")
    v.add_argument("--data", required=True); v.add_argument("--extract", required=True)
    v.add_argument("--out", default="out/verify/report.md"); v.add_argument("--day")
    v.add_argument("--peakmap", help="PeakMap WebApp/data dir (optional)")
    v.add_argument("--site-cache", help="dir with cached schedule.json + level-N.json; else fetch live")
    v.set_defaults(fn=cmd_verify)
    a = p.parse_args(argv)
    a.fn(a)


if __name__ == "__main__":
    main()
