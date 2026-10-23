const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const { spawn } = require('node:child_process');
const { once } = require('node:events');
const { createHash } = require('node:crypto');
const { _electron } = require('./harness/node_modules/playwright');

const root = path.resolve(__dirname, '../..');
const work = path.join(root, 'validation/.work/t27-native-zoom');
const serviceDirectory = path.join(work, 'service');
const buildDirectory = path.join(root, '.work/t27-native-zoom');
const output = path.join(root, 'evidence/T27/native-zoom.json');
fs.mkdirSync(path.join(work, 'tmp'), { recursive: true, mode: 0o700 });
process.env.TMPDIR = path.join(work, 'tmp');
const hash = file => createHash('sha256').update(fs.readFileSync(file)).digest('hex');
const records = [];
const previewFiles = ['validation/.work/t27-preview/instance.json', 'validation/.work/t27-native/profile/DevToolsActivePort'];
const previewBefore = Object.fromEntries(previewFiles.map(file => [file, hash(path.join(root, file))]));
const sources = JSON.parse(fs.readFileSync(path.join(buildDirectory, 'build-source.json')));
// 上游源码在构建时核查，运行期间通过完整产物校验和绑定该构建版本。
const productSources = Object.entries(sources).filter(([file]) => file.startsWith(root + path.sep));
for (const [file, expected] of productSources) assert.equal(hash(file), expected);
const assets = path.join(buildDirectory, 'dist/boss-brand');
fs.mkdirSync(assets, { recursive: true });
for (const name of fs.readdirSync(path.join(root, 'Boss-Agent-Desktop-Complete-v6/assets')).filter(name => name.endsWith('.png'))) {
  fs.copyFileSync(path.join(root, 'Boss-Agent-Desktop-Complete-v6/assets', name), path.join(assets, name));
}
fs.copyFileSync(path.join(root, 'Boss-Agent-Desktop-Complete-v6/animation/01-待机悬浮.webp'), path.join(assets, 'boss-idle.webp'));
fs.copyFileSync(path.join(root, 'design/T27/assets/boss-flight-sprite.png'), path.join(assets, 'boss-flight-sprite.png'));
const artifacts = Object.fromEntries(fs.readdirSync(path.join(buildDirectory, 'dist'), { recursive: true, withFileTypes: true }).filter(entry => entry.isFile())
  .map(entry => { const file = path.join(entry.parentPath, entry.name); return [path.relative(path.join(buildDirectory, 'dist'), file), hash(file)]; }));

async function measure(application, page, requested, phase, reducedMotion) {
  await page.emulateMedia({ reducedMotion });
  const marker = reducedMotion === 'reduce' ? '[data-motion="reduced"]' : '[data-flight="active"]';
  await page.locator(marker).waitFor();
  const native = await application.evaluate(({ BrowserWindow, app }) => {
    const window = BrowserWindow.getAllWindows()[0];
    return { zoomFactor: window.webContents.getZoomFactor(), contentSize: window.getContentSize(), visible: window.isVisible(),
      userData: app.getPath('userData'), origin: new URL(window.webContents.getURL()).origin };
  });
  const dom = await page.locator('.boss-login').evaluate(element => {
    const bounds = element.getBoundingClientRect();
    const sprite = document.querySelector('[data-motion]');
    const fields = document.querySelectorAll('.boss-login-field');
    const first = fields[0].getBoundingClientRect();
    const second = fields[1].getBoundingClientRect();
    const passwordLabel = fields[1].querySelector('label').getBoundingClientRect();
    const passwordInput = fields[1].querySelector('.boss-login-input').getBoundingClientRect();
    const submit = document.querySelector('.boss-login-submit').getBoundingClientRect();
    return { viewport: { width: innerWidth, height: innerHeight }, bounds: { left: bounds.left, top: bounds.top, right: bounds.right, bottom: bounds.bottom },
      cssZoom: getComputedStyle(document.getElementById('root')).zoom,
      horizontalOverflow: document.documentElement.scrollWidth > innerWidth,
      mediaReduced: matchMedia('(prefers-reduced-motion: reduce)').matches,
      motion: sprite?.getAttribute('data-motion'), flightAnimations: document.querySelector('.boss-login-flight')?.getAnimations({ subtree: true }).length || 0,
      visibility: document.visibilityState,
      title: document.getElementById('boss-login-title')?.textContent,
      spacing: { fields: second.top - first.bottom, label: passwordInput.top - passwordLabel.bottom, submit: submit.top - second.bottom },
      cardRadius: getComputedStyle(document.querySelector('.boss-login-card')).borderRadius,
      inputRadius: getComputedStyle(document.getElementById('boss-login-account')).borderRadius };
  });
  assert.equal(native.zoomFactor, 2);
  assert.deepEqual(native.contentSize, requested);
  assert.equal(native.visible, false);
  assert.ok(native.userData.startsWith(path.join(work, 'host/profile')));
  assert.equal(dom.cssZoom, '1');
  assert.ok(Math.abs(dom.viewport.width * native.zoomFactor - requested[0]) <= 2);
  assert.ok(Math.abs(dom.viewport.height * native.zoomFactor - requested[1]) <= 2);
  assert.ok(Math.abs(dom.bounds.left) <= 1 && Math.abs(dom.bounds.top) <= 1);
  assert.ok(Math.abs(dom.bounds.right - dom.viewport.width) <= 1 && Math.abs(dom.bounds.bottom - dom.viewport.height) <= 1);
  assert.equal(dom.horizontalOverflow, false);
  assert.equal(dom.mediaReduced, reducedMotion === 'reduce');
  assert.equal(dom.motion, reducedMotion === 'reduce' ? 'reduced' : 'animated');
  if (reducedMotion === 'reduce') assert.equal(dom.flightAnimations, 0);
  else assert.ok(dom.flightAnimations > 0);
  assert.equal(dom.cardRadius, '14px'); assert.equal(dom.inputRadius, '9px');
  assert.ok(dom.spacing.fields >= 24 && dom.spacing.label >= 8 && dom.spacing.submit >= 24);
  assert.equal(dom.title, phase === 'auth' ? '登录 Boss Agent' : '登录状态已过期');
  records.push({ check: 'native-content-bounds-motion', requested, phase, reducedMotion, native, dom, status: 'PASS' });
}

async function keyboard(page, requested, phase) {
  await page.getByLabel('账号', { exact: true }).focus();
  await page.keyboard.press('Tab');
  const passwordFocus = await page.getByLabel('密码', { exact: true }).evaluate(element => {
    const bounds = element.getBoundingClientRect();
    return { focused: element === document.activeElement, focusVisible: element.matches(':focus-visible'), outline: getComputedStyle(element).outlineWidth,
      inViewport: bounds.top >= 0 && bounds.bottom <= innerHeight };
  });
  assert.equal(passwordFocus.focused, true); assert.equal(passwordFocus.focusVisible, true);
  assert.equal(passwordFocus.outline, '2px'); assert.equal(passwordFocus.inViewport, true);
  await page.keyboard.press('Tab');
  assert.equal(await page.getByRole('button', { name: '显示密码', exact: true }).evaluate(element => element === document.activeElement), true);
  await page.keyboard.press('Space');
  assert.equal(await page.getByLabel('密码', { exact: true }).getAttribute('type'), 'text');
  await page.keyboard.press('Space');
  assert.equal(await page.getByLabel('密码', { exact: true }).getAttribute('type'), 'password');
  await page.keyboard.press('Tab');
  assert.equal(await page.getByRole('button', { name: phase === 'auth' ? '登录' : '重新认证', exact: true }).evaluate(element => element === document.activeElement), true);
  if (phase === 'reauth') await page.keyboard.press('Tab');
  await page.keyboard.press('Tab');
  assert.equal(await page.getByRole('button', { name: '技术维护', exact: true }).evaluate(element => element === document.activeElement), true);
  await page.keyboard.press('Tab');
  assert.equal(await page.locator('.boss-login-assistance summary').evaluate(element => element === document.activeElement), true);
  await page.keyboard.press('Enter');
  assert.equal(await page.locator('.boss-login-assistance').getAttribute('open'), '');
  await page.keyboard.press('Enter');
  assert.equal(await page.locator('.boss-login-assistance').getAttribute('open'), null);
  await page.keyboard.press('Shift+Tab');
  await page.keyboard.press('Enter');
  await page.getByRole('heading', { name: phase === 'auth' ? '技术维护登录' : '登录状态已过期', exact: true }).waitFor();
  await page.getByRole('button', { name: '返回本人登录', exact: true }).focus();
  await page.keyboard.press('Enter');
  assert.equal(await page.getByLabel('账号', { exact: true }).evaluate(element => element === document.activeElement), true);
  records.push({ check: 'native-keyboard-label-focus-help-entry', requested, phase, passwordFocus, status: 'PASS' });
}

async function signIn(page, account, phase) {
  await page.getByLabel('账号', { exact: true }).fill(account.username);
  await page.getByLabel('密码', { exact: true }).fill(account.password);
  const connected = page.waitForEvent('websocket').then(socket => socket.waitForEvent('framereceived', {
    predicate: event => typeof event.payload === 'string' && JSON.parse(event.payload).event === 'ready',
  }));
  await page.keyboard.press('Enter');
  await connected;
  await page.locator('.boss-v6[data-role="BOSS"]').waitFor();
  await page.getByRole('heading', { name: '早上好，张总 · 今天想推进什么？', exact: true }).waitFor();
  records.push({ check: phase === 'auth' ? 'native-keyboard-account-login-home' : 'native-keyboard-reauth-home', status: 'PASS' });
}

async function main() {
  const log = fs.openSync(path.join(work, 'service.log'), 'a', 0o600);
  const service = spawn(path.join(root, 'validation/.venv/bin/python'), [path.join(__dirname, 'server.py')], {
    cwd: root, env: { ...process.env, BOSS_T27_NATIVE_ZOOM: '1', BOSS_T27_PREVIEW: '0' }, stdio: ['ignore', 'pipe', log],
  });
  let application;
  try {
    await once(service.stdout, 'data');
    const instance = JSON.parse(fs.readFileSync(path.join(serviceDirectory, 'instance.json')));
    assert.equal(instance.pid, service.pid); assert.notEqual(instance.port, 8872);
    assert.equal(instance.work, serviceDirectory);
    const origin = `http://127.0.0.1:${instance.port}`;
    assert.equal((await fetch(origin)).status, 200);
    const accounts = JSON.parse(fs.readFileSync(path.join(serviceDirectory, 'accounts/credentials.json')));
    const account = accounts.find(value => value.role === 'BOSS');
    assert.ok(account);
    application = await _electron.launch({ args: [path.join(__dirname, 'zoom-host.cjs')],
      executablePath: '/Users/liuhaoxian/.codex/worktrees/boss-integration/Boss-Agent/validation/desktop/node_modules/electron/dist/Electron.app/Contents/MacOS/Electron',
      env: { ...process.env, BOSS_T27_ZOOM_ORIGIN: origin }, cwd: root });
    const page = await application.firstWindow();
    const errors = [];
    page.on('pageerror', error => errors.push({ name: error.name, message: error.message }));
    await page.waitForURL(origin + '/');
    const brand = await application.evaluate(({ app, BrowserWindow, nativeImage }, icon) => ({
      name: app.getName(), title: BrowserWindow.getAllWindows()[0].getTitle(), imageSize: nativeImage.createFromPath(icon).getSize(),
    }), path.join(root, 'validation/desktop/branding/boss-agent.png'));
    assert.equal(brand.name, 'Boss Agent'); assert.equal(brand.title, 'Boss Agent');
    assert.ok(brand.imageSize.width >= 1024 && brand.imageSize.height >= 1024);
    for (const requested of [[1440, 1024], [1280, 800], [1024, 768]]) {
      await application.evaluate(({ BrowserWindow }, size) => {
        const window = BrowserWindow.getAllWindows()[0];
        window.setContentSize(...size); window.webContents.setZoomFactor(2);
      }, requested);
      await page.getByRole('heading', { name: '登录 Boss Agent', exact: true }).waitFor();
      await page.waitForFunction(size => Math.abs(innerWidth * 2 - size[0]) <= 2 && Math.abs(innerHeight * 2 - size[1]) <= 2, requested);
      for (const phase of ['auth', 'reauth']) {
        if (phase === 'reauth') await page.getByRole('heading', { name: '登录状态已过期', exact: true }).waitFor({ timeout: 45000 });
        for (const motion of ['no-preference', 'reduce']) await measure(application, page, requested, phase, motion);
        await keyboard(page, requested, phase);
        await signIn(page, account, phase);
      }
      await page.locator('button[title="退出当前身份"]').click();
      await page.getByRole('heading', { name: '登录 Boss Agent', exact: true }).waitFor();
      console.log(`${requested.join('×')}原生200%登录、重新认证与键盘检查通过`);
    }
    assert.deepEqual(errors, []);
    for (const [file, expected] of Object.entries(previewBefore)) assert.equal(hash(path.join(root, file)), expected);
    for (const [file, expected] of productSources) assert.equal(hash(file), expected);
    for (const [file, expected] of Object.entries(artifacts)) assert.equal(hash(path.join(buildDirectory, 'dist', file)), expected);
    const report = { status: 'PASS_INDEPENDENT_NATIVE_ZOOM_ONLY', at: new Date().toISOString(), records, brand,
      isolation: { servicePid: service.pid, port: instance.port, serviceDirectory, database: path.join(serviceDirectory, 'business.sqlite'),
        accounts: path.join(serviceDirectory, 'accounts'), buildDirectory: path.join(buildDirectory, 'dist'), hidden: true, previewFilesUnchanged: previewBefore },
      source_sha256: { ...sources, ...Object.fromEntries(['design/T27/check-native-zoom.cjs', 'design/T27/zoom-host.cjs', 'design/T27/server.py'].map(file => [file, hash(path.join(root, file))])) },
      source_scope: 'COMPILED_BUILD_SNAPSHOT', artifact_sha256: artifacts,
      rendererErrors: errors, visual: 'NOT_RUN', publicIntegration: 'NOT_RUN', installedApplication: 'NOT_RUN' };
    for (const value of accounts) assert.equal(JSON.stringify(report).includes(value.password), false);
    fs.writeFileSync(output, JSON.stringify(report, null, 2));
    fs.writeFileSync(path.join(root, 'evidence/T27/native-brand.json'), JSON.stringify({ status: 'PASS_NATIVE_HIDDEN_HOST_ONLY',
      result: { ...brand, image: true, profile: path.join(work, 'host/profile') },
      icon_reference: 'Boss-Agent-Desktop-Complete-v6/assets/boss-logo-from-reference.png',
      installed_application: 'NOT_RUN', visual: 'NOT_RUN' }, null, 2));
    console.log(`${records.length}项原生缩放记录通过`);
  } finally {
    if (application) await application.close();
    service.kill('SIGTERM'); await once(service, 'exit'); fs.closeSync(log);
  }
}

void main();
