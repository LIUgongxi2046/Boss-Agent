const { app, BrowserWindow } = require('electron');
const path = require('node:path');
const fs = require('node:fs');
const branding = require('../../validation/desktop/branding.cjs');

const directory = path.resolve(__dirname, '../../validation/.work/t27-native-zoom/host');
for (const name of ['profile', 'tmp', 'logs', 'crash']) fs.mkdirSync(path.join(directory, name), { recursive: true, mode: 0o700 });
app.setPath('userData', path.join(directory, 'profile'));
app.setPath('temp', path.join(directory, 'tmp'));
app.setPath('logs', path.join(directory, 'logs'));
app.setPath('crashDumps', path.join(directory, 'crash'));
app.setName(branding.name);
const origin = new URL(process.env.BOSS_T27_ZOOM_ORIGIN);
if (origin.protocol !== 'http:' || origin.hostname !== '127.0.0.1' || !origin.port || origin.port === '8872' || origin.username || origin.password) throw new Error('原生缩放检查需要独立服务');
app.whenReady().then(async () => {
  if (process.platform === 'darwin') app.dock.hide();
  const window = new BrowserWindow({ ...branding.windowOptions(), width: 1280, height: 800, show: false,
    paintWhenInitiallyHidden: true,
    webPreferences: { nodeIntegration: false, contextIsolation: true, sandbox: true, backgroundThrottling: false } });
  branding.attachWindow(window);
  window.webContents.setWindowOpenHandler(() => ({ action: 'deny' }));
  window.webContents.on('will-navigate', (event, target) => { if (new URL(target).origin !== origin.origin) event.preventDefault(); });
  await window.loadURL(origin.origin);
});
app.on('window-all-closed', () => app.quit());
