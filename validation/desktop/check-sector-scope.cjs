const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const {execFileSync} = require('node:child_process');
const {createHash, randomUUID} = require('node:crypto');
const {_electron: electron} = require('playwright');
const {expect} = require('@playwright/test');

const root = path.resolve(__dirname, '../..');
const validation = path.join(root, 'validation');
const runId = 'sector-scope-' + randomUUID();
const directory = path.join(validation, '.work', runId);
const output = path.join(root, 'evidence/T11/w3-local-20261023', runId + '.json');
const ports = {business: 8971, webui: 8972, gateway: 18971};
const origin = 'http://127.0.0.1:8972';
const pageIds = ['F14', 'F15', 'F16', 'F17', 'F18', 'F19', 'F20', 'F21', 'F22', 'F23', 'V19-BEEF', 'V19-EGG', 'V19-MILK'];
const digest = value => createHash('sha256').update(value).digest('hex');
const records = [];
const inputs = ['app/webui/BossSectorView.tsx', 'app/webui/BossDesktop.tsx', 'validation/boss_page_api.py',
  'validation/role_channel.py', 'validation/desktop/check-sector-scope.cjs', 'evidence/T12/check_simulation_reads.py',
  '.work/product/nanobot/nanobot/web/dist/asset-manifest.json'].map(file => ({path: file, sha256: digest(fs.readFileSync(path.join(root, file)))}));
function save(status) {fs.writeFileSync(output, JSON.stringify({status, run_id: runId, at: new Date().toISOString(),
  application_directory: path.relative(root, directory), inputs, records, ports, external_api_mode: 'SIMULATED_FIRST',
  model_requested: false, external_delivery_requested: false, sector_kpi_calculations_verified: false,
  visual_acceptance: 'NOT_RUN', full_sector_business_accepted: false}, null, 2));}
function note(check, values) {records.push({check, ...values}); save('IN_PROGRESS');}
function manifest() {return JSON.parse(execFileSync(path.join(validation, '.venv/bin/python'), [
  path.join(root, 'evidence/T12/check_simulation_reads.py'), '--database', path.join(directory, 'business.sqlite'),
], {cwd: root, encoding: 'utf8'}));}
async function check() {
  const desktop = await electron.launch({args: [__dirname], cwd: validation, timeout: 60000,
    env: {...process.env, BOSS_VALIDATION_ROOT: validation, BOSS_PRODUCT_UI: '1', BOSS_APPLICATION_WORK_DIR: directory,
      BOSS_APPLICATION_PORTS: JSON.stringify(ports), BOSS_DESKTOP_TEST_WINDOW_HIDDEN: '1', TMPDIR: path.join(validation, '.work/tmp')}});
  let paused = null;
  try {
    const page = await desktop.firstWindow({timeout: 120000});
    const errors = [], mutations = [], reads = [];
    page.on('pageerror', error => errors.push({name: error.name}));
    page.on('websocket', socket => socket.on('framesent', event => {
      const frame = JSON.parse(String(event.payload));
      if (frame.type === 'webui_request') mutations.push(frame.action);
    }));
    page.on('response', response => {const address = new URL(response.url());
      if (address.pathname === '/api/boss/ui/sector') reads.push({page_id: address.searchParams.get('page'), status: response.status()});});
    await page.waitForURL(origin + '/');
    const access = JSON.parse(fs.readFileSync(path.join(directory, 'access.json')));
    async function login(role) {
      await expect(page.getByLabel('本机访问凭据', {exact: true})).toBeEnabled();
      await page.getByRole('radio', {name: role === 'BOSS' ? /^老板本人/ : /^技术维护/}).check();
      await page.getByLabel('本机访问凭据', {exact: true}).fill(access[role]);
      await page.getByRole('button', {name: '继续认证', exact: true}).click();
      await page.locator('.boss-v6[data-role="' + role + '"]').waitFor();
    }
    async function boot(role) {
      const response = await fetch(origin + '/webui/bootstrap', {headers: {'X-Nanobot-Auth': access[role]}});
      assert.equal(response.status, 200); return (await response.json()).api_token;
    }
    async function navigate(id) {
      await page.getByTitle('全部设计页面', {exact: true}).click();
      const dialog = page.getByRole('dialog', {name: '全部页面导航', exact: true});
      await dialog.getByPlaceholder('搜索页面编号或名称', {exact: true}).fill(id);
      const observed = page.waitForResponse(response => {
        const address = new URL(response.url());
        return address.pathname === '/api/boss/ui/sector' && address.searchParams.get('page') === id && response.status() === 200;
      });
      await dialog.getByRole('button', {name: new RegExp('^' + id + ' · ')}).click();
      const value = await (await observed).json();
      await page.getByRole('heading', {name: '经营筛选范围', exact: true}).waitFor();
      return value;
    }
    await login('BOSS'); const boss = await boot('BOSS');
    const before = manifest();
    for (const id of pageIds) {
      const value = await navigate(id);
      assert.equal(value.page_id, id); assert.equal(value.source_type, 'SIMULATED');
      assert.equal(value.sector_specific_dataset_available, false); assert.equal(value.sector_kpi_calculations_supported, false);
      assert.ok(value.metrics.length > 0 && value.metrics.every(item => item.value === null && item.unit === null));
      const filters = page.locator('.boss-sector-filters');
      assert.deepEqual(await filters.locator('input').evaluateAll(inputs => inputs.map(input => input.value)), value.design_filters.map(() => ''));
      for (const label of value.design_filters) await expect(filters.getByLabel(label, {exact: true})).toHaveValue('');
      const firstField = filters.getByLabel(value.design_filters[0], {exact: true});
      await firstField.fill(value.business_scope);
      await filters.getByRole('button', {name: '核对资料范围', exact: true}).click();
      await page.getByRole('status').filter({hasText: '已记录当前页面的查询条件'}).waitFor();
      const metricValues = await page.locator('.boss-sector-stat strong').allTextContents();
      assert.deepEqual(metricValues, value.metrics.map(() => '待查询'));
      assert.equal(new URL(page.url()).searchParams.get('bossPage'), id);
      note('public_current_sector_scope_and_unknown_metrics', {page_id: id, source_type: value.source_type,
        design_filters: value.design_filters, metric_labels: value.metrics.map(item => item.label), numeric_values: value.metrics.map(item => item.value),
        source_ids: value.related_source_refs.map(item => item.source_id), page_fields_initialized_empty: true,
        actual_scope_input_sha256: digest(value.business_scope), response_sha256: digest(JSON.stringify(value))});
    }
    await navigate('F19');
    const tabResponse = page.waitForResponse(response => new URL(response.url()).pathname === '/api/boss/ui/sector' &&
      new URL(response.url()).searchParams.get('page') === 'V19-EGG' && response.status() === 200);
    await page.locator('.boss-sector-tabs').getByRole('button', {name: '蛋禽', exact: true}).click();
    const tabValue = await (await tabResponse).json(); assert.equal(tabValue.page_id, 'V19-EGG');
    await expect(page.locator('.boss-sector-filters input')).toHaveCount(tabValue.design_filters.length);
    assert.ok((await page.locator('.boss-sector-filters input').evaluateAll(inputs => inputs.map(input => input.value))).every(value => value === ''));
    await page.context().setOffline(true); await page.getByRole('button', {name: '重新核对', exact: true}).click();
    await page.getByRole('alert').filter({hasText: 'Failed to fetch'}).waitFor();
    assert.equal(await page.locator('.boss-sector-filters').count(), 0);
    await page.context().setOffline(false);
    await page.getByRole('button', {name: '重新核对', exact: true}).click();
    await page.getByRole('heading', {name: '经营筛选范围', exact: true}).waitFor();
    note('public_sector_tab_and_actual_offline_recovery', {current_page: 'V19-EGG', previous_fields_absent: true,
      offline_current_data_removed: true, recovered: true});
    await page.getByTitle('退出当前身份', {exact: true}).click();
    await expect(page.getByLabel('本机访问凭据', {exact: true})).toBeEnabled();
    assert.equal(await page.locator('.boss-sector-filters').count(), 0);
    const expired = await fetch(origin + '/api/boss/ui/sector?page=V19-EGG', {headers: {Authorization: 'Bearer ' + boss}});
    assert.equal(expired.status, 401);
    await login('MAINTAINER'); const maint = await boot('MAINTAINER');
    const forbidden = await fetch(origin + '/api/boss/ui/sector?page=F14', {headers: {Authorization: 'Bearer ' + maint}});
    assert.equal(forbidden.status, 403);
    await page.goto(origin + '/?bossPage=A06&bossSop=SOP03', {waitUntil: 'networkidle'});
    const instance = JSON.parse(fs.readFileSync(path.join(directory, 'instance.json')));
    assert.deepEqual(instance.ports, ports); paused = instance.pid; process.kill(paused, 'SIGSTOP');
    const pending = page.waitForRequest(request => new URL(request.url()).pathname === '/api/boss/ui/admin/sop-method');
    await page.getByRole('button', {name: '读取当前方法', exact: true}).click(); await pending;
    await page.getByRole('button', {name: '取消本次读取', exact: true}).click();
    await page.getByText('本次读取已经取消。', {exact: true}).waitFor();
    process.kill(paused, 'SIGCONT'); paused = null;
    await page.getByRole('button', {name: '读取当前方法', exact: true}).click();
    await page.getByRole('table', {name: '已保存方法步骤表', exact: true}).waitFor();
    assert.deepEqual(errors, []);
    assert.deepEqual(mutations.filter(action => action.startsWith('boss.')), ['boss.auth.logout']);
    const after = manifest(); assert.deepEqual(after.before_tables_sha256, before.before_tables_sha256);
    note('public_logout_roles_a06_pending_http_cancellation_and_zero_mutation', {old_token: 401, cross_role: 403,
      page_reads: reads, actual_websocket_actions: mutations, renderer_errors: errors,
      pending_http_canceled_and_reread: true, business_tables_sha256: after.after_tables_sha256,
      initial_snapshot_sha256: after.initial_snapshot_sha256});
    save('PASS_PUBLIC_THIRTEEN_SECTOR_SCOPES_AND_A06_PENDING_READ_CANCELLATION');
    console.log(JSON.stringify({status: 'PASS_PUBLIC_THIRTEEN_SECTOR_SCOPES_AND_A06_PENDING_READ_CANCELLATION', evidence: output}));
  } finally {if (paused !== null) process.kill(paused, 'SIGCONT'); await desktop.close();}
}
process.on('uncaughtExceptionMonitor', error => {records.push({check: 'uncaught_failure', name: error.name}); save('FAILED_CHECK');});
check();
