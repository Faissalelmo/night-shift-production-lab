#!/usr/bin/env bash
# Turn a raw screen recording into a README-friendly MP4 under 2 MB.
#   scripts/make-demo-video.sh <raw-recording> [speed] [output]
#   scripts/make-demo-video.sh ~/Videos/raw-demo.mkv 8 docs/demo.mp4
# speed: playback speed-up (default 8: a 12-minute recording becomes 90 s).
# Needs ffmpeg + ffprobe. H.264, no audio, max 1280 px wide, 12 fps.
set -euo pipefail

IN=${1:?usage: $0 <raw-recording> [speed] [output]}
SPEED=${2:-8}
OUT=${3:-docs/demo.mp4}
MAX_BYTES=$((1950 * 1024))   # a little under 2 MB

DUR=$(ffprobe -v error -show_entries format=duration -of csv=p=0 "$IN")
OUT_DUR=$(awk -v d="$DUR" -v s="$SPEED" 'BEGIN { printf "%.1f", d / s }')
VF="setpts=PTS/${SPEED},fps=12,scale='min(1280,iw)':-2:flags=lanczos,format=yuv420p"
echo "input ${DUR%.*}s, speed ×${SPEED} → output ${OUT_DUR}s"

mkdir -p "$(dirname "$OUT")"
# Pass 1: quality-based. Text-heavy screen captures compress very well.
ffmpeg -hide_banner -loglevel error -y -i "$IN" -an -vf "$VF" \
    -c:v libx264 -preset veryslow -crf 28 -tune stillimage -movflags +faststart "$OUT"
SIZE=$(wc -c < "$OUT")

if (( SIZE > MAX_BYTES )); then
    # Too big: two-pass encode at the exact bitrate that fits (3 % container overhead).
    KBPS=$(awk -v b="$MAX_BYTES" -v d="$OUT_DUR" 'BEGIN { printf "%d", b * 8 * 0.97 / d / 1000 }')
    echo "crf 28 gave $((SIZE / 1024)) KB, re-encoding in two passes at ${KBPS} kbit/s"
    PASSLOG=$(mktemp -d)/pass
    ffmpeg -hide_banner -loglevel error -y -i "$IN" -an -vf "$VF" -c:v libx264 -preset veryslow \
        -b:v "${KBPS}k" -pass 1 -passlogfile "$PASSLOG" -f mp4 /dev/null
    ffmpeg -hide_banner -loglevel error -y -i "$IN" -an -vf "$VF" -c:v libx264 -preset veryslow \
        -b:v "${KBPS}k" -pass 2 -passlogfile "$PASSLOG" -movflags +faststart "$OUT"
    SIZE=$(wc -c < "$OUT")
fi

echo "wrote $OUT — $((SIZE / 1024)) KB"
(( SIZE <= 2 * 1024 * 1024 )) || { echo "still over 2 MB: raise the speed-up" >&2; exit 1; }
