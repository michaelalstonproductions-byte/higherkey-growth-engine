const { contextBridge, ipcRenderer, webUtils } = require("electron");

contextBridge.exposeInMainWorld("higherkey", {
  getSettings: () => ipcRenderer.invoke("settings:get"),
  setSettings: (settings) => ipcRenderer.invoke("settings:set", settings),
  pickDirectory: (kind) => ipcRenderer.invoke("dialog:pickDirectory", kind),
  useCurrentRepoProject: () => ipcRenderer.invoke("project:useCurrentRepo"),
  startWatcher: () => ipcRenderer.invoke("pipeline:startWatcher"),
  stopWatcher: () => ipcRenderer.invoke("pipeline:stopWatcher"),
  runPipelineOnce: () => ipcRenderer.invoke("pipeline:runOnce"),
  runFullMediaPrep: () => ipcRenderer.invoke("pipeline:runFullMediaPrep"),
  runOrchestratorOnce: () => ipcRenderer.invoke("orchestrator:runOnce"),
  buildMediaCache: () => ipcRenderer.invoke("media:buildCache"),
  archiveTestMedia: () => ipcRenderer.invoke("media:archiveTestMedia"),
  exportSocialPacks: (options) => ipcRenderer.invoke("social:exportPacks", options),
  runDiagnostics: () => ipcRenderer.invoke("diagnostics:run"),
  runFullQa: () => ipcRenderer.invoke("qa:runFull"),
  getAppInfo: () => ipcRenderer.invoke("app:info"),
  showAbout: () => ipcRenderer.invoke("app:about"),
  runFirstRunSetup: () => ipcRenderer.invoke("setup:firstRun"),
  openContentInbox: () => ipcRenderer.invoke("folder:openContentInbox"),
  pipelineStatus: () => ipcRenderer.invoke("pipeline:status"),
  importFootage: () => ipcRenderer.invoke("files:importFootage"),
  importAndProcessFootage: () => ipcRenderer.invoke("files:importAndProcessFootage"),
  verifyImportBridge: () => ipcRenderer.invoke("files:verifyImportBridge"),
  verifyImportAndProcessBridge: () => ipcRenderer.invoke("files:verifyImportAndProcessBridge"),
  getDroppedFilePaths: (files) => Array.from(files || []).map((file) => ({
    name: file.name || "",
    path: webUtils.getPathForFile(file) || file.path || "",
    size: file.size || 0,
    type: file.type || ""
  })),
  ingestDroppedFiles: (paths) => ipcRenderer.invoke("files:ingestDropped", paths),
  testNotification: () => ipcRenderer.invoke("notify:test"),
  onSettingsChanged: (callback) => ipcRenderer.on("higherkey:settings", (_event, settings) => callback(settings)),
  onProjectChanged: (callback) => ipcRenderer.on("higherkey:project", (_event, info) => callback(info))
});
