const { app, BrowserWindow, Menu, dialog, ipcMain, Notification, shell } = require("electron");
const http = require("node:http");
const fs = require("node:fs");
const fsp = require("node:fs/promises");
const path = require("node:path");
const { spawn } = require("node:child_process");
const { ingestDroppedFilesToInbox } = require("./ingest");

if (process.env.HK_OPERATOR_USER_DATA) {
  app.setPath("userData", process.env.HK_OPERATOR_USER_DATA);
}

const APP_ROOT = app.isPackaged ? path.join(process.resourcesPath, "app-assets") : path.resolve(__dirname, "..");
const DEFAULT_PROJECT_ROOT = app.isPackaged ? path.join(app.getPath("userData"), "HigherKey Operator OS Project") : APP_ROOT;
const SETTINGS_NAME = "higherkey-settings.json";
const RUNTIME_DIRS = new Set(["analytics", "captions", "clips", "config", "content_inbox", "logs", "out", "queue"]);
const MIME = new Map([
  [".html", "text/html"],
  [".js", "text/javascript"],
  [".css", "text/css"],
  [".json", "application/json"],
  [".mp4", "video/mp4"],
  [".mov", "video/quicktime"],
  [".txt", "text/plain"]
]);

let mainWindow = null;
let splashWindow = null;
let staticServer = null;
let watcherProcess = null;
let activityPoll = null;
let lastActivityCount = 0;
let activeProjectRoot = DEFAULT_PROJECT_ROOT;
let releaseInfoCache = null;

function releaseInfo() {
  if (releaseInfoCache) return releaseInfoCache;
  try {
    releaseInfoCache = JSON.parse(fs.readFileSync(path.join(APP_ROOT, "config", "release.json"), "utf8"));
  } catch {
    releaseInfoCache = {
      app_id: "com.higherkey.operatoros",
      build_status: "release-candidate",
      local_first_statement: "HigherKey Operator OS runs locally. No cloud APIs or social APIs are configured.",
      product_name: "HigherKey Operator OS",
      release_name: "Release Candidate Desktop Demo",
      version: "V2.7"
    };
  }
  return releaseInfoCache;
}

function normalizeVersion(value) {
  const text = String(value || "").trim().replace(/^v/i, "");
  const match = text.match(/(\d+)(?:\.(\d+))?(?:\.(\d+))?/);
  if (!match) return text || "unknown";
  return [match[1], match[2] || "0", match[3] || "0"].join(".");
}

function packageInfo() {
  const candidates = [
    path.join(app.getAppPath(), "package.json"),
    path.join(APP_ROOT, "package.json"),
    path.resolve(__dirname, "..", "package.json")
  ];
  for (const candidate of candidates) {
    try {
      return JSON.parse(fs.readFileSync(candidate, "utf8"));
    } catch {}
  }
  return { version: app.getVersion(), productName: "HigherKey Operator OS" };
}

function buildInfo() {
  const release = releaseInfo();
  const pkg = packageInfo();
  const packageVersion = normalizeVersion(pkg.version);
  const releaseVersion = normalizeVersion(release.version);
  const runtimeVersion = normalizeVersion(app.getVersion());
  const warnings = [];
  if (packageVersion !== releaseVersion) {
    warnings.push(`Package version ${packageVersion} does not match release version ${release.version || "unknown"}.`);
  }
  if (runtimeVersion !== packageVersion) {
    warnings.push(`Runtime app version ${runtimeVersion} does not match package version ${packageVersion}.`);
  }
  const appPath = app.getAppPath();
  const launchPaths = [appPath, process.resourcesPath, process.execPath].filter(Boolean);
  if (launchPaths.some((item) => item.startsWith("/Volumes/"))) {
    warnings.push("App appears to be running from a mounted DMG volume. Copy or launch the newest local build instead.");
  }
  return {
    packageVersion,
    releaseVersion,
    releaseVersionRaw: release.version || "unknown",
    runtimeVersion,
    buildStatus: release.build_status || "unknown",
    productName: pkg.productName || release.product_name || "HigherKey Operator OS",
    appPath,
    execPath: process.execPath,
    resourcesPath: process.resourcesPath,
    appRoot: APP_ROOT,
    warnings,
    ok: warnings.length === 0
  };
}

function settingsPath() {
  return path.join(app.getPath("userData"), SETTINGS_NAME);
}

function defaultSettings() {
  return {
    version: 2,
    appName: "HigherKey Operator OS",
    packaged: app.isPackaged,
    assetRoot: APP_ROOT,
    activeProject: DEFAULT_PROJECT_ROOT,
    recentProjects: [DEFAULT_PROJECT_ROOT],
    profiles: {
      default: {
        name: "Default",
        projectPath: DEFAULT_PROJECT_ROOT,
        contentInbox: path.join(DEFAULT_PROJECT_ROOT, "content_inbox"),
        exportDirectory: path.join(DEFAULT_PROJECT_ROOT, "out", "approved_posts"),
        analyticsDirectory: path.join(DEFAULT_PROJECT_ROOT, "analytics"),
        startWatcherOnLaunch: false,
        setupCompleted: false,
        setupCompletedAt: null
      }
    }
  };
}

function projectProfile(settings) {
  const profile = settings.profiles?.default || {};
  return {
    projectRoot: settings.activeProject || profile.projectPath || activeProjectRoot || DEFAULT_PROJECT_ROOT,
    contentInbox: path.join(settings.activeProject || profile.projectPath || activeProjectRoot || DEFAULT_PROJECT_ROOT, "content_inbox"),
    exportDirectory: path.join(settings.activeProject || profile.projectPath || activeProjectRoot || DEFAULT_PROJECT_ROOT, "out", "approved_posts"),
    analyticsDirectory: path.join(settings.activeProject || profile.projectPath || activeProjectRoot || DEFAULT_PROJECT_ROOT, "analytics")
  };
}

async function readSettings() {
  try {
    const settings = JSON.parse(await fsp.readFile(settingsPath(), "utf8"));
    if (app.isPackaged && settings.packaged !== true) {
      settings.activeProject = DEFAULT_PROJECT_ROOT;
      settings.recentProjects = [DEFAULT_PROJECT_ROOT];
      settings.profiles = settings.profiles || {};
      settings.profiles.default = {
        ...(settings.profiles.default || {}),
        name: settings.profiles.default?.name || "Default",
        projectPath: DEFAULT_PROJECT_ROOT,
        contentInbox: path.join(DEFAULT_PROJECT_ROOT, "content_inbox"),
        exportDirectory: path.join(DEFAULT_PROJECT_ROOT, "out", "approved_posts"),
        analyticsDirectory: path.join(DEFAULT_PROJECT_ROOT, "analytics")
      };
    }
    const projectRoot = settings.activeProject || settings.profiles?.default?.projectPath || DEFAULT_PROJECT_ROOT;
    activeProjectRoot = projectRoot;
    await ensureRuntimeProject(projectRoot);
    return settings;
  } catch {
    const settings = defaultSettings();
    activeProjectRoot = settings.activeProject;
    await ensureRuntimeProject(activeProjectRoot);
    return settings;
  }
}

async function writeSettings(settings) {
  settings.version = Math.max(Number(settings.version || 1), 2);
  settings.appName = "HigherKey Operator OS";
  settings.packaged = app.isPackaged;
  settings.assetRoot = APP_ROOT;
  settings.activeProject = settings.activeProject || settings.profiles?.default?.projectPath || DEFAULT_PROJECT_ROOT;
  settings.profiles = settings.profiles || {};
  settings.profiles.default = settings.profiles.default || {};
  settings.profiles.default.projectPath = settings.activeProject;
  settings.profiles.default.contentInbox = path.join(settings.activeProject, "content_inbox");
  settings.profiles.default.exportDirectory = path.join(settings.activeProject, "out", "approved_posts");
  settings.profiles.default.analyticsDirectory = path.join(settings.activeProject, "analytics");
  settings.profiles.default.setupCompleted = Boolean(settings.profiles.default.setupCompleted);
  settings.profiles.default.setupCompletedAt = settings.profiles.default.setupCompletedAt || null;
  activeProjectRoot = settings.activeProject;
  await ensureRuntimeProject(activeProjectRoot);
  await fsp.mkdir(path.dirname(settingsPath()), { recursive: true });
  await fsp.writeFile(settingsPath(), JSON.stringify(settings, null, 2) + "\n");
  return settings;
}

async function ensureRuntimeProject(projectRoot) {
  for (const name of RUNTIME_DIRS) {
    await fsp.mkdir(path.join(projectRoot, name), { recursive: true });
  }
  const notesPath = path.join(projectRoot, "HIGHERKEY_OPERATOR_OS_SETUP.md");
  const runtimeContractPath = path.join(projectRoot, "config", "desktop_runtime.json");
  if (!app.isPackaged) {
    return;
  }
  const notes = [
    "# HigherKey Operator OS Local Project",
    "",
    "This folder stores writable runtime files for the packaged desktop app.",
    "",
    "- Drop source videos into `content_inbox/`.",
    "- Generated clips, captions, analytics, queue files, logs, and exports stay in this local project folder.",
    "- Packaged application resources are read-only and are not used for generated outputs.",
    "- No cloud APIs or social APIs are configured by this desktop setup.",
    "",
  ].join("\n");
  const contract = {
    version: 1,
    appName: "HigherKey Operator OS",
    packaged: app.isPackaged,
    projectRoot,
    assetRoot: APP_ROOT,
    localOnly: true,
    runtimeDirectories: [...RUNTIME_DIRS].sort(),
    notesPath,
    updatedAt: new Date().toISOString()
  };
  try {
    await fsp.writeFile(notesPath, notes, { flag: "wx" });
  } catch {
    // Keep user-edited setup notes intact after first launch.
  }
  await fsp.writeFile(runtimeContractPath, JSON.stringify(contract, null, 2) + "\n");
}

function safePathFromUrl(urlPath) {
  const decoded = decodeURIComponent(urlPath.split("?")[0]);
  const relative = decoded === "/" ? "dashboard/review.html" : decoded.replace(/^\/+/, "");
  const topLevel = relative.split(/[\\/]/)[0];
  const root = RUNTIME_DIRS.has(topLevel) ? activeProjectRoot : APP_ROOT;
  const target = path.resolve(root, relative);
  if (!target.startsWith(path.resolve(root))) {
    return null;
  }
  const fallback = root === activeProjectRoot ? path.resolve(APP_ROOT, relative) : null;
  if (fallback && !fallback.startsWith(path.resolve(APP_ROOT))) {
    return null;
  }
  return { target, fallback };
}

function startStaticServer() {
  return new Promise((resolve, reject) => {
    staticServer = http.createServer((request, response) => {
      const resolved = safePathFromUrl(request.url || "/");
      if (!resolved) {
        response.writeHead(403);
        response.end("Forbidden");
        return;
      }
      fs.readFile(resolved.target, (error, data) => {
        if (error) {
          if (!resolved.fallback) {
            response.writeHead(404);
            response.end("Not found");
            return;
          }
          fs.readFile(resolved.fallback, (fallbackError, fallbackData) => {
            if (fallbackError) {
              response.writeHead(404);
              response.end("Not found");
              return;
            }
            response.writeHead(200, { "Content-Type": MIME.get(path.extname(resolved.fallback)) || "application/octet-stream" });
            response.end(fallbackData);
          });
          return;
        }
        response.writeHead(200, { "Content-Type": MIME.get(path.extname(resolved.target)) || "application/octet-stream" });
        response.end(data);
      });
    });
    staticServer.listen(0, "127.0.0.1", () => {
      const address = staticServer.address();
      resolve(`http://127.0.0.1:${address.port}/dashboard/review.html`);
    });
    staticServer.on("error", reject);
  });
}

function createMenu() {
  const template = [
    {
      label: "File",
      submenu: [
        { label: "Open Project", click: () => pickDirectory("project") },
        { label: "Choose Content Inbox", click: () => pickDirectory("contentInbox") },
        { label: "Choose Export Directory", click: () => pickDirectory("exportDirectory") },
        { label: "Open Content Inbox", click: () => openContentInbox() },
        { label: "Run First-Run Setup", click: () => runFirstRunSetup(true) },
        { type: "separator" },
        { role: "quit" }
      ]
    },
    {
      label: "Pipeline",
      submenu: [
        { label: "Start Watcher", click: () => startWatcher() },
        { label: "Stop Watcher", click: () => stopWatcher() },
        { label: "Run One Daemon Tick", click: () => runPython(["scripts/watch_daemon.py", "--once"]) },
        { label: "Run Full Media Prep", click: () => runFullMediaPrep() },
        { label: "Run Orchestrator Once", click: () => runPython(["scripts/run_orchestrator.py", "--once"]) },
        { label: "Build Media Cache", click: () => runPython(["scripts/build_media_cache.py"]) },
        { label: "Run Diagnostics", click: () => runPython(["scripts/run_diagnostics.py"]) },
        { label: "Run Full QA", click: () => runPython(["scripts/run_full_qa.py"]) }
      ]
    },
    {
      label: "View",
      submenu: [
        { role: "reload" },
        { role: "toggleDevTools" },
        { role: "resetZoom" },
        { role: "zoomIn" },
        { role: "zoomOut" }
      ]
    },
    {
      label: "Tools",
      submenu: [
        { label: "Rebuild Metadata Index", click: () => runPython(["scripts/rebuild_metadata_index.py"]) },
        { label: "Open Project Folder", click: async () => shell.openPath((await readSettings()).activeProject || activeProjectRoot) }
      ]
    },
    {
      label: "Help",
      submenu: [
        { label: "Show Build Info", click: () => showBuildInfoPanel() },
        { label: "About HigherKey Operator OS", click: () => showAboutPanel() }
      ]
    }
  ];
  Menu.setApplicationMenu(Menu.buildFromTemplate(template));
}

async function createSplashWindow() {
  splashWindow = new BrowserWindow({
    width: 460,
    height: 360,
    frame: false,
    resizable: false,
    show: false,
    title: "HigherKey Operator OS",
    webPreferences: { sandbox: true }
  });
  await splashWindow.loadFile(path.join(__dirname, "splash.html"));
  splashWindow.once("ready-to-show", () => splashWindow?.show());
}

async function createWindow(url) {
  mainWindow = new BrowserWindow({
    width: 1440,
    height: 1000,
    minWidth: 1000,
    minHeight: 720,
    title: "HigherKey Operator OS",
    webPreferences: {
      preload: path.join(__dirname, "preload.js"),
      contextIsolation: true,
      nodeIntegration: false,
      sandbox: false
    }
  });
  await mainWindow.loadURL(url);
  splashWindow?.close();
  splashWindow = null;
  if (process.env.HK_ELECTRON_SMOKE === "1") {
    notify("HigherKey verification", "Electron notification path is wired.");
    setTimeout(() => app.quit(), 1200);
  }
}

async function showAboutPanel() {
  const info = releaseInfo();
  const build = buildInfo();
  let diagnosticsStatus = "not run";
  let qaStatus = "not run";
  try {
    diagnosticsStatus = JSON.parse(await fsp.readFile(path.join(activeProjectRoot, "analytics", "diagnostics.json"), "utf8")).status || diagnosticsStatus;
  } catch {}
  try {
    qaStatus = JSON.parse(await fsp.readFile(path.join(activeProjectRoot, "analytics", "qa_report.json"), "utf8")).status || qaStatus;
  } catch {}
  return dialog.showMessageBox(mainWindow, {
    type: "info",
    message: `${info.product_name} ${info.version}`,
    detail: [
      info.release_name,
      `Build status: ${info.build_status}`,
      `App ID: ${info.app_id}`,
      `Diagnostics: ${diagnosticsStatus}`,
      `Full QA: ${qaStatus}`,
      `Runtime version: ${build.runtimeVersion}`,
      `Package version: ${build.packageVersion}`,
      `Release version: ${build.releaseVersionRaw}`,
      build.warnings.length ? `Build warning: ${build.warnings.join(" ")}` : "Build versions aligned.",
      "",
      info.local_first_statement
    ].join("\n")
  });
}

async function showBuildInfoPanel() {
  const build = buildInfo();
  return dialog.showMessageBox(mainWindow, {
    type: build.ok ? "info" : "warning",
    message: `${build.productName} Build Info`,
    detail: [
      `Runtime version: ${build.runtimeVersion}`,
      `Package version: ${build.packageVersion}`,
      `Release version: ${build.releaseVersionRaw} (${build.releaseVersion})`,
      `Build status: ${build.buildStatus}`,
      `Packaged: ${app.isPackaged}`,
      `App path: ${build.appPath}`,
      `Resources path: ${build.resourcesPath}`,
      `Asset root: ${build.appRoot}`,
      `Active project: ${activeProjectRoot}`,
      "",
      build.warnings.length ? `Warnings:\n- ${build.warnings.join("\n- ")}` : "Versions aligned. This appears to be the current local build."
    ].join("\n")
  });
}

function runPython(args) {
  return new Promise((resolve) => {
    const cwd = activeProjectRoot;
    const [script, ...rest] = args;
    const scriptPath = path.isAbsolute(script) ? script : path.join(APP_ROOT, script);
    const startedAt = new Date().toISOString();
    const child = spawn("python3", [scriptPath, ...rest], {
      cwd,
      env: { ...process.env, PYTHONPATH: APP_ROOT }
    });
    let stdout = "";
    let stderr = "";
    child.stdout.on("data", (data) => { stdout += data.toString(); });
    child.stderr.on("data", (data) => { stderr += data.toString(); });
    child.on("close", (code) => resolve({ code, stdout, stderr, cwd, scriptPath, args: rest, startedAt, completedAt: new Date().toISOString() }));
  });
}

function tail(value, max = 4000) {
  const text = String(value || "");
  return text.length > max ? text.slice(-max) : text;
}

async function writePipelineLastRun(result, extra = {}) {
  const logsDir = path.join(activeProjectRoot, "logs");
  const analyticsDir = path.join(activeProjectRoot, "analytics");
  await fsp.mkdir(logsDir, { recursive: true });
  await fsp.mkdir(analyticsDir, { recursive: true });
  const payload = {
    state: extra.state_hint || (result.code === 0 ? "completed" : "failed"),
    message: extra.state_hint === "running" ? "Pipeline running" : (result.code === 0 ? "Pipeline completed" : "Pipeline failed"),
    local_only: true,
    active_project_root: activeProjectRoot,
    content_inbox: path.join(activeProjectRoot, "content_inbox"),
    last_run: {
      ...extra,
      cwd: result.cwd,
      script_path: result.scriptPath,
      args: result.args,
      returncode: result.code,
      stdout_tail: tail(result.stdout),
      stderr_tail: tail(result.stderr),
      started_at: result.startedAt,
      completed_at: result.completedAt
    },
    updated_at: new Date().toISOString()
  };
  await fsp.writeFile(path.join(logsDir, "pipeline_last_run.log"), [
    `started_at=${result.startedAt}`,
    `completed_at=${result.completedAt}`,
    `cwd=${result.cwd}`,
    `script=${result.scriptPath}`,
    `returncode=${result.code}`,
    "",
    "STDOUT:",
    result.stdout || "",
    "",
    "STDERR:",
    result.stderr || ""
  ].join("\n"), "utf8");
  await fsp.writeFile(path.join(analyticsDir, "pipeline_status.json"), JSON.stringify(payload, null, 2) + "\n");
  return payload;
}

async function runPipelineOnce() {
  const settings = await readSettings();
  const profile = projectProfile(settings);
  await fsp.mkdir(profile.contentInbox, { recursive: true });
  await writePipelineLastRun({
    code: null,
    stdout: "",
    stderr: "",
    cwd: activeProjectRoot,
    scriptPath: path.join(APP_ROOT, "scripts", "run_pipeline.py"),
    args: [],
    startedAt: new Date().toISOString(),
    completedAt: null
  }, { state_hint: "running" });
  const result = await runPython(["scripts/run_pipeline.py"]);
  const status = await writePipelineLastRun(result, { command: "run_pipeline.py" });
  let parsed = null;
  try {
    parsed = JSON.parse(result.stdout);
  } catch {}
  return { ...result, status, parsed, contentInbox: profile.contentInbox, activeProjectRoot };
}

async function importFootage() {
  await readSettings();
  const inbox = path.join(activeProjectRoot, "content_inbox");
  const selected = await dialog.showOpenDialog(mainWindow, {
    title: "Import Footage",
    buttonLabel: "Import Footage",
    properties: ["openFile", "multiSelections"],
    filters: [
      { name: "Video files", extensions: ["mp4", "mov", "m4v"] }
    ]
  });
  if (selected.canceled || !selected.filePaths.length) {
    return {
      imported: 0,
      skipped: [],
      errors: [],
      inbox,
      importedFiles: [],
      canceled: true
    };
  }
  const result = await ingestDroppedFilesToInbox(selected.filePaths, inbox);
  return {
    imported: result.copied.length,
    skipped: result.skipped,
    errors: result.errors,
    inbox: result.inbox,
    importedFiles: result.copied,
    accepted_extensions: result.accepted_extensions,
    canceled: false
  };
}

async function runFullMediaPrep() {
  const settings = await readSettings();
  const profile = projectProfile(settings);
  await fsp.mkdir(profile.contentInbox, { recursive: true });
  const steps = [
    { name: "Creating clips", stage: "creating_clips", args: ["scripts/run_pipeline.py"] },
    { name: "Indexing metadata", stage: "indexing_metadata", args: ["scripts/rebuild_metadata_index.py"] },
    { name: "Building thumbnails", stage: "building_thumbnails", args: ["scripts/build_media_cache.py"] },
    { name: "Updating agents", stage: "updating_agents", args: ["scripts/run_orchestrator.py", "--once"] }
  ];
  const results = [];
  for (const step of steps) {
    await writePipelineLastRun({
      code: null,
      stdout: "",
      stderr: "",
      cwd: activeProjectRoot,
      scriptPath: path.join(APP_ROOT, step.args[0]),
      args: step.args.slice(1),
      startedAt: new Date().toISOString(),
      completedAt: null
    }, { state_hint: "running", command: step.stage });
    const result = await runPython(step.args);
    results.push({ name: step.name, stage: step.stage, ...result });
    await writePipelineLastRun(result, { command: step.stage });
    if (result.code !== 0) {
      return { code: result.code, steps: results, activeProjectRoot, contentInbox: profile.contentInbox };
    }
  }
  return { code: 0, steps: results, activeProjectRoot, contentInbox: profile.contentInbox };
}

async function importAndProcessFootage() {
  const imported = await importFootage();
  if (imported.canceled || imported.imported === 0) {
    return {
      code: imported.errors.length ? 1 : 0,
      imported,
      prep: null,
      activeProjectRoot
    };
  }
  const prep = await runFullMediaPrep();
  return {
    code: prep.code,
    imported,
    prep,
    activeProjectRoot
  };
}

async function verifyImportBridge() {
  await readSettings();
  const inbox = path.join(activeProjectRoot, "content_inbox");
  return {
    ok: true,
    activeProjectRoot,
    inbox,
    acceptedExtensions: [".mp4", ".mov", ".m4v"],
    importFootage: "ready",
    importAndProcessFootage: "ready"
  };
}

async function verifyImportAndProcessBridge() {
  const bridge = await verifyImportBridge();
  return {
    ...bridge,
    fullMediaPrep: ["run_pipeline.py", "rebuild_metadata_index.py", "build_media_cache.py", "run_orchestrator.py --once"]
  };
}

async function archiveTestMedia() {
  const result = await runPython(["scripts/archive_test_media.py"]);
  let parsed = null;
  try {
    parsed = JSON.parse(result.stdout);
  } catch {}
  return { ...result, parsed, activeProjectRoot };
}

async function exportSocialPacks(_event, options = {}) {
  const platforms = Array.isArray(options.platforms) && options.platforms.length ? options.platforms : [];
  const approvedIds = Array.isArray(options.approvedIds) ? options.approvedIds.filter(Boolean) : [];
  const args = ["scripts/export_social_packs.py"];
  for (const platform of platforms) {
    args.push("--platform", String(platform));
  }
  for (const id of approvedIds) {
    args.push("--approved-id", String(id));
  }
  const result = await runPython(args);
  let parsed = null;
  try {
    parsed = JSON.parse(result.stdout);
  } catch {}
  return { ...result, parsed, activeProjectRoot };
}

async function startWatcher() {
  if (watcherProcess) {
    return { running: true, pid: watcherProcess.pid };
  }
  watcherProcess = spawn("python3", [path.join(APP_ROOT, "scripts", "watch_daemon.py"), "--interval", "5"], {
    cwd: activeProjectRoot,
    env: { ...process.env, PYTHONPATH: APP_ROOT }
  });
  watcherProcess.on("close", () => { watcherProcess = null; });
  return { running: true, pid: watcherProcess.pid };
}

async function stopWatcher() {
  if (!watcherProcess) {
    return { running: false };
  }
  watcherProcess.kill();
  watcherProcess = null;
  return { running: false };
}

function notify(title, body) {
  if (Notification.isSupported()) {
    new Notification({ title, body }).show();
  }
}

async function pollActivity() {
  const activityPath = path.join(activeProjectRoot, "analytics", "activity_feed.json");
  try {
    const payload = JSON.parse(await fsp.readFile(activityPath, "utf8"));
    const events = payload.events || [];
    if (lastActivityCount === 0) {
      lastActivityCount = events.length;
      return;
    }
    for (const event of events.slice(lastActivityCount)) {
      if (["completed", "failed", "retrying"].includes(event.event)) {
        notify(`HigherKey job ${event.event}`, event.message || event.source_path || "Pipeline update");
      }
    }
    lastActivityCount = events.length;
  } catch {
    // Activity file is optional until the daemon runs.
  }
}

async function pickDirectory(kind) {
  const result = await dialog.showOpenDialog(mainWindow, { properties: ["openDirectory", "createDirectory"] });
  if (result.canceled || !result.filePaths[0]) {
    return null;
  }
  const selected = result.filePaths[0];
  const settings = await readSettings();
  const profile = settings.profiles.default;
  if (kind === "project") {
    settings.activeProject = selected;
    profile.projectPath = selected;
    profile.contentInbox = path.join(selected, "content_inbox");
    profile.exportDirectory = path.join(selected, "out", "approved_posts");
    profile.analyticsDirectory = path.join(selected, "analytics");
    settings.recentProjects = [selected, ...(settings.recentProjects || []).filter((item) => item !== selected)].slice(0, 10);
  } else {
    profile[kind] = selected;
  }
  await writeSettings(settings);
  mainWindow?.webContents.send("higherkey:settings", settings);
  mainWindow?.webContents.send("higherkey:project", await appInfo());
  return selected;
}

async function openContentInbox() {
  const settings = await readSettings();
  const inbox = path.join(activeProjectRoot, "content_inbox");
  settings.profiles.default.contentInbox = inbox;
  await writeSettings(settings);
  await fsp.mkdir(inbox, { recursive: true });
  await shell.openPath(inbox);
  return { path: inbox, activeProjectRoot };
}

async function runFirstRunSetup(force = false) {
  if (process.env.HK_ELECTRON_SMOKE === "1") return { skipped: true, reason: "smoke mode" };
  const settings = await readSettings();
  const profile = settings.profiles.default;
  if (profile.setupCompleted && !force) return { skipped: true, reason: "already completed" };

  const start = await dialog.showMessageBox(mainWindow, {
    type: "info",
    buttons: ["Start Setup", "Use Defaults"],
    defaultId: 0,
    cancelId: 1,
    message: "Set up HigherKey Operator OS",
    detail: "Choose local folders, verify FFmpeg, run diagnostics, then open the Operator workspace."
  });
  if (start.response === 0) {
    const project = await dialog.showOpenDialog(mainWindow, { title: "Choose Project Folder", properties: ["openDirectory", "createDirectory"] });
    if (!project.canceled && project.filePaths[0]) {
      settings.activeProject = project.filePaths[0];
      activeProjectRoot = project.filePaths[0];
      profile.projectPath = project.filePaths[0];
      profile.contentInbox = path.join(project.filePaths[0], "content_inbox");
      profile.exportDirectory = path.join(project.filePaths[0], "out", "approved_posts");
      profile.analyticsDirectory = path.join(project.filePaths[0], "analytics");
    }
    const inbox = await dialog.showOpenDialog(mainWindow, { title: "Choose Content Inbox", properties: ["openDirectory", "createDirectory"] });
    if (!inbox.canceled && inbox.filePaths[0]) {
      profile.contentInbox = inbox.filePaths[0];
    }
  }
  await writeSettings(settings);
  const diagnostics = await runPython(["scripts/run_diagnostics.py"]);
  profile.setupCompleted = true;
  profile.setupCompletedAt = new Date().toISOString();
  await writeSettings(settings);
  mainWindow?.webContents.send("higherkey:settings", settings);
  await dialog.showMessageBox(mainWindow, {
    type: diagnostics.code === 0 ? "info" : "warning",
    message: diagnostics.code === 0 ? "Setup complete" : "Setup completed with diagnostics warnings",
    detail: "The Operator workspace is ready. Generated outputs will stay in the selected local project folder."
  });
  return { completed: true, diagnostics };
}

async function ingestDroppedFiles(filePaths) {
  await readSettings();
  const inbox = path.join(activeProjectRoot, "content_inbox");
  return ingestDroppedFilesToInbox(filePaths, inbox);
}

async function appInfo() {
  const settings = await readSettings();
  const profile = projectProfile(settings);
  const build = buildInfo();
  let lastPipeline = null;
  try {
    lastPipeline = JSON.parse(await fsp.readFile(path.join(profile.projectRoot, "analytics", "pipeline_status.json"), "utf8")).last_run || null;
  } catch {}
  return {
    ...releaseInfo(),
    packaged: app.isPackaged,
    devMode: !app.isPackaged,
    appRoot: APP_ROOT,
    projectRoot: profile.projectRoot,
    activeProjectRoot: profile.projectRoot,
    contentInbox: profile.contentInbox,
    analyticsDirectory: profile.analyticsDirectory,
    exportDirectory: profile.exportDirectory,
    lastPipeline,
    build,
    buildWarnings: build.warnings,
    packageVersion: build.packageVersion,
    runtimeVersion: build.runtimeVersion,
    releaseVersion: build.releaseVersionRaw
  };
}

async function useCurrentRepoProject() {
  if (app.isPackaged) {
    return { changed: false, reason: "Use Current Repo as Project is only available in dev mode.", ...(await appInfo()) };
  }
  const settings = await readSettings();
  settings.activeProject = APP_ROOT;
  settings.recentProjects = [APP_ROOT, ...(settings.recentProjects || []).filter((item) => item !== APP_ROOT)].slice(0, 10);
  await writeSettings(settings);
  mainWindow?.webContents.send("higherkey:settings", settings);
  mainWindow?.webContents.send("higherkey:project", await appInfo());
  return { changed: true, ...(await appInfo()) };
}

function registerIpc() {
  ipcMain.handle("settings:get", readSettings);
  ipcMain.handle("settings:set", async (_event, settings) => writeSettings(settings));
  ipcMain.handle("dialog:pickDirectory", (_event, kind) => pickDirectory(kind));
  ipcMain.handle("pipeline:startWatcher", startWatcher);
  ipcMain.handle("pipeline:stopWatcher", stopWatcher);
  ipcMain.handle("pipeline:status", () => ({ watcherRunning: Boolean(watcherProcess), watcherPid: watcherProcess?.pid || null }));
  ipcMain.handle("pipeline:runOnce", runPipelineOnce);
  ipcMain.handle("pipeline:runFullMediaPrep", runFullMediaPrep);
  ipcMain.handle("files:importFootage", importFootage);
  ipcMain.handle("files:importAndProcessFootage", importAndProcessFootage);
  ipcMain.handle("files:verifyImportBridge", verifyImportBridge);
  ipcMain.handle("files:verifyImportAndProcessBridge", verifyImportAndProcessBridge);
  ipcMain.handle("orchestrator:runOnce", () => runPython(["scripts/run_orchestrator.py", "--once"]));
  ipcMain.handle("media:buildCache", () => runPython(["scripts/build_media_cache.py"]));
  ipcMain.handle("media:archiveTestMedia", archiveTestMedia);
  ipcMain.handle("social:exportPacks", exportSocialPacks);
  ipcMain.handle("diagnostics:run", () => runPython(["scripts/run_diagnostics.py"]));
  ipcMain.handle("qa:runFull", () => runPython(["scripts/run_full_qa.py"]));
  ipcMain.handle("app:info", appInfo);
  ipcMain.handle("project:useCurrentRepo", useCurrentRepoProject);
  ipcMain.handle("app:about", showAboutPanel);
  ipcMain.handle("setup:firstRun", () => runFirstRunSetup(true));
  ipcMain.handle("folder:openContentInbox", openContentInbox);
  ipcMain.handle("files:ingestDropped", (_event, filePaths) => ingestDroppedFiles(filePaths));
  ipcMain.handle("notify:test", () => {
    notify("HigherKey notification test", "Local notifications are wired.");
    return { sent: Notification.isSupported() };
  });
}

app.whenReady().then(async () => {
  await createSplashWindow();
  await writeSettings(await readSettings());
  registerIpc();
  createMenu();
  const url = await startStaticServer();
  await createWindow(url);
  await runFirstRunSetup(false);
  activityPoll = setInterval(pollActivity, 4000);
  const settings = await readSettings();
  if (settings.profiles.default.startWatcherOnLaunch) {
    startWatcher();
  }
});

app.on("window-all-closed", () => {
  if (process.platform !== "darwin") {
    app.quit();
  }
});

app.on("before-quit", () => {
  if (activityPoll) clearInterval(activityPoll);
  if (watcherProcess) watcherProcess.kill();
  if (staticServer) staticServer.close();
});
