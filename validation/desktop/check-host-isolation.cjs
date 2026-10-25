const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const { createHash, randomUUID } = require('node:crypto');
const { spawnSync } = require('node:child_process');
const { _electron: electron } = require('playwright');

const validation = path.resolve(__dirname, '..');
const root = path.dirname(validation);
const runId = 'host-isolation-' + randomUUID();
const applicationDirectory = path.join(validation, '.work', runId);
const desktopDirectory = path.join(validation, '.work', 'desktop-' + runId);
const ports = { business: 8971, webui: 8972, gateway: 18971 };
const output = path.join(root, 'evidence/T11/w3-local-20261023', runId + '.json');
const inputs = ['validation/application.py', 'validation/application_paths.py',
  'validation/desktop/main.cjs', 'validation/desktop/check-host-isolation.cjs'].map(file => ({
  path: file, sha256: createHash('sha256').update(fs.readFileSync(path.join(root, file))).digest('hex'),
}));

async function check() {
  const desktop = await electron.launch({ args: [__dirname], cwd: validation, timeout: 60000,
    env: { ...process.env, BOSS_VALIDATION_ROOT: validation, BOSS_PRODUCT_UI: '1',
      BOSS_APPLICATION_WORK_DIR: applicationDirectory, BOSS_APPLICATION_PORTS: JSON.stringify(ports),
      BOSS_DESKTOP_TEST_WINDOW_HIDDEN: '1', TMPDIR: path.join(validation, '.work/tmp') } });
  let report;
  try {
    const page = await desktop.firstWindow({ timeout: 120000 });
    await page.waitForURL('http://127.0.0.1:' + ports.webui + '/');
    await page.locator('.boss-login').waitFor();
    const windows = await desktop.evaluate(({ BrowserWindow }) => BrowserWindow.getAllWindows().map(window => ({ visible: window.isVisible() })));
    assert.equal(windows.length, 1);
    assert.equal(windows[0].visible, false);
    const capability = await page.evaluate(() => window.bossDesktop.invoke({ action: 'status' }));
    const instance = JSON.parse(fs.readFileSync(path.join(applicationDirectory, 'instance.json')));
    assert.equal(capability.service_pid, instance.pid);
    assert.deepEqual(instance.ports, ports);
    const permissions = {
      application: fs.statSync(applicationDirectory).mode & 0o777,
      desktop: fs.statSync(desktopDirectory).mode & 0o777,
      access: fs.statSync(path.join(applicationDirectory, 'access.json')).mode & 0o777,
    };
    assert.deepEqual(permissions, { application: 0o700, desktop: 0o700, access: 0o600 });
    assert.equal(await page.evaluate(() => typeof window.require), 'undefined');
    assert.equal(await page.evaluate(() => typeof window.process), 'undefined');
    report = { status: 'PASS_HIDDEN_HOST_AND_DIRECTORY_ISOLATION_ONLY', run_id: runId,
      at: new Date().toISOString(), inputs, ports, windows, permissions,
      service_pid: instance.pid, service_startup_ms: capability.service_startup_ms,
      business_write_requested: false, authentication_requested: false,
      visual_acceptance: 'NOT_RUN', full_A11_accepted: false };
  } finally {
    await desktop.close();
  }
  const remaining = spawnSync('lsof', ['-nP', '-iTCP:8971', '-iTCP:8972', '-sTCP:LISTEN'], { encoding: 'utf8' });
  assert.equal(remaining.status, 1);
  assert.equal(remaining.stdout, '');
  report.own_service_ports_released = true;
  fs.writeFileSync(output, JSON.stringify(report, null, 2));
  console.log(JSON.stringify({ status: report.status, evidence: output }));
}

check();
