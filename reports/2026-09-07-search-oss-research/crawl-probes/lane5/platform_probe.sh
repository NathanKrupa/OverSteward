#!/usr/bin/env bash
# ABOUTME: Read-only homepage fingerprint of the foundation sample: CMS/platform, edge, JS-only signals.
# ABOUTME: One request per domain, declared User-Agent, 1.2s pacing.
set -u
D="${D:-$(cd "$(dirname "$0")" && pwd)}"
[ -r "$D/domains.txt" ] || { echo "$0: $D/domains.txt is missing — could not look" >&2; exit 2; }
UA="GrantSpiderResearch/1.0 (one-off platform census; bot@aigranthelper.com)"
OUT="$D/platform.tsv"
mkdir -p "$D/rawhp"
echo -e "size\tdomain\thttp\tserver\tcf\tplatform\ttext_bytes\tjs_state" > "$OUT"
while read -r SIZE DOM; do
  [ -z "${DOM:-}" ] && continue
  H="$D/rawhp/${DOM}.hdr"; B="$D/rawhp/${DOM}.html"
  CODE=$(curl -sL -m 45 -A "$UA" -D "$H" -o "$B" -w "%{http_code}" "https://$DOM/")
  SRV=$(grep -i '^server:' "$H" 2>/dev/null | tail -1 | tr -d '\r' | cut -d' ' -f2- | tr -d '\t')
  CF=no; grep -qi '^cf-ray:' "$H" 2>/dev/null && CF=yes
  P="unknown"
  grep -qi 'wp-content\|wp-includes\|/wp-json' "$B" 2>/dev/null && P="wordpress"
  grep -qi 'static.parastorage.com\|wix.com\|X-Wix' "$B" "$H" 2>/dev/null && P="wix"
  grep -qi 'squarespace' "$B" 2>/dev/null && P="squarespace"
  grep -qi 'weebly' "$B" 2>/dev/null && P="weebly"
  grep -qi 'blackbaud\|bbnc\|sky.blackbaud' "$B" 2>/dev/null && P="blackbaud"
  grep -qi 'duda\|dudaone\|irp.cdn-website.com' "$B" 2>/dev/null && P="duda"
  grep -qi '__NEXT_DATA__\|/_next/static' "$B" 2>/dev/null && P="${P}+next"
  grep -qi '__NUXT__' "$B" 2>/dev/null && P="${P}+nuxt"
  grep -qi 'drupal-settings-json\|/sites/default/files' "$B" 2>/dev/null && P="drupal"
  grep -qi 'aem\|/etc.clientlibs/' "$B" 2>/dev/null && P="${P}?aem"
  TB=$(sed -e 's/<script[^>]*>.*<\/script>//g' -e 's/<[^>]*>/ /g' "$B" 2>/dev/null | tr -s ' \n' ' ' | wc -c)
  JS=no; [ "${TB:-0}" -lt 1500 ] && JS=likely_js_only
  echo -e "${SIZE}\t${DOM}\t${CODE}\t${SRV:-}\t${CF}\t${P}\t${TB}\t${JS}" >> "$OUT"
  sleep 1.2
done < "$D/domains.txt"
echo "PLATFORM_DONE" >> "$OUT"
