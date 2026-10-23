const path = require('node:path');
const fs = require('node:fs');
const { spawn } = require('node:child_process');
const { once } = require('node:events');
const assert = require('node:assert/strict');
const { _electron } = require('./harness/node_modules/playwright');

const root = path.resolve(__dirname, '../..');
const work = path.join(root, 'validation/.work/t27-preview');
fs.mkdirSync(path.join(work, 'tmp'), { recursive: true });
process.env.TMPDIR = path.join(work, 'tmp');

async function main() {
  const log = fs.openSync(path.join(work, 'desktop-service.log'), 'a', 0o600);
  const service = spawn(path.join(root, 'validation/.venv/bin/python'), [path.join(__dirname, 'server.py')], {
    cwd: root, env: { ...process.env, BOSS_T27_PREVIEW: '1' }, stdio: ['ignore', 'pipe', log],
  });
  let application;
  try {
    await once(service.stdout, 'data');
    const { port } = JSON.parse(fs.readFileSync(path.join(work, 'instance.json')));
    assert.ok(Number.isInteger(port) && port > 0 && port !== 8872);
    const origin = `http://127.0.0.1:${port}`;
    const response = await fetch(origin);
    assert.equal(response.status, 200);
    application = await _electron.launch({
      executablePath: '/Users/liuhaoxian/.codex/worktrees/boss-integration/Boss-Agent/validation/desktop/node_modules/electron/dist/Electron.app/Contents/MacOS/Electron',
      args: [path.join(__dirname, 'desktop-host.cjs')], cwd: root,
      env: { ...process.env, BOSS_T27_ORIGIN: origin },
    });
    const page = await application.firstWindow();
    await page.getByLabel('账号', { exact: true }).waitFor();
    await page.getByText('内测版本', { exact: true }).waitFor();
    assert.equal(await application.evaluate(({ BrowserWindow }) => BrowserWindow.getAllWindows()[0].getTitle()), 'Boss Agent');
    await application.evaluate(({ BrowserWindow, app }) => {
      const window = BrowserWindow.getAllWindows()[0];
      window.show(); window.focus(); app.focus({ steal: true });
    });
    console.log('Boss Agent独立登录桌面已打开，账号表单及内测标识加载通过。');
    await once(application, 'close');
  } finally {
    if (application) await application.close();
    service.kill('SIGTERM');
    await once(service, 'exit');
    fs.closeSync(log);
  }
}

void main();
