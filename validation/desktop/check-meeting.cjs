const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const { createHash } = require('node:crypto');
const { execFileSync } = require('node:child_process');
const { _electron: electron } = require('playwright');

const root = path.resolve(__dirname, '../..');
const validation = path.join(root, 'validation');
const output = path.join(root, 'evidence/T11/w3-local-20261023/meeting-desktop.json');
const records = [];
const sourcePaths = ['app/webui/BossDesktop.tsx', 'app/webui/BossMeetingBrief.tsx',
  'app/webui/BossMeetingArrangement.tsx', 'validation/boss_command_api.py',
  'validation/boss_page_api.py', 'validation/boss_workspace_api.py', 'validation/boss_meetings.py'];

function save(status) {
  fs.writeFileSync(output, JSON.stringify({ status, at: new Date().toISOString(),
    commit: execFileSync('git', ['rev-parse', 'HEAD'], { cwd: root, encoding: 'utf8' }).trim(),
    inputs: sourcePaths.map(file => ({ path: file,
      sha256: createHash('sha256').update(fs.readFileSync(path.join(root, file))).digest('hex') })),
    records, source_type: 'SIMULATED', visual_acceptance: 'NOT_RUN',
    terminal_ui_actions_verified: false, full_A11_accepted: false,
  }, null, 2));
}

async function check() {
  const desktop = await electron.launch({ args: [__dirname], cwd: validation, timeout: 60000,
    env: { ...process.env, BOSS_VALIDATION_ROOT: validation, BOSS_PRODUCT_UI: '1', TMPDIR: path.join(validation, '.work/tmp') } });
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
    await page.waitForURL('http://127.0.0.1:8872/');
    await page.locator('.boss-login, .boss-v6[data-role]').waitFor();
    if (await page.locator('.boss-v6[data-role]').count())
      await page.getByTitle('退出当前身份', { exact: true }).click();
    const access = JSON.parse(fs.readFileSync(path.join(validation, '.work/application/access.json')));
    await page.getByRole('radio', { name: /^老板本人/ }).check();
    await page.getByLabel('本机访问凭据', { exact: true }).fill(access.BOSS);
    await page.getByRole('button', { name: '继续认证', exact: true }).click();
    await page.locator('.boss-v6[data-role="BOSS"]').waitFor();
    const bootstrap = await fetch('http://127.0.0.1:8872/webui/bootstrap', { headers: { 'X-Nanobot-Auth': access.BOSS } });
    assert.equal(bootstrap.status, 200);
    const headers = { Authorization: 'Bearer ' + (await bootstrap.json()).api_token };
    async function read(route) {
      const response = await fetch('http://127.0.0.1:8872/api/boss/ui/' + route, { headers });
      assert.equal(response.status, 200, route);
      return response.json();
    }
    async function businessHashes() {
      const hashes = {};
      for (const kind of ['task', 'outbox']) {
        const response = await fetch('http://127.0.0.1:8871/spaces/ui-check/objects/' + kind,
          { headers: { Authorization: 'Bearer ' + access.BOSS } });
        assert.equal(response.status, 200);
        hashes[kind] = createHash('sha256').update(await response.text()).digest('hex');
      }
      return hashes;
    }
    const before = await read('meeting-arrangement');
    assert.ok(!['HELD', 'CANCELED'].includes(before.meeting.state));
    const businessBefore = await businessHashes();
    const calendar = (await read('workspace/calendar')).calendar;
    const source = await read('evidence?source=finance-note');
    await page.goto('http://127.0.0.1:8872/?bossPage=F04', { waitUntil: 'networkidle' });
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
    save('PASS_MEETING_DRAFT_CONFIRM_REFRESH_ONLY');
    console.log(JSON.stringify({ status: 'PASS_MEETING_DRAFT_CONFIRM_REFRESH_ONLY', observations: records.length }));
  } finally {
    await desktop.close();
  }
}

check();
