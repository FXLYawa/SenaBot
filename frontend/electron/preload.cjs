const { contextBridge, ipcRenderer } = require("electron");
contextBridge.exposeInMainWorld("senaDesktop", {
  status: () => ipcRenderer.invoke("backend:status"),
  saveKeys: (keys) => ipcRenderer.invoke("backend:keys", keys),
  restart: () => ipcRenderer.invoke("backend:restart"),
});
