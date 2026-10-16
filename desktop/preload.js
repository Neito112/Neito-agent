const { contextBridge, ipcRenderer } = require("electron");

contextBridge.exposeInMainWorld("neitoDesktop", {
  isElectron: true,
  setIgnoreMouseEvents: (ignore) => ipcRenderer.send("neito:set-ignore-mouse", ignore),
  quitApp: () => ipcRenderer.send("neito:quit"),
});
