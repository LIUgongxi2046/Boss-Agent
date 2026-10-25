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
const runId = 'account-public-' + randomUUID();
const directory = path.join(validation, '.work', runId);
const accounts = accountAccess.provision(directory);
const output = path.join(root, 'evidence/T11/w3-local-20261023', runId + '.json');
const ports = {business: 8971, webui: 8972, gateway: 18971};
const origin = 'http://127.0.0.1:8972';
const digest = value => createHash('sha256').update(value).digest('hex');
const records = [];
const inputs = ['app/webui/BossLogin.tsx', 'app/webui/boss-login.css', 'app/webui/BossDesktop.tsx',
  'validation/application.py', 'validation/boss_account_auth.py', 'validation/role_channel.py',
  'validation/desktop/main.cjs', 'validation/desktop/branding.cjs', 'validation/desktop/account-access.cjs',
  'validation/desktop/check-account-public.cjs', 'validation/pyproject.toml', 'validation/uv.lock',
  'validation/check_product_access.py',
  'specs/product-auth.openapi.yaml',
  '.work/product/nanobot/nanobot/web/dist/asset-manifest.json'].map(file => ({path: file, sha256: digest(fs.readFileSync(path.join(root, file)))}));
function save(status) {fs.writeFileSync(output, JSON.stringify({status, run_id: runId, at: new Date().toISOString(),
  application_directory: path.relative(root, directory), inputs, records, ports, external_api_mode: 'SIMULATED_FIRST',
  model_requested: false, external_delivery_requested: false, credentials_recorded: false,
  visual_acceptance: 'NOT_RUN', full_A11_A27_accepted: false}, null, 2));}
function note(check, values) {records.push({check, ...values}); save('IN_PROGRESS');}
function manifest() {return JSON.parse(execFileSync(path.join(validation, '.venv/bin/python'), [
  path.join(root, 'evidence/T12/check_simulation_reads.py'), '--database', path.join(directory, 'business.sqlite'),
], {cwd: root, encoding: 'utf8'}));}
async function launch() {return electron.launch({args: [__dirname], cwd: validation, timeout: 60000,
  env: {...process.env, BOSS_VALIDATION_ROOT: validation, BOSS_PRODUCT_UI: '1', BOSS_APPLICATION_WORK_DIR: directory,
    BOSS_APPLICATION_PORTS: JSON.stringify(ports), BOSS_DESKTOP_TEST_WINDOW_HIDDEN: '1', TMPDIR: path.join(validation, '.work/tmp')}});}
async function check() {
  let desktop = await launch();
  const errors = [], sockets = [];
  try {
    let page = await desktop.firstWindow({timeout: 120000});
    page.on('pageerror', error => errors.push({name: error.name})); await page.waitForURL(origin + '/');
    const internal = JSON.parse(fs.readFileSync(path.join(directory, 'access.json')));
    const legacy = await fetch(origin + '/webui/bootstrap', {headers: {'X-Nanobot-Auth': internal.BOSS}});
    assert.equal(legacy.status, 401);
    const before = manifest(); const accountFileSha = digest(fs.readFileSync(path.join(directory, 'accounts/accounts.sqlite')));
    async function read(token, route, status = 200) {
      const response = await fetch(origin + '/api/boss/ui/' + route, {headers: {Authorization: 'Bearer ' + token}});
      assert.equal(response.status, status); return status === 200 ? response.json() : null;
    }
    async function socketFor(role) {
      const boot = await accountAccess.bootstrap(origin, accounts, role);
      const socket = new WebSocket(origin.replace('http:', 'ws:') + boot.ws_path + '?token=' + encodeURIComponent(boot.token)); sockets.push(socket);
      await new Promise(resolve => socket.addEventListener('message', event => {if (JSON.parse(event.data).event === 'ready') resolve();}));
      return {token: boot.api_token, async command(action, payload) {
        const id = randomUUID(); const result = new Promise(resolve => {
          const listener = event => {const value = JSON.parse(event.data); if (value.request_id === id) {socket.removeEventListener('message', listener); resolve(value);}};
          socket.addEventListener('message', listener);
        }); socket.send(JSON.stringify({type: 'webui_request', request_id: id, action, payload})); return result;
      }};
    }
    await page.getByRole('heading', {name: '登录 Boss Agent', exact: true}).waitFor();
    await page.getByText('老板的AI助理', {exact: true}).waitFor(); await page.getByText('内测版本', {exact: true}).waitFor();
    await page.getByRole('button', {name: '登录', exact: true}).click();
    await page.getByRole('alert').filter({hasText: '请输入账号。'}).waitFor();
    await page.getByLabel('账号', {exact: true}).fill(accounts.BOSS.username);
    await page.getByRole('button', {name: '登录', exact: true}).click();
    await page.getByRole('alert').filter({hasText: '请输入密码。'}).waitFor();
    await page.getByLabel('密码', {exact: true}).fill(accounts.BOSS.password + '!');
    await page.getByRole('button', {name: '登录', exact: true}).click();
    await page.getByRole('alert').filter({hasText: '账号或密码无效'}).waitFor();
    await expect(page.getByLabel('密码', {exact: true})).toHaveValue('');
    const native = await desktop.evaluate(({app, BrowserWindow}) => ({name: app.getName(), title: BrowserWindow.getAllWindows()[0].getTitle()}));
    assert.deepEqual(native, {name: 'Boss Agent', title: 'Boss Agent'});
    for (const zoom of [1, 2]) {
      await desktop.evaluate(({BrowserWindow}, value) => BrowserWindow.getAllWindows()[0].webContents.setZoomFactor(value), zoom);
      for (const size of [[1024, 768], [1280, 800], [1440, 1024]]) {
        await desktop.evaluate(({BrowserWindow}, value) => BrowserWindow.getAllWindows()[0].setContentSize(...value), size);
        const bounds = await page.locator('.boss-login').evaluate(element => {
          const box = element.getBoundingClientRect(); return {x: box.x, y: box.y, right: box.right, bottom: box.bottom,
            width: innerWidth, height: innerHeight, horizontal_overflow: document.documentElement.scrollWidth > innerWidth + 1};
        });
        assert.ok(Math.abs(bounds.x) <= 1 && Math.abs(bounds.y) <= 1 && Math.abs(bounds.right - bounds.width) <= 1 && Math.abs(bounds.bottom - bounds.height) <= 1);
        assert.equal(bounds.horizontal_overflow, false); note('public_login_native_viewport', {zoom, size, bounds});
      }
    }
    await desktop.evaluate(({BrowserWindow}) => BrowserWindow.getAllWindows()[0].webContents.setZoomFactor(1));
    await accountAccess.login(page, accounts, 'BOSS'); const boss = await socketFor('BOSS');
    const dashboard = await read(boss.token, 'dashboard'); assert.equal(dashboard.source_type, 'SIMULATED');
    await page.reload({waitUntil: 'networkidle'}); await page.locator('.boss-v6[data-role="BOSS"]').waitFor();
    await read(boss.token, 'admin/sop-method?sop_id=SOP03', 403);
    const denied = await boss.command('boss.sop.save', {client_request_id: runId}); assert.equal(denied.error.status, 403);
    const storage = await page.evaluate(() => [...Object.values(localStorage), ...Object.values(sessionStorage)]);
    assert.ok(storage.every(value => Object.values(accounts).every(account => !value.includes(account.password))));
    const refreshed = await fetch(origin + '/webui/bootstrap', {headers: {Authorization: 'Bearer ' + boss.token}});
    assert.equal(refreshed.status, 200); assert.equal(refreshed.headers.get('cache-control'), 'no-store');
    await accountAccess.logout(page); await read(boss.token, 'dashboard', 401);
    assert.equal((await fetch(origin + '/webui/bootstrap', {headers: {Authorization: 'Bearer ' + boss.token}})).status, 401);
    await page.getByRole('button', {name: '技术维护', exact: true}).click();
    await page.getByLabel('账号', {exact: true}).fill(accounts.BOSS.username);
    await page.getByLabel('密码', {exact: true}).fill(accounts.BOSS.password);
    await page.getByRole('button', {name: '登录', exact: true}).click();
    await page.getByRole('alert').filter({hasText: '账号或密码无效'}).waitFor();
    await page.getByRole('button', {name: '返回本人登录', exact: true}).click();
    await accountAccess.login(page, accounts, 'MAINTAINER'); const maint = await socketFor('MAINTAINER');
    await read(maint.token, 'dashboard', 403);
    assert.equal((await read(maint.token, 'admin/skills')).items.length, 13);
    await page.goto(origin + '/?bossPage=A06&bossSop=SOP03', {waitUntil: 'networkidle'});
    await page.getByRole('button', {name: '读取当前方法', exact: true}).click();
    await page.getByRole('table', {name: '已保存方法步骤表', exact: true}).waitFor();
    note('public_account_owner_maintenance_roles_reload_and_logout', {legacy_secret: 401, owner_technical: 403,
      maintenance_business: 403, old_token: 401, password_absent_from_browser_storage: true, native_brand: native});
    await accountAccess.logout(page); const previous = maint.token;
    for (const socket of sockets.splice(0)) socket.close(); await desktop.close();
    desktop = await launch(); page = await desktop.firstWindow({timeout: 120000});
    page.on('pageerror', error => errors.push({name: error.name})); await page.waitForURL(origin + '/');
    await accountAccess.login(page, accounts, 'BOSS');
    await read(previous, 'admin/skills', 401);
    const again = await accountAccess.bootstrap(origin, accounts, 'BOSS');
    const reopenedDashboard = await read(again.api_token, 'dashboard');
    const {refreshed_at: beforeReadAt, ...beforeDashboard} = dashboard;
    const {refreshed_at: afterReadAt, ...afterDashboard} = reopenedDashboard;
    assert.ok(beforeReadAt && afterReadAt); assert.deepEqual(afterDashboard, beforeDashboard);
    assert.equal(digest(fs.readFileSync(path.join(directory, 'accounts/accounts.sqlite'))), accountFileSha);
    const after = manifest(); assert.deepEqual(after.before_tables_sha256, before.before_tables_sha256); assert.deepEqual(errors, []);
    const credentials = Object.values(accounts).map(account => account.password);
    const audit = fs.readFileSync(path.join(directory, 'diagnostics/access.jsonl'), 'utf8');
    assert.ok(credentials.every(value => !audit.includes(value)));
    const accessCheck = JSON.parse(execFileSync(path.join(validation, '.venv/bin/python'), [path.join(validation, 'check_product_access.py'),
      '--application-directory', directory], {cwd: root, env: {...process.env, TMPDIR: path.join(validation, '.work/tmp')},
      timeout: 60000, maxBuffer: 1024 * 1024}).toString());
    assert.equal(accessCheck.model_invoked, false); assert.equal(accessCheck.business_write, false);
    await expect(page.getByLabel('账号', {exact: true})).toBeEnabled();
    assert.deepEqual(manifest().before_tables_sha256, before.before_tables_sha256);
    note('current_command_line_authentication_and_cross_role_access', {result: accessCheck});
    note('public_restart_credentials_and_business_data_continuity', {account_database_sha256: accountFileSha,
      business_tables_sha256: after.after_tables_sha256, initial_snapshot_sha256: after.initial_snapshot_sha256,
      previous_token: 401, renderer_errors: errors, password_absent_from_access_audit: true});
    save('PASS_PUBLIC_ACCOUNT_LOGIN_ROLES_BRANDING_AND_RESTART');
    console.log(JSON.stringify({status: 'PASS_PUBLIC_ACCOUNT_LOGIN_ROLES_BRANDING_AND_RESTART', evidence: output}));
  } finally {for (const socket of sockets) socket.close(); await desktop.close();}
}
process.on('uncaughtExceptionMonitor', error => {records.push({check: 'uncaught_failure', name: error.name}); save('FAILED_CHECK');});
check();
