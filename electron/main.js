const { app, BrowserWindow, Menu, dialog, ipcMain, Notification, shell } = require("electron");
const http = require("node:http");
const fs = require("node:fs");
const fsp = require("node:fs/promises");
const path = require("node:path");
const { spawn } = require("node:child_process");

const PROJECT_ROOT = path.resolve(__dirname, "..");
const SETTINGS_NAME = "higherkey-settings.json";
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
let staticServer = null;
let watcherProcess = null;
let activityPoll = null;
let lastActivityCount = 0;

function settingsPath() {
  return path.join(app.getPath("userData"), SETTINGS_NAME);
}

function defaultSettings() {
  return {
    version: 1,
    activeProject: PROJECT_ROOT,
    recentProjects: [PROJECT_ROOT],
    profiles: {
      default: {
        name: "Default",
        projectPath: PROJECT_ROOT,
        contentInbox: path.join(PROJECT_ROOT, "content_inbox"),
        exportDirectory: path.join(PROJECT_ROOT, "out", "approved_posts"),
        analyticsDirectory: path.join(PROJECT_ROOT, "analytics"),
        startWatcherOnLaunch: false
      }
    }
  };
}

async function readSettings() {
  try {
    return JSON.parse(await fsp.readFile(settingsPath(), "utf8"));
  } catch {
    return defaultSettings();
  }
}

async function writeSettings(settings) {
  await fsp.mkdir(path.dirname(settingsPath()), { recursive: true });
  await fsp.writeFile(settingsPath(), JSON.stringify(settings, null, 2) + "\n");
  return settings;
}

function safePathFromUrl(urlPath) {
  const decoded = decodeURIComponent(urlPath.split("?")[0]);
  const relative = decoded === "/" ? "dashboard/review.html" : decoded.replace(/^\/+/, "");
  const target = path.resolve(PROJECT_ROOT, relative);
  if (!target.startsWith(PROJECT_ROOT)) {
    return null;
  }
  return target;
}

function startStaticServer() {
  return new Promise((resolve, reject) => {
    staticServer = http.createServer((request, response) => {
      const target = safePathFromUrl(request.url || "/");
      if (!target) {
        response.writeHead(403);
        response.end("Forbidden");
        return;
      }
      fs.readFile(target, (error, data) => {
        if (error) {
          response.writeHead(404);
          response.end("Not found");
          return;
        }
        response.writeHead(200, { "Content-Type": MIME.get(path.extname(target)) || "application/octet-stream" });
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
        { type: "separator" },
        { role: "quit" }
      ]
    },
    {
      label: "Pipeline",
      submenu: [
        { label: "Start Watcher", click: () => startWatcher() },
        { label: "Stop Watcher", click: () => stopWatcher() },
        { label: "Run One Daemon Tick", click: () => runPython(["scripts/watch_daemon.py", "--once"]) }
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
        { label: "Open Project Folder", click: () => shell.openPath(PROJECT_ROOT) }
      ]
    },
    {
      label: "Help",
      submenu: [
        { label: "About HigherKey", click: () => dialog.showMessageBox({ message: "HigherKey Growth Engine", detail: "Local-first Operator shell. No cloud or social APIs." }) }
      ]
    }
  ];
  Menu.setApplicationMenu(Menu.buildFromTemplate(template));
}

async function createWindow(url) {
  mainWindow = new BrowserWindow({
    width: 1440,
    height: 1000,
    minWidth: 1000,
    minHeight: 720,
    title: "HigherKey Operator",
    webPreferences: {
      preload: path.join(__dirname, "preload.js"),
      contextIsolation: true,
      nodeIntegration: false,
      sandbox: false
    }
  });
  await mainWindow.loadURL(url);
  if (process.env.HK_ELECTRON_SMOKE === "1") {
    notify("HigherKey verification", "Electron notification path is wired.");
    setTimeout(() => app.quit(), 1200);
  }
}

function runPython(args) {
  return new Promise((resolve) => {
    const child = spawn("python3", args, { cwd: PROJECT_ROOT });
    let stdout = "";
    let stderr = "";
    child.stdout.on("data", (data) => { stdout += data.toString(); });
    child.stderr.on("data", (data) => { stderr += data.toString(); });
    child.on("close", (code) => resolve({ code, stdout, stderr }));
  });
}

async function startWatcher() {
  if (watcherProcess) {
    return { running: true, pid: watcherProcess.pid };
  }
  watcherProcess = spawn("python3", ["scripts/watch_daemon.py", "--interval", "5"], { cwd: PROJECT_ROOT });
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
  const activityPath = path.join(PROJECT_ROOT, "analytics", "activity_feed.json");
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
    settings.recentProjects = [selected, ...(settings.recentProjects || []).filter((item) => item !== selected)].slice(0, 10);
  } else {
    profile[kind] = selected;
  }
  await writeSettings(settings);
  mainWindow?.webContents.send("higherkey:settings", settings);
  return selected;
}

async function ingestDroppedFiles(filePaths) {
  const settings = await readSettings();
  const inbox = settings.profiles.default.contentInbox || path.join(PROJECT_ROOT, "content_inbox");
  await fsp.mkdir(inbox, { recursive: true });
  const copied = [];
  for (const filePath of filePaths) {
    const target = path.join(inbox, path.basename(filePath));
    await fsp.copyFile(filePath, target);
    copied.push(target);
  }
  return { copied, inbox };
}

function registerIpc() {
  ipcMain.handle("settings:get", readSettings);
  ipcMain.handle("settings:set", async (_event, settings) => writeSettings(settings));
  ipcMain.handle("dialog:pickDirectory", (_event, kind) => pickDirectory(kind));
  ipcMain.handle("pipeline:startWatcher", startWatcher);
  ipcMain.handle("pipeline:stopWatcher", stopWatcher);
  ipcMain.handle("pipeline:status", () => ({ watcherRunning: Boolean(watcherProcess), watcherPid: watcherProcess?.pid || null }));
  ipcMain.handle("pipeline:runOnce", () => runPython(["scripts/watch_daemon.py", "--once"]));
  ipcMain.handle("files:ingestDropped", (_event, filePaths) => ingestDroppedFiles(filePaths));
  ipcMain.handle("notify:test", () => {
    notify("HigherKey notification test", "Local notifications are wired.");
    return { sent: Notification.isSupported() };
  });
}

app.whenReady().then(async () => {
  await writeSettings(await readSettings());
  registerIpc();
  createMenu();
  const url = await startStaticServer();
  await createWindow(url);
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
