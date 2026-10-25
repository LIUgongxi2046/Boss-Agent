const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const { spawn } = require('node:child_process');
const { once } = require('node:events');
const { createRequire } = require('node:module');
const { createHash } = require('node:crypto');
const root = path.resolve(__dirname, '../..');
const load = createRequire(path.join(root, 'design/T27/harness/package.json'));
const { chromium } = load('playwright');
const branding = require('./branding.cjs');
const nativeZoom = process.env.BOSS_T27_NATIVE_ZOOM === '1';
const work = path.join(root, nativeZoom ? 'validation/.work/t27-native-zoom/service' : 'validation/.work/t27');
fs.mkdirSync(path.join(work, 'tmp'), { recursive: true });
process.env.TMPDIR = path.join(work, 'tmp');
const dist = path.join(root, nativeZoom ? '.work/t27-native-zoom/dist/boss-brand' : 'design/T27/harness/dist/boss-brand');
fs.mkdirSync(dist, { recursive: true });
for (const name of ['boss-logo-from-reference.png', 'dapeng-front.png']) fs.copyFileSync(path.join(root, 'Boss-Agent-Desktop-Complete-v6/assets', name), path.join(dist, name));
fs.copyFileSync(path.join(root, 'Boss-Agent-Desktop-Complete-v6/animation/01-待机悬浮.webp'), path.join(dist, 'boss-idle.webp'));
fs.copyFileSync(path.join(root, 'design/T27/assets/boss-flight-sprite.png'), path.join(dist, 'boss-flight-sprite.png'));
const records = [];
const save = check => { records.push({ check, status: 'PASS' }); console.log(check); };

async function main() {
  const service = spawn(path.join(root, 'validation/.venv/bin/python'), [path.join(root, 'design/T27/server.py')], {
    cwd: root, env: { ...process.env, TMPDIR: path.join(work, 'tmp') }, stdio: ['ignore', 'pipe', 'pipe'],
  });
  const serviceErrors = [];
  service.stderr.on('data', chunk => serviceErrors.push(chunk.toString()));
  await once(service.stdout, 'data');
  const { port } = JSON.parse(fs.readFileSync(path.join(work, 'instance.json')));
  assert.notEqual(port, 8872);
  let browser;
  let page;
  const errors = [];
  const responses = [];
  try {
    browser = await chromium.launch({ executablePath: '/Applications/Google Chrome.app/Contents/MacOS/Google Chrome', headless: true, env: { ...process.env, TMPDIR: path.join(work, 'tmp') } });
    const context = await browser.newContext();
    page = await context.newPage();
    page.on('pageerror', error => errors.push({ name: error.name, message: error.message }));
    page.on('response', response => { if (new URL(response.url()).pathname === '/webui/bootstrap') responses.push({ status: response.status() }); });
    const waitForConnection = () => page.waitForEvent('websocket').then(socket => socket.waitForEvent('framereceived', {
      predicate: event => typeof event.payload === 'string' && JSON.parse(event.payload).event === 'ready',
    }));
    await page.goto(`http://127.0.0.1:${port}`);
    await page.getByLabel('账号', { exact: true }).waitFor();
    assert.equal(await page.getByRole('radio').count(), 0);
    assert.equal(await page.getByText('老板的AI助理', { exact: true }).count(), 1);
    assert.equal(await page.getByText('内测版本', { exact: true }).count(), 1);
    assert.equal((await page.locator('#boss-login-brand-title').textContent()), '公司信息了如指掌，工作推进有条不紊。');
    save('copy-beta-default-boss');
    const spacing = await page.locator('.boss-login-card form').evaluate(form => {
      const groups = form.querySelectorAll('.boss-login-field');
      const account = groups[0].getBoundingClientRect();
      const password = groups[1].getBoundingClientRect();
      const submit = form.querySelector('button[type="submit"]').getBoundingClientRect();
      const label = groups[1].querySelector('label').getBoundingClientRect();
      const input = groups[1].querySelector('.boss-login-input').getBoundingClientRect();
      return { fields: password.top - account.bottom, submit: submit.top - password.bottom, label: input.top - label.bottom };
    });
    assert.ok(spacing.fields >= 24 && spacing.submit >= 24 && spacing.label >= 8); save('field-label-submit-spacing');
    await page.getByRole('button', { name: '登录', exact: true }).click();
    await page.getByRole('alert').filter({ hasText: '请输入账号' }).waitFor();
    assert.equal(await page.getByLabel('账号', { exact: true }).evaluate(element => element === document.activeElement), true);
    await page.getByText('认证帮助', { exact: true }).click();
    await page.getByText('请使用本机初始化时提供的账号和密码。账号所属身份由服务端核验。', { exact: true }).waitFor();
    await page.getByText('认证帮助', { exact: true }).click(); save('empty-input-focus-help');
    const footer = await page.locator('.boss-login-footer').evaluate(element => {
      const [entry, help] = element.children;
      return Math.abs(entry.getBoundingClientRect().top - help.getBoundingClientRect().top);
    });
    assert.ok(footer <= 1); save('parallel-maintenance-help');
    for (const [width, height, zoom] of [[1440, 1024, 1], [1280, 800, 1], [1024, 768, 1], [1024, 768, 2]]) {
      await page.setViewportSize({ width, height });
      await page.locator('#root').evaluate((element, scale) => { element.style.zoom = String(scale); }, zoom);
      const bounds = await page.locator('.boss-login').evaluate(element => {
        const rectangle = element.getBoundingClientRect();
        return { left: rectangle.left, top: rectangle.top, right: rectangle.right, bottom: rectangle.bottom,
          width: innerWidth, height: innerHeight, overflow: document.documentElement.scrollWidth > innerWidth };
      });
      assert.ok(Math.abs(bounds.left) <= 1 && Math.abs(bounds.top) <= 1 && Math.abs(bounds.right - bounds.width) <= 1 && Math.abs(bounds.bottom - bounds.height) <= 1);
      assert.equal(bounds.overflow, false); save(`content-bounds-${width}-${height}-${zoom}`);
      await page.waitForFunction(() => document.querySelector('[data-flight="active"]')?.getAnimations().some(animation => animation.playState === 'running'));
      const flight = await page.locator('[data-flight="active"]').evaluate(async image => {
        const initial = image.getBoundingClientRect();
        const depthLayer = image.querySelector('.boss-login-bird-depth');
        const depth = Number.parseFloat(getComputedStyle(depthLayer).scale);
        const wing = image.querySelector('[data-flap]');
        const wingTransform = getComputedStyle(wing).transform;
        await new Promise(resolve => setTimeout(resolve, 400));
        const current = image.getBoundingClientRect();
        const container = image.closest('main').getBoundingClientRect();
        return { moved: Math.hypot(initial.x - current.x, initial.y - current.y),
          contained: current.left >= container.left && current.top >= container.top && current.right <= container.right && current.bottom <= container.bottom,
          depthChanged: Number.parseFloat(getComputedStyle(depthLayer).scale) !== depth,
          wingChanged: getComputedStyle(wing).transform !== wingTransform,
          interaction: getComputedStyle(image.parentElement).pointerEvents };
      });
      assert.ok(flight.moved > 0); assert.equal(flight.contained, true); assert.equal(flight.interaction, 'none');
      assert.equal(flight.depthChanged, true); assert.equal(flight.wingChanged, true);
      save(`random-flight-${width}-${height}-${zoom}`);
    }
    await page.locator('#root').evaluate(element => { element.style.zoom = '1'; });
    await page.emulateMedia({ reducedMotion: 'reduce' });
    await page.locator('[data-motion="reduced"]').waitFor();
    assert.ok((await page.getByAltText('大鹏吉祥物').getAttribute('src')).endsWith('dapeng-front.png'));
    await page.emulateMedia({ reducedMotion: 'no-preference' });
    await page.locator('[data-motion="animated"]').waitFor();
    await page.waitForFunction(() => {
      const image = document.querySelector('[data-flap]');
      return image instanceof HTMLImageElement && image.complete && image.naturalWidth > 0;
    });
    save('motion-preference-change');
    const accounts = JSON.parse(fs.readFileSync(nativeZoom ? path.join(work, 'accounts/credentials.json') : path.join(root, 'validation/.work/application/accounts/credentials.json')));
    for (const account of accounts) {
      if (account.role === 'MAINTAINER') await page.getByRole('button', { name: '技术维护', exact: true }).click();
      await page.getByLabel('账号', { exact: true }).fill(account.username);
      await page.getByLabel('密码', { exact: true }).fill(account.password + '!');
      await page.getByRole('button', { name: '登录', exact: true }).click();
      await page.getByRole('alert').filter({ hasText: '账号或密码无效' }).waitFor();
      save(`reject-password-${account.role}`);
      await page.getByLabel('密码', { exact: true }).fill(account.password);
      let accountRequests = 0;
      const observe = request => { if (request.headers()['x-boss-password']) accountRequests += 1; };
      page.on('request', observe);
      const connected = waitForConnection();
      await page.getByRole('button', { name: '登录', exact: true }).click({ clickCount: 2 });
      await page.locator(`[data-role="${account.role}"]`).waitFor();
      await connected;
      page.off('request', observe);
      assert.equal(accountRequests, 1); save(`login-double-submit-${account.role}`);
      const storage = await page.evaluate(() => JSON.stringify({ local: { ...localStorage }, session: { ...sessionStorage } }));
      for (const value of accounts) assert.equal(storage.includes(value.password), false);
      const refreshedConnection = waitForConnection();
      await page.reload();
      await page.locator(`[data-role="${account.role}"]`).waitFor(); save(`refresh-${account.role}`);
      await refreshedConnection;
      if (account.role === 'MAINTAINER') {
        await page.getByRole('heading', { name: '登录状态已过期' }).waitFor({ timeout: 45000 });
        save('natural-token-expiry');
        await page.getByRole('button', { name: '技术维护', exact: true }).click();
        await page.getByLabel('账号', { exact: true }).fill(account.username);
        await page.getByLabel('密码', { exact: true }).fill(account.password);
        const reconnected = waitForConnection();
        await page.getByRole('button', { name: '重新认证', exact: true }).click();
        await page.locator(`[data-role="${account.role}"]`).waitFor(); save('reauthentication');
        await reconnected;
      }
      if (account.role === 'BOSS') {
        await page.getByRole('heading', { name: '早上好，张总 · 今天想推进什么？', exact: true }).waitFor();
        await page.getByRole('button', { name: '更新当前事项', exact: true }).click();
        await page.getByRole('heading', { name: '业务日期与资料范围', exact: true }).waitFor();
        save('authenticated-homepage-real-data');
      }
      await page.locator('button[title="退出当前身份"]').click();
      await page.getByLabel('账号', { exact: true }).waitFor(); save(`logout-${account.role}`);
    }
    assert.deepEqual(errors, []); save('renderer-errors-zero');
    assert.equal(branding.windowOptions().title, 'Boss Agent');
    assert.equal(branding.packageOptions().name, 'Boss Agent');
    assert.equal(createHash('sha256').update(fs.readFileSync(branding.png)).digest('hex'), createHash('sha256').update(fs.readFileSync(path.join(root, 'validation/desktop/branding/boss-agent-hd.png'))).digest('hex'));
    save('brand-config-project-resource');
    fs.writeFileSync(path.join(root, 'evidence/T27/login-dom.json'), JSON.stringify({ status: 'PASS_INDEPENDENT_LOGIN_AND_HOME', at: new Date().toISOString(), records, visual: 'NOT_RUN', public_integration: 'NOT_RUN' }, null, 2));
  } finally {
    if (page && !page.isClosed()) {
      const state = await page.evaluate(() => ({ card: document.querySelector('.boss-login-card')?.textContent,
        busy: document.querySelector('main')?.getAttribute('aria-busy'),
        fields: [...document.querySelectorAll('.boss-login-field input')].map(input => ({ name: input.name, length: input.value.length, disabled: input.disabled })) }));
      fs.writeFileSync(path.join(work, 'login-check-state.json'), JSON.stringify({ records, state, errors, responses }, null, 2));
    }
    if (browser) await browser.close();
    service.kill('SIGTERM'); await once(service, 'exit');
  }
  console.log(`${records.length}项独立登录检查通过`);
}
main().catch(error => { console.error(error.name, error.message); process.exitCode = 1; });
