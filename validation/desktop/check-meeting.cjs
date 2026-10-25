const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const { createHash, randomUUID } = require('node:crypto');
const { once } = require('node:events');
const { execFileSync } = require('node:child_process');
const { _electron: electron } = require('playwright');

const root = path.resolve(__dirname, '../..');
const validation = path.join(root, 'validation');
const ports = { business: 8971, webui: 8972, gateway: 18971 };
const origin = 'http://127.0.0.1:' + ports.webui;
const businessOrigin = 'http://127.0.0.1:' + ports.business;
const websocketOrigin = 'ws://127.0.0.1:' + ports.webui;
const terminalAction = process.argv[2];
assert.ok(['cancel', 'held'].includes(terminalAction), '需要指定cancel或held检查');
const runId = 'meeting-' + terminalAction + '-' + randomUUID();
const applicationDirectory = path.join(validation, '.work', runId);
const output = path.join(root, 'evidence/T11/w3-local-20261023', runId + '.json');
const records = [];
const sourcePaths = ['app/webui/BossDesktop.tsx', 'app/webui/BossMeetingBrief.tsx',
  'app/webui/BossMeetingArrangement.tsx', 'validation/boss_command_api.py',
  'validation/boss_page_api.py', 'validation/boss_workspace_api.py', 'validation/boss_meetings.py',
  'validation/application.py', 'validation/application_paths.py', 'validation/desktop/main.cjs',
  'validation/desktop/check-meeting.cjs', '.work/product/nanobot/nanobot/web/dist/asset-manifest.json'];

function save(status) {
  fs.writeFileSync(output, JSON.stringify({ status, at: new Date().toISOString(),
    commit: execFileSync('git', ['rev-parse', 'HEAD'], { cwd: root, encoding: 'utf8' }).trim(),
    inputs: sourcePaths.map(file => ({ path: file,
      sha256: createHash('sha256').update(fs.readFileSync(path.join(root, file))).digest('hex') })),
    records, source_type: 'SIMULATED', visual_acceptance: 'NOT_RUN',
    run_id: runId, terminal_action: terminalAction, ports, full_A11_accepted: false,
  }, null, 2));
}

async function launch() {
  return electron.launch({ args: [__dirname], cwd: validation, timeout: 60000,
    env: { ...process.env, BOSS_VALIDATION_ROOT: validation, BOSS_PRODUCT_UI: '1',
      BOSS_APPLICATION_WORK_DIR: applicationDirectory, BOSS_APPLICATION_PORTS: JSON.stringify(ports),
      TMPDIR: path.join(validation, '.work/tmp') } });
}

async function loginOwner(page, access) {
  await page.waitForURL(origin + '/');
  await page.locator('.boss-login, .boss-v6[data-role]').waitFor();
  if (await page.locator('.boss-v6[data-role]').count())
    await page.getByTitle('退出当前身份', { exact: true }).click();
  await page.getByRole('radio', { name: /^老板本人/ }).check();
  await page.getByLabel('本机访问凭据', { exact: true }).fill(access.BOSS);
  await page.getByRole('button', { name: /^(继续认证|重新认证)$/ }).click();
  await page.locator('.boss-v6[data-role="BOSS"]').waitFor();
}

async function roleCommand(secret, action, payload) {
  const response = await fetch(origin + '/webui/bootstrap', { headers: { 'X-Nanobot-Auth': secret } });
  assert.equal(response.status, 200);
  const boot = await response.json();
  const socket = new WebSocket(websocketOrigin + boot.ws_path + '?token=' + encodeURIComponent(boot.token));
  try {
    await once(socket, 'open', { signal: AbortSignal.timeout(15000) });
    const requestId = randomUUID();
    socket.send(JSON.stringify({ type: 'webui_request', request_id: requestId, action, payload }));
    while (true) {
      const [message] = await once(socket, 'message', { signal: AbortSignal.timeout(15000) });
      const frame = JSON.parse(message.data);
      if (frame.request_id === requestId) {
        assert.equal(frame.ok, true);
        return frame.result;
      }
    }
  } finally {
    socket.close();
  }
}

async function check() {
  let desktop = await launch();
  try {
    const page = await desktop.firstWindow({ timeout: 120000 });
    const errors = [];
    page.on('framenavigated', frame => {
      if (frame === page.mainFrame()) {
        const address = new URL(frame.url());
        records.push({ check: 'document_navigation', pathname: address.pathname, page_id: address.searchParams.get('bossPage') });
        save('IN_PROGRESS');
      }
    });
    page.on('pageerror', error => errors.push({ name: error.name }));
    const access = JSON.parse(fs.readFileSync(path.join(applicationDirectory, 'access.json')));
    await loginOwner(page, access);
    const bootstrap = await fetch(origin + '/webui/bootstrap', { headers: { 'X-Nanobot-Auth': access.BOSS } });
    assert.equal(bootstrap.status, 200);
    let headers = { Authorization: 'Bearer ' + (await bootstrap.json()).api_token };
    async function read(route) {
      const response = await fetch(origin + '/api/boss/ui/' + route, { headers });
      assert.equal(response.status, 200, route);
      return response.json();
    }
    async function businessHashes() {
      const hashes = {};
      for (const kind of ['task', 'outbox']) {
        const response = await fetch(businessOrigin + '/spaces/ui-check/objects/' + kind,
          { headers: { Authorization: 'Bearer ' + access.BOSS } });
        assert.equal(response.status, 200);
        hashes[kind] = createHash('sha256').update(await response.text()).digest('hex');
      }
      return hashes;
    }
    const before = await read('meeting-arrangement');
    assert.ok(!['HELD', 'CANCELED'].includes(before.meeting.state));
    const calendar = (await read('workspace/calendar')).calendar;
    const source = await read('evidence?source=finance-note');
    const dashboard = await read('dashboard');
    const coordinator = before.meeting.participant_ids[0];
    const created = await roleCommand(access.BOSS, 'boss.assignment.create', {
      client_request_id: runId + '-assignment', purpose: source.content, coordinator_id: coordinator,
      due_at: calendar.ends_at, timezone: calendar.timezone, evidence_requirements: [source.content],
      related_meeting_id: before.meeting.meeting_id, related_event_ids: [dashboard.event.event_id],
      source_refs: [source.source_id], content_version: '1',
    });
    await roleCommand(access.BOSS, 'boss.assignment.send', {
      client_request_id: runId + '-send', task_id: created.task_id, task_version: created.version,
      recipient_id: coordinator, body: source.content, content_version: '1',
    });
    const businessBefore = await businessHashes();
    assert.equal((await read('tasks')).tasks.find(task => task.task_id === created.task_id).status, 'WAITING_FEEDBACK');
    records.push({ check: 'independent_owner_authorized_assignment', task_id: created.task_id,
      state: 'WAITING_FEEDBACK', source_type: 'SIMULATED' });
    await page.goto(origin + '/?bossPage=F04', { waitUntil: 'networkidle' });
    const panel = page.locator('section.boss-panel').filter({ has: page.getByRole('heading', { name: '本人会议安排', exact: true }) });
    await panel.getByLabel('会议目的', { exact: true }).fill(source.content);
    await panel.getByLabel('开始时间（保留UTC时差）', { exact: true }).fill(calendar.starts_at);
    await panel.getByLabel('结束时间（保留UTC时差）', { exact: true }).fill(calendar.ends_at);
    await panel.getByLabel('IANA时区', { exact: true }).fill(calendar.timezone);
    await page.getByTitle('任务与承诺', { exact: true }).click();
    const unsaved = page.getByRole('dialog', { name: '未保存修改（D06）' });
    await unsaved.waitFor();
    await unsaved.getByRole('button', { name: '返回继续编辑', exact: true }).click();
    records.push({ check: 'return_to_meeting_editing', page_id: new URL(page.url()).searchParams.get('bossPage'),
      arrangement_panels: await panel.count(), unsaved_dialogs: await unsaved.count(), renderer_errors: [...errors],
      fields: await panel.locator('input,textarea').evaluateAll(fields => fields.map(field => ({
        tag: field.tagName, type: field.type, labels: Array.from(field.labels || []).map(label => ({
          prefix: label.textContent.slice(0, 4), length: label.textContent.length,
        })),
      }))) });
    save('IN_PROGRESS');
    assert.equal(new URL(page.url()).searchParams.get('bossPage'), 'F04');
    assert.equal(await panel.getByRole('textbox', { name: /^会议目的/ }).inputValue(), source.content);
    records.push({ check: 'unsaved_meeting_navigation_preserves_input', passed: true });
    const savedRead = page.waitForResponse(response => new URL(response.url()).pathname === '/api/boss/ui/meeting-arrangement' && response.status() === 200);
    await panel.getByRole('button', { name: '保存草稿并核查影响', exact: true }).click();
    const saved = await (await savedRead).json();
    assert.deepEqual(saved.meeting, before.meeting);
    assert.equal(saved.draft.state, 'DRAFT');
    assert.equal(saved.draft.review_current, true);
    records.push({ check: 'draft_preserves_current_meeting', version: saved.draft.version, current_version: saved.meeting.version });
    const tab = page.getByRole('button', { name: /^历史承诺/ });
    await tab.click();
    await panel.getByRole('button', { name: '确认当前草稿', exact: true }).click();
    await panel.getByLabel('本人已核查保存草稿中的时间、参会范围、材料及安排冲突', { exact: true }).check();
    await panel.getByLabel('本人授权本次操作', { exact: true }).check();
    const currentRead = page.waitForResponse(response => new URL(response.url()).pathname === '/api/boss/ui/meeting-arrangement' && response.status() === 200);
    const briefRead = page.waitForResponse(response => new URL(response.url()).pathname === '/api/boss/ui/workspace/briefing' && response.status() === 200);
    await panel.getByRole('button', { name: '提交本人决定', exact: true }).click();
    const current = await (await currentRead).json();
    const brief = await (await briefRead).json();
    assert.equal(current.meeting.state, 'SCHEDULED');
    assert.equal(Number(current.meeting.version), Number(before.meeting.version) + 1);
    assert.equal(current.meeting.ends_at, calendar.ends_at);
    assert.equal(brief.current.meeting.version, current.meeting.version);
    assert.equal(await tab.getAttribute('aria-current'), 'page');
    assert.equal(current.invitation_sent, false);
    assert.deepEqual(await businessHashes(), businessBefore);
    records.push({ check: 'owner_confirmation_refreshes_brief_and_preserves_tab', meeting_version: current.meeting.version,
      current_brief_version: brief.current.meeting.version, invitation_sent: false, independent_business_unchanged: true });
    await page.reload({ waitUntil: 'networkidle' });
    await page.getByRole('heading', { name: '本人会议安排', exact: true }).waitFor();
    assert.equal((await read('meeting-arrangement')).meeting.version, current.meeting.version);
    assert.equal(errors.length, 0);
    const bounds = await page.locator('.boss-main').evaluate(() => ({
      horizontal_overflow: document.documentElement.scrollWidth > innerWidth + 1,
    }));
    assert.equal(bounds.horizontal_overflow, false);
    records.push({ check: 'reload_reads_persisted_meeting', meeting_version: current.meeting.version, renderer_errors: errors, ...bounds });
    if (terminalAction === 'held') {
      await roleCommand(access.MAINTAINER, 'boss.simulation.clock.advance', {
        client_request_id: runId + '-clock', at: current.meeting.starts_at,
      });
      const clockRead = page.waitForResponse(response => new URL(response.url()).pathname === '/api/boss/ui/meeting-arrangement' && response.status() === 200);
      await panel.getByRole('button', { name: '读取会议与核查结果', exact: true }).click();
      assert.equal((await (await clockRead).json()).business_at, current.meeting.starts_at);
    }
    const terminalState = terminalAction === 'held' ? 'HELD' : 'CANCELED';
    await panel.getByRole('button', { name: terminalAction === 'held' ? '确认会议已经举行' : '取消当前会议', exact: true }).click();
    await panel.getByLabel('本次决定依据', { exact: true }).fill(source.content);
    await panel.getByLabel('本人授权本次操作', { exact: true }).check();
    const terminalRead = page.waitForResponse(response => new URL(response.url()).pathname === '/api/boss/ui/meeting-arrangement' && response.status() === 200);
    await panel.getByRole('button', { name: '提交本人决定', exact: true }).click();
    const terminal = await (await terminalRead).json();
    assert.equal(terminal.meeting.state, terminalState);
    assert.equal(Number(terminal.meeting.version), Number(current.meeting.version) + 1);
    for (const label of ['确认当前草稿', '取消当前会议', '确认会议已经举行'])
      assert.equal(await panel.getByRole('button', { name: label, exact: true }).isDisabled(), true);
    assert.deepEqual(await businessHashes(), businessBefore);
    records.push({ check: 'explicit_owner_terminal_action', state: terminalState,
      meeting_version: terminal.meeting.version, independent_business_unchanged: true });
    save('IN_PROGRESS');
    const previousHeaders = headers;
    const previousPid = JSON.parse(fs.readFileSync(path.join(applicationDirectory, 'instance.json'))).pid;
    await desktop.close();
    desktop = await launch();
    const restartedPage = await desktop.firstWindow({ timeout: 120000 });
    await loginOwner(restartedPage, access);
    const restartedBootstrap = await fetch(origin + '/webui/bootstrap', { headers: { 'X-Nanobot-Auth': access.BOSS } });
    assert.equal(restartedBootstrap.status, 200);
    headers = { Authorization: 'Bearer ' + (await restartedBootstrap.json()).api_token };
    assert.equal((await fetch(origin + '/api/boss/identity', { headers: previousHeaders })).status, 401);
    const reopened = (await read('meeting-arrangement')).meeting;
    assert.equal(reopened.state, terminalState);
    assert.equal(reopened.version, terminal.meeting.version);
    assert.notEqual(JSON.parse(fs.readFileSync(path.join(applicationDirectory, 'instance.json'))).pid, previousPid);
    await restartedPage.goto(origin + '/?bossPage=F04', { waitUntil: 'networkidle' });
    await restartedPage.getByRole('heading', { name: '本人会议安排', exact: true }).waitFor();
    assert.equal(await restartedPage.getByRole('button', { name: '取消当前会议', exact: true }).isDisabled(), true);
    assert.deepEqual(await businessHashes(), businessBefore);
    assert.notEqual(fs.realpathSync(applicationDirectory), fs.realpathSync(path.join(validation, '.work/application')));
    records.push({ check: 'service_restart_preserves_terminal_meeting', state: terminalState,
      meeting_version: reopened.version, previous_token_status: 401, application_directory_isolated: true });
    save('PASS_MEETING_TERMINAL_AND_RESTART_ONLY');
    console.log(JSON.stringify({ status: 'PASS_MEETING_TERMINAL_AND_RESTART_ONLY', observations: records.length, evidence: output }));
  } finally {
    await desktop.close();
  }
}

process.on('uncaughtExceptionMonitor', error => {
  records.push({ check: 'uncaught_failure', name: error.name });
  save('FAILED_CHECK');
});

check();
