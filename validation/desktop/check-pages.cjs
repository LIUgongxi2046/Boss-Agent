const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const { createHash, randomUUID } = require('node:crypto');
const { execFileSync } = require('node:child_process');
const { _electron: electron } = require('playwright');

const root = path.resolve(__dirname, '../..');
const validation = path.join(root, 'validation');
const pages = JSON.parse(fs.readFileSync(path.join(root, 'specs/page-service-map.json'))).pages;
const runId = 'page-dom-' + randomUUID();
const directory = path.join(validation, '.work', runId);
const ports = {business: 8971, webui: 8972, gateway: 18971};
const origin = 'http://127.0.0.1:8972';
const output = path.join(root, 'evidence/T09/w3-20261023', runId + '.json');
const records = [];
const inputs = ['specs/page-service-map.json', 'app/webui/BossDesktop.tsx', 'app/webui/MaintainerSkillVersions.tsx',
  'app/webui/MaintainerSkills.tsx', 'app/webui/BossSectorView.tsx', 'validation/boss_page_api.py',
  'validation/product_skills.py', 'validation/desktop/check-pages.cjs',
  '.work/product/nanobot/nanobot/web/dist/asset-manifest.json'].map(file => ({path: file,
    sha256: createHash('sha256').update(fs.readFileSync(path.join(root, file))).digest('hex')}));
function manifest() {return JSON.parse(execFileSync(path.join(validation, '.venv/bin/python'), [
  path.join(root, 'evidence/T12/check_simulation_reads.py'), '--database', path.join(directory, 'business.sqlite'),
], {cwd: root, encoding: 'utf8'}));}

async function check() {
  const startedAt = new Date().toISOString();
  const desktop = await electron.launch({ args: [__dirname], cwd: validation, timeout: 60000,
    env: { ...process.env, BOSS_VALIDATION_ROOT: validation, BOSS_PRODUCT_UI: '1', BOSS_APPLICATION_WORK_DIR: directory,
      BOSS_APPLICATION_PORTS: JSON.stringify(ports), BOSS_DESKTOP_TEST_WINDOW_HIDDEN: '1', TMPDIR: path.join(validation, '.work/tmp') } });
  try {
    const page = await desktop.firstWindow({ timeout: 120000 });
    const errors = [];
    let responses = [];
    page.on('pageerror', error => errors.push({ name: error.name }));
    page.on('response', response => {
      const address = new URL(response.url());
      if (address.pathname.startsWith('/api/boss/ui/') && response.status() >= 400)
        responses.push({ path: address.pathname, status: response.status() });
    });
    await page.waitForURL(origin + '/');
    const access = JSON.parse(fs.readFileSync(path.join(directory, 'access.json')));
    const before = manifest();
    for (const role of ['BOSS', 'MAINTAINER']) {
      await page.getByRole('radio', { name: role === 'BOSS' ? /^老板本人/ : /^技术维护/ }).check();
      await page.getByLabel('本机访问凭据', { exact: true }).fill(access[role]);
      await page.getByRole('button', { name: '继续认证', exact: true }).click();
      await page.locator('.boss-v6[data-role="' + role + '"]').waitFor();
      for (const entry of pages.filter(item => item.role_gate === role || item.role_gate === 'AUTHENTICATED_BOSS_OR_MAINTAINER')) {
        responses = [];
        await page.goto(origin + '/?bossPage=' + entry.page_id, { waitUntil: 'networkidle' });
        await page.locator('.boss-v6[data-role="' + role + '"]').waitFor();
        const marker = page.locator('.boss-hero .boss-eyebrow');
        await marker.filter({ hasText: '· ' + entry.page_id }).waitFor();
        assert.equal(errors.length, 0, entry.page_id + ': renderer error');
        const result = await page.locator('.boss-main').evaluate(element => ({
          headings: element.querySelectorAll('h1,h2,h3').length,
          buttons: element.querySelectorAll('button').length,
          fields: element.querySelectorAll('input,select,textarea').length,
          horizontal_overflow: document.documentElement.scrollWidth > innerWidth + 1,
        }));
        assert.ok(result.headings > 0);
        assert.equal(result.horizontal_overflow, false, entry.page_id + ': horizontal overflow');
        assert.deepEqual(responses, [], entry.page_id + ': non-success reads');
        records.push({ page_id: entry.page_id, role, ...result, non_success_reads: [...responses] });
        fs.writeFileSync(output, JSON.stringify({
          status: 'IN_PROGRESS', scope: '页面渲染与DOM；完整动作、561状态及视觉未验收', records, inputs,
          application_directory: path.relative(root, directory), model_requested: false, external_api_mode: 'SIMULATED_FIRST',
        }, null, 2));
      }
      await page.getByTitle('退出当前身份', { exact: true }).click();
      await page.getByLabel('本机访问凭据', { exact: true }).waitFor();
    }
    const visited = new Set(records.map(row => row.page_id));
    assert.equal(visited.size, pages.filter(row => row.role_gate !== 'ANONYMOUS').length);
    const after = manifest(); assert.deepEqual(after.before_tables_sha256, before.before_tables_sha256);
    const report = {
      status: 'PASS_RENDER_NO_PAGEERROR_ONLY',
      started_at: startedAt, finished_at: new Date().toISOString(),
      commit: execFileSync('git', ['rev-parse', 'HEAD'], { cwd: root, encoding: 'utf8' }).trim(),
      inputs, application_directory: path.relative(root, directory), ports, model_requested: false,
      external_api_mode: 'SIMULATED_FIRST', business_tables_sha256: after.after_tables_sha256,
      initial_snapshot_sha256: after.initial_snapshot_sha256,
      component_sha256: createHash('sha256').update(fs.readFileSync(path.join(root, 'app/webui/BossDesktop.tsx'))).digest('hex'),
      visited_pages: visited.size, role_page_observations: records.length,
      anonymous_pages: { page_ids: ['N01', 'D08'], evidence: 'evidence/T11/w3-local-20261023/desktop.json' },
      renderer_errors: errors, records, business_actions_verified: false,
      state_561_coverage_verified: false, visual_acceptance: 'NOT_RUN', full_A08_A09_accepted: false,
    };
    fs.writeFileSync(output, JSON.stringify(report, null, 2));
    console.log(JSON.stringify({ status: report.status, pages: visited.size, observations: records.length, evidence: output }));
  } finally {
    await desktop.close();
  }
}

check();
