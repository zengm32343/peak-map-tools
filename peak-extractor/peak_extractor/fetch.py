"""Fetch today's LevelIndex from the live PEAK login API (read-only).

Evidence (Assembly-CSharp CloudAPI.CheckVersion, PEAK 2.6.b):
  GET https://peaklogin3.azurewebsites.net/api/VersionCheck?version=<BuildVersion.ToMatchmaking()>
  beta builds use https://peaklogin-beta.azurewebsites.net/...
  No auth headers; UnityWebRequest.Get; body is LoginResponse JSON.

LoginResponse fields (LoginResponse.cs):
  VersionOkay, HoursUntilLevel, MinutesUntilLevel, SecondsUntilLevel,
  LevelIndex, Message, CrossplaySteam/Xbox/PlayStation/Switch.

Application.version (PlayerSettings.bundleVersion) is "2.6.b". The decompiled
ctor is `new BuildVersion(Application.version, "???")`; BuildName == "beta"
switches host. Empirically `?version=2.6.b` returns VersionOkay=true and a
usable LevelIndex. ToMatchmaking source is in Zorro.Core (not shipped here);
we treat Application.version as the query value unless overridden.

What changes daily: LevelIndex, Hours/Minutes/SecondsUntilLevel, Message.
What changes rarely: VersionOkay (vs client version), Crossplay* flags.
"""
from __future__ import annotations

import json
import os
import urllib.error
import urllib.request
from datetime import datetime, timezone

from .mapbaker import decode_biome_id, read_mapbaker
from .schedule import EPOCH, RESET_HOUR_UTC, level_index_at

DEFAULT_URL = "https://peaklogin3.azurewebsites.net/api/VersionCheck"
BETA_URL = "https://peaklogin-beta.azurewebsites.net/api/VersionCheck"
DEFAULT_VERSION = "2.6.b"
USER_AGENT = "peak-extractor/0.1 (+local read-only VersionCheck)"


def fetch_login(version: str = DEFAULT_VERSION, beta: bool = False, timeout: float = 15.0) -> dict:
    base = BETA_URL if beta else DEFAULT_URL
    url = f"{base}?version={urllib.request.quote(version, safe='')}"
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT, "Accept": "application/json"})
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        body = resp.read().decode("utf-8")
        status = resp.status
    data = json.loads(body)
    data["_meta"] = {"url": url, "httpStatus": status, "fetchedAtUtc": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")}
    return data


def map_day_start(when: datetime) -> datetime:
    """Start of the map-day containing `when` (daily reset at 17:00 UTC)."""
    when = when.astimezone(timezone.utc)
    start = when.replace(hour=RESET_HOUR_UTC, minute=0, second=0, microsecond=0)
    if when < start:
        from datetime import timedelta
        start -= timedelta(days=1)
    return start


def build_day_record(
    *,
    data_dir: str | None = None,
    scene_paths: list[str] | None = None,
    biome_ids: list[str] | None = None,
    version: str = DEFAULT_VERSION,
    beta: bool = False,
    timeout: float = 15.0,
    force_fallback: bool = False,
) -> dict:
    """Prefer live server LevelIndex; fall back to offline formula with a clear source flag."""
    now = datetime.now(timezone.utc)
    if scene_paths is None or biome_ids is None:
        if not data_dir:
            raise ValueError("data_dir or scene_paths+biome_ids required")
        scene_paths, biome_ids = read_mapbaker(data_dir)
    names = [os.path.splitext(os.path.basename(p))[0] for p in scene_paths]
    n = len(names)
    offline_idx = level_index_at(now)
    day_start = map_day_start(now)

    source = "fallback"
    server = None
    error = None
    idx = offline_idx
    version_okay = None
    message = ""
    countdown = None
    crossplay = None

    if not force_fallback:
        try:
            server = fetch_login(version=version, beta=beta, timeout=timeout)
            if "LevelIndex" in server and isinstance(server["LevelIndex"], int):
                idx = server["LevelIndex"]
                source = "server"
                version_okay = server.get("VersionOkay")
                message = server.get("Message") or ""
                countdown = {
                    "hours": server.get("HoursUntilLevel"),
                    "minutes": server.get("MinutesUntilLevel"),
                    "seconds": server.get("SecondsUntilLevel"),
                }
                crossplay = {
                    "steam": server.get("CrossplaySteam"),
                    "xbox": server.get("CrossplayXbox"),
                    "playstation": server.get("CrossplayPlayStation"),
                    "switch": server.get("CrossplaySwitch"),
                }
            else:
                error = "response missing LevelIndex"
        except (urllib.error.URLError, urllib.error.HTTPError, TimeoutError, json.JSONDecodeError, ValueError) as e:
            error = f"{type(e).__name__}: {e}"

    rot = idx % n
    biome_id = biome_ids[rot] if biome_ids else None
    record = {
        "fetchedAtUtc": now.isoformat().replace("+00:00", "Z"),
        "mapDayStartsAtUtc": day_start.isoformat().replace("+00:00", "Z"),
        "mapDayDate": day_start.date().isoformat(),
        "source": source,
        "levelIndex": idx,
        "rotationIndex": rot,
        "level": names[rot],
        "biomeId": biome_id,
        "biomes": decode_biome_id(biome_id or ""),
        "offlineLevelIndex": offline_idx,
        "offlineMatchesServer": (idx == offline_idx) if source == "server" else None,
        "versionQueried": version,
        "versionOkay": version_okay,
        "message": message,
        "countdown": countdown,
        "crossplay": crossplay,
        "epochUtc": EPOCH.isoformat().replace("+00:00", "Z"),
        "resetUtcHour": RESET_HOUR_UTC,
        "sceneCount": n,
        "error": error,
        "serverRaw": {k: v for k, v in (server or {}).items() if not k.startswith("_")} if server else None,
        "serverMeta": (server or {}).get("_meta"),
    }
    return record


def write_day(record: dict, out_dir: str) -> str:
    os.makedirs(out_dir, exist_ok=True)
    path = os.path.join(out_dir, f"day-{record['mapDayDate']}.json")
    latest = os.path.join(out_dir, "day-latest.json")
    with open(path, "w") as fh:
        json.dump(record, fh, indent=2, ensure_ascii=False)
        fh.write("\n")
    with open(latest, "w") as fh:
        json.dump(record, fh, indent=2, ensure_ascii=False)
        fh.write("\n")
    return path
