const { app, BrowserWindow, nativeImage } = require('electron');
const path = require('node:path');
const fs = require('node:fs');
const branding = require('../../validation/desktop/branding.cjs');
const profile = process.env.BOSS_T27_PROFILE || 't27-native';
if (!['t27-native', 't27-native-check'].includes(profile)) throw new Error('桌面配置目录无效');
const directory = path.resolve(__dirname, '../../validation/.work', profile);
for (const name of ['profile', 'tmp', 'logs', 'crash']) fs.mkdirSync(path.join(directory, name), { recursive: true });
app.setPath('userData', path.join(directory, 'profile'));
app.setPath('temp', path.join(directory, 'tmp'));
app.setPath('logs', path.join(directory, 'logs'));
app.setPath('crashDumps', path.join(directory, 'crash'));
app.whenReady().then(async () => {
  branding.configureApp(app, nativeImage);
  const window = new BrowserWindow({ ...branding.windowOptions(), width: 1280, height: 800,
    webPreferences: { nodeIntegration: false, contextIsolation: true, sandbox: true } });
  branding.attachWindow(window);
  const origin = process.env.BOSS_T27_ORIGIN;
  if (origin) {
    const address = new URL(origin);
    if (address.protocol !== 'http:' || address.hostname !== '127.0.0.1' || !address.port || address.port === '8872' || address.username || address.password) throw new Error('需要独立本机认证服务地址');
    window.webContents.setWindowOpenHandler(() => ({ action: 'deny' }));
    window.webContents.on('will-navigate', (event, target) => {
      if (new URL(target).origin !== address.origin) event.preventDefault();
    });
    await window.loadURL(address.origin);
  } else {
    await window.loadFile(path.join(__dirname, 'harness/dist/index.html'));
  }
});
app.on('window-all-closed', () => app.quit());
