const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const Module = require("node:module");
const root = path.resolve(__dirname, "../..");
const dependencies = path.join(root, ".work/upgrade2-u2-07/dependencies/node_modules");
const React = require(path.join(dependencies, "react"));
const {renderToStaticMarkup} = require(path.join(dependencies, "react-dom/server"));
const {Window} = require(path.join(dependencies, "happy-dom/cjs/index.cjs"));
const {buildSync} = require(path.join(dependencies, "esbuild"));
const data = JSON.parse(fs.readFileSync(0, "utf8"));
const output = buildSync({entryPoints:[path.join(root,"app/webui/Upgrade2RunPanel.tsx")],bundle:true,write:false,
  platform:"node",format:"cjs",jsx:"automatic",nodePaths:[dependencies],external:["react","react/jsx-runtime"],loader:{".css":"empty"}});
const moduleView = new Module(path.join(root,"app/webui/Upgrade2RunPanel.cjs"));
moduleView.filename = path.join(root,"app/webui/Upgrade2RunPanel.cjs");
moduleView.paths = [dependencies];
moduleView._compile(output.outputFiles[0].text,moduleView.filename);
const {Upgrade2RunPanel} = moduleView.exports;
const allowed = data.actions.flatMap(action=>action==="ADD_INPUT"?["SUPPLY_INPUT"]:action==="CANCEL"?["CANCEL"]:[]);
const run = {run_id:data.run.run_id,goal:data.run.goal,revision:data.run.revision,goal_revision:data.run.goal_revision,
  status:data.run.status,requirements:data.requirements,allowed_actions:allowed,waiting_inputs:[],intent:null,artifacts:[],projection_ready:false};
const window = new Window();
const render = connection => new window.DOMParser().parseFromString(renderToStaticMarkup(React.createElement(Upgrade2RunPanel,
  {run,events:data.events,event_base_seq:0,connection,loading:false,busy:false,error:null,supplement:"",supplementOutputs:[],
    onSupplementChange:()=>{},onSupplement:()=>{},onSupplementOutputsChange:()=>{},onCancel:()=>{}})),"text/html");
const connected = render("CONNECTED");
assert.match(connected.body.textContent,/等待本人选择必要成果/);
assert.match(connected.body.textContent,/当前没有可核查的方法读取记录/);
assert.match(connected.body.textContent,/方法选择与工具依赖状态尚未提供/);
assert.match(connected.body.textContent,/补充要求/);
assert.equal(connected.querySelector('textarea').disabled,false);
assert.equal(connected.querySelectorAll('input[type="checkbox"]:checked').length,0);
assert.equal(Array.from(connected.querySelectorAll('button')).find(button=>button.textContent==="继续运行").disabled,true);
assert.equal(render("DISCONNECTED").querySelector('textarea').disabled,true);
process.stdout.write(JSON.stringify({waiting_input:true,action_names:data.actions}));
