import { createHash } from 'node:crypto';
import fs from 'node:fs/promises';
import path from 'node:path';
import { fileURLToPath } from 'node:url';
import { Cache } from './node_modules/@electron/get/dist/Cache.js';

const directory = path.dirname(fileURLToPath(import.meta.url));
const name = 'electron-v45.0.0-darwin-x64.zip';
const source = path.resolve(directory, '../.work', name);
const content = await fs.readFile(source);
const digest = createHash('sha256').update(content).digest('hex');
const checksums = JSON.parse(await fs.readFile(path.join(directory, 'node_modules/electron/checksums.json')));
if (digest !== '7877c282e74a52f8d87949536a25735cf9982de1265b544c9cd258dd14eff4de' || digest !== checksums[name]) throw new Error('Electron 官方资产校验失败');
const copy = path.resolve(directory, '../.work/electron-cache-input.zip');
await fs.copyFile(source, copy);
const cache = new Cache(path.resolve(directory, '../.work/electron-cache'));
const result = await cache.putFileInCache('https://github.com/electron/electron/releases/download/v45.0.0/' + name, copy, name);
console.log(JSON.stringify({ official_digest: digest, cached_artifact: result }));
