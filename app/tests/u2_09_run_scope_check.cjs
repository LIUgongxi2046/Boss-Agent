const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const Module = require("node:module");
const root = path.resolve(__dirname, "../..");
const dependencies = path.join(root, ".work/upgrade2-u2-07/dependencies/node_modules");
const {buildSync} = require(path.join(dependencies, "esbuild"));
const data = JSON.parse(fs.readFileSync(0, "utf8"));
const built = buildSync({entryPoints: [path.join(root, "app/webui/upgrade2-run-scope.ts")], bundle: true, write: false,
  outdir: path.join(root, "app/tests/run-scope-build"), platform: "node", format: "cjs", nodePaths: [dependencies],
  external: ["react", "react/jsx-runtime"]});
const compiled = new Module(path.join(root, "app/webui/upgrade2-run-scope.cjs"));
compiled.filename = path.join(root, "app/webui/upgrade2-run-scope.cjs");
compiled.paths = [dependencies];
compiled._compile(built.outputFiles[0].text, compiled.filename);
const {upgrade2RunScopeKey} = compiled.exports;
const base = {identityKey: "identity-a", pendingScopeKey: "space-a", conversationId: data.conversation_id, runId: data.run_id, authToken: "token-a"};
const key = upgrade2RunScopeKey(base);
assert.equal(upgrade2RunScopeKey({...base}), key);
assert.notEqual(upgrade2RunScopeKey({...base, authToken: "token-b"}), key);
assert.notEqual(upgrade2RunScopeKey({...base, identityKey: "identity-b"}), key);
assert.notEqual(upgrade2RunScopeKey({...base, pendingScopeKey: "space-b"}), key);
assert.notEqual(upgrade2RunScopeKey({...base, conversationId: data.conversation_id + "-other"}), key);
assert.notEqual(upgrade2RunScopeKey({...base, runId: data.run_id + "-other"}), key);
assert.throws(() => upgrade2RunScopeKey({...base, identityKey: ""}), /身份、会话或认证范围标识无效/);
const hook = fs.readFileSync(path.join(root, "app/webui/useUpgrade2Run.ts"), "utf8");
assert.ok(hook.includes("upgrade2RunScopeKey({identityKey, pendingScopeKey, conversationId, runId, authToken})"));
assert.ok(hook.includes("authToken: string"));
const component = fs.readFileSync(path.join(root, "app/webui/Upgrade2ConversationRun.tsx"), "utf8");
assert.ok(component.includes("authToken: binding.authToken"));
process.stdout.write(JSON.stringify({scope_key_changes_with_token: true, scope_key_changes_with_identity: true,
  scope_key_changes_with_space: true, scope_key_changes_with_run: true, wiring: true}));
