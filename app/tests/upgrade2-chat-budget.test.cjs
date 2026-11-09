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

test("维护界面提供十项预算输入及原请求核查入口", () => {
  const result = buildSync({entryPoints: [path.join(root, "app/webui/MaintainerChatBudget.tsx")], bundle: true,
    write: false, platform: "node", format: "cjs", jsx: "automatic", nodePaths: [dependencies],
    external: ["react", "react/jsx-runtime", "react-dom", "react-dom/*"], loader: {".css": "empty"}});
  const compiled = new Module(path.join(root, "app/tests/upgrade2-chat-budget-entry.cjs"));
  compiled.filename = path.join(root, "app/tests/upgrade2-chat-budget-entry.cjs");
  compiled.paths = [dependencies];
  compiled._compile(result.outputFiles[0].text, compiled.filename);
  const html = renderToStaticMarkup(React.createElement(compiled.exports.MaintainerChatBudget,
    {getToken: () => "", identityKey: "", onDirtyChange: () => {}}));
  assert.match(html, /聊天运行预算/);
  assert.match(html, /读取当前预算/);
  assert.match(html, /维护身份/);
  const window = new Window();
  const document = new window.DOMParser().parseFromString(html, "text/html");
  const inputs = Array.from(document.querySelectorAll('input[type="number"]'));
  assert.equal(inputs.length, 10);
  assert.ok(inputs.every(input => input.getAttribute("value") === ""));
  assert.ok(document.querySelector("fieldset").disabled);
  assert.ok(document.querySelector('button[type="submit"]').disabled);
});
