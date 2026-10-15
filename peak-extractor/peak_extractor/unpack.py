"""Unpack PEAK_Data/data.unity3d (a UnityFS bundle) into individual files.

The Windows build ships every scene and asset file inside one ~1.5 GB bundle.
Unpacking needs a few GB of RAM once; afterwards each scene loads in seconds.
"""
from __future__ import annotations

import os
import sys

import UnityPy


def unpack(bundle_path: str, out_dir: str) -> list[str]:
    os.makedirs(out_dir, exist_ok=True)
    env = UnityPy.load(bundle_path)
    bundle = next(iter(env.files.values()))
    written = []
    for name, f in bundle.files.items():
        reader = getattr(f, "reader", f)
        data = getattr(reader, "bytes", None)
        if data is None:
            print(f"skip {name}", file=sys.stderr)
            continue
        dest = os.path.join(out_dir, os.path.basename(name))
        with open(dest, "wb") as fh:
            fh.write(bytes(data))
        written.append(dest)
    return written
