const assert = require("node:assert/strict");
const fs = require("node:fs");
const Module = require("node:module");
const path = require("node:path");

const project = path.resolve(__dirname, "../..");
const dependencies = path.join(project, ".work/upgrade2-u2-07/dependencies/node_modules");
const {buildSync} = require(path.join(dependencies, "esbuild"));
const React = require(path.join(dependencies, "react"));
const {renderToStaticMarkup} = require(path.join(dependencies, "react-dom/server"));
const {Window} = require(path.join(dependencies, "happy-dom/cjs/index.cjs"));
const built = buildSync({entryPoints: [path.join(project, "app/tests/u2_09_plan_panel_entry.ts")], bundle: true,
  write: false, platform: "node", format: "cjs", jsx: "automatic", nodePaths: [dependencies],
  alias: {"@": path.join(project, ".work/upgrade2-u2-07/nanobot-independent/webui/src")},
  external: ["react", "react/jsx-runtime", "react-dom", "react-dom/*"], loader: {".css": "empty"}});
const compiled = new Module(path.join(project, "app/tests/u2_09_plan_panel_entry.cjs"));
compiled.filename = path.join(project, "app/tests/u2_09_plan_panel_entry.cjs");
compiled.paths = [dependencies];
compiled._compile(built.outputFiles[0].text, compiled.filename);
const {OwnerPlanExecutionScope, Upgrade2RunPanel, Upgrade2RunClient, ClientProvider, NanobotClient} = compiled.exports;
const data = JSON.parse(fs.readFileSync(0, "utf8"));
const window = new Window({url: "http://127.0.0.1/"});
const client = new NanobotClient({url: "ws://127.0.0.1/", reconnect: false});
const api = new Upgrade2RunClient({getToken: () => ""});
const document = html => new window.DOMParser().parseFromString(html, "text/html");

function planSection(disabled) {
  return document(renderToStaticMarkup(React.createElement(ClientProvider, {client, token: ""},
    React.createElement(OwnerPlanExecutionScope, {plan: data.plan, disabled, onDirtyChange: Boolean, onReload: Number}))));
}

const blocked = planSection(true);
assert.equal(blocked.querySelector("fieldset").disabled, true);
assert.match(blocked.body.textContent, /需要重新读取或完成编辑/);
assert.equal([...blocked.querySelectorAll("button")].find(button => button.textContent === "生成服务端范围预览").disabled, true);
const ready = planSection(false);
assert.equal(ready.querySelector("fieldset").disabled, false);
assert.equal([...ready.querySelectorAll("button")].find(button => button.textContent === "生成服务端范围预览").disabled, true);
assert.equal([...ready.querySelectorAll('input[type="checkbox"]')].length, 10);
assert.ok([...ready.querySelectorAll('input[type="checkbox"]')].every(input => !input.checked));
assert.equal([...ready.querySelectorAll("button")].find(button => button.textContent === "读取当前可用方法").disabled, true);

for (const row of data.runs) {
  const actions = [...(row.allowed_actions.includes("ADD_INPUT") ? ["SUPPLY_INPUT"] : []),
                   ...(row.allowed_actions.includes("CANCEL") ? ["CANCEL"] : [])];
  const run = {run_id: row.run_id, goal: row.goal, revision: row.revision, goal_revision: row.goal_revision,
    status: row.status, allowed_actions: actions, waiting_inputs: [], intent: null, artifacts: [], projection_ready: false};
  const props = {run, events: [], event_base_seq: 0, connection: "CONNECTED", loading: false, busy: false,
    error: null, supplement: data.supplement, onSupplementChange: String,
    onSupplement: api.supplement.bind(api), onCancel: api.cancel.bind(api)};
  const visible = document(renderToStaticMarkup(React.createElement(Upgrade2RunPanel, props)));
  const input = [...visible.querySelectorAll("button")].find(button => button.textContent === "提交补充");
  const cancel = [...visible.querySelectorAll("button")].find(button => button.textContent === "取消未执行步骤");
  assert.equal(input.disabled, !row.allowed_actions.includes("ADD_INPUT"));
  assert.equal(cancel.disabled, !row.allowed_actions.includes("CANCEL"));
  const disconnected = document(renderToStaticMarkup(React.createElement(Upgrade2RunPanel, {...props, connection: "DISCONNECTED"})));
  assert.equal([...disconnected.querySelectorAll("button")].find(button => button.textContent === "提交补充").disabled, true);
  assert.equal([...disconnected.querySelectorAll("button")].find(button => button.textContent === "取消未执行步骤").disabled, true);
}
process.stdout.write(JSON.stringify({plan_component: "disabled-and-empty", run_states: data.runs.map(row => row.status), disconnected: "disabled"}));
