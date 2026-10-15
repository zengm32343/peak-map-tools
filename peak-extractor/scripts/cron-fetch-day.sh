#!/usr/bin/env bash
# Cron-friendly daily fetch. It calls the developers' login server, so run it
# once a day, just after the reset (UTC host):
#   5 17 * * *  /path/to/peak-extractor/scripts/cron-fetch-day.sh
# Env: PEAK_DATA (unpacked dir), PEAK_OUT (default out/day), PEAK_VERSION (default 2.6.b),
#      STEAM_MANIFEST (optional appmanifest_3527290.acf to watch buildid)
set -euo pipefail
cd "$(dirname "$0")/.."
OUT="${PEAK_OUT:-out/day}"
python -m peak_extractor fetch-day --data "${PEAK_DATA:?set PEAK_DATA}" --out "$OUT" --version "${PEAK_VERSION:-2.6.b}"
if [[ -n "${STEAM_MANIFEST:-}" && -f "$STEAM_MANIFEST" ]]; then
  bid=$(sed -n 's/.*"buildid"[[:space:]]*"\([0-9]*\)".*/\1/p' "$STEAM_MANIFEST" | head -1)
  prev=$(cat "$OUT/.buildid" 2>/dev/null || true)
  echo "$bid" > "$OUT/.buildid"
  if [[ -n "$prev" && "$prev" != "$bid" ]]; then
    echo "STEAM BUILD CHANGED $prev -> $bid : re-run unpack + extract + render + verify" >&2
    exit 3
  fi
fi
