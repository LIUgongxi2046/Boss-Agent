const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const { createHash } = require('node:crypto');
const { execFileSync } = require('node:child_process');
const { _electron: electron } = require('playwright');

const root = path.resolve(__dirname, '../..');
const validation = path.join(root, 'validation');
const pages = JSON.parse(fs.readFileSync(path.join(root, 'specs/page-service-map.json'))).pages;
const output = path.join(root, 'evidence/T09/w3-20261023/page-dom.json');
const records = [];

async function check() {
  const startedAt = new Date().toISOString();
  const desktop = await electron.launch({ args: [__dirname], cwd: validation, timeout: 60000,
    env: { ...process.env, BOSS_VALIDATION_ROOT: validation, BOSS_PRODUCT_UI: '1', TMPDIR: path.join(validation, '.work/tmp') } });
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
    await page.waitForURL('http://127.0.0.1:8872/');
    await page.locator('.boss-login, .boss-v6[data-role]').waitFor();
    if (await page.locator('.boss-v6[data-role]').count())
      await page.getByTitle('退出当前身份', { exact: true }).click();
    const access = JSON.parse(fs.readFileSync(path.join(validation, '.work/application/access.json')));
    for (const role of ['BOSS', 'MAINTAINER']) {
      await page.getByRole('radio', { name: role === 'BOSS' ? /^老板本人/ : /^技术维护/ }).check();
      await page.getByLabel('本机访问凭据', { exact: true }).fill(access[role]);
      await page.getByRole('button', { name: '继续认证', exact: true }).click();
      await page.locator('.boss-v6[data-role="' + role + '"]').waitFor();
      for (const entry of pages.filter(item => item.role_gate === role || item.role_gate === 'AUTHENTICATED_BOSS_OR_MAINTAINER')) {
        responses = [];
        await page.goto('http://127.0.0.1:8872/?bossPage=' + entry.page_id, { waitUntil: 'networkidle' });
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
        records.push({ page_id: entry.page_id, role, ...result, non_success_reads: [...responses] });
        fs.writeFileSync(output, JSON.stringify({
          status: 'IN_PROGRESS', scope: '页面渲染与DOM；完整动作、561状态及视觉未验收', records,
        }, null, 2));
      }
      await page.getByTitle('退出当前身份', { exact: true }).click();
      await page.getByLabel('本机访问凭据', { exact: true }).waitFor();
    }
    const visited = new Set(records.map(row => row.page_id));
    assert.equal(visited.size, pages.filter(row => row.role_gate !== 'ANONYMOUS').length);
    const report = {
      status: 'PASS_RENDER_NO_PAGEERROR_ONLY',
      started_at: startedAt, finished_at: new Date().toISOString(),
      commit: execFileSync('git', ['rev-parse', 'HEAD'], { cwd: root, encoding: 'utf8' }).trim(),
      component_sha256: createHash('sha256').update(fs.readFileSync(path.join(root, 'app/webui/BossDesktop.tsx'))).digest('hex'),
      visited_pages: visited.size, role_page_observations: records.length,
      anonymous_pages: { page_ids: ['N01', 'D08'], evidence: 'evidence/T11/w3-local-20261023/desktop.json' },
      renderer_errors: errors, records, business_actions_verified: false,
      state_561_coverage_verified: false, visual_acceptance: 'NOT_RUN', full_A08_A09_accepted: false,
    };
    fs.writeFileSync(output, JSON.stringify(report, null, 2));
    console.log(JSON.stringify({ status: report.status, pages: visited.size, observations: records.length }));
  } finally {
    await desktop.close();
  }
}

check();
