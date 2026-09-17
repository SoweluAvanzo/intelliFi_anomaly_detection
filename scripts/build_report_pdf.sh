#!/usr/bin/env bash
# Render docs/research_plan_technical_report.md -> docs/research_plan_technical_report.pdf
# via pandoc (gfm -> self-contained HTML) + headless Chrome, with the report's own print CSS
# embedded below (Lato headings / Tinos body / DejaVu fallback, A4, zebra tables, theme-safe).
# Requires: pandoc, google-chrome (or chromium), and the Tinos/Lato/DejaVu fonts (all present on
# the workstation). Run from anywhere.
set -euo pipefail
cd "$(dirname "${BASH_SOURCE[0]}")/.."

SRC="docs/research_plan_technical_report.md"
OUT="docs/research_plan_technical_report.pdf"
TMP="$(mktemp -d)"; trap 'rm -rf "$TMP"' EXIT
HDR="$TMP/header.html"; HTML="$TMP/report.html"

cat > "$HDR" <<'CSS'
<style>
:root{
  --ink:#1c1e22; --muted:#5b626c; --head:#10233f; --accent:#2d6a9f;
  --rule:#d8dee7; --thead:#eaf0f7; --zebra:#f5f8fb;
  --quote-bg:#f5f8fc; --quote-bar:#9db4d0; --code-bg:#eef1f5;
}
@page{ size:A4; margin:18mm 17mm 18mm 17mm; }
html{ -webkit-print-color-adjust:exact; print-color-adjust:exact; }
body{ font-family:"Tinos","DejaVu Serif",Georgia,serif; font-size:10.4pt; line-height:1.5;
  color:var(--ink); text-align:justify; hyphens:auto; -webkit-hyphens:auto; }
p{ margin:.55em 0; }
h1,h2,h3,h4{ font-family:"Lato","DejaVu Sans",Arial,sans-serif; color:var(--head); hyphens:none; text-align:left; }
h1{ font-size:23pt; font-weight:700; letter-spacing:-.2px; margin:0 0 .12em; padding-bottom:.18em; border-bottom:2.5px solid var(--accent); }
h1 + p{ margin-top:.5em; text-align:left; hyphens:none; }
h1 + p em{ color:var(--muted); font-size:12pt; font-style:italic; }
h2{ font-size:14.5pt; font-weight:700; margin:1.7em 0 .55em; padding-bottom:4px; border-bottom:1px solid var(--rule); break-after:avoid; }
h3{ font-size:11.6pt; font-weight:700; color:var(--accent); margin:1.2em 0 .35em; break-after:avoid; }
strong{ font-weight:700; color:var(--head); }
em{ font-style:italic; }
a{ color:var(--accent); text-decoration:none; }
code{ font-family:"DejaVu Sans Mono",monospace; font-size:.82em; background:var(--code-bg); padding:.5px 3px; border-radius:2.5px; }
sup,sub{ line-height:0; }
ul,ol{ margin:.4em 0 .8em; padding-left:1.45em; }
li{ margin:.18em 0; }
li::marker{ color:var(--accent); }
blockquote{ border-left:3.5px solid var(--quote-bar); background:var(--quote-bg); margin:1em 0; padding:.5em 1em; color:#2e343d; border-radius:0 3px 3px 0; text-align:left; hyphens:none; }
blockquote p{ margin:.25em 0; }
hr{ border:0; border-top:1px solid var(--rule); margin:1.6em 0; }
table{ border-collapse:collapse; width:100%; font-size:8.2pt; line-height:1.32; margin:.9em 0; font-variant-numeric:tabular-nums; break-inside:auto; text-align:left; hyphens:none; }
thead th{ background:var(--thead); color:var(--head); font-family:"Lato","DejaVu Sans",sans-serif; font-weight:700; }
th,td{ border:.6px solid var(--rule); padding:3px 6px; text-align:left; vertical-align:top; overflow-wrap:anywhere; }
tbody tr:nth-child(even){ background:var(--zebra); }
tr{ break-inside:avoid; }
table:first-of-type{ font-size:7.1pt; }
table:first-of-type th,table:first-of-type td{ padding:2.5px 4px; }
h2,h3{ page-break-after:avoid; }
li,tr,blockquote{ page-break-inside:avoid; }
</style>
CSS

# pandoc 2.x uses --self-contained; pandoc >=3 renamed it --embed-resources --standalone.
EMBED="--self-contained"
pandoc --version | head -1 | grep -qE 'pandoc 3' && EMBED="--embed-resources --standalone"

pandoc "$SRC" -f gfm -t html5 -s $EMBED -M lang=en -H "$HDR" -o "$HTML"

CHROME="$(command -v google-chrome || command -v google-chrome-stable || command -v chromium || command -v chromium-browser)"
[ -n "$CHROME" ] || { echo "no chrome/chromium found"; exit 1; }
"$CHROME" --headless=new --disable-gpu --no-sandbox --no-pdf-header-footer \
  --print-to-pdf="$OUT" "file://$HTML" 2>/dev/null

echo "wrote $OUT"
