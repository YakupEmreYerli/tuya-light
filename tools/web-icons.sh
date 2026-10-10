#!/bin/sh
# Renders the phone page's icons from docs/brand/logo.svg. The PNGs are full
# squares, because iOS and Android round the corners themselves; the SVG keeps
# the logo's own corners for browser tabs. Needs rsvg-convert (librsvg).
set -eu
root=$(cd "$(dirname "$0")/.." && pwd)
out="$root/backend/src/tuya_light/static"
square=$(mktemp --suffix=.svg)
trap 'rm -f "$square"' EXIT
sed 's/ rx="28"//' "$root/docs/brand/logo.svg" > "$square"
rsvg-convert -w 180 -h 180 "$square" -o "$out/apple-touch-icon.png"
rsvg-convert -w 192 -h 192 "$square" -o "$out/icon-192.png"
rsvg-convert -w 512 -h 512 "$square" -o "$out/icon-512.png"
cp "$root/docs/brand/logo.svg" "$out/icon.svg"
echo "icons written to $out"
