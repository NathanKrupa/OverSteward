#!/usr/bin/env bash
# ABOUTME: Probes whether WordPress-fingerprinted foundation sites expose an open wp-json REST API.
# ABOUTME: Follows redirects, reads X-WP-Total, declared UA, ~1.2s pacing per request.
set -u
D=/home/natha/.claude/tmp/claude-1000/-home-natha-OverSteward/69309070-6f71-422f-9333-aeba569aae31/scratchpad/search-research/lane5
UA="GrantSpiderResearch/1.0 (one-off REST-API census; bot@aigranthelper.com)"
OUT="$D/wprest_final.tsv"
echo -e "size\tdomain\troot_http\tpages_http\ttotal_pages\ttotal_posts" > "$OUT"
mapfile -t ROWS < <(awk -F'\t' '$6 ~ /wordpress/ {print $1"|"$2}' "$D/platform.tsv")
for ROW in "${ROWS[@]}"; do
  SIZE=${ROW%%|*}; DOM=${ROW##*|}
  R=$(curl -sL < /dev/null -m 30 -A "$UA" -o /dev/null -w "%{http_code}" "https://$DOM/wp-json/")
  sleep 1.2
  H=$(curl -sL < /dev/null -m 30 -A "$UA" -D "$D/rawhp/${DOM}.wp2" -o /dev/null -w "%{http_code}" "https://$DOM/wp-json/wp/v2/pages?per_page=1")
  TP=$(grep -i '^x-wp-total:' "$D/rawhp/${DOM}.wp2" 2>/dev/null | tr -d '\r' | awk '{print $2}' | tail -1)
  sleep 1.2
  curl -sL < /dev/null -m 30 -A "$UA" -D "$D/rawhp/${DOM}.wpp2" -o /dev/null "https://$DOM/wp-json/wp/v2/posts?per_page=1"
  TQ=$(grep -i '^x-wp-total:' "$D/rawhp/${DOM}.wpp2" 2>/dev/null | tr -d '\r' | awk '{print $2}' | tail -1)
  echo -e "${SIZE}\t${DOM}\t${R}\t${H}\t${TP:-}\t${TQ:-}" >> "$OUT"
  sleep 1.2
done
echo "WP_DONE" >> "$OUT"
