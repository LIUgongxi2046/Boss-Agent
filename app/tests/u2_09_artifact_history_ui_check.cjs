const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const Module = require("node:module");
const root = path.resolve(__dirname, "../..");
const dependencies = path.join(root, ".work/upgrade2-u2-07/dependencies/node_modules");
const {buildSync} = require(path.join(dependencies, "esbuild"));
const React = require(path.join(dependencies, "react"));
const {renderToStaticMarkup} = require(path.join(dependencies, "react-dom/server"));
const input = JSON.parse(fs.readFileSync(0, "utf8"));
const output = buildSync({entryPoints:[path.join(root,"app/webui/Upgrade2ArtifactSourceHistory.tsx")],bundle:true,write:false,platform:"node",format:"cjs",jsx:"automatic",nodePaths:[dependencies],external:["react","react/jsx-runtime"]});
const bundle = new Module(path.join(root,"app/tests/u2_09_artifact_history_bundle.cjs"));
bundle.filename = path.join(root,"app/tests/u2_09_artifact_history_bundle.cjs");
bundle.paths = [dependencies];
bundle._compile(output.outputFiles[0].text,bundle.filename);
const {validateArtifactHistory,ArtifactHistoryContent} = bundle.exports;
const listOutput = buildSync({entryPoints:[path.join(root,"app/webui/Upgrade2ArtifactList.tsx")],bundle:true,write:false,platform:"node",format:"cjs",jsx:"automatic",nodePaths:[dependencies],external:["react","react/jsx-runtime"]});
const listBundle = new Module(path.join(root,"app/tests/u2_09_artifact_list_bundle.cjs"));
listBundle.filename = path.join(root,"app/tests/u2_09_artifact_list_bundle.cjs");
listBundle.paths = [dependencies];
listBundle._compile(listOutput.outputFiles[0].text,listBundle.filename);
const {ArtifactAvailability,ArtifactGoalRevision,Upgrade2ArtifactList} = listBundle.exports;
const availability = renderToStaticMarkup(React.createElement(ArtifactAvailability,{item:input.artifact,allowOpen:false,allowExport:false,hasExport:false}));
assert.notEqual(input.artifact.status,"PUBLISHED");
assert.ok(availability.includes("成果尚未发布"));
const list = renderToStaticMarkup(React.createElement(Upgrade2ArtifactList,{runId:input.artifact.run_id,token:"",getToken:()=>"",connected:false,onOpenSource:()=>{},allowOpen:false,allowExport:false}));
assert.ok(list.includes("所属目标版本依据服务核查结果显示"));
for(const revision of [input.goal_before,input.goal_after]){
  const goal=renderToStaticMarkup(React.createElement(ArtifactGoalRevision,{item:input.artifact,current:revision}));
  assert.match(goal,/成果所属目标版本未知/);
}
const data=validateArtifactHistory(input.history,input.reference);
const html=renderToStaticMarkup(React.createElement(ArtifactHistoryContent,{data}));
for(const value of [data.content,data.version,data.current_version,data.locator,data.sha256])assert.ok(html.includes(value));
assert.ok(html.includes("原文位置未经核查"));
for(const field of ["artifact_id","artifact_version","artifact_sha256","source_id","version","sha256","locator"]){
  const changed={...input.reference,[field]:field==="artifact_version"?input.reference[field]+1:input.reference[field]+"x"};
  assert.throws(()=>validateArtifactHistory(input.history,changed),/不一致/);
}
process.stdout.write(JSON.stringify({historical:data.historical}));
