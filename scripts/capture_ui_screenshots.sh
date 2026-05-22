#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
OUT_DIR="$ROOT/out/ui_screenshots"
REPORT="$OUT_DIR/v6_5_reference_style_capture_report.txt"
CAPTURE_PID=""
PRE_EXISTING_HIGHERKEY_PIDS=""
LAUNCHED_HIGHERKEY_PIDS=""
HELPER_CLEANUP_STATUS="not_started"
APP_CLEANUP_STATUS="not_started"
FINAL_EXIT_STATUS=0

higherkey_pids() {
  set +e
  local pids
  pids="$(ps aux 2>/dev/null | rg "HigherKey Operator OS.app/Contents/" | rg -v rg | awk '{print $2}')"
  local status=$?
  set -e
  if [[ "$status" -eq 0 && -n "$pids" ]]; then
    printf '%s\n' "$pids" | sort -n | tr '\n' ' ' | sed 's/[[:space:]]*$//'
  fi
}

pid_in_list() {
  local needle="$1"
  local list="${2:-}"
  for pid in $list; do
    [[ "$pid" == "$needle" ]] && return 0
  done
  return 1
}

new_pids_since_launch() {
  local after="$1"
  local before="$2"
  local new_pids=""
  for pid in $after; do
    if ! pid_in_list "$pid" "$before"; then
      new_pids="$new_pids $pid"
    fi
  done
  echo "$new_pids" | xargs
}

cleanup_capture() {
  local status=$?
  FINAL_EXIT_STATUS=$status

  if [[ -n "${CAPTURE_PID:-}" ]] && kill -0 "$CAPTURE_PID" 2>/dev/null; then
    kill "$CAPTURE_PID" 2>/dev/null || true
    sleep 1
    if kill -0 "$CAPTURE_PID" 2>/dev/null; then
      kill -9 "$CAPTURE_PID" 2>/dev/null || true
      HELPER_CLEANUP_STATUS="killed_force"
    else
      HELPER_CLEANUP_STATUS="killed"
    fi
    wait "$CAPTURE_PID" 2>/dev/null || true
  elif [[ -n "${CAPTURE_PID:-}" ]]; then
    HELPER_CLEANUP_STATUS="already_exited"
  else
    HELPER_CLEANUP_STATUS="not_started"
  fi

  local after_pids
  after_pids="$(higherkey_pids)"
  LAUNCHED_HIGHERKEY_PIDS="$(new_pids_since_launch "$after_pids" "$PRE_EXISTING_HIGHERKEY_PIDS")"
  if [[ -n "$LAUNCHED_HIGHERKEY_PIDS" ]]; then
    kill $LAUNCHED_HIGHERKEY_PIDS 2>/dev/null || true
    sleep 1
    local still_running=""
    for pid in $LAUNCHED_HIGHERKEY_PIDS; do
      if kill -0 "$pid" 2>/dev/null; then
        still_running="$still_running $pid"
      fi
    done
    if [[ -n "$still_running" ]]; then
      kill -9 $still_running 2>/dev/null || true
      APP_CLEANUP_STATUS="killed_force:$(echo "$still_running" | xargs)"
    else
      APP_CLEANUP_STATUS="killed"
    fi
  else
    APP_CLEANUP_STATUS="no_new_app_process"
  fi

  return "$status"
}

trap cleanup_capture EXIT INT TERM

mkdir -p "$OUT_DIR"
cd "$ROOT"

echo "[capture] rebuilding packaged app"
npm run dist:dir

echo "[capture] launching latest packaged app"
APP_OPEN_STATUS=0
PRE_EXISTING_HIGHERKEY_PIDS="$(higherkey_pids)"
npm run app:open-latest || APP_OPEN_STATUS=$?

TMP_HELPER="/private/tmp/hk_capture_ui.js"
cat > "$TMP_HELPER" <<'JS'
const { app, BrowserWindow } = require("electron");
const fs = require("fs");
const path = require("path");

const root = process.env.HK_CAPTURE_ROOT;
const outDir = process.env.HK_CAPTURE_OUT_DIR;
const reportJson = process.env.HK_CAPTURE_JSON_REPORT;
const tmpShot = "/private/tmp/higherkey_v6_5_ui_style_clean.png";
const pages = [
  ["command", "Command/Home", "v6_5_command_home.png"],
  ["queue", "Review", "v6_5_review.png"],
  ["media", "Media", "v6_5_media.png"],
  ["marketing", "Marketing", "v6_5_marketing.png"],
  ["scheduler", "Scheduler", "v6_5_scheduler.png"],
  ["autopilot", "Autopilot", "v6_5_autopilot.png"],
  ["social", "Exports", "v6_5_exports.png"],
  ["diagnostics", "Support", "v6_5_support.png"],
  ["settings", "Settings", "v6_5_settings.png"]
];

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
    window.higherkey = Object.assign({
      localOnly: true,
      getAppInfo: async () => ({
        version: 'V6.5',
        activeProjectRoot: '${root}',
        projectRoot: '${root}',
        contentInbox: 'content_inbox',
        exportDirectory: 'out/approved_posts',
        build: { packageVersion: '6.5.0', buildStatus: 'release-candidate' }
      }),
      getLocalApiStatus: async () => ({ state: 'ready', running: false }),
      getTrialReadiness: async () => ({ readiness: { status: 'not run' } })
    }, window.higherkey || {});
    if (typeof state === 'object') {
      state.mode = 'command';
      state.appInfo = Object.assign({}, state.appInfo || {}, {
        version: 'V6.5',
        appVersion: '6.5.0',
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
  fs.mkdirSync(outDir, { recursive: true });
  const captured = [];
  const missing = [];
  for (const [mode, label, fileName] of pages) {
    const shotPath = path.join(outDir, fileName);
    try {
      const ok = await win.webContents.executeJavaScript(`
        if (typeof state !== 'object' || typeof render !== 'function') false;
        else {
          state.mode = ${JSON.stringify(mode)};
          state.workspace = Object.assign({}, state.workspace || {}, { mode: ${JSON.stringify(mode)} });
          render();
          document.getElementById('startupOverlay')?.classList.remove('visible');
          document.getElementById('notice')?.classList.remove('visible');
          true;
        }
      `);
      await new Promise((resolve) => setTimeout(resolve, 700));
      const image = await win.webContents.capturePage({ x: 0, y: 0, width: 1440, height: 1000 });
      fs.writeFileSync(shotPath, image.toPNG());
      if (mode === "command") fs.writeFileSync(tmpShot, image.toPNG());
      if (ok) captured.push({ mode, label, path: shotPath });
      else missing.push({ mode, label, reason: "Dashboard state/render function was unavailable." });
      console.log(`[capture] ${label}: ${shotPath}`);
    } catch (error) {
      missing.push({ mode, label, reason: String(error && error.message ? error.message : error) });
    }
  }
  fs.writeFileSync(reportJson, JSON.stringify({ captured, missing }, null, 2));
  console.log(`[capture] tmp: ${tmpShot}`);
  clearTimeout(timeout);
  process.exit(0);
}

main().catch((error) => {
  console.error(error);
  process.exit(1);
});
JS

echo "[capture] screenshots: $OUT_DIR"
SCREENSHOT_STATUS=0
rm -f "$OUT_DIR"/v6_5_*.png "$OUT_DIR/v6_5_capture_pages.json" /private/tmp/higherkey_v6_5_ui_style_clean.png
HK_CAPTURE_ROOT="$ROOT" HK_CAPTURE_OUT_DIR="$OUT_DIR" HK_CAPTURE_JSON_REPORT="$OUT_DIR/v6_5_capture_pages.json" "$ROOT/node_modules/.bin/electron" "$TMP_HELPER" &
CAPTURE_PID=$!
CAPTURE_DONE=0
for _ in {1..35}; do
  if [[ -s "$OUT_DIR/v6_5_capture_pages.json" && -s "$OUT_DIR/v6_5_settings.png" && -s /private/tmp/higherkey_v6_5_ui_style_clean.png ]]; then
    CAPTURE_DONE=1
    break
  fi
  if ! kill -0 "$CAPTURE_PID" 2>/dev/null; then
    break
  fi
  sleep 1
done
if [[ "$CAPTURE_DONE" == "1" ]]; then
  if kill -0 "$CAPTURE_PID" 2>/dev/null; then
    kill "$CAPTURE_PID" 2>/dev/null || true
    sleep 1
    if kill -0 "$CAPTURE_PID" 2>/dev/null; then
      kill -9 "$CAPTURE_PID" 2>/dev/null || true
      HELPER_CLEANUP_STATUS="killed_force"
    else
      HELPER_CLEANUP_STATUS="killed"
    fi
  else
    HELPER_CLEANUP_STATUS="already_exited"
  fi
  wait "$CAPTURE_PID" 2>/dev/null || true
else
  SCREENSHOT_STATUS=124
  kill "$CAPTURE_PID" 2>/dev/null || true
  sleep 1
  kill -9 "$CAPTURE_PID" 2>/dev/null || true
  wait "$CAPTURE_PID" 2>/dev/null || true
  HELPER_CLEANUP_STATUS="timeout_killed"
fi

AFTER_CAPTURE_HIGHERKEY_PIDS="$(higherkey_pids)"
LAUNCHED_HIGHERKEY_PIDS="$(new_pids_since_launch "$AFTER_CAPTURE_HIGHERKEY_PIDS" "$PRE_EXISTING_HIGHERKEY_PIDS")"
if [[ -n "$LAUNCHED_HIGHERKEY_PIDS" ]]; then
  kill $LAUNCHED_HIGHERKEY_PIDS 2>/dev/null || true
  sleep 1
  STILL_RUNNING_HIGHERKEY_PIDS=""
  for pid in $LAUNCHED_HIGHERKEY_PIDS; do
    if kill -0 "$pid" 2>/dev/null; then
      STILL_RUNNING_HIGHERKEY_PIDS="$STILL_RUNNING_HIGHERKEY_PIDS $pid"
    fi
  done
  if [[ -n "$STILL_RUNNING_HIGHERKEY_PIDS" ]]; then
    kill -9 $STILL_RUNNING_HIGHERKEY_PIDS 2>/dev/null || true
    APP_CLEANUP_STATUS="killed_force:$(echo "$STILL_RUNNING_HIGHERKEY_PIDS" | xargs)"
  else
    APP_CLEANUP_STATUS="killed"
  fi
else
  APP_CLEANUP_STATUS="no_new_app_process"
fi

if [[ "$SCREENSHOT_STATUS" -ne 0 ]]; then
  FINAL_EXIT_STATUS="$SCREENSHOT_STATUS"
else
  FINAL_EXIT_STATUS="$APP_OPEN_STATUS"
fi

cat > "$REPORT" <<EOF
HigherKey Operator OS UI screenshot capture

Captured:
EOF

MISSING_SCREENSHOTS_COUNT=9
if [[ -s "$OUT_DIR/v6_5_capture_pages.json" ]]; then
  MISSING_SCREENSHOTS_COUNT="$(python3 - "$OUT_DIR/v6_5_capture_pages.json" <<'PY'
import json
import sys
data = json.load(open(sys.argv[1], encoding="utf-8"))
print(len(data.get("missing", [])))
PY
)"
  python3 - "$OUT_DIR/v6_5_capture_pages.json" >> "$REPORT" <<'PY'
import json
import sys
data = json.load(open(sys.argv[1], encoding="utf-8"))
for item in data.get("captured", []):
    print(f"- {item['label']}: {item['path']}")
missing = data.get("missing", [])
print("")
print("Missing:")
if missing:
    for item in missing:
        print(f"- {item['label']}: {item['reason']}")
else:
    print("- None")
PY
else
  cat >> "$REPORT" <<EOF
- None

Missing:
- Command/Home, Review, Media, Marketing, Scheduler, Autopilot, Exports, Support, and Settings: screenshot helper did not complete.
EOF
fi

cat >> "$REPORT" <<EOF

Launch:
- npm run app:open-latest exit code: $APP_OPEN_STATUS
- pre_existing_higherkey_pids: ${PRE_EXISTING_HIGHERKEY_PIDS:-none}
- launched_higherkey_pids: ${LAUNCHED_HIGHERKEY_PIDS:-none}

Screenshot:
- Electron capture exit code: $SCREENSHOT_STATUS
- Clean temp copy: /private/tmp/higherkey_v6_5_ui_style_clean.png
- helper_cleanup_status: $HELPER_CLEANUP_STATUS
- app_cleanup_status: $APP_CLEANUP_STATUS
- missing_screenshots count: $MISSING_SCREENSHOTS_COUNT
- exit_status: $FINAL_EXIT_STATUS

Page switching:
- Automated by setting dashboard state.mode for each main page and re-rendering before capture.

Notes:
- This helper does not call cloud APIs or social posting APIs.
- This helper does not open QuickTime.
EOF

echo "[capture] report: $REPORT"
