"""Compare our extract + schedule (+ optional server day) against PeakMap / site public data.

Read-only: never writes into the Astro project. Produces a markdown report under out/verify/.
"""
from __future__ import annotations

import collections
import json
import os
import urllib.request
from datetime import date, datetime, timezone

from .mapbaker import decode_biome_id
from .schedule import level_index_at, schedule

SITE_SCHEDULE = "https://peakmaptoday.org/map-data/schedule.json"
SITE_LEVEL = "https://peakmaptoday.org/map-data/levels/level-{n}/index.json"

# Map our (category, type) -> site (type, variant) buckets for rough counts.
OURS_TO_SITE = {
    ("luggage", "normal"): ("luggage", "small"),
    ("luggage", "big"): ("luggage", "big"),
    ("luggage", "explorer"): ("luggage", "epic"),
    ("luggage", "ancient"): ("luggage", "ancient"),
    ("luggage", "clown"): ("luggage", "clown"),
    ("luggage", "trick"): ("luggage", "trick"),
    ("belltower", "belltower"): ("belltower", "belltower"),
    ("critter", "capybara"): ("animal", "capybara"),
    ("critter", "beehive"): ("animal", "beehive"),
    ("critter", "early_worm"): ("animal", "earlyworm"),
    ("critter", "antlion"): ("animal", "antlion"),
}


def _get_json(url: str, timeout: float = 20.0):
    req = urllib.request.Request(url, headers={"User-Agent": "peak-extractor/0.1 (verify)", "Accept": "application/json"})
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return json.loads(resp.read().decode("utf-8"))


def load_our_levels(out_dir: str) -> dict:
    levels = {}
    for fn in os.listdir(out_dir):
        if fn.startswith("Level_") and fn.endswith(".json"):
            with open(os.path.join(out_dir, fn)) as fh:
                levels[fn[:-5]] = json.load(fh)
    return levels


def site_front_counts(level_index: dict) -> collections.Counter:
    c = collections.Counter()
    for seg in level_index.get("segments", []):
        for view in seg.get("views", []):
            if view.get("id") != "front":
                continue
            for m in view.get("markers", []):
                c[(m.get("type"), m.get("variant") or "")] += 1
    return c


def our_counts(level: dict) -> collections.Counter:
    return collections.Counter((o["category"], o["type"]) for o in level.get("objects", []))


def peakmap_counts(peakmap_dir: str, level_name: str) -> collections.Counter:
    c = collections.Counter()
    d = os.path.join(peakmap_dir, level_name)
    if not os.path.isdir(d):
        return c
    for sg in range(5):
        p = os.path.join(d, f"level_{sg}.json")
        if not os.path.exists(p):
            continue
        with open(p) as fh:
            raw = json.load(fh)
        for k, lst in raw.items():
            if isinstance(lst, list):
                for item in lst:
                    name = item.get("Name", "")
                    c[(k, name)] += 1
    return c


def compare_schedule(our_days, site_days: dict, peakmap_days: dict | None):
    rows = []
    for e in our_days:
        d = e["date"]
        site = site_days.get(d)
        site_lvl = site["level"].replace("level-", "Level_") if site else None
        pm = None
        if peakmap_days:
            # PeakMap uses D-M-YYYY
            y, m, day = d.split("-")
            key = f"{int(day)}-{int(m)}-{y}"
            pm = peakmap_days.get(key)
        pm_lvl = pm["Level"] if pm else None
        rows.append({
            "date": d,
            "ours": e["level"],
            "oursBiomes": e.get("biomes") or decode_biome_id(e.get("biomeId") or ""),
            "site": site_lvl,
            "siteBiomes": site.get("biomes") if site else None,
            "peakmap": pm_lvl,
            "peakmapBiomes": pm.get("Biomes") if pm else None,
            "matchSite": site_lvl == e["level"] and (not site or site.get("biomes") == (e.get("biomes") or decode_biome_id(e.get("biomeId") or ""))),
            "matchPeakmap": pm_lvl is None or pm_lvl == e["level"],
        })
    return rows


def build_report(
    *,
    extract_dir: str,
    data_dir: str,
    day_record: dict | None,
    peakmap_dir: str | None,
    site_cache_dir: str | None,
    out_path: str,
) -> str:
    from .mapbaker import read_mapbaker

    scenes, biome_ids = read_mapbaker(data_dir)
    names = [os.path.splitext(os.path.basename(p))[0] for p in scenes]
    our_levels = load_our_levels(extract_dir)

    # site schedule
    if site_cache_dir and os.path.exists(os.path.join(site_cache_dir, "schedule.json")):
        with open(os.path.join(site_cache_dir, "schedule.json")) as fh:
            site_sched = json.load(fh)
    else:
        site_sched = _get_json(SITE_SCHEDULE)

    peakmap_days = None
    if peakmap_dir and os.path.exists(os.path.join(peakmap_dir, "info.json")):
        with open(os.path.join(peakmap_dir, "info.json")) as fh:
            peakmap_days = json.load(fh).get("DayLevels")

    start = min(date.fromisoformat(d) for d in site_sched["days"]) if site_sched.get("days") else date.today()
    our_days = []
    for e in schedule(start, len(site_sched.get("days") or []) or 21, names, biome_ids):
        e["biomes"] = decode_biome_id(e["biomeId"])
        our_days.append(e)
    sched_rows = compare_schedule(our_days, site_sched.get("days", {}), peakmap_days)

    # per-level counts vs site
    level_rows = []
    for i, name in enumerate(names):
        ours = our_levels.get(name)
        if not ours:
            continue
        cache = os.path.join(site_cache_dir or "", f"level-{i}.json") if site_cache_dir else None
        if cache and os.path.exists(cache):
            with open(cache) as fh:
                site_lvl = json.load(fh)
        else:
            try:
                site_lvl = _get_json(SITE_LEVEL.format(n=i))
            except Exception as e:  # noqa: BLE001
                site_lvl = None
                level_rows.append({"level": name, "error": str(e)})
                continue
        oc = our_counts(ours)
        sc = site_front_counts(site_lvl)
        diffs = []
        for ok, sk in OURS_TO_SITE.items():
            ov, sv = oc.get(ok, 0), sc.get(sk, 0)
            if ov != sv:
                diffs.append({"oursKey": f"{ok[0]}:{ok[1]}", "siteKey": f"{sk[0]}:{sk[1]}", "ours": ov, "site": sv, "delta": ov - sv})
        # note categories we have that site maps differently
        extras = {
            "amulet_statue": oc.get(("amulet_statue", "amulet_statue"), 0) + oc.get(("amulet_statue", "peak_scout_statue"), 0),
            "respawn_statue": oc.get(("respawn_statue", "respawn_statue"), 0),
            "tomb": oc.get(("tomb", "tomb"), 0),
            "campfire": sum(v for k, v in oc.items() if k[0] == "campfire"),
            "site_amulet": sum(v for k, v in sc.items() if k[0] == "amulet"),
            "site_luggage_statue": sc.get(("luggage", "statue"), 0),
        }
        pm = peakmap_counts(peakmap_dir, name) if peakmap_dir else None
        level_rows.append({
            "level": name,
            "ourObjectCount": sum(oc.values()),
            "siteFrontMarkerCount": sum(sc.values()),
            "mappedDiffs": diffs,
            "extras": extras,
            "peakmapCategoryTotals": {k: sum(v for (cat, _), v in pm.items() if cat == k) for k in {c for c, _ in pm}} if pm else None,
        })

    now = datetime.now(timezone.utc)
    lines = [
        "# PEAK extractor verification report",
        "",
        f"Generated: `{now.isoformat().replace('+00:00', 'Z')}`",
        f"Extract dir: `{extract_dir}`",
        f"MapBaker scenes: **{len(names)}** (`Level_0`..`Level_{len(names)-1}`)",
        "",
        "## Time-sensitive day (server vs offline)",
        "",
    ]
    if day_record:
        lines += [
            f"- source: **`{day_record.get('source')}`**",
            f"- mapDayDate: `{day_record.get('mapDayDate')}` (starts `{day_record.get('mapDayStartsAtUtc')}`)",
            f"- levelIndex: **{day_record.get('levelIndex')}** → `{day_record.get('level')}` / `{day_record.get('biomeId')}` {day_record.get('biomes')}",
            f"- offlineLevelIndex: {day_record.get('offlineLevelIndex')} (match={day_record.get('offlineMatchesServer')})",
            f"- versionOkay: {day_record.get('versionOkay')} (queried `{day_record.get('versionQueried')}`)",
            f"- countdown: {day_record.get('countdown')}",
            f"- message: {day_record.get('message')!r}",
            f"- error: {day_record.get('error')}",
            "",
        ]
    else:
        lines += [f"- (no day record) offline index now: {level_index_at(now)} → `{names[level_index_at(now) % len(names)]}`", ""]

    match_n = sum(1 for r in sched_rows if r["matchSite"])
    lines += [
        "## Schedule vs peakmaptoday.org / PeakMap info.json",
        "",
        f"Site schedule updatedAt: `{site_sched.get('updatedAt')}`, resetUtcHour={site_sched.get('resetUtcHour')}",
        f"Matching days (level + biomes vs site): **{match_n}/{len(sched_rows)}**",
        "",
        "| date | ours | site | peakmap | match site |",
        "|---|---|---|---|---|",
    ]
    for r in sched_rows:
        lines.append(f"| {r['date']} | {r['ours']} | {r['site']} | {r['peakmap']} | {'✅' if r['matchSite'] else '❌'} |")

    lines += [
        "",
        "## Marker counts (ours extract vs site *front* views only)",
        "",
        "Site coordinates are screenshot-normalized; counts are the fairest apples-to-apples check.",
        "Known asymmetries (not necessarily bugs):",
        "- Site `luggage:statue` ≈ our `respawn_statue` (naming differs).",
        "- Site amulet *variants* are runtime-chosen; we only have statue *locations*.",
        "- Belltower: site/PeakMap always show 14 vs our 7 on Gloom/Swamp levels; PeakMap level_3.json lists every belltower twice (identical screen coords), so the site value is a duplicate, ours is the unique count.",
        "- Luggage normal/big: ours is consistently +2..+10 higher. Likely cause (unverified): import-peakmap.ts drops markers outside each screenshot frame (x/y outside 0..1), and segment cameras don't cover the whole island.",
        "",
    ]
    for lr in level_rows:
        if "error" in lr:
            lines.append(f"### {lr['level']}: ERROR {lr['error']}")
            continue
        lines.append(f"### {lr['level']} — ours objects={lr['ourObjectCount']}, site front markers={lr['siteFrontMarkerCount']}")
        if lr["mappedDiffs"]:
            lines.append("| ours | site | Δ |")
            lines.append("|---|---|---|")
            for d in lr["mappedDiffs"]:
                lines.append(f"| {d['oursKey']}={d['ours']} | {d['siteKey']}={d['site']} | {d['delta']:+d} |")
        else:
            lines.append("_All mapped luggage/critter/belltower buckets match._")
        ex = lr["extras"]
        lines.append(
            f"- extras: amulet_loc={ex['amulet_statue']} (site amulet markers={ex['site_amulet']}), "
            f"respawn={ex['respawn_statue']} (site luggage:statue={ex['site_luggage_statue']}), "
            f"tomb={ex['tomb']}, campfire={ex['campfire']}"
        )
        if lr.get("peakmapCategoryTotals"):
            lines.append(f"- PeakMap category totals (sum over segments): `{lr['peakmapCategoryTotals']}`")
        lines.append("")

    lines += [
        "## What should be scheduled vs one-shot",
        "",
        "| Item | Cadence | Why |",
        "|---|---|---|",
        "| `VersionCheck` LevelIndex (+ countdown, Message) | **Daily ~17:05 UTC** (and optional hourly) | Changes every map-day; can diverge from offline formula |",
        "| Offline fallback recompute | Continuous / on page load | Deterministic; use when server unreachable |",
        "| Steam `appmanifest_*.acf` buildid + `version.txt` | Daily or on Steam update | Detect new game build → re-unpack |",
        "| MapBaker `ScenePaths` length / BiomeIDs | After each buildid change | New levels or biome rotation |",
        "| Full JSON extract of all levels | After MapBaker change | One-shot per game build |",
        "| Top-down map PNGs | After extract | One-shot per game build |",
        "| Site schedule scrape (verify only) | Daily | Catch divergence before publishing |",
        "",
        "## Notes / uncertainties",
        "",
        "- `BuildVersion.ToMatchmaking()` lives in Zorro.Core (not in Assembly-CSharp). Empirically `version=2.6.b` (= PlayerSettings.bundleVersion) yields `VersionOkay=true`.",
        "- No auth / special headers observed on VersionCheck (plain GET).",
        "- Do **not** replace live site data until diffs are understood and intentional.",
        "",
    ]

    os.makedirs(os.path.dirname(out_path) or ".", exist_ok=True)
    text = "\n".join(lines) + "\n"
    with open(out_path, "w") as fh:
        fh.write(text)
    # also dump machine-readable summary
    summary = {
        "generatedAtUtc": now.isoformat().replace("+00:00", "Z"),
        "day": day_record,
        "scheduleMatchSite": match_n,
        "scheduleTotal": len(sched_rows),
        "scheduleRows": sched_rows,
        "levels": level_rows,
    }
    with open(os.path.splitext(out_path)[0] + ".json", "w") as fh:
        json.dump(summary, fh, indent=2, ensure_ascii=False)
        fh.write("\n")
    return out_path
