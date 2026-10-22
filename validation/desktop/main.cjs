const { app, BrowserWindow, dialog, ipcMain, Notification, powerMonitor, session, shell, systemPreferences } = require('electron');
const { spawn } = require('node:child_process');
const fs = require('node:fs');
const path = require('node:path');
const { once } = require('node:events');

const root = process.env.BOSS_VALIDATION_ROOT;
if (!root || !path.isAbsolute(root)) throw new Error('缺少验证工程绝对路径');
const work = path.join(root, '.work', 'desktop');
fs.mkdirSync(work, { recursive: true });
app.setPath('userData', path.join(work, 'profile'));
app.setPath('temp', path.join(root, '.work', 'tmp'));
app.setPath('logs', path.join(work, 'logs'));
app.setPath('crashDumps', path.join(work, 'crash-dumps'));
const lifecycle = path.join(root, '..', 'evidence', 'T02', 'desktop-lifecycle.jsonl');
function record(event, details = {}) {
  fs.appendFileSync(lifecycle, JSON.stringify({ at: new Date().toISOString(), pid: process.pid, event, ...details }) + '\n');
}

let child;
let quitting = false;
let window;
let microphoneAuthorized = false;
const origin = 'http://127.0.0.1:8872';
if (!app.requestSingleInstanceLock()) {
  record('duplicate_instance_rejected');
  app.quit();
} else {
  app.on('second-instance', () => { record('existing_instance_activated'); window?.focus(); });
  app.on('window-all-closed', () => app.quit());
  app.on('before-quit', async (event) => {
    if (quitting || !child || child.exitCode !== null) return;
    event.preventDefault();
    quitting = true;
    record('stop_service_requested', { service_pid: child.pid });
    child.kill('SIGTERM');
    await once(child, 'exit');
    record('service_stopped');
    app.quit();
  });
  app.on('quit', () => record('quit'));

  async function authorize(event, token) {
    if (!window || event.sender !== window.webContents || event.senderFrame !== window.webContents.mainFrame || new URL(event.senderFrame.url).origin !== origin) throw new Error('IPC 发送方无权访问');
    if (typeof token !== 'string' || token.length > 200) throw new Error('IPC 身份凭据无效');
    const response = await fetch(origin + '/api/boss/identity', { headers: { Authorization: 'Bearer ' + token } });
    if (!response.ok) throw new Error('IPC 未认证');
    const identity = await response.json();
    if (identity.role !== 'BOSS') throw new Error('IPC 需要老板身份');
  }

  ipcMain.handle('boss-desktop:capability', async (event, request) => {
    if (!request || typeof request !== 'object' || Object.keys(request).some(key => !['action', 'token', 'url'].includes(key))) throw new Error('IPC 参数无效');
    const action = request.action;
    const allowed = ['status', 'microphone_status', 'request_microphone', 'select_file', 'open_source', 'notify', 'quit'];
    if (!allowed.includes(action)) { record('ipc_denied', { action }); throw new Error('IPC 能力未授权'); }
    if (!window || event.sender !== window.webContents || event.senderFrame !== window.webContents.mainFrame || new URL(event.senderFrame.url).origin !== origin) throw new Error('IPC 发送方无权访问');
    if (action === 'status') return { versions: process.versions, service_pid: child.pid, platform: process.platform, architecture: process.arch, microphone: systemPreferences.getMediaAccessStatus('microphone'), notifications_supported: Notification.isSupported() };
    await authorize(event, request.token);
    record('ipc_authorized', { action });
    if (action === 'microphone_status') return systemPreferences.getMediaAccessStatus('microphone');
    if (action === 'request_microphone') {
      microphoneAuthorized = await systemPreferences.askForMediaAccess('microphone');
      return microphoneAuthorized;
    }
    if (action === 'select_file') {
      const selected = await dialog.showOpenDialog(window, { properties: ['openFile'], defaultPath: path.join(root, '.work', 'materials'), filters: [{ name: '获准业务资料', extensions: ['md', 'txt', 'pdf', 'csv', 'json'] }] });
      if (selected.canceled) return { canceled: true };
      const file = fs.realpathSync(selected.filePaths[0]);
      const relative = path.relative(path.join(root, '.work', 'materials'), file);
      if (relative.startsWith('..') || path.isAbsolute(relative)) throw new Error('文件超出获准材料范围');
      return { canceled: false, name: path.basename(file) };
    }
    if (action === 'open_source') {
      const address = new URL(request.url);
      if (address.protocol !== 'https:' || !['api-docs.deepseek.com', 'github.com'].includes(address.hostname) || address.username || address.password || address.hostname === 'github.com' && !address.pathname.startsWith('/HKUDS/nanobot')) throw new Error('外部来源不在允许范围');
      await shell.openExternal(address.href);
      return { opened: true };
    }
    if (action === 'notify') { new Notification({ title: 'Boss-Agent', body: '有待处理事项，请在应用内查看。' }).show(); return { requested: true }; }
    if (action === 'quit') { setImmediate(() => app.quit()); return { requested: true }; }
    throw new Error('IPC 动作缺少处理');
  });

  app.whenReady().then(async () => {
    const log = fs.openSync(path.join(root, '..', 'evidence', 'T02', 'desktop-service.log'), 'a');
    child = spawn(path.join(root, '.venv', 'bin', 'python'), [path.join(root, 'application.py')], { cwd: root, env: { ...process.env, TMPDIR: path.join(root, '.work', 'tmp') }, stdio: ['ignore', log, log] });
    child.on('error', error => { throw error; });
    const deadline = Date.now() + 20000;
    let ready = false;
    while (!ready) {
      if (child.exitCode !== null) throw new Error('业务服务启动失败，退出码 ' + child.exitCode);
      if (Date.now() > deadline) throw new Error('业务服务启动超时');
      const instance = path.join(root, '.work', 'application', 'instance.json');
      if (fs.existsSync(instance)) ready = JSON.parse(fs.readFileSync(instance)).pid === child.pid;
      if (!ready) await new Promise(resolve => setTimeout(resolve, 100));
    }
    record('service_started', { service_pid: child.pid });
    window = new BrowserWindow({ width: 1280, height: 800, webPreferences: { nodeIntegration: false, contextIsolation: true, sandbox: true, webSecurity: true, preload: path.join(__dirname, 'preload.cjs') } });
    window.webContents.setWindowOpenHandler(() => ({ action: 'deny' }));
    window.webContents.on('will-navigate', (event, address) => { if (new URL(address).origin !== origin) event.preventDefault(); });
    window.webContents.on('will-attach-webview', event => event.preventDefault());
    session.defaultSession.setPermissionCheckHandler((contents, permission, requestingOrigin) => microphoneAuthorized && contents === window.webContents && permission === 'media' && new URL(requestingOrigin).origin === origin);
    session.defaultSession.setPermissionRequestHandler((contents, permission, callback, details) => {
      const allowed = microphoneAuthorized && contents === window.webContents && permission === 'media' && details.mediaTypes.length > 0 && details.mediaTypes.every(type => type === 'audio');
      record('renderer_permission_decision', { permission, allowed });
      callback(allowed);
    });
    session.defaultSession.webRequest.onHeadersReceived((details, callback) => callback({ responseHeaders: { ...details.responseHeaders, 'Content-Security-Policy': ["default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline'; img-src 'self' data: blob:; font-src 'self' data:; connect-src 'self' ws://127.0.0.1:8872; media-src 'self' blob:; object-src 'none'; frame-src 'none'; base-uri 'self'"] } }));
    for (const event of ['suspend', 'resume', 'lock-screen', 'unlock-screen']) powerMonitor.on(event, () => record(event));
    await window.loadURL(origin);
    record('window_loaded', { versions: process.versions, architecture: process.arch });
  });
}
