const { contextBridge, ipcRenderer } = require('electron');

contextBridge.exposeInMainWorld('bossDesktop', Object.freeze({
  invoke: request => ipcRenderer.invoke('boss-desktop:capability', request),
}));
