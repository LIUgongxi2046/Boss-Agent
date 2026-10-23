const { app, BrowserWindow, nativeImage } = require('electron');
const path = require('node:path');
const fs = require('node:fs');
const branding = require('../../validation/desktop/branding.cjs');
const revision = process.env.BOSS_T27_REVIEW_REVISION || '';
if (!['', 'flight'].includes(revision)) throw new Error('查看窗口版本无效');
const directory = path.resolve(__dirname, '../../validation/.work', revision === 'flight' ? 't27-review-flight/host' : 't27-review/host');
for (const name of ['profile', 'tmp', 'logs', 'crash']) fs.mkdirSync(path.join(directory, name), { recursive: true, mode: 0o700 });
app.setPath('userData', path.join(directory, 'profile'));
app.setPath('temp', path.join(directory, 'tmp'));
app.setPath('logs', path.join(directory, 'logs'));
app.setPath('crashDumps', path.join(directory, 'crash'));
const origin = new URL(process.env.BOSS_T27_REVIEW_ORIGIN);
if (origin.protocol !== 'http:' || origin.hostname !== '127.0.0.1' || !origin.port || origin.port === '8872' || origin.username || origin.password) throw new Error('查看窗口需要独立本机服务');
app.whenReady().then(async () => {
  branding.configureApp(app, nativeImage);
  const window = new BrowserWindow({ ...branding.windowOptions(), width: 1280, height: 800,
    webPreferences: { nodeIntegration: false, contextIsolation: true, sandbox: true } });
  branding.attachWindow(window);
  window.webContents.setWindowOpenHandler(() => ({ action: 'deny' }));
  window.webContents.on('will-navigate', (event, target) => { if (new URL(target).origin !== origin.origin) event.preventDefault(); });
  await window.loadURL(origin.origin);
});
app.on('window-all-closed', () => app.quit());
