const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const {execFileSync} = require('node:child_process');
const {createHash, randomUUID} = require('node:crypto');
const {_electron: electron} = require('playwright');
const {expect} = require('@playwright/test');

const root = path.resolve(__dirname, '../..');
const validation = path.join(root, 'validation');
const runId = 'simulation-public-' + randomUUID();
const directory = path.join(validation, '.work', runId);
const output = path.join(root, 'evidence/T11/w3-local-20261023', runId + '.json');
const origin = 'http://127.0.0.1:8972';
const ports = {business: 8971, webui: 8972, gateway: 18971};
const digest = value => createHash('sha256').update(value).digest('hex');
const inputs = ['validation/application.py', 'validation/role_channel.py', 'validation/boss_page_api.py',
  'validation/boss_simulation_api.py', 'specs/simulation-query.schema.json', 'specs/openapi.yaml',
  'app/webui/MaintainerSimulationInspect.tsx', 'app/webui/BossDesktop.tsx', 'app/webui/boss-v6.css',
  'validation/desktop/check-simulation-public.cjs', 'evidence/T12/check_simulation_reads.py',
  '.work/product/nanobot/nanobot/web/dist/asset-manifest.json'].map(file => ({path: file, sha256: digest(fs.readFileSync(path.join(root, file)))}));
const records = [];
function save(status) {fs.writeFileSync(output, JSON.stringify({status, run_id: runId, at: new Date().toISOString(), inputs, records, ports,
  application_directory: path.relative(root, directory), external_api_mode: 'SIMULATED_FIRST', source_type: 'SIMULATED',
  model_requested: false, external_delivery_requested: false, private_body_recorded: false,
  visual_acceptance: 'NOT_RUN', full_A11_A12_A19_accepted: false}, null, 2));}
function note(check, values) {records.push({check, ...values}); save('IN_PROGRESS');}
function manifest() {return JSON.parse(execFileSync(path.join(validation, '.venv/bin/python'), [
  path.join(root, 'evidence/T12/check_simulation_reads.py'), '--database', path.join(directory, 'business.sqlite'),
], {cwd: root, encoding: 'utf8'}));}
async function launch() {return electron.launch({args: [__dirname], cwd: validation, timeout: 60000,
  env: {...process.env, BOSS_VALIDATION_ROOT: validation, BOSS_PRODUCT_UI: '1', BOSS_APPLICATION_WORK_DIR: directory,
    BOSS_APPLICATION_PORTS: JSON.stringify(ports), BOSS_DESKTOP_TEST_WINDOW_HIDDEN: '1', TMPDIR: path.join(validation, '.work/tmp')}});}
async function check() {
  const desktop = await launch();
  let paused = null;
  try {
    const page = await desktop.firstWindow({timeout: 120000});
    const errors = [];
    const inspectRequests = [];
    page.on('pageerror', error => errors.push({name: error.name}));
    page.on('request', request => {if (new URL(request.url()).pathname === '/api/boss/ui/simulation-inspect') inspectRequests.push(request.url());});
    await page.waitForURL(origin + '/');
    const access = JSON.parse(fs.readFileSync(path.join(directory, 'access.json')));
    async function boot(role) {
      const response = await fetch(origin + '/webui/bootstrap', {headers: {'X-Nanobot-Auth': access[role]}});
      assert.equal(response.status, 200); return response.json();
    }
    async function read(token, endpoint, parameters, status = 200) {
      const response = await fetch(origin + '/api/boss/ui/' + endpoint + '?' + parameters, {headers: {Authorization: 'Bearer ' + token}});
      assert.equal(response.status, status); if (status === 200) return response.json();
    }
    await page.getByRole('radio', {name: /^技术维护/}).check();
    await page.getByLabel('本机访问凭据', {exact: true}).fill(access.MAINTAINER);
    await page.getByRole('button', {name: '继续认证', exact: true}).click();
    await page.locator('.boss-v6[data-role="MAINTAINER"]').waitFor();
    await page.goto(origin + '/?bossPage=A02', {waitUntil: 'networkidle'});
    const panel = page.getByRole('region', {name: '模拟接口人工检查', exact: true});
    const responsePanel = page.getByRole('complementary', {name: '模拟接口实际响应', exact: true});
    await responsePanel.getByText('接口未调用', {exact: true}).waitFor();
    const control = panel.getByRole('combobox', {name: '接口编号', exact: true});
    await control.waitFor();
    assert.equal(await control.locator('option').count(), 14);
    note('a02_authenticated_initial_form_and_uncalled_state', {interface_options: 14, initial_response: 'NOT_CALLED'});
    const maint = await boot('MAINTAINER');
    const boss = await boot('BOSS');
    const before = manifest();
    for (const id of JSON.parse(fs.readFileSync(path.join(root, 'specs/simulation-query.schema.json'))).$defs.Interface.enum) {
      await panel.getByLabel('接口编号', {exact: true}).selectOption(id);
      const observed = page.waitForResponse(response => {
        const url = new URL(response.url());
        return url.pathname === '/api/boss/ui/simulation-inspect' && url.searchParams.get('interface_id') === id && response.status() === 200;
      });
      await panel.getByRole('button', {name: '人工检查', exact: true}).click();
      const result = await (await observed).json();
      await responsePanel.getByText(result.read_at, {exact: true}).waitFor();
      assert.equal(result.access, 'TECHNICAL_METADATA'); assert.equal(result.source_type, 'SIMULATED');
      assert.ok(result.records.every(item => item.data === null && item.content_state === 'METADATA_ONLY' && item.source_refs.length === 0));
      const owner = await read(boss.api_token, 'simulation-query', 'interface_id=' + id);
      assert.equal(owner.access, 'BOSS_ONLY');
      assert.deepEqual(result.records.map(item => item.record_id).sort(), owner.records.map(item => item.record_id).sort());
      note('gui_manual_current_interface_and_owner_http_role', {interface_id: id, availability: result.availability,
        records: result.records.length, missing_fields: result.missing_fields, response_sha256: digest(JSON.stringify(result)), private_body_excluded: true});
    }
    await panel.getByLabel('接口编号', {exact: true}).selectOption('SI07');
    const requestCount = inspectRequests.length;
    await panel.getByLabel('筛选参数（JSON）', {exact: true}).fill('{"product_ids":"product-1"}');
    await panel.getByRole('button', {name: '人工检查', exact: true}).click();
    await page.getByRole('alert').filter({hasText: 'product_ids 必须是非空字符串数组'}).waitFor();
    assert.equal(inspectRequests.length, requestCount);
    note('schema_filter_type_rejected_before_http', {new_http_requests: 0});
    const filter = {period_start: '2026-10-01', period_end: '2026-10-10', region_id: 'region-1', product_ids: ['product-1'], currency: 'CNY'};
    await panel.getByLabel('筛选参数（JSON）', {exact: true}).fill(JSON.stringify(filter));
    const filteredResponse = page.waitForResponse(response => new URL(response.url()).pathname === '/api/boss/ui/simulation-inspect' && response.status() === 200);
    await panel.getByRole('button', {name: '人工检查', exact: true}).click();
    const filtered = await (await filteredResponse).json();
    await responsePanel.getByText(filtered.read_at, {exact: true}).waitFor();
    const params = new URLSearchParams({interface_id: 'SI07', ...filter});
    params.delete('product_ids'); params.append('product_ids', 'product-1');
    const ownerFiltered = await read(boss.api_token, 'simulation-query', params);
    assert.ok(filtered.records.length > 0);
    assert.deepEqual(filtered.records.map(item => item.record_id).sort(), ownerFiltered.records.map(item => item.record_id).sort());
    assert.ok(ownerFiltered.records.filter(item => item.entity_type === 'metric_detail').every(item => item.data.product_id === 'product-1'));
    await panel.getByLabel('筛选参数（JSON）', {exact: true}).fill('{"currency":"USD"}');
    await panel.getByRole('button', {name: '人工检查', exact: true}).click();
    await page.getByRole('alert').filter({hasText: 'HTTP 400'}).waitFor();
    assert.equal(await responsePanel.getByText('当前资料覆盖', {exact: true}).count(), 0);
    await panel.getByLabel('筛选参数（JSON）', {exact: true}).fill('{}');
    await page.context().setOffline(true);
    await panel.getByRole('button', {name: '人工检查', exact: true}).click();
    await page.getByRole('alert').filter({hasText: 'Failed to fetch'}).waitFor();
    await page.context().setOffline(false);
    await panel.getByRole('button', {name: '人工检查', exact: true}).click();
    await responsePanel.getByText('当前资料覆盖', {exact: true}).waitFor();
    note('actual_filter_error_and_offline_recovery', {filtered_records: filtered.records.length, rejected_currency: 400, recovered: true});
    const instance = JSON.parse(fs.readFileSync(path.join(directory, 'instance.json')));
    assert.deepEqual(instance.ports, ports); paused = instance.pid;
    process.kill(paused, 'SIGSTOP');
    await panel.getByRole('button', {name: '人工检查', exact: true}).click();
    await page.getByRole('status').filter({hasText: '正在读取当前模拟资料的技术元信息'}).waitFor();
    await panel.getByRole('button', {name: '取消检查', exact: true}).click();
    await responsePanel.getByText('已取消本次人工检查，业务状态保持当前内容。', {exact: true}).waitFor();
    process.kill(paused, 'SIGCONT'); paused = null;
    await panel.getByRole('button', {name: '人工检查', exact: true}).click();
    await responsePanel.getByText('当前资料覆盖', {exact: true}).waitFor();
    note('actual_pending_read_cancel_and_service_resume', {pending_service: 'own_profile_only', recovered: true});
    await panel.getByLabel('接口编号', {exact: true}).selectOption('SI13');
    await panel.getByLabel('对象编号（每行一个，可留空）', {exact: true}).fill('memory-1');
    await panel.getByRole('button', {name: '人工检查', exact: true}).click();
    await responsePanel.getByText('memory:memory-1', {exact: true}).waitFor();
    await responsePanel.getByText('查看实际响应 JSON', {exact: true}).click();
    await panel.getByText('Input Schema', {exact: true}).click();
    for (const zoom of [1, 2]) {
      await desktop.evaluate(({BrowserWindow}, value) => BrowserWindow.getAllWindows()[0].webContents.setZoomFactor(value), zoom);
      for (const size of [[1024, 768], [1280, 800], [1440, 1024]]) {
        await desktop.evaluate(({BrowserWindow}, value) => BrowserWindow.getAllWindows()[0].setContentSize(...value), size);
        const overflow = await page.evaluate(() => document.documentElement.scrollWidth > innerWidth + 1);
        assert.equal(overflow, false); note('a02_viewport', {zoom, size, horizontal_overflow: overflow});
      }
    }
    await desktop.evaluate(({BrowserWindow}) => BrowserWindow.getAllWindows()[0].webContents.setZoomFactor(1));
    await read(maint.api_token, 'simulation-query', 'interface_id=SI13', 403);
    await read(boss.api_token, 'simulation-inspect', 'interface_id=SI13', 403);
    await read('', 'simulation-inspect', 'interface_id=SI13', 401);
    await read(maint.api_token, 'simulation-inspect', 'interface_id=SI13&namespace=ui-check', 400);
    await panel.getByRole('button', {name: '查看工具映射', exact: true}).click();
    await page.waitForURL(origin + '/?bossPage=A09');
    const after = manifest(); assert.deepEqual(after.after_tables_sha256, before.before_tables_sha256);
    assert.deepEqual(errors, []);
    await page.getByTitle('退出当前身份', {exact: true}).click();
    await page.getByLabel('本机访问凭据', {exact: true}).waitFor();
    await read(maint.api_token, 'simulation-inspect', 'interface_id=SI13', 401);
    note('schema_role_logout_and_complete_business_table_invariance', {domain_verification: after,
      role_denied: 403, scope_denied: 400, anonymous_and_logged_out: 401, renderer_errors: errors});
    save('PASS_PUBLIC_FOURTEEN_SIMULATION_INTERFACES_AND_A02_INSPECTION');
    console.log(JSON.stringify({status: 'PASS_PUBLIC_FOURTEEN_SIMULATION_INTERFACES_AND_A02_INSPECTION', evidence: output}));
  } finally {if (paused !== null) process.kill(paused, 'SIGCONT'); await desktop.close();}
}
process.on('uncaughtExceptionMonitor', error => {records.push({check: 'uncaught_failure', name: error.name}); save('FAILED_CHECK');});
check();
