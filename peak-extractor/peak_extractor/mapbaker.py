"""Read the MapBaker ScriptableObject (scene order + biome ids) from resources.assets.

The build strips MonoBehaviour type trees, so the fields are recovered from the
raw serialized bytes: Unity serializes string[] / List<string> as
int32 count + (int32 length + utf8 bytes, 4-byte aligned) per item.
"""
from __future__ import annotations

import os
import re
import struct

import UnityPy

BIOME_LETTERS = {  # first letter of Biome.BiomeType, position-dependent
    0: {"S": "Shore"},
    1: {"T": "Tropics", "R": "Roots"},
    2: {"A": "Alpine", "M": "Mesa"},
    3: {"V": "Volcano", "S": "Swamp"},
}


def _read_str_array(buf: bytes, off: int):
    (n,) = struct.unpack_from("<i", buf, off)
    off += 4
    out = []
    for _ in range(n):
        (ln,) = struct.unpack_from("<i", buf, off)
        off += 4
        out.append(buf[off:off + ln].decode("utf-8"))
        off += (ln + 3) & ~3
    return out, off


def read_mapbaker(data_dir: str):
    env = UnityPy.load(os.path.join(data_dir, "resources.assets"))
    for o in env.objects:
        if o.type.name != "MonoBehaviour":
            continue
        raw = bytes(o.get_raw_data())
        if b"Generated/Level_" not in raw or b"MapBaker" not in raw:
            continue
        first = raw.index(b"Assets/8_SCENES/Generated/Level_")
        # walk back to the array header: [count][len]["Assets/..."]
        off = first - 8
        scenes, off = _read_str_array(raw, off)
        biome_ids, _ = _read_str_array(raw, off)
        return scenes, biome_ids
    raise RuntimeError("MapBaker asset not found")


def decode_biome_id(bid: str) -> list[str]:
    return [BIOME_LETTERS.get(i, {}).get(ch, ch) for i, ch in enumerate(bid)]
