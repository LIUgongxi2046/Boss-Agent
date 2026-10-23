const path = require('node:path');
const fs = require('node:fs');
const assert = require('node:assert/strict');
const { spawn } = require('node:child_process');
const { once } = require('node:events');
const { _electron } = require('./harness/node_modules/playwright');
const root = path.resolve(__dirname, '../..');
const revision = process.env.BOSS_T27_REVIEW_REVISION || '';
assert.ok(['', 'flight'].includes(revision));
const name = revision === 'flight' ? 't27-review-flight' : 't27-review';
const work = path.join(root, 'validation/.work', name);
const dist = path.join(root, '.work', name, 'dist/boss-brand');
fs.mkdirSync(path.join(work, 'tmp'), { recursive: true, mode: 0o700 });
fs.mkdirSync(dist, { recursive: true });
process.env.TMPDIR = path.join(work, 'tmp');
for (const name of fs.readdirSync(path.join(root, 'Boss-Agent-Desktop-Complete-v6/assets')).filter(name => name.endsWith('.png'))) {
  fs.copyFileSync(path.join(root, 'Boss-Agent-Desktop-Complete-v6/assets', name), path.join(dist, name));
}
fs.copyFileSync(path.join(root, 'design/T27/assets/boss-flight-sprite.png'), path.join(dist, 'boss-flight-sprite.png'));

async function main() {
  const log = fs.openSync(path.join(work, 'service.log'), 'a', 0o600);
  const service = spawn(path.join(root, 'validation/.venv/bin/python'), [path.join(__dirname, 'server.py')], {
    cwd: root, env: { ...process.env, BOSS_T27_REVIEW: '1', BOSS_T27_NATIVE_ZOOM: '0', BOSS_T27_PREVIEW: '0' }, stdio: ['ignore', 'pipe', log],
  });
  let application;
  try {
    await once(service.stdout, 'data', { signal: AbortSignal.timeout(90000) });
    const instance = JSON.parse(fs.readFileSync(path.join(work, 'service/instance.json')));
    assert.equal(instance.pid, service.pid); assert.notEqual(instance.port, 8872);
    const origin = `http://127.0.0.1:${instance.port}`;
    const accounts = JSON.parse(fs.readFileSync(path.join(root, 'validation/.work/application/accounts/credentials.json')));
    for (const account of accounts) {
      const response = await fetch(origin + '/webui/bootstrap', { headers: { 'X-Boss-Username': account.username, 'X-Boss-Password': account.password, 'X-Boss-Role': account.role } });
      assert.equal(response.status, 200);
      const boot = await response.json();
      const identity = await fetch(origin + '/api/boss/identity', { headers: { Authorization: 'Bearer ' + boot.api_token } });
      assert.equal((await identity.json()).role, account.role);
    }
    application = await _electron.launch({ args: [path.join(__dirname, 'review-host.cjs')],
      executablePath: '/Users/liuhaoxian/.codex/worktrees/boss-integration/Boss-Agent/validation/desktop/node_modules/electron/dist/Electron.app/Contents/MacOS/Electron',
      env: { ...process.env, BOSS_T27_REVIEW_ORIGIN: origin }, cwd: root });
    const page = await application.firstWindow();
    await page.getByLabel('账号', { exact: true }).waitFor();
    await page.locator('[data-flap="eight-frame"]').waitFor();
    await application.evaluate(({ app, BrowserWindow }) => { BrowserWindow.getAllWindows()[0].focus(); app.focus({ steal: true }); });
    console.log('同款Logo、连续转弯与方向同步、表单间距的新窗口已打开，原窗口保持运行。');
    await once(application, 'close');
  } finally {
    if (application) await application.close();
    service.kill('SIGTERM'); await once(service, 'exit'); fs.closeSync(log);
  }
}
void main();
