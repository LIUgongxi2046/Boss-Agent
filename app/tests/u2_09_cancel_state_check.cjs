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
const built = buildSync({entryPoints: [path.join(project, "app/tests/u2_09_cancel_state_entry.ts")], bundle: true,
  write: false, platform: "node", format: "cjs", jsx: "automatic", nodePaths: [dependencies],
  external: ["react", "react/jsx-runtime", "react-dom", "react-dom/*"], loader: {".css": "empty"}});
const compiled = new Module(path.join(project, "app/tests/u2_09_cancel_state_entry.cjs"));
compiled.filename = path.join(project, "app/tests/u2_09_cancel_state_entry.cjs");
compiled.paths = [dependencies];
compiled._compile(built.outputFiles[0].text, compiled.filename);
const {Upgrade2RunPanel} = compiled.exports;
const data = JSON.parse(fs.readFileSync(0, "utf8"));
const window = new Window({url: "http://127.0.0.1/"});
const document = html => new window.DOMParser().parseFromString(html, "text/html");

function panel(row, connection) {
  const actions = [...(row.allowed_actions.includes("ADD_INPUT") ? ["SUPPLY_INPUT"] : []),
                   ...(row.allowed_actions.includes("CANCEL") ? ["CANCEL"] : [])];
  const run = {run_id: row.run_id, goal: row.goal, revision: row.revision, goal_revision: row.goal_revision,
    status: row.status, cancel_requested_at: row.cancel_requested_at, allowed_actions: actions,
    waiting_inputs: [], intent: null, artifacts: [], projection_ready: false};
  const props = {run, events: [], event_base_seq: 0, connection, loading: false, busy: false,
    error: null, supplement: "", onSupplementChange: String, onSupplement: () => {}, onCancel: () => {}};
  return document(renderToStaticMarkup(React.createElement(Upgrade2RunPanel, props)));
}

const observed = {};
for (const row of data.runs) {
  const view = panel(row, "CONNECTED");
  const text = view.body.textContent;
  const cancel = [...view.querySelectorAll("button")].find(button => button.textContent === "取消未执行步骤");
  if (row.status === "RUNNING") {
    assert.ok(!text.includes("取消请求"));
    observed[row.status] = {notice: false, cancel_disabled: cancel.disabled};
  } else if (row.status === "CANCEL_REQUESTED") {
    assert.match(text, /取消请求已记录于/);
    assert.match(text, /不能视为全部取消/);
    assert.equal(cancel.disabled, true);
    observed[row.status] = {notice: true, cancel_disabled: true};
  } else if (row.status === "RECONCILING") {
    assert.match(text, /正在核查原业务动作的结果/);
    assert.match(text, /不能重复提交/);
    observed[row.status] = {notice: true};
  } else if (row.status === "CANCELED") {
    assert.match(text, /取消前已经完成的业务动作继续保留/);
    observed[row.status] = {notice: true};
  }
  const disconnected = panel(row, "DISCONNECTED");
  assert.ok(!disconnected.body.textContent.includes("取消请求已记录于"));
  assert.ok(!disconnected.body.textContent.includes("取消请求记录于"));
}
process.stdout.write(JSON.stringify({states: data.runs.map(row => row.status), observed}));
