#!/usr/bin/env bash
# ABOUTME: Read-only Wayback CDX + availability probe over the same foundation-domain sample.
# ABOUTME: One request per second per endpoint, declared User-Agent.
set -u
D="${D:-$(cd "$(dirname "$0")" && pwd)}"
[ -r "$D/domains.txt" ] || { echo "$0: $D/domains.txt is missing — could not look" >&2; exit 2; }
UA="GrantSpiderResearch/1.0 (one-off coverage measurement; bot@aigranthelper.com)"
OUT="$D/wb_results.tsv"
echo -e "size\tdomain\thome_http\thome_latest_ts\tcdx_http\tdistinct_urls_2024plus\tcapped\tfirst_ts\tlast_ts" > "$OUT"
mkdir -p "$D/rawwb"
while read -r SIZE DOM; do
  [ -z "${DOM:-}" ] && continue
  A="$D/rawwb/avail_${DOM}.json"
  C1=$(curl -s -m 60 -A "$UA" -o "$A" -w "%{http_code}" "https://archive.org/wayback/available?url=${DOM}")
  HT=$(grep -o '"timestamp": *"[0-9]*"' "$A" 2>/dev/null | grep -o '[0-9]\{4,\}' | head -1)
  sleep 1.1
  B="$D/rawwb/cdx_${DOM}.txt"
  C2=$(curl -s -m 90 -A "$UA" -o "$B" -w "%{http_code}" "https://web.archive.org/cdx/search/cdx?url=${DOM}&matchType=domain&from=2024&collapse=urlkey&fl=original,timestamp&limit=3000&filter=statuscode:200")
  if [ "$C2" = "200" ]; then
    N=$(grep -c . "$B" 2>/dev/null || echo 0)
  else
    N=0
  fi
  CAP=no; [ "$N" -ge 3000 ] && CAP=yes
  FT=$(awk '{print $2}' "$B" 2>/dev/null | sort | head -1)
  LT=$(awk '{print $2}' "$B" 2>/dev/null | sort | tail -1)
  echo -e "${SIZE}\t${DOM}\t${C1}\t${HT:-}\t${C2}\t${N}\t${CAP}\t${FT:-}\t${LT:-}" >> "$OUT"
  sleep 1.1
done < "$D/domains.txt"
echo "WB_PROBE_DONE" >> "$OUT"
