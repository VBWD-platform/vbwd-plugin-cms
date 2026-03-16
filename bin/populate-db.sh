#!/bin/bash
# Populate CMS Demo Data
# ======================
# Populates the CMS plugin database with demo styles, widgets, layouts, and pages.
# Runs Alembic migrations first, then populate_cms.py inside the backend API container.
#
# Behaviour: UPSERT — safe to re-run at any time. Existing records are updated
# to reflect the current canonical data (correct base64 HTML / extracted CSS).
# New records are inserted. Nothing is deleted.
#
# Usage:
#   ./plugins/cms/bin/populate-db.sh
#
# Requirements:
#   - docker compose running with api service
#   - PostgreSQL database running
#   - Required migrations (applied automatically by this script):
#       20260302_create_cms_tables
#       20260305_cms_templates
#       20260308_cms_page_content_html
#       20260308_cms_widget_refactor   (drops content_html, adds source_css to cms_widget)
#       20260308_cms_page_source_css   (adds source_css to cms_page)
#
# This script creates/updates:
#   - 10 CSS themes (5 light: clean/warm/cool/soft/paper, 5 dark: midnight/charcoal/forest/purple/carbon)
#   - 8 widgets: header-nav, footer-nav, hero-home1, hero-home2, cta-primary,
#                features-3col, pricing-2col, testimonials
#     HTML widgets store content as base64 in content_json.content, CSS in source_css
#   - 4 layouts: home-v1, home-v2, landing, content-page
#   - 5 demo pages: home1, home2, landing2, landing3, about

set -e

RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m'

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")"/.. && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR"/../../.. && pwd)"

echo -e "${BLUE}╔════════════════════════════════════════╗${NC}"
echo -e "${BLUE}║  CMS Plugin — Demo Data Population    ║${NC}"
echo -e "${BLUE}╚════════════════════════════════════════╝${NC}"
echo ""

cd "$PROJECT_ROOT/vbwd-backend" 2>/dev/null || cd "$PROJECT_ROOT" 2>/dev/null

if ! docker compose ps 2>/dev/null | grep -q "api.*Up"; then
    echo -e "${RED}✗ Error: api service is not running${NC}"
    echo ""
    echo "Please start the services first:"
    echo "  cd $PROJECT_ROOT/vbwd-backend"
    echo "  make up"
    exit 1
fi

echo -e "${YELLOW}Step 1/2 — Running Alembic migrations...${NC}"
echo ""

docker compose exec -T api python -m alembic upgrade heads

if [ $? -ne 0 ]; then
    echo ""
    echo -e "${RED}✗ Alembic migrations failed — aborting population${NC}"
    exit 1
fi

echo ""
echo -e "${YELLOW}Step 2/2 — Populating CMS demo data (upsert)...${NC}"
echo ""

docker compose exec -T api python /app/plugins/cms/src/bin/populate_cms.py

if [ $? -eq 0 ]; then
    echo ""
    echo -e "${GREEN}╔════════════════════════════════════════╗${NC}"
    echo -e "${GREEN}║   CMS Demo Data Population Complete   ║${NC}"
    echo -e "${GREEN}╚════════════════════════════════════════╝${NC}"
    echo ""
    echo -e "${GREEN}✓ Styles:  5 light + 5 dark themes${NC}"
    echo -e "${GREEN}✓ Widgets: 8 blocks (HTML stored as base64 + source_css)${NC}"
    echo -e "${GREEN}✓ Layouts: home-v1, home-v2, landing, content-page${NC}"
    echo -e "${GREEN}✓ Pages:   home1, home2, landing2, landing3, about${NC}"
    echo ""
    echo "  Admin:   http://localhost:8081/admin/cms/styles"
    echo "  Preview: http://localhost:8080/home1"
    echo ""
    exit 0
else
    echo ""
    echo -e "${RED}✗ Failed to populate CMS demo data${NC}"
    exit 1
fi
