const { contextBridge, ipcRenderer } = require('electron');

contextBridge.exposeInMainWorld('bossDesktop', Object.freeze({
  invoke: request => ipcRenderer.invoke('boss-desktop:capability', request),
  onNotificationOpen: listener => {
    if (typeof listener !== 'function') throw new Error('通知监听器无效');
    const receive = (_event, target) => listener(target);
    ipcRenderer.on('boss-desktop:notification-open', receive);
    return () => ipcRenderer.removeListener('boss-desktop:notification-open', receive);
  },
}));
