const fs = require('node:fs');
const path = require('node:path');
const { execFileSync } = require('node:child_process');

const root = path.resolve(__dirname, '../../..');
const source = path.join(__dirname, 'boss-agent-hd.png');
const output = path.join(root, '.work/t27-branding/boss-agent.iconset');
fs.mkdirSync(output, { recursive: true });
fs.copyFileSync(source, path.join(__dirname, 'boss-agent.png'));
for (const size of [16, 32, 128, 256, 512]) {
  for (const scale of [1, 2]) {
    const suffix = scale === 2 ? '@2x' : '';
    const target = path.join(output, `icon_${size}x${size}${suffix}.png`);
    execFileSync('sips', ['-Z', String(size * scale), source, '--out', target], { stdio: 'ignore' });
    execFileSync('sips', ['--padToHeightWidth', String(size * scale), String(size * scale), '--padColor', 'FFFFFF', target], { stdio: 'ignore' });
  }
}
execFileSync('iconutil', ['-c', 'icns', output, '-o', path.join(__dirname, 'boss-agent.icns')]);
console.log('项目图标已转换为macOS应用资源');
