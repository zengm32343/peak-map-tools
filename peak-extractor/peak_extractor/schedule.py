"""Daily level rotation, mirroring the game's offline fallback.

Evidence (Assembly-CSharp, PEAK 2.6.b):
  NextLevelService.CreateFallbackData():
      epoch = new DateTime(2025, 6, 14, 17, 0, 0)
      index = floor(floor((UtcNow - epoch).TotalHours) / 24)
  MapBaker.GetLevel(index) -> ScenePaths[index % ScenePaths.Length]
  ScenePaths (resources.assets, MapBaker asset) = Level_0 .. Level_20 in order.

Online, the index comes from the login server (LoginResponse.LevelIndex), which
may differ from this fallback (e.g. if the developers skip or pin a day).
"""
from __future__ import annotations

from datetime import date, datetime, timedelta, timezone

EPOCH = datetime(2025, 6, 14, 17, 0, 0, tzinfo=timezone.utc)
RESET_HOUR_UTC = 17


def level_index_at(when: datetime) -> int:
    if when.tzinfo is None:
        raise ValueError("timezone-aware datetime required")
    hours = int((when - EPOCH).total_seconds() // 3600)
    return hours // 24


def level_for(when: datetime, scene_paths: list[str]) -> str:
    return scene_paths[level_index_at(when) % len(scene_paths)]


def schedule(start: date, days: int, scene_paths: list[str], biome_ids: list[str] | None = None):
    """Yield one entry per 'map day'. A map day D runs D 17:00 UTC -> D+1 17:00 UTC."""
    for i in range(days):
        d = start + timedelta(days=i)
        t = datetime(d.year, d.month, d.day, RESET_HOUR_UTC, 0, 1, tzinfo=timezone.utc)
        idx = level_index_at(t)
        entry = {
            "date": d.isoformat(),
            "startsAtUtc": t.replace(second=0).isoformat().replace("+00:00", "Z"),
            "levelIndex": idx,
            "level": scene_paths[idx % len(scene_paths)],
        }
        if biome_ids:
            entry["biomeId"] = biome_ids[idx % len(biome_ids)]
        yield entry
