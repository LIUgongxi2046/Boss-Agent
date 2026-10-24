import {useCallback,useEffect,useRef,useState} from "react";
import {useClient} from "@/providers/ClientProvider";

type Period={report_id:string;source_id:string;source_version:string;period_start:string;period_end:string;quantity:string|null;total_cost:string|null;unit_cost:string|null};
type CostReport={cost_type:string;currency:string;quantity_unit:string;scope_description:string;cost_owner_id:string|null;cost_basis_id:string;report_scope_id:string;baseline:Period|null;current:Period;comparison_state:string;unit_cost_change:string|null;total_cost_change:string|null;formula:string;missing_fields:string[]};
type Projection={business_at:string;review_sha256:string;availability:string;records:{record_id:string;entity_type:string;version:string}[];supply:{material_id:string;cost_reports:CostReport[]}[];coordination_links:{task_id:string;origin_record_id:string}[]};
type Coordinate={interface_id:string;origin_entity_type:string;origin_record_id:string;origin_version:string;review_sha256:string;purpose:string;coordinator_id:string;due_at:string;timezone:string;evidence_requirements:string[]};
type Query={query_id:string;read_at:string;business_at:string;review_sha256:string;cost_report:CostReport;source_refs:{source_id:string;version:string}[];coordinate_input:Coordinate};
type Receipt={client_request_id:string;request_state:string;run_id:string|null;adoption_state:string;origin_reference:{origin_record_id:string;review_sha256:string}|null;query:Query|null;preparation:{client_request_id:string;coordinate_input:Coordinate;owner_decision_required:true;business_authority_granted:false}|null;write_performed_by_lookup:false};
type Task={task_id:string;status:string;version:string;purpose:string;coordinator_id:string;due_at:string;source_refs:string[]};
type Saved={action:string;client_request_id:string;outcome:string;result:{task_id:string;version:string;coordination_link:{origin_record_id:string;review_sha256:string}}|null};
type Document={source_id:string;version:string;content:string;author_contact_id?:string;author_display_name?:string;published_at?:string;observed_at?:string;original_locator?:unknown};
const titles:Record<string,string>={INBOUND_RECEIPT:"入库报告成本",ACTUAL_CONSUMPTION:"实际领用报告成本"};
const shown=(value:string|null)=>value??"未知";
function remember(values:Record<string,string|null>){const url=new URL(window.location.href);for(const [key,value] of Object.entries(values)){if(value===null)url.searchParams.delete(key);else url.searchParams.set(key,value);}window.history.replaceState(null,"",url);}

export function BossMVPView({contacts,onDirtyChange,refreshVersion,onOpenTask}:{contacts:{contact_id:string;name:string}[];onDirtyChange:(value:boolean)=>void;refreshVersion:number;onOpenTask?:(id:string)=>void}){
  const {client,getToken,token}=useClient();
  const [data,setData]=useState<Projection|null>(null),[day,setDay]=useState<{date:string;timezone:string}|null>(null),[selected,setSelected]=useState("");
  const [purpose,setPurpose]=useState(""),[due,setDue]=useState(""),[evidence,setEvidence]=useState("");
  const [receipt,setReceipt]=useState<Receipt|null>(null),[queryKey,setQueryKey]=useState(""),[saved,setSaved]=useState<Saved|null>(null),[coordinateKey,setCoordinateKey]=useState("");
  const [document,setDocument]=useState<Document|null>(null),[sourceId,setSourceId]=useState(""),[tasks,setTasks]=useState<Task[]>([]),[taskId,setTaskId]=useState("");
  const [history,setHistory]=useState<{client_request_id:string;read_at:string;cost_type:string}[]>([]),[busy,setBusy]=useState(false),[loading,setLoading]=useState(true),[error,setError]=useState("");
  const [dirty,setDirty]=useState(false),[uncertain,setUncertain]=useState(false),[coordinatePending,setCoordinatePending]=useState(false),[approved,setApproved]=useState(false),[denied,setDenied]=useState(false);
  const epoch=useRef(0),generation=useRef(0),restoreSequence=useRef(0),deniedRef=useRef(false);
  const queryRef=useRef<Receipt|null>(null);
  queryRef.current=receipt;
  const clearProtected=useCallback(()=>{setData(null);setDay(null);setReceipt(null);setDocument(null);setTasks([]);setHistory([]);setSaved(null);setPurpose("");setDue("");setEvidence("");setApproved(false);},[]);
  const read=useCallback(async<T,>(path:string,signal?:AbortSignal):Promise<T>=>{
    const response=await fetch(path,{headers:{Authorization:"Bearer "+getToken()},cache:"no-store",signal});
    if(response.status===401||response.status===403){deniedRef.current=true;generation.current++;setDenied(true);clearProtected();if(response.status===401)window.dispatchEvent(new Event("boss-auth-expired"));throw new Error("当前身份无法读取采购资料");}
    const result=await response.json();if(!response.ok)throw new Error("HTTP "+response.status+" · "+result.error);return result as T;
  },[getToken,clearProtected]);
  const restore=useCallback(async(key:string,signal?:AbortSignal)=>{
    const current=epoch.current,version=generation.current,sequence=++restoreSequence.current;
    const value=await read<Receipt>("/api/boss/ui/mvp/query?"+new URLSearchParams({client_request_id:key}),signal);
    if(current!==epoch.current||version!==generation.current||sequence!==restoreSequence.current||signal?.aborted||deniedRef.current)return;
    if(value.client_request_id!==key||value.write_performed_by_lookup!==false)throw new Error("采购原请求与回执编号不符");
    const terminal=["SUCCEEDED","FAILED","CANCELED","TIMED_OUT"].includes(value.request_state);queryRef.current=value;setReceipt(value);setQueryKey(key);setUncertain(!terminal);if(terminal)setBusy(false);
    if(value.query){const input=value.query.coordinate_input;setSelected(input.origin_record_id);setPurpose(input.purpose);setDue(input.due_at.slice(0,16));setEvidence(input.evidence_requirements.join("\n"));setDirty(false);}
  },[read]);
  const readSaved=useCallback(async(key:string,signal?:AbortSignal)=>{
    const current=epoch.current,version=generation.current,value=await read<Saved>("/api/boss/ui/supply-quality-receipt?"+new URLSearchParams({action:"boss.supply_quality.coordinate",client_request_id:key}),signal);
    if(current!==epoch.current||version!==generation.current||signal?.aborted||deniedRef.current)return;
    if(value.action!=="boss.supply_quality.coordinate"||value.client_request_id!==key)throw new Error("协调原请求与回执编号不符");
    if(value.result&&(!queryRef.current?.origin_reference||value.result.coordination_link.origin_record_id!==queryRef.current.origin_reference.origin_record_id||value.result.coordination_link.review_sha256!==queryRef.current.origin_reference.review_sha256))throw new Error("该协调回执不属于当前采购查询");
    setSaved(value);setCoordinateKey(key);setCoordinatePending(value.outcome!=="RECORDED");
    if(value.result)setTaskId(value.result.task_id);
    const currentTasks=await read<{tasks:Task[]}>("/api/boss/ui/tasks",signal);if(current===epoch.current&&version===generation.current&&!signal?.aborted&&!deniedRef.current)setTasks(currentTasks.tasks);
  },[read]);
  const reload=useCallback(async(signal?:AbortSignal)=>{
    const current=epoch.current,version=generation.current;
    const values=await Promise.all([read<Projection>("/api/boss/ui/supply-quality?interface_id=SI09",signal),read<{date:string;timezone:string}>("/api/boss/ui/today",signal),read<{requests:typeof history}>("/api/boss/ui/mvp/history",signal),read<{tasks:Task[]}>("/api/boss/ui/tasks",signal)]);
    if(current!==epoch.current||version!==generation.current||signal?.aborted||deniedRef.current)return;
    setData(values[0]);setDay(values[1]);setHistory(values[2].requests);setTasks(values[3].tasks);
  },[read]);
  useEffect(()=>{
    const current=++epoch.current,abort=new AbortController();generation.current++;deniedRef.current=false;setDenied(false);clearProtected();setBusy(false);setLoading(true);setError("");setDirty(false);setApproved(false);setUncertain(false);setCoordinatePending(false);
    const parameters=new URLSearchParams(window.location.search),key=parameters.get("mvpQuery")??"",coordinate=parameters.get("mvpCoordinate")??"";
    setQueryKey(key);setCoordinateKey(coordinate);setSelected(parameters.get("mvpReport")??"");setSourceId(parameters.get("mvpSource")??"");setTaskId(parameters.get("mvpTask")??"");
    void reload(abort.signal).then(async()=>{if(key&&current===epoch.current){setUncertain(true);await restore(key,abort.signal);}if(coordinate&&current===epoch.current){setCoordinatePending(true);await readSaved(coordinate,abort.signal);}}).catch(failure=>{if(current===epoch.current&&!abort.signal.aborted)setError(failure.message);}).finally(()=>{if(current===epoch.current&&!abort.signal.aborted)setLoading(false);});
    return()=>{epoch.current++;generation.current++;restoreSequence.current++;abort.abort();};
  },[token,read,restore,readSaved,reload,clearProtected]);
  useEffect(()=>{if(!loading&&!busy&&!uncertain&&!coordinatePending){setReceipt(null);setDocument(null);void reload().then(()=>{if(queryKey&&!dirty)return restore(queryKey);}).catch(failure=>setError(failure.message));}},[refreshVersion]);
  useEffect(()=>{onDirtyChange(dirty||busy||uncertain||coordinatePending);},[onDirtyChange,dirty,busy,uncertain,coordinatePending]);
  useEffect(()=>{
    if(!sourceId||!receipt?.query||dirty||deniedRef.current)return;
    const abort=new AbortController(),current=epoch.current,version=generation.current;setDocument(null);
    void read<Document>("/api/boss/ui/mvp/source?"+new URLSearchParams({client_request_id:receipt.client_request_id,source_id:sourceId}),abort.signal).then(value=>{if(current===epoch.current&&version===generation.current&&!abort.signal.aborted)setDocument(value);},failure=>{if(current===epoch.current&&version===generation.current&&!abort.signal.aborted)setError(failure.message);});
    return()=>abort.abort();
  },[sourceId,receipt,dirty,read]);
  const reports=data?.supply.flatMap(row=>row.cost_reports.filter(report=>report.baseline).map(report=>({material:row.material_id,report})))??[];
  const selection=reports.find(value=>value.report.current.report_id===selected),origin=data?.records.find(record=>record.record_id===selected&&record.entity_type==="material_cost_report");
  const coordinator=contacts.find(contact=>contact.contact_id==="coordinator-1"),visible=!dirty?receipt?.query:null;
  const blocked=busy||uncertain||coordinatePending||denied;
  const currentTask=tasks.find(task=>task.task_id===taskId);
  function edit(){generation.current++;restoreSequence.current++;setDirty(true);setReceipt(null);setDocument(null);setSourceId("");setApproved(false);setSaved(null);setCoordinateKey("");setTaskId("");remember({mvpSource:null,mvpCoordinate:null,mvpTask:null});}
  function choose(id:string){edit();setSelected(id);remember({mvpReport:id});}
  async function submit(){
    if(blocked||!data||!origin||!selection||!coordinator||!purpose.trim()||!due||!evidence.trim())return;
    const current=epoch.current,version=++generation.current,key="mvp-query-"+crypto.randomUUID();restoreSequence.current++;setDirty(false);setQueryKey(key);setReceipt(null);setDocument(null);setSaved(null);setTaskId("");setCoordinateKey("");setBusy(true);setUncertain(true);setApproved(false);setError("");
    remember({mvpQuery:key,mvpReport:selected,mvpSource:null,mvpCoordinate:null,mvpTask:null});
    const coordinate_input={interface_id:"SI09",origin_entity_type:"material_cost_report",origin_record_id:origin.record_id,origin_version:origin.version,review_sha256:data.review_sha256,
      purpose:purpose.trim(),coordinator_id:coordinator.contact_id,due_at:due+":00+08:00",timezone:"Asia/Shanghai",evidence_requirements:evidence.split("\n").map(value=>value.trim()).filter(Boolean)};
    await client.requestMutation<Receipt>("boss.mvp.query",{client_request_id:key,coordinate_input}).then(async()=>{if(current===epoch.current&&version===generation.current){await restore(key);await reload();}},failure=>{
      if(current!==epoch.current||version!==generation.current)return;setError(failure.message+"；请读取原采购查询 "+key);if([400,401,403,404,409,410,413,422].includes(failure.status))setUncertain(false);
      if([401,403].includes(failure.status)){deniedRef.current=true;setDenied(true);clearProtected();}
    });if(current===epoch.current&&version===generation.current)setBusy(false);
  }
  async function recover(key=queryKey){if(!key||dirty||deniedRef.current)return;const current=epoch.current;generation.current++;setDocument(null);setSourceId("");setError("");remember({mvpQuery:key,mvpSource:null});await restore(key).catch(failure=>{if(current===epoch.current)setError(failure.message);});}
  async function coordinate(){
    if(blocked||!approved||!receipt?.preparation||!visible||dirty||saved?.outcome==="RECORDED")return;
    const current=epoch.current,version=generation.current,key="mvp-coordinate-"+crypto.randomUUID();setCoordinateKey(key);setCoordinatePending(true);setBusy(true);setError("");remember({mvpCoordinate:key});
    await client.requestMutation("boss.fc01.coordinate",{client_request_id:key,preparation_request_id:receipt.client_request_id,coordinate_input:receipt.preparation.coordinate_input}).then(async()=>{if(current===epoch.current&&version===generation.current){await readSaved(key);await reload();}},failure=>{if(current===epoch.current&&version===generation.current)setError(failure.message+"；请读取原协调请求 "+key);});
    if(current===epoch.current&&version===generation.current){setBusy(false);setApproved(false);}
  }
  const openSource=(id:string)=>{setSourceId(id);setDocument(null);remember({mvpSource:id});};
  return <div className="boss-morning-view boss-mvp-view" role="region" aria-label="采购成本连续体验">
    <section className="boss-panel"><header className="boss-panel-head"><h2>今日采购事项</h2><span className="boss-tag boss-tag-amber">SIMULATED</span></header>
      <p>业务日期 {day?.date??"正在读取"} · 时区 {day?.timezone??"正在读取"} · 业务时间 {data?.business_at??"正在读取"}</p>
      <p>当前报告可供本人核查与协调；完整企业成本尚未提供。</p>{loading&&<p role="status">正在读取已有采购场景</p>}{error&&<p role="alert" className="boss-status boss-status-error">{error}</p>}
      {!loading&&reports.length===0&&<p role="status">当前没有具有两个期间的有效采购报告，请维护身份核查已有资料和来源。</p>}
      <div className="boss-actions">{reports.map(value=><button className="boss-btn" key={value.report.current.report_id} disabled={blocked} aria-pressed={selected===value.report.current.report_id} onClick={()=>choose(value.report.current.report_id)}>{titles[value.report.cost_type]} · {value.material}</button>)}</div>
    </section>
    <div className="boss-columns"><div className="boss-column"><section className="boss-panel"><header className="boss-panel-head"><h2>查询采购成本并准备协调材料</h2></header>
      {selection?<><p>当前事项：{titles[selection.report.cost_type]} · {selection.material}</p><p>基期 {selection.report.baseline?.period_start} 至 {selection.report.baseline?.period_end}</p><p>本期 {selection.report.current.period_start} 至 {selection.report.current.period_end}</p></>:<p>选择当前采购事项后查询同一场景的两个期间。</p>}
      <form onSubmit={event=>{event.preventDefault();void submit();}}><fieldset disabled={blocked||!selection}>
        <label>协调目的<textarea aria-label="协调目的" required maxLength={1600} value={purpose} onChange={event=>{edit();setPurpose(event.target.value);}}/></label>
        <p>统筹负责人：{coordinator?coordinator.name+" · "+coordinator.contact_id:"当前负责人尚未读取"}</p>
        <label>截止时间（Asia/Shanghai）<input aria-label="截止时间（Asia/Shanghai）" type="datetime-local" required value={due} onChange={event=>{edit();setDue(event.target.value);}}/></label>
        <label>证据要求（每行一项）<textarea aria-label="证据要求（每行一项）" required value={evidence} onChange={event=>{edit();setEvidence(event.target.value);}}/></label>
        <button className="boss-btn boss-btn-primary" type="submit" disabled={!coordinator}>{busy?"正在读取与准备":"查询成本并准备协调材料"}</button>
      </fieldset></form>
      <p>查询和准备只保存当前结果，协调任务由本人另行确认。</p>{busy&&<button className="boss-btn" onClick={()=>void client.requestMutation("boss.mvp.cancel",{client_request_id:queryKey}).then(()=>setError("取消已经请求，请读取原查询确认终态。"),failure=>setError(failure.message))}>取消当前查询</button>}
    </section>
    <section className="boss-panel"><header className="boss-panel-head"><h2>两个期间成本查询结果</h2></header>{visible?<><p>{titles[visible.cost_report.cost_type]} · 查询 {visible.query_id}</p><p>{visible.cost_report.scope_description}</p>
      <div className="boss-table-scroll"><table className="boss-table"><thead><tr><th>期间</th><th>起止时间</th><th>数量</th><th>报告金额</th><th>单位成本</th></tr></thead><tbody>{(["baseline","current"] as const).map(period=>{const value=visible.cost_report[period];return value&&<tr key={period}><th>{period==="baseline"?"基期":"本期"}</th><td>{value.period_start} 至 {value.period_end}</td><td>{shown(value.quantity)} {visible.cost_report.quantity_unit}</td><td>{shown(value.total_cost)} {visible.cost_report.currency}</td><td>{shown(value.unit_cost)} {visible.cost_report.currency}/{visible.cost_report.quantity_unit}</td></tr>;})}</tbody></table></div>
      <p>单位成本变化 {shown(visible.cost_report.unit_cost_change)} {visible.cost_report.currency}/{visible.cost_report.quantity_unit} · 报告总成本变化 {shown(visible.cost_report.total_cost_change)} {visible.cost_report.currency}</p>
      <p>{visible.cost_report.formula}</p><p>比较状态 {visible.cost_report.comparison_state} · 成本口径 {visible.cost_report.cost_basis_id} · 成本归属 {visible.cost_report.cost_owner_id??"未知"}</p>
      {visible.cost_report.missing_fields.map(value=><p key={value}>{value}</p>)}<div className="boss-actions"><button className="boss-btn" disabled={blocked} onClick={()=>openSource(visible.cost_report.current.source_id)}>查看本期原文依据</button><button className="boss-btn" disabled={blocked||!visible.cost_report.baseline} onClick={()=>visible.cost_report.baseline&&openSource(visible.cost_report.baseline.source_id)}>查看基期原文依据</button></div>
      </>:<p>{dirty?"条件已编辑，请提交当前查询。":receipt?.adoption_state==="HISTORICAL_REQUIRES_REQUERY"?"原查询来源或记录已变化，需要重新查询。":"当前尚无匹配的查询结果。"}</p>}</section>
    <section className="boss-panel"><header className="boss-panel-head"><h2>本次查询原文依据</h2></header>{document?<article className="boss-document-source"><h3>{document.source_id} · v{document.version}</h3><p>作者 {document.author_display_name??document.author_contact_id??"未知"} · 发布 {document.published_at??"未知"} · 更新 {document.observed_at??"未知"}</p><p>原文位置 {JSON.stringify(document.original_locator??"尚未提供")}</p><blockquote>{document.content}</blockquote></article>:<p>{sourceId&&visible?"正在读取本次查询绑定的原文":"从本次查询选择匹配的原文依据。"}</p>}</section>
    </div><div className="boss-column"><section className="boss-panel"><header className="boss-panel-head"><h2>本人确认协调交办</h2></header>
      {visible&&<><p>目的：{visible.coordinate_input.purpose}</p><p>负责人：{coordinator?.name??visible.coordinate_input.coordinator_id} · {visible.coordinate_input.coordinator_id}</p><p>期限：{visible.coordinate_input.due_at}</p><p>证据：{visible.coordinate_input.evidence_requirements.join("；")}</p><p>依据：{visible.coordinate_input.origin_record_id} · v{visible.coordinate_input.origin_version}</p></>}
      <label className="boss-mvp-confirm"><input type="checkbox" checked={approved} disabled={blocked||dirty||!receipt?.preparation||saved?.outcome==="RECORDED"} onChange={event=>setApproved(event.target.checked)}/>本人确认当前依据、负责人、内容、期限与证据要求</label>
      <button className="boss-btn boss-btn-primary" disabled={blocked||!approved||dirty||!receipt?.preparation||saved?.outcome==="RECORDED"} onClick={()=>void coordinate()}>本人确认创建协调任务</button>
      <p>创建仅保存协调交办，后续发送与完成分别处理。</p>{coordinateKey&&<><p>原协调请求 {coordinateKey} · 回执 {saved?.outcome??"结果尚未确认"}</p><button className="boss-btn" disabled={busy||denied} onClick={()=>void readSaved(coordinateKey).catch(failure=>setError(failure.message))}>读取原协调请求回执</button></>}
    </section><section className="boss-panel"><header className="boss-panel-head"><h2>已保存的协调记录</h2></header>{currentTask?<><p>交办 {currentTask.task_id} · 版本 {currentTask.version} · 状态 {currentTask.status}</p><p>{currentTask.purpose}</p><p>负责人 {currentTask.coordinator_id} · 期限 {currentTask.due_at}</p><p>来源 {currentTask.source_refs.join("；")}</p></>:<p>选择已保存交办后读取实际记录。</p>}
      {data?.coordination_links.filter(link=>link.origin_record_id===selected).map(link=><button className="boss-btn" key={link.task_id} disabled={busy||denied} onClick={()=>{setTaskId(link.task_id);remember({mvpTask:link.task_id});void reload().catch(failure=>setError(failure.message));}}>重新打开交办 {link.task_id}</button>)}</section>
    {currentTask&&onOpenTask&&<button className="boss-btn boss-btn-primary" type="button" disabled={blocked||dirty} onClick={()=>onOpenTask(currentTask.task_id)}>进入此项交办详情</button>}
    <section className="boss-panel"><header className="boss-panel-head"><h2>查询记录与原编号恢复</h2></header><p>原采购查询 {queryKey||"尚未提交"}</p><p>查询状态 {receipt?.request_state??(busy?"执行中":uncertain?"结果尚未确认":"尚未提交")} · 来源采用 {receipt?.adoption_state??"尚未读取"}</p>
      {uncertain&&<p role="status">执行结果尚未确定，仅查询同一原编号。</p>}<button className="boss-btn" disabled={!queryKey||dirty||denied} onClick={()=>void recover()}>读取原采购查询结果</button>
      <ul>{history.map(value=><li key={value.client_request_id}><button className="boss-btn" disabled={blocked||dirty} onClick={()=>{setCoordinateKey("");setSaved(null);setTaskId("");remember({mvpCoordinate:null,mvpTask:null});void recover(value.client_request_id);}}>{titles[value.cost_type]} · {value.read_at}</button></li>)}</ul></section>
    <section className="boss-panel"><div className="boss-mascot-work"><img src={busy?"/boss-brand/03-思考分析.webp":"/boss-brand/01-待机悬浮.webp"} alt=""/><div><h2>大鹏 · 采购成本协调</h2><p>{busy?"正在读取实际资料":"等候本人核查与决定"}</p></div></div></section>
    </div></div>
  </div>;
}
