#!/usr/bin/env bash
# ABOUTME: Probes whether WordPress-fingerprinted foundation sites expose an open wp-json REST API.
# ABOUTME: One HEAD-ish GET per domain against /wp-json/wp/v2/pages?per_page=1, declared UA, 1.2s pacing.
set -u
D="${D:-$(cd "$(dirname "$0")" && pwd)}"
[ -r "$D/platform.tsv" ] || { echo "$0: $D/platform.tsv is missing — could not look" >&2; exit 2; }
UA="GrantSpiderResearch/1.0 (one-off REST-API census; bot@aigranthelper.com)"
OUT="$D/wprest.tsv"
echo -e "size\tdomain\troot_http\tpages_http\ttotal_pages\ttotal_posts" > "$OUT"
grep -P '\t(wordpress)' "$D/platform.tsv" | while IFS=$'\t' read -r SIZE DOM HTTP SRV CF PLAT TB JS; do
  R=$(curl < /dev/null -s -m 30 -A "$UA" -o /dev/null -w "%{http_code}" "https://$DOM/wp-json/")
  sleep 1.2
  H=$(curl < /dev/null -s -m 30 -A "$UA" -D "$D/rawhp/${DOM}.wp" -o /dev/null -w "%{http_code}" "https://$DOM/wp-json/wp/v2/pages?per_page=1")
  TP=$(grep -i '^x-wp-total:' "$D/rawhp/${DOM}.wp" 2>/dev/null | tr -d '\r' | awk '{print $2}')
  sleep 1.2
  P=$(curl < /dev/null -s -m 30 -A "$UA" -D "$D/rawhp/${DOM}.wpp" -o /dev/null -w "%{http_code}" "https://$DOM/wp-json/wp/v2/posts?per_page=1")
  TQ=$(grep -i '^x-wp-total:' "$D/rawhp/${DOM}.wpp" 2>/dev/null | tr -d '\r' | awk '{print $2}')
  echo -e "${SIZE}\t${DOM}\t${R}\t${H}\t${TP:-}\t${TQ:-}" >> "$OUT"
  sleep 1.2
done
echo "WP_DONE" >> "$OUT"
