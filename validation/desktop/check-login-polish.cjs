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
const work = path.join(root, 'validation/.work/t27');
fs.mkdirSync(path.join(work, 'tmp'), { recursive: true });
process.env.TMPDIR = path.join(work, 'tmp');
const dist = path.join(root, 'design/T27/harness/dist/boss-brand');
fs.mkdirSync(dist, { recursive: true });
for (const name of ['boss-logo-from-reference.png', 'dapeng-front.png']) fs.copyFileSync(path.join(root, 'Boss-Agent-Desktop-Complete-v6/assets', name), path.join(dist, name));
fs.copyFileSync(path.join(root, 'Boss-Agent-Desktop-Complete-v6/animation/01-待机悬浮.webp'), path.join(dist, 'boss-idle.webp'));
const records = [];
const save = check => records.push({ check, status: 'PASS' });

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
  try {
    browser = await chromium.launch({ executablePath: '/Applications/Google Chrome.app/Contents/MacOS/Google Chrome', headless: true, env: { ...process.env, TMPDIR: path.join(work, 'tmp') } });
    const context = await browser.newContext();
    const page = await context.newPage();
    const errors = [];
    page.on('pageerror', error => errors.push(error.name));
    await page.goto(`http://127.0.0.1:${port}`);
    await page.getByLabel('账号', { exact: true }).waitFor();
    assert.equal(await page.getByRole('radio').count(), 0);
    assert.equal(await page.getByText('老板的AI助理', { exact: true }).count(), 1);
    assert.equal(await page.getByText('内测版本', { exact: true }).count(), 1);
    assert.equal((await page.locator('#boss-login-brand-title').textContent()), '公司信息了如指掌，工作推进有条不紊');
    save('copy-beta-default-boss');
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
    }
    await page.locator('#root').evaluate(element => { element.style.zoom = '1'; });
    await page.emulateMedia({ reducedMotion: 'reduce' });
    await page.locator('[data-motion="reduced"]').waitFor();
    assert.ok((await page.getByAltText('大鹏吉祥物').getAttribute('src')).endsWith('dapeng-front.png'));
    await page.emulateMedia({ reducedMotion: 'no-preference' });
    await page.locator('[data-motion="animated"]').waitFor();
    await page.waitForFunction(() => {
      const image = document.querySelector('[data-motion="animated"]');
      return image instanceof HTMLImageElement && image.complete && image.naturalWidth > 0;
    });
    save('motion-preference-change');
    const accounts = JSON.parse(fs.readFileSync(path.join(root, 'validation/.work/application/accounts/credentials.json')));
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
      await page.getByRole('button', { name: '登录', exact: true }).click({ clickCount: 2 });
      await page.locator(`[data-role="${account.role}"]`).waitFor();
      page.off('request', observe);
      assert.equal(accountRequests, 1); save(`login-double-submit-${account.role}`);
      const storage = await page.evaluate(() => JSON.stringify({ local: { ...localStorage }, session: { ...sessionStorage } }));
      for (const value of accounts) assert.equal(storage.includes(value.password), false);
      await page.reload();
      await page.locator(`[data-role="${account.role}"]`).waitFor(); save(`refresh-${account.role}`);
      if (account.role === 'MAINTAINER') {
        await page.waitForTimeout(31000);
        await page.reload();
        await page.getByRole('heading', { name: '登录状态已过期' }).waitFor();
        save('natural-token-expiry');
        await page.getByRole('button', { name: '技术维护', exact: true }).click();
        await page.getByLabel('账号', { exact: true }).fill(account.username);
        await page.getByLabel('密码', { exact: true }).fill(account.password);
        await page.getByRole('button', { name: '重新认证', exact: true }).click();
        await page.locator(`[data-role="${account.role}"]`).waitFor(); save('reauthentication');
      }
      await page.getByRole('button', { name: '退出登录', exact: true }).click();
      await page.getByLabel('账号', { exact: true }).waitFor(); save(`logout-${account.role}`);
    }
    assert.deepEqual(errors, []); save('renderer-errors-zero');
    assert.equal(branding.windowOptions().title, 'Boss Agent');
    assert.equal(branding.packageOptions().name, 'Boss Agent');
    assert.equal(createHash('sha256').update(fs.readFileSync(branding.png)).digest('hex'), createHash('sha256').update(fs.readFileSync(path.join(root, 'Boss-Agent-Desktop-Complete-v6/assets/boss-logo-from-reference.png'))).digest('hex'));
    save('brand-config-project-resource');
    fs.writeFileSync(path.join(root, 'evidence/T27/login-dom.json'), JSON.stringify({ status: 'PASS_INDEPENDENT_LOGIN_ONLY', at: new Date().toISOString(), records, visual: 'NOT_RUN', public_integration: 'NOT_RUN' }, null, 2));
  } finally {
    if (browser) await browser.close();
    service.kill('SIGTERM'); await once(service, 'exit');
  }
  console.log(`${records.length}项独立登录检查通过`);
}
main().catch(error => { console.error(error.name, error.message); process.exitCode = 1; });
