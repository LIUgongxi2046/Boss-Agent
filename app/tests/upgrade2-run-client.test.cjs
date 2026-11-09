const assert = require("node:assert/strict");
const {test} = require("node:test");
const path = require("node:path");
const Module = require("node:module");
const crypto = require("node:crypto");
const fs = require("node:fs");
const {spawn} = require("node:child_process");
const {once} = require("node:events");

const root = path.resolve(__dirname, "../..");
const dependencies = path.join(root, ".work/upgrade2-u2-07/dependencies/node_modules");
const {buildSync} = require(path.join(dependencies, "esbuild"));
const {Window} = require(path.join(dependencies, "happy-dom/cjs/index.cjs"));
const schemaDependencies = dependencies;
const compiled = buildSync({entryPoints: [path.join(root, "app/webui/upgrade2-run-client.ts")], bundle: true,
  write: false, platform: "node", format: "cjs", nodePaths: [schemaDependencies, dependencies]});
const component = new Module(path.join(root, "app/webui/upgrade2-run-client.cjs"));
component.filename = path.join(root, "app/webui/upgrade2-run-client.cjs");
component._compile(compiled.outputFiles[0].text, component.filename);
const {Upgrade2RunClient, RunApiError, validateRunResponse} = component.exports;
const hookBundle = buildSync({entryPoints: [path.join(root, "app/webui/useUpgrade2Run.ts")], bundle: true,
  write: false, platform: "node", format: "cjs", external: ["react"], nodePaths: [schemaDependencies, dependencies]});
const hookModule = new Module(path.join(root, "app/webui/useUpgrade2Run.cjs"));
hookModule.filename = path.join(root, "app/webui/useUpgrade2Run.cjs");
hookModule.paths = [dependencies];
hookModule._compile(hookBundle.outputFiles[0].text, hookModule.filename);
const {useUpgrade2Run} = hookModule.exports;

test("真实接口拒绝无身份的读取与写入", {timeout: 30000}, async () => {
  const server = spawn(path.join(root, ".work/upgrade2-u2-04/locked-env/bin/python"), [path.join(root, "app/tests/upgrade2-run-client-server.py")],
    {cwd: root, env: {...process.env, PYTHONDONTWRITEBYTECODE: "1"}, stdio: ["ignore", "pipe", "pipe"]});
  let stderr = "";
  server.stderr.on("data", value => { stderr += value; });
  const data = await Promise.race([
    once(server.stdout, "data").then(([value]) => value),
    once(server, "exit").then(([code]) => { throw new Error(`接口启动失败 ${code}: ${stderr}`); }),
  ]);
  const port = Number(String(data).trim());
  assert.ok(Number.isInteger(port) && port > 0, stderr);
  const window = new Window({url: `http://127.0.0.1:${port}/`});
  const oldFetch = globalThis.fetch;
  const oldWindow = globalThis.window, oldDocument = globalThis.document, oldStorage = globalThis.sessionStorage, oldLocalStorage = globalThis.localStorage, oldActEnvironment = globalThis.IS_REACT_ACT_ENVIRONMENT;
  globalThis.fetch = window.fetch.bind(window);
  globalThis.window = window;
  globalThis.document = window.document;
  globalThis.sessionStorage = window.sessionStorage;
  globalThis.localStorage = window.localStorage;
  globalThis.IS_REACT_ACT_ENVIRONMENT = true;
  const client = new Upgrade2RunClient({getToken: () => ""});
  try {
    assert.deepEqual(await client.resumeStatus("00000000-0000-0000-0000-000000000000"), {httpStatus:401});
    const resumePath = "/api/v2/runs/00000000-0000-0000-0000-000000000000";
    await assert.rejects(client.createMethodCatalog("conversation-1", []), error => error instanceof RunApiError && error.status === 401);
    for (const action of [() => client.dispatch("00000000-0000-0000-0000-000000000000", 0, "dispatch-check"),
      () => client.dispatchReceipt("00000000-0000-0000-0000-000000000000", 0, "dispatch-check"),
      () => client.dispatchInspection("00000000-0000-0000-0000-000000000000", "dispatch-check")]) {
      await assert.rejects(action(), error => error instanceof RunApiError && error.status === 401);
    }
    assert.equal((await client.objectCandidates("00000000-0000-0000-0000-000000000000",1)).status,401);
    assert.equal((await client.meetingCandidate("00000000-0000-0000-0000-000000000000",1,"meeting-1")).status,401);
    assert.equal((await client.objectReceipt("00000000-0000-0000-0000-000000000000",1,"technical-request",[])).status,401);
    assert.equal((await window.fetch(resumePath + "/object-scope",{method:"POST",headers:{"Content-Type":"application/json"},body:"{}"})).status,401);
    assert.equal((await window.fetch(resumePath + "/resume-requests/technical-request")).status,401);
    assert.equal((await oldFetch(`http://127.0.0.1:${port}` + resumePath + "/resume",{method:"POST",headers:{"Content-Type":"application/json",Origin:`http://127.0.0.1:${port}`},body:JSON.stringify({expected_revision:0,expected_goal_revision:1,request_key:"technical-request"})})).status,401);
    const digest=crypto.createHash("sha256").update(fs.readFileSync(path.join(root,"specs/agent-intents.schema.json"))).digest("hex");
    assert.equal((await oldFetch(`http://127.0.0.1:${port}/api/v2/intents/technical-intent/decision`,{method:"POST",headers:{"Content-Type":"application/json",Origin:`http://127.0.0.1:${port}`},body:JSON.stringify({decision:"CONFIRM",expected_revision:0,payload_digest:digest,request_key:"technical-request",acknowledge_conflict:true})})).status,401);
    for (const request of [() => client.create("conversation-1", "准备会议资料", [], "create-1"), () => client.create("conversation-1", "准备会议资料", [], "create-1",undefined,["TEXT"]), () => client.createReceipt("create-1"), () => client.read("run-1"), () => client.events("run-1", 0), () => client.result("run-1"), () => client.requestReceipt("input-1", "run-1", "inputs"), () => client.intent("run-1"), () => client.decisionReceipt("decision-1", "intent-1", "REJECT", 0),
      () => client.supplement("run-1", "补充会议材料", 1, "input-1"), () => client.supplement("run-1", "补充会议材料", 1, "input-1",undefined,["PDF"]), () => client.cancel("run-1", 1, "cancel-1")]) {
      await assert.rejects(request(), error => {
        assert.ok(error instanceof RunApiError);
        assert.equal(error.status, 401);
        assert.equal(error.detail.code, "UNAUTHENTICATED");
        assert.doesNotThrow(() => validateRunResponse("error", error.detail));
        assert.throws(() => validateRunResponse("snapshot", error.detail), /不符合Schema/);
        return true;
      });
    }
    await assert.rejects(client.request("/api/v2/runs/00000000-0000-0000-0000-000000000000/resume", "error"), error => error.message.includes("HTTP 405") && error.message.includes("Method Not Allowed"));
    const React = require(path.join(dependencies, "react"));
    const {createRoot} = require(path.join(dependencies, "react-dom/client"));
    const container = window.document.createElement("div");
    window.document.body.appendChild(container);
    const rootNode = createRoot(container);
    function Probe({connected, identityKey}) {
      const state = useUpgrade2Run({client, identityKey, pendingScopeKey: "anonymous", runId: "run-1", conversationId: "conversation-1", authToken: "", connected, projection: null});
      return React.createElement("p", {"data-run": state.panelProps.run ? "visible" : "hidden", "data-events": state.panelProps.events.length, "data-connection": state.panelProps.connection}, state.panelProps.error || "读取中");
    }
    await React.act(async () => { rootNode.render(React.createElement(Probe, {connected: true, identityKey: "anonymous"})); });
    for (let index = 0; index < 50 && !container.textContent.includes("当前身份无效"); index++) {
      await React.act(async () => { await new Promise(resolve => setTimeout(resolve, 20)); });
    }
    assert.match(container.textContent, /当前身份无效/);
    await React.act(async () => { rootNode.render(React.createElement(Probe, {connected: false, identityKey: "anonymous"})); });
    assert.equal(container.querySelector("p").dataset.run, "hidden");
    assert.equal(container.querySelector("p").dataset.events, "0");
    assert.equal(container.querySelector("p").dataset.connection, "DISCONNECTED");
    await React.act(async () => { rootNode.render(React.createElement(Probe, {connected: true, identityKey: "new-identity"})); });
    for (let index = 0; index < 50 && !container.textContent.includes("当前身份无效"); index++) {
      await React.act(async () => { await new Promise(resolve => setTimeout(resolve, 20)); });
    }
    assert.match(container.textContent, /当前身份无效/);
    await React.act(async () => { rootNode.unmount(); });
  } finally {
    globalThis.fetch = oldFetch;
    globalThis.window = oldWindow;
    globalThis.document = oldDocument;
    globalThis.sessionStorage = oldStorage;
    globalThis.localStorage = oldLocalStorage;
    globalThis.IS_REACT_ACT_ENVIRONMENT = oldActEnvironment;
    await window.happyDOM.close();
    server.kill("SIGTERM");
    await once(server, "exit");
  }
});
