#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
APP_PATH="$ROOT/dist/mac-arm64/HigherKey Operator OS.app"
DRY_RUN=0
SET_PROJECT=1

for arg in "$@"; do
  case "$arg" in
    --dry-run) DRY_RUN=1 ;;
    --no-set-project) SET_PROJECT=0 ;;
    *) echo "Unknown argument: $arg" >&2; exit 2 ;;
  esac
done

cd "$ROOT"

if [[ ! -d "$APP_PATH" ]]; then
  echo "HigherKey Operator OS app not found at: $APP_PATH" >&2
  echo "Run npm run dist:dir first." >&2
  exit 1
fi

INFO_JSON="$(node - <<'NODE'
const fs = require("fs");
const path = require("path");
function normalize(value) {
  const text = String(value || "").trim().replace(/^v/i, "");
  const match = text.match(/(\d+)(?:\.(\d+))?(?:\.(\d+))?/);
  if (!match) return text || "unknown";
  return [match[1], match[2] || "0", match[3] || "0"].join(".");
}
const root = process.cwd();
const pkg = JSON.parse(fs.readFileSync(path.join(root, "package.json"), "utf8"));
const release = JSON.parse(fs.readFileSync(path.join(root, "config", "release.json"), "utf8"));
const packageVersion = normalize(pkg.version);
const releaseVersion = normalize(release.version);
const warnings = [];
if (packageVersion !== releaseVersion) {
  warnings.push(`package.json ${packageVersion} != config/release.json ${release.version}`);
}
console.log(JSON.stringify({
  packageVersion,
  releaseVersion,
  releaseVersionRaw: release.version,
  productName: pkg.productName || release.product_name || "HigherKey Operator OS",
  warnings
}));
NODE
)"

PACKAGE_VERSION="$(node -e 'const info=JSON.parse(process.argv[1]); process.stdout.write(info.packageVersion)' "$INFO_JSON")"
RELEASE_VERSION="$(node -e 'const info=JSON.parse(process.argv[1]); process.stdout.write(info.releaseVersionRaw)' "$INFO_JSON")"
WARNING_COUNT="$(node -e 'const info=JSON.parse(process.argv[1]); process.stdout.write(String(info.warnings.length))' "$INFO_JSON")"
LATEST_MANIFEST="$ROOT/dist/latest-build.json"

echo "HigherKey Operator OS latest local app:"
echo "  App: $APP_PATH"
echo "  package.json version: $PACKAGE_VERSION"
echo "  config/release.json version: $RELEASE_VERSION"
echo "  repo project: $ROOT"

if [[ -f "$LATEST_MANIFEST" ]]; then
  node - "$LATEST_MANIFEST" "$APP_PATH" <<'NODE'
const fs = require("fs");
const path = require("path");
const manifestPath = process.argv[2];
const expectedApp = process.argv[3];
const manifest = JSON.parse(fs.readFileSync(manifestPath, "utf8"));
console.log(`  latest build manifest: ${path.relative(process.cwd(), manifestPath)}`);
console.log(`  latest build time: ${manifest.built_at || "unknown"}`);
if (manifest.app_path && path.resolve(manifest.app_path) !== path.resolve(expectedApp)) {
  console.error(`  WARNING: latest manifest app path differs: ${manifest.app_path}`);
  process.exitCode = 1;
}
NODE
else
  echo "  latest build manifest: missing; run npm run dist:dir or npm run dist:unsigned"
fi

if [[ "$WARNING_COUNT" != "0" ]]; then
  node -e 'const info=JSON.parse(process.argv[1]); for (const warning of info.warnings) console.error("  WARNING: " + warning)' "$INFO_JSON"
  exit 1
fi

if [[ "$DRY_RUN" == "1" ]]; then
  if [[ "$SET_PROJECT" == "1" ]]; then
    echo "Dry run only. Would set packaged app active project to repo root."
  fi
  echo "Dry run only. App not opened."
  exit 0
fi

if [[ "$SET_PROJECT" == "1" ]]; then
  node - "$ROOT" <<'NODE'
const fs = require("fs");
const os = require("os");
const path = require("path");

const projectRoot = process.argv[2];
const userData = path.join(os.homedir(), "Library", "Application Support", "HigherKey Operator OS");
const settingsPath = path.join(userData, "higherkey-settings.json");
fs.mkdirSync(userData, { recursive: true });

let settings = {};
try {
  settings = JSON.parse(fs.readFileSync(settingsPath, "utf8"));
} catch {
  settings = {};
}

settings.version = Math.max(Number(settings.version || 1), 2);
settings.appName = "HigherKey Operator OS";
settings.packaged = true;
settings.activeProject = projectRoot;
settings.recentProjects = [
  projectRoot,
  ...(Array.isArray(settings.recentProjects) ? settings.recentProjects.filter((item) => item !== projectRoot) : [])
].slice(0, 10);
settings.profiles = settings.profiles || {};
settings.profiles.default = {
  ...(settings.profiles.default || {}),
  name: settings.profiles.default?.name || "Default",
  projectPath: projectRoot,
  contentInbox: path.join(projectRoot, "content_inbox"),
  exportDirectory: path.join(projectRoot, "out", "approved_posts"),
  analyticsDirectory: path.join(projectRoot, "analytics"),
  startWatcherOnLaunch: Boolean(settings.profiles.default?.startWatcherOnLaunch),
  setupCompleted: true,
  setupCompletedAt: settings.profiles.default?.setupCompletedAt || new Date().toISOString()
};

fs.writeFileSync(settingsPath, `${JSON.stringify(settings, null, 2)}\n`);
console.log(`  active project set: ${projectRoot}`);
console.log(`  settings: ${settingsPath}`);
NODE
fi

open "$APP_PATH"
echo "Opened: $APP_PATH"
