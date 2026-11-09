const assert=require("node:assert/strict");
const fs=require("node:fs");
const path=require("node:path");
const Module=require("node:module");
const {spawn}=require("node:child_process");
const {once}=require("node:events");
const root=path.resolve(__dirname,"../..");
const dependencies=path.join(root,".work/upgrade2-u2-07/dependencies/node_modules");
const React=require(path.join(dependencies,"react"));
const {Window}=require(path.join(dependencies,"happy-dom/cjs/index.cjs"));
const {buildSync}=require(path.join(dependencies,"esbuild"));
const snapshot=JSON.parse(fs.readFileSync(0,"utf8"));
const output=buildSync({entryPoints:[path.join(root,"app/webui/Upgrade2ResumeStatus.tsx"),path.join(root,"app/webui/upgrade2-run-client.ts")],bundle:true,write:false,outdir:path.join(root,"app/tests/resume-permission-build"),platform:"node",format:"cjs",jsx:"automatic",nodePaths:[dependencies],external:["react","react/jsx-runtime"]});
function load(name){const moduleView=new Module(path.join(root,"app/webui/"+name+".cjs"));moduleView.filename=path.join(root,"app/webui/"+name+".cjs");moduleView.paths=[dependencies];moduleView._compile(output.outputFiles.find(item=>item.path.endsWith("/"+name+".js")).text,moduleView.filename);return moduleView.exports;}
async function main(){
  const server=spawn(path.join(root,".work/upgrade2-u2-04/locked-env/bin/python"),[path.join(root,"app/tests/upgrade2-run-client-server.py")],{cwd:root,env:{...process.env,PYTHONDONTWRITEBYTECODE:"1"},stdio:["ignore","pipe","pipe"]});
  let stderr="";server.stderr.on("data",value=>{stderr+=value;});
  const data=await Promise.race([once(server.stdout,"data").then(([value])=>value),once(server,"exit").then(([code])=>{throw new Error("服务启动失败 "+code+": "+stderr);})]);
  const port=Number(String(data).trim());assert.ok(Number.isInteger(port)&&port>0);
  const window=new Window({url:"http://127.0.0.1:"+port+"/"});
  global.window=window;global.document=window.document;global.navigator=window.navigator;global.fetch=window.fetch.bind(window);global.XMLHttpRequest=window.XMLHttpRequest;global.IS_REACT_ACT_ENVIRONMENT=true;
  const {createRoot}=require(path.join(dependencies,"react-dom/client"));
  const {Upgrade2ResumeStatus}=load("Upgrade2ResumeStatus"),{Upgrade2RunClient}=load("upgrade2-run-client");
  const getToken=()=>"",client=new Upgrade2RunClient({getToken}),denied=[];
  let expired=0;window.addEventListener("boss-auth-expired",()=>expired++);
  const container=document.createElement("div");document.body.appendChild(container);const view=createRoot(container);
  await React.act(async()=>view.render(React.createElement(Upgrade2ResumeStatus,{client,snapshot,token:"",getToken,onAccessDenied:status=>denied.push(status)})));
  for(let index=0;index<100&&denied.length===0;index++)await React.act(async()=>{await new Promise(resolve=>setTimeout(resolve,20));});
  assert.deepEqual(denied,[401]);assert.equal(expired,1);assert.match(container.textContent,/HTTP 401/);
  await React.act(async()=>view.unmount());await window.happyDOM.close();server.kill();await once(server,"exit");
  process.stdout.write(JSON.stringify({status:denied[0],expired}));
}
void main();
