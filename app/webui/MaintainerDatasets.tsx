import {useEffect,useId,useRef,useState} from "react";
import {useClient} from "@/providers/ClientProvider";
import * as Dialog from "@radix-ui/react-dialog";
import {Database, RefreshCw, ShieldCheck} from "lucide-react";
import {V7Empty,V7Fact,V7Panel,V7Pagination,V7ReadState} from "./BossV7UI";
import {useTechnicalWorkspace} from "./useTechnicalWorkspace";

type Dataset={id:string;version:string;seed:number;scale:string;period_start:string;period_end:string;generator_version:string;relationship_version:string;state:string;created_at:string;counts:Record<string,number>;checks:{name:string;state:string;message:string}[];facts_sha256:string;validated_at:string;totals:Record<string,Record<string,string>>};
type Transition={request_id:string;action:string;state:string;namespace:string;previous_namespace:string;dataset_id:string;dataset_version:string;requested_at:string;activated_at:string|null;runtime_adopted_at:string|null;error:string|null};
type Projection={projection:"datasets";private_body_available_here:false;current:{dataset_id:string;version:string;namespace:string;business_clock:string};
  datasets:Dataset[];generator_versions:string[];relationship_versions:string[];scales:{id:string;label:string}[];
  reset_impact:{version:string;namespace:string;sessions:number;memories:number;tasks:number;plans:number;outbox:number;active_runs:number;schedule_configurations:number;model_validation_jobs:number;checked_at:string;state:"CURRENT"|"STALE"}|null;
  history:{namespace:string;dataset_id:string;version:string;state:string;created_at:string|null;history_available:boolean}[];transitions:Transition[];inspection_available:boolean;transition_available:boolean;transition_reason:string|null;read_at:string};

type GeneratedRecords={dataset_id:string;version:string;source_type:"SIMULATED";kind:string;facts_sha256:string;offset:number;limit:number;total:number;records:unknown[]};
type Confirmation={action:"load"|"reset";datasetId:string;datasetVersion:string;factsSha256:string;namespace:string;impactVersion:string};
const EMPTY_GENERATOR={seed:"",scale:"",period_start:"",period_end:"",generator_version:"",relationship_version:""};
export type {Dataset,Projection as DatasetProjection};
type HistoryRecords={namespace:string;state:"READ_ONLY";dataset_id:string;dataset_version:string;archived_at:string;private_body_available_here:false;current_evidence_eligible:false;counts:Record<string,number>;runtime:{runs:{run_id:string;status:string;started_at:string;finished_at:string|null;runtime:{provider:string;model_id:string};tool_results:unknown[]}[];matched_count:number;next_cursor:{cursor_started_at:string;cursor_run_id:string}|null}};
function DatasetHistory({namespace}:{namespace:string}){
  const {getToken,token}=useClient();
  const [loaded,setLoaded]=useState<{token:string|null;data:HistoryRecords}|null>(null);
  const [query,setQuery]=useState("");
  const [error,setError]=useState("");
  const [loading,setLoading]=useState(true);
  const [refresh,setRefresh]=useState(0);
  const data=loaded?.token===token&&loaded.data.namespace===namespace?loaded.data:null;
  useEffect(()=>{
    const abort=new AbortController();setLoading(true);setLoaded(null);setError("");
    void fetch("/api/boss/ui/admin/technical/datasets/history/"+encodeURIComponent(namespace)+(query?"?"+query:""),{headers:{Authorization:"Bearer "+getToken()},cache:"no-store",signal:abort.signal}).then(async response=>{
      if(response.status===401)window.dispatchEvent(new Event("boss-auth-expired"));
      if(!response.ok)throw new Error("历史空间读取失败（HTTP "+response.status+"）");
      const value=await response.json() as HistoryRecords;
      if(value.namespace!==namespace||value.state!=="READ_ONLY"||value.private_body_available_here!==false||value.current_evidence_eligible!==false)throw new Error("历史空间范围不符合当前要求");
      if(!abort.signal.aborted){setLoaded({token,data:value});setLoading(false);}
    }).then(undefined,reason=>{if(!abort.signal.aborted){setLoading(false);setError(reason.message);}});
    return()=>abort.abort();
  },[namespace,query,getToken,token,refresh]);
  const labels:Record<string,string>={sessions:"原生会话",memory:"本人记忆",task:"交办任务",owner_plan:"本人计划",outbox:"发件箱",query:"经营查询",runtime_run:"实际运行"};
  return <><V7ReadState loading={loading} error={error} onReload={()=>setRefresh(value=>value+1)}/>{data&&<><p className="boss-status">历史资料保持只读，不能作为当前空间的业务依据。私人正文仅在本人入口提供。</p><V7Fact label="归档时间">{data.archived_at}</V7Fact><div className="boss-form-grid">{Object.entries(data.counts).map(([key,value])=><V7Fact key={key} label={labels[key]??key}>{value}</V7Fact>)}</div><p>实际运行 · 共{data.runtime.matched_count}项</p>{data.runtime.runs.map(run=><article className="boss-workspace-item" key={run.run_id}><strong>{run.status} · {run.run_id}</strong><p>{run.runtime.provider} / {run.runtime.model_id}</p><V7Fact label="开始 / 结束">{run.started_at} / {run.finished_at??"尚无结束记录"}</V7Fact><V7Fact label="工具结果">{run.tool_results.length}项</V7Fact></article>)}<div className="boss-actions"><button className="boss-btn" disabled={!query} onClick={()=>setQuery("")}>返回首页</button><button className="boss-btn" disabled={!data.runtime.next_cursor} onClick={()=>{if(data.runtime.next_cursor)setQuery(new URLSearchParams(data.runtime.next_cursor).toString());}}>读取下一页</button></div></>}</>;
}

function DatasetRecords({dataset}:{dataset:Dataset}){
  const {getToken,token}=useClient();
  const [kind,setKind]=useState("financial_detail");
  const [offset,setOffset]=useState(0);
  const [loaded,setRecords]=useState<GeneratedRecords|null>(null);
  const [loadedToken,setLoadedToken]=useState(token);
  const records=loadedToken===token&&loaded?.dataset_id===dataset.id&&loaded.kind===kind&&loaded.offset===offset?loaded:null;
  const [error,setError]=useState("");
  const [loading,setLoading]=useState(true);
  const [refresh,setRefresh]=useState(0);
  useEffect(()=>{
    const abort=new AbortController();setRecords(null);setError("");setLoading(true);
    const query=new URLSearchParams({kind,offset:String(offset)});
    void fetch("/api/boss/ui/admin/technical/datasets/"+encodeURIComponent(dataset.id)+"/records?"+query.toString(),{headers:{Authorization:"Bearer "+getToken()},signal:abort.signal,cache:"no-store"}).then(async response=>{
      if(response.status===401)window.dispatchEvent(new Event("boss-auth-expired"));
      if(!response.ok)throw new Error("生成明细读取失败（HTTP "+response.status+"）");
      const value=await response.json() as GeneratedRecords;
      if(value.dataset_id!==dataset.id||value.version!==dataset.version||value.facts_sha256!==dataset.facts_sha256||value.kind!==kind||value.offset!==offset||value.source_type!=="SIMULATED")throw new Error("生成明细与当前数据集范围不一致");
      if(!abort.signal.aborted){setRecords(value);setLoadedToken(token);setLoading(false);}
    }).then(undefined,reason=>{if(!abort.signal.aborted){setError(reason.message);setLoading(false);}});
    return()=>abort.abort();
  },[dataset.id,dataset.version,dataset.facts_sha256,kind,offset,getToken,token,refresh]);
  return <div><div className="boss-v7-filter-bar"><label>资料类别<select value={kind} onChange={event=>{setKind(event.target.value);setOffset(0);}}>{Object.keys(dataset.counts).map(name=><option key={name}>{name}</option>)}</select></label></div>
    <V7ReadState loading={loading} error={error} onReload={()=>setRefresh(value=>value+1)}/>
    {records&&<><p>SIMULATED · {records.total}项记录 · 当前第{offset+1}至{Math.min(offset+records.limit,records.total)}项</p>{records.records.map((record,index)=><pre className="boss-v7-code" key={offset+index}>{JSON.stringify(record,null,2)}</pre>)}<div className="boss-actions"><button className="boss-btn" disabled={offset===0} onClick={()=>setOffset(value=>Math.max(0,value-records.limit))}>上一页</button><button className="boss-btn" disabled={offset+records.limit>=records.total} onClick={()=>setOffset(value=>value+records.limit)}>下一页</button></div></>}
  </div>;
}

export function MaintainerDatasets({onNavigate,onDirtyChange}:{onNavigate:(page:string)=>void;onDirtyChange:(dirty:boolean)=>void}){
  const api=useTechnicalWorkspace<Projection>("datasets");
  const {token}=useClient();
  const formId=useId();
  const [values,setValues]=useState(EMPTY_GENERATOR);
  const [selected,setSelected]=useState("");
  const [confirm,setConfirm]=useState<Confirmation|null>(null);
  const [checked,setChecked]=useState(false);
  const [expanded,setExpanded]=useState(false);
  const [error,setError]=useState("");
  const [page,setPage]=useState(1),[recordDetail,setRecordDetail]=useState<Transition|null>(null);
  const currentId=selected||api.data?.datasets[0]?.id;
  const focusApplied=useRef(false);
  useEffect(()=>{if(!api.data||focusApplied.current)return;focusApplied.current=true;const sectionId=new URLSearchParams(window.location.search).get("bossSimulationSection");if(sectionId&&["generate","checks","reset","history"].includes(sectionId)){const section=document.querySelector<HTMLElement>(".boss-dataset-"+sectionId);section?.setAttribute("tabindex","-1");section?.scrollIntoView({block:"start",behavior:"smooth"});section?.focus();}},[api.data]);
  const [historyNamespace,setHistoryNamespace]=useState<string|null>(null);
  const current=api.data?.datasets.find(row=>row.id===currentId);
  const loaded=api.data?.datasets.find(row=>row.id===api.data?.current.dataset_id&&row.version===api.data.current.version);
  const target=confirm?api.data?.datasets.find(row=>row.id===confirm.datasetId):null;
  const impact=api.data?.reset_impact;
  const disabled=api.busy||api.loading||!!api.pending;
  const confirmationCurrent=!!confirm&&!!target&&target.version===confirm.datasetVersion&&target.facts_sha256===confirm.factsSha256&&target.state==="VALIDATED"&&api.data?.current.namespace===confirm.namespace&&impact?.namespace===confirm.namespace&&impact.version===confirm.impactVersion&&impact.state==="CURRENT"&&api.data.transition_available;
  useEffect(()=>{setValues(EMPTY_GENERATOR);setSelected("");setConfirm(null);setChecked(false);setExpanded(false);setError("");setPage(1);setRecordDetail(null);setHistoryNamespace(null);focusApplied.current=false;onDirtyChange(false);},[token,onDirtyChange]);
  useEffect(()=>()=>onDirtyChange(false),[onDirtyChange]);
  useEffect(()=>{const identifier=api.receipt?.result.dataset_id;if(typeof identifier==="string")setSelected(identifier);},[api.receipt]);
  function edit(key:keyof typeof values,value:string){setValues(old=>({...old,[key]:value}));onDirtyChange(true);setError("");}
  function generate(){
    if(disabled||!api.data)return;
    if(!Object.values(values).every(Boolean)){setError("请填写完整的数据生成条件");return;}
    const seed=Number(values.seed);
    if(!Number.isSafeInteger(seed)||seed<0){setError("seed 必须为有效的非负整数");return;}
    if(values.period_end<values.period_start){setError("结束期间必须晚于或等于开始期间");return;}
    void api.execute("generate",{...values,seed}).then(saved=>{if(saved)onDirtyChange(false);});
  }
  function prepare(action:"load"|"reset"){
    const dataset=action==="reset"?loaded:current;
    if(disabled||!api.data||!dataset||dataset.state!=="VALIDATED"||impact?.state!=="CURRENT"||impact.namespace!==api.data.current.namespace||!api.data.transition_available)return;
    setConfirm({action,datasetId:dataset.id,datasetVersion:dataset.version,factsSha256:dataset.facts_sha256,namespace:api.data.current.namespace,impactVersion:impact.version});setChecked(false);
  }
  function execute(){
    if(!confirm||!checked||!confirmationCurrent||disabled)return;
    void api.execute(confirm.action,{dataset_id:confirm.datasetId,expected_dataset_version:confirm.datasetVersion,expected_namespace:confirm.namespace,impact_version:confirm.impactVersion,confirmed:true});setConfirm(null);setChecked(false);
  }
  const rows=[...(api.data?.datasets.map(row=>({key:"dataset:"+row.id,component:"数据生成",request:row.id,at:row.created_at,state:row.state,dataset:row,transition:null as Transition|null}))??[]),...(api.data?.transitions.map(row=>({key:"transition:"+row.request_id,component:row.action==="reset"?"空间重置":"数据载入",request:row.request_id,at:row.requested_at,state:row.state,dataset:null as Dataset|null,transition:row}))??[])].sort((a,b)=>b.at.localeCompare(a.at));
  const currentPage=Math.min(page,Math.max(1,Math.ceil(rows.length/10)));
  const controls=<><button className="boss-btn boss-btn-primary" type="submit" form={formId} disabled={disabled||!api.data}>生成模拟数据</button><button className="boss-btn" disabled={disabled||current?.state!=="VALIDATED"||impact?.state!=="CURRENT"||!api.data?.transition_available} onClick={()=>prepare("load")}>载入数据</button><button className="boss-btn" disabled={disabled||!current} onClick={()=>{if(current)void api.execute("validate",{dataset_id:current.id,expected_dataset_version:current.version});}}>检查关系</button><button className="boss-btn" disabled={disabled||loaded?.state!=="VALIDATED"||impact?.state!=="CURRENT"||!api.data?.transition_available} onClick={()=>prepare("reset")}>重置空间</button></>;
  return <div className="boss-maintainer-records boss-dataset-workspace">
    <V7ReadState loading={api.loading} error={api.error||error} onReload={api.reload}/>
    {api.pending&&<p className="boss-status boss-status-warn">原请求 {api.pending.request_id} 等待核查。<button className="boss-btn" disabled={api.busy} onClick={()=>void api.reconcile()}>查询原请求</button></p>}
    {api.receipt&&<p role="status" className="boss-status boss-status-ok">数据操作已记录 · {api.receipt.request_id}</p>}
    <div className="boss-maintainer-columns"><div className="boss-column">
      <V7Panel title="数据集生成条件" className="boss-dataset-generate" description="SIMULATED · 仅针对获准的模拟资料">
        <form id={formId} onSubmit={event=>{event.preventDefault();generate();}}><fieldset disabled={disabled||!api.data} className="boss-v7-form-fieldset"><div className="boss-form-grid">
          <label>随机种子 seed<input required type="number" min={0} step={1} value={values.seed} onChange={event=>edit("seed",event.target.value)}/></label>
          <label>数据规模<select required value={values.scale} onChange={event=>edit("scale",event.target.value)}><option value="">请选择规模</option>{api.data?.scales.map(row=><option key={row.id} value={row.id}>{row.label}</option>)}</select></label>
          <label>开始期间<input required type="month" value={values.period_start} onChange={event=>edit("period_start",event.target.value)}/></label><label>结束期间<input required type="month" value={values.period_end} min={values.period_start} onChange={event=>edit("period_end",event.target.value)}/></label>
          <label>生成器版本<select required value={values.generator_version} onChange={event=>edit("generator_version",event.target.value)}><option value="">请选择</option>{api.data?.generator_versions.map(version=><option key={version}>{version}</option>)}</select></label>
          <label>关系配置版本<select required value={values.relationship_version} onChange={event=>edit("relationship_version",event.target.value)}><option value="">请选择</option>{api.data?.relationship_versions.map(version=><option key={version}>{version}</option>)}</select></label>
        </div><div className="boss-actions"><button className="boss-btn boss-btn-primary" type="submit"><Database size={16}/>生成模拟数据</button><button className="boss-btn" type="button" onClick={()=>{setValues(EMPTY_GENERATOR);onDirtyChange(false);setError("");}}>取消未提交条件</button></div></fieldset></form>
        <div className="boss-v7-filter-bar"><label>数据集版本<select value={currentId||""} disabled={disabled} onChange={event=>{setSelected(event.target.value);setExpanded(false);}}><option value="">选择已生成数据集</option>{api.data?.datasets.map(row=><option key={row.id} value={row.id}>{row.id} · v{row.version}</option>)}</select></label><button className="boss-btn" disabled={disabled||current?.state!=="VALIDATED"||impact?.state!=="CURRENT"||!api.data?.transition_available} onClick={()=>prepare("load")}>载入获准数据集</button></div>
        {api.data?.transition_reason&&<p className="boss-status boss-status-warn">{api.data.transition_reason}</p>}
      </V7Panel>
      <V7Panel title="校验与生成记录" className="boss-dataset-checks" action={<button className="boss-btn" onClick={api.reload} disabled={disabled}><RefreshCw size={16}/>重新读取</button>}>
        <div className="boss-simulation-regions">{["实体关系","数值平衡","来源属性"].map(name=>{const check=current?.checks.find(row=>row.name===name);return <article key={name}><h3>{name}</h3><p>{check?.state??"尚无已读取检查结果"}</p><p>{check?.message??"选择数据集并查询实际校验记录。"}</p>{check&&<small>{current?.validated_at}</small>}</article>;})}<article><h3>生成记录</h3><p>{current?`${current.id} · v${current.version}`:"尚未选择生成记录"}</p><p>{current?.created_at??"生成时间未知"}</p><p>{current?.state??"尚未读取"}</p></article></div>
        <div className="boss-v7-table-scroll"><table className="boss-v7-table"><thead><tr><th>组件</th><th>请求或对象</th><th>执行时间</th><th>结果状态</th><th>详情</th></tr></thead><tbody>{rows.slice((currentPage-1)*10,currentPage*10).map(row=><tr key={row.key}><td>{row.component}</td><td>{row.request}</td><td>{row.at}</td><td>{row.state}</td><td><button className="boss-btn" onClick={()=>{if(row.dataset){setSelected(row.dataset.id);setExpanded(true);}else setRecordDetail(row.transition);}}>查看详情</button></td></tr>)}</tbody></table></div>{!rows.length&&<V7Empty title="尚无已读取的生成或空间切换记录"/>}<V7Pagination page={currentPage} total={rows.length} pageSize={10} onChange={setPage}/>
        {current&&<><div className="boss-actions"><button className="boss-btn" disabled={disabled} onClick={()=>void api.execute("validate",{dataset_id:current.id,expected_dataset_version:current.version})}><ShieldCheck size={16}/>运行关系检查</button><button className="boss-btn" aria-expanded={expanded} onClick={()=>setExpanded(value=>!value)}>{expanded?"关闭生成明细":"查看生成明细"}</button></div>{expanded&&<div className="boss-dataset-details">{current.checks.map(row=><div className="boss-workspace-item" key={row.name}><strong>{row.name} · {row.state}</strong><p>{row.message}</p></div>)}<div className="boss-form-grid">{Object.entries(current.counts).map(([name,count])=><V7Fact key={name} label={name}>{count}</V7Fact>)}</div><V7Fact label="seed">{current.seed}</V7Fact><V7Fact label="业务期间">{current.period_start} — {current.period_end}</V7Fact><V7Fact label="生成器 / 关系配置">{current.generator_version} / {current.relationship_version}</V7Fact><V7Fact label="资料摘要">{current.facts_sha256}</V7Fact><V7Fact label="关系检查时间">{current.validated_at}</V7Fact><DatasetRecords key={current.id} dataset={current}/></div>}</>}
      </V7Panel>
      <V7Panel title="重置影响确认" className="boss-dataset-reset" description="旧执行空间保留只读历史，当前运行采用新的独立空间。">
        <div className="boss-form-grid"><V7Fact label="受影响会话">{impact?.sessions??"待查询"}</V7Fact><V7Fact label="个人记忆">{impact?.memories??"待查询"}</V7Fact><V7Fact label="任务与计划">{impact?`${impact.tasks} / ${impact.plans}`:"待查询"}</V7Fact><V7Fact label="发件箱与在途运行">{impact?`${impact.outbox} / ${impact.active_runs}`:"待查询"}</V7Fact></div>
        {impact&&<><V7Fact label="技术调度配置 / 模型验证任务">{impact.schedule_configurations} / {impact.model_validation_jobs}</V7Fact><V7Fact label="影响核查时间">{impact.checked_at}</V7Fact>{impact.state==="STALE"&&<p className="boss-status boss-status-warn">资料或会话已经变化，请重新核查重置影响。</p>}</>}
        <p>新空间保留模型连接、运行配置、访问与工具配置及技术Prompt。指标采用记录、会话、本人资料、任务、计划和发件箱保留原归属；新空间的调度保持暂停。</p>
        {!loaded&&<p className="boss-status">当前空间尚未载入生成数据集，可选择已校验数据集并载入。</p>}
        <div className="boss-actions"><button className="boss-btn" disabled={disabled||!api.data?.inspection_available} onClick={()=>void api.execute("inspect-reset",{expected_namespace:api.data?.current.namespace})}>查看重置影响</button><button className="boss-btn" disabled={disabled||impact?.state!=="CURRENT"||loaded?.state!=="VALIDATED"||!api.data?.transition_available} onClick={()=>prepare("reset")}>重置模拟空间</button></div>
      </V7Panel>
    </div><aside className="boss-column">
      <V7Panel title="当前模拟空间"><V7Fact label="execution_namespace">{api.data?.current.namespace??"尚未读取"}</V7Fact><V7Fact label="业务时钟">{api.data?.current.business_clock??"尚未读取"}</V7Fact><V7Fact label="已载入版本">{api.data?.current.version??"尚未读取"}</V7Fact><V7Fact label="当前数据集">{api.data?.current.dataset_id??"尚未读取"}</V7Fact><V7Fact label="历史空间保留">{api.data?`${api.data.history.length} 项只读空间`:"尚未读取"}</V7Fact><V7Fact label="重置影响范围">{impact?.state??"尚未查询"}</V7Fact><div className="boss-actions"><button className="boss-btn" onClick={()=>onNavigate("F25")}>模拟中心</button><button className="boss-btn" onClick={()=>onNavigate("A15")}>运行记录</button></div></V7Panel>
      <V7Panel title="状态与核查"><V7Fact label="当前数据状态">{current?.state??"数据待生成"}</V7Fact><V7Fact label="已载入版本">{api.data?.current.version??"尚未读取"}</V7Fact><V7Fact label="检查时间">{api.data?.read_at??"尚未读取"}</V7Fact><V7Fact label="本人决定隔离">{current?.checks.find(row=>row.name==="本人决定隔离")?.state??"尚未取得检查记录"}</V7Fact><V7Fact label="切换能力">{api.data?api.data.transition_available?"当前服务已提供":"当前服务尚未提供":"尚未读取"}</V7Fact></V7Panel>
        <V7Panel title="历史执行空间" className="boss-dataset-history">{api.data?.history.length?api.data.history.map(row=><article className="boss-workspace-item" key={row.namespace}><strong>{row.namespace}</strong><p>{row.dataset_id} · v{row.version}</p><small>{row.state} · {row.created_at??"创建时间尚无记录"}</small><div className="boss-actions"><button className="boss-btn" disabled={!row.history_available} onClick={()=>setHistoryNamespace(row.namespace)}>查看只读历史</button></div>{!row.history_available&&<p>此空间尚无原生会话归档记录。</p>}</article>):<V7Empty title="尚无历史空间记录"/>}</V7Panel>
    </aside></div>
    <footer className="boss-maintainer-actions"><span>SIMULATED · 当前空间操作</span>{controls}</footer>
    <Dialog.Root open={recordDetail!==null} onOpenChange={open=>{if(!open)setRecordDetail(null);}}><Dialog.Portal><Dialog.Overlay className="boss-v7-dialog-overlay"/><Dialog.Content className="boss-v7-dialog"><Dialog.Title>执行空间切换记录</Dialog.Title><Dialog.Description>实际请求、服务采用与错误信息</Dialog.Description>{recordDetail&&<><V7Fact label="原请求">{recordDetail.request_id}</V7Fact><V7Fact label="动作与状态">{recordDetail.action} · {recordDetail.state}</V7Fact><V7Fact label="原执行空间">{recordDetail.previous_namespace}</V7Fact><V7Fact label="目标空间">{recordDetail.namespace}</V7Fact><V7Fact label="数据集与版本">{recordDetail.dataset_id} · v{recordDetail.dataset_version}</V7Fact><V7Fact label="请求时间">{recordDetail.requested_at}</V7Fact><V7Fact label="激活时间">{recordDetail.activated_at??"尚未激活"}</V7Fact><V7Fact label="服务采用时间">{recordDetail.runtime_adopted_at??"尚未采用"}</V7Fact><V7Fact label="错误">{recordDetail.error??"记录没有错误"}</V7Fact></>}<div className="boss-actions"><Dialog.Close asChild><button className="boss-btn">关闭详情</button></Dialog.Close></div></Dialog.Content></Dialog.Portal></Dialog.Root>
    <Dialog.Root open={historyNamespace!==null&&!!api.data?.history.some(row=>row.namespace===historyNamespace)} onOpenChange={open=>{if(!open)setHistoryNamespace(null);}}><Dialog.Portal><Dialog.Overlay className="boss-v7-dialog-overlay"/><Dialog.Content className="boss-v7-dialog"><Dialog.Title>历史执行空间</Dialog.Title><Dialog.Description>{historyNamespace} · 资料元信息与实际运行记录</Dialog.Description>{historyNamespace&&<DatasetHistory key={historyNamespace} namespace={historyNamespace}/>}<div className="boss-actions"><Dialog.Close asChild><button className="boss-btn">关闭</button></Dialog.Close></div></Dialog.Content></Dialog.Portal></Dialog.Root>
    <Dialog.Root open={confirm!==null} onOpenChange={open=>{if(!open)setConfirm(null);}}><Dialog.Portal><Dialog.Overlay className="boss-v7-dialog-overlay"/><Dialog.Content className="boss-v7-dialog"><Dialog.Title>{confirm?.action==="reset"?"重置模拟执行空间":"载入获准数据集"}</Dialog.Title><Dialog.Description>采用数据集 {confirm?.datasetId} · v{confirm?.datasetVersion}。当前空间 {confirm?.namespace} 将保留历史归属，旧请求不能写入新空间。服务会停止当前运行并重新启动，需要重新登录后查询原请求。</Dialog.Description><V7Fact label="影响版本">{confirm?.impactVersion}</V7Fact>{!confirmationCurrent&&<p role="alert" className="boss-status boss-status-warn">当前资料、执行空间或影响范围已变化。请取消本次确认并重新查询。</p>}<label className="boss-confirm-check"><input type="checkbox" checked={checked} disabled={!confirmationCurrent||disabled} onChange={event=>setChecked(event.target.checked)}/>已核查数据集版本、影响范围与在途运行</label><div className="boss-actions"><Dialog.Close asChild><button className="boss-btn">取消</button></Dialog.Close><button className="boss-btn boss-btn-primary" disabled={!checked||disabled||!confirmationCurrent} onClick={execute}>确认操作</button></div></Dialog.Content></Dialog.Portal></Dialog.Root>
  </div>;
}
