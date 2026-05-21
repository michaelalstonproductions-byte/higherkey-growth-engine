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

TMP_HELPER="/private/tmp/hk_capture_ui.js"
cat > "$TMP_HELPER" <<'JS'
const { app, BrowserWindow } = require("electron");
const fs = require("fs");
const path = require("path");

const root = process.env.HK_CAPTURE_ROOT;
const dashboardShot = process.env.HK_CAPTURE_DASHBOARD_SHOT;
const tmpShot = "/private/tmp/higherkey_v6_ui_style_clean.png";

const timeout = setTimeout(() => {
  console.error("[capture] timed out");
  process.exit(124);
}, 25000);

async function main() {
  app.commandLine.appendSwitch("disable-gpu");
  await app.whenReady();
  const win = new BrowserWindow({
    width: 1440,
    height: 1000,
    show: false,
    title: "HigherKey Operator OS",
    webPreferences: {
      contextIsolation: false,
      nodeIntegration: false,
      sandbox: false
    }
  });
  await win.loadFile(path.join(root, "dashboard", "review.html"));
  await new Promise((resolve) => setTimeout(resolve, 2500));
  await win.webContents.executeJavaScript(`
    window.higherkey = window.higherkey || { localOnly: true };
    if (typeof state === 'object') {
      state.mode = 'command';
      state.appInfo = Object.assign({}, state.appInfo || {}, {
        version: 'V6.0',
        appVersion: '6.0.0',
        activeProjectRoot: '${root}',
        projectRoot: '${root}',
        devMode: false
      });
      state.pipeline = Object.assign({}, state.pipeline || {}, {
        status: 'idle',
        state: 'completed',
        message: 'Ready'
      });
      state.workspace = Object.assign({}, state.workspace || {}, { mode: 'command' });
    }
    if (typeof render === 'function') render();
    document.getElementById('startupOverlay')?.classList.remove('visible');
    document.getElementById('notice')?.classList.remove('visible');
    document.body.style.overflow = 'hidden';
    true;
  `);
  await new Promise((resolve) => setTimeout(resolve, 1200));
  const image = await win.webContents.capturePage({ x: 0, y: 0, width: 1440, height: 1000 });
  fs.mkdirSync(path.dirname(dashboardShot), { recursive: true });
  fs.writeFileSync(dashboardShot, image.toPNG());
  fs.writeFileSync(tmpShot, image.toPNG());
  console.log(`[capture] dashboard: ${dashboardShot}`);
  console.log(`[capture] tmp: ${tmpShot}`);
  clearTimeout(timeout);
  process.exit(0);
}

main().catch((error) => {
  console.error(error);
  process.exit(1);
});
JS

echo "[capture] screenshot: $DASHBOARD_SHOT"
SCREENSHOT_STATUS=0
rm -f "$DASHBOARD_SHOT" /private/tmp/higherkey_v6_ui_style_clean.png
HK_CAPTURE_ROOT="$ROOT" HK_CAPTURE_DASHBOARD_SHOT="$DASHBOARD_SHOT" "$ROOT/node_modules/.bin/electron" "$TMP_HELPER" &
CAPTURE_PID=$!
CAPTURE_DONE=0
for _ in {1..25}; do
  if [[ -s "$DASHBOARD_SHOT" && -s /private/tmp/higherkey_v6_ui_style_clean.png ]]; then
    CAPTURE_DONE=1
    break
  fi
  if ! kill -0 "$CAPTURE_PID" 2>/dev/null; then
    break
  fi
  sleep 1
done
if [[ "$CAPTURE_DONE" == "1" ]]; then
  kill "$CAPTURE_PID" 2>/dev/null || true
  sleep 1
  kill -9 "$CAPTURE_PID" 2>/dev/null || true
  wait "$CAPTURE_PID" 2>/dev/null || true
else
  SCREENSHOT_STATUS=124
  kill "$CAPTURE_PID" 2>/dev/null || true
  sleep 1
  kill -9 "$CAPTURE_PID" 2>/dev/null || true
  wait "$CAPTURE_PID" 2>/dev/null || true
fi

cat > "$REPORT" <<EOF
HigherKey Operator OS UI screenshot capture

Captured:
- Dashboard/current launched state: $DASHBOARD_SHOT

Launch:
- npm run app:open-latest exit code: $APP_OPEN_STATUS

Screenshot:
- Electron capture exit code: $SCREENSHOT_STATUS
- Clean temp copy: /private/tmp/higherkey_v6_ui_style_clean.png

Page switching:
- Not automated by this helper. Manual page screenshots are still needed for Command/Home, Review, Media, Marketing, Autopilot, Exports, Support, and Settings if exact per-page visual evidence is required.

Notes:
- This helper does not call cloud APIs or social posting APIs.
- This helper does not open QuickTime.
EOF

echo "[capture] report: $REPORT"
