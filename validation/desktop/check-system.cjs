const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const { randomUUID } = require('node:crypto');
const { _electron: electron } = require('playwright');

const root = path.resolve(__dirname, '..');
const work = path.join(root, '.work/system-check');
fs.mkdirSync(work, { recursive: true });
const output = path.join(root, '../evidence/T02/system-' + randomUUID());
fs.mkdirSync(output);
const executable = path.join(root, '.work/installed/Boss-Agent-Validation-darwin-x64/Boss-Agent-Validation.app/Contents/MacOS/Boss-Agent-Validation');
const records = [];
let desktop;
let processHandle;

function save(check, result) {
  records.push({ at: new Date().toISOString(), check, result });
  fs.writeFileSync(path.join(output, 'checks.json'), JSON.stringify(records, null, 2));
  fs.writeFileSync(path.join(work, 'status.json'), JSON.stringify({ at: new Date().toISOString(), evidence: output, check, result }, null, 2));
}

async function main() {
  desktop = await electron.launch({ executablePath: executable, args: [], cwd: root, env: { ...process.env, BOSS_VALIDATION_ROOT: root, TMPDIR: path.join(root, '.work/tmp') }, timeout: 60000 });
  processHandle = desktop.process();
  const page = await desktop.firstWindow();
  await page.waitForURL('http://127.0.0.1:8872/', { waitUntil: 'domcontentloaded' });
  await page.waitForLoadState('networkidle');
  await desktop.evaluate(({ BrowserWindow }) => BrowserWindow.getAllWindows()[0].webContents.setZoomFactor(1));
  const access = JSON.parse(fs.readFileSync(path.join(root, '.work/application/access.json')));
  const response = await fetch('http://127.0.0.1:8872/webui/bootstrap', { headers: { 'X-Nanobot-Auth': access.BOSS } });
  assert.equal(response.status, 200);
  const token = (await response.json()).api_token;
  const invoke = (action, extra = {}) => page.evaluate(request => window.bossDesktop.invoke(request), { action, token, ...extra });
  const status = await invoke('status');
  save('installed_app_started', { executable, status });
  let sequence = 0;
  const deadline = Date.now() + 30 * 60 * 1000;
  while (Date.now() < deadline) {
    const commandPath = path.join(work, 'command.json');
    if (!fs.existsSync(commandPath)) { await new Promise(resolve => setTimeout(resolve, 200)); continue; }
    const command = JSON.parse(fs.readFileSync(commandPath));
    assert.equal(typeof command.sequence, 'number');
    if (command.sequence <= sequence) { await new Promise(resolve => setTimeout(resolve, 200)); continue; }
    sequence = command.sequence;
    if (command.action === 'quit') { save('completed_system_session', { sequence }); return; }
    if (command.action === 'microphone_request') {
      save('microphone_request_started', { before: await invoke('microphone_status') });
      const allowed = await invoke('request_microphone');
      save('os_microphone_request_result', { allowed, after: await invoke('microphone_status') });
    } else if (command.action === 'capture_start') {
      await page.evaluate(async () => { window.permissionCheckStream = await navigator.mediaDevices.getUserMedia({ audio: true }); });
      save('actual_microphone_capture_started', await page.evaluate(() => window.permissionCheckStream.getTracks().map(track => ({ kind: track.kind, readyState: track.readyState, muted: track.muted }))));
    } else if (command.action === 'capture_check') {
      save('actual_microphone_capture_state', { os: await invoke('microphone_status'), tracks: await page.evaluate(() => window.permissionCheckStream.getTracks().map(track => ({ kind: track.kind, readyState: track.readyState, muted: track.muted }))) });
    } else if (command.action === 'capture_stop') {
      save('microphone_capture_stopped', await page.evaluate(() => { for (const track of window.permissionCheckStream.getTracks()) track.stop(); return window.permissionCheckStream.getTracks().map(track => ({ kind: track.kind, readyState: track.readyState })); }));
    } else if (command.action === 'notify') {
      save('system_notification_request', await invoke('notify'));
    } else if (command.action === 'file_dialog') {
      save('file_dialog_requested', { directory: path.join(root, '.work/materials') });
      save('native_file_selection', await invoke('select_file'));
    } else if (command.action === 'open_source') {
      save('external_source_opened', await invoke('open_source', { url: 'https://api-docs.deepseek.com/' }));
    } else if (command.action === 'state') {
      const state = {};
      for (const kind of ['task', 'outbox', 'notification']) {
        const response = await fetch('http://127.0.0.1:8871/spaces/ui-check/objects/' + kind, { headers: { Authorization: 'Bearer ' + access.BOSS } });
        assert.equal(response.status, 200);
        state[kind] = await response.json();
      }
      save('persistent_state', { sequence, status: await invoke('status'), task_ids: state.task.map(task => task.task_id), task_statuses: state.task.map(task => task.status), outbox_count: state.outbox.length, notification_count: state.notification.length });
    } else if (command.action === 'microphone_status') {
      save('os_microphone_status', { state: await invoke('microphone_status') });
    } else {
      throw new Error('系统检查动作无效');
    }
  }
  throw new Error('系统检查等待超过允许时间');
}

main().finally(async () => {
  if (desktop && processHandle.exitCode === null) await desktop.close();
});
