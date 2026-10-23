const path = require('node:path');
const fs = require('node:fs');

const name = 'Boss Agent';
const png = path.join(__dirname, 'branding', 'boss-agent.png');
const icns = path.join(__dirname, 'branding', 'boss-agent.icns');

function requireAssets() {
  for (const file of [png, icns]) if (!fs.statSync(file).isFile()) throw new Error('项目品牌资源不可用');
}

function configureApp(app, nativeImage) {
  requireAssets();
  app.setName(name);
  if (process.platform === 'darwin') app.dock.setIcon(nativeImage.createFromPath(png));
}

function windowOptions() {
  requireAssets();
  return { title: name, icon: png };
}

function attachWindow(window) {
  window.setTitle(name);
  window.on('page-title-updated', event => { event.preventDefault(); window.setTitle(name); });
}

function packageOptions() {
  requireAssets();
  return { name, executableName: name, icon: icns,
    extendInfo: { CFBundleDisplayName: name, CFBundleName: name } };
}

module.exports = { name, png, icns, configureApp, windowOptions, attachWindow, packageOptions };
