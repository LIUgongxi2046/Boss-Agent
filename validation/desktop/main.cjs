const { app, BrowserWindow, dialog, ipcMain, nativeImage, Notification, powerMonitor, session, shell, systemPreferences } = require('electron');
const branding = require('./branding.cjs');
const { spawn } = require('node:child_process');
const fs = require('node:fs');
const path = require('node:path');
const { once } = require('node:events');

const root = process.env.BOSS_VALIDATION_ROOT;
if (!root || !path.isAbsolute(root)) throw new Error('缺少验证工程绝对路径');
fs.mkdirSync(path.join(root, '.work'), { recursive: true });
const applicationParent = fs.realpathSync(path.join(root, '.work'));
const configuredApplicationWork = process.env.BOSS_APPLICATION_WORK_DIR;
const applicationWork = configuredApplicationWork === undefined
  ? path.join(applicationParent, 'application') : configuredApplicationWork;
if (!path.isAbsolute(applicationWork) || path.dirname(path.resolve(applicationWork)) !== applicationParent)
  throw new Error('应用数据目录必须位于本工程.work的直接子目录');
if (fs.existsSync(applicationWork) && path.dirname(fs.realpathSync(applicationWork)) !== applicationParent)
  throw new Error('应用数据目录不能引用工程范围以外的位置');
const work = path.join(applicationParent, configuredApplicationWork === undefined
  ? 'desktop' : 'desktop-' + path.basename(applicationWork));
if (fs.existsSync(work) && path.dirname(fs.realpathSync(work)) !== applicationParent)
  throw new Error('桌面配置目录不能引用工程范围以外的位置');
fs.mkdirSync(path.join(work, 'tmp'), { recursive: true });
fs.chmodSync(work, 0o700);
const ports = process.env.BOSS_APPLICATION_PORTS === undefined
  ? { business: 8871, webui: 8872, gateway: 18791 } : JSON.parse(process.env.BOSS_APPLICATION_PORTS);
if (!ports || Array.isArray(ports) || Object.keys(ports).sort().join(',') !== 'business,gateway,webui' ||
    Object.values(ports).some(value => !Number.isInteger(value) || value < 1024 || value > 65535) ||
    new Set(Object.values(ports)).size !== 3) throw new Error('应用端口配置无效');
app.setPath('userData', path.join(work, 'profile'));
app.setPath('temp', path.join(work, 'tmp'));
app.setPath('logs', path.join(work, 'logs'));
app.setPath('crashDumps', path.join(work, 'crash-dumps'));
const productMode = process.env.BOSS_PRODUCT_UI === '1';
const demoAccountInjection = productMode && process.env.BOSS_EXECUTION_SCOPE === 'BOSS-PRIORITY-ITERATION' && process.env.BOSS_DEMO_ACCOUNT_INJECTION === '1';
const diagnostics = productMode ? path.join(work, 'diagnostics') : path.join(root, '..', 'evidence', 'T02');
fs.mkdirSync(diagnostics, { recursive: true, mode: productMode ? 0o700 : 0o755 });
if (productMode) fs.chmodSync(diagnostics, 0o700);
const lifecycle = path.join(diagnostics, 'desktop-lifecycle.jsonl');
function record(event, details = {}) {
  fs.appendFileSync(lifecycle, JSON.stringify({ at: new Date().toISOString(), pid: process.pid, event, ...details }) + '\n');
}

let child;
let quitting = false;
let window;
let microphoneAuthorized = false;
let closeHandlerReady = false;
let closeRequested = false;
let closeConfirmed = false;
let serviceStartupElapsedMs = null;
const eventNotifications = new Map();
const origin = 'http://127.0.0.1:' + ports.webui;
const serviceStartupTimeoutMs = 90000;
const initialPage = process.env.BOSS_INITIAL_PAGE;
if (initialPage !== undefined && !['F01', 'F02', 'N02'].includes(initialPage)) throw new Error('初始页面配置无效');
if (!app.requestSingleInstanceLock()) {
  record('duplicate_instance_rejected');
  app.quit();
} else {
  app.on('second-instance', () => { record('existing_instance_activated'); window?.focus(); });
  app.on('window-all-closed', () => app.quit());
  app.on('before-quit', async (event) => {
    if (quitting || !child || child.exitCode !== null) return;
    event.preventDefault();
    if (window && !window.isDestroyed()) { window.close(); return; }
    quitting = true;
    record('stop_service_requested', { service_pid: child.pid });
    child.kill('SIGTERM');
    await once(child, 'exit');
    record('service_stopped');
    app.quit();
  });
  app.on('quit', () => record('quit'));

  function requireWindowFrame(event) {
    if (!window || event.sender !== window.webContents || event.senderFrame !== window.webContents.mainFrame || new URL(event.senderFrame.url).origin !== new URL(window.webContents.getURL()).origin) throw new Error('IPC 发送方无权访问');
  }
  function requireMainFrame(event) {
    requireWindowFrame(event);
    if (new URL(event.senderFrame.url).origin !== origin) throw new Error('IPC 页面来源无权访问业务能力');
  }
  ipcMain.on('boss-desktop:close-handler', (event, enabled) => {
    requireWindowFrame(event);
    if (typeof enabled !== 'boolean') throw new Error('关闭处理器状态无效');
    closeHandlerReady = enabled;
    if (!enabled) closeRequested = false;
  });
  ipcMain.handle('boss-desktop:confirm-close', event => {
    requireWindowFrame(event);
    if (!closeHandlerReady || !closeRequested || closeConfirmed) throw new Error('当前没有待确认的窗口关闭请求');
    closeConfirmed = true;
    window.close();
    return { closing: true };
  });

  async function authorize(event, token) {
    requireMainFrame(event);
    if (typeof token !== 'string' || token.length > 200) throw new Error('IPC 身份凭据无效');
    const response = await fetch(origin + '/api/boss/identity', { headers: { Authorization: 'Bearer ' + token } });
    if (!response.ok) throw new Error('IPC 未认证');
    const identity = await response.json();
    if (identity.role !== 'BOSS') throw new Error('IPC 需要老板身份');
  }

  ipcMain.handle('boss-desktop:capability', async (event, request) => {
    if (!request || typeof request !== 'object' || Object.keys(request).some(key => !['action', 'token', 'url', 'event_id', 'event_version', 'role'].includes(key))) throw new Error('IPC 参数无效');
    const action = request.action;
    const allowed = ['status', 'microphone_status', 'request_microphone', 'select_file', 'open_source', 'notify', 'notify_event', 'retry_notification', 'notification_status', 'quit', ...(demoAccountInjection ? ['test_account'] : [])];
    if (!allowed.includes(action)) { record('ipc_denied', { action }); throw new Error('IPC 能力未授权'); }
    if (!window || event.sender !== window.webContents || event.senderFrame !== window.webContents.mainFrame || new URL(event.senderFrame.url).origin !== origin) throw new Error('IPC 发送方无权访问');
    if (action === 'test_account') {
      if (Object.keys(request).sort().join(',') !== 'action,role' || !['BOSS', 'MAINTAINER'].includes(request.role)) throw new Error('测试账号入口身份无效');
      const accountPath = path.join(applicationWork, 'accounts', 'credentials.json');
      const stat = fs.lstatSync(accountPath);
      if (!stat.isFile() || stat.isSymbolicLink() || fs.realpathSync(accountPath) !== accountPath || (stat.mode & 0o077) !== 0 || stat.uid !== process.getuid() || stat.size > 65536) throw new Error('当前测试账号来源不符合本机读取条件');
      const accounts = JSON.parse(fs.readFileSync(accountPath, 'utf8'));
      if (!Array.isArray(accounts)) throw new Error('测试账号文件格式无效');
      const matches = accounts.filter(account => account.role === request.role);
      if (matches.length !== 1 || typeof matches[0].username !== 'string' || !matches[0].username || typeof matches[0].password !== 'string' || !matches[0].password) throw new Error('当前入口没有唯一有效测试账号');
      record('demo_account_filled', { role: request.role });
      return { role: request.role, username: matches[0].username, password: matches[0].password };
    }
    if ('role' in request) throw new Error('当前能力不接受入口身份字段');
    if (action === 'status') return { versions: process.versions, service_pid: child.pid, service_startup_ms: serviceStartupElapsedMs, platform: process.platform, architecture: process.arch, microphone: systemPreferences.getMediaAccessStatus('microphone'), notifications_supported: Notification.isSupported(), demo_account_injection_supported: demoAccountInjection, auto_start: ['darwin', 'win32'].includes(process.platform) ? app.getLoginItemSettings().openAtLogin : null, auto_update: false, background_mode: 'QUIT_WITH_LAST_WINDOW' };
    await authorize(event, request.token);
    record('ipc_authorized', { action });
    if (action === 'notify_event' || action === 'retry_notification' || action === 'notification_status') {
      if (Object.keys(request).sort().join(',') !== 'action,event_id,event_version,token' ||
          ['event_id', 'event_version'].some(key => typeof request[key] !== 'string' || !request[key] || request[key].length > 200)) throw new Error('通知对象参数无效');
      const query = new URLSearchParams({ event_id: request.event_id, event_version: request.event_version });
      const response = await fetch(origin + '/api/boss/ui/notification-target?' + query, { headers: { Authorization: 'Bearer ' + request.token } });
      if (!response.ok) throw new Error('当前通知对象不能采用，HTTP ' + response.status);
      const target = await response.json();
      if (target.event_id !== request.event_id || target.event_version !== request.event_version || typeof target.execution_namespace !== 'string' || !target.execution_namespace || target.page_id !== 'F02' || target.notification_saved !== true) throw new Error('通知目标与当前对象不符');
      const key = JSON.stringify([target.execution_namespace, target.event_id, target.event_version]);
      const supported = Notification.isSupported();
      if (action === 'notification_status') return { supported, permission: eventNotifications.get(key)?.permission ?? 'NOT_REPORTED_BY_SYSTEM', state: eventNotifications.get(key)?.state ?? 'NOT_REQUESTED', failure_reason: eventNotifications.get(key)?.failure_reason ?? null, external_delivery_verified: false };
      if (!supported) throw new Error('当前系统不支持桌面通知，请查看应用内通知记录');
      const previous = eventNotifications.get(key);
      if (action === 'retry_notification' && previous?.state !== 'FAILED') throw new Error('只有系统已经明确失败的通知可以由本人重新请求');
      if (previous && action !== 'retry_notification') return { supported, permission: previous.permission ?? 'NOT_REPORTED_BY_SYSTEM', state: previous.state, failure_reason: previous.failure_reason ?? null, original_request_reused: true, external_delivery_verified: false };
      const notification = new Notification({ title: 'Boss-Agent', body: '经营提醒 · 请打开应用核查当前事项。' });
      const observed = { notification, state: 'REQUESTED' };
      eventNotifications.set(key, observed);
      record('notification_requested', { event_id: target.event_id, event_version: target.event_version });
      notification.on('show', () => { observed.state = 'SHOWN'; record('notification_shown', { event_id: target.event_id, event_version: target.event_version }); });
      notification.on('failed', (_event, error) => { observed.state = 'FAILED'; observed.failure_reason = error; observed.permission = error === 'Notifications are not allowed for this application' ? 'DENIED_BY_SYSTEM' : 'NOT_REPORTED_BY_SYSTEM'; record('notification_failed', { event_id: target.event_id, event_version: target.event_version }); });
      notification.on('click', () => {
        observed.state = 'CLICKED';
        if (!window || window.isDestroyed()) return;
        window.show();
        window.focus();
        window.webContents.send('boss-desktop:notification-open', { execution_namespace: target.execution_namespace, event_id: target.event_id, event_version: target.event_version });
      });
      notification.show();
      return { supported, permission: 'NOT_REPORTED_BY_SYSTEM', state: observed.state, original_request_reused: false, external_delivery_verified: false };
    }
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
    branding.configureApp(app, nativeImage);
    const log = fs.openSync(path.join(diagnostics, 'desktop-service.log'), 'a', productMode ? 0o600 : 0o644);
    child = spawn(path.join(root, '.venv', 'bin', 'python'), [path.join(root, 'application.py')], { cwd: root, env: { ...process.env, TMPDIR: path.join(work, 'tmp') }, stdio: ['ignore', log, log] });
    const startedAt = Date.now();
    record('service_start_requested', { service_pid: child.pid, timeout_ms: serviceStartupTimeoutMs });
    child.on('error', error => { throw error; });
    child.on('exit', code => {
      if (!quitting) {
        record('service_exit_unexpected', { exit_code: code });
        app.exit(code === 0 || code === null ? 1 : code);
      }
    });
    const deadline = startedAt + serviceStartupTimeoutMs;
    let ready = false;
    while (!ready) {
      if (child.exitCode !== null) throw new Error('业务服务启动失败，退出码 ' + child.exitCode);
      if (Date.now() > deadline) {
        record('service_start_timeout', { service_pid: child.pid, elapsed_ms: Date.now() - startedAt });
        throw new Error('业务服务启动超时');
      }
      const instance = path.join(applicationWork, 'instance.json');
      if (fs.existsSync(instance)) ready = JSON.parse(fs.readFileSync(instance)).pid === child.pid;
      if (!ready) await new Promise(resolve => setTimeout(resolve, 100));
    }
    serviceStartupElapsedMs = Date.now() - startedAt;
    record('service_started', { service_pid: child.pid, elapsed_ms: serviceStartupElapsedMs });
    window = new BrowserWindow({ ...branding.windowOptions(), show: process.env.BOSS_DESKTOP_TEST_WINDOW_HIDDEN !== '1', width: 1280, height: 800, webPreferences: { nodeIntegration: false, contextIsolation: true, sandbox: true, webSecurity: true, preload: path.join(__dirname, 'preload.cjs') } });
    window.on('close', event => {
      if (closeHandlerReady && !closeConfirmed) {
        event.preventDefault();
        closeRequested = true;
        window.webContents.send('boss-desktop:close-requested');
      }
    });
    window.webContents.on('did-navigate', () => { closeHandlerReady = false; closeRequested = false; closeConfirmed = false; });
    window.webContents.on('will-prevent-unload', () => { closeConfirmed = false; });
    branding.attachWindow(window);
    window.webContents.setWindowOpenHandler(() => ({ action: 'deny' }));
    window.webContents.on('will-navigate', (event, address) => { if (new URL(address).origin !== origin) event.preventDefault(); });
    window.webContents.on('will-attach-webview', event => event.preventDefault());
    session.defaultSession.setPermissionCheckHandler((contents, permission, requestingOrigin) => microphoneAuthorized && contents === window.webContents && permission === 'media' && new URL(requestingOrigin).origin === origin);
    session.defaultSession.setPermissionRequestHandler((contents, permission, callback, details) => {
      const allowed = microphoneAuthorized && contents === window.webContents && permission === 'media' && details.mediaTypes.length > 0 && details.mediaTypes.every(type => type === 'audio');
      record('renderer_permission_decision', { permission, allowed });
      callback(allowed);
    });
    session.defaultSession.webRequest.onHeadersReceived((details, callback) => callback({ responseHeaders: { ...details.responseHeaders, 'Content-Security-Policy': ["default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline'; img-src 'self' data: blob:; font-src 'self' data:; connect-src 'self' ws://127.0.0.1:" + ports.webui + "; media-src 'self' blob:; object-src 'none'; frame-src 'none'; base-uri 'self'"] } }));
    for (const event of ['suspend', 'resume', 'lock-screen', 'unlock-screen']) powerMonitor.on(event, () => record(event));
    await window.loadURL(origin + (initialPage ? '/?' + new URLSearchParams({ bossPage: initialPage }) : ''));
    record('window_loaded', { versions: process.versions, architecture: process.arch });
  });
}
