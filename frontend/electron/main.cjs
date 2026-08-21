const { app, BrowserWindow } = require("electron");
const path = require("node:path");

const DEV_SERVER_URL = "http://127.0.0.1:5173";

function createWindow() {
  const window = new BrowserWindow({
    title: "SenaBot",
    width: 1080,
    height: 760,
    minWidth: 420,
    minHeight: 560,
    backgroundColor: "#ffffff",
    autoHideMenuBar: true,
    show: false,
    webPreferences: {
      contextIsolation: true,
      nodeIntegration: false,
      sandbox: true,
    },
  });

  window.once("ready-to-show", () => window.show());

  if (app.isPackaged) {
    void window.loadFile(path.join(__dirname, "..", "dist", "index.html"));
  } else {
    void window.loadURL(DEV_SERVER_URL);
  }
}

const hasSingleInstanceLock = app.requestSingleInstanceLock();

if (!hasSingleInstanceLock) {
  app.quit();
} else {
  app.on("second-instance", () => {
    const window = BrowserWindow.getAllWindows()[0];
    if (!window) return;
    if (window.isMinimized()) window.restore();
    window.focus();
  });

  app.whenReady().then(() => {
    createWindow();
    app.on("activate", () => {
      if (BrowserWindow.getAllWindows().length === 0) createWindow();
    });
  });

  app.on("window-all-closed", () => {
    if (process.platform !== "darwin") app.quit();
  });
}
