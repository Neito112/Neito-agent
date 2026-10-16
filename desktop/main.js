const { app, BrowserWindow, ipcMain, screen } = require("electron");
const path = require("path");

let mainWindow = null;

function createOverlayWindow() {
  const primaryDisplay = screen.getPrimaryDisplay();
  const { width, height } = primaryDisplay.workAreaSize;

  mainWindow = new BrowserWindow({
    width: width,
    height: height,
    x: 0,
    y: 0,
    transparent: true,
    frame: false,
    alwaysOnTop: true,
    skipTaskbar: false,
    resizable: false,
    hasShadow: false,
    webPreferences: {
      preload: path.join(__dirname, "preload.js"),
      contextIsolation: true,
      nodeIntegration: false,
    },
  });

  mainWindow.setAlwaysOnTop(true, "screen-saver");
  mainWindow.setVisibleOnAllWorkspaces(true, { visibleOnFullScreen: true });

  // By default, let clicks pass through transparent areas to the game/app underneath
  mainWindow.setIgnoreMouseEvents(true, { forward: true });

  const backendUrl = process.env.NEITO_URL || "http://127.0.0.1:8765";
  mainWindow.loadURL(backendUrl).catch(() => {
    mainWindow.loadFile(path.join(__dirname, "src", "index.html"));
  });

  ipcMain.on("neito:set-ignore-mouse", (_event, ignore) => {
    if (mainWindow && !mainWindow.isDestroyed()) {
      mainWindow.setIgnoreMouseEvents(Boolean(ignore), { forward: true });
    }
  });

  ipcMain.on("neito:quit", () => {
    app.quit();
  });
}

app.whenReady().then(() => {
  createOverlayWindow();
});

app.on("window-all-closed", () => {
  app.quit();
});
