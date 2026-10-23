const path = require('node:path');
const fs = require('node:fs');
const assert = require('node:assert/strict');
const { _electron } = require('./harness/node_modules/playwright');
const root = path.resolve(__dirname, '../..');
process.env.TMPDIR = path.join(root, 'validation/.work/t27/tmp');
async function main() {
  const application = await _electron.launch({ args: [path.join(__dirname, 'desktop-host.cjs')],
    executablePath: '/Users/liuhaoxian/.codex/worktrees/boss-integration/Boss-Agent/validation/desktop/node_modules/electron/dist/Electron.app/Contents/MacOS/Electron',
    env: { ...process.env }, cwd: root });
  try {
    const page = await application.firstWindow();
    await page.evaluate(() => { document.title = '页面内容'; });
    const result = await application.evaluate(({ app, BrowserWindow, nativeImage }, image) => {
      const window = BrowserWindow.getAllWindows()[0];
      return { name: app.getName(), title: window.getTitle(), image: !nativeImage.createFromPath(image).isEmpty(),
        profile: app.getPath('userData'), versions: process.versions };
    }, path.join(root, 'validation/desktop/branding/boss-agent.png'));
    assert.equal(result.name, 'Boss Agent'); assert.equal(result.title, 'Boss Agent'); assert.equal(result.image, true);
    assert.ok(result.profile.startsWith(path.join(root, 'validation/.work/t27-native')));
    fs.writeFileSync(path.join(root, 'evidence/T27/native-brand.json'), JSON.stringify({ status: 'PASS_NATIVE_HOST_ONLY', result, installed_application: 'NOT_RUN', visual: 'NOT_RUN' }, null, 2));
  } finally { await application.close(); }
  console.log('独立原生宿主名称及图标检查通过');
}
main().catch(error => { console.error(error.name, error.message); process.exitCode = 1; });
