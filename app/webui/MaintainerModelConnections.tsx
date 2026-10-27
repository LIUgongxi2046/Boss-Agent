import {useEffect,useRef,useState} from "react";
import * as Dialog from "@radix-ui/react-dialog";
import {V7Empty,V7Fact,V7Panel,V7ReadState,V7Tabs} from "./BossV7UI";
import {useTechnicalWorkspace} from "./useTechnicalWorkspace";
import {ProductRuntimeConfiguration} from "./ProductRuntimeConfiguration";

type ModelValues={provider:string;api_type:string;model_id:string;credential_reference:string;timeout_seconds:number;max_tool_rounds:number;pricing_version:string;capabilities:string[];change_note:string};
type Validation={id:string;version:string;state:string;at:string;error:string|null;capabilities:string[];usage:string|null;cost:string|null;pricing_version:string|null};
type Version={version:string;values:ModelValues;content_sha256:string;state:string;created_at:string;validation:Validation|null};
type Connection={id:string;title:string;draft:Version|null;current:Version|null;history:Version[];validations:Validation[]};
type Projection={projection:"models";private_body_available_here:false;connections:Connection[];active_connection_id:string|null;
  configuration_version:string;runtime_mode:"SIMULATED_FIRST"|"EXTERNAL_PROVIDER";
  options:{providers:{id:string;label:string}[];api_types:{id:string;label:string}[];credentials:{id:string;label:string}[];pricing:{id:string;label:string}[];capabilities:{id:string;label:string}[]};
  adoption:{run_id:string;connection_id:string;version:string;model_id:string;at:string;state:string}[];
  active_run_count:number;read_at:string};
const EMPTY:ModelValues={provider:"",api_type:"",model_id:"",credential_reference:"",timeout_seconds:120,max_tool_rounds:8,pricing_version:"",capabilities:[],change_note:""};

export function MaintainerModelWorkspace({onNavigate,onDirtyChange,getToken,onCommand,onReload}:{onNavigate:(page:string)=>void;onDirtyChange:(dirty:boolean)=>void;getToken:()=>string;onCommand:(action:string,payload:Record<string,unknown>)=>Promise<void>;onReload:()=>void}){
  const [connectionDirty,setConnectionDirty]=useState(false),[runtimeDirty,setRuntimeDirty]=useState(false);
  useEffect(()=>onDirtyChange(connectionDirty||runtimeDirty),[connectionDirty,runtimeDirty,onDirtyChange]);
  return <><MaintainerModelConnections onNavigate={onNavigate} onDirtyChange={setConnectionDirty}/><details className="boss-panel"><summary>工具与工作资料的 Runtime 范围</summary><ProductRuntimeConfiguration getToken={getToken} onCommand={onCommand} onReload={onReload} onDirtyChange={setRuntimeDirty}/></details></>;
}

export function MaintainerModelConnections({onNavigate,onDirtyChange}:{onNavigate:(page:string)=>void;onDirtyChange:(dirty:boolean)=>void}){
  const api=useTechnicalWorkspace<Projection>("models");
  const [selected,setSelected]=useState("");
  const [values,setValues]=useState<ModelValues>(EMPTY);
  const [dirty,setDirty]=useState(false);
  const [tab,setTab]=useState<"editor"|"active"|"history">("editor");
  const [confirm,setConfirm]=useState<"validate"|"activate"|null>(null);
  const [checked,setChecked]=useState(false);
  const initial=useRef(false);
  const base=useRef("0");
  const selectedReceipt=useRef<string|null>(null);
  const item=api.data?.connections.find(row=>row.id===selected);
  useEffect(()=>{
    if(!api.data||dirty)return;
    const row=api.data.connections.find(row=>row.id===selected)??(!initial.current?api.data.connections[0]:undefined);
    initial.current=true;setSelected(row?.id??"");setValues(row?.draft?.values??row?.current?.values??EMPTY);base.current=row?.draft?.version??"0";
  },[api.data,selected,dirty]);
  useEffect(()=>{
    if(api.receipt?.action!=="save"||selectedReceipt.current===api.receipt.request_id)return;
    selectedReceipt.current=api.receipt.request_id;
    if(typeof api.receipt.result.object_id==="string")setSelected(api.receipt.result.object_id);
  },[api.receipt]);
  const validationPending=api.data?.connections.some(row=>["QUEUED","RUNNING"].includes(row.draft?.validation?.state??""));
  useEffect(()=>{
    if(!validationPending||api.loading||api.error||api.busy)return;
    const timer=window.setTimeout(api.reload,1500);
    return()=>window.clearTimeout(timer);
  },[validationPending,api.loading,api.error,api.busy,api.reload]);
  function edit<K extends keyof ModelValues>(key:K,value:ModelValues[K]){setValues(previous=>({...previous,[key]:value}));setDirty(true);onDirtyChange(true);}
  function save(){void api.execute("save",{object_id:selected||null,expected_version:base.current,values}).then(saved=>{if(saved){setDirty(false);onDirtyChange(false);}});}
  const payload={object_id:selected,expected_version:item?.draft?.version,expected_content_sha256:item?.draft?.content_sha256};
  const activation={...payload,confirmation:true,expected_active_connection_id:api.data?.active_connection_id??null,expected_configuration_version:api.data?.configuration_version,expected_active_version:api.data?.connections.find(row=>row.id===api.data?.active_connection_id)?.current?.version??"0"};
  const unavailable=api.loading||api.busy||!!api.pending;
  const validation=item?.draft?.validation;
  const active=api.data?.connections.find(row=>row.id===api.data?.active_connection_id);
  const adoption=api.data?.adoption.filter(row=>row.connection_id===selected)??[];
  const latestAdoption=[...adoption].sort((a,b)=>a.at.localeCompare(b.at)).at(-1);
  return <div className="boss-model-workspace"><V7ReadState loading={api.loading} error={api.error} onReload={dirty?undefined:api.reload}/>
    {api.pending&&<p className="boss-status boss-status-warn">原请求 {api.pending.request_id} 等待核查。<button className="boss-btn" disabled={api.busy} onClick={()=>void api.reconcile()}>核查原请求</button></p>}
    {api.receipt&&<p role="status" className="boss-status boss-status-ok">操作已记录 · {api.receipt.request_id}</p>}
    {api.data?.runtime_mode==="SIMULATED_FIRST"&&<p className="boss-status">当前运行方式：显式模拟。实际连接验证与模型启用分别记录。</p>}
    <div className="boss-columns"><div className="boss-column">
      <V7Panel title="模型与 Provider 配置">
        <V7Tabs label="模型配置视图" value={tab} onChange={setTab} items={[{id:"editor",title:"模型配置"},{id:"active",title:"当前启用版本"},{id:"history",title:"版本记录"}]}/>
        <label className="boss-field">模型连接<select disabled={dirty||unavailable} value={selected} onChange={event=>setSelected(event.target.value)}><option value="">新建连接</option>{api.data?.connections.map(row=><option key={row.id} value={row.id}>{row.title}</option>)}</select></label>
        {tab==="editor"&&<form onSubmit={event=>{event.preventDefault();save();}}><fieldset disabled={unavailable||!api.data} className="boss-v7-form-fieldset"><div className="boss-form-grid">
          <label>Provider<select required value={values.provider} onChange={event=>edit("provider",event.target.value)}><option value="">请选择</option>{api.data?.options.providers.map(row=><option key={row.id} value={row.id}>{row.label}</option>)}</select></label>
          <label>API 类型<select required value={values.api_type} onChange={event=>edit("api_type",event.target.value)}><option value="">请选择</option>{api.data?.options.api_types.map(row=><option key={row.id} value={row.id}>{row.label}</option>)}</select></label>
          <label>model_id<input required value={values.model_id} onChange={event=>edit("model_id",event.target.value)}/></label>
          <label>服务端凭据引用<select required value={values.credential_reference} onChange={event=>edit("credential_reference",event.target.value)}><option value="">请选择已配置的引用</option>{api.data?.options.credentials.map(row=><option key={row.id} value={row.id}>{row.label}</option>)}</select></label>
          <label>超时（秒）<input type="number" required min={1} max={600} value={values.timeout_seconds} onChange={event=>edit("timeout_seconds",event.target.valueAsNumber)}/></label>
          <label>轮数限制<input type="number" required min={1} max={12} value={values.max_tool_rounds} onChange={event=>edit("max_tool_rounds",event.target.valueAsNumber)}/></label>
          <label>用量计价<select required value={values.pricing_version} onChange={event=>edit("pricing_version",event.target.value)}><option value="">请选择计价版本</option>{api.data?.options.pricing.map(row=><option key={row.id} value={row.id}>{row.label}</option>)}</select></label>
          <V7Fact label="当前编辑版本">{item?.draft?.version??"尚未保存"}</V7Fact>
        </div><fieldset className="boss-v7-check-list"><legend>需要验证的能力</legend>{api.data?.options.capabilities.map(row=><label key={row.id}><input type="checkbox" checked={values.capabilities.includes(row.id)} onChange={event=>edit("capabilities",event.target.checked?[...values.capabilities,row.id]:values.capabilities.filter(id=>id!==row.id))}/>{row.label}</label>)}</fieldset>
        <label className="boss-field">变更说明<textarea required rows={3} value={values.change_note} onChange={event=>edit("change_note",event.target.value)}/></label>
        <div className="boss-actions"><button type="submit" className="boss-btn" disabled={!dirty||validation?.state==="QUEUED"||validation?.state==="RUNNING"}>保存草稿</button><button type="button" className="boss-btn" disabled={dirty||!item?.draft||validation?.state==="QUEUED"||validation?.state==="RUNNING"} onClick={()=>{setChecked(false);setConfirm("validate");}}>验证此版本的模型连接</button>{validation?.state==="QUEUED"&&<button type="button" className="boss-btn" onClick={()=>void api.execute("cancel",payload)}>取消未执行验证</button>}<button type="button" className="boss-btn" disabled={!dirty} onClick={()=>{setDirty(false);onDirtyChange(false);}}>放弃本次编辑</button></div>
        </fieldset></form>}
        {tab==="active"&&(active?.current?<><V7Fact label="连接">{active.title}</V7Fact><V7Fact label="Provider">{active.current.values.provider}</V7Fact><V7Fact label="model_id">{active.current.values.model_id}</V7Fact><V7Fact label="启用版本">{active.current.version}</V7Fact><V7Fact label="已验证能力">{active.current.validation?.capabilities.join("、")??"没有验证记录"}</V7Fact></>:<V7Empty title="当前没有启用的模型版本"/>)}
        {tab==="history"&&(item?.history.length?<div className="boss-v7-table-scroll"><table className="boss-v7-table"><thead><tr><th>版本</th><th>模型</th><th>状态</th><th>保存时间</th><th>变更说明</th></tr></thead><tbody>{item.history.map(row=><tr key={row.version}><td>{row.version}</td><td>{row.values.model_id}</td><td>{row.state}</td><td>{row.created_at}</td><td>{row.values.change_note}</td></tr>)}</tbody></table></div>:<V7Empty title="尚无版本记录"/>)}
        <p className="boss-v7-note">凭据仅显示服务端引用。真实连接验证通过后才能启用对应版本。</p>
      </V7Panel>
      <V7Panel title="启用与实际采用"><V7Fact label="当前草稿">{item?.draft?.version??"尚未保存"}</V7Fact><V7Fact label="当前启用连接">{active?.title??"尚未启用"}</V7Fact><V7Fact label="当前启用版本">{active?.current?.version??"尚未启用"}</V7Fact><V7Fact label="本次验证结果">{validation?.state??"未验证"}</V7Fact><V7Fact label="实际采用版本">{latestAdoption?`${latestAdoption.model_id} · v${latestAdoption.version} · ${latestAdoption.at}`:"当前连接尚无实际采用记录"}</V7Fact><V7Fact label="在途运行">{api.data?.active_run_count??"尚未读取"}</V7Fact><div className="boss-actions"><button className="boss-btn boss-btn-primary" disabled={unavailable||dirty||validation?.state!=="PASSED"||api.data?.active_run_count!==0} onClick={()=>{setChecked(false);setConfirm("activate");}}>启用此模型版本</button><button className="boss-btn" onClick={()=>onNavigate("A16")}>查看同一任务集的模型评测</button></div></V7Panel>
    </div><aside className="boss-column">
      <V7Panel title="真实连接记录">{validation?<><V7Fact label="验证版本">{validation.version}</V7Fact><V7Fact label="验证发生时间">{validation.at}</V7Fact><V7Fact label="验证状态">{validation.state}</V7Fact><V7Fact label="连接错误">{validation.error??"没有已记录错误"}</V7Fact><V7Fact label="验证能力">{validation.capabilities.join("、")||"尚无通过的能力"}</V7Fact><V7Fact label="用量">{validation.usage??"未提供"}</V7Fact><V7Fact label="费用与计价版本">{validation.cost??"无法核算"} · {validation.pricing_version??"未记录"}</V7Fact></>:<V7Empty title="尚无本版本的实际连接验证"/>}<button className="boss-btn" onClick={()=>onNavigate("A15")}>查看此模型的运行与用量</button></V7Panel>
    </aside></div>
    <V7Panel title="版本、验证与实际采用记录" className="boss-model-records">
      <div className="boss-model-status-grid"><V7Fact label="当前编辑">{dirty?"存在未保存修改":item?.draft?.version??"尚未保存"}</V7Fact><V7Fact label="真实连接验证">{validation?.state??"尚未执行"}</V7Fact><V7Fact label="允许启用">{dirty?"需要保存并验证当前修改":validation?.state==="PASSED"?api.data?.active_run_count===0?"当前版本可以启用":"等待在途运行结束":"等待当前版本验证"}</V7Fact><V7Fact label="实际运行采用">{latestAdoption?`v${latestAdoption.version} · ${latestAdoption.state}`:"当前连接尚无采用记录"}</V7Fact></div>
      <details><summary>全部连接验证 · {item?.validations.length??0} 条</summary>{item?.validations.length?<div className="boss-v7-table-scroll"><table className="boss-v7-table"><thead><tr><th>验证编号</th><th>连接版本</th><th>状态</th><th>时间</th><th>用量</th><th>错误</th></tr></thead><tbody>{item.validations.map(row=><tr key={row.id}><td>{row.id}</td><td>{row.version}</td><td>{row.state}</td><td>{row.at}</td><td>{row.usage??"未提供"}</td><td>{row.error??"没有已记录错误"}</td></tr>)}</tbody></table></div>:<V7Empty title="尚无连接验证记录"/>}</details>
      <details><summary>当前连接的运行采用 · {adoption.length} 条</summary>{adoption.length?<div className="boss-v7-table-scroll"><table className="boss-v7-table"><thead><tr><th>运行编号</th><th>模型</th><th>采用版本</th><th>状态</th><th>时间</th></tr></thead><tbody>{adoption.map(row=><tr key={row.run_id}><td>{row.run_id}</td><td>{row.model_id}</td><td>{row.version}</td><td>{row.state}</td><td>{row.at}</td></tr>)}</tbody></table></div>:<V7Empty title="尚无实际采用记录"/>}</details>
    </V7Panel>
    <Dialog.Root open={!!confirm} onOpenChange={open=>{if(!open)setConfirm(null);}}><Dialog.Portal><Dialog.Overlay className="boss-v7-dialog-overlay"/><Dialog.Content className="boss-v7-dialog"><Dialog.Title>{confirm==="validate"?"执行实际连接验证":"启用当前模型版本"}</Dialog.Title><Dialog.Description>{confirm==="validate"?"将使用当前服务端凭据向所选 Provider 发起实际请求，记录服务返回的用量；缺少已核实价格时，费用保持未知。":"后续任务采用此模型版本，已经开始的运行保留其原配置。"} 连接 {selected} · 版本 {item?.draft?.version}。</Dialog.Description><label className="boss-confirm-check"><input type="checkbox" checked={checked} onChange={event=>setChecked(event.target.checked)}/>确认当前对象、版本与操作</label><div className="boss-actions"><Dialog.Close asChild><button className="boss-btn">取消</button></Dialog.Close><button className="boss-btn boss-btn-primary" disabled={!checked||unavailable} onClick={()=>{if(!confirm)return;void api.execute(confirm,confirm==="activate"?activation:{...payload,external_request_confirmed:true});setConfirm(null);}}>确认执行</button></div></Dialog.Content></Dialog.Portal></Dialog.Root>
  </div>;
}
