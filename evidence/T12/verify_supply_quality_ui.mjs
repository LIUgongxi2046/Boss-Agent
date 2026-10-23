import assert from "node:assert/strict";
import {execFileSync} from "node:child_process";
import {createRequire} from "node:module";
import {mkdirSync, writeFileSync} from "node:fs";
import path from "node:path";

const project=process.cwd();
const uiRoot=process.argv[2];
const output=path.resolve(process.argv[3]);
assert(uiRoot&&output.startsWith(path.join(project,".work")+path.sep));
mkdirSync(output,{recursive:true});
const require=createRequire(path.join(uiRoot,"package.json"));
const {Window}=require("happy-dom");
const window=new Window();
Object.defineProperty(globalThis,"navigator",{value:window.navigator,configurable:true});
Object.assign(globalThis,{window,document:window.document,HTMLElement:window.HTMLElement,Node:window.Node,IS_REACT_ACT_ENVIRONMENT:true});
const esbuild=require("esbuild");
const compiled=path.join(output,"panels.cjs");
esbuild.buildSync({stdin:{contents:'export {BossSupplyQualityPanel} from "./app/webui/BossSupplyQualityPanel"; export {BossAssignmentSourceReview} from "./app/webui/BossAssignmentSourceReview";',resolveDir:project,loader:"tsx"},outfile:compiled,bundle:true,platform:"node",format:"cjs",jsx:"automatic",external:["react","react/jsx-runtime"],nodePaths:[path.join(uiRoot,"node_modules")]});
const React=require("react");
const {render,fireEvent,screen,waitFor,cleanup}=require("@testing-library/react");
const {BossSupplyQualityPanel,BossAssignmentSourceReview}=require(compiled);
const database=path.join(output,"ui-store.sqlite");
function bridge(mode,payload={}){
  return JSON.parse(execFileSync(path.join(project,"validation/.venv/bin/python"),["evidence/T12/supply_quality_ui_bridge.py","--database",database,"--mode",mode,"--payload",JSON.stringify(payload)],{cwd:project,encoding:"utf8"}));
}
assert.equal(bridge("initialize").record_count,21);
const sourceRecord=bridge("read",{interface_id:"SI10"}).records.find(record=>record.record_id==="sim-production-event-1");
const source={observed_at:sourceRecord.observed_at,valid_from:sourceRecord.valid_from,valid_until:sourceRecord.valid_until,author_contact_id:sourceRecord.author_contact_id};
const costs=[];
for(const [costType,amounts] of [["INBOUND_RECEIPT",["20000","21000"]],["ACTUAL_CONSUMPTION",["4000","4300"]]]){
  amounts.forEach((total,index)=>costs.push({entity_type:"material_cost_report",expected_version:"0",source,data:{report_id:"sim-ui-cost-"+costType.toLowerCase()+"-"+index,
    material_id:"sim-material-1",legal_entity_id:"entity-1",asset_owner_id:"entity-1",cost_owner_id:"entity-1",ownership_type:"COMPANY",customer_id:null,cost_type:costType,
    report_scope_id:"sim-ui-cost-scope",cost_basis_id:"sim-reported-direct-material",scope_description:"SIMULATED：仅当前明确库存的报告成本，用于组件行为检查。",
    period_start:"2026-10-"+(19+index)+"T18:00:00+08:00",period_end:"2026-10-"+(20+index)+"T18:00:00+08:00",inventory_ids:["sim-stock-available-1"],
    quantity:costType==="INBOUND_RECEIPT"?"10":"2",total_cost:total,quantity_unit:"tonne",currency:"CNY",state:"REPORTED"}}));
}
assert.equal(bridge("command",{role:"MAINTAINER",action:"boss.simulation.supply_quality.import",input:{client_request_id:"sim-ui-cost-import",mode:"SIMULATED",simulation_definition:"si09-si10-business-v1",outcome:"SUCCESS",records:costs,error_code:null}}).record_count,4);
const supply=bridge("read",{interface_id:"SI09"});
const emptyEditor={originId:"",purpose:"",due:"",evidence:"",approvedFor:null,pending:null};
const common={loading:false,error:"",editor:emptyEditor,onEditorChange:()=>{},onOpenSource:()=>assert.fail("当前检查没有授权打开资料窗口"),onOpenTask:()=>{},onReceipt:()=>assert.fail("本次成功请求不需要查询回执")};
render(React.createElement(BossSupplyQualityPanel,{...common,data:supply,onReload:()=>{},onCommand:()=>assert.fail("读取库存不执行协调写入")}));
assert(screen.getAllByText("20 tonne").length>0);
assert(screen.getAllByText("10 日").length>0);
assert(screen.getByRole("region",{name:"已报告入库成本"}).textContent.includes("2100 CNY/tonne"));
assert(screen.getByRole("region",{name:"已报告实际领用成本"}).textContent.includes("2150 CNY/tonne"));
assert.equal(screen.getByRole("button",{name:"本人确认创建协调任务"}).disabled,true);
cleanup();
const quality=bridge("read",{interface_id:"SI10"});
function Harness(){
  const [data,setData]=React.useState(quality);
  const [editor,setEditor]=React.useState(emptyEditor);
  return React.createElement(BossSupplyQualityPanel,{...common,data,editor,onEditorChange:changes=>setEditor(current=>({...current,...changes})),onReload:()=>setData(bridge("read",{interface_id:"SI10"})),
    onCommand:async(action,input)=>bridge("command",{role:"BOSS",action,input})});
}
render(React.createElement(Harness));
fireEvent.change(screen.getByLabelText("协调依据"),{target:{value:"production_event:sim-production-event-1"}});
fireEvent.change(screen.getByLabelText("协调目的"),{target:{value:"汇总当前SIMULATED批次核查资料"}});
fireEvent.change(screen.getByLabelText("截止时间（Asia/Shanghai）"),{target:{value:"2026-10-24T17:00"}});
fireEvent.change(screen.getByLabelText("证据要求（每行一项，最多八项）"),{target:{value:"当前明确的模拟来源"}});
assert.equal(screen.getByRole("button",{name:"本人确认创建协调任务"}).disabled,true);
fireEvent.click(screen.getByLabelText("本人确认当前依据、负责人、期限与证据要求"));
fireEvent.click(screen.getByRole("button",{name:"本人确认创建协调任务"}));
await waitFor(()=>assert(screen.getByText("协调任务已经保存，请打开交办查看发送与后续状态。")),{timeout:30000});
const persisted=bridge("verify");
assert.equal(persisted.tasks.length,1);
assert.equal(persisted.tasks[0].status,"OPEN");
assert.equal(persisted.tasks[0].related_meeting_id,null);
assert.equal(persisted.outbox_count,0);
assert.equal(persisted.event_state,"PROFESSIONAL_REVIEW_PENDING");
assert.equal(persisted.stock_state,"HOLD");
cleanup();
const professional=quality.records.find(record=>record.entity_type==="professional_record"&&record.record_id==="sim-quality-review-1");
bridge("command",{role:"MAINTAINER",action:"boss.simulation.supply_quality.import",input:{client_request_id:"sim-ui-professional-update",mode:"SIMULATED",simulation_definition:"si09-si10-business-v1",outcome:"SUCCESS",error_code:null,records:[{entity_type:"professional_record",expected_version:professional.version,source:{observed_at:professional.observed_at,valid_from:professional.valid_from,valid_until:professional.valid_until,author_contact_id:professional.author_contact_id},data:{...professional.data,state:"PROFESSIONALLY_CONFIRMED",conclusion:"PASS_REPORTED"}}]}});
const review=bridge("review",{task_id:persisted.tasks[0].task_id});
assert.equal(review.can_confirm,false);
render(React.createElement(BossAssignmentSourceReview,{data:review,loading:false,error:"",onReload:()=>{},onOpenSource:()=>{},onDirtyChange:()=>{},onCommand:()=>assert.fail("关联资料变化时不能确认采用"),onReceipt:()=>assert.fail("本次没有来源确认请求")}));
assert(screen.getAllByText("关联资料已经变化，需要重新导入当前外部记录。").length>0);
assert.equal(screen.getByRole("button",{name:"本人确认当前来源"}).disabled,true);
cleanup();
const result={source_type:"SIMULATED",external_services_invoked:false,environment:"happy-dom and actual React; direct local SupplyQualityAPI and SQLite",checks:["真实库存计算读取","独立入库与实际领用成本","填写协调目的与期限","本人确认控制","实际SQLite保存与重读","原事件和库存状态独立","关联资料变化阻止来源确认"],public_authenticated_channel:"NOT_RUN",visual:"NOT_RUN",task_id:persisted.tasks[0].task_id};
writeFileSync(path.join(output,"result.json"),JSON.stringify(result,null,2)+"\n");
console.log(JSON.stringify(result));
