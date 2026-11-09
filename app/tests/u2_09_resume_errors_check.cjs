const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const Module = require("node:module");
const root = path.resolve(__dirname, "../..");
const dependencies = path.join(root, ".work/upgrade2-u2-07/dependencies/node_modules");
const React = require(path.join(dependencies, "react"));
const {Window} = require(path.join(dependencies, "happy-dom/cjs/index.cjs"));
const {buildSync} = require(path.join(dependencies, "esbuild"));
const data = JSON.parse(fs.readFileSync(0, "utf8"));
const window = new Window({url: data.origin + "/"});
global.window = window;
global.document = window.document;
global.navigator = window.navigator;
global.XMLHttpRequest = window.XMLHttpRequest;
global.IS_REACT_ACT_ENVIRONMENT = true;
const {createRoot} = require(path.join(dependencies, "react-dom/client"));
const output = buildSync({entryPoints: [path.join(root, "app/webui/Upgrade2ResumeStatus.tsx"), path.join(root, "app/webui/upgrade2-run-client.ts")],
  bundle: true, write: false, outdir: path.join(root, "app/tests/resume-errors-build"), platform: "node", format: "cjs",
  jsx: "automatic", nodePaths: [dependencies], external: ["react", "react/jsx-runtime"]});
function load(name) {
  const moduleView = new Module(path.join(root, "app/webui/" + name + ".cjs"));
  moduleView.filename = path.join(root, "app/webui/" + name + ".cjs");
  moduleView.paths = [dependencies];
  moduleView._compile(output.outputFiles.find(item => item.path.endsWith("/" + name + ".js")).text, moduleView.filename);
  return moduleView.exports;
}
const {Upgrade2ResumeStatus} = load("Upgrade2ResumeStatus");
const {Upgrade2RunClient} = load("upgrade2-run-client");
const getToken = () => "";
const client = new Upgrade2RunClient({getToken});

async function renderCase(runId) {
  const container = document.createElement("div");
  document.body.appendChild(container);
  const rootView = createRoot(container);
  const snapshot = {run_id: runId, revision: 1, goal_revision: 1, status: "WAITING_INPUT"};
  await React.act(async () => rootView.render(React.createElement(Upgrade2ResumeStatus, {client, snapshot, token: "", getToken, onAccessDenied: () => {}})));
  await React.act(async () => { await new Promise(resolve => setTimeout(resolve, 400)); });
  const text = container.textContent;
  const alert = container.querySelector('[role="alert"]')?.textContent ?? null;
  const retry = [...container.querySelectorAll("button")].find(button => button.textContent === "重新读取继续运行条件") ?? null;
  await React.act(async () => rootView.unmount());
  return {text, alert, retry: Boolean(retry)};
}

async function main() {
  const schema = await renderCase("00000000-0000-4000-8000-000000000001");
  assert.match(schema.alert ?? "", /不符合 Schema/);
  assert.equal(schema.retry, true);
  const http = await renderCase("00000000-0000-4000-8000-000000000002");
  assert.match(http.alert ?? "", /HTTP 503/);
  assert.equal(http.retry, true);
  const valid = await renderCase("00000000-0000-4000-8000-000000000003");
  assert.equal(valid.alert, null);
  assert.match(valid.text, /引擎启动条件尚未核查/);
  assert.equal(valid.retry, true);
  process.stdout.write(JSON.stringify({schema_error_visible: true, http_error_visible: true, valid_state_visible: true, retry_visible: true}));
}

main();
