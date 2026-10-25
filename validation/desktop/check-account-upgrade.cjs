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
const runId = 'account-upgrade-' + randomUUID();
const directory = path.join(validation, '.work', runId);
const reference = 'evidence/T11/w3-local-20261023/memory-public-5917d36b-ce8d-411a-af34-2e999e3feeef.json';
const output = path.join(root, 'evidence/T11/w3-local-20261023', runId + '.json');
const ports = {business: 8971, webui: 8972, gateway: 18971};
const origin = 'http://127.0.0.1:8972';
const digest = value => createHash('sha256').update(value).digest('hex');
const records = [];
const inputs = ['validation/prepare_account_upgrade.py', 'validation/application.py', 'validation/product_runtime.py',
  'validation/boss_account_auth.py', 'validation/boss_page_api.py', 'validation/role_channel.py',
  'validation/desktop/check-account-upgrade.cjs', 'validation/desktop/account-access.cjs',
  'specs/runtime-records.schema.json', reference,
  '.work/product/nanobot/nanobot/web/dist/asset-manifest.json'].map(file => ({path: file, sha256: digest(fs.readFileSync(path.join(root, file)))}));
function save(status) {fs.writeFileSync(output, JSON.stringify({status, run_id: runId, at: new Date().toISOString(),
  application_directory: path.relative(root, directory), inputs, records, ports, external_api_mode: 'SIMULATED_FIRST',
  new_model_calls: false, new_business_actions: false, new_external_delivery: false, private_body_recorded: false,
  visual_acceptance: 'NOT_RUN', full_A11_A25_A27_accepted: false}, null, 2));}
function note(check, values) {records.push({check, ...values}); save('IN_PROGRESS');}
function python(script, args) {return JSON.parse(execFileSync(path.join(validation, '.venv/bin/python'),
  [path.join(root, script), ...args], {cwd: root, env: {...process.env, TMPDIR: path.join(validation, '.work/tmp')},
    timeout: 60000, maxBuffer: 4 * 1024 * 1024}).toString());}
function manifest() {return python('evidence/T12/check_simulation_reads.py', ['--database', path.join(directory, 'business.sqlite')]);}
async function launch() {return electron.launch({args: [__dirname], cwd: validation, timeout: 60000,
  env: {...process.env, BOSS_VALIDATION_ROOT: validation, BOSS_PRODUCT_UI: '1', BOSS_APPLICATION_WORK_DIR: directory,
    BOSS_APPLICATION_PORTS: JSON.stringify(ports), BOSS_DESKTOP_TEST_WINDOW_HIDDEN: '1', TMPDIR: path.join(validation, '.work/tmp')}});}
async function check() {
  let desktop = null;
  try {
    const prepared = python('validation/prepare_account_upgrade.py', ['--reference', path.join(root, reference), '--target-directory', directory]);
    note('actual_existing_application_native_backup', {prepared});
    const accounts = accountAccess.provision(directory); const before = manifest();
    const accountSha = digest(fs.readFileSync(path.join(directory, 'accounts/accounts.sqlite')));
    const source = path.join(root, prepared.source_directory);
    const errors = [];
    async function open() {
      desktop = await launch(); const page = await desktop.firstWindow({timeout: 120000});
      page.on('pageerror', error => errors.push({name: error.name})); await page.waitForURL(origin + '/'); return page;
    }
    async function read(token, route, status = 200) {
      const response = await fetch(origin + '/api/boss/ui/' + route, {headers: {Authorization: 'Bearer ' + token}});
      assert.equal(response.status, status); return status === 200 ? response.json() : null;
    }
    let page = await open(); await accountAccess.login(page, accounts, 'BOSS');
    const boss = await accountAccess.bootstrap(origin, accounts, 'BOSS');
    const dashboard = await read(boss.api_token, 'dashboard');
    assert.equal(dashboard.dataset_id, 'selection');
    const tasks = await read(boss.api_token, 'tasks'); assert.ok(tasks.tasks.length > 0);
    await page.goto(origin + '/?bossPage=F06', {waitUntil: 'networkidle'});
    await page.locator('.boss-hero .boss-eyebrow').filter({hasText: '· F06'}).waitFor();
    await expect(page.locator('.boss-v6')).toHaveAttribute('data-role', 'BOSS');
    await expect(page.locator('.boss-kv').filter({has: page.getByText('任务 ID', {exact: true})}).locator('strong')).toHaveText(tasks.tasks[0].task_id);
    await read(boss.api_token, 'admin/memory-status', 403); await accountAccess.logout(page);
    await accountAccess.login(page, accounts, 'MAINTAINER');
    const maint = await accountAccess.bootstrap(origin, accounts, 'MAINTAINER');
    await read(maint.api_token, 'dashboard', 403);
    const current = await read(maint.api_token, 'admin/runtime-configuration');
    assert.equal(current.current.version, '3'); assert.equal(current.current.max_tool_rounds, 6);
    const memory = await read(maint.api_token, 'admin/memory-status');
    assert.equal(memory.memory.version, '2'); assert.equal(memory.memory.confirmation_state, 'DELETED');
    assert.equal(memory.future_context_eligible, false);
    const runs = await read(maint.api_token, 'runtime-records?limit=50');
    assert.deepEqual(runs.runs.map(row => row.run_id).sort(), prepared.historical_run_ids.slice().sort());
    assert.ok(runs.runs.every(row => row.status === 'SUCCEEDED' && row.cost_total === null));
    await page.goto(origin + '/?bossPage=A15', {waitUntil: 'networkidle'});
    await page.getByRole('region', {name: '运行记录查询', exact: true}).getByRole('button', {name: '查询记录', exact: true}).click();
    for (const id of prepared.historical_run_ids) await page.getByRole('button', {name: '打开记录 ' + id, exact: true}).waitFor();
    const taskReferences = [];
    for (const run of runs.runs) {
      for (const id of new Set(run.tool_results.filter(item => item.task_id).map(item => item.task_id))) {
        const value = await read(maint.api_token, 'runtime-records/task?' + new URLSearchParams({run_id: run.run_id, task_id: id}));
        assert.equal(value.task_id, id); assert.equal(value.run_id, run.run_id);
        taskReferences.push({run_id: run.run_id, task_id: id, task_version: value.task_version, task_status: value.task_status});
      }
    }
    assert.ok(taskReferences.length > 0);
    note('account_login_preserves_existing_configuration_memory_runs_and_task_links', {
      configuration_version: current.current.version, max_tool_rounds: current.current.max_tool_rounds,
      memory_version: memory.memory.version, confirmation_state: memory.memory.confirmation_state,
      future_context_eligible: memory.future_context_eligible, historical_run_ids: prepared.historical_run_ids,
      historical_run_records_sha256: digest(JSON.stringify(runs.runs)), current_task_references: taskReferences,
      current_task_ids: tasks.tasks.map(item => item.task_id), maintenance_business: 403, owner_technical: 403});
    await accountAccess.logout(page); await desktop.close(); desktop = null;
    page = await open(); await accountAccess.login(page, accounts, 'MAINTAINER');
    const reopened = await accountAccess.bootstrap(origin, accounts, 'MAINTAINER');
    await read(maint.api_token, 'admin/memory-status', 401);
    assert.deepEqual((await read(reopened.api_token, 'runtime-records?limit=50')).runs, runs.runs);
    assert.equal((await read(reopened.api_token, 'admin/memory-status')).memory.confirmation_state, 'DELETED');
    assert.equal((await read(reopened.api_token, 'admin/runtime-configuration')).current.version, '3');
    assert.equal(digest(fs.readFileSync(path.join(directory, 'accounts/accounts.sqlite'))), accountSha);
    const after = manifest(); assert.deepEqual(after.before_tables_sha256, before.before_tables_sha256);
    assert.equal(digest(fs.readFileSync(path.join(source, 'business.sqlite'))), prepared.source_database_sha256);
    assert.equal(digest(fs.readFileSync(path.join(source, 'config.json'))), prepared.source_configuration_sha256);
    assert.deepEqual(errors, []);
    note('second_restart_preserves_actual_upgrade_and_source_application', {previous_token: 401,
      source_database_and_configuration_unchanged: true, business_tables_sha256: after.after_tables_sha256,
      account_database_sha256: accountSha, initial_snapshot_sha256: after.initial_snapshot_sha256, renderer_errors: errors,
      historical_model_evidence_reused_only: true, fresh_runtime_model_adoption_verified: false});
    save('PASS_ACTUAL_EXISTING_APPLICATION_ACCOUNT_UPGRADE_AND_RESTART');
    console.log(JSON.stringify({status: 'PASS_ACTUAL_EXISTING_APPLICATION_ACCOUNT_UPGRADE_AND_RESTART', evidence: output}));
  } finally {if (desktop) await desktop.close();}
}
process.on('uncaughtExceptionMonitor', error => {records.push({check: 'uncaught_failure', name: error.name}); save('FAILED_CHECK');});
check();
