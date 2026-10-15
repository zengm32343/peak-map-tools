from datetime import datetime, timezone
from peak_extractor.schedule import level_index_at, schedule
from peak_extractor.mapbaker import decode_biome_id

NAMES = [f"Level_{i}" for i in range(21)]

def utc(*a):
    return datetime(*a, tzinfo=timezone.utc)

def test_epoch():
    assert level_index_at(utc(2025, 6, 14, 17, 0, 0)) == 0
    assert level_index_at(utc(2025, 6, 15, 16, 59, 59)) == 0
    assert level_index_at(utc(2025, 6, 15, 17, 0, 0)) == 1

def test_anchor_matches_site():
    # peakmaptoday tests anchor 2026-09-22 -> Level_3
    assert level_index_at(utc(2026, 9, 22, 17, 0, 1)) % 21 == 3
    assert level_index_at(utc(2026, 9, 22, 16, 59, 0)) % 21 == 2

def test_schedule_rolls():
    from datetime import date
    s = list(schedule(date(2026, 9, 22), 22, NAMES))
    assert s[0]["level"] == "Level_3" and s[21]["level"] == "Level_3"

def test_biome_decode():
    assert decode_biome_id("SRMS") == ["Shore", "Roots", "Mesa", "Swamp"]
    assert decode_biome_id("STAV") == ["Shore", "Tropics", "Alpine", "Volcano"]


def test_map_day_start():
    from peak_extractor.fetch import map_day_start
    assert map_day_start(utc(2026, 10, 14, 14, 0, 0)) == utc(2026, 10, 13, 17, 0, 0)
    assert map_day_start(utc(2026, 10, 14, 17, 0, 0)) == utc(2026, 10, 14, 17, 0, 0)


def test_fallback_record_offline():
    from peak_extractor.fetch import build_day_record
    r = build_day_record(scene_paths=NAMES, biome_ids=["STMV"] * 21, force_fallback=True)
    assert r["source"] == "fallback" and r["level"] == NAMES[r["levelIndex"] % 21]
