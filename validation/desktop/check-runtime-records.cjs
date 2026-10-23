const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const { createHash, randomUUID } = require('node:crypto');
const { _electron: electron } = require('playwright');

const root = path.resolve(__dirname, '../..');
const validation = path.join(root, 'validation');
const runId = 'runtime-public-' + randomUUID();
const applicationDirectory = path.join(validation, '.work', runId);
const ports = { business: 8971, webui: 8972, gateway: 18971 };
const origin = 'http://127.0.0.1:' + ports.webui;
const output = path.join(root, 'evidence/T11/w3-local-20261023', runId + '.json');
const records = [];
const inputs = ['app/webui/BossDesktop.tsx', 'app/webui/MaintainerRuntimeRecords.tsx',
  'app/webui/RuntimeTaskTechnicalView.tsx', 'validation/boss_page_api.py',
  'validation/boss_runtime_records.py', 'validation/runtime_records_query.py',
  'validation/application.py', 'validation/desktop/main.cjs', 'validation/desktop/check-runtime-records.cjs',
  '.work/product/nanobot/nanobot/web/dist/asset-manifest.json'].map(file => ({
  path: file, sha256: createHash('sha256').update(fs.readFileSync(path.join(root, file))).digest('hex'),
}));

function save(status) {
  fs.writeFileSync(output, JSON.stringify({ status, run_id: runId, at: new Date().toISOString(), inputs,
    ports, records, source_type: 'RUNTIME_RECORD', business_write_requested: false,
    model_requested: false, positive_runtime_rows_verified: false, task_reference_action_verified: false,
    visual_acceptance: 'NOT_RUN', full_A11_accepted: false }, null, 2));
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
    await page.getByRole('radio', { name: /^技术维护/ }).check();
    await page.getByLabel('本机访问凭据', { exact: true }).fill(access.MAINTAINER);
    await page.getByRole('button', { name: '继续认证', exact: true }).click();
    await page.locator('.boss-v6[data-role="MAINTAINER"]').waitFor();
    const bootstrap = await fetch(origin + '/webui/bootstrap', { headers: { 'X-Nanobot-Auth': access.MAINTAINER } });
    assert.equal(bootstrap.status, 200);
    const headers = { Authorization: 'Bearer ' + (await bootstrap.json()).api_token };
    async function businessHashes() {
      const hashes = {};
      for (const kind of ['task', 'outbox']) {
        const response = await fetch('http://127.0.0.1:' + ports.business + '/spaces/ui-check/objects/' + kind,
          { headers: { Authorization: 'Bearer ' + access.BOSS } });
        assert.equal(response.status, 200);
        hashes[kind] = createHash('sha256').update(await response.text()).digest('hex');
      }
      return hashes;
    }
    const before = await businessHashes();
    assert.equal((await fetch(origin + '/api/boss/ui/runtime-records')).status, 401);
    for (const query of ['provider=deepseek&provider=deepseek', 'namespace=ui-check', 'limit=101'])
      assert.equal((await fetch(origin + '/api/boss/ui/runtime-records?' + query, { headers })).status, 400);
    assert.equal((await fetch(origin + '/api/boss/ui/runtime-records?run_id=unrecorded-run', { headers })).status, 404);
    records.push({ check: 'real_http_authentication_and_query_rejection', unauthed: 401, invalid_queries: 400, absent_run: 404 });
    save('IN_PROGRESS');
    await page.goto(origin + '/?bossPage=A15', { waitUntil: 'networkidle' });
    const queryPanel = page.getByRole('region', { name: '运行记录查询', exact: true });
    await queryPanel.getByLabel('Provider', { exact: true }).fill('deepseek');
    await queryPanel.getByLabel('数据集', { exact: true }).fill('selection');
    await queryPanel.getByRole('combobox', { name: '运行状态', exact: true }).selectOption('SUCCEEDED');
    await queryPanel.getByRole('combobox', { name: '每页数量', exact: true }).selectOption('1');
    const resultRead = page.waitForResponse(response => new URL(response.url()).pathname === '/api/boss/ui/runtime-records' && response.status() === 200);
    await queryPanel.getByRole('button', { name: '查询记录', exact: true }).click();
    const resultResponse = await resultRead;
    const parameters = new URL(resultResponse.url()).searchParams;
    assert.equal(parameters.get('provider'), 'deepseek');
    assert.equal(parameters.get('dataset_id'), 'selection');
    assert.equal(parameters.get('status'), 'SUCCEEDED');
    assert.equal(parameters.get('limit'), '1');
    const result = await resultResponse.json();
    assert.equal(result.projection, 'runtime-records');
    assert.equal(result.source_type, 'RUNTIME_RECORD');
    assert.equal(result.matched_count, 0);
    assert.deepEqual(result.runs, []);
    assert.equal(result.private_body_available_here, false);
    assert.equal(result.business_mutation_performed, false);
    await page.getByText('没有符合当前条件的运行记录', { exact: true }).waitFor();
    records.push({ check: 'maintainer_form_queries_real_empty_store', matched_count: 0, limit: result.limit });
    await page.context().setOffline(true);
    await queryPanel.getByRole('button', { name: '查询记录', exact: true }).click();
    await page.getByRole('alert').filter({ hasText: 'Failed to fetch' }).waitFor();
    await page.context().setOffline(false);
    const recovered = page.waitForResponse(response => new URL(response.url()).pathname === '/api/boss/ui/runtime-records' && response.status() === 200);
    await queryPanel.getByRole('button', { name: '查询记录', exact: true }).click();
    assert.equal((await (await recovered).json()).matched_count, 0);
    await page.getByText('没有符合当前条件的运行记录', { exact: true }).waitFor();
    records.push({ check: 'real_offline_failure_and_online_recovery', recovered: true });
    const overflow = await page.locator('.boss-main').evaluate(() => document.documentElement.scrollWidth > innerWidth + 1);
    assert.equal(overflow, false);
    assert.equal(errors.length, 0);
    assert.deepEqual(await businessHashes(), before);
    await page.getByTitle('退出当前身份', { exact: true }).click();
    await page.getByLabel('本机访问凭据', { exact: true }).waitFor();
    assert.equal(await page.locator('.boss-v6[data-role]').count(), 0);
    assert.equal(await page.getByRole('region', { name: '运行记录查询', exact: true }).count(), 0);
    assert.equal((await fetch(origin + '/api/boss/ui/runtime-records', { headers })).status, 401);
    records.push({ check: 'logout_clears_technical_view_and_revokes_token', previous_token: 401,
      renderer_errors: errors, horizontal_overflow: overflow, business_unchanged: true });
    save('PASS_A15_PUBLIC_EMPTY_QUERY_AND_FAILURES_ONLY');
    console.log(JSON.stringify({ status: 'PASS_A15_PUBLIC_EMPTY_QUERY_AND_FAILURES_ONLY', evidence: output }));
  } finally {
    await desktop.close();
  }
}

process.on('uncaughtExceptionMonitor', error => {
  records.push({ check: 'uncaught_failure', name: error.name });
  save('FAILED_CHECK');
});

check();
