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
const runId = 'sop-versions-' + randomUUID();
const directory = path.join(validation, '.work', runId);
const accounts = accountAccess.provision(directory);
const output = path.join(root, 'evidence/T11/w3-local-20261023', runId + '.json');
const ports = {business: 8971, webui: 8972, gateway: 18971};
const origin = 'http://127.0.0.1:8972';
const digest = value => createHash('sha256').update(value).digest('hex');
const records = [];
const inputs = ['validation/application.py', 'validation/product_skills.py', 'validation/product_runtime.py',
  'validation/role_channel.py', 'validation/boss_page_api.py', 'validation/boss_command_api.py',
  'validation/boss_skill_drafts.py', 'validation/boss_native_skills.py', 'validation/sop_recovery_check.py',
  'specs/product-skills.openapi.yaml', 'app/webui/MaintainerSkillVersions.tsx', 'app/webui/BossDesktop.tsx',
  'app/webui/BossSectorView.tsx', 'validation/desktop/check-sop-versions.cjs',
  '.work/product/nanobot/nanobot/web/dist/asset-manifest.json'].map(file => ({path: file, sha256: digest(fs.readFileSync(path.join(root, file)))}));
function save(status) {fs.writeFileSync(output, JSON.stringify({status, run_id: runId, at: new Date().toISOString(),
  application_directory: path.relative(root, directory), inputs, records, ports, external_api_mode: 'SIMULATED_FIRST',
  model_requested: false, external_delivery_requested: false, model_quality_verified: false,
  method_body_recorded: false, visual_acceptance: 'NOT_RUN', full_A06_A11_A19_accepted: false}, null, 2));}
function note(check, values) {records.push({check, ...values}); save('IN_PROGRESS');}
function compact(value) {return {sop_id: value.sop_id,
  active: {version: value.active.version, enabled: value.active.enabled, content_sha256: value.active.content_sha256},
  draft: value.draft && {draft_version: value.draft.draft_version, method_version: value.draft.method_version,
    state: value.draft.state, validation_status: value.draft.validation_status, content_sha256: value.draft.content_sha256},
  history: value.history, pending_activations: value.pending_activations, global_pending_activations: value.global_pending_activations};}
async function launch() {return electron.launch({args: [__dirname], cwd: validation, timeout: 60000,
  env: {...process.env, BOSS_VALIDATION_ROOT: validation, BOSS_PRODUCT_UI: '1', BOSS_APPLICATION_WORK_DIR: directory,
    BOSS_APPLICATION_PORTS: JSON.stringify(ports), BOSS_DESKTOP_TEST_WINDOW_HIDDEN: '1', TMPDIR: path.join(validation, '.work/tmp')}});}
async function check() {
  let desktop = null, page, maint;
  const errors = [], sockets = [], commands = [];
  async function start() {
    desktop = await launch(); page = await desktop.firstWindow({timeout: 120000});
    page.on('pageerror', error => errors.push({name: error.name}));
    page.on('websocket', socket => socket.on('framesent', event => {
      const frame = JSON.parse(String(event.payload));
      if (frame.type === 'webui_request' && frame.action.startsWith('boss.sop.')) commands.push(frame);
    }));
    await page.waitForURL(origin + '/');
  }
  async function stop() {
    for (const socket of sockets.splice(0)) socket.close();
    if (desktop) {await desktop.close(); desktop = null;}
  }
  async function login(role) {
    await accountAccess.login(page, accounts, role);
  }
  async function logout() {
    await accountAccess.logout(page);
  }
  async function rpc(role) {
    const auth = await accountAccess.bootstrap(origin, accounts, role);
    const socket = new WebSocket(origin.replace('http:', 'ws:') + auth.ws_path + '?token=' + encodeURIComponent(auth.token));
    sockets.push(socket);
    await new Promise(resolve => socket.addEventListener('message', event => {if (JSON.parse(event.data).event === 'ready') resolve();}));
    return {token: auth.api_token, async command(action, payload) {
      const id = randomUUID();
      const result = new Promise(resolve => {
        const listener = event => {const frame = JSON.parse(event.data); if (frame.request_id === id) {socket.removeEventListener('message', listener); resolve(frame);}};
        socket.addEventListener('message', listener);
      });
      socket.send(JSON.stringify({type: 'webui_request', request_id: id, action, payload})); return result;
    }};
  }
  async function read(route = 'admin/sop-method?sop_id=SOP03', status = 200, token = maint.token) {
    const response = await fetch(origin + '/api/boss/ui/' + route, {headers: {Authorization: 'Bearer ' + token}});
    assert.equal(response.status, status); return status === 200 ? response.json() : null;
  }
  async function open() {
    await page.goto(origin + '/?bossPage=A06&bossSop=SOP03', {waitUntil: 'networkidle'});
    await page.getByRole('button', {name: '读取当前方法', exact: true}).waitFor();
  }
  async function load() {
    await page.getByRole('button', {name: '读取当前方法', exact: true}).click();
    await page.getByRole('table', {name: '已保存方法步骤表', exact: true}).waitFor();
    await expect(page.getByLabel('新方法版本', {exact: true})).toBeEnabled();
  }
  async function commit(button, title) {
    await page.getByRole('button', {name: button, exact: true}).click();
    const dialog = page.getByRole('dialog', {name: title, exact: true});
    await expect(dialog.getByRole('button', {name: '确认执行技术操作', exact: true})).toBeDisabled();
    await dialog.getByRole('checkbox', {name: '已核查当前方法、版本和操作范围', exact: true}).check();
    await dialog.getByRole('button', {name: '确认执行技术操作', exact: true}).click();
    await dialog.waitFor({state: 'detached'});
    await expect(page.getByLabel('新方法版本', {exact: true})).toBeEnabled();
  }
  async function draft(version, noteText) {
    await page.getByLabel('新方法版本', {exact: true}).fill(version);
    await page.getByLabel('变更说明', {exact: true}).fill(noteText);
    await commit('保存方法草稿', '保存方法草稿');
    assert.equal((await read()).draft.method_version, version);
    await commit('校验当前草稿', '校验当前方法引用');
    const checked = await read(); assert.equal(checked.draft.validation_status, 'VALIDATED_STATIC_ONLY'); return checked;
  }
  function recovery(action) {
    return JSON.parse(execFileSync(path.join(validation, '.venv/bin/python'), [path.join(validation, 'sop_recovery_check.py'),
      '--application-directory', directory, '--action', action], {cwd: root, env: {...process.env,
        TMPDIR: path.join(validation, '.work/tmp')}, timeout: 60000, maxBuffer: 1024 * 1024}).toString());
  }
  try {
    await start(); await login('MAINTAINER'); maint = await rpc('MAINTAINER'); await open();
    await expect(page.getByLabel('新方法版本', {exact: true})).toBeDisabled();
    assert.equal(await page.getByLabel(/^方法正文/).inputValue(), '');
    await load(); const initial = await read(); assert.equal(initial.active.version, '0.1.0');
    assert.equal(await page.getByLabel(/^方法正文/).inputValue(), initial.active.body);
    assert.equal((await read('admin/runtime-configuration')).admission_ready, true);
    await page.getByLabel('新方法版本', {exact: true}).fill('0.1.1');
    await page.getByLabel('变更说明', {exact: true}).fill(initial.active.description);
    await page.getByRole('button', {name: '保存方法草稿', exact: true}).click();
    const canceled = page.getByRole('dialog', {name: '保存方法草稿', exact: true});
    await canceled.getByRole('button', {name: '取消未提交操作', exact: true}).click();
    assert.equal((await read()).draft, null);
    await page.getByRole('button', {name: '查看实际步骤记录', exact: true}).click();
    const navigation = page.getByRole('dialog', {name: '未保存修改（D06）', exact: true});
    await navigation.getByRole('button', {name: '返回继续编辑', exact: true}).click();
    await expect(page.getByLabel('新方法版本', {exact: true})).toHaveValue('0.1.1');
    await page.getByLabel('选择方法', {exact: true}).selectOption('SOP01');
    await page.getByRole('dialog', {name: '取消未保存修改', exact: true}).getByRole('button', {name: '继续编辑', exact: true}).click();
    await expect(page.getByLabel('选择方法', {exact: true})).toHaveValue('SOP03');
    await draft('0.1.1', initial.active.description);
    assert.equal((await read()).active.content_sha256, initial.active.content_sha256);
    const saveCommand = commands.find(item => item.action === 'boss.sop.save'); assert.ok(saveCommand);
    const receipt = await read('admin/sop-operation-status?action=save&client_request_id=' + saveCommand.payload.client_request_id);
    assert.equal(receipt.outcome, 'RECORDED'); assert.equal(receipt.result.method_version, '0.1.1');
    const replay = await maint.command(saveCommand.action, saveCommand.payload); assert.equal(replay.ok, true);
    await commit('启用当前草稿', '启用当前已校验方法');
    let current = await read(); assert.equal(current.active.version, '0.1.1');
    assert.equal(digest(fs.readFileSync(path.join(directory, 'workspace/skills/boss-sop03/SKILL.md'))), current.active.content_sha256);
    const history = current.history.find(item => item.method_version === '0.1.0'); assert.ok(history);
    await page.getByLabel('选择历史版本', {exact: true}).selectOption(history.history_id);
    await page.getByRole('button', {name: '查看历史正文', exact: true}).click();
    await expect(page.getByRole('article', {name: '历史方法正文', exact: true}).locator('pre')).toHaveText(initial.active.body);
    await page.getByLabel('新方法版本', {exact: true}).fill('0.1.2');
    await page.getByLabel('变更说明', {exact: true}).fill(initial.active.description);
    await commit('恢复历史为新草稿', '恢复历史为新草稿');
    current = await read(); assert.equal(current.active.version, '0.1.1'); assert.equal(current.draft.restored_from, history.history_id);
    assert.equal(current.draft.body, initial.active.body);
    await commit('校验当前草稿', '校验当前方法引用'); await commit('启用当前草稿', '启用当前已校验方法');
    assert.equal((await read()).active.version, '0.1.2');
    await commit('停用当前方法', '停用当前方法'); assert.equal((await read()).active.enabled, false);
    assert.equal((await read('admin/runtime-configuration')).admission_ready, true);
    await commit('启用当前方法', '启用当前原生方法'); assert.equal((await read()).active.enabled, true);
    note('public_editor_native_save_validate_activate_restore_enable_and_receipts', {initial: compact(initial), current: compact(await read()),
      original_save_receipt: {action: receipt.action, client_request_id: receipt.client_request_id, outcome: receipt.outcome},
      canceled_unsubmitted_preserved: true, dirty_navigation_return_preserved: true, method_switch_return_preserved: true});
    await page.getByRole('button', {name: '查看实际步骤记录', exact: true}).click();
    await page.getByText(/^方法上下文：SOP03。当前正式记录没有方法编号筛选/).waitFor();
    assert.equal(new URL(page.url()).searchParams.get('bossSop'), 'SOP03');
    await open(); await load();
    await page.context().setOffline(true);
    await page.getByRole('button', {name: '读取当前方法', exact: true}).click();
    await page.getByRole('alert').filter({hasText: 'Failed to fetch'}).waitFor();
    assert.equal(await page.getByRole('table', {name: '已保存方法步骤表', exact: true}).count(), 0);
    assert.equal(await page.getByLabel(/^方法正文/).inputValue(), '');
    await page.context().setOffline(false); await load();
    await read('admin/sop-method?sop_id=SOP03&namespace=ui-check', 400);
    await read('admin/sop-method?sop_id=SOP03&sop_id=SOP01', 400);
    const rejectedPrepare = await maint.command('boss.sop.prepare', {sop_id: 'SOP03'});
    assert.equal(rejectedPrepare.ok, false); assert.equal(rejectedPrepare.error.status, 404);
    const rejectedScope = await maint.command('boss.sop.save', {...saveCommand.payload, namespace: 'ui-check'});
    assert.equal(rejectedScope.ok, false); assert.equal(rejectedScope.error.status, 400);
    for (const zoom of [1, 2]) {
      await desktop.evaluate(({BrowserWindow}, value) => BrowserWindow.getAllWindows()[0].webContents.setZoomFactor(value), zoom);
      for (const size of [[1024, 768], [1280, 800], [1440, 1024]]) {
        await desktop.evaluate(({BrowserWindow}, value) => BrowserWindow.getAllWindows()[0].setContentSize(...value), size);
        const overflow = await page.evaluate(() => document.documentElement.scrollWidth > innerWidth + 1);
        assert.equal(overflow, false); note('a06_viewport', {zoom, size, horizontal_overflow: overflow});
      }
    }
    await desktop.evaluate(({BrowserWindow}) => BrowserWindow.getAllWindows()[0].webContents.setZoomFactor(1));
    await draft('0.1.3', initial.active.description); await logout(); await stop();
    const prepared = recovery('prepare'); assert.equal(prepared.status, 'ACTUAL_VALIDATED_METHOD_PREPARED');
    await start(); await login('MAINTAINER'); maint = await rpc('MAINTAINER'); await open(); await load();
    current = await read(); assert.equal(current.active.version, '0.1.2'); assert.equal(current.pending_activations.length, 1);
    assert.equal((await read('admin/runtime-configuration')).admission_ready, false);
    const originalActivation = current.pending_activations[0].client_request_id;
    const preparedReceipt = await read('admin/sop-operation-status?action=activate&client_request_id=' + originalActivation);
    assert.equal(preparedReceipt.outcome, 'PREPARED');
    const blocked = await maint.command('skill.update', {name: current.active.name, enabled: false, expected_content_sha256: current.active.content_sha256});
    assert.equal(blocked.ok, false); assert.equal(blocked.error.status, 409);
    await page.getByLabel('选择方法', {exact: true}).selectOption('SOP01'); await load();
    await page.getByText('SOP03 存在待恢复操作，当前全部新上下文暂停采用。', {exact: true}).waitFor();
    await page.getByRole('button', {name: '查看 SOP03 待恢复操作', exact: true}).click();
    await expect(page.getByLabel('选择方法', {exact: true})).toHaveValue('SOP03');
    await commit('继续原启用操作', '继续原启用操作');
    current = await read(); assert.equal(current.active.version, '0.1.3'); assert.equal(current.pending_activations.length, 0);
    assert.equal((await read('admin/runtime-configuration')).admission_ready, true);
    const completedReceipt = await read('admin/sop-operation-status?action=activate&client_request_id=' + originalActivation);
    assert.equal(completedReceipt.outcome, 'RECORDED'); assert.equal(completedReceipt.result.method_version, '0.1.3');
    note('actual_prepared_journal_restart_and_public_recover', {prepared, prepared_receipt: {outcome: preparedReceipt.outcome,
      client_request_id: originalActivation}, completed_receipt: completedReceipt, current: compact(current), legacy_update_blocked: 409});
    await draft('0.1.4', initial.active.description); await logout(); await stop(); const canceledPreparation = recovery('prepare');
    await start(); await login('MAINTAINER'); maint = await rpc('MAINTAINER'); await open(); await load();
    await commit('取消原启用', '取消原启用并恢复此前方法');
    current = await read(); assert.equal(current.active.version, '0.1.3'); assert.equal(current.active.enabled, true);
    assert.equal(current.pending_activations.length, 0); assert.equal(current.draft.state, 'DRAFT');
    assert.equal(current.draft.method_version, '0.1.4');
    assert.equal((await read('admin/runtime-configuration')).admission_ready, true);
    note('actual_prepared_journal_restart_and_public_cancel', {prepared: canceledPreparation, current: compact(current)});
    const previous = maint.token;
    await logout();
    await read('admin/sop-method?sop_id=SOP03', 401, previous);
    assert.equal(await page.getByLabel(/^方法正文/).count(), 0);
    await login('BOSS'); const boss = await rpc('BOSS');
    await read('admin/sop-method?sop_id=SOP03', 403, boss.token);
    const forbidden = await boss.command('boss.sop.save', saveCommand.payload);
    assert.equal(forbidden.ok, false); assert.equal(forbidden.error.status, 403);
    assert.deepEqual(errors, []); await stop(); const inspected = recovery('inspect');
    assert.equal(inspected.status, 'ACTUAL_NATIVE_CONTEXT_READ_ONLY');
    assert.equal(inspected.result[0].version, '0.1.3');
    note('role_boundaries_logout_native_context_and_zero_business_mutation', {old_token: 401, boss_read_and_write: 403,
      renderer_errors: errors, native_context: inspected, gui_operations: commands.map(frame => ({action: frame.action,
        request_id: frame.request_id, client_request_id: frame.payload.client_request_id}))});
    save('PASS_PUBLIC_SOP_VERSIONS_HISTORY_PREPARED_RECOVERY_AND_NATIVE_CONTEXT');
    console.log(JSON.stringify({status: 'PASS_PUBLIC_SOP_VERSIONS_HISTORY_PREPARED_RECOVERY_AND_NATIVE_CONTEXT', evidence: output}));
  } finally {await stop();}
}
process.on('uncaughtExceptionMonitor', error => {records.push({check: 'uncaught_failure', name: error.name}); save('FAILED_CHECK');});
check();
