const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const {createHash, randomUUID} = require('node:crypto');
const {execFileSync} = require('node:child_process');
const {_electron: electron} = require('playwright');
const {expect} = require('@playwright/test');
const accountAccess = require('./account-access.cjs');

const root = path.resolve(__dirname, '../..');
const validation = path.join(root, 'validation');
const runId = 'account-upgrade-expiry-' + randomUUID();
const directory = path.join(validation, '.work', runId);
const reference = 'evidence/T11/w3-local-20261023/memory-public-5917d36b-ce8d-411a-af34-2e999e3feeef.json';
const output = path.join(root, 'evidence/T11/w3-local-20261023', runId + '.json');
const ports = {business: 8971, webui: 8972, gateway: 18971};
const origin = 'http://127.0.0.1:8972';
const digest = value => createHash('sha256').update(value).digest('hex');
const records = [];
const inputs = ['validation/prepare_account_upgrade.py', 'validation/application.py', 'validation/boss_account_auth.py',
  'validation/desktop/main.cjs', 'validation/desktop/check-account-expiry.cjs', 'app/webui/BossLogin.tsx',
  'app/webui/boss-login.css', 'scripts/boss_auth_overlay.py', reference,
  '.work/product/nanobot/nanobot/web/dist/asset-manifest.json'].map(file => ({path: file, sha256: digest(fs.readFileSync(path.join(root, file)))}));
function save(status) {fs.writeFileSync(output, JSON.stringify({status, run_id: runId, at: new Date().toISOString(),
  application_directory: path.relative(root, directory), inputs, records, ports, token_ttl_seconds: 30,
  external_api_mode: 'SIMULATED_FIRST', new_model_calls: false, new_business_actions: false,
  natural_time_used: true, private_body_recorded: false, visual_acceptance: 'NOT_RUN', full_A11_A27_accepted: false}, null, 2));}
function note(check, values) {records.push({check, ...values}); save('IN_PROGRESS');}
function python(script, args) {return JSON.parse(execFileSync(path.join(validation, '.venv/bin/python'),
  [path.join(root, script), ...args], {cwd: root, env: {...process.env, TMPDIR: path.join(validation, '.work/tmp')},
    timeout: 60000, maxBuffer: 4 * 1024 * 1024}).toString());}
function manifest() {return python('evidence/T12/check_simulation_reads.py', ['--database', path.join(directory, 'business.sqlite')]);}
async function check() {
  let desktop = null;
  try {
    const prepared = python('validation/prepare_account_upgrade.py', ['--reference', path.join(root, reference),
      '--target-directory', directory, '--token-ttl-seconds', '30']);
    assert.equal(prepared.token_ttl_seconds, 30); const accounts = accountAccess.provision(directory); const before = manifest();
    desktop = await electron.launch({args: [__dirname], cwd: validation, timeout: 60000,
      env: {...process.env, BOSS_VALIDATION_ROOT: validation, BOSS_PRODUCT_UI: '1', BOSS_APPLICATION_WORK_DIR: directory,
        BOSS_APPLICATION_PORTS: JSON.stringify(ports), BOSS_DESKTOP_TEST_WINDOW_HIDDEN: '1', TMPDIR: path.join(validation, '.work/tmp')}});
    const page = await desktop.firstWindow({timeout: 120000}); const errors = [];
    page.on('pageerror', error => errors.push({name: error.name})); await page.waitForURL(origin + '/');
    await accountAccess.login(page, accounts, 'MAINTAINER');
    const boot = await accountAccess.bootstrap(origin, accounts, 'MAINTAINER'); assert.equal(boot.expires_in, 30);
    await page.goto(origin + '/?bossPage=A15', {waitUntil: 'networkidle'});
    await page.getByRole('region', {name: '运行记录查询', exact: true}).waitFor();
    const departed = await page.goto(origin + '/api/boss/identity', {waitUntil: 'networkidle'});
    assert.equal(departed.status(), 401); await page.getByText('未认证', {exact: true}).waitFor();
    const stored = await page.evaluate(() => localStorage.getItem('nanobot-webui.bootstrap-secret'));
    assert.ok(stored);
    const status = async () => (await fetch(origin + '/api/boss/identity', {headers: {Authorization: 'Bearer ' + stored}})).status;
    assert.equal(await status(), 200); const started = performance.now();
    await expect.poll(status, {timeout: 45000, intervals: [500, 1000]}).toBe(401);
    note('actual_stored_native_api_token_expires_without_clock_override', {prepared, expires_in: boot.expires_in,
      elapsed_after_document_departure_ms: Math.round(performance.now() - started), token_value_recorded: false, expired_status: 401});
    await page.goto(origin + '/?bossPage=A15', {waitUntil: 'networkidle'});
    await page.getByRole('heading', {name: '登录状态已过期', exact: true}).waitFor();
    assert.equal(await page.locator('.boss-v6[data-role]').count(), 0);
    for (const zoom of [1, 2]) {
      await desktop.evaluate(({BrowserWindow}, value) => BrowserWindow.getAllWindows()[0].webContents.setZoomFactor(value), zoom);
      for (const size of [[1024, 768], [1280, 800], [1440, 1024]]) {
        await desktop.evaluate(({BrowserWindow}, value) => BrowserWindow.getAllWindows()[0].setContentSize(...value), size);
        const bounds = await page.locator('.boss-login').evaluate(element => {
          const box = element.getBoundingClientRect(); return {x: box.x, y: box.y, right: box.right, bottom: box.bottom,
            width: innerWidth, height: innerHeight, horizontal_overflow: document.documentElement.scrollWidth > innerWidth + 1};
        });
        assert.ok(Math.abs(bounds.x) <= 1 && Math.abs(bounds.y) <= 1 && Math.abs(bounds.right - bounds.width) <= 1 && Math.abs(bounds.bottom - bounds.height) <= 1);
        assert.equal(bounds.horizontal_overflow, false); note('public_d08_native_viewport', {zoom, size, bounds});
      }
    }
    await desktop.evaluate(({BrowserWindow}) => BrowserWindow.getAllWindows()[0].webContents.setZoomFactor(1));
    await page.emulateMedia({reducedMotion: 'reduce'});
    await expect(page.locator('[data-motion="reduced"]')).toHaveAttribute('src', '/boss-brand/dapeng-front.png');
    assert.equal(await page.locator('.boss-login-flight').count(), 0);
    await page.getByLabel('账号', {exact: true}).focus(); await page.keyboard.press('Tab');
    await expect(page.getByLabel('密码', {exact: true})).toBeFocused(); await page.keyboard.press('Tab');
    await expect(page.getByRole('button', {name: '显示密码', exact: true})).toBeFocused(); await page.keyboard.press('Space');
    await expect(page.getByLabel('密码', {exact: true})).toHaveAttribute('type', 'text');
    await page.keyboard.press('Shift+Tab'); await expect(page.getByLabel('密码', {exact: true})).toBeFocused();
    await page.emulateMedia({reducedMotion: 'no-preference'}); await page.locator('[data-motion="animated"]').waitFor();
    await accountAccess.login(page, accounts, 'MAINTAINER');
    await page.getByRole('region', {name: '运行记录查询', exact: true}).getByRole('button', {name: '查询记录', exact: true}).click();
    for (const id of prepared.historical_run_ids) await page.getByRole('button', {name: '打开记录 ' + id, exact: true}).waitFor();
    assert.equal(new URL(page.url()).searchParams.get('bossPage'), 'A15'); assert.equal(await status(), 401);
    const after = manifest(); assert.deepEqual(after.before_tables_sha256, before.before_tables_sha256); assert.deepEqual(errors, []);
    const source = path.join(root, prepared.source_directory);
    assert.equal(digest(fs.readFileSync(path.join(source, 'business.sqlite'))), prepared.source_database_sha256);
    assert.equal(digest(fs.readFileSync(path.join(source, 'config.json'))), prepared.source_configuration_sha256);
    note('public_d08_reauthentication_keyboard_motion_preference_and_existing_records', {role: 'MAINTAINER', current_page: 'A15',
      historical_run_ids: prepared.historical_run_ids, old_token: 401, keyboard_tab_and_password_control: true,
      browser_reduced_motion_condition_verified: true, full_motion_visual_acceptance: false,
      renderer_errors: errors, business_tables_sha256: after.after_tables_sha256, source_database_and_configuration_unchanged: true});
    save('PASS_PUBLIC_NATURAL_ACCOUNT_EXPIRY_D08_AND_REAUTHENTICATION');
    console.log(JSON.stringify({status: 'PASS_PUBLIC_NATURAL_ACCOUNT_EXPIRY_D08_AND_REAUTHENTICATION', evidence: output}));
  } finally {if (desktop) await desktop.close();}
}
process.on('uncaughtExceptionMonitor', error => {records.push({check: 'uncaught_failure', name: error.name}); save('FAILED_CHECK');});
check();
