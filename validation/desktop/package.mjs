import { packager } from '@electron/packager';
import fs from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';
import { createHash } from 'node:crypto';

const directory = path.dirname(fileURLToPath(import.meta.url));
const root = path.resolve(directory, '..');
const zip = path.join(root, '.work/electron-v45.0.0-darwin-x64.zip');
const sha = createHash('sha256').update(fs.readFileSync(zip)).digest('hex');
if (sha !== '7877c282e74a52f8d87949536a25735cf9982de1265b544c9cd258dd14eff4de') throw new Error('Electron 官方归档校验失败');
const bundles = await packager({
  dir: directory, name: 'Boss-Agent-Validation', platform: 'darwin', arch: 'x64',
  electronVersion: '45.0.0', electronZipDir: path.join(root, '.work'),
  out: path.join(root, '.work/installed'), overwrite: true,
  appBundleId: 'local.bossagent.validation', appVersion: '0.1.0',
  tmpdir: path.join(root, '.work/tmp'), prune: true,
  ignore: /\/(?:check-desktop\.cjs|check-system\.cjs|package\.mjs|prepare-cache\.mjs)$/,
  extendInfo: { NSMicrophoneUsageDescription: '仅用于本人授权的 Boss-Agent 麦克风权限技术验证。', LSMinimumSystemVersion: '13.0' },
});
const report = { at: new Date().toISOString(), status: 'PASS', electron: '45.0.0', packager: '20.3.0', architecture: 'x64', electron_archive_sha256: sha, bundles, code_signing: '未配置开发者证书及公证', dependency_scope: '桌面验证宿主引用本机 validation Python 环境，最终产品安装由 T25 完成' };
fs.writeFileSync(path.join(root, '../evidence/T02/desktop-package.json'), JSON.stringify(report, null, 2));
console.log(JSON.stringify(report));
