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
  bundle: true, write: false, outdir: path.join(root, "app/tests/resume-late-build"), platform: "node", format: "cjs",
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
const runs = data.runs;

function Probe({runId, token, timeoutMs, denied}) {
  const client = React.useMemo(() => new Upgrade2RunClient({getToken: () => token}), [token]);
  const getToken = () => token;
  const snapshot = {run_id: runId, revision: 1, goal_revision: 1, status: "WAITING_INPUT"};
  return React.createElement(Upgrade2ResumeStatus, {client, snapshot, token, getToken, timeoutMs, onAccessDenied: status => denied.push(status)});
}

async function wait(ms) {
  await React.act(async () => { await new Promise(resolve => setTimeout(resolve, ms)); });
}

async function main() {
  const timeoutDenied = [];
  const timeoutContainer = document.createElement("div");
  document.body.appendChild(timeoutContainer);
  const timeoutView = createRoot(timeoutContainer);
  await React.act(async () => timeoutView.render(React.createElement(Probe, {runId: runs.timeout, token: "", timeoutMs: 200, denied: timeoutDenied})));
  await wait(500);
  assert.match(timeoutContainer.textContent, /读取超时/);
  assert.ok(timeoutContainer.querySelector('[role="alert"]'));
  await React.act(async () => timeoutView.unmount());

  const unmountContainer = document.createElement("div");
  document.body.appendChild(unmountContainer);
  const unmountView = createRoot(unmountContainer);
  const unmountDenied = [];
  await React.act(async () => unmountView.render(React.createElement(Probe, {runId: runs.unmount, token: "", timeoutMs: 5000, denied: unmountDenied})));
  await wait(50);
  await React.act(async () => unmountView.unmount());
  await wait(900);
  assert.equal(unmountContainer.textContent, "");

  const runContainer = document.createElement("div");
  document.body.appendChild(runContainer);
  const runView = createRoot(runContainer);
  const runDenied = [];
  await React.act(async () => runView.render(React.createElement(Probe, {runId: runs.a, token: "token-a", timeoutMs: 5000, denied: runDenied})));
  await wait(50);
  await React.act(async () => runView.render(React.createElement(Probe, {runId: runs.b, token: "token-a", timeoutMs: 5000, denied: runDenied})));
  await wait(900);
  assert.match(runContainer.textContent, /原进程的完整回收尚未核查/);
  assert.ok(!runContainer.textContent.includes("引擎启动条件尚未核查"));
  await React.act(async () => runView.unmount());

  const tokenContainer = document.createElement("div");
  document.body.appendChild(tokenContainer);
  const tokenView = createRoot(tokenContainer);
  const tokenDenied = [];
  await React.act(async () => tokenView.render(React.createElement(Probe, {runId: runs.a, token: "token-a", timeoutMs: 5000, denied: tokenDenied})));
  await wait(50);
  await React.act(async () => tokenView.render(React.createElement(Probe, {runId: runs.a, token: "token-b", timeoutMs: 5000, denied: tokenDenied})));
  await wait(900);
  assert.match(tokenContainer.textContent, /原进程的完整回收尚未核查/);
  assert.ok(!tokenContainer.textContent.includes("引擎启动条件尚未核查"));
  await React.act(async () => tokenView.unmount());

  const authContainer = document.createElement("div");
  document.body.appendChild(authContainer);
  const authView = createRoot(authContainer);
  const authDenied = [];
  let expired = 0;
  window.addEventListener("boss-auth-expired", () => { expired += 1; });
  await React.act(async () => authView.render(React.createElement(Probe, {runId: runs.unauthorized, token: "", timeoutMs: 5000, denied: authDenied})));
  await wait(400);
  assert.match(authContainer.textContent, /HTTP 401/);
  assert.deepEqual(authDenied, [401]);
  assert.equal(expired, 1);
  await React.act(async () => authView.unmount());

  process.stdout.write(JSON.stringify({timeout_visible: true, unmount_late_response_ignored: true, run_switch_late_response_ignored: true,
    token_change_late_response_ignored: true, unauthorized_cleanup: true}));
}

main();
