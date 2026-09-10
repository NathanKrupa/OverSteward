#!/usr/bin/env bash
# ABOUTME: Read-only Common Crawl CDX index probe over a fixed foundation-domain sample.
# ABOUTME: One request per second, declared User-Agent, no writes anywhere but this scratchpad.
set -u
D="${D:-$(cd "$(dirname "$0")" && pwd)}"
[ -r "$D/domains.txt" ] || { echo "$0: $D/domains.txt is missing — could not look" >&2; exit 2; }
UA="GrantSpiderResearch/1.0 (one-off coverage measurement; bot@aigranthelper.com)"
OUT="$D/cc_results.tsv"
echo -e "crawl\tsize\tdomain\thttp\trecords\tcapped\tdistinct_urls\tlatest_ts" > "$OUT"
for CRAWL in CC-MAIN-2026-34 CC-MAIN-2026-30 CC-MAIN-2026-25; do
  while read -r SIZE DOM; do
    [ -z "${DOM:-}" ] && continue
    URL="https://index.commoncrawl.org/${CRAWL}-index?url=${DOM}%2F*&output=json&limit=1000"
    BODY="$D/raw/${CRAWL}_${DOM}.json"
    mkdir -p "$D/raw"
    CODE=$(curl -s -m 60 -A "$UA" -H "Accept: application/json" -o "$BODY" -w "%{http_code}" "$URL")
    if [ "$CODE" = "200" ]; then
      N=$(grep -c '"urlkey"' "$BODY" 2>/dev/null || echo 0)
      DU=$(grep -o '"url": "[^"]*"' "$BODY" 2>/dev/null | sort -u | wc -l)
      TS=$(grep -o '"timestamp": "[0-9]*"' "$BODY" 2>/dev/null | grep -o '[0-9]*' | sort | tail -1)
    else
      N=0; DU=0; TS=""
    fi
    CAP=no; [ "$N" -ge 1000 ] && CAP=yes
    echo -e "${CRAWL}\t${SIZE}\t${DOM}\t${CODE}\t${N}\t${CAP}\t${DU}\t${TS:-}" >> "$OUT"
    sleep 1.1
  done < "$D/domains.txt"
done
echo "CC_PROBE_DONE" >> "$OUT"
