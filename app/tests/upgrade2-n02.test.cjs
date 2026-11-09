const {test} = require("node:test");
const assert = require("node:assert/strict");
const path = require("node:path");
const Module = require("node:module");
const root = path.resolve(__dirname, "../..");
const dependencies = path.join(root, ".work/upgrade2-u2-07/dependencies/node_modules");
const {buildSync} = require(path.join(dependencies, "esbuild"));
const React = require(path.join(dependencies, "react"));
const {renderToStaticMarkup} = require(path.join(dependencies, "react-dom/server"));
const {Window} = require(path.join(dependencies, "happy-dom/cjs/index.cjs"));
const output = buildSync({entryPoints: [path.join(root, "app/tests/upgrade2-n02-entry.ts")], bundle: true,
  write: false, platform: "node", format: "cjs", jsx: "automatic", nodePaths: [dependencies],
  alias: {"@": path.join(root, ".work/product/nanobot/webui/src")},
  external: ["react", "react/jsx-runtime", "react-dom", "react-dom/*"], loader: {".css": "empty"}});
const compiled = new Module(path.join(root, "app/tests/upgrade2-n02-entry.cjs"));
compiled.filename = path.join(root, "app/tests/upgrade2-n02-entry.cjs");
compiled.paths = [dependencies];
compiled._compile(output.outputFiles[0].text, compiled.filename);
const {BossConversationWorkspace, ClientProvider, NanobotClient} = compiled.exports;

test("N02及运行接入模块生成浏览器代码", () => {
  const result = buildSync({entryPoints: [path.join(root, "app/webui/BossConversationWorkspace.tsx")], bundle: true,
    write: false, outdir: path.join(root, "app/tests/upgrade2-n02-output"), platform: "browser", format: "esm", jsx: "automatic", nodePaths: [dependencies],
    alias: {"@": path.join(root, ".work/product/nanobot/webui/src")}, loader: {".css": "css"}});
  assert.ok(result.outputFiles.some(file => file.path.endsWith(".js") && file.contents.length > 0));
  assert.ok(result.outputFiles.some(file => file.path.endsWith(".css") && file.contents.length > 0));
});

test("无运行关联时保留聊天内容并显示持续任务不可用", async () => {
  const window = new Window({url: "http://127.0.0.1/"});
  const original = globalThis.window;
  globalThis.window = window;
  try {
    const client = new NanobotClient({url: "ws://127.0.0.1/", reconnect: false});
    const element = React.createElement(ClientProvider, {client, token: ""},
      React.createElement(BossConversationWorkspace, {role: "BOSS", visible: true, activeKey: null, sessions: []},
        React.createElement("p", null, "聊天区域")));
    const document = new window.DOMParser().parseFromString(renderToStaticMarkup(element), "text/html");
    assert.match(document.querySelector('[aria-label="交办消息"]').textContent, /聊天区域/);
    assert.match(document.querySelector('[aria-label="持续任务"]').textContent, /尚未取得可用的持续任务运行/);
    assert.equal(document.querySelector('[aria-label="持续任务"] button'), null);
  } finally {
    globalThis.window = original;
    await window.happyDOM.close();
  }
});
