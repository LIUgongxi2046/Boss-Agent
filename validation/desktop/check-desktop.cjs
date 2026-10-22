const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const { spawn } = require('node:child_process');
const { once } = require('node:events');
const { randomUUID } = require('node:crypto');
const { _electron: electron } = require('playwright');
const { expect } = require('@playwright/test');

const root = path.resolve(__dirname, '..');
const output = path.join(root, '..', 'evidence', 'T02', 'desktop-' + randomUUID());
fs.mkdirSync(output);
const environment = { ...process.env, BOSS_VALIDATION_ROOT: root, TMPDIR: path.join(root, '.work', 'tmp') };
const records = [];
let activeDesktop;
let activeProcess;
function record(check, result) {
  records.push({ at: new Date().toISOString(), check, result });
  fs.writeFileSync(path.join(output, 'checks.json'), JSON.stringify(records, null, 2));
}

async function start() {
  const desktop = await electron.launch({ args: [__dirname], cwd: root, env: environment, timeout: 60000 });
  activeDesktop = desktop;
  activeProcess = desktop.process();
  const page = await desktop.firstWindow();
  await page.waitForURL('http://127.0.0.1:8872/', { waitUntil: 'domcontentloaded' });
  await page.waitForLoadState('networkidle');
  await desktop.evaluate(({ BrowserWindow }) => BrowserWindow.getAllWindows()[0].webContents.setZoomFactor(1));
  return { desktop, page };
}

async function main() {
  const { desktop, page } = await start();
  const access = JSON.parse(fs.readFileSync(path.join(root, '.work/application/access.json')));
  async function business(method, route, payload) {
    const response = await fetch('http://127.0.0.1:8871' + route, { method, headers: { Authorization: 'Bearer ' + access.BOSS, 'Content-Type': 'application/json' }, body: payload === undefined ? undefined : JSON.stringify(payload), signal: AbortSignal.timeout(10000) });
    assert.equal(response.status, 200);
    return response.json();
  }
  const composer = page.getByRole('region', { name: 'Conversation workbench', exact: true }).getByRole('textbox');
  const password = page.getByRole('textbox', { name: 'WebUI password', exact: true });
  await password.or(composer).first().waitFor();
  if (await password.isVisible()) {
    await password.fill(access.BOSS);
    await page.getByRole('button', { name: 'Connect', exact: true }).click();
  }
  await composer.waitFor();
  const status = await page.evaluate(() => window.bossDesktop.invoke({ action: 'status' }));
  assert.equal(status.versions.electron, '45.0.0');
  assert.equal(status.architecture, 'x64');
  assert.equal(await page.evaluate(() => typeof window.require), 'undefined');
  assert.equal(await page.evaluate(() => typeof window.process), 'undefined');
  record('desktop_start', status);
  const instance = JSON.parse(fs.readFileSync(path.join(root, '.work/application/instance.json')));
  assert.equal(instance.max_tool_rounds, 8);
  record('admin_configuration_reloaded', instance);

  async function turn(text) {
    await composer.fill(text);
    await composer.press('Enter');
    const stop = page.getByRole('button', { name: 'Stop response', exact: true });
    await stop.waitFor({ state: 'visible', timeout: 15000 });
    await stop.waitFor({ state: 'hidden', timeout: 120000 });
    await composer.waitFor();
  }

  const current = await business('GET', '/spaces/ui-check/context');
  const memory = await business('PUT', '/spaces/ui-check/memory', { version: current.memory_version, confirmation_state: 'CONFIRMED', text: '简报第一行固定为“本人决定优先”，随后列出经营指标和待办。' });
  await turn('根据当前已确认要求生成简报，并查询 region-1 的 product-1 和 product-2，2026-10-01 至 2026-10-10 对比 2026-09-01 至 2026-09-10，CNY、EXTERNAL_SALES、definition_version=1，查询六个经营指标并读取依据。');
  await expect(page.locator('main')).toContainText('本人决定优先');
  fs.writeFileSync(path.join(output, 'memory-adopted.txt'), await page.locator('body').ariaSnapshot());
  const admissions = JSON.parse(fs.readFileSync(path.join(root, '..', 'evidence/T02/application/events.json'))).filter(record => record.type === 'runtime_admission');
  assert.equal(admissions.at(-1).configuration.max_tool_rounds, 8);
  record('next_model_task_configuration_and_memory', { memory_version: memory.version, configuration: admissions.at(-1).configuration });

  await business('PUT', '/spaces/ui-check/memory', { version: memory.version, confirmation_state: 'DELETED' });
  await page.getByRole('button', { name: 'New topic', exact: true }).click();
  await turn('说明当前已确认的阅读要求；缺少时请明确说明，不从其他会话猜测。');
  const transport = JSON.parse(fs.readFileSync(path.join(root, '..', 'evidence/T02/application/http-requests.json'))).filter(record => record.type === 'request');
  const latest = JSON.stringify(transport.at(-1).input.messages);
  assert.equal(latest.includes('本人决定优先'), false);
  assert.equal((await business('GET', '/spaces/ui-check/context')).memory, null);
  record('new_session_deleted_memory_excluded', { request_url: transport.at(-1).url, memory: null });

  const tasks = await business('GET', '/spaces/ui-check/objects/task');
  assert.equal(tasks.length, 1);
  await turn('重新查询交办 ' + tasks[0].task_id + ' 的正式状态、负责人、期限和消息关联。');
  await expect(page.locator('main')).toContainText('WAITING_FEEDBACK');
  await page.reload({ waitUntil: 'networkidle' });
  await expect(page.locator('main')).toContainText(tasks[0].task_id, { timeout: 20000 });
  record('desktop_state_readback', { task_id: tasks[0].task_id, state: tasks[0].status, outbox_count: (await business('GET', '/spaces/ui-check/objects/outbox')).length });

  await assert.rejects(page.evaluate(() => window.bossDesktop.invoke({ action: 'exec' })), /IPC 能力未授权/);
  await assert.rejects(page.evaluate(() => window.bossDesktop.invoke({ action: 'select_file', token: 'coordinator-1' })), /IPC 未认证/);
  const bootstrap = await fetch('http://127.0.0.1:8872/webui/bootstrap', { headers: { 'X-Nanobot-Auth': access.MAINTAINER } });
  const credentials = await bootstrap.json();
  await assert.rejects(page.evaluate(token => window.bossDesktop.invoke({ action: 'notify', token }), credentials.api_token), /IPC 需要老板身份/);
  record('ipc_role_and_capability_denied', { arbitrary_command: 'DENIED', unauthenticated: 'DENIED', maintainer_boss_operation: 'DENIED' });
  const otherWindow = await desktop.evaluate(async ({ BrowserWindow }, preload) => {
    const child = new BrowserWindow({ show: false, webPreferences: { preload, nodeIntegration: false, contextIsolation: true, sandbox: true } });
    await child.loadURL('data:text/html,<p>IPC 来源检查</p>');
    return child.id;
  }, path.join(__dirname, 'preload.cjs'));
  await assert.rejects(desktop.evaluate(async ({ BrowserWindow }, id) => BrowserWindow.fromId(id).webContents.executeJavaScript("window.bossDesktop.invoke({action:'status'})"), otherWindow), /IPC 发送方无权访问/);
  await desktop.evaluate(({ BrowserWindow }, id) => BrowserWindow.fromId(id).close(), otherWindow);
  record('ipc_foreign_renderer_denied', true);
  await assert.rejects(page.evaluate(() => navigator.mediaDevices.getUserMedia({ audio: true })), /Permission|permission|NotAllowedError|denied/);
  assert.equal(await page.evaluate(() => Notification.requestPermission()), 'denied');
  await composer.fill('文字输入仍可使用');
  await expect(composer).toHaveValue('文字输入仍可使用');
  await composer.fill('');
  record('host_permission_denial', { microphone: 'DENIED_BY_HOST', browser_notifications: 'DENIED_BY_HOST', os_microphone_state: status.microphone, os_allow_deny_revoke: 'NOT_RUN' });

  for (const [width, height] of [[1024, 768], [1280, 800], [1440, 1024]]) {
    await desktop.evaluate(({ BrowserWindow }, size) => {
      const windows = BrowserWindow.getAllWindows();
      if (windows.length !== 1) throw new Error('桌面窗口数量不符合检查条件');
      windows[0].setContentSize(size[0], size[1]);
    }, [width, height]);
    await expect(page.getByRole('button', { name: 'New topic', exact: true })).toBeVisible();
    record('content_window', { width, height, navigation_accessible: true });
  }
  await desktop.evaluate(({ BrowserWindow }) => BrowserWindow.getAllWindows()[0].webContents.setZoomFactor(2));
  await expect(composer).toBeVisible();
  record('zoom_200_percent', true);
  const executable = desktop.process().spawnfile;
  const duplicate = spawn(executable, [__dirname], { cwd: root, env: environment, stdio: 'ignore' });
  await once(duplicate, 'exit', { signal: AbortSignal.timeout(10000) });
  assert.equal(JSON.parse(fs.readFileSync(path.join(root, '.work/application/instance.json'))).pid, status.service_pid);
  record('duplicate_start_single_service', true);

  const exited = once(desktop.process(), 'exit', { signal: AbortSignal.timeout(20000) });
  await desktop.evaluate(({ BrowserWindow }) => { setTimeout(() => BrowserWindow.getAllWindows()[0].close(), 100); });
  await exited;
  await assert.rejects(fetch('http://127.0.0.1:8871/health', { signal: AbortSignal.timeout(2000) }));
  record('last_window_closes_service_and_scheduler', true);
  const restarted = await start();
  const after = JSON.parse(fs.readFileSync(path.join(root, '.work/application/instance.json')));
  assert.notEqual(after.pid, status.service_pid);
  assert.equal((await business('GET', '/spaces/ui-check/context')).memory, null);
  assert.deepEqual(await business('GET', '/spaces/ui-check/objects/task'), tasks);
  assert.equal((await business('GET', '/spaces/ui-check/objects/outbox')).length, 1);
  record('actual_desktop_restart_state', { pid: after.pid, task_id: tasks[0].task_id, deleted_memory: true, outbox_count: 1 });
  await restarted.desktop.close();
  const report = { status: 'PASS', at: new Date().toISOString(), scope: 'Electron 实际启动、两端状态采用、IPC 拒绝、窗口关闭与进程重启；系统休眠及 OS 权限完整过程尚未执行', checks: records.length, system_sleep: 'NOT_RUN', os_permissions: 'PARTIAL' };
  fs.writeFileSync(path.join(output, 'result.json'), JSON.stringify(report, null, 2));
  console.log(JSON.stringify({ ...report, evidence: output }));
}

main().finally(async () => {
  if (activeDesktop && activeProcess.exitCode === null) await activeDesktop.close();
});
