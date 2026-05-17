const { app, BrowserWindow, Menu, dialog, ipcMain, Notification, shell } = require("electron");
const http = require("node:http");
const fs = require("node:fs");
const fsp = require("node:fs/promises");
const os = require("node:os");
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
let localApiProcess = null;
let activityPoll = null;
let lastActivityCount = 0;
let activeProjectRoot = DEFAULT_PROJECT_ROOT;
let releaseInfoCache = null;
let securityPolicyCache = null;

function securityPolicy() {
  if (securityPolicyCache) return securityPolicyCache;
  try {
    securityPolicyCache = JSON.parse(fs.readFileSync(path.join(APP_ROOT, "config", "security_policy.json"), "utf8"));
  } catch {
    securityPolicyCache = {
      allowed_import_extensions: [".mp4", ".mov", ".m4v"],
      max_import_file_size_mb: 20480,
      allowed_script_actions: [],
      protected_dirs: ["/", "/Applications", "/System", "/Library", "/usr", "/bin", "/sbin", "/private"],
      denied_project_roots: ["/", "/Users", "/Applications", "/System", "/Library"],
      destructive_actions_require_confirmation: ["restore_project", "reset_demo_workspace", "archive_project_artifacts", "reconcile_apply", "backup_project"]
    };
  }
  return securityPolicyCache;
}

function securityFail(message, extra = {}) {
  return { ok: false, status: "fail", message, error: message, security: true, ...extra };
}

function validateProjectRootSelection(selected) {
  const resolved = path.resolve(selected);
  const denied = new Set([path.parse(resolved).root, os.homedir(), ...securityPolicy().denied_project_roots.map((item) => path.resolve(item))]);
  if (path.basename(resolved) === "content_inbox") {
    return securityFail("Select the project folder, not the inbox folder.", { suggestedProjectRoot: path.dirname(resolved) });
  }
  if (denied.has(resolved)) {
    return securityFail("That folder cannot be used as a project.", { path: resolved });
  }
  return { ok: true, status: "pass", path: resolved, message: "Project folder is allowed." };
}

function validateImportSelection(filePath) {
  const resolved = path.resolve(filePath);
  const extension = path.extname(resolved).toLowerCase();
  const allowed = new Set(securityPolicy().allowed_import_extensions || [".mp4", ".mov", ".m4v"]);
  if (!allowed.has(extension)) {
    return securityFail("This file type is not supported.", { path: resolved, extension });
  }
  let stats = null;
  try {
    stats = fs.statSync(resolved);
  } catch {
    return securityFail("The selected file was not found.", { path: resolved });
  }
  if (!stats.isFile()) {
    return securityFail("Only video files can be imported.", { path: resolved });
  }
  const maxBytes = Number(securityPolicy().max_import_file_size_mb || 20480) * 1024 * 1024;
  if (stats.size > maxBytes) {
    return securityFail("This file is larger than the import limit.", { path: resolved, size: stats.size });
  }
  for (const protectedDir of ["/System", "/Library", "/Applications"]) {
    const protectedPath = path.resolve(protectedDir);
    if (resolved === protectedPath || resolved.startsWith(`${protectedPath}${path.sep}`)) {
      return securityFail("Files from protected system folders cannot be imported.", { path: resolved });
    }
  }
  return { ok: true, status: "pass", path: resolved, extension, size: stats.size };
}

function filterImportSelections(filePaths) {
  const valid = [];
  const errors = [];
  for (const filePath of filePaths || []) {
    const result = validateImportSelection(filePath);
    if (result.ok) valid.push(result.path);
    else errors.push(result);
  }
  return { valid, errors };
}

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
        worker: { auto_start: false },
        local_api: { auto_start: false, port: 8765 },
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
        analyticsDirectory: path.join(DEFAULT_PROJECT_ROOT, "analytics"),
        worker: settings.profiles.default?.worker || { auto_start: false },
        local_api: settings.profiles.default?.local_api || { auto_start: false, port: 8765 }
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
  settings.profiles.default.worker = settings.profiles.default.worker || { auto_start: false };
  settings.profiles.default.local_api = settings.profiles.default.local_api || { auto_start: false, port: 8765 };
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
        { label: "Run Color School", click: () => runColorSchool() },
        { label: "Run Audio School", click: () => runAudioSchool() },
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

function parseJsonOutput(value) {
  try {
    return JSON.parse(value || "{}");
  } catch {
    return null;
  }
}

async function projectClipCounts() {
  const queuePath = path.join(activeProjectRoot, "queue", "review_queue.json");
  const repairPath = path.join(activeProjectRoot, "analytics", "project_repair_report.json");
  let queueEntries = 0;
  let missingSources = 0;
  let staleQueueEntries = 0;
  try {
    const queue = JSON.parse(await fsp.readFile(queuePath, "utf8"));
    queueEntries = Array.isArray(queue.entries) ? queue.entries.length : 0;
  } catch {}
  try {
    const repair = JSON.parse(await fsp.readFile(repairPath, "utf8"));
    missingSources = Number(repair.counts?.missing_sources || 0);
    staleQueueEntries = Number(repair.counts?.stale_queue_entries || 0);
  } catch {}
  return { queueEntries, missingSources, staleQueueEntries };
}

async function classifyPipelineResult(result, extra = {}) {
  const parsed = extra.parsed || parseJsonOutput(result.stdout);
  const counts = await projectClipCounts();
  const validClips = Number(parsed?.valid_clips ?? parsed?.queue_entries ?? counts.queueEntries ?? 0);
  const missingSources = Number(parsed?.missing_sources ?? counts.missingSources ?? 0);
  const staleQueueEntries = Number(extra.staleQueueEntries ?? counts.staleQueueEntries ?? 0);
  const warnings = Array.isArray(parsed?.warnings) ? parsed.warnings.length : 0;
  const errors = Array.isArray(parsed?.errors) ? parsed.errors.length : 0;
  const parsedSeverity = parsed?.severity || parsed?.status;

  if (extra.state_hint === "running") {
    return { state: "running", severity: "warn", message: "Pipeline running", validClips, missingSources, staleQueueEntries, warnings, errors, parsed };
  }
  if (parsedSeverity === "fail" || (result.code !== 0 && validClips === 0)) {
    return { state: "failed", severity: "fail", message: "No valid media found. Import footage to begin.", validClips, missingSources, staleQueueEntries, warnings, errors, parsed };
  }
  if (parsedSeverity === "needs_attention" || parsedSeverity === "warn" || result.code !== 0 || warnings || errors || missingSources || staleQueueEntries) {
    return {
      state: "needs_attention",
      severity: "needs_attention",
      message: `Some older media references were skipped. ${validClips} clips are ready.`,
      validClips,
      missingSources,
      staleQueueEntries,
      warnings,
      errors,
      parsed
    };
  }
  if (validClips === 0 && parsed?.discovered === 0) {
    return { state: "empty", severity: "warn", message: "Import footage to begin.", validClips, missingSources, staleQueueEntries, warnings, errors, parsed };
  }
  return { state: "completed", severity: "pass", message: "Pipeline completed. Clips are ready.", validClips, missingSources, staleQueueEntries, warnings, errors, parsed };
}

async function writePipelineLastRun(result, extra = {}) {
  const logsDir = path.join(activeProjectRoot, "logs");
  const analyticsDir = path.join(activeProjectRoot, "analytics");
  await fsp.mkdir(logsDir, { recursive: true });
  await fsp.mkdir(analyticsDir, { recursive: true });
  const classification = await classifyPipelineResult(result, extra);
  const payload = {
    state: classification.state,
    severity: classification.severity,
    status: classification.severity,
    message: classification.message,
    local_only: true,
    active_project_root: activeProjectRoot,
    content_inbox: path.join(activeProjectRoot, "content_inbox"),
    summary: {
      valid_clips: classification.validClips,
      queue_entries: classification.validClips,
      missing_sources: classification.missingSources,
      stale_queue_entries: classification.staleQueueEntries,
      warnings: classification.warnings,
      errors: classification.errors
    },
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
  const projectCheck = validateProjectRootSelection(activeProjectRoot);
  if (!projectCheck.ok) {
    return {
      imported: 0,
      skipped: [],
      errors: [{ reason: projectCheck.message || "That folder cannot be used as a project." }],
      inbox,
      importedFiles: [],
      canceled: false,
      status: "fail",
      message: projectCheck.message || "That folder cannot be used as a project."
    };
  }
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
  const filtered = filterImportSelections(selected.filePaths);
  if (!filtered.valid.length) {
    return {
      imported: 0,
      skipped: [],
      errors: filtered.errors,
      inbox,
      importedFiles: [],
      canceled: false,
      status: "fail",
      message: "No supported footage files were selected."
    };
  }
  const result = await ingestDroppedFilesToInbox(filtered.valid, inbox);
  const errors = [...filtered.errors, ...result.errors];
  const imported = result.copied.length;
  return {
    imported,
    skipped: result.skipped,
    errors,
    inbox: result.inbox,
    importedFiles: result.copied,
    accepted_extensions: result.accepted_extensions,
    canceled: false,
    status: imported ? (errors.length ? "warn" : "pass") : "fail",
    message: imported
      ? `${imported} video${imported === 1 ? "" : "s"} imported.`
      : "No supported footage files were imported."
  };
}

async function runFullMediaPrep() {
  const projectCheck = validateProjectRootSelection(activeProjectRoot);
  if (!projectCheck.ok) return projectCheck;
  const settings = await readSettings();
  const profile = projectProfile(settings);
  await fsp.mkdir(profile.contentInbox, { recursive: true });
  const steps = [
    { name: "Preparing project", stage: "repair_preflight", args: ["scripts/repair_project_media.py"] },
    { name: "Creating clips", stage: "creating_clips", args: ["scripts/run_pipeline.py"] },
    { name: "Indexing metadata", stage: "indexing_metadata", args: ["scripts/rebuild_metadata_index.py"] },
    { name: "Building previews", stage: "building_previews", args: ["scripts/build_media_cache.py"] },
    { name: "Checking color", stage: "checking_color", args: ["scripts/run_color_school.py"], optional: true },
    { name: "Checking audio", stage: "checking_audio", args: ["scripts/run_audio_school.py"], optional: true },
    { name: "Preparing recommendations", stage: "updating_agents", args: ["scripts/run_orchestrator.py", "--once"], optional: true },
    { name: "Updating workspace", stage: "client_workflow", args: ["scripts/build_client_workflow.py"], optional: true },
    { name: "Refreshing client state", stage: "client_state", args: ["scripts/build_runtime_snapshot.py"], optional: true }
  ];
  const results = [];
  let staleQueueEntries = 0;
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
    const parsed = parseJsonOutput(result.stdout);
    if (step.stage === "repair_preflight") {
      staleQueueEntries = Number(parsed?.counts?.stale_queue_entries || 0);
    }
    results.push({ name: step.name, stage: step.stage, parsed, ...result });
    const status = await writePipelineLastRun(result, { command: step.stage, parsed, staleQueueEntries });
    if (result.code !== 0 && status.severity === "fail" && !step.optional) {
      return { code: result.code, status, steps: results, activeProjectRoot, contentInbox: profile.contentInbox };
    }
  }
  const finalStatus = await writePipelineLastRun({
    code: 0,
    stdout: JSON.stringify({
      severity: staleQueueEntries ? "needs_attention" : "pass",
      stale_queue_entries: staleQueueEntries
    }),
    stderr: "",
    cwd: activeProjectRoot,
    scriptPath: "full_media_prep",
    args: [],
    startedAt: results[0]?.startedAt || new Date().toISOString(),
    completedAt: new Date().toISOString()
  }, { command: "full_media_prep", staleQueueEntries });
  const code = finalStatus.severity === "fail" ? 1 : 0;
  return { code, status: finalStatus, steps: results, activeProjectRoot, contentInbox: profile.contentInbox };
}

async function repairProjectMedia() {
  const result = await runPython(["scripts/repair_project_media.py"]);
  let parsed = null;
  try {
    parsed = JSON.parse(result.stdout);
  } catch {}
  return { ...result, parsed, activeProjectRoot };
}

async function runMaintenance() {
  const check = validateProjectRootSelection(activeProjectRoot);
  if (!check.ok) return check;
  return runPython(["scripts/run_maintenance.py"]);
}

async function buildRuntimeSnapshot() {
  return runPython(["scripts/build_runtime_snapshot.py"]);
}

async function getClientState() {
  const profile = await currentProfile();
  const clientStatePath = path.join(profile.projectRoot, "analytics", "client_state.json");
  try {
    const payload = JSON.parse(await fsp.readFile(clientStatePath, "utf8"));
    return { ok: true, path: clientStatePath, clientState: payload };
  } catch (error) {
    return { ok: false, path: clientStatePath, error: String(error?.message || error) };
  }
}

async function buildClientWorkflow() {
  return runPython(["scripts/build_client_workflow.py"]);
}

async function getClientWorkflow() {
  const profile = await currentProfile();
  const workflowPath = path.join(profile.projectRoot, "analytics", "client_workflow.json");
  try {
    const payload = JSON.parse(await fsp.readFile(workflowPath, "utf8"));
    return { ok: true, path: workflowPath, workflow: payload };
  } catch (error) {
    return { ok: false, path: workflowPath, error: String(error?.message || error) };
  }
}

async function createDemoProject() {
  const check = validateProjectRootSelection(activeProjectRoot);
  if (!check.ok) return check;
  return runPython(["scripts/create_demo_project.py", "--target", activeProjectRoot]);
}

async function collectClientFeedback(options = {}) {
  const args = ["scripts/collect_client_feedback.py"];
  if (options.template) args.push("--template");
  if (options.exportSummary) args.push("--export-summary");
  if (options.json) args.push("--json");
  if (options.interactive) args.push("--interactive");
  if (options.dryRun) args.push("--dry-run");
  const fields = {
    clientName: "--client-name",
    sessionDate: "--session-date",
    whatWorked: "--what-worked",
    whatConfusedYou: "--what-confused-you",
    bugsSeen: "--bugs-seen",
    featureRequests: "--feature-requests",
    uploadWorkflowRating: "--upload-workflow-rating",
    overallRating: "--overall-rating",
    notes: "--notes"
  };
  for (const [key, flag] of Object.entries(fields)) {
    if (options[key]) args.push(flag, String(options[key]));
  }
  return runPython(args);
}

async function openFeedbackFolder() {
  const feedbackDir = path.join(activeProjectRoot, "analytics");
  await fsp.mkdir(feedbackDir, { recursive: true });
  await shell.openPath(feedbackDir);
  return { ok: true, path: feedbackDir, activeProjectRoot };
}

async function createIssueReport() {
  return runPython(["scripts/create_issue_report.py"]);
}

async function openIssueReportFolder() {
  const reportDir = path.join(activeProjectRoot, "out", "client_issue_report");
  await fsp.mkdir(reportDir, { recursive: true });
  await shell.openPath(reportDir);
  return { path: reportDir, activeProjectRoot };
}

async function buildTrialPackage() {
  const check = validateProjectRootSelection(activeProjectRoot);
  if (!check.ok) return check;
  return runPython(["scripts/package_trial_release.py"]);
}

async function openTrialPackageFolder() {
  const trialDir = path.join(activeProjectRoot, "out", "trial_release");
  await fsp.mkdir(trialDir, { recursive: true });
  await shell.openPath(trialDir);
  return { ok: true, path: trialDir, activeProjectRoot };
}

async function getTrialReadiness() {
  const profile = await currentProfile();
  return {
    ok: true,
    activeProjectRoot,
    path: path.join(profile.projectRoot, "analytics", "trial_readiness_report.json"),
    readiness: await readAnalyticsJson("trial_readiness_report.json", {})
  };
}

async function getStorageReport() {
  const profile = await currentProfile();
  return { ok: true, activeProjectRoot, report: await readAnalyticsJson("cache_report.json", {}), path: path.join(profile.projectRoot, "analytics", "cache_report.json") };
}

async function getClientStorage() {
  const profile = await currentProfile();
  return { ok: true, activeProjectRoot, storage: await readAnalyticsJson("client_storage.json", {}), path: path.join(profile.projectRoot, "analytics", "client_storage.json") };
}

function storageCommand(args, options = {}) {
  if ((args.includes("apply") || args.includes("archive") || args.includes("vacuum-db")) && options.apply && !options.confirmed) {
    return securityFail("This action requires confirmation.", { action: args[0] });
  }
  return runPython(["scripts/manage_storage.py", ...args]);
}

async function buildCleanupPlan(options = {}) {
  const args = ["plan", "--dry-run"];
  if (options.category) args.push("--category", String(options.category));
  return storageCommand(args, options);
}

async function applyCleanupPlan(options = {}) {
  const args = ["apply"];
  if (options.apply) args.push("--apply");
  if (options.confirmed) args.push("--confirm");
  if (options.category) args.push("--category", String(options.category));
  return storageCommand(args, options);
}

async function archiveGeneratedArtifacts(options = {}) {
  const args = ["archive"];
  if (!options.apply) args.push("--dry-run");
  if (options.apply) args.push("--apply");
  if (options.confirmed) args.push("--confirm");
  if (options.category) args.push("--category", String(options.category));
  return storageCommand(args, options);
}

async function vacuumRuntimeDb(options = {}) {
  const args = ["vacuum-db"];
  if (options.apply) args.push("--apply");
  if (options.confirmed) args.push("--confirm");
  return storageCommand(args, options);
}

async function checkUpgradeStatus() {
  return { ok: true, activeProjectRoot, upgrade: await readAnalyticsJson("client_upgrade_status.json", {}) };
}

async function buildUpgradePlan() {
  return runPython(["scripts/upgrade_project.py", "--plan"]);
}

async function runUpgradeCheck() {
  return runPython(["scripts/upgrade_project.py", "--check"]);
}

async function runLaunchPreflight() {
  return runPython(["scripts/run_launch_preflight.py"]);
}

async function validateDataContract() {
  return runPython(["scripts/validate_data_contract.py"]);
}

async function enqueueFullMediaPrep() {
  const result = await runPython(["scripts/enqueue_full_media_prep.py"]);
  let parsed = null;
  try {
    parsed = JSON.parse(result.stdout);
  } catch {}
  return { ...result, parsed, activeProjectRoot };
}

async function runTaskWorkerOnce() {
  const result = await runPython(["scripts/run_task_worker.py", "--once"]);
  let parsed = null;
  try {
    parsed = JSON.parse(result.stdout);
  } catch {}
  return { ...result, parsed, activeProjectRoot };
}

async function getTaskSummary() {
  await runPython(["scripts/build_task_snapshot.py"]);
  const profile = await currentProfile();
  const clientTasksPath = path.join(profile.projectRoot, "analytics", "client_tasks.json");
  try {
    const payload = JSON.parse(await fsp.readFile(clientTasksPath, "utf8"));
    return { ok: true, path: clientTasksPath, clientTasks: payload };
  } catch (error) {
    return { ok: false, path: clientTasksPath, error: String(error?.message || error) };
  }
}

function workerCommand(command) {
  return runPython(["scripts/manage_worker.py", command]);
}

async function lifecycleScript(script, options = {}) {
  const projectCheck = validateProjectRootSelection(activeProjectRoot);
  if (!projectCheck.ok) return projectCheck;
  if (script === "scripts/reset_demo_workspace.py" && !options?.dryRun && !options?.confirmed) {
    return securityFail("This action requires confirmation.", { action: "reset_demo_workspace" });
  }
  if (script === "scripts/archive_project_artifacts.py" && !options?.dryRun && !options?.confirmed) {
    return securityFail("This action requires confirmation.", { action: "archive_project_artifacts" });
  }
  const args = [script];
  if (script === "scripts/backup_project.py") {
    if (options?.dryRun) args.push("--dry-run");
    if (options?.includeSourceMedia) args.push("--include-source-media");
    if (options?.includeCache) args.push("--include-cache");
  }
  if (script === "scripts/reset_demo_workspace.py") {
    args.push(options?.hard ? "--hard" : "--soft");
    if (options?.dryRun) args.push("--dry-run");
    if (options?.archiveFirst) args.push("--archive-first");
    if (options?.confirmDeleteSourceMedia) args.push("--confirm-delete-source-media");
  }
  if (script === "scripts/archive_project_artifacts.py" && options?.dryRun) args.push("--dry-run");
  const result = await runPython(args);
  let parsed = null;
  try {
    parsed = JSON.parse(result.stdout);
  } catch {}
  return { ...result, parsed, activeProjectRoot };
}

async function localApiStatus() {
  const profile = await currentProfile();
  const statusPath = path.join(profile.projectRoot, "analytics", "local_api_status.json");
  let status = null;
  try {
    status = JSON.parse(await fsp.readFile(statusPath, "utf8"));
  } catch {}
  return {
    ok: true,
    running: Boolean(localApiProcess && localApiProcess.exitCode === null),
    pid: localApiProcess?.pid || null,
    status,
    activeProjectRoot
  };
}

async function startLocalApi() {
  if (localApiProcess && localApiProcess.exitCode === null) {
    return { ok: true, running: true, pid: localApiProcess.pid, activeProjectRoot };
  }
  const settings = await readSettings();
  const port = Number(settings.profiles.default.local_api?.port || 8765);
  const scriptPath = path.join(APP_ROOT, "scripts", "run_local_api.py");
  localApiProcess = spawn("python3", [scriptPath, "--port", String(port), "--write-status"], {
    cwd: activeProjectRoot,
    env: { ...process.env, PYTHONPATH: APP_ROOT },
    stdio: "ignore"
  });
  localApiProcess.on("exit", () => {
    localApiProcess = null;
  });
  return { ok: true, running: true, pid: localApiProcess.pid, port, activeProjectRoot };
}

async function stopLocalApi() {
  if (!localApiProcess || localApiProcess.exitCode !== null) {
    localApiProcess = null;
    return { ok: true, running: false, activeProjectRoot };
  }
  const pid = localApiProcess.pid;
  localApiProcess.kill("SIGTERM");
  localApiProcess = null;
  return { ok: true, stopped: true, pid, activeProjectRoot };
}

async function callLocalApi(_event, apiPath, options = {}) {
  if (!String(apiPath || "").startsWith("/")) {
    return { ok: false, status: "fail", message: "Local API path must start with /." };
  }
  const settings = await readSettings();
  const port = Number(settings.profiles.default.local_api?.port || 8765);
  const method = String(options.method || "GET").toUpperCase();
  const body = options.body ? JSON.stringify(options.body) : "";
  return new Promise((resolve) => {
    const request = http.request({
      hostname: "127.0.0.1",
      port,
      path: apiPath,
      method,
      headers: {
        "Content-Type": "application/json",
        "Content-Length": Buffer.byteLength(body)
      }
    }, (response) => {
      let data = "";
      response.on("data", (chunk) => { data += chunk.toString(); });
      response.on("end", () => {
        try {
          resolve(JSON.parse(data));
        } catch {
          resolve({ ok: false, status: "fail", message: "Local API returned invalid JSON.", code: response.statusCode });
        }
      });
    });
    request.on("error", (error) => resolve({ ok: false, status: "fail", message: String(error?.message || error) }));
    if (body) request.write(body);
    request.end();
  });
}

async function readAnalyticsJson(filename, fallback = {}) {
  const profile = await currentProfile();
  const jsonPath = path.join(profile.projectRoot, "analytics", filename);
  try {
    return JSON.parse(await fsp.readFile(jsonPath, "utf8"));
  } catch {
    return fallback;
  }
}

async function getRuntimeMetrics() {
  return { ok: true, activeProjectRoot, metrics: await readAnalyticsJson("runtime_metrics.json", {}) };
}

async function getClientMetrics() {
  return { ok: true, activeProjectRoot, metrics: await readAnalyticsJson("client_metrics.json", {}) };
}

async function getAuditLog() {
  const profile = await currentProfile();
  const auditPath = path.join(profile.projectRoot, "analytics", "audit_log.jsonl");
  try {
    const lines = (await fsp.readFile(auditPath, "utf8")).trim().split(/\n+/).filter(Boolean).slice(-100);
    return { ok: true, activeProjectRoot, events: lines.map((line) => JSON.parse(line)) };
  } catch {
    return { ok: true, activeProjectRoot, events: [] };
  }
}

async function runColorSchool() {
  const result = await runPython(["scripts/run_color_school.py"]);
  let parsed = null;
  try {
    parsed = JSON.parse(result.stdout);
  } catch {}
  return { ...result, parsed, activeProjectRoot };
}

async function runAudioSchool() {
  const result = await runPython(["scripts/run_audio_school.py"]);
  let parsed = null;
  try {
    parsed = JSON.parse(result.stdout);
  } catch {}
  return { ...result, parsed, activeProjectRoot };
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

async function importAndQueueFootage() {
  const imported = await importFootage();
  if (imported.canceled || imported.imported === 0) {
    return { code: imported.errors.length ? 1 : 0, imported, queued: null, worker: null, activeProjectRoot };
  }
  const queued = await enqueueFullMediaPrep();
  const worker = await runTaskWorkerOnce();
  return { code: worker.code || queued.code || 0, imported, queued, worker, activeProjectRoot };
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
    fullMediaPrep: [
      "repair_project_media.py",
      "run_pipeline.py",
      "rebuild_metadata_index.py",
      "build_media_cache.py",
      "run_color_school.py",
      "run_audio_school.py",
      "run_orchestrator.py --once",
      "build_client_workflow.py",
      "build_runtime_snapshot.py"
    ]
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
  const projectCheck = validateProjectRootSelection(activeProjectRoot);
  if (!projectCheck.ok) return projectCheck;
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
  let selected = result.filePaths[0];
  const settings = await readSettings();
  const profile = settings.profiles.default;
  if (kind === "project") {
    selected = await normalizeProjectSelection(selected);
    if (!selected) return null;
    const security = validateProjectRootSelection(selected);
    if (!security.ok) {
      await dialog.showMessageBox(mainWindow, {
        type: "warning",
        message: security.message,
        detail: security.suggestedProjectRoot ? `Suggested project folder: ${security.suggestedProjectRoot}` : "Choose a writable project folder that contains or can contain content_inbox."
      });
      return security;
    }
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

async function normalizeProjectSelection(selected) {
  if (path.basename(selected) !== "content_inbox") {
    return selected;
  }
  const parent = path.dirname(selected);
  const choice = await dialog.showMessageBox(mainWindow, {
    type: "warning",
    buttons: ["Use Parent Project Folder", "Cancel"],
    defaultId: 0,
    cancelId: 1,
    message: "You selected the inbox folder.",
    detail: "Select the project folder that contains content_inbox instead."
  });
  return choice.response === 0 ? parent : null;
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

async function openSocialExportsFolder() {
  const exportDir = path.join(activeProjectRoot, "out", "social_exports");
  await fsp.mkdir(exportDir, { recursive: true });
  await shell.openPath(exportDir);
  return { path: exportDir, activeProjectRoot };
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
      const selectedProject = await normalizeProjectSelection(project.filePaths[0]);
      if (selectedProject) {
        settings.activeProject = selectedProject;
        activeProjectRoot = selectedProject;
        profile.projectPath = selectedProject;
        profile.contentInbox = path.join(selectedProject, "content_inbox");
        profile.exportDirectory = path.join(selectedProject, "out", "approved_posts");
        profile.analyticsDirectory = path.join(selectedProject, "analytics");
      }
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
  const projectCheck = validateProjectRootSelection(activeProjectRoot);
  if (!projectCheck.ok) {
    return {
      copied: [],
      imported: 0,
      importedFiles: [],
      skipped: [],
      errors: [{ reason: projectCheck.message || "That folder cannot be used as a project." }],
      inbox,
      accepted_extensions: [".mp4", ".mov", ".m4v"],
      status: "fail",
      message: projectCheck.message || "That folder cannot be used as a project."
    };
  }
  const filtered = filterImportSelections(filePaths || []);
  if (!filtered.valid.length) {
    return {
      copied: [],
      imported: 0,
      importedFiles: [],
      skipped: [],
      errors: filtered.errors,
      inbox,
      accepted_extensions: [".mp4", ".mov", ".m4v"],
      status: "fail",
      message: "No supported footage files were dropped."
    };
  }
  const result = await ingestDroppedFilesToInbox(filtered.valid, inbox);
  const errors = [...filtered.errors, ...result.errors];
  const imported = result.copied.length;
  return {
    ...result,
    imported,
    importedFiles: result.copied,
    errors,
    status: imported ? (errors.length ? "warn" : "pass") : "fail",
    message: imported
      ? `${imported} video${imported === 1 ? "" : "s"} imported.`
      : "No supported footage files were imported."
  };
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
  ipcMain.handle("files:importAndQueueFootage", importAndQueueFootage);
  ipcMain.handle("files:verifyImportBridge", verifyImportBridge);
  ipcMain.handle("files:verifyImportAndProcessBridge", verifyImportAndProcessBridge);
  ipcMain.handle("orchestrator:runOnce", () => runPython(["scripts/run_orchestrator.py", "--once"]));
  ipcMain.handle("media:buildCache", () => runPython(["scripts/build_media_cache.py"]));
  ipcMain.handle("media:archiveTestMedia", archiveTestMedia);
  ipcMain.handle("media:repairProject", repairProjectMedia);
  ipcMain.handle("school:runColor", runColorSchool);
  ipcMain.handle("school:runAudio", runAudioSchool);
  ipcMain.handle("social:exportPacks", exportSocialPacks);
  ipcMain.handle("diagnostics:run", () => runPython(["scripts/run_diagnostics.py"]));
  ipcMain.handle("runtime:runMaintenance", runMaintenance);
  ipcMain.handle("runtime:buildSnapshot", buildRuntimeSnapshot);
  ipcMain.handle("runtime:getClientState", getClientState);
  ipcMain.handle("workflow:buildClient", buildClientWorkflow);
  ipcMain.handle("workflow:getClient", getClientWorkflow);
  ipcMain.handle("workflow:createDemoProject", createDemoProject);
  ipcMain.handle("feedback:collectClient", (_event, options = {}) => collectClientFeedback(options));
  ipcMain.handle("feedback:openFolder", openFeedbackFolder);
  ipcMain.handle("support:createIssueReport", createIssueReport);
  ipcMain.handle("support:openIssueReportFolder", openIssueReportFolder);
  ipcMain.handle("trial:buildPackage", buildTrialPackage);
  ipcMain.handle("trial:openPackageFolder", openTrialPackageFolder);
  ipcMain.handle("trial:getReadiness", getTrialReadiness);
  ipcMain.handle("storage:getReport", getStorageReport);
  ipcMain.handle("storage:getClient", getClientStorage);
  ipcMain.handle("storage:buildCleanupPlan", (_event, options = {}) => buildCleanupPlan(options));
  ipcMain.handle("storage:applyCleanupPlan", (_event, options = {}) => applyCleanupPlan(options));
  ipcMain.handle("storage:archiveGeneratedArtifacts", (_event, options = {}) => archiveGeneratedArtifacts(options));
  ipcMain.handle("storage:vacuumRuntimeDb", (_event, options = {}) => vacuumRuntimeDb(options));
  ipcMain.handle("upgrade:getStatus", checkUpgradeStatus);
  ipcMain.handle("upgrade:buildPlan", buildUpgradePlan);
  ipcMain.handle("upgrade:runCheck", runUpgradeCheck);
  ipcMain.handle("upgrade:launchPreflight", runLaunchPreflight);
  ipcMain.handle("upgrade:validateDataContract", validateDataContract);
  ipcMain.handle("tasks:enqueueFullMediaPrep", enqueueFullMediaPrep);
  ipcMain.handle("tasks:getSummary", getTaskSummary);
  ipcMain.handle("tasks:runWorkerOnce", runTaskWorkerOnce);
  ipcMain.handle("worker:start", () => workerCommand("start"));
  ipcMain.handle("worker:stop", () => workerCommand("stop"));
  ipcMain.handle("worker:restart", () => workerCommand("restart"));
  ipcMain.handle("worker:status", () => workerCommand("status"));
  ipcMain.handle("worker:once", () => workerCommand("once"));
  ipcMain.handle("worker:pause", () => workerCommand("pause"));
  ipcMain.handle("worker:resume", () => workerCommand("resume"));
  ipcMain.handle("localApi:start", startLocalApi);
  ipcMain.handle("localApi:stop", stopLocalApi);
  ipcMain.handle("localApi:status", localApiStatus);
  ipcMain.handle("localApi:call", callLocalApi);
  ipcMain.handle("observability:getRuntimeMetrics", getRuntimeMetrics);
  ipcMain.handle("observability:getClientMetrics", getClientMetrics);
  ipcMain.handle("observability:getAuditLog", getAuditLog);
  ipcMain.handle("observability:buildReport", () => runPython(["scripts/build_observability_report.py"]));
  ipcMain.handle("security:getStatus", async () => ({ ok: true, activeProjectRoot, security: await readAnalyticsJson("security_report.json", {}) }));
  ipcMain.handle("security:runCheck", () => runPython(["scripts/run_security_check.py"]));
  ipcMain.handle("state:reconcile", (_event, options = {}) => {
    if (options.apply && !options.confirmed) {
      return securityFail("This action requires confirmation.", { action: "reconcile_apply" });
    }
    return runPython(["scripts/reconcile_runtime_state.py", options.apply ? "--apply" : "--dry-run", ...(options.limit ? ["--limit", String(options.limit)] : [])]);
  });
  ipcMain.handle("state:getClientIntegrity", async () => ({ ok: true, activeProjectRoot, integrity: await readAnalyticsJson("client_integrity.json", {}) }));
  ipcMain.handle("state:getReconciliationReport", async () => ({ ok: true, activeProjectRoot, report: await readAnalyticsJson("state_reconciliation_report.json", {}) }));
  ipcMain.handle("project:backup", (_event, options) => lifecycleScript("scripts/backup_project.py", options));
  ipcMain.handle("project:validate", () => lifecycleScript("scripts/validate_project.py"));
  ipcMain.handle("project:sizeReport", () => lifecycleScript("scripts/project_size_report.py"));
  ipcMain.handle("project:resetDemo", (_event, options) => lifecycleScript("scripts/reset_demo_workspace.py", options));
  ipcMain.handle("project:archiveArtifacts", (_event, options) => lifecycleScript("scripts/archive_project_artifacts.py", options));
  ipcMain.handle("qa:runFull", () => runPython(["scripts/run_full_qa.py"]));
  ipcMain.handle("app:info", appInfo);
  ipcMain.handle("project:useCurrentRepo", useCurrentRepoProject);
  ipcMain.handle("app:about", showAboutPanel);
  ipcMain.handle("setup:firstRun", () => runFirstRunSetup(true));
  ipcMain.handle("folder:openContentInbox", openContentInbox);
  ipcMain.handle("folder:openSocialExports", openSocialExportsFolder);
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
  if (settings.profiles.default.worker?.auto_start) {
    workerCommand("start").catch(() => {});
  }
  if (settings.profiles.default.local_api?.auto_start) {
    startLocalApi().catch(() => {});
  }
});

app.on("window-all-closed", () => {
  if (process.platform !== "darwin") {
    app.quit();
  }
});

app.on("before-quit", () => {
  if (localApiProcess && localApiProcess.exitCode === null) {
    localApiProcess.kill("SIGTERM");
  }
});

app.on("before-quit", () => {
  if (activityPoll) clearInterval(activityPoll);
  if (watcherProcess) watcherProcess.kill();
  if (staticServer) staticServer.close();
});
