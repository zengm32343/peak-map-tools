# peak-map-tools

Open-source tools for mapping the daily islands of **PEAK**, used by [PEAK Map Today](https://peakmaptoday.org).

## See it live

Everything these tools capture ends up on [peakmaptoday.org](https://peakmaptoday.org), updated every day at 17:00 UTC:

- [Today's interactive map](https://peakmaptoday.org/map/): every luggage, belltower, critter, amulet and tomb on today's island
- [Biome rotation](https://peakmaptoday.org/today/biomes/): today's lineup and the next week of islands
- [Today's belltowers](https://peakmaptoday.org/today/belltowers/) and [today's Tomb](https://peakmaptoday.org/today/tombs/)
- [How the daily map works](https://peakmaptoday.org/guides/how-the-daily-map-works/): reset time, the 21-day cycle and what stays the same between runs

| Tool | What it does |
| --- | --- |
| [`peak-shot/`](peak-shot/) | BepInEx plugin that renders a 2D screenshot of every island segment from inside the game and records where each point of interest sits on it. |
| [`peak-extractor/`](peak-extractor/) | Python tool that reads world positions and the daily level rotation straight from your local game files, and fetches which island is live today. |

Both work only with your own, legally obtained copy of PEAK. This repository contains no game files,
assemblies or extracted assets, and must not: `ref/`, `bin/` and unpacked data are git-ignored.

## How the daily island is chosen

PEAK plays a fixed list of 21 islands (`Level_0` … `Level_20`), one per day, switching at 17:00 UTC:

    index = floor(hours since 2025-06-14 17:00 UTC / 24)
    level = Level_(index mod 21)

The game normally takes the index from its login server, which has always matched this formula so far.
`peak-extractor fetch-day` reads it from there; please call it at most once a day.

## License

MIT, see [LICENSE](LICENSE). PEAK and all of its assets belong to Aggro Crab and Landfall. This is an
unofficial fan project, not affiliated with or endorsed by them.
