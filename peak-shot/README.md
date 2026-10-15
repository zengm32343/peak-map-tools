# PeakShot

BepInEx 5 (Mono) plugin for **PEAK** that renders 2D map screenshots of every daily island and writes the
on-screen position of each point of interest (luggage, belltowers, critters, amulet statues, tombs) to JSON.
It powers the [daily PEAK map](https://peakmaptoday.org/map/) on [peakmaptoday.org](https://peakmaptoday.org). Tested on PEAK 2.6.b.

No game files are included. You need your own copy of PEAK.

## Build

1. Copy the game's managed assemblies (`<PEAK>/PEAK_Data/Managed/*.dll`) into `ref/`.
2. Copy `BepInEx.dll` and `0Harmony.dll` from a BepInEx 5 install into `bin/`.
3. `dotnet build -c Release`

`ref/` and `bin/` are git-ignored: never commit game assemblies.

## Install and run

1. Install [BepInEx 5](https://github.com/BepInEx/BepInEx) (x64, Mono) into the PEAK folder.
2. Copy `PeakShot.dll` to `<PEAK>/BepInEx/plugins/PeakShot/`.
3. Start the game once to create `<PEAK>/BepInEx/config/org.peakmaptoday.peakshot.cfg`, then set:

| Key | Default | Meaning |
| --- | --- | --- |
| `Enabled` | `false` | Run the capture on startup. The game quits when it is done, so keep it `false` to play normally. |
| `OutputDir` | `<PEAK>/peakshot-out` | Where captures are written. |
| `Levels` | `Level_3` | Comma-separated scenes (`Level_3,Level_4`) or `ALL`. |
| `Width` / `Height` | `7680` / `4320` | Render size. |
| `JpgQuality` | `92` | JPEG quality. |

With `Enabled = true` and Steam running, the plugin goes main menu → offline solo → Airport → loads each
`Level_N` in turn → captures → quits. No input is needed. Putting `steam_appid.txt` (`3527290`) in the game
folder lets `PEAK.exe` start directly.

The game leaks memory when it loads many islands in one session; capture about three levels per launch.

## Output: `<OutputDir>/<Level_N>/`

`level_<i>.jpg` (front view, i = 0..4), `level_<i>_side.jpg` (side view, i = 0..2) and `level.json`:

    { "format": "peakshot/1", "scene": "Level_3", "gameVersion": "2.6.b", "capturedUtc": "...", "width": 7680, "height": 4320,
      "segments": [ { "index": 0, "biome": "Shore", "campfire": [x, y, z] | null, "zMax": ..., "yMax": ...,
        "views": [ { "id": "front" | "side", "image": "level_0.jpg", "camera": { "pos": [...], "euler": [...], "fov": 45 },
          "markers": [ { "category": "luggage|respawn|amulet|belltower|critter|tomb", "name": "<GameObject or item name>",
                         "displayName": "LUGGAGE|BIG LUGGAGE|EXPLORER'S LUGGAGE|ANCIENT LUGGAGE|CLOWN LUGGAGE|ANCIENT STATUE|...",
                         "world": [x, y, z], "px": [px, py], "x": 0..1, "y": 0..1 } ] } ] } ] }

`x`, `y` are normalized screen coordinates with the origin at the top left (y down).

Notes:

- Segment 4's `biome` is the raw game enum (for example `Swamp` for the Citadel climb).
- Amulet names may contain U+2019 (’).
- Belltowers are deduplicated by instance.
- A marker belongs to segment *i* when its z is in (zMax[i-1], zMax[i]] (zMax[-1] = -500), its y is at most
  the segment campfire's y + 10, and it is in front of the camera and inside the viewport. Luggage and statues
  must be active in the hierarchy.

## License

MIT. PEAK and its assets belong to Aggro Crab and Landfall; this project is not affiliated with them.
