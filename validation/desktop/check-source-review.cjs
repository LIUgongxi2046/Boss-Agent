const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const {execFileSync} = require('node:child_process');
const {createHash, randomUUID} = require('node:crypto');
const {_electron: electron} = require('playwright');
const {expect} = require('@playwright/test');

const root = path.resolve(__dirname, '../..');
const validation = path.join(root, 'validation');
const runId = 'source-review-' + randomUUID();
const applicationDirectory = path.join(validation, '.work', runId);
const ports = {business: 8971, webui: 8972, gateway: 18971};
const origin = 'http://127.0.0.1:' + ports.webui;
const output = path.join(root, 'evidence/T11/w3-local-20261023', runId + '.json');
const prepared = JSON.parse(execFileSync(path.join(validation, '.venv/bin/python'), [
  path.join(validation, 'legacy_assignment_fixture.py'), '--directory', applicationDirectory,
], {cwd: root, encoding: 'utf8'}));
const taskId = prepared.task.task_id;
const records = [{check: 'actual_legacy_store_produced_same_approved_selection', producer: prepared}];
const inputs = ['validation/legacy_assignment_fixture.py', 'validation/boss_assignment_sources.py', 'validation/business.py',
  'validation/boss_command_api.py', 'validation/boss_page_api.py', 'validation/boss_recovery_api.py',
  'app/webui/BossDesktop.tsx', 'app/webui/BossAssignmentSourceReview.tsx', 'validation/desktop/check-source-review.cjs',
  '.work/product/nanobot/nanobot/web/dist/asset-manifest.json'].map(file => ({path: file,
    sha256: createHash('sha256').update(fs.readFileSync(path.join(root, file))).digest('hex')}));
function save(status) {fs.writeFileSync(output, JSON.stringify({status, run_id: runId, at: new Date().toISOString(), inputs,
  records, model_requested: false, external_delivery_requested: false, visual_acceptance: 'NOT_RUN', full_A11_A14_accepted: false}, null, 2));}
async function launch() {
  return electron.launch({args: [__dirname], cwd: validation, timeout: 60000, env: {...process.env,
    BOSS_VALIDATION_ROOT: validation, BOSS_PRODUCT_UI: '1', BOSS_APPLICATION_WORK_DIR: applicationDirectory,
    BOSS_APPLICATION_PORTS: JSON.stringify(ports), BOSS_DESKTOP_TEST_WINDOW_HIDDEN: '1', TMPDIR: path.join(validation, '.work/tmp')}});
}
async function bootstrap(access) {
  const response = await fetch(origin + '/webui/bootstrap', {headers: {'X-Nanobot-Auth': access}});
  assert.equal(response.status, 200); return response.json();
}
async function read(token, route) {
  const response = await fetch(origin + '/api/boss/ui/' + route, {headers: {Authorization: 'Bearer ' + token}});
  assert.equal(response.status, 200); return response.json();
}
async function createCurrentTask(access) {
  const auth = await bootstrap(access);
  const socket = new WebSocket(origin.replace('http:', 'ws:') + auth.ws_path + '?token=' + encodeURIComponent(auth.token));
  await new Promise(resolve => socket.addEventListener('message', event => {if (JSON.parse(event.data).event === 'ready') resolve();}));
  const requestId = randomUUID();
  const response = new Promise(resolve => socket.addEventListener('message', event => {
    const frame = JSON.parse(event.data); if (frame.request_id === requestId) resolve(frame);
  }));
  socket.send(JSON.stringify({type: 'webui_request', request_id: requestId, action: 'boss.assignment.create', payload: {
    client_request_id: randomUUID(), purpose: '提交当前会议关联的毛利变化解释、措施和证据', coordinator_id: 'coordinator-1',
    due_at: '2026-10-25T17:00:00+08:00', timezone: 'Asia/Shanghai', evidence_requirements: ['原因明细', '措施及证据'],
    related_meeting_id: 'meeting-1', related_event_ids: ['event-1'], source_refs: ['finance-note'], content_version: '1',
  }}));
  const receipt = await response; socket.close(); assert.equal(receipt.ok, true); return receipt.result;
}
async function check() {
  let desktop = await launch();
  try {
    let page = await desktop.firstWindow({timeout: 120000});
    const errors = [];
    page.on('pageerror', error => errors.push({name: error.name}));
    await page.waitForURL(origin + '/');
    const access = JSON.parse(fs.readFileSync(path.join(applicationDirectory, 'access.json')));
    async function login() {
      await page.getByRole('radio', {name: /^老板本人/}).check();
      await page.getByLabel('本机访问凭据', {exact: true}).fill(access.BOSS);
      await page.getByRole('button', {name: '继续认证', exact: true}).click();
      await page.locator('.boss-v6[data-role="BOSS"]').waitFor();
    }
    await login();
    const auth = await bootstrap(access.BOSS);
    const current = await createCurrentTask(access.BOSS);
    const source = await read(auth.api_token, 'evidence?source=finance-note');
    await page.goto(origin + '/?bossPage=F06&bossTask=' + taskId, {waitUntil: 'networkidle'});
    const review = page.getByRole('region', {name: '核查交办来源', exact: true});
    await review.getByText('历史来源没有完整记录。请核查当前资料后独立确认。', {exact: true}).waitFor();
    const reason = review.getByRole('textbox', {name: '本次核查依据', exact: true});
    await reason.fill(source.content);
    await review.getByRole('button', {name: '查看当前原始资料', exact: true}).click();
    const dialog = page.getByRole('dialog', {name: '未保存修改（D06）', exact: true});
    await dialog.waitFor(); await page.keyboard.press('Escape'); await dialog.waitFor({state: 'detached'});
    assert.equal(await reason.inputValue(), source.content);
    const currentButton = page.getByRole('button', {name: /提交当前会议关联的毛利变化解释、措施和证据/});
    await currentButton.click(); await dialog.waitFor();
    await dialog.getByRole('button', {name: '返回继续编辑', exact: true}).click();
    await dialog.waitFor({state: 'detached'});
    assert.equal(new URL(page.url()).searchParams.get('bossTask'), taskId);
    assert.equal(await reason.inputValue(), source.content);
    await currentButton.click(); await dialog.waitFor();
    await dialog.getByRole('button', {name: '放弃草稿并离开', exact: true}).click();
    await expect.poll(() => new URL(page.url()).searchParams.get('bossTask')).toBe(current.task_id);
    await review.getByText('当前来源与本人确认版本一致。', {exact: true}).waitFor();
    assert.equal(await reason.inputValue(), '');
    records.push({check: 'source_editing_protected_during_source_and_task_navigation', original_task_id: taskId, selected_task_id: current.task_id}); save('IN_PROGRESS');
    await page.getByRole('button', {name: /核查饲料外销经营明细并准备会议/}).click();
    await review.getByText('历史来源没有完整记录。请核查当前资料后独立确认。', {exact: true}).waitFor();
    await reason.fill(source.content);
    await review.getByRole('checkbox', {name: '本人已经核查当前资料，确认用于此项交办', exact: true}).check();
    await review.getByRole('button', {name: '本人确认当前来源', exact: true}).click();
    await review.getByText('当前来源与本人确认版本一致。', {exact: true}).waitFor();
    const confirmed = await read(auth.api_token, 'assignment-source-review?task_id=' + taskId);
    assert.equal(confirmed.task.version, '2'); assert.equal(confirmed.task.status, 'OPEN');
    assert.equal(confirmed.binding_state, 'CURRENT'); assert.deepEqual(confirmed.history, []);
    assert.equal(confirmed.confirmed_reason, source.content);
    assert.equal(confirmed.can_confirm, false);
    await expect(review.getByRole('button', {name: '本人确认当前来源', exact: true})).toBeDisabled();
    records.push({check: 'gui_owner_confirm_persists_current_binding_and_original_business_state', task_id: taskId, version: '2', status: 'OPEN', binding: 'CURRENT', known_history_count: 0}); save('IN_PROGRESS');
    await review.getByRole('button', {name: '查看当前原始资料', exact: true}).click();
    await page.waitForURL(origin + '/?bossPage=D01');
    await page.getByRole('button', {name: '返回原页面', exact: true}).click();
    await expect.poll(() => new URL(page.url()).searchParams.get('bossTask')).toBe(taskId);
    await page.reload({waitUntil: 'networkidle'});
    await review.getByText('当前来源与本人确认版本一致。', {exact: true}).waitFor();
    for (const zoom of [1, 2]) {
      await desktop.evaluate(({BrowserWindow}, value) => BrowserWindow.getAllWindows()[0].webContents.setZoomFactor(value), zoom);
      for (const size of [[1024, 768], [1280, 800], [1440, 1024]]) {
        await desktop.evaluate(({BrowserWindow}, value) => BrowserWindow.getAllWindows()[0].setContentSize(...value), size);
        const overflow = await page.evaluate(() => document.documentElement.scrollWidth > innerWidth + 1);
        assert.equal(overflow, false); records.push({check: 'f06_viewport', zoom, size, horizontal_overflow: overflow});
      }
    }
    await desktop.evaluate(({BrowserWindow}) => BrowserWindow.getAllWindows()[0].webContents.setZoomFactor(1));
    const response = await fetch('http://127.0.0.1:8971/spaces/ui-check/objects/outbox', {headers: {Authorization: 'Bearer ' + access.BOSS}});
    assert.equal(response.status, 200); assert.deepEqual(await response.json(), []);
    assert.deepEqual(errors, []);
    await page.getByTitle('退出当前身份', {exact: true}).click();
    await page.getByLabel('本机访问凭据', {exact: true}).waitFor();
    assert.equal((await fetch(origin + '/api/boss/ui/assignment-source-review?task_id=' + taskId, {headers: {Authorization: 'Bearer ' + auth.api_token}})).status, 401);
    await desktop.close(); desktop = await launch();
    page = await desktop.firstWindow({timeout: 120000});
    await page.waitForURL(origin + '/'); await page.getByLabel('本机访问凭据', {exact: true}).waitFor();
    await login();
    const after = await bootstrap(access.BOSS);
    const persisted = await read(after.api_token, 'assignment-source-review?task_id=' + taskId);
    assert.equal(persisted.task.version, '2'); assert.equal(persisted.binding_state, 'CURRENT');
    records.push({check: 'refresh_source_return_logout_and_service_restart', task_id: taskId, version: '2', prior_token: 401,
      outbox_count: 0, renderer_errors: errors});
    save('PASS_PUBLIC_F06_SOURCE_REVIEW_AND_LEGACY_UPGRADE');
    console.log(JSON.stringify({status: 'PASS_PUBLIC_F06_SOURCE_REVIEW_AND_LEGACY_UPGRADE', evidence: output}));
  } finally {await desktop.close();}
}
process.on('uncaughtExceptionMonitor', error => {records.push({check: 'uncaught_failure', name: error.name}); save('FAILED_CHECK');});
check();
