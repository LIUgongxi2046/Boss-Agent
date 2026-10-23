const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const { once } = require('node:events');
const { createHash } = require('node:crypto');
const { execFileSync } = require('node:child_process');
const { _electron: electron } = require('playwright');

const root = path.resolve(__dirname, '..');
const output = path.join(root, '../evidence/T11/w3-local-20261023/desktop.json');
const records = [];
let activeDesktop;

function save(check, result) {
  records.push({ check, result, at: new Date().toISOString() });
  fs.writeFileSync(output, JSON.stringify(records, null, 2));
}

async function start() {
  const desktop = await electron.launch({
    args: [__dirname], cwd: root, timeout: 60000,
    env: { ...process.env, BOSS_VALIDATION_ROOT: root, BOSS_PRODUCT_UI: '1', TMPDIR: path.join(root, '.work/tmp') },
  });
  activeDesktop = desktop;
  const page = await desktop.firstWindow();
  page.on('pageerror', error => save('renderer_error', { name: error.name, message: error.message }));
  page.on('requestfailed', request => save('request_failed', { path: new URL(request.url()).pathname }));
  await page.waitForURL('http://127.0.0.1:8872/', { waitUntil: 'domcontentloaded' });
  return { desktop, page };
}

async function login(page, role) {
  const access = JSON.parse(fs.readFileSync(path.join(root, '.work/application/access.json')));
  const field = page.getByLabel('本机访问凭据', { exact: true });
  await field.waitFor();
  await page.getByRole('radio', { name: role === 'BOSS' ? /^老板本人/ : /^技术维护/ }).check();
  await field.fill(access[role]);
  let requests = 0;
  const count = request => { if (new URL(request.url()).pathname === '/webui/bootstrap') requests += 1; };
  page.on('request', count);
  await page.getByRole('button', { name: /^(继续认证|重新认证)$/ }).click({ clickCount: 2 });
  await page.locator('.boss-v6[data-role="' + role + '"]').waitFor();
  page.off('request', count);
  assert.equal(requests, 1);
  save('authenticated_shell', { role });
}

async function snapshot() {
  const access = JSON.parse(fs.readFileSync(path.join(root, '.work/application/access.json')));
  const values = [];
  for (const kind of ['task', 'outbox']) {
    const response = await fetch('http://127.0.0.1:8871/spaces/ui-check/objects/' + kind, {
      headers: { Authorization: 'Bearer ' + access.BOSS }, signal: AbortSignal.timeout(15000),
    });
    assert.equal(response.status, 200);
    const body = await response.text();
    values.push({ kind, sha256: createHash('sha256').update(body).digest('hex') });
  }
  const bootstrap = await fetch('http://127.0.0.1:8872/webui/bootstrap', { headers: { 'X-Nanobot-Auth': access.BOSS } });
  assert.equal(bootstrap.status, 200);
  const headers = { Authorization: 'Bearer ' + (await bootstrap.json()).api_token };
  for (const kind of ['owner-plans', 'today']) {
    const response = await fetch('http://127.0.0.1:8872/api/boss/ui/' + kind, { headers });
    assert.equal(response.status, 200);
    const body = await response.json();
    const saved = kind === 'owner-plans' ? body.plans : { order_version: body.order_version, item_ids: body.items.map(item => item.item_id) };
    values.push({ kind, sha256: createHash('sha256').update(JSON.stringify(saved)).digest('hex') });
  }
  return values;
}

async function close(desktop) {
  const exited = once(desktop.process(), 'exit', { signal: AbortSignal.timeout(20000) });
  await desktop.evaluate(({ app }) => { setTimeout(() => app.quit(), 50); });
  await exited;
  activeDesktop = null;
}

async function roleCommand(secret, action, payload) {
  const response = await fetch('http://127.0.0.1:8872/webui/bootstrap', { headers: { 'X-Nanobot-Auth': secret } });
  assert.equal(response.status, 200);
  const boot = await response.json();
  const socket = new WebSocket('ws://127.0.0.1:8872' + boot.ws_path + '?token=' + encodeURIComponent(boot.token));
  await once(socket, 'open', { signal: AbortSignal.timeout(15000) });
  const requestId = crypto.randomUUID();
  socket.send(JSON.stringify({ type: 'webui_request', request_id: requestId, action, payload }));
  while (true) {
    const [message] = await once(socket, 'message', { signal: AbortSignal.timeout(15000) });
    const frame = JSON.parse(message.data);
    if (frame.request_id === requestId) {
      assert.equal(frame.ok, true);
      socket.close();
      return frame;
    }
  }
}

async function checkBounds(page, stage) {
  const bounds = await page.locator('.boss-v6, .boss-frame, .boss-layout, .boss-login-content').evaluateAll(nodes => nodes.map(node => {
    const rect = node.getBoundingClientRect();
    const style = getComputedStyle(node);
    return { className: node.className, left: rect.left, top: rect.top,
      right: window.innerWidth - rect.right, bottom: window.innerHeight - rect.bottom,
      padding: style.padding, margin: style.margin, border: style.borderWidth,
      radius: style.borderRadius, shadow: style.boxShadow,
      horizontalOverflow: document.documentElement.scrollWidth > window.innerWidth + 1 };
  }));
  save('content_bounds', { stage, nodes: bounds });
  assert.ok(bounds.length > 0);
  for (const row of bounds) {
    for (const edge of ['left', 'top', 'right', 'bottom']) assert.ok(Math.abs(row[edge]) <= 1, stage + ':' + row.className + ':' + edge);
    assert.equal(row.horizontalOverflow, false);
  }
}

async function checkViewports(desktop, page, stage) {
  for (const factor of [1, 2]) {
    await desktop.evaluate(({ BrowserWindow }, zoom) => BrowserWindow.getAllWindows()[0].webContents.setZoomFactor(zoom), factor);
    for (const [width, height] of [[1024, 768], [1280, 800], [1440, 1024]]) {
      await desktop.evaluate(({ BrowserWindow }, size) => BrowserWindow.getAllWindows()[0].setContentSize(...size), [width, height]);
      await checkBounds(page, stage + ':' + width + 'x' + height + ':' + factor);
    }
  }
  await desktop.evaluate(({ BrowserWindow }) => BrowserWindow.getAllWindows()[0].webContents.setZoomFactor(1));
}

async function ownerActions(page, access) {
  const maintainer = await fetch('http://127.0.0.1:8872/webui/bootstrap', { headers: { 'X-Nanobot-Auth': access.MAINTAINER } });
  assert.equal(maintainer.status, 200);
  const datasetResponse = await fetch('http://127.0.0.1:8872/api/boss/ui/workspace/dataset', {
    headers: { Authorization: 'Bearer ' + (await maintainer.json()).api_token },
  });
  assert.equal(datasetResponse.status, 200);
  const dataset = await datasetResponse.json();
  assert.ok(dataset.simulated_event_id);
  await roleCommand(access.MAINTAINER, 'boss.simulation.event.seed', {
    client_request_id: 'desktop-approved-selection-event', event_id: dataset.simulated_event_id,
  });
  save('approved_selection_event_registered', { event_id: dataset.simulated_event_id, source_type: 'SIMULATED' });
  await page.reload({ waitUntil: 'domcontentloaded' });
  await page.locator('.boss-v6[data-role="BOSS"]').waitFor();
  const bootstrap = await fetch('http://127.0.0.1:8872/webui/bootstrap', { headers: { 'X-Nanobot-Auth': access.BOSS } });
  assert.equal(bootstrap.status, 200);
  const headers = { Authorization: 'Bearer ' + (await bootstrap.json()).api_token };
  const todayResponse = await fetch('http://127.0.0.1:8872/api/boss/ui/today', { headers });
  assert.equal(todayResponse.status, 200);
  const today = await todayResponse.json();
  assert.ok(today.items.length > 1);
  const panel = page.locator('section.boss-panel').filter({ has: page.getByRole('heading', { name: '本人事项与处理次序', exact: true }) });
  await panel.getByRole('button', { name: '降低事项次序：' + today.items[0].title, exact: true }).click();
  const savedOrder = page.waitForResponse(response => new URL(response.url()).pathname === '/api/boss/ui/today' && response.status() === 200);
  await page.getByRole('button', { name: '本人确认保存当前次序', exact: true }).click();
  const ordered = await (await savedOrder).json();
  assert.equal(Number(ordered.order_version), Number(today.order_version) + 1);
  const expectedOrder = today.items.map(item => item.item_id);
  [expectedOrder[0], expectedOrder[1]] = [expectedOrder[1], expectedOrder[0]];
  assert.deepEqual(ordered.items.map(item => item.item_id), expectedOrder);
  save('today_owner_order_persisted', { version: ordered.order_version, item_count: ordered.items.length });
  await page.goto('http://127.0.0.1:8872/?bossPage=N09', { waitUntil: 'domcontentloaded' });
  await page.getByRole('heading', { name: '本人计划列表', exact: true }).waitFor();
  const planResponse = await fetch('http://127.0.0.1:8872/api/boss/ui/owner-plans', { headers });
  assert.equal(planResponse.status, 200);
  const planData = await planResponse.json();
  const event = planData.events.find(item => item.state !== 'CANCELED');
  assert.ok(event);
  const dashboardResponse = await fetch('http://127.0.0.1:8872/api/boss/ui/dashboard', { headers });
  assert.equal(dashboardResponse.status, 200);
  const clock = (await dashboardResponse.json()).business_clock;
  const local = new Date(Date.parse(clock) + 9 * 3600000).toISOString().slice(0, 16);
  const purpose = '复查 ' + event.event_id + ' · ' + crypto.randomUUID();
  await page.getByLabel('计划用途', { exact: true }).fill(purpose);
  await page.getByLabel('时间条件（Asia/Shanghai）', { exact: true }).fill(local);
  await page.locator('label').filter({ hasText: event.event_id }).getByRole('checkbox').check();
  const approval = page.getByRole('checkbox', { name: '本人已核对当前范围、时间和本次操作后果', exact: true });
  await approval.check();
  const savePlan = page.waitForResponse(response => new URL(response.url()).pathname === '/api/boss/ui/owner-plans' && response.status() === 200);
  await page.getByRole('button', { name: '创建获准计划', exact: true }).click();
  const created = (await (await savePlan).json()).plans.find(plan => plan.purpose === purpose);
  assert.ok(created);
  save('owner_plan_saved', { plan_id: created.plan_id, state: created.state, version: created.version });
  for (const [action, state] of [['暂停', 'PAUSED'], ['恢复', 'ACTIVE'], ['取消', 'CANCELED']]) {
    const row = page.locator('button.boss-task-row').filter({ hasText: purpose });
    await row.click();
    await approval.check();
    const updated = page.waitForResponse(response => new URL(response.url()).pathname === '/api/boss/ui/owner-plans' && response.status() === 200);
    await page.getByRole('button', { name: action, exact: true }).click();
    const plan = (await (await updated).json()).plans.find(item => item.plan_id === created.plan_id);
    assert.equal(plan.state, state);
    save('owner_plan_transition', { plan_id: plan.plan_id, state: plan.state, version: plan.version });
  }
  await page.goto('http://127.0.0.1:8872/?bossPage=F01', { waitUntil: 'domcontentloaded' });
  await page.locator('.boss-v6[data-role="BOSS"]').waitFor();
}

async function main() {
  save('source_version', { commit: execFileSync('git', ['rev-parse', 'HEAD'], { cwd: path.join(root, '..'), encoding: 'utf8' }).trim(),
    source_hashes: Object.fromEntries(['app/webui/BossLogin.tsx', 'app/webui/BossDesktop.tsx', 'app/webui/boss-v6.css', 'validation/role_channel.py', 'validation/application.py']
      .map(file => [file, createHash('sha256').update(fs.readFileSync(path.join(root, '..', file))).digest('hex')])) });
  const { desktop, page } = await start();
  await page.locator('.boss-login, .boss-v6[data-role]').waitFor();
  save('public_auth_controls', await page.locator('.boss-login input').evaluateAll(inputs => inputs.map(input => ({
    id: input.id, type: input.type, disabled: input.disabled,
    labels: Array.from(input.labels || []).map(label => label.textContent),
    width: input.getBoundingClientRect().width, height: input.getBoundingClientRect().height,
    display: getComputedStyle(input).display, visibility: getComputedStyle(input).visibility,
  }))));
  if (await page.locator('.boss-v6[data-role]').count()) {
    await page.getByTitle('退出当前身份', { exact: true }).click();
    save('saved_session_restored_then_signed_out', true);
  }
  await page.getByLabel('本机访问凭据', { exact: true }).waitFor();
  await checkViewports(desktop, page, 'N01');
  assert.equal(await page.locator('.boss-sidebar').count(), 0);
  await page.getByRole('button', { name: '继续认证', exact: true }).click();
  await page.getByRole('alert').getByText('请输入本机访问凭据。', { exact: true }).waitFor();
  assert.equal(await page.getByLabel('本机访问凭据', { exact: true }).evaluate(element => element === document.activeElement), true);
  save('empty_credential_validation', { private_shell_present: false, focus_on_credential: true });
  const localAccess = JSON.parse(fs.readFileSync(path.join(root, '.work/application/access.json')));
  const credentialField = page.getByLabel('本机访问凭据', { exact: true });
  const contactBootstrap = await fetch('http://127.0.0.1:8872/webui/bootstrap', { headers: { 'X-Nanobot-Auth': localAccess.BOSS } });
  assert.equal(contactBootstrap.status, 200);
  const contactToken = (await contactBootstrap.json()).api_token;
  const dashboard = await fetch('http://127.0.0.1:8872/api/boss/ui/dashboard', { headers: { Authorization: 'Bearer ' + contactToken } });
  assert.equal(dashboard.status, 200);
  const contactId = (await dashboard.json()).contacts[0].contact_id;
  await credentialField.fill(contactId);
  await page.getByRole('button', { name: '继续认证', exact: true }).click();
  await page.getByRole('alert').getByText('访问凭据无效或已失效，请重新输入。', { exact: true }).waitFor();
  assert.equal(await page.locator('.boss-sidebar').count(), 0);
  save('contact_credential_rejected', { private_shell_present: false });
  await credentialField.fill(localAccess.MAINTAINER);
  await page.getByRole('button', { name: '继续认证', exact: true }).click();
  await page.getByRole('alert').getByText('凭据身份与所选入口不符，请核查入口与访问凭据。', { exact: true }).waitFor();
  assert.equal(await page.locator('.boss-sidebar').count(), 0);
  save('entry_scope_mismatch_rejected', { private_shell_present: false });
  await page.context().setOffline(true);
  await credentialField.fill(localAccess.BOSS);
  await page.getByRole('button', { name: '继续认证', exact: true }).click();
  await page.getByRole('alert').getByText('无法完成认证连接，请检查本机服务后重新尝试。', { exact: true }).waitFor();
  await page.context().setOffline(false);
  save('actual_network_unavailable', { private_shell_present: false });
  await login(page, 'BOSS');
  await checkViewports(desktop, page, 'BOSS');
  const status = await page.evaluate(() => window.bossDesktop.invoke({ action: 'status' }));
  assert.equal(status.versions.electron, '45.0.0');
  assert.equal(status.architecture, 'x64');
  assert.equal(await page.evaluate(() => typeof window.require), 'undefined');
  assert.equal(await page.evaluate(() => typeof window.process), 'undefined');
  save('host_isolation', { electron: status.versions.electron, architecture: status.architecture, service_pid: status.service_pid });
  await ownerActions(page, localAccess);
  const before = await snapshot();
  const access = JSON.parse(fs.readFileSync(path.join(root, '.work/application/access.json')));
  const bootstrap = await fetch('http://127.0.0.1:8872/webui/bootstrap', { headers: { 'X-Nanobot-Auth': access.BOSS } });
  assert.equal(bootstrap.status, 200);
  const previousToken = (await bootstrap.json()).api_token;
  for (const [width, height] of [[1024, 768], [1280, 800], [1440, 1024]]) {
    await desktop.evaluate(({ BrowserWindow }, size) => BrowserWindow.getAllWindows()[0].setContentSize(...size), [width, height]);
    assert.equal(await page.getByRole('button', { name: '今日工作', exact: true }).isVisible(), true);
    save('navigation_dom', { width, height });
  }
  await desktop.evaluate(({ BrowserWindow }) => BrowserWindow.getAllWindows()[0].webContents.setZoomFactor(2));
  assert.equal(await page.getByRole('button', { name: '今日工作', exact: true }).isVisible(), true);
  save('zoom_dom', { factor: 2 });
  await desktop.evaluate(({ BrowserWindow }) => BrowserWindow.getAllWindows()[0].webContents.setZoomFactor(1));
  await page.getByRole('button', { name: '经营关注', exact: true }).click();
  await page.waitForURL(/bossPage=N03/);
  await page.reload({ waitUntil: 'domcontentloaded' });
  await page.locator('.boss-v6[data-role="BOSS"]').waitFor();
  assert.equal(new URL(page.url()).searchParams.get('bossPage'), 'N03');
  save('page_reload_context', { page_id: 'N03' });
  await checkBounds(page, 'BOSS_AFTER_RELOAD');
  await roleCommand(localAccess.BOSS, 'boss.auth.logout', {});
  await page.getByRole('button', { name: '重新读取业务数据', exact: true }).click();
  await page.getByRole('heading', { name: '登录状态已过期', exact: true }).waitFor();
  await checkViewports(desktop, page, 'D08');
  assert.equal(await page.locator('.boss-sidebar').count(), 0);
  save('expired_identity_hides_private_shell', true);
  await login(page, 'BOSS');
  assert.deepEqual(await snapshot(), before);
  save('reauthentication_does_not_replay_business', true);
  await page.getByTitle('退出当前身份', { exact: true }).click();
  await login(page, 'MAINTAINER');
  await checkViewports(desktop, page, 'MAINTAINER');
  assert.equal(await page.getByRole('button', { name: '今日工作', exact: true }).count(), 0);
  assert.equal(await page.getByRole('button', { name: '模型连接', exact: true }).isVisible(), true);
  save('role_switch_dom', { role: 'MAINTAINER', boss_navigation_present: false });
  await page.getByRole('button', { name: '记忆技术维护', exact: true }).click();
  await page.getByRole('heading', { name: '记忆技术状态', exact: true }).waitFor();
  await page.getByRole('button', { name: '重新核查技术状态', exact: true }).waitFor();
  const memoryPanel = page.locator('section.boss-panel').filter({ has: page.getByRole('heading', { name: '记忆技术状态', exact: true }) });
  await memoryPanel.getByText('CONFIRMED', { exact: true }).waitFor();
  await page.getByRole('button', { name: '重新核查技术状态', exact: true }).click();
  await memoryPanel.getByText('CONFIRMED', { exact: true }).waitFor();
  save('memory_technical_dom', { role: 'MAINTAINER', read_only: true });
  await close(desktop);
  save('desktop_quit', { service_pid: status.service_pid });
  const restarted = await start();
  assert.deepEqual(await snapshot(), before);
  const instance = JSON.parse(fs.readFileSync(path.join(root, '.work/application/instance.json')));
  assert.notEqual(instance.pid, status.service_pid);
  const expired = await fetch('http://127.0.0.1:8872/api/boss/identity', { headers: { Authorization: 'Bearer ' + previousToken } });
  assert.equal(expired.status, 401);
  save('restart_rejects_previous_token', { status: expired.status });
  save('desktop_restart', { service_pid: instance.pid, task_and_outbox_unchanged: true });
  await close(restarted.desktop);
  save('scope', { visual_acceptance: 'NOT_RUN', model_tools: 'NOT_RUN', os_permissions: 'NOT_RUN' });
  console.log(JSON.stringify({ checks: records.length, evidence: output }));
}

main().finally(async () => {
  if (activeDesktop && activeDesktop.process().exitCode === null) await activeDesktop.close();
});
