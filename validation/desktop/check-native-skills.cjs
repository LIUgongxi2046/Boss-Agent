const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const {createHash, randomUUID} = require('node:crypto');
const {_electron: electron} = require('playwright');
const {expect} = require('@playwright/test');

const root = path.resolve(__dirname, '../..');
const validation = path.join(root, 'validation');
const runId = 'native-skills-' + randomUUID();
const directory = path.join(validation, '.work', runId);
const output = path.join(root, 'evidence/T11/w3-local-20261023', runId + '.json');
const ports = {business: 8971, webui: 8972, gateway: 18971};
const origin = 'http://127.0.0.1:8972';
const digest = value => createHash('sha256').update(value).digest('hex');
const inputs = ['validation/application.py', 'validation/product_skills.py', 'validation/product_runtime.py',
  'validation/role_channel.py', 'validation/boss_page_api.py', 'validation/boss_native_skills.py',
  'specs/agent-assets.json', 'specs/product-skills.openapi.yaml', 'app/webui/MaintainerSkills.tsx',
  'app/webui/BossDesktop.tsx', 'validation/desktop/check-native-skills.cjs',
  '.work/product/nanobot/nanobot/web/dist/asset-manifest.json'].map(file => ({path: file, sha256: digest(fs.readFileSync(path.join(root, file)))}));
const records = [];
function save(status) {fs.writeFileSync(output, JSON.stringify({status, run_id: runId, at: new Date().toISOString(), inputs, records, ports,
  application_directory: path.relative(root, directory), external_api_mode: 'SIMULATED_FIRST', model_requested: false,
  external_delivery_requested: false, model_quality_verified: false, private_body_recorded: false,
  visual_acceptance: 'NOT_RUN', full_A11_A19_accepted: false}, null, 2));}
function note(check, values) {records.push({check, ...values}); save('IN_PROGRESS');}
async function launch() {return electron.launch({args: [__dirname], cwd: validation, timeout: 60000,
  env: {...process.env, BOSS_VALIDATION_ROOT: validation, BOSS_PRODUCT_UI: '1', BOSS_APPLICATION_WORK_DIR: directory,
    BOSS_APPLICATION_PORTS: JSON.stringify(ports), BOSS_DESKTOP_TEST_WINDOW_HIDDEN: '1', TMPDIR: path.join(validation, '.work/tmp')}});}
async function check() {
  let desktop = await launch();
  const sockets = [];
  try {
    let page = await desktop.firstWindow({timeout: 120000});
    const errors = [];
    page.on('pageerror', error => errors.push({name: error.name}));
    await page.waitForURL(origin + '/');
    const access = JSON.parse(fs.readFileSync(path.join(directory, 'access.json')));
    async function login(role) {
      await page.getByRole('radio', {name: role === 'BOSS' ? /^老板本人/ : /^技术维护/}).check();
      await page.getByLabel('本机访问凭据', {exact: true}).fill(access[role]);
      await page.getByRole('button', {name: '继续认证', exact: true}).click();
      await page.locator('.boss-v6[data-role="' + role + '"]').waitFor();
    }
    async function boot(role) {
      const response = await fetch(origin + '/webui/bootstrap', {headers: {'X-Nanobot-Auth': access[role]}});
      assert.equal(response.status, 200); return response.json();
    }
    async function read(token, route, status = 200) {
      const response = await fetch(origin + '/api/boss/ui/' + route, {headers: {Authorization: 'Bearer ' + token}});
      assert.equal(response.status, status); if (status === 200) return response.json();
    }
    async function rpc(role) {
      const auth = await boot(role);
      const socket = new WebSocket(origin.replace('http:', 'ws:') + auth.ws_path + '?token=' + encodeURIComponent(auth.token));
      sockets.push(socket);
      await new Promise(resolve => socket.addEventListener('message', event => {if (JSON.parse(event.data).event === 'ready') resolve();}));
      return {token: auth.api_token, async update(payload) {
        const id = randomUUID();
        const result = new Promise(resolve => {
          const listener = event => {const frame = JSON.parse(event.data); if (frame.request_id === id) {socket.removeEventListener('message', listener); resolve(frame);}};
          socket.addEventListener('message', listener);
        });
        socket.send(JSON.stringify({type: 'webui_request', request_id: id, action: 'skill.update', payload}));
        return result;
      }};
    }
    async function businessDigest() {
      const hashes = {};
      for (const kind of ['task', 'outbox']) {
        const response = await fetch('http://127.0.0.1:8971/spaces/ui-check/objects/' + kind, {headers: {Authorization: 'Bearer ' + access.BOSS}});
        assert.equal(response.status, 200); hashes[kind] = digest(await response.text());
      }
      return hashes;
    }
    async function currentPage() {
      await page.goto(origin + '/?bossPage=A06', {waitUntil: 'networkidle'});
      await page.getByRole('region', {name: '方法 SOP03', exact: true}).waitFor();
    }
    async function change(enabled) {
      const method = page.getByRole('region', {name: '方法 SOP03', exact: true});
      await method.getByRole('button', {name: (enabled ? '启用方法 ' : '停用方法 ') + 'SOP03', exact: true}).click();
      const dialog = page.getByRole('dialog', {name: enabled ? '确认启用方法' : '确认停用方法', exact: true});
      await expect(dialog.getByRole('button', {name: '确认变更', exact: true})).toBeDisabled();
      await dialog.getByRole('checkbox', {name: '我确认本次方法状态变更。', exact: true}).check();
      await dialog.getByRole('button', {name: '确认变更', exact: true}).click();
      await dialog.waitFor({state: 'detached'});
      await method.getByText(enabled ? '已经启用' : '已经停用', {exact: true}).waitFor();
    }
    await login('MAINTAINER'); await currentPage();
    let maint = await rpc('MAINTAINER');
    const before = await businessDigest();
    const initial = await read(maint.token, 'admin/skills');
    assert.equal(initial.items.length, 13); assert.equal(initial.runtime_admission_ready, true);
    assert.deepEqual(initial.items.filter(item => item.context_eligible).map(item => item.sop_id), ['SOP03']);
    const method = initial.items.find(item => item.sop_id === 'SOP03');
    for (const item of initial.items) assert.equal(digest(fs.readFileSync(path.join(directory, 'workspace/skills', item.name, 'SKILL.md'))), item.content_sha256);
    note('a06_actual_native_files_versions_and_registered_tool_dependencies', {status: initial});
    await page.context().setOffline(true);
    await page.getByRole('button', {name: '读取当前方法状态', exact: true}).click();
    await page.getByRole('alert').filter({hasText: 'Failed to fetch'}).waitFor();
    assert.equal(await page.getByRole('region', {name: '方法 SOP03', exact: true}).count(), 0);
    await page.context().setOffline(false);
    await page.getByRole('button', {name: '读取当前方法状态', exact: true}).click();
    await page.getByRole('region', {name: '方法 SOP03', exact: true}).waitFor();
    note('actual_offline_clears_old_methods_and_recovery_reads_current_state', {recovered: true});
    await read(maint.token, 'admin/skills?namespace=ui-check', 400);
    const invalid = [
      [{name: method.name, enabled: 'false', expected_content_sha256: method.content_sha256}, 400],
      [{name: 'read_assignment', enabled: true, expected_content_sha256: method.content_sha256}, 400],
      [{name: method.name, enabled: false, expected_content_sha256: initial.items[0].content_sha256}, 409],
      [{name: initial.items[0].name, enabled: true, expected_content_sha256: initial.items[0].content_sha256}, 409],
    ];
    for (const [payload, status] of invalid) {const result = await maint.update(payload); assert.equal(result.ok, false); assert.equal(result.error.status, status);}
    assert.equal((await read(maint.token, 'admin/skills')).native_configuration_sha256, initial.native_configuration_sha256);
    const raw = await fetch(origin + '/api/webui/skills/update?name=' + method.name + '&enabled=false', {headers: {Authorization: 'Bearer ' + maint.token}});
    assert.equal(raw.status, 403);
    await change(false);
    const disabled = await read(maint.token, 'admin/skills');
    assert.equal(disabled.items.find(item => item.sop_id === 'SOP03').enabled, false);
    assert.equal(disabled.items.find(item => item.sop_id === 'SOP03').context_eligible, false);
    assert.equal(disabled.runtime_admission_ready, true);
    assert.notEqual(disabled.native_configuration_sha256, initial.native_configuration_sha256);
    note('gui_disable_persists_native_state_and_preserves_model_admission', {status: disabled,
      invalid_inputs: [400, 409], raw_native_write: 403, business_sha256: before});
    for (const zoom of [1, 2]) {
      await desktop.evaluate(({BrowserWindow}, value) => BrowserWindow.getAllWindows()[0].webContents.setZoomFactor(value), zoom);
      for (const size of [[1024, 768], [1280, 800], [1440, 1024]]) {
        await desktop.evaluate(({BrowserWindow}, value) => BrowserWindow.getAllWindows()[0].setContentSize(...value), size);
        const overflow = await page.evaluate(() => document.documentElement.scrollWidth > innerWidth + 1);
        assert.equal(overflow, false); note('a06_viewport', {zoom, size, horizontal_overflow: overflow});
      }
    }
    await desktop.evaluate(({BrowserWindow}) => BrowserWindow.getAllWindows()[0].webContents.setZoomFactor(1));
    await page.getByTitle('退出当前身份', {exact: true}).click();
    await page.getByLabel('本机访问凭据', {exact: true}).waitFor();
    await read(maint.token, 'admin/skills', 401);
    assert.equal(await page.getByRole('region', {name: '秘书方法技术维护', exact: true}).count(), 0);
    await login('BOSS'); const boss = await rpc('BOSS');
    await read(boss.token, 'admin/skills', 403);
    const rejected = await boss.update({name: method.name, enabled: true, expected_content_sha256: method.content_sha256});
    assert.equal(rejected.ok, false); assert.equal(rejected.error.status, 403);
    await page.getByTitle('退出当前身份', {exact: true}).click(); await page.getByLabel('本机访问凭据', {exact: true}).waitFor();
    await desktop.close(); desktop = await launch();
    page = await desktop.firstWindow({timeout: 120000}); page.on('pageerror', error => errors.push({name: error.name}));
    await page.waitForURL(origin + '/'); await login('MAINTAINER'); await currentPage();
    maint = await rpc('MAINTAINER');
    const restarted = await read(maint.token, 'admin/skills');
    assert.equal(restarted.items.find(item => item.sop_id === 'SOP03').enabled, false);
    await change(true);
    const enabled = await read(maint.token, 'admin/skills');
    assert.equal(enabled.items.find(item => item.sop_id === 'SOP03').context_eligible, true);
    assert.equal(enabled.runtime_admission_ready, true);
    assert.deepEqual(await businessDigest(), before); assert.deepEqual(errors, []);
    note('service_restart_gui_enable_role_boundaries_and_zero_business_mutation', {status: enabled,
      boss_read_and_update: 403, previous_token: 401, renderer_errors: errors, business_sha256: before});
    save('PASS_PUBLIC_A06_NATIVE_FILES_ENABLE_DISABLE_AND_RESTART');
    console.log(JSON.stringify({status: 'PASS_PUBLIC_A06_NATIVE_FILES_ENABLE_DISABLE_AND_RESTART', evidence: output}));
  } finally {for (const socket of sockets) socket.close(); await desktop.close();}
}
process.on('uncaughtExceptionMonitor', error => {records.push({check: 'uncaught_failure', name: error.name}); save('FAILED_CHECK');});
check();
