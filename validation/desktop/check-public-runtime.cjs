const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const { createHash, randomUUID } = require('node:crypto');
const { _electron: electron } = require('playwright');
const { expect } = require('@playwright/test');

const root = path.resolve(__dirname, '../..');
const validation = path.join(root, 'validation');
const runId = 'runtime-application-' + randomUUID();
const applicationDirectory = path.join(validation, '.work', runId);
const ports = {business: 8971, webui: 8972, gateway: 18971};
const origin = 'http://127.0.0.1:' + ports.webui;
const output = path.join(root, 'evidence/T11/w3-local-20261023', runId + '.json');
const records = [];
const inputs = ['validation/application.py', 'validation/product_runtime.py', 'validation/role_channel.py',
  'validation/boss_command_api.py', 'validation/boss_page_api.py', 'validation/boss_runtime_records.py',
  'validation/boss_memory_runtime.py', 'validation/connection.py', 'validation/controls.py', 'validation/business.py',
  'app/webui/BossDesktop.tsx', 'app/webui/ProductRuntimeConfiguration.tsx', 'app/webui/MaintainerRuntimeRecords.tsx',
  'app/webui/RuntimeTaskTechnicalView.tsx', 'validation/desktop/check-public-runtime.cjs',
  '.work/product/nanobot/nanobot/web/dist/asset-manifest.json'].map(file => ({path: file,
    sha256: createHash('sha256').update(fs.readFileSync(path.join(root, file))).digest('hex')}));
function save(status) {
  fs.writeFileSync(output, JSON.stringify({status, run_id: runId, at: new Date().toISOString(), inputs, ports, records,
    model_service: 'api.deepseek.com', model_id: 'deepseek-flash', source_type: 'SIMULATED',
    cost_total: null, private_body_recorded: false, visual_acceptance: 'NOT_RUN', full_A11_A16_accepted: false}, null, 2));
}
function note(record) {records.push(record); save('IN_PROGRESS');}
async function launch() {
  return electron.launch({args: [__dirname], cwd: validation, timeout: 60000,
    env: {...process.env, BOSS_VALIDATION_ROOT: validation, BOSS_PRODUCT_UI: '1',
      BOSS_APPLICATION_WORK_DIR: applicationDirectory, BOSS_APPLICATION_PORTS: JSON.stringify(ports),
      BOSS_DESKTOP_TEST_WINDOW_HIDDEN: '1', TMPDIR: path.join(validation, '.work/tmp')}});
}
async function boot(secret) {
  const response = await fetch(origin + '/webui/bootstrap', {headers: {'X-Nanobot-Auth': secret}});
  assert.equal(response.status, 200);
  return response.json();
}
async function read(token, route) {
  const response = await fetch(origin + '/api/boss/ui/' + route, {headers: {Authorization: 'Bearer ' + token}});
  assert.equal(response.status, 200);
  return response.json();
}
async function client(secret) {
  const auth = await boot(secret);
  const socket = new WebSocket(origin.replace('http:', 'ws:') + auth.ws_path + '?token=' + encodeURIComponent(auth.token));
  const ready = new Promise(resolve => socket.addEventListener('message', event => {
    const frame = JSON.parse(event.data);
    if (frame.event === 'ready') resolve(frame);
  }));
  await ready;
  return {token: auth.api_token, close: () => socket.close(), async rpc(action, payload) {
    const requestId = randomUUID();
    return new Promise(resolve => {
      const listener = event => {
        const frame = JSON.parse(event.data);
        if (frame.event === 'webui_response' && frame.request_id === requestId) {
          socket.removeEventListener('message', listener); resolve(frame);
        }
      };
      socket.addEventListener('message', listener);
      socket.send(JSON.stringify({type: 'webui_request', request_id: requestId, action, payload}));
    });
  }};
}

async function check() {
  let desktop = await launch();
  const sockets = [];
  try {
    let page = await desktop.firstWindow({timeout: 120000});
    const errors = [];
    const ended = [];
    page.on('pageerror', error => errors.push({name: error.name}));
    page.on('websocket', socket => socket.on('framereceived', event => {
      const frame = JSON.parse(event.payload.toString());
      if (frame.event === 'turn_end') ended.push({turn_id: frame.turn_id, outcome: frame.outcome, failure_kind: frame.failure_kind});
    }));
    await page.waitForURL(origin + '/');
    const access = JSON.parse(fs.readFileSync(path.join(applicationDirectory, 'access.json')));
    async function login(role) {
      await page.getByRole('radio', {name: role === 'BOSS' ? /^老板本人/ : /^技术维护/}).check();
      await page.getByLabel('本机访问凭据', {exact: true}).fill(access[role]);
      await page.getByRole('button', {name: '继续认证', exact: true}).click();
      await page.locator('.boss-v6[data-role="' + role + '"]').waitFor();
    }
    await login('MAINTAINER');
    const configuration = page.getByRole('region', {name: '公共模型运行配置', exact: true});
    await configuration.getByRole('checkbox', {name: 'bossWorkspaceRead', exact: true}).check();
    await configuration.getByLabel('最大工具轮数', {exact: true}).fill('8');
    await configuration.getByLabel('最大输出 Token', {exact: true}).fill('2048');
    await configuration.getByRole('button', {name: '保存配置草稿', exact: true}).click();
    await configuration.getByText('配置草稿已保存。请校验并明确启用。', {exact: true}).waitFor();
    await configuration.getByRole('button', {name: '校验配置', exact: true}).click();
    await configuration.getByText('配置静态校验通过，模型行为尚未验证。', {exact: true}).waitFor();
    await configuration.getByRole('button', {name: '启用下一任务配置', exact: true}).click();
    await configuration.getByText('已启用当前配置，下一任务使用该版本。', {exact: true}).waitFor();
    const maintBoot = await boot(access.MAINTAINER);
    const initialConfig = await read(maintBoot.api_token, 'admin/runtime-configuration');
    assert.equal(initialConfig.current.version, '2');
    assert.equal(initialConfig.admission_ready, true);
    assert.equal(initialConfig.effective.max_tool_rounds, 8);
    assert.equal(initialConfig.effective.max_output_tokens, 2048);
    assert.ok(initialConfig.current.tool_scope.includes('bossWorkspaceRead'));
    note({check: 'gui_configuration_save_validate_activate', version: '2', max_tool_rounds: 8, max_output_tokens: 2048,
      tool_scope: initialConfig.current.tool_scope, actual_native_sha256: initialConfig.native_config_sha256});
    await page.getByTitle('退出当前身份', {exact: true}).click();
    await page.getByLabel('本机访问凭据', {exact: true}).waitFor();
    await login('BOSS');
    const boss = await client(access.BOSS); sockets.push(boss);
    assert.equal((await fetch(origin + '/api/boss/ui/admin/runtime-configuration', {headers: {Authorization: 'Bearer ' + boss.token}})).status, 403);
    await page.getByLabel('输入本次工作需求', {exact: true}).fill('只读调用query_metrics比较region-1的product-1、product-2，2026-10-01至2026-10-10与2026-09-01至2026-09-10，CNY、EXTERNAL_SALES、definition_version=1，查询收入和毛利率并调用read_evidence读取finance-note依据。缺少原因明确说明未知，不创建交办或发送消息。');
    await page.getByRole('button', {name: '提交需求', exact: true}).click();
    await expect.poll(async () => (await read(boss.token, 'runtime-records')).runs.some(row => row.status === 'RUNNING'),
      {timeout: 30000, intervals: [250, 500]}).toBe(true);
    const maint = await client(access.MAINTAINER); sockets.push(maint);
    const values = {max_tool_rounds: 6, max_output_tokens: 2048, tool_scope: initialConfig.current.tool_scope};
    const saved = await maint.rpc('boss.runtime.save', {client_request_id: randomUUID(), expected_version: '2', values});
    assert.equal(saved.ok, true);
    const validated = await maint.rpc('boss.runtime.validate', {client_request_id: randomUUID(), expected_version: saved.result.version,
      expected_content_sha256: saved.result.content_sha256});
    assert.equal(validated.ok, true);
    const activation = {client_request_id: randomUUID(), expected_version: validated.result.version,
      expected_content_sha256: validated.result.content_sha256, expected_active_version: '2'};
    const blocked = await maint.rpc('boss.runtime.activate', activation);
    assert.equal(blocked.ok, false); assert.equal(blocked.error.status, 409);
    note({check: 'activation_rejected_during_actual_model_run', http_status: 409});
    await expect.poll(() => ended.length, {timeout: 150000, intervals: [500]}).toBe(1);
    assert.equal(ended[0].failure_kind ?? null, null);
    const first = (await read(boss.token, 'runtime-records')).runs[0];
    assert.equal(first.status, 'SUCCEEDED'); assert.equal(first.configuration_version, '2');
    assert.equal(first.runtime.max_tool_rounds, 8); assert.equal(first.runtime.max_output_tokens, 2048);
    assert.ok(first.tool_results.some(tool => tool.tool_id === 'query_metrics' && tool.query_id));
    assert.ok(first.tool_results.some(tool => tool.tool_id === 'read_evidence'));
    assert.ok(first.model_requests.length > 0 && first.model_requests.every(request => request.http_status === 200));
    assert.equal(first.private_body_recorded, false);
    note({check: 'home_form_actual_model_and_persisted_runtime', record: first});
    const activated = await maint.rpc('boss.runtime.activate', activation);
    assert.equal(activated.ok, true); assert.equal(activated.result.version, '3');
    const created = await boss.rpc('boss.assignment.create', {client_request_id: randomUUID(),
      purpose: '提交当前会议关联的毛利变化解释、措施和证据', coordinator_id: 'coordinator-1',
      due_at: '2026-10-25T17:00:00+08:00', timezone: 'Asia/Shanghai', evidence_requirements: ['原因明细', '措施及证据'],
      related_meeting_id: 'meeting-1', related_event_ids: ['event-1'], source_refs: ['finance-note'], content_version: '1'});
    assert.equal(created.ok, true);
    const taskId = created.result.task_id;
    await page.goto(origin + '/?bossPage=F01', {waitUntil: 'networkidle'});
    await page.getByLabel('输入本次工作需求', {exact: true}).fill('只调用read_assignment读取当前交办task_id=' + taskId + '，说明当前正式状态和版本。不得发送消息或更改任务，不得推断已经完成。');
    await page.getByRole('button', {name: '提交需求', exact: true}).click();
    await expect.poll(() => ended.length, {timeout: 150000, intervals: [500]}).toBe(2);
    assert.equal(ended[1].failure_kind ?? null, null);
    const second = (await read(boss.token, 'runtime-records')).runs.find(row => row.run_id !== first.run_id);
    assert.equal(second.status, 'SUCCEEDED'); assert.equal(second.configuration_version, '3');
    assert.equal(second.runtime.max_tool_rounds, 6);
    assert.ok(second.tool_results.some(tool => tool.tool_id === 'read_assignment' && tool.task_id === taskId));
    note({check: 'next_home_task_adopts_new_configuration_and_real_task_reference', task_id: taskId, record: second});
    await page.goto(origin + '/?bossPage=F01', {waitUntil: 'networkidle'});
    await page.getByTitle('退出当前身份', {exact: true}).click();
    await page.getByLabel('本机访问凭据', {exact: true}).waitFor();
    await login('MAINTAINER');
    await page.goto(origin + '/?bossPage=A15', {waitUntil: 'networkidle'});
    const query = page.getByRole('region', {name: '运行记录查询', exact: true});
    await query.getByLabel('run_id', {exact: true}).fill(second.run_id);
    await query.getByRole('button', {name: '查询记录', exact: true}).click();
    await page.getByRole('button', {name: '打开记录 ' + second.run_id, exact: true}).click();
    await page.getByRole('button', {name: '核查明细', exact: true}).click();
    await page.getByText(second.runtime.config_sha256, {exact: true}).waitFor();
    await page.getByRole('button', {name: '查看关联任务 ' + taskId, exact: true}).click();
    const technical = page.getByRole('region', {name: '关联交办技术状态', exact: true});
    await technical.getByText(taskId, {exact: true}).waitFor();
    await technical.getByText('coordinator-1', {exact: true}).waitFor();
    await expect(technical).not.toContainText('提交当前会议关联的毛利变化解释、措施和证据');
    assert.deepEqual(errors, []);
    note({check: 'a15_real_record_detail_and_current_task_reference', run_id: second.run_id, task_id: taskId,
      private_task_body_excluded: true, renderer_errors: errors});
    const oldToken = (await boot(access.MAINTAINER)).api_token;
    await page.getByTitle('退出当前身份', {exact: true}).click();
    await page.getByLabel('本机访问凭据', {exact: true}).waitFor();
    assert.equal((await fetch(origin + '/api/boss/ui/runtime-records', {headers: {Authorization: 'Bearer ' + oldToken}})).status, 401);
    for (const socket of sockets) socket.close();
    await desktop.close();
    desktop = await launch();
    page = await desktop.firstWindow({timeout: 120000});
    await page.waitForURL(origin + '/');
    await page.getByLabel('本机访问凭据', {exact: true}).waitFor();
    await login('MAINTAINER');
    const reopened = await boot(access.MAINTAINER);
    const persisted = await read(reopened.api_token, 'runtime-records?run_id=' + second.run_id);
    assert.deepEqual(persisted.runs[0], second);
    const current = await read(reopened.api_token, 'admin/runtime-configuration');
    assert.equal(current.current.version, '3'); assert.equal(current.admission_ready, true);
    assert.equal(current.effective.max_tool_rounds, 6);
    note({check: 'logout_and_service_restart_preserve_actual_records_and_configuration', run_id: second.run_id,
      configuration_version: current.current.version, previous_token: 401});
    save('PASS_PUBLIC_RUNTIME_CONFIGURATION_AND_A15_TASK_REFERENCE');
    console.log(JSON.stringify({status: 'PASS_PUBLIC_RUNTIME_CONFIGURATION_AND_A15_TASK_REFERENCE', evidence: output}));
  } finally {
    for (const socket of sockets) socket.close();
    await desktop.close();
  }
}
process.on('uncaughtExceptionMonitor', error => {records.push({check: 'uncaught_failure', name: error.name}); save('FAILED_CHECK');});
check();
