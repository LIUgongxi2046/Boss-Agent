const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const Module = require("node:module");
const root = path.resolve(__dirname, "../..");
const dependencies = path.join(root, ".work/upgrade2-u2-07/dependencies/node_modules");
const {buildSync} = require(path.join(dependencies, "esbuild"));
const React = require(path.join(dependencies, "react"));
const {renderToStaticMarkup} = require(path.join(dependencies, "react-dom/server"));
const data = JSON.parse(fs.readFileSync(0, "utf8"));
const output = buildSync({entryPoints:[path.join(root,"app/webui/Upgrade2RunPanel.tsx"),path.join(root,"app/webui/upgrade2-run-client.ts")],
  bundle:true,write:false,outdir:path.join(root,"app/tests/u2-09-build"),platform:"node",format:"cjs",jsx:"automatic",nodePaths:[dependencies],
  external:["react","react/jsx-runtime"],loader:{".css":"empty"}});
function load(name) {
  const file = output.outputFiles.find(item=>item.path.endsWith("/"+name+".js"));
  assert.ok(file);
  const module = new Module(path.join(root,"app/tests/"+name+".cjs"));
  module.filename = path.join(root,"app/tests/"+name+".cjs");
  module.paths = [dependencies];
  module._compile(file.text,module.filename);
  return module.exports;
}
const {Upgrade2RunPanel} = load("Upgrade2RunPanel");
const {validateRunResponse,validateResultAgainstEvents} = load("upgrade2-run-client");
const result = {run_id:data.run.run_id,goal_revision:data.run.goal_revision,result:data.result,citation_checks:data.checks};
validateRunResponse("result",result);
validateResultAgainstEvents({...data.run,selected_refs:JSON.parse(data.run.selected_refs)},data.events,result);
const run = {run_id:data.run.run_id,goal:data.run.goal,revision:data.run.revision,goal_revision:data.run.goal_revision,
  status:data.run.status,allowed_actions:data.actions.flatMap(action=>action==="ADD_INPUT"?["SUPPLY_INPUT"]:action==="CANCEL"?["CANCEL"]:[]),
  waiting_inputs:[],intent:null,artifacts:[],projection_ready:false};
const html = renderToStaticMarkup(React.createElement(Upgrade2RunPanel,{run,events:data.events,result:data.result,citationChecks:data.checks,
  event_base_seq:0,connection:"CONNECTED",loading:false,busy:false,error:null,supplement:"",onOpenSource:()=>{}}));
assert.ok(html.includes("原文位置未经核查"));
assert.ok(html.includes(data.checks[0].locator));
process.stdout.write(JSON.stringify({locator_verification:data.checks[0].locator_verification,citation_count:data.checks.length}));
