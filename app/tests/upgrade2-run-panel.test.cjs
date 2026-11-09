const assert = require("node:assert/strict");
const {test} = require("node:test");
const path = require("node:path");
const Module = require("node:module");

const root = path.resolve(__dirname, "../..");
const dependencies = path.join(root, ".work/upgrade2-u2-07/dependencies/node_modules");
const React = require(path.join(dependencies, "react"));
const {renderToStaticMarkup} = require(path.join(dependencies, "react-dom/server"));
const {Window} = require(path.join(dependencies, "happy-dom/cjs/index.cjs"));
const {buildSync} = require(path.join(dependencies, "esbuild"));
const compiled = buildSync({entryPoints: [path.join(root, "app/webui/Upgrade2RunPanel.tsx")], bundle: true,
  write: false, platform: "node", format: "cjs", jsx: "automatic", nodePaths: [dependencies],
  external: ["react", "react/jsx-runtime"], loader: {".css": "empty"}});
const component = new Module(path.join(root, "app/webui/Upgrade2RunPanel.cjs"));
component.filename = path.join(root, "app/webui/Upgrade2RunPanel.cjs");
component.paths = [dependencies];
component._compile(compiled.outputFiles[0].text, component.filename);
const {Upgrade2RunPanel} = component.exports;

test("无运行记录时显示空状态，读取期间显示状态提示", () => {
  const window = new Window();
  const render = (loading, connection = "CONNECTED") => new window.DOMParser().parseFromString(renderToStaticMarkup(React.createElement(Upgrade2RunPanel, {
    run: null, events: [], event_base_seq: 0, connection, loading, busy: false, error: null, supplement: "",
  })), "text/html");
  const empty = render(false);
  assert.match(empty.body.textContent, /当前没有运行记录/);
  assert.equal(empty.querySelectorAll("button").length, 0);
  const loading = render(true);
  assert.equal(loading.querySelector('[role="status"]').textContent, "正在读取运行");
  assert.equal(loading.querySelector("section").getAttribute("aria-busy"), "true");
  assert.match(render(false, "DISCONNECTED").body.textContent, /连接已中断，尚未读取运行/);
});
