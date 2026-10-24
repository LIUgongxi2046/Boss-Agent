const { contextBridge, ipcRenderer } = require('electron');

contextBridge.exposeInMainWorld('bossDesktop', Object.freeze({
  invoke: request => ipcRenderer.invoke('boss-desktop:capability', request),
  confirmClose: () => ipcRenderer.invoke('boss-desktop:confirm-close'),
  onCloseRequested: listener => {
    if (typeof listener !== 'function') throw new Error('关闭监听器无效');
    const receive = () => listener();
    ipcRenderer.on('boss-desktop:close-requested', receive);
    ipcRenderer.send('boss-desktop:close-handler', true);
    return () => {
      ipcRenderer.removeListener('boss-desktop:close-requested', receive);
      if (ipcRenderer.listenerCount('boss-desktop:close-requested') === 0) ipcRenderer.send('boss-desktop:close-handler', false);
    };
  },
  onNotificationOpen: listener => {
    if (typeof listener !== 'function') throw new Error('通知监听器无效');
    const receive = (_event, target) => listener(target);
    ipcRenderer.on('boss-desktop:notification-open', receive);
    return () => ipcRenderer.removeListener('boss-desktop:notification-open', receive);
  },
}));
