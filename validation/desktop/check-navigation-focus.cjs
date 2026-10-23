const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const { createHash, randomUUID } = require('node:crypto');
const { _electron: electron } = require('playwright');
const { expect } = require('@playwright/test');

const root = path.resolve(__dirname, '../..');
const validation = path.join(root, 'validation');
const runId = 'navigation-focus-' + randomUUID();
const applicationDirectory = path.join(validation, '.work', runId);
const ports = { business: 8971, webui: 8972, gateway: 18971 };
const origin = 'http://127.0.0.1:' + ports.webui;
const output = path.join(root, 'evidence/T11/w3-local-20261023', runId + '.json');
const records = [];
const inputs = ['app/webui/BossDesktop.tsx', 'app/webui/boss-v6.css', 'validation/desktop/check-navigation-focus.cjs',
  '.work/product/nanobot/nanobot/web/dist/asset-manifest.json'].map(file => ({ path: file,
  sha256: createHash('sha256').update(fs.readFileSync(path.join(root, file))).digest('hex') }));
function save(status) {
  fs.writeFileSync(output, JSON.stringify({ status, run_id: runId, at: new Date().toISOString(), inputs, records,
    business_write_requested: false, model_requested: false, visual_acceptance: 'NOT_RUN',
    full_A08_A11_accepted: false }, null, 2));
}

async function check() {
  const desktop = await electron.launch({ args: [__dirname], cwd: validation, timeout: 60000,
    env: { ...process.env, BOSS_VALIDATION_ROOT: validation, BOSS_PRODUCT_UI: '1',
      BOSS_APPLICATION_WORK_DIR: applicationDirectory, BOSS_APPLICATION_PORTS: JSON.stringify(ports),
      BOSS_DESKTOP_TEST_WINDOW_HIDDEN: '1', TMPDIR: path.join(validation, '.work/tmp') } });
  try {
    const page = await desktop.firstWindow({ timeout: 120000 });
    const errors = [];
    page.on('pageerror', error => errors.push({ name: error.name }));
    await page.waitForURL(origin + '/');
    await page.getByLabel('本机访问凭据', { exact: true }).waitFor();
    const access = JSON.parse(fs.readFileSync(path.join(applicationDirectory, 'access.json')));
    await page.getByRole('radio', { name: /^老板本人/ }).check();
    await page.getByLabel('本机访问凭据', { exact: true }).fill(access.BOSS);
    await page.getByRole('button', { name: '继续认证', exact: true }).click();
    await page.locator('.boss-v6[data-role="BOSS"]').waitFor();
    const bootstrap = await fetch(origin + '/webui/bootstrap', { headers: { 'X-Nanobot-Auth': access.BOSS } });
    assert.equal(bootstrap.status, 200);
    const headers = { Authorization: 'Bearer ' + (await bootstrap.json()).api_token };
    async function read(route) {
      const response = await fetch(origin + '/api/boss/ui/' + route, { headers });
      assert.equal(response.status, 200);
      return response.json();
    }
    const before = await read('meeting-arrangement');
    const source = await read('evidence?source=finance-note');
    await page.goto(origin + '/?bossPage=F04', { waitUntil: 'networkidle' });
    const purpose = page.getByRole('textbox', { name: /^会议目的/ });
    await purpose.fill(source.content);
    const trigger = page.getByTitle('任务与承诺', { exact: true });
    await trigger.click();
    const dialog = page.getByRole('dialog', { name: '未保存修改（D06）', exact: true });
    await dialog.waitFor();
    const focusedInside = await dialog.evaluate(element => element.contains(document.activeElement));
    records.push({ check: 'dialog_open_focus', focused_inside: focusedInside }); save('IN_PROGRESS');
    assert.equal(focusedInside, true);
    for (const key of ['Tab', 'Tab', 'Tab', 'Shift+Tab', 'Shift+Tab']) {
      await page.keyboard.press(key);
      assert.equal(await dialog.evaluate(element => element.contains(document.activeElement)), true);
    }
    await trigger.evaluate(element => element.focus());
    assert.equal(await dialog.evaluate(element => element.contains(document.activeElement)), true);
    records.push({ check: 'tab_and_programmatic_focus_remain_in_dialog', passed: true });
    for (const zoom of [1, 2]) {
      await desktop.evaluate(({ BrowserWindow }, value) => BrowserWindow.getAllWindows()[0].webContents.setZoomFactor(value), zoom);
      for (const size of [[1024, 768], [1280, 800], [1440, 1024]]) {
        await desktop.evaluate(({ BrowserWindow }, value) => BrowserWindow.getAllWindows()[0].setContentSize(...value), size);
        const bounds = await dialog.evaluate(element => {
          const rect = element.getBoundingClientRect();
          return { left: rect.left, top: rect.top, right: innerWidth - rect.right, bottom: innerHeight - rect.bottom };
        });
        assert.ok(Object.values(bounds).every(value => value >= -1));
        records.push({ check: 'dialog_content_bounds', zoom, size, bounds });
      }
    }
    await desktop.evaluate(({ BrowserWindow }) => BrowserWindow.getAllWindows()[0].webContents.setZoomFactor(1));
    await page.keyboard.press('Escape');
    await dialog.waitFor({ state: 'detached' });
    await expect(trigger).toBeFocused();
    assert.equal(await purpose.inputValue(), source.content);
    records.push({ check: 'escape_restores_trigger_and_preserves_editing', passed: true });
    await trigger.click();
    await dialog.getByRole('button', { name: '返回继续编辑', exact: true }).click();
    await dialog.waitFor({ state: 'detached' });
    assert.equal(await purpose.inputValue(), source.content);
    await trigger.click();
    await dialog.getByRole('button', { name: '放弃草稿并离开', exact: true }).click();
    await page.waitForURL(origin + '/?bossPage=N05');
    assert.deepEqual((await read('meeting-arrangement')).meeting, before.meeting);
    assert.equal(errors.length, 0);
    records.push({ check: 'explicit_discard_navigates_without_saving_meeting', passed: true, renderer_errors: errors });
    save('PASS_D06_FOCUS_AND_VIEWPORT_ONLY');
    console.log(JSON.stringify({ status: 'PASS_D06_FOCUS_AND_VIEWPORT_ONLY', evidence: output }));
  } finally {
    await desktop.close();
  }
}

process.on('uncaughtExceptionMonitor', error => {
  records.push({ check: 'uncaught_failure', name: error.name }); save('FAILED_CHECK');
});
check();
