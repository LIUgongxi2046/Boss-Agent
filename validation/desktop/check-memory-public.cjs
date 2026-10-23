const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const {createHash, randomUUID} = require('node:crypto');
const {_electron: electron} = require('playwright');
const {expect} = require('@playwright/test');

const root = path.resolve(__dirname, '../..');
const validation = path.join(root, 'validation');
const reference = 'runtime-application-c6e06b70-5c16-4d4c-bbad-b76aaddf70e1';
const originalPath = path.join(root, 'evidence/T11/w3-local-20261023', reference + '.json');
const original = JSON.parse(fs.readFileSync(originalPath));
assert.equal(original.status, 'PASS_PUBLIC_RUNTIME_CONFIGURATION_AND_A15_TASK_REFERENCE');
const applicationDirectory = path.join(validation, '.work', reference);
const access = JSON.parse(fs.readFileSync(path.join(applicationDirectory, 'access.json')));
const runId = 'memory-public-' + randomUUID();
const output = path.join(root, 'evidence/T11/w3-local-20261023', runId + '.json');
const ports = {business: 8971, webui: 8972, gateway: 18971};
const origin = 'http://127.0.0.1:' + ports.webui;
const records = [];
const inputs = ['validation/application.py', 'validation/product_runtime.py', 'validation/boss_page_api.py',
  'validation/boss_admin_config.py', 'validation/boss_memory_runtime.py', 'validation/boss_memory.py',
  'app/webui/BossDesktop.tsx', 'app/webui/MaintainerMemoryStatus.tsx', 'app/webui/BossWorkspaceView.tsx',
  'app/webui/MaintainerRuntimeRecords.tsx', 'validation/desktop/check-memory-public.cjs',
  '.work/product/nanobot/nanobot/web/dist/asset-manifest.json'].map(file => ({path: file,
    sha256: createHash('sha256').update(fs.readFileSync(path.join(root, file))).digest('hex')}));
function note(check, values) {records.push({check, ...values}); save('IN_PROGRESS');}
function save(status) {fs.writeFileSync(output, JSON.stringify({status, run_id: runId, at: new Date().toISOString(),
  application_directory: path.relative(root, applicationDirectory), ports, inputs, records,
  previous_evidence: {path: path.relative(root, originalPath), sha256: createHash('sha256').update(fs.readFileSync(originalPath)).digest('hex')},
  model_service: 'api.deepseek.com', model_id: 'deepseek-flash', source_type: 'SIMULATED',
  cost_total: null, private_body_recorded: false, visual_acceptance: 'NOT_RUN', full_A11_A15_accepted: false}, null, 2));}
async function launch() {return electron.launch({args: [__dirname], cwd: validation, timeout: 60000,
  env: {...process.env, BOSS_VALIDATION_ROOT: validation, BOSS_PRODUCT_UI: '1',
    BOSS_APPLICATION_WORK_DIR: applicationDirectory, BOSS_APPLICATION_PORTS: JSON.stringify(ports),
    BOSS_DESKTOP_TEST_WINDOW_HIDDEN: '1', TMPDIR: path.join(validation, '.work/tmp')}});}
async function boot(role) {
  const response = await fetch(origin + '/webui/bootstrap', {headers: {'X-Nanobot-Auth': access[role]}});
  assert.equal(response.status, 200); return response.json();
}
async function read(token, route, status = 200) {
  const response = await fetch(origin + '/api/boss/ui/' + route, {headers: {Authorization: 'Bearer ' + token}});
  assert.equal(response.status, status);
  if (status !== 200) return;
  return response.json();
}
async function check() {
  let desktop = await launch();
  try {
    let page = await desktop.firstWindow({timeout: 120000});
    const errors = [];
    const ended = [];
    function observe() {
      page.on('pageerror', error => errors.push({name: error.name}));
      page.on('websocket', socket => socket.on('framereceived', event => {
        const frame = JSON.parse(event.payload.toString());
        if (frame.event === 'turn_end') ended.push({turn_id: frame.turn_id, outcome: frame.outcome, failure_kind: frame.failure_kind});
      }));
    }
    observe();
    async function login(role) {
      await page.getByRole('radio', {name: role === 'BOSS' ? /^老板本人/ : /^技术维护/}).check();
      await page.getByLabel('本机访问凭据', {exact: true}).fill(access[role]);
      await page.getByRole('button', {name: '继续认证', exact: true}).click();
      await page.locator('.boss-v6[data-role="' + role + '"]').waitFor();
    }
    async function logout(token) {
      await page.getByTitle('退出当前身份', {exact: true}).click();
      await page.getByLabel('本机访问凭据', {exact: true}).waitFor();
      await read(token, 'runtime-records', 401);
      assert.equal(await page.getByRole('region', {name: '当前记忆确认', exact: true}).count(), 0);
    }
    async function memoryPage() {
      await page.goto(origin + '/?bossPage=A12', {waitUntil: 'networkidle'});
      await page.getByRole('button', {name: '检查技术状态', exact: true}).click();
      await page.getByRole('region', {name: '当前记忆确认', exact: true}).getByText('memory-1', {exact: true}).waitFor();
    }
    await page.waitForURL(origin + '/');
    await login('MAINTAINER');
    let maint = await boot('MAINTAINER');
    const before = await read(maint.api_token, 'admin/memory-status');
    assert.equal(before.memory.version, '1'); assert.equal(before.memory.confirmation_state, 'CONFIRMED');
    assert.equal(before.future_context_eligible, true); assert.equal(before.context_selection_count, 2);
    assert.equal(before.latest_context_selection.eligible, true);
    assert.equal(before.private_body_available_here, false);
    await memoryPage();
    await page.getByRole('region', {name: '当前记忆确认', exact: true}).getByText('符合当前确认条件', {exact: true}).waitFor();
    await page.getByRole('button', {name: '查看关联运行记录', exact: true}).click();
    const query = page.getByRole('region', {name: '运行记录查询', exact: true});
    await expect(query.getByLabel('run_id', {exact: true})).toHaveValue(before.latest_context_selection.run_id);
    await query.getByRole('button', {name: '查询记录', exact: true}).click();
    await page.getByRole('button', {name: '打开记录 ' + before.latest_context_selection.run_id, exact: true}).click();
    note('a12_current_confirmation_and_a15_actual_run_navigation', {status: before});
    await read(maint.api_token, 'admin/memory-status?namespace=ui-check', 400);
    await memoryPage();
    await page.context().setOffline(true);
    await page.getByRole('button', {name: '检查技术状态', exact: true}).click();
    await page.getByRole('alert').filter({hasText: 'Failed to fetch'}).waitFor();
    await expect(page.getByRole('region', {name: '当前记忆确认', exact: true})).not.toContainText('memory-1');
    await page.context().setOffline(false);
    await page.getByRole('button', {name: '检查技术状态', exact: true}).click();
    await page.getByRole('region', {name: '当前记忆确认', exact: true}).getByText('memory-1', {exact: true}).waitFor();
    note('offline_clears_technical_data_and_recovery_reloads_current_state', {scope_query: 400});
    await logout(maint.api_token);
    await login('BOSS');
    const boss = await boot('BOSS');
    await read(boss.api_token, 'admin/memory-status', 403);
    await page.goto(origin + '/?bossPage=F13', {waitUntil: 'networkidle'});
    await page.getByRole('button', {name: '本人确认停止采用', exact: true}).click();
    const dialog = page.getByRole('dialog', {name: '本人确认删除长期要求', exact: true});
    await dialog.getByRole('checkbox', {name: '我确认本次具体对象、内容与执行后果。', exact: true}).check();
    await dialog.getByRole('button', {name: '确认并提交', exact: true}).click();
    await dialog.waitFor({state: 'detached'});
    await expect(page.getByRole('button', {name: '本人确认停止采用', exact: true})).toBeDisabled();
    await logout(boss.api_token);
    await login('MAINTAINER'); maint = await boot('MAINTAINER');
    await memoryPage();
    const deleted = await read(maint.api_token, 'admin/memory-status');
    assert.equal(deleted.memory.version, '2'); assert.equal(deleted.memory.confirmation_state, 'DELETED');
    assert.equal(deleted.future_context_eligible, false); assert.equal(deleted.next_context_memory_version, null);
    assert.equal(deleted.deletion_scopes.current_memory_content, 'CLEARED');
    assert.equal(deleted.deletion_scopes.initial_approved_source, 'RETAINED');
    for (const field of ['loaded_sessions', 'backups', 'physical_erasure']) assert.equal(deleted.deletion_scopes[field], 'NOT_VERIFIED');
    assert.equal(deleted.latest_context_selection.eligible, true);
    assert.equal(deleted.latest_context_selection.matches_current_memory_version, false);
    note('gui_owner_deletion_preserves_historical_observation_and_stops_future_eligibility', {status: deleted});
    await logout(maint.api_token);
    await login('BOSS'); const nextBoss = await boot('BOSS');
    await page.goto(origin + '/?bossPage=F01', {waitUntil: 'networkidle'});
    await page.getByLabel('输入本次工作需求', {exact: true}).fill('只读调用query_metrics比较region-1的product-1、product-2，2026-10-01至2026-10-10与2026-09-01至2026-09-10，CNY、EXTERNAL_SALES、definition_version=1，查询收入和毛利率并调用read_evidence读取finance-note依据。缺少原因明确说明未知，不创建交办或发送消息。');
    await page.getByRole('button', {name: '提交需求', exact: true}).click();
    await expect.poll(() => ended.length, {timeout: 150000, intervals: [500]}).toBe(1);
    assert.equal(ended[0].failure_kind ?? null, null);
    const runs = await read(nextBoss.api_token, 'runtime-records');
    const current = runs.runs.find(run => !original.records.some(record => record.record?.run_id === run.run_id));
    assert.ok(current); assert.equal(current.status, 'SUCCEEDED');
    assert.equal(current.memory_reference.version, '2'); assert.equal(current.memory_reference.eligible, false);
    assert.equal(current.memory_reference.confirmation_authority_checked, true);
    assert.ok(current.tool_results.some(tool => tool.tool_id === 'query_metrics'));
    assert.ok(current.tool_results.some(tool => tool.tool_id === 'read_evidence'));
    assert.ok(current.model_requests.length > 0 && current.model_requests.every(request => request.http_status === 200));
    note('next_home_task_records_actual_deleted_memory_version', {record: current, turn_end: ended[0]});
    await page.goto(origin + '/?bossPage=F01', {waitUntil: 'networkidle'});
    await logout(nextBoss.api_token);
    await login('MAINTAINER'); maint = await boot('MAINTAINER');
    await memoryPage();
    const after = await read(maint.api_token, 'admin/memory-status');
    assert.equal(after.context_selection_count, 3); assert.equal(after.latest_context_selection.run_id, current.run_id);
    assert.equal(after.latest_context_selection.memory_version, '2'); assert.equal(after.latest_context_selection.eligible, false);
    assert.equal(after.latest_context_selection.model_completion_observed, true);
    assert.equal(after.model_adoption_verified, false);
    await page.getByText('该次停止采用', {exact: true}).waitFor();
    for (const zoom of [1, 2]) {
      await desktop.evaluate(({BrowserWindow}, value) => BrowserWindow.getAllWindows()[0].webContents.setZoomFactor(value), zoom);
      for (const size of [[1024, 768], [1280, 800], [1440, 1024]]) {
        await desktop.evaluate(({BrowserWindow}, value) => BrowserWindow.getAllWindows()[0].setContentSize(...value), size);
        const overflow = await page.evaluate(() => document.documentElement.scrollWidth > innerWidth + 1);
        assert.equal(overflow, false); note('a12_viewport', {zoom, size, horizontal_overflow: overflow});
      }
    }
    assert.deepEqual(errors, []); note('a12_actual_next_context_selection', {status: after, renderer_errors: errors});
    await logout(maint.api_token); await desktop.close(); desktop = await launch();
    page = await desktop.firstWindow({timeout: 120000}); observe();
    await page.waitForURL(origin + '/'); await login('MAINTAINER');
    maint = await boot('MAINTAINER'); await memoryPage();
    const reopened = await read(maint.api_token, 'admin/memory-status');
    assert.equal(reopened.memory.version, '2'); assert.equal(reopened.memory.confirmation_state, 'DELETED');
    assert.equal(reopened.latest_context_selection.run_id, current.run_id);
    assert.equal(reopened.context_selection_count, 3); assert.equal(reopened.future_context_eligible, false);
    note('logout_and_service_restart_preserve_deleted_state_and_actual_selection', {version: '2', run_id: current.run_id, prior_token: 401});
    save('PASS_PUBLIC_A12_OWNER_DELETION_AND_NEXT_ACTUAL_MODEL_CONTEXT');
    console.log(JSON.stringify({status: 'PASS_PUBLIC_A12_OWNER_DELETION_AND_NEXT_ACTUAL_MODEL_CONTEXT', evidence: output}));
  } finally {await desktop.close();}
}
process.on('uncaughtExceptionMonitor', error => {records.push({check: 'uncaught_failure', name: error.name}); save('FAILED_CHECK');});
check();
