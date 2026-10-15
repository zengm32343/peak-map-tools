# peak-extractor

Extracts the points of interest of every daily island in **PEAK** (Aggro Crab / LandCrab)
directly from *your own* local copy of the game, and computes which island is active on a
given day. No game assets are included in this repository; you need a legally obtained install.

Its rotation logic and server check back the daily island shown on [peakmaptoday.org](https://peakmaptoday.org/today/biomes/).

Output per level: segment, biome, world position (x, y, z) and a normalized top-down
coordinate for luggage (normal / big / explorer / ancient / clown / trick), belltowers,
critters (capybara, antlion, beehive spawn, early-worm spawn), amulet statues, the tomb,
respawn statues and campfires.

## Requirements

* Python 3.10+, `pip install -r requirements.txt` (UnityPy)
* ~4 GB free RAM for the one-time unpack, ~4 GB disk for unpacked files
* `PEAK_Data/data.unity3d` from the Windows build (tested: PEAK 2.6.b, Unity 6000.3.15f1)

## Usage

```bash
python -m peak_extractor unpack   --bundle ~/PEAK/PEAK_Data/data.unity3d --out work/unpacked
python -m peak_extractor extract  --data work/unpacked --out out            # all 21 levels
python -m peak_extractor extract  --data work/unpacked --out out --levels Level_3
python -m peak_extractor schedule --data work/unpacked --start 2026-10-01 --days 30
```

`out/Level_N.json`:

```json
{ "level": "Level_3", "rotationIndex": 3, "biomeId": "STAS",
  "biomes": ["Shore","Tropics","Alpine","Swamp"],
  "campfires": [[x,y,z], ...],
  "bounds": {"x": [-250,250], "z": [-450,2350]},
  "objects": [ {"category": "luggage", "type": "big", "segment": 1, "biomeSlot": 2,
                "world": [x,y,z], "topDown": [u,v], "name": "LuggageBig", "path": "..."} ] }
```

`topDown` maps world x/z into a fixed frame shared by all levels (u = x, v = z, 0..1).
`segment` 0..4 is split by the campfires, the last one being the final climb (Kiln / Temple).

## How it works

* `globalgamemanagers` → BuildSettings scene list; the daily islands are
  `Assets/8_SCENES/Generated/Level_0..20`, stored as `level5..level25`.
* `resources.assets` → `MapBaker` asset: `ScenePaths` (rotation order) and `BiomeIDs`
  (`S/T|R/A|M/V|S` = Shore, Tropics|Roots, Alpine|Mesa, Volcano|Swamp).
* In each scene, objects are identified by their MonoBehaviour class (resolved via MonoScript):
  `Luggage`/`LuggageCursed` (+ prefab name for the luggage kind), `GhostFire` (belltower),
  `Capybara`, `Antlion`, `RespawnChest`, `TombTrigger`, `PropSpawner_AmuletStatues`,
  `ScoutStatue`, `Campfire`, and `SingleItemSpawner` named `Beehive_Spawner`/`EarlyWorm_Spawner`.
  Only objects active in hierarchy under `Map/Biome_N` are kept (`Map/VOID` is skipped).
* World positions are computed from the Transform hierarchy (TRS matrices).

## Day rotation

From the game's `NextLevelService` offline fallback:
`index = floor(hours_since(2025-06-14 17:00 UTC) / 24)`, `level = ScenePaths[index % 21]`.
Online the index comes from the game's login server, which could override this.

## Daily fetch (time-sensitive)

```bash
python -m peak_extractor fetch-day --data work/unpacked --out out/day          # server, fallback to formula
python -m peak_extractor fetch-day --data work/unpacked --out out/day --offline
```

Calls the game's own read-only endpoint
`GET https://peaklogin3.azurewebsites.net/api/VersionCheck?version=2.6.b` (no auth) and writes
`out/day/day-<mapDayDate>.json` + `day-latest.json` with `"source": "server" | "fallback"`.
This is the developers' login server, not a public API: call it at most once a day (17:05 UTC, see
`scripts/cron-fetch-day.sh`), never in a loop.

## Top-down maps / verification

```bash
python -m peak_extractor render --data work/unpacked --extract out --out out/maps [--levels Level_3]
python -m peak_extractor verify --data work/unpacked --extract out --out out/verify/report.md \
    --day out/day/day-latest.json [--peakmap path/to/WebApp/data] [--site-cache dir]
```

Maps are drawn from the active MeshColliders (max-height raster, hillshade, 25 m contours,
biome tint) with our markers; 1 px = 1 m, frame x∈[-300,300], z∈[-480,2400].

## 3D level models

```bash
python -m peak_extractor model --data work/unpacked --out out/models [--shots captures] [--levels Level_4]
```

Writes `out/models/Level_N/model.glb` and `model.json` (`{"format": "peak-model/1", "palette": {...}, "stats": {...}}`),
about 2–3 MB per level. Needs `trimesh` and `pyfqmr` (see `requirements.txt`) and
[gltfpack](https://meshoptimizer.org/gltf/) on `PATH` (falls back to `npx gltfpack`).

* Geometry is the visible scene: every enabled `MeshRenderer` under `Map/Biome_N` with its `MeshFilter` mesh.
  No textures or shaders are exported.
* LOD: `LODGroup` entries and `*_AutoLOD/…_LOD_N` children are resolved per object; large objects keep a finer
  LOD (radius > 40 m → LOD0, > 15 m → LOD1, > 6 m → LOD2, else the coarsest).
* Each unique mesh is simplified (pyfqmr) to a cap from its world size and instance count, then written once
  and drawn with GPU instancing (`gltfpack -cc -mi -vpf -km`, `EXT_meshopt_compression` + `EXT_mesh_gpu_instancing`).
* Axes: glTF is right-handed, Unity left-handed, so world x is negated (marker positions need the same flip).
* `palette` gives a stylized two-tone colour per material name — `side` for walls, `top` for upward faces —
  derived from the material's base/top colour parameters. The viewer blends them by face normal.

### Palette calibration (`--shots`)

PEAK's rock and foliage textures are grayscale noise, so the parameter-derived colours only approximate the
in-game look. With `--shots` pointing at [PeakShot](../peak-shot) captures (`<shots>/Level_N/level.json` + images),
each captured view is re-rendered offscreen (moderngl) from the exact camera with every material as a flat ID.
Projected marker `world` positions are checked against the capture's `px` and views that don't line up are skipped.
For pixels away from ID edges and within 900 m, the median screenshot colour per material becomes `side`
(|normal.y| < 0.45) or `top` (normal.y > 0.75). Materials that render where the screenshot shows sky are treated as
hidden at runtime for that view. Materials not seen in a level's own captures use the median over all levels;
anything else keeps the parameter colour. `model.json` gains a `calibration` block (per-view alignment error and
the calibrated material list). Only colours are kept — no pixels from the screenshots end up in the output.

The model files are derived from your own copy of the game; don't commit them to this repository.

## Known limitations

* Amulet *type* per statue is chosen at runtime (`StatueSpawnRandomizationStep`, random offset),
  only the location is static.
* Spawners (beehives, early worms) give the spawn point, the item itself appears at runtime.

## License

MIT. PEAK and its assets are property of their owners; this project ships no game data.
