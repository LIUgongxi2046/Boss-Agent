const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const {createHash, randomUUID} = require('node:crypto');
const {_electron: electron} = require('playwright');
const {expect} = require('@playwright/test');

const root = path.resolve(__dirname, '../..');
const validation = path.join(root, 'validation');
const reference = process.argv[2];
if (!reference || !/^runtime-application-[a-f0-9-]{36}$/.test(reference)) throw Error('需要实际运行证据标识');
const basePath = path.join(root, 'evidence/T11/w3-local-20261023', reference + '.json');
const base = JSON.parse(fs.readFileSync(basePath));
const prior = base.records.find(record => record.check === 'next_home_task_adopts_new_configuration_and_real_task_reference');
assert.ok(prior && prior.record.status === 'SUCCEEDED' && prior.task_id);
const applicable = base.inputs.filter(input => input.path !== 'validation/desktop/check-public-runtime.cjs');
for (const input of applicable)
  assert.equal(createHash('sha256').update(fs.readFileSync(path.join(root, input.path))).digest('hex'), input.sha256);
const applicationDirectory = path.join(validation, '.work', reference);
const access = JSON.parse(fs.readFileSync(path.join(applicationDirectory, 'access.json')));
const origin = 'http://127.0.0.1:8972';
const runId = 'runtime-recorded-' + randomUUID();
const output = path.join(root, 'evidence/T11/w3-local-20261023', runId + '.json');
const records = [];
function save(status) {
  fs.writeFileSync(output, JSON.stringify({status, run_id: runId, at: new Date().toISOString(), records,
    prior_evidence: {path: path.relative(root, basePath), sha256: createHash('sha256').update(fs.readFileSync(basePath)).digest('hex')},
    applicable_product_inputs: applicable, script_sha256: createHash('sha256').update(fs.readFileSync(__filename)).digest('hex'),
    new_model_calls: false, business_write_requested: false, private_body_recorded: false,
    visual_acceptance: 'NOT_RUN', full_A11_A16_accepted: false}, null, 2));
}
async function launch() {
  return electron.launch({args: [__dirname], cwd: validation, timeout: 60000,
    env: {...process.env, BOSS_VALIDATION_ROOT: validation, BOSS_PRODUCT_UI: '1',
      BOSS_APPLICATION_WORK_DIR: applicationDirectory,
      BOSS_APPLICATION_PORTS: JSON.stringify({business: 8971, webui: 8972, gateway: 18971}),
      BOSS_DESKTOP_TEST_WINDOW_HIDDEN: '1', TMPDIR: path.join(validation, '.work/tmp')}});
}
async function check() {
  let desktop = await launch();
  try {
    let page = await desktop.firstWindow({timeout: 120000});
    const errors = [];
    page.on('pageerror', error => errors.push({name: error.name}));
    async function login() {
      await page.waitForURL(origin + '/');
      await page.getByRole('radio', {name: /^技术维护/}).check();
      await page.getByLabel('本机访问凭据', {exact: true}).fill(access.MAINTAINER);
      await page.getByRole('button', {name: '继续认证', exact: true}).click();
      await page.locator('.boss-v6[data-role="MAINTAINER"]').waitFor();
    }
    async function token() {
      const response = await fetch(origin + '/webui/bootstrap', {headers: {'X-Nanobot-Auth': access.MAINTAINER}});
      assert.equal(response.status, 200); return (await response.json()).api_token;
    }
    async function read(auth, route) {
      const response = await fetch(origin + '/api/boss/ui/' + route, {headers: {Authorization: 'Bearer ' + auth}});
      assert.equal(response.status, 200); return response.json();
    }
    await page.waitForURL(origin + '/');
    await page.getByLabel('本机访问凭据', {exact: true}).waitFor();
    await login();
    const auth = await token();
    const persisted = await read(auth, 'runtime-records?run_id=' + prior.record.run_id);
    assert.deepEqual(persisted.runs[0], prior.record);
    const current = await read(auth, 'admin/runtime-configuration');
    assert.equal(current.current.version, '3'); assert.equal(current.admission_ready, true);
    assert.equal(current.effective.max_tool_rounds, 6);
    records.push({check: 'actual_record_and_configuration_reopened', run_id: prior.record.run_id, configuration_version: '3'}); save('IN_PROGRESS');
    await page.goto(origin + '/?bossPage=A15', {waitUntil: 'networkidle'});
    const query = page.getByRole('region', {name: '运行记录查询', exact: true});
    await query.getByLabel('run_id', {exact: true}).fill(prior.record.run_id);
    await query.getByRole('button', {name: '查询记录', exact: true}).click();
    await page.getByRole('button', {name: '打开记录 ' + prior.record.run_id, exact: true}).click();
    await page.getByRole('button', {name: '核查明细', exact: true}).click();
    await page.getByText(prior.record.runtime.config_sha256, {exact: true}).waitFor();
    await page.getByRole('button', {name: '查看关联任务 ' + prior.task_id, exact: true}).click();
    const technical = page.getByRole('region', {name: '关联交办技术状态', exact: true});
    await technical.getByText(prior.task_id, {exact: true}).waitFor();
    await technical.getByText('coordinator-1', {exact: true}).waitFor();
    await expect(technical).not.toContainText('提交当前会议关联的毛利变化解释、措施和证据');
    assert.deepEqual(errors, []);
    records.push({check: 'a15_real_record_detail_and_current_task_reference', run_id: prior.record.run_id, task_id: prior.task_id,
      renderer_errors: errors, private_task_body_excluded: true}); save('IN_PROGRESS');
    await page.getByTitle('退出当前身份', {exact: true}).click();
    await page.getByLabel('本机访问凭据', {exact: true}).waitFor();
    assert.equal((await fetch(origin + '/api/boss/ui/runtime-records', {headers: {Authorization: 'Bearer ' + auth}})).status, 401);
    await desktop.close();
    desktop = await launch();
    page = await desktop.firstWindow({timeout: 120000});
    await page.waitForURL(origin + '/');
    await page.getByLabel('本机访问凭据', {exact: true}).waitFor();
    await login();
    const reopened = await token();
    assert.deepEqual((await read(reopened, 'runtime-records?run_id=' + prior.record.run_id)).runs[0], prior.record);
    assert.equal((await read(reopened, 'admin/runtime-configuration')).admission_ready, true);
    records.push({check: 'logout_and_service_restart_preserve_records_and_configuration', prior_token: 401});
    save('PASS_A15_RECORDED_PUBLIC_RUNTIME_AND_RESTART');
    console.log(JSON.stringify({status: 'PASS_A15_RECORDED_PUBLIC_RUNTIME_AND_RESTART', evidence: output}));
  } finally {await desktop.close();}
}
process.on('uncaughtExceptionMonitor', error => {records.push({check: 'uncaught_failure', name: error.name}); save('FAILED_CHECK');});
check();
