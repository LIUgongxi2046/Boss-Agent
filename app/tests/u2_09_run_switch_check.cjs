const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const Module = require("node:module");

const project = path.resolve(__dirname, "../..");
const dependencies = path.join(project, ".work/upgrade2-u2-07/dependencies/node_modules");
const {buildSync} = require(path.join(dependencies, "esbuild"));
const React = require(path.join(dependencies, "react"));
const {Window} = require(path.join(dependencies, "happy-dom/cjs/index.cjs"));
const data = JSON.parse(fs.readFileSync(0, "utf8"));
const built = buildSync({entryPoints: [path.join(project, "app/tests/u2_09_run_switch_entry.ts")], bundle: true,
  write: false, platform: "node", format: "cjs", jsx: "automatic", nodePaths: [dependencies],
  external: ["react", "react/jsx-runtime", "react-dom", "react-dom/*"], loader: {".css": "empty"}});
const compiled = new Module(path.join(project, "app/tests/u2_09_run_switch_entry.cjs"));
compiled.filename = path.join(project, "app/tests/u2_09_run_switch_entry.cjs");
compiled.paths = [dependencies];
compiled._compile(built.outputFiles[0].text, compiled.filename);
const {Upgrade2RunPanel, Upgrade2RunClient, useUpgrade2Run} = compiled.exports;
const window = new Window({url: data.origin + "/"});
global.window = window;
global.document = window.document;
global.navigator = window.navigator;
global.fetch = window.fetch.bind(window);
global.sessionStorage = window.sessionStorage;
global.localStorage = window.localStorage;
global.IS_REACT_ACT_ENVIRONMENT = true;
const {createRoot} = require(path.join(dependencies, "react-dom/client"));

function Probe({runId, token}) {
  const client = React.useMemo(() => new Upgrade2RunClient({getToken: () => token}), [token]);
  const state = useUpgrade2Run({client, identityKey: "technical", pendingScopeKey: "space", runId,
    conversationId: data.conversation_id, authToken: token, connected: true, projection: null});
  return React.createElement("div", null,
    React.createElement("p", {id: "run"}, state.panelProps.run?.run_id ?? ""),
    React.createElement("p", {id: "text"}, state.panelProps.result?.payload.text ?? ""),
    React.createElement("p", {id: "error"}, state.panelProps.error ?? ""),
    React.createElement(Upgrade2RunPanel, state.panelProps));
}

async function main() {
  const container = document.createElement("div");
  document.body.appendChild(container);
  const root = createRoot(container);
  await React.act(async () => root.render(React.createElement(Probe, {runId: data.a, token: "token-a"})));
  await new Promise(resolve => setTimeout(resolve, 100));
  await React.act(async () => root.render(React.createElement(Probe, {runId: data.b, token: "token-b"})));
  await React.act(async () => { await new Promise(resolve => setTimeout(resolve, 1200)); });
  const run = container.querySelector("#run").textContent;
  const text = container.querySelector("#text").textContent;
  const error = container.querySelector("#error").textContent;
  assert.equal(run, data.b);
  assert.equal(text, "技术结果");
  assert.ok(!text.includes("包含补充要求"));
  assert.equal(error, "");
  await React.act(async () => root.unmount());
  process.stdout.write(JSON.stringify({switched: true, final_run: run, final_text: text, old_text_hidden: true, error: error}));
}

main();
