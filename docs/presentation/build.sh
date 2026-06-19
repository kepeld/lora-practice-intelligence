#!/usr/bin/env bash
# ML Underground — presentation build script
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
cd "$SCRIPT_DIR"

GREEN='\033[0;32m'; CYAN='\033[0;36m'; RED='\033[0;31m'; NC='\033[0m'
info() { echo -e "${CYAN}[INFO]${NC} $*"; }
ok()   { echo -e "${GREEN}[OK]${NC}   $*"; }
fail() { echo -e "${RED}[FAIL]${NC} $*"; exit 1; }

MARP="npx @marp-team/marp-cli"

info "Building HTML..."
$MARP slides.md --theme theme.css --html --allow-local-files -o presentation.html \
  || fail "HTML build failed"
ok "HTML: presentation.html"

info "Building PDF..."
$MARP slides.md --theme theme.css --html --allow-local-files --pdf -o presentation.pdf 2>/dev/null \
  || echo "  Warning: PDF build failed (Chrome/Puppeteer needed)"
[ -f presentation.pdf ] && ok "PDF: presentation.pdf"

info "Building PPTX..."
$MARP slides.md --theme theme.css --html --allow-local-files --pptx -o presentation.pptx 2>/dev/null \
  || echo "  Warning: PPTX build failed"
[ -f presentation.pptx ] && ok "PPTX: presentation.pptx"

echo ""
ok "Done! Open presentation.html (press 'p' for presenter mode with speaker notes)"
