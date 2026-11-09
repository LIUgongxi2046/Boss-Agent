const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const Module = require("node:module");
const root = path.resolve(__dirname, "../..");
const dependencies = path.join(root, ".work/upgrade2-u2-07/dependencies/node_modules");
const {buildSync} = require(path.join(dependencies, "esbuild"));
const React = require(path.join(dependencies, "react"));
const {renderToStaticMarkup} = require(path.join(dependencies, "react-dom/server"));
const {Window} = require(path.join(dependencies, "happy-dom/cjs/index.cjs"));
const data = JSON.parse(fs.readFileSync(0, "utf8"));
const output = buildSync({entryPoints:[path.join(root,"app/webui/Upgrade2RunPanel.tsx"),path.join(root,"app/webui/upgrade2-run-client.ts"),path.join(root,"app/webui/RequiredOutputs.tsx")],
  bundle:true,write:false,outdir:path.join(root,"app/tests/result-render-build"),platform:"node",format:"cjs",jsx:"automatic",nodePaths:[dependencies],
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
const {RequiredOutputs} = load("RequiredOutputs");
const {validateRunResponse,validateResultAgainstEvents} = load("upgrade2-run-client");
const result = {run_id:data.run.run_id,goal_revision:data.run.goal_revision,result:data.event,citation_checks:data.citation_checks};
validateRunResponse("result",result);
const snapshot = {...data.run,selected_refs:JSON.parse(data.run.selected_refs)};
validateResultAgainstEvents(snapshot,data.events,result);
const previous = data.events.find(event=>event.type==="RESULT_RECORDED" && event.payload.goal_revision!==data.run.goal_revision);
assert.ok(previous);
assert.throws(()=>validateResultAgainstEvents(snapshot,data.events,{run_id:data.run.run_id,goal_revision:previous.payload.goal_revision,result:previous,citation_checks:null}),/目标版本/);
const allowed = data.actions.flatMap(action=>action==="ADD_INPUT"?["SUPPLY_INPUT"]:action==="CANCEL"?["CANCEL"]:[]);
const run = {run_id:data.run.run_id,goal:data.run.goal,revision:data.run.revision,goal_revision:data.run.goal_revision,
  status:data.run.status,allowed_actions:allowed,waiting_inputs:[],intent:null,artifacts:[],projection_ready:false};
const window = new Window();
const render = (connection,error=null,onReload=undefined) => new window.DOMParser().parseFromString(renderToStaticMarkup(React.createElement(Upgrade2RunPanel,
  {run,events:data.events,result:data.event,citationChecks:data.citation_checks,event_base_seq:0,connection,loading:false,busy:false,error,supplement:"",onOpenSource:()=>{},onReload})),"text/html");
const document = render("CONNECTED");
const section = document.querySelector('[aria-label="当前目标的运行结果"]');
assert.ok(section.textContent.includes(data.event.payload.text));
assert.ok(section.textContent.includes(data.event.payload.source_pins[0].version));
assert.ok(section.textContent.includes(data.event.payload.citations[0].locator));
assert.ok(section.textContent.includes(data.citation_checks === null ? "引用核查记录未提供" : "原文位置未经核查"));
assert.equal(section.querySelector("button").disabled,false);
assert.equal(section.textContent.includes("重新读取运行结果"),false);
assert.ok(!render("DISCONNECTED").body.textContent.includes(data.event.payload.text));
const failed=render("CONNECTED","会话或来源版本已经变化",()=>{});
assert.ok(!failed.body.textContent.includes(data.event.payload.text));
const reloadButton=[...failed.querySelectorAll("button")].find(button=>button.textContent==="重新读取运行结果");
assert.ok(reloadButton);
assert.equal(reloadButton.disabled,false);
global.window = window;
global.document = window.document;
global.navigator = window.navigator;
global.IS_REACT_ACT_ENVIRONMENT = true;
const {createRoot} = require(path.join(dependencies,"react-dom/client"));
const {act} = React;
async function checkSourceAction() {
  const container = document.createElement("div");
  document.body.appendChild(container);
  const rootView = createRoot(container);
  let selected;
  await act(async()=>rootView.render(React.createElement(Upgrade2RunPanel,
    {run,events:data.events,result:data.event,citationChecks:data.citation_checks,event_base_seq:0,connection:"CONNECTED",loading:false,busy:false,error:null,supplement:"",onOpenSource:source=>{selected=source;}})));
  const citation = data.event.payload.citations[0];
  const pin = data.event.payload.source_pins.find(item=>item.source_id===citation.source_id);
  const button = Array.from(container.querySelectorAll('[aria-label="当前目标的运行结果"] button')).find(item=>item.textContent.includes(citation.locator));
  assert.ok(button);
  await act(async()=>button.click());
  assert.deepEqual(selected,{source_id:pin.source_id,revision:pin.version,locator:citation.locator,result_event_id:data.event.event_id,content_sha256:pin.content_sha256});
  let reloads=0;
  await act(async()=>rootView.render(React.createElement(Upgrade2RunPanel,
    {run,events:data.events,result:data.event,citationChecks:data.citation_checks,event_base_seq:0,connection:"CONNECTED",loading:false,busy:false,error:"会话或来源版本已经变化",supplement:"",onOpenSource:()=>{},onReload:()=>{reloads+=1;}})));
  const reload=Array.from(container.querySelectorAll("button")).find(item=>item.textContent==="重新读取运行结果");
  assert.ok(reload);
  await act(async()=>reload.click());
  assert.equal(reloads,1);
  function Selection(){const [value,setValue]=React.useState([]);return React.createElement(RequiredOutputs,{value,onChange:setValue,disabled:false});}
  await act(async()=>rootView.render(React.createElement(Selection)));
  const choices = Array.from(container.querySelectorAll('input[type="checkbox"]'));
  assert.equal(choices.length,10);
  assert.ok(choices.every(choice=>!choice.checked));
  await act(async()=>choices[0].click());
  assert.equal(choices.filter(choice=>choice.checked).length,1);
  await act(async()=>choices[0].click());
  assert.ok(choices.every(choice=>!choice.checked));
  await act(async()=>rootView.unmount());
  process.stdout.write(JSON.stringify({source_version:pin.version,source_sha256:data.source_sha256,citation_action_verified:true,explicit_selection_verified:true,disconnected_result_hidden:true,error_result_hidden:true,reload_action_verified:true}));
}
checkSourceAction();
