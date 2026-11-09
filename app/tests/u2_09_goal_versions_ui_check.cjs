const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const Module = require("node:module");
const root = path.resolve(__dirname, "../..");
const dependencies = path.join(root, ".work/upgrade2-u2-07/dependencies/node_modules");
const React = require(path.join(dependencies, "react"));
const {renderToStaticMarkup} = require(path.join(dependencies, "react-dom/server"));
const {buildSync} = require(path.join(dependencies, "esbuild"));
const {Window} = require(path.join(dependencies, "happy-dom/cjs/index.cjs"));
const data = JSON.parse(fs.readFileSync(0, "utf8"));
const output = buildSync({entryPoints:[path.join(root,"app/webui/Upgrade2RunPanel.tsx"),path.join(root,"app/webui/upgrade2-run-client.ts")],bundle:true,write:false,outdir:path.join(root,"app/tests/goal-versions-build"),platform:"node",format:"cjs",jsx:"automatic",nodePaths:[dependencies],external:["react","react/jsx-runtime"],loader:{".css":"empty"}});
const moduleView = new Module(path.join(root,"app/tests/u2_09_goal_versions_bundle.cjs"));
moduleView.filename = path.join(root,"app/tests/u2_09_goal_versions_bundle.cjs");
moduleView.paths = [dependencies];
moduleView._compile(output.outputFiles.find(item=>item.path.endsWith("/Upgrade2RunPanel.js")).text,moduleView.filename);
const {Upgrade2RunPanel} = moduleView.exports;
const clientModule=new Module(path.join(root,"app/tests/goal-versions-client.cjs"));clientModule.filename=path.join(root,"app/tests/goal-versions-client.cjs");clientModule.paths=[dependencies];clientModule._compile(output.outputFiles.find(item=>item.path.endsWith("/upgrade2-run-client.js")).text,clientModule.filename);
const {validateRunReadFence}=clientModule.exports;
const oldEvents=data.events.filter(item=>item.seq<=data.previous.last_event_seq);
validateRunReadFence(data.previous,data.previous,[...oldEvents,...oldEvents]);
validateRunReadFence(data.current,data.current,data.events);
assert.throws(()=>validateRunReadFence(data.previous,data.current,oldEvents),/已经变化/);
assert.throws(()=>validateRunReadFence(data.previous,data.previous,data.events),/快照不一致/);
function render(record, requirements, connection, loading=false, error=null, busy=false) {
  const run={run_id:record.run_id,goal:record.goal,revision:record.revision,goal_revision:record.goal_revision,status:record.status,requirements,
    allowed_actions:[],waiting_inputs:[],intent:null,artifacts:[],projection_ready:false};
  return renderToStaticMarkup(React.createElement(Upgrade2RunPanel,{run,events:data.events,event_base_seq:0,connection,loading,busy,error,supplement:""}));
}
assert.match(render(data.previous,data.confirmed,"CONNECTED"),/本人已选择：文字结果、PDF 文件/);
assert.match(render(data.current,data.pending,"CONNECTED"),/等待本人选择/);
assert.doesNotMatch(render(data.current,data.pending,"CONNECTED"),/本人已选择/);
for (const html of [render(data.previous,data.confirmed,"DISCONNECTED"),render(data.previous,data.confirmed,"RECONNECTING",true),render(data.previous,data.confirmed,"CONNECTED",false,"读取失败"),render(data.previous,data.confirmed,"CONNECTED",false,null,true)]) {
  assert.doesNotMatch(html,/本人已选择/);
  assert.match(html,/当前目标的必要成果尚未核查/);
}
const window = new Window();
global.window=window;
global.document=window.document;
global.navigator=window.navigator;
global.IS_REACT_ACT_ENVIRONMENT=true;
const {createRoot}=require(path.join(dependencies,"react-dom/client"));
const {act}=React;
async function checkInteraction() {
  const container=document.createElement("div");
  document.body.appendChild(container);
  const rootView=createRoot(container);
  let submitted;
  const record=data.current;
  const run={run_id:record.run_id,goal:record.goal,revision:record.revision,goal_revision:record.goal_revision,status:record.status,requirements:data.pending,
    allowed_actions:data.actions.flatMap(action=>action==="ADD_INPUT"?["SUPPLY_INPUT"]:[]),waiting_inputs:[],intent:null,artifacts:[],projection_ready:false};
  assert.ok(run.allowed_actions.includes("SUPPLY_INPUT"));
  function Panel(){
    const [selection,setSelection]=React.useState([]);
    return React.createElement(Upgrade2RunPanel,{run,events:data.events,event_base_seq:0,connection:"CONNECTED",loading:false,busy:false,error:null,
      supplement:data.input,onSupplementChange:()=>{},supplementOutputs:selection,onSupplementOutputsChange:setSelection,
      onSupplement:(...args)=>{submitted=args;}});
  }
  await act(async()=>rootView.render(React.createElement(Panel)));
  const choices=Array.from(container.querySelectorAll('input[type="checkbox"]'));
  assert.equal(choices.length,10);
  assert.ok(choices.every(choice=>!choice.checked));
  await act(async()=>choices[0].click());
  await act(async()=>choices[5].click());
  assert.match(container.textContent,/等待本人选择/);
  assert.doesNotMatch(container.textContent,/本人已选择/);
  await act(async()=>container.querySelector('button[type="submit"]').click());
  assert.deepEqual(submitted,[run.run_id,data.input.trim(),run.goal_revision,data.confirmed.required_outputs]);
  await act(async()=>rootView.unmount());
  process.stdout.write(JSON.stringify({checked:true}));
}
checkInteraction();
