const { app, BrowserWindow, nativeImage } = require('electron');
const path = require('node:path');
const fs = require('node:fs');
const branding = require('../../validation/desktop/branding.cjs');
const directory = path.resolve(__dirname, '../../validation/.work/t27-native');
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
  await window.loadFile(path.join(__dirname, 'harness/dist/index.html'));
});
app.on('window-all-closed', () => app.quit());
