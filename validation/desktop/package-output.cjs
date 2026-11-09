const fs = require('node:fs');
const path = require('node:path');

function desktopPackageOutput(root, requested) {
  if (!requested || !path.isAbsolute(requested)) throw new Error('桌面打包需要明确的绝对输出目录');
  const workPath = path.resolve(root, '.work');
  const parentPath = path.resolve(path.dirname(requested));
  const work = fs.realpathSync(workPath);
  const parent = fs.realpathSync(parentPath);
  if (work !== workPath || parent !== parentPath) throw new Error('桌面打包目录不能经过符号链接');
  const output = path.join(parent, path.basename(requested));
  const relative = path.relative(work, output);
  if (!relative || relative.startsWith('..' + path.sep) || relative === '..' || path.isAbsolute(relative)) {
    throw new Error('桌面打包输出必须位于独立工作目录');
  }
  if (fs.lstatSync(output, { throwIfNoEntry: false })) throw new Error('桌面打包输出目录已经存在');
  return output;
}

function reserveDesktopPackageOutput(root, requested) {
  const output = desktopPackageOutput(root, requested);
  fs.mkdirSync(output, { mode: 0o700 });
  return output;
}

module.exports = { desktopPackageOutput, reserveDesktopPackageOutput };
