const { contextBridge, ipcRenderer } = require("electron");

contextBridge.exposeInMainWorld("higherkey", {
  getSettings: () => ipcRenderer.invoke("settings:get"),
  setSettings: (settings) => ipcRenderer.invoke("settings:set", settings),
  pickDirectory: (kind) => ipcRenderer.invoke("dialog:pickDirectory", kind),
  startWatcher: () => ipcRenderer.invoke("pipeline:startWatcher"),
  stopWatcher: () => ipcRenderer.invoke("pipeline:stopWatcher"),
  runPipelineOnce: () => ipcRenderer.invoke("pipeline:runOnce"),
  runOrchestratorOnce: () => ipcRenderer.invoke("orchestrator:runOnce"),
  buildMediaCache: () => ipcRenderer.invoke("media:buildCache"),
  pipelineStatus: () => ipcRenderer.invoke("pipeline:status"),
  ingestDroppedFiles: (paths) => ipcRenderer.invoke("files:ingestDropped", paths),
  testNotification: () => ipcRenderer.invoke("notify:test"),
  onSettingsChanged: (callback) => ipcRenderer.on("higherkey:settings", (_event, settings) => callback(settings))
});
