#!/usr/bin/env bash
# Fetch open-licensed Blender films into ./media-src/ (gitignored) from Wikimedia Commons.
#
#   scripts/fetch_films.sh            # CHECK ONLY: verify every URL, print sizes, record sources in films.yaml
#   scripts/fetch_films.sh --download # also download the verified files (resumable; re-run to continue)
#
# Why Commons: download.blender.org sits behind a bot challenge that scripts must not bypass, and the Internet
# Archive copies of these films are third-party uploads with inconsistent license metadata. Commons file pages
# state the license explicitly, and every file below is checked with a HEAD request before it is used.
# Commons serves 1080p VP9/WebM derivatives; ffmpeg (and the bhavs pipeline) reads WebM/OGV fine, so MP4 is
# not required. Where a 1080p derivative is not available we fall back to the original upload.
set -uo pipefail
cd "$(dirname "$0")/.."

MODE=check; [ "${1:-}" = "--download" ] && MODE=download
OUT=media-src; mkdir -p "$OUT"
UA="bhavs-portfolio-project/0.1 (open-license film fetch; polite, sequential)"
W=https://upload.wikimedia.org/wikipedia/commons
P=https://commons.wikimedia.org/wiki/File

# id | file page title | license shown on that page | candidate URLs (first one that verifies wins)
read -r -d '' FILMS <<LIST
big-buck-bunny|Big_Buck_Bunny_4K.webm|CC BY 3.0|$W/transcoded/c/c0/Big_Buck_Bunny_4K.webm/Big_Buck_Bunny_4K.webm.1080p.vp9.webm
sintel|Sintel_movie_4K.webm|CC BY 3.0|$W/transcoded/f/f1/Sintel_movie_4K.webm/Sintel_movie_4K.webm.1080p.vp9.webm
tears-of-steel|Tears_of_Steel_1080p.webm|CC BY 3.0|$W/transcoded/c/cb/Tears_of_Steel_1080p.webm/Tears_of_Steel_1080p.webm.1080p.vp9.webm $W/c/cb/Tears_of_Steel_1080p.webm
elephants-dream|Elephants_Dream_(2006).webm|CC BY 2.5|$W/transcoded/a/a2/Elephants_Dream_%282006%29.webm/Elephants_Dream_%282006%29.webm.1080p.vp9.webm $W/a/a2/Elephants_Dream_%282006%29.webm
cosmos-laundromat|Cosmos_Laundromat_-_First_Cycle_-_Official_Blender_Foundation_release.webm|CC BY-SA 3.0|$W/transcoded/3/36/Cosmos_Laundromat_-_First_Cycle_-_Official_Blender_Foundation_release.webm/Cosmos_Laundromat_-_First_Cycle_-_Official_Blender_Foundation_release.webm.1080p.vp9.webm $W/3/36/Cosmos_Laundromat_-_First_Cycle_-_Official_Blender_Foundation_release.webm
spring|Spring_-_Blender_Open_Movie.webm|CC BY 4.0|$W/a/a5/Spring_-_Blender_Open_Movie.webm
caminandes-llama-drama|Caminandes-_Llama_Drama_-_Short_Movie.ogv|CC BY 3.0|$W/d/d0/Caminandes-_Llama_Drama_-_Short_Movie.ogv
caminandes-gran-dillama|Caminandes_-_Gran_Dillama_-_Blender_Foundation's_new_Open_Movie.webm|CC BY-SA 3.0|https://upload.wikimedia.org/wikipedia/commons/7/7c/Caminandes_-_Gran_Dillama_-_Blender_Foundation%27s_new_Open_Movie.webm https://upload.wikimedia.org/wikipedia/commons/transcoded/7/7c/Caminandes_-_Gran_Dillama_-_Blender_Foundation%27s_new_Open_Movie.webm/Caminandes_-_Gran_Dillama_-_Blender_Foundation%27s_new_Open_Movie.webm.1080p.vp9.webm
caminandes-llamigos|Caminandes_3_-_Llamigos_-_Blender_Animated_Short.webm|CC BY 3.0|https://upload.wikimedia.org/wikipedia/commons/a/ab/Caminandes_3_-_Llamigos_-_Blender_Animated_Short.webm https://upload.wikimedia.org/wikipedia/commons/transcoded/a/ab/Caminandes_3_-_Llamigos_-_Blender_Animated_Short.webm/Caminandes_3_-_Llamigos_-_Blender_Animated_Short.webm.1080p.vp9.webm
glass-half|Glass_Half_-_Blender_Open_Movie-full_movie.webm|CC BY 4.0|https://upload.wikimedia.org/wikipedia/commons/transcoded/0/02/Glass_Half_-_Blender_Open_Movie-full_movie.webm/Glass_Half_-_Blender_Open_Movie-full_movie.webm.1080p.vp9.webm https://upload.wikimedia.org/wikipedia/commons/0/02/Glass_Half_-_Blender_Open_Movie-full_movie.webm
daily-dweebs|The_Daily_Dweebs_-_Blender_Open_Movie-full_movie.webm|CC BY 4.0|https://upload.wikimedia.org/wikipedia/commons/transcoded/b/b2/The_Daily_Dweebs_-_Blender_Open_Movie-full_movie.webm/The_Daily_Dweebs_-_Blender_Open_Movie-full_movie.webm.1080p.vp9.webm https://upload.wikimedia.org/wikipedia/commons/b/b2/The_Daily_Dweebs_-_Blender_Open_Movie-full_movie.webm
coffee-run|Coffee_Run_-_Blender_Open_Movie-full_movie.webm|CC BY 4.0|https://upload.wikimedia.org/wikipedia/commons/3/3f/Coffee_Run_-_Blender_Open_Movie-full_movie.webm https://upload.wikimedia.org/wikipedia/commons/transcoded/3/3f/Coffee_Run_-_Blender_Open_Movie-full_movie.webm/Coffee_Run_-_Blender_Open_Movie-full_movie.webm.1080p.vp9.webm
sprite-fright|Sprite_Fright_-_Blender_Open_Movie-full_movie.webm|CC BY 4.0|https://upload.wikimedia.org/wikipedia/commons/7/76/Sprite_Fright_-_Blender_Open_Movie-full_movie.webm https://upload.wikimedia.org/wikipedia/commons/transcoded/7/76/Sprite_Fright_-_Blender_Open_Movie-full_movie.webm/Sprite_Fright_-_Blender_Open_Movie-full_movie.webm.1080p.vp9.webm
wing-it|WING_IT!_-_Blender_Open_Movie-full_movie.webm|CC BY 4.0|https://upload.wikimedia.org/wikipedia/commons/3/38/WING_IT%21_-_Blender_Open_Movie-full_movie.webm https://upload.wikimedia.org/wikipedia/commons/transcoded/3/38/WING_IT%21_-_Blender_Open_Movie-full_movie.webm/WING_IT%21_-_Blender_Open_Movie-full_movie.webm.1080p.vp9.webm
charge|Charge_-_Blender_Open_Movie-full_movie.webm|CC BY 4.0|https://upload.wikimedia.org/wikipedia/commons/transcoded/7/7a/Charge_-_Blender_Open_Movie-full_movie.webm/Charge_-_Blender_Open_Movie-full_movie.webm.1080p.vp9.webm https://upload.wikimedia.org/wikipedia/commons/7/7a/Charge_-_Blender_Open_Movie-full_movie.webm
hero|HERO_-_Blender_Open_Movie-full_movie.webm|CC BY 4.0|https://upload.wikimedia.org/wikipedia/commons/a/a9/HERO_-_Blender_Open_Movie-full_movie.webm https://upload.wikimedia.org/wikipedia/commons/transcoded/a/a9/HERO_-_Blender_Open_Movie-full_movie.webm/HERO_-_Blender_Open_Movie-full_movie.webm.1080p.vp9.webm
singularity|SINGULARITY_-_Blender_Open_Movie-full_movie.webm|CC BY 4.0|https://upload.wikimedia.org/wikipedia/commons/transcoded/f/f2/SINGULARITY_-_Blender_Open_Movie-full_movie.webm/SINGULARITY_-_Blender_Open_Movie-full_movie.webm.1080p.vp9.webm https://upload.wikimedia.org/wikipedia/commons/f/f2/SINGULARITY_-_Blender_Open_Movie-full_movie.webm
LIST
# agent-327 (Operation Barbershop) was removed from the catalogue: no official or verifiable archival source found.
# conflicting license metadata), so it is deliberately NOT fetched. Add it by hand to media-src/ if you obtain it
# from Blender Studio yourself.

TSV=$(mktemp); TOTAL=0; OK=0; SKIPPED=0
printf '%-24s %-9s %s\n' FILM SIZE RESULT
while IFS='|' read -r id page license urls; do
  [ -z "$id" ] && continue
  picked=""; size=0
  for u in $urls; do
    sleep 1   # be gentle with Wikimedia (they rate-limit aggressive clients)
    hdr=$(curl -sIL --max-time 30 -A "$UA" "$u") || continue
    code=$(printf '%s' "$hdr" | grep -i '^HTTP' | tail -1 | awk '{print $2}')
    len=$(printf '%s' "$hdr" | grep -i '^content-length:' | tail -1 | tr -dc '0-9')
    if [ "$code" = "200" ] && [ "${len:-0}" -gt 1000000 ]; then picked=$u; size=$len; break; fi
  done
  if [ -z "$picked" ]; then
    printf '%-24s %-9s %s\n' "$id" "-" "SKIPPED (no URL verified)"; SKIPPED=$((SKIPPED+1)); continue
  fi
  OK=$((OK+1)); TOTAL=$((TOTAL+size))
  printf '%-24s %6s MB  verified (%s)\n' "$id" "$((size/1000000))" "$license"
  printf '%s\t%s\t%s\t%s\t%s\t%s\n' "$id" "$picked" "$P:$page" "$license" "$size" "$(date +%F)" >> "$TSV"
  if [ "$MODE" = download ]; then
    ext="${picked##*.}"; dest="$OUT/$id.$ext"
    printf '   downloading -> %s\n' "$dest"
    curl -L --fail --retry 3 -C - -A "$UA" -o "$dest" "$picked" || echo "   download FAILED for $id"
    sleep 2
  fi
done <<< "$FILMS"

python3 scripts/record_sources.py films.yaml "$TSV"
rm -f "$TSV"
echo "agent-327               -         NOT fetched (no official/verifiable archival source; add by hand if you obtain it)"
printf '\n%d verified, %d skipped, total %d MB. Sources + licenses recorded in films.yaml.\n' "$OK" "$SKIPPED" "$((TOTAL/1000000))"
[ "$MODE" = check ] && echo "Nothing was downloaded. Re-run with --download to fetch the verified files into $OUT/."
exit 0
