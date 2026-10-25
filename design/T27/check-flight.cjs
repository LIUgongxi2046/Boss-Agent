const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const { spawn } = require('node:child_process');
const { once } = require('node:events');
const { createHash } = require('node:crypto');
const { chromium } = require('./harness/node_modules/playwright');
const root = path.resolve(__dirname, '../..');
const work = path.join(root, 'validation/.work/t27-native-zoom/service');
const dist = path.join(root, '.work/t27-native-zoom/dist/boss-brand');
const hash = file => createHash('sha256').update(fs.readFileSync(file)).digest('hex');
const sources = JSON.parse(fs.readFileSync(path.join(root, '.work/t27-native-zoom/build-source.json')));
// 上游源码在构建时核查，运行期间通过完整产物校验和绑定该构建版本。
const productSources = Object.entries(sources).filter(([file]) => file.startsWith(root + path.sep));
for (const [file, expected] of productSources) assert.equal(hash(file), expected);
fs.mkdirSync(path.join(work, 'tmp'), { recursive: true });
process.env.TMPDIR = path.join(work, 'tmp');
fs.mkdirSync(dist, { recursive: true });
for (const name of ['boss-logo-from-reference.png', 'dapeng-front.png']) {
  fs.copyFileSync(path.join(root, 'Boss-Agent-Desktop-Complete-v6/assets', name), path.join(dist, name));
}
fs.copyFileSync(path.join(__dirname, 'assets/boss-flight-sprite.png'), path.join(dist, 'boss-flight-sprite.png'));
const build = path.dirname(dist);
const artifacts = Object.fromEntries(fs.readdirSync(build, { recursive: true, withFileTypes: true }).filter(entry => entry.isFile())
  .map(entry => { const file = path.join(entry.parentPath, entry.name); return [path.relative(build, file), hash(file)]; }));

async function main() {
  const log = fs.openSync(path.join(work, 'flight-service.log'), 'a', 0o600);
  const service = spawn(path.join(root, 'validation/.venv/bin/python'), [path.join(__dirname, 'server.py')], {
    cwd: root, env: { ...process.env, BOSS_T27_NATIVE_ZOOM: '1', BOSS_T27_REVIEW: '0', BOSS_T27_PREVIEW: '0' },
    stdio: ['ignore', 'pipe', log],
  });
  let browser;
  try {
    await once(service.stdout, 'data', { signal: AbortSignal.timeout(90000) });
    const instance = JSON.parse(fs.readFileSync(path.join(work, 'instance.json')));
    assert.equal(instance.pid, service.pid); assert.notEqual(instance.port, 8872);
    browser = await chromium.launch({ executablePath: '/Applications/Google Chrome.app/Contents/MacOS/Google Chrome', headless: true });
    const page = await browser.newPage({ viewport: { width: 1280, height: 800 } });
    const errors = [];
    page.on('pageerror', error => errors.push(error.message));
    await page.goto(`http://127.0.0.1:${instance.port}`);
    await page.locator('[data-heading]').waitFor({ timeout: 5000 });
    await page.evaluate(() => document.fonts.ready.then(() => undefined));
    const layers = await page.locator('.boss-login-flight').evaluate(layer => ({
      flight: Number(getComputedStyle(layer).zIndex), content: Number(getComputedStyle(document.querySelector('.boss-login-content')).zIndex),
      interaction: getComputedStyle(layer).pointerEvents,
    }));
    assert.ok(layers.flight > layers.content, '飞鸟必须位于登录内容前景');
    assert.equal(layers.interaction, 'none');
    assert.equal(await page.evaluate(() => CSS.supports('mix-blend-mode', 'plus-lighter')), true);
    const capture = await page.locator('[data-flight="active"]').evaluate(async bird => {
      const records = [];
      const begin = performance.now();
      const firstCircuit = Number(bird.dataset.flightLeg);
      let renderedAt = await new Promise(resolve => requestAnimationFrame(resolve));
      while (Number(bird.dataset.flightLeg) < firstCircuit + 2 || performance.now() - begin < 30000) {
        const box = bird.getBoundingClientRect();
        const bounds = bird.closest('main').getBoundingClientRect();
        const sideStyle = getComputedStyle(bird.querySelector('.boss-login-bird-facing'));
        const frontStyle = getComputedStyle(bird.querySelector('.boss-login-bird-turn'));
        const matrix = new DOMMatrix(sideStyle.transform);
        const frontMatrix = new DOMMatrix(frontStyle.transform);
        const heading = Number(bird.dataset.heading);
        records.push({ time: renderedAt, x: box.x + box.width / 2, y: box.y + box.height / 2,
          headX: matrix.m11, headY: matrix.m12, heading, circuit: Number(bird.dataset.flightLeg),
          sideOpacity: Number(sideStyle.opacity), frontOpacity: Number(frontStyle.opacity),
          visibleWidth: Number(sideStyle.opacity) * Math.hypot(matrix.m11, matrix.m12) + Number(frontStyle.opacity),
          pitch: Math.atan(matrix.m12 / matrix.m11),
          bank: Math.atan2(frontMatrix.m12, frontMatrix.m11),
          scale: Number.parseFloat(getComputedStyle(bird.querySelector('.boss-login-bird-depth')).scale),
          contained: box.left >= bounds.left - 1 && box.top >= bounds.top - 1 && box.right <= bounds.right + 1 && box.bottom <= bounds.bottom + 1 });
        if (performance.now() - begin > 90000) throw new Error('飞行周期没有连续完成');
        const previousFrame = renderedAt;
        do { renderedAt = await new Promise(resolve => requestAnimationFrame(resolve)); } while (renderedAt - previousFrame < 100);
      }
      return { records, completedCircuits: Number(bird.dataset.flightLeg) - firstCircuit };
    }, undefined, { timeout: 100000 });
    const samples = capture.records;
    const movements = samples.slice(1).map((current, index) => {
      const previous = samples[index];
      const dx = current.x - previous.x;
      const dy = current.y - previous.y;
      const distance = Math.hypot(dx, dy);
      const headLength = Math.hypot(current.headX, current.headY);
      const elapsed = (current.time - previous.time) / 1000;
      return { dx, dy, elapsed: current.time - previous.time, speed: distance / ((current.time - previous.time) / 1000),
        facing: distance > 0.1 ? (dx * Math.cos(current.heading) + dy * Math.sin(current.heading)) / distance : 1,
        sideFacing: current.sideOpacity > 0.5 && headLength > 0.02 && distance > 0.1 ? (dx * current.headX + dy * current.headY) / (distance * headLength) : 1,
        pitchSpeed: Math.abs(current.pitch - previous.pitch) / elapsed,
        scaleSpeed: Math.abs(current.scale - previous.scale) / elapsed,
        scaleAcceleration: index > 0 ? Math.abs((current.scale - previous.scale) / elapsed -
          (previous.scale - samples[index - 1].scale) / ((previous.time - samples[index - 1].time) / 1000)) / elapsed : 0,
        turn: Math.abs(Math.atan2(Math.sin(current.heading - previous.heading), Math.cos(current.heading - previous.heading))) };
    });
    fs.writeFileSync(path.join(root, '.work/t27-flight-samples.json'), JSON.stringify({ samples, movements }, null, 2));
    assert.ok(samples.every(sample => sample.contained), '飞行必须保持在内容视口内');
    assert.ok(capture.completedCircuits >= 2, '必须连续完成两个飞行周期');
    assert.ok(movements.every(movement => movement.facing > 0), '鸟的朝向必须与实际位移保持一致');
    assert.ok(movements.every(movement => movement.sideFacing > 0), '侧面姿态必须保持向前');
    assert.ok(samples.every(sample => sample.visibleWidth > 0.8 && Math.abs(sample.frontOpacity + sample.sideOpacity - 1) < 0.001), '转弯姿态必须连续可见');
    assert.ok(samples.every(sample => sample.scale >= 0.619 && sample.scale <= 0.941 && Math.abs(sample.bank) <= 0.151 && Math.abs(sample.pitch) <= 0.301), '缩放与飞行角度必须保持范围');
    assert.ok(movements.every(movement => movement.pitchSpeed < 1 && movement.scaleSpeed < 0.09 && movement.scaleAcceleration < 0.12), '姿态与透视变化必须平滑');
    assert.ok(movements.some(movement => movement.dx > 1) && movements.some(movement => movement.dx < -1), '必须覆盖两个水平方向');
    assert.ok(movements.every(movement => movement.turn < 0.5), '转弯必须连续');
    assert.ok(movements.every(movement => movement.speed > 12 && movement.speed < 180), '飞行速度必须连续且保持范围');
    assert.deepEqual(errors, []);
    for (const [file, expected] of productSources) assert.equal(hash(file), expected);
    for (const [file, expected] of Object.entries(artifacts)) assert.equal(hash(path.join(build, file)), expected);
    const report = { status: 'PASS_CONTINUOUS_FORWARD_FLIGHT', at: new Date().toISOString(),
      samples: samples.length, circuits: capture.completedCircuits,
      minimumFacingDot: Math.min(...movements.map(movement => movement.facing)),
      maximumTurnRadians: Math.max(...movements.map(movement => movement.turn)),
      minimumSpeed: Math.min(...movements.map(movement => movement.speed)), maximumSpeed: Math.max(...movements.map(movement => movement.speed)),
      layers, minimumVisibleWidth: Math.min(...samples.map(sample => sample.visibleWidth)),
      minimumScale: Math.min(...samples.map(sample => sample.scale)), maximumScale: Math.max(...samples.map(sample => sample.scale)),
      maximumPitchSpeed: Math.max(...movements.map(movement => movement.pitchSpeed)), maximumScaleSpeed: Math.max(...movements.map(movement => movement.scaleSpeed)),
      maximumScaleAcceleration: Math.max(...movements.map(movement => movement.scaleAcceleration)),
      source_sha256: { ...sources, ...Object.fromEntries(['design/T27/check-flight.cjs', 'design/T27/assets/boss-flight-sprite.png'].map(file => [file, hash(path.join(root, file))])) },
      source_scope: 'COMPILED_BUILD_SNAPSHOT', artifact_sha256: artifacts,
      visual: 'NOT_RUN' };
    fs.writeFileSync(path.join(root, 'evidence/T27/flight-direction.json'), JSON.stringify(report, null, 2));
    console.log(`${samples.length}次采样与两个完整周期的朝向、连续转弯和速度检查通过`);
  } finally {
    if (browser) await browser.close();
    service.kill('SIGTERM'); await once(service, 'exit'); fs.closeSync(log);
  }
}
void main();
