"""Classify points of interest inside one generated PEAK level scene."""
from __future__ import annotations

import re

from .scene import Scene, ScriptIndex

# Scripts we need to resolve. Identification is by MonoScript class name
# (from Assembly-CSharp) and, for luggage variants, by the prefab instance name.
WANTED = {
    "Luggage", "LuggageCursed", "TrickLuggage", "GhostFire", "Capybara", "Antlion",
    "RespawnChest", "TombTrigger", "Campfire", "PropSpawner_AmuletStatues",
    "ScoutStatue", "SingleItemSpawner", "MapHandler",
}

LUGGAGE_TYPES = {
    "LuggageSmall": "normal",
    "LuggageBig": "big",
    "LuggageEpic": "explorer",
    "LuggageAncient": "ancient",
    "LuggageClown": "clown",
    "LuggageTrick": "trick",
}

# SingleItemSpawner instances whose spawned item is fixed by the prefab name.
ITEM_SPAWNERS = {
    "Beehive_Spawner": ("critter", "beehive"),
    "EarlyWorm_Spawner": ("critter", "early_worm"),
}

BIOME_FOLDER = re.compile(r"^Biome_(\d+)$")


def _base(name: str) -> str:
    return re.sub(r"\s*\(\d+\)$", "", name)


def classify(node) -> tuple[str, str] | None:
    s = set(node.scripts)
    name = _base(node.name)
    if "GhostFire" in s:
        return ("belltower", "belltower")
    if "Capybara" in s:
        return ("critter", "capybara")
    if "Antlion" in s:
        return ("critter", "antlion")
    if "RespawnChest" in s:
        return ("respawn_statue", "respawn_statue")
    if "TombTrigger" in s:
        return ("tomb", "tomb")
    if "PropSpawner_AmuletStatues" in s:
        return ("amulet_statue", "amulet_statue")
    if "ScoutStatue" in s:
        return ("amulet_statue", "peak_scout_statue")
    if "Campfire" in s and name.startswith("Campfire") and name != "Campfire_Flame":
        return ("campfire", name.replace("Campfire-", "").lower() if "-" in name else "campfire")
    if s & {"Luggage", "LuggageCursed"} and name in LUGGAGE_TYPES:
        return ("luggage", LUGGAGE_TYPES[name])
    if "SingleItemSpawner" in s and name in ITEM_SPAWNERS:
        return ITEM_SPAWNERS[name]
    return None


def extract_level(scene_path: str, scripts: ScriptIndex, level_name: str) -> dict:
    sc = Scene(scene_path, scripts, WANTED)
    children: dict[int, list[int]] = {}
    for g, n in sc.nodes.items():
        if n.parent_go is not None:
            children.setdefault(n.parent_go, []).append(g)

    biomes: dict[int, str] = {}
    objects = []
    for g, n in sc.nodes.items():
        if not n.scripts:
            continue
        cat = classify(n)
        if cat is None:
            continue
        path = sc.path_of(g)
        if len(path) < 2 or path[0] != "Map" or path[1] == "VOID":
            continue  # VOID = post-game variant, not part of the daily climb
        if not sc.active_in_hierarchy(g):
            continue
        m = BIOME_FOLDER.match(path[1])
        biome_slot = int(m.group(1)) if m else None
        if biome_slot is not None and len(path) > 2:
            biomes[biome_slot] = path[2]
        pos_go = g
        if cat[0] == "amulet_statue" and cat[1] == "amulet_statue" and children.get(g):
            pos_go = children[g][0]  # baked statue placed by the level generator
        x, y, z = sc.world_pos(pos_go)
        objects.append({
            "category": cat[0],
            "type": cat[1],
            "name": _base(sc.nodes[pos_go].name),
            "biomeSlot": biome_slot,
            "world": [round(x, 3), round(y, 3), round(z, 3)],
            "path": "/".join(path[1:]),
        })

    # Segment split: ordered campfires (by z) close each segment, same as the
    # in-game climb; anything past the last campfire is the final (peak) section.
    fires = sorted((o for o in objects if o["category"] == "campfire"), key=lambda o: o["world"][2])
    edges = [f["world"][2] + 10.0 for f in fires]
    for o in objects:
        z = o["world"][2]
        o["segment"] = next((i for i, e in enumerate(edges) if z <= e), len(edges))

    return {
        "level": level_name,
        "biomeFolders": {str(k): v for k, v in sorted(biomes.items())},
        "campfires": [f["world"] for f in fires],
        "objects": sorted(objects, key=lambda o: (o["segment"], o["category"], o["world"][2])),
    }


def normalize(level: dict, bounds: dict) -> dict:
    """Add top-down normalized coordinates (u = x, v = z, both 0..1)."""
    x0, x1 = bounds["x"]
    z0, z1 = bounds["z"]
    for o in level["objects"]:
        x, _, z = o["world"]
        o["topDown"] = [round((x - x0) / (x1 - x0), 5), round((z - z0) / (z1 - z0), 5)]
    level["bounds"] = bounds
    return level
