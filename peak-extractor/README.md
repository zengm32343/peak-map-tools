# peak-extractor

Extracts the points of interest of every daily island in **PEAK** (Aggro Crab / LandCrab)
directly from *your own* local copy of the game, and computes which island is active on a
given day. No game assets are included in this repository; you need a legally obtained install.

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

## Known limitations

* Amulet *type* per statue is chosen at runtime (`StatueSpawnRandomizationStep`, random offset),
  only the location is static.
* Spawners (beehives, early worms) give the spawn point, the item itself appears at runtime.

## License

MIT. PEAK and its assets are property of their owners; this project ships no game data.
