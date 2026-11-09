const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const Module = require("node:module");

const project = path.resolve(__dirname, "../..");
const dependencies = path.join(project, ".work/upgrade2-u2-07/dependencies/node_modules");
const {buildSync} = require(path.join(dependencies, "esbuild"));
const React = require(path.join(dependencies, "react"));
const {renderToStaticMarkup} = require(path.join(dependencies, "react-dom/server"));
const {Window} = require(path.join(dependencies, "happy-dom/cjs/index.cjs"));
const built = buildSync({entryPoints: [path.join(project, "app/tests/u2_09_input_receipt_state_entry.ts")], bundle: true,
  write: false, platform: "node", format: "cjs", jsx: "automatic", nodePaths: [dependencies],
  external: ["react", "react/jsx-runtime"], loader: {".css": "empty"}});
const compiled = new Module(path.join(project, "app/tests/u2_09_input_receipt_state_entry.cjs"));
compiled.filename = path.join(project, "app/tests/u2_09_input_receipt_state_entry.cjs");
compiled.paths = [dependencies];
compiled._compile(built.outputFiles[0].text, compiled.filename);
const {RunInputReceiptStatus, inputReceiptVersionState} = compiled.exports;
const data = JSON.parse(fs.readFileSync(0, "utf8"));
const window = new Window({url: "http://127.0.0.1/"});
const document = html => new window.DOMParser().parseFromString(html, "text/html");

const observed = {};
for (const item of data.cases) {
  assert.equal(inputReceiptVersionState(item.receipt, item.current), item.expected);
  const parsed = document(renderToStaticMarkup(React.createElement(RunInputReceiptStatus, {
    receipt: item.receipt, currentGoalRevision: item.current})));
  const text = parsed.body.textContent;
  if (item.expected === "HISTORY") {
    assert.match(text, /历史目标版本/);
    assert.match(text, new RegExp("当前目标版本 " + item.current));
  } else if (item.expected === "AHEAD") {
    assert.ok(parsed.querySelector('[role="alert"]'));
    assert.match(text, /高于当前目标版本/);
    assert.match(text, /请重新读取运行/);
  } else if (item.expected === "UNKNOWN") {
    assert.match(text, /当前目标版本尚未读取/);
  } else {
    assert.match(text, /当前目标版本/);
  }
  observed[item.name] = {state: item.expected, input_id: item.receipt.input_id, goal_revision: item.receipt.goal_revision};
}
process.stdout.write(JSON.stringify({cases: observed, duplicate_receipt_same: data.duplicate_same}));
