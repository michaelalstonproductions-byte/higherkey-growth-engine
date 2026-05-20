#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
OUT_DIR="$ROOT/out/ui_screenshots"
DASHBOARD_SHOT="$OUT_DIR/v6_reference_style_dashboard.png"
REPORT="$OUT_DIR/v6_reference_style_capture_report.txt"

mkdir -p "$OUT_DIR"
cd "$ROOT"

echo "[capture] rebuilding packaged app"
npm run dist:dir

echo "[capture] launching latest packaged app"
APP_OPEN_STATUS=0
npm run app:open-latest || APP_OPEN_STATUS=$?

echo "[capture] bringing HigherKey Operator OS frontmost"
osascript -e 'tell application "System Events" to set frontmost of process "HigherKey Operator OS" to true' || true
sleep 2

echo "[capture] screenshot: $DASHBOARD_SHOT"
SCREENSHOT_STATUS=0
screencapture -x "$DASHBOARD_SHOT" || SCREENSHOT_STATUS=$?

cat > "$REPORT" <<EOF
HigherKey Operator OS UI screenshot capture

Captured:
- Dashboard/current launched state: $DASHBOARD_SHOT

Launch:
- npm run app:open-latest exit code: $APP_OPEN_STATUS

Screenshot:
- screencapture exit code: $SCREENSHOT_STATUS

Page switching:
- Not automated by this helper. Manual page screenshots are still needed for Command/Home, Review, Media, Marketing, Autopilot, Exports, Support, and Settings if exact per-page visual evidence is required.

Notes:
- This helper does not call cloud APIs or social posting APIs.
- This helper does not open QuickTime.
EOF

echo "[capture] report: $REPORT"
