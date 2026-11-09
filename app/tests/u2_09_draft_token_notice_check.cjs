const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const Module = require("node:module");
const root = path.resolve(__dirname, "../..");
const dependencies = path.join(root, ".work/upgrade2-u2-07/dependencies/node_modules");
const React = require(path.join(dependencies, "react"));
const {Window} = require(path.join(dependencies, "happy-dom/cjs/index.cjs"));
const {buildSync} = require(path.join(dependencies, "esbuild"));

const output = buildSync({entryPoints: [path.join(root, "app/webui/draft-token-notice.ts")], bundle: true, write: false,
  outdir: path.join(root, "app/tests/draft-token-build"), platform: "node", format: "cjs", jsx: "automatic",
  nodePaths: [dependencies], external: ["react", "react/jsx-runtime"]});
const compiled = new Module(path.join(root, "app/webui/draft-token-notice.cjs"));
compiled.filename = path.join(root, "app/webui/draft-token-notice.cjs");
compiled.paths = [dependencies];
compiled._compile(output.outputFiles[0].text, compiled.filename);
const {useTokenChangeDraftNotice} = compiled.exports;

const window = new Window({url: "http://127.0.0.1/"});
global.window = window;
global.document = window.document;
global.navigator = window.navigator;
global.IS_REACT_ACT_ENVIRONMENT = true;
const {createRoot} = require(path.join(dependencies, "react-dom/client"));

function Probe({token}) {
  const [dirty, setDirty] = React.useState(false);
  const {notice, dismiss} = useTokenChangeDraftNotice(token, dirty);
  return React.createElement("div", null,
    React.createElement("button", {id: "dirty-on", onClick: () => setDirty(true)}, "dirty-on"),
    React.createElement("button", {id: "dirty-off", onClick: () => setDirty(false)}, "dirty-off"),
    React.createElement("span", {id: "notice"}, notice),
    React.createElement("button", {id: "dismiss", onClick: dismiss}, "dismiss"));
}

const container = window.document.createElement("div");
window.document.body.appendChild(container);
const rootView = createRoot(container);
React.act(() => rootView.render(React.createElement(Probe, {token: "token-a"})));
assert.equal(container.querySelector("#notice").textContent, "");

React.act(() => container.querySelector("#dirty-on").click());
React.act(() => rootView.render(React.createElement(Probe, {token: "token-b"})));
assert.match(container.querySelector("#notice").textContent, /认证令牌已更新/);
assert.match(container.querySelector("#notice").textContent, /未自动恢复/);

React.act(() => container.querySelector("#dismiss").click());
assert.equal(container.querySelector("#notice").textContent, "");

React.act(() => container.querySelector("#dirty-on").click());
React.act(() => rootView.render(React.createElement(Probe, {token: "token-c"})));
assert.match(container.querySelector("#notice").textContent, /认证令牌已更新/);

React.act(() => container.querySelector("#dismiss").click());
React.act(() => container.querySelector("#dirty-off").click());
React.act(() => rootView.render(React.createElement(Probe, {token: "token-d"})));
assert.equal(container.querySelector("#notice").textContent, "");
React.act(() => rootView.render(React.createElement(Probe, {token: "token-d"})));
assert.equal(container.querySelector("#notice").textContent, "");
React.act(() => rootView.unmount());
window.happyDOM.close();

const source = fs.readFileSync(path.join(root, "app/webui/BossMeetingApproval.tsx"), "utf8");
assert.ok(source.includes('import {useTokenChangeDraftNotice} from "./draft-token-notice";'));
assert.ok(source.includes("useTokenChangeDraftNotice(token,dirty)"));
assert.ok(source.includes('role="alert" className="boss-status boss-status-warn"'));
assert.ok(source.includes("onDirtyChange={onDirtyChange}"));
process.stdout.write(JSON.stringify({dirty_token_change_notice: true, clean_token_change_silent: true, dismiss: true, wiring: true}));
