const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const {createHash, randomUUID} = require('node:crypto');
const {_electron: electron} = require('playwright');

const root = path.resolve(__dirname, '../..');
const validation = path.join(root, 'validation');
const reference = 'runtime-application-c6e06b70-5c16-4d4c-bbad-b76aaddf70e1';
const reportPath = path.join(root, 'evidence/T11/w3-local-20261023', reference + '.json');
const report = JSON.parse(fs.readFileSync(reportPath));
const prior = report.records.find(item => item.check === 'next_home_task_adopts_new_configuration_and_real_task_reference');
assert.equal(report.status, 'PASS_PUBLIC_RUNTIME_CONFIGURATION_AND_A15_TASK_REFERENCE');
assert.ok(prior?.task_id && prior.record.status === 'SUCCEEDED');
const directory = path.join(validation, '.work', reference);
const access = JSON.parse(fs.readFileSync(path.join(directory, 'access.json')));
const runId = 'runtime-task-access-' + randomUUID();
const output = path.join(root, 'evidence/T11/w3-local-20261023', runId + '.json');
const ports = {business: 8971, webui: 8972, gateway: 18971};
const origin = 'http://127.0.0.1:8972';
const records = [];
const digest = value => createHash('sha256').update(value).digest('hex');
const inputs = ['validation/boss_page_api.py', 'validation/runtime_records_query.py', 'validation/desktop/check-runtime-task-access.cjs',
  '.work/product/nanobot/nanobot/web/dist/asset-manifest.json'].map(file => ({path: file, sha256: digest(fs.readFileSync(path.join(root, file)))}));
function save(status) {fs.writeFileSync(output, JSON.stringify({status, run_id: runId, at: new Date().toISOString(), inputs, records,
  prior_evidence: {path: path.relative(root, reportPath), sha256: digest(fs.readFileSync(reportPath))},
  model_requested: false, business_write_requested: false, private_body_recorded: false, visual_acceptance: 'NOT_RUN'}, null, 2));}
async function boot(role) {
  const response = await fetch(origin + '/webui/bootstrap', {headers: {'X-Nanobot-Auth': access[role]}});
  assert.equal(response.status, 200); return response.json();
}
async function query(token, parameters, status = 200) {
  const response = await fetch(origin + '/api/boss/ui/runtime-records/task?' + parameters, {headers: {Authorization: 'Bearer ' + token}});
  assert.equal(response.status, status);
  return status === 200 ? response.json() : {status};
}
async function businessDigest() {
  const result = {};
  for (const kind of ['task', 'outbox']) {
    const response = await fetch('http://127.0.0.1:8971/spaces/ui-check/objects/' + kind, {headers: {Authorization: 'Bearer ' + access.BOSS}});
    assert.equal(response.status, 200); result[kind] = digest(await response.text());
  }
  return result;
}
async function check() {
  const desktop = await electron.launch({args: [__dirname], cwd: validation, timeout: 60000,
    env: {...process.env, BOSS_VALIDATION_ROOT: validation, BOSS_PRODUCT_UI: '1', BOSS_APPLICATION_WORK_DIR: directory,
      BOSS_APPLICATION_PORTS: JSON.stringify(ports), BOSS_DESKTOP_TEST_WINDOW_HIDDEN: '1', TMPDIR: path.join(validation, '.work/tmp')}});
  try {
    const page = await desktop.firstWindow({timeout: 120000});
    await page.waitForURL(origin + '/');
    await page.getByRole('radio', {name: /^技术维护/}).check();
    await page.getByLabel('本机访问凭据', {exact: true}).fill(access.MAINTAINER);
    await page.getByRole('button', {name: '继续认证', exact: true}).click();
    await page.locator('.boss-v6[data-role="MAINTAINER"]').waitFor();
    const before = await businessDigest();
    const parameter = new URLSearchParams({run_id: prior.record.run_id, task_id: prior.task_id});
    const tokens = {};
    for (const role of ['BOSS', 'MAINTAINER']) {
      tokens[role] = (await boot(role)).api_token;
      const result = await query(tokens[role], parameter);
      assert.equal(result.run_id, prior.record.run_id); assert.equal(result.task_id, prior.task_id);
      assert.equal(result.task_status, 'OPEN'); assert.equal(result.task_version, '1');
      assert.equal(result.source_type, 'RUNTIME_RECORD'); assert.equal(result.task_source_type, 'SIMULATED');
      assert.equal(result.private_body_available_here, false); assert.equal(result.business_mutation_performed, false);
      assert.deepEqual(Object.keys(result).sort(), ['projection', 'source_type', 'task_source_type', 'namespace', 'run_id',
        'dataset_id', 'dataset_version', 'task_id', 'task_version', 'task_status', 'read_at',
        'private_body_available_here', 'business_mutation_performed'].sort());
      records.push({check: 'authenticated_actual_run_current_task_metadata', role, result}); save('IN_PROGRESS');
    }
    for (const parameters of ['', parameter + '&namespace=ui-check', parameter + '&task_id=' + prior.task_id, 'run_id=&task_id=' + prior.task_id])
      await query(tokens.MAINTAINER, parameters, 400);
    await query(tokens.MAINTAINER, new URLSearchParams({run_id: prior.task_id, task_id: prior.task_id}), 404);
    await query(tokens.MAINTAINER, new URLSearchParams({run_id: prior.record.run_id, task_id: prior.record.run_id}), 403);
    await query('', parameter, 401);
    assert.deepEqual(await businessDigest(), before);
    await page.getByTitle('退出当前身份', {exact: true}).click();
    await page.getByLabel('本机访问凭据', {exact: true}).waitFor();
    await query(tokens.MAINTAINER, parameter, 401);
    records.push({check: 'strict_query_link_permissions_logout_and_zero_business_mutation', invalid_query: 400,
      unknown_run: 404, unrelated_task: 403, anonymous_and_logged_out: 401, business_sha256: before});
    save('PASS_PUBLIC_RUNTIME_TASK_REFERENCE_ACTUAL_STORE');
    console.log(JSON.stringify({status: 'PASS_PUBLIC_RUNTIME_TASK_REFERENCE_ACTUAL_STORE', evidence: output}));
  } finally {await desktop.close();}
}
process.on('uncaughtExceptionMonitor', error => {records.push({check: 'uncaught_failure', name: error.name}); save('FAILED_CHECK');});
check();
