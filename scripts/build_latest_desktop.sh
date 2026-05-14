#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
MODE="dmg"
PRODUCT="HigherKey Operator OS"
BUILDER="$ROOT/node_modules/.bin/electron-builder"

for arg in "$@"; do
  case "$arg" in
    --dir) MODE="dir" ;;
    --dmg) MODE="dmg" ;;
    *) echo "Unknown argument: $arg" >&2; exit 2 ;;
  esac
done

cd "$ROOT"

if [[ ! -x "$BUILDER" ]]; then
  echo "electron-builder not found at $BUILDER" >&2
  echo "Run npm install first." >&2
  exit 1
fi

PACKAGE_VERSION="$(node -e 'const pkg=require("./package.json"); process.stdout.write(String(pkg.version || "unknown"))')"
RELEASE_VERSION="$(node - <<'NODE'
const fs = require("fs");
const release = JSON.parse(fs.readFileSync("config/release.json", "utf8"));
process.stdout.write(String(release.version || "unknown"));
NODE
)"

echo "[build] HigherKey desktop build"
echo "[build] mode: $MODE"
echo "[build] package.json: $PACKAGE_VERSION"
echo "[build] config/release.json: $RELEASE_VERSION"

mkdir -p "$ROOT/dist"

echo "[build] removing stale packaged app"
rm -rf "$ROOT/dist/mac-arm64"

if [[ "$MODE" == "dmg" ]]; then
  echo "[build] replacing prior HigherKey DMG artifacts"
  find "$ROOT/dist" -maxdepth 1 -type f \( -name "${PRODUCT}-*.dmg" -o -name "${PRODUCT}-*.dmg.blockmap" -o -name "${PRODUCT}-latest-arm64.dmg" \) -print -delete
  "$BUILDER" --mac dmg -c.mac.identity=null
else
  "$BUILDER" --mac dir
fi

APP_PATH="$ROOT/dist/mac-arm64/${PRODUCT}.app"
DMG_PATH=""
if [[ "$MODE" == "dmg" ]]; then
  DMG_PATH="$(find "$ROOT/dist" -maxdepth 1 -type f -name "${PRODUCT}-*.dmg" -print | sort | tail -n 1)"
  if [[ -z "$DMG_PATH" || ! -f "$DMG_PATH" ]]; then
    echo "[build] DMG build did not produce an artifact" >&2
    exit 1
  fi
fi

MANIFEST="$ROOT/dist/latest-build.json"
node - "$MANIFEST" "$APP_PATH" "$DMG_PATH" "$PACKAGE_VERSION" "$RELEASE_VERSION" "$MODE" <<'NODE'
const fs = require("fs");
const path = require("path");
const [manifestPath, appPath, dmgPath, packageVersion, releaseVersion, mode] = process.argv.slice(2);
const payload = {
  product: "HigherKey Operator OS",
  mode,
  package_version: packageVersion,
  release_version: releaseVersion,
  built_at: new Date().toISOString(),
  app_path: appPath,
  app_exists: fs.existsSync(appPath),
  dmg_path: dmgPath || null,
  dmg_exists: dmgPath ? fs.existsSync(dmgPath) : false,
};
fs.writeFileSync(manifestPath, `${JSON.stringify(payload, null, 2)}\n`);
console.log(`[build] latest manifest: ${path.relative(process.cwd(), manifestPath)}`);
if (!payload.app_exists) {
  console.error(`[build] packaged app missing: ${appPath}`);
  process.exit(1);
}
if (mode === "dmg" && !payload.dmg_exists) {
  console.error(`[build] DMG missing: ${dmgPath}`);
  process.exit(1);
}
NODE

echo "[build] app: $APP_PATH"
if [[ "$MODE" == "dmg" ]]; then
  echo "[build] dmg: $DMG_PATH"
  echo "[build] previous DMG artifacts were removed before build; this is the current DMG."
fi
