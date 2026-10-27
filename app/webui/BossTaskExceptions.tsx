import {useEffect,useRef,useState} from "react";
import * as Dialog from "@radix-ui/react-dialog";
import {useClient} from "@/providers/ClientProvider";
import {V7Empty,V7Fact,V7Panel,V7ReadState} from "./BossV7UI";
import {useOwnerWorkspace} from "./useTechnicalWorkspace";
import {RunArtifacts,runTime,type RunArtifact,type RunProjection} from "./BossRunDetails";

type Retry={allowed:boolean;reason:string;expected_task_version:string|null;authorization_id:string|null};
type Issue={id:string;task_id:string|null;run_id:string|null;request_id:string|null;action:string|null;state:string;title:string;reason:string;
  executed:{id:string;state:string;description:string}[];remaining:{id:string;state:string;description:string}[];missing:string[];source_ids:string[];
  current_business_state:string;can_cancel:boolean;created_at:string;
  task_version?:string;action_coverage?:"COMPLETE"|"PARTIAL";retry?:Retry;
  timeline?:{id:string;at:string;title:string;description:string;state:string}[];artifacts?:RunArtifact[]};
type Projection={projection:"task-exceptions";source_type:"RUNTIME_RECORD";namespace?:string;issues:Issue[];read_at:string};
type Props={taskId:string;onNavigate:(page:string)=>void;onOpenTask:(id:string)=>void;onViewSource:(id:string)=>void;refreshVersion?:number};
type View={query:string;state:string;runId:string;selected:string};
type RetryBasis={issueId:string;runId:string;state:string;namespace:string;taskVersion:string|null;authorizationId:string|null};

export function BossTaskExceptions(props:Props){
  const {token}=useClient(),identity=useRef({token,sequence:0});
  if(identity.current.token!==token)identity.current={token,sequence:identity.current.sequence+1};
  return <TaskExceptions key={props.taskId+":"+identity.current.sequence} {...props}/>;
}
function TaskExceptions({taskId,onNavigate,onOpenTask,onViewSource,refreshVersion}:Props){
  const {getToken}=useClient(),api=useOwnerWorkspace<RunProjection>("runs");
  const [data,setData]=useState<Projection|null>(null),[loading,setLoading]=useState(true),[error,setError]=useState(""),[revision,setRevision]=useState(0);
  const [view,setView]=useState<View>(()=>window.history.state?.bossIssueView??{query:"",state:"",runId:new URL(window.location.href).searchParams.get("bossRun")??"",selected:new URL(window.location.href).searchParams.get("bossIssue")??""});
  const [form,setForm]=useState({query:view.query,state:view.state,runId:view.runId});
  const [retry,setRetry]=useState<RetryBasis|null>(null),[reason,setReason]=useState(""),[checked,setChecked]=useState(false),[artifactsOpen,setArtifactsOpen]=useState(false);
  const previousRefresh=useRef(refreshVersion);
  useEffect(()=>{if(previousRefresh.current!==refreshVersion){previousRefresh.current=refreshVersion;api.reload();}},[refreshVersion,api.reload]);
  useEffect(()=>{window.history.replaceState({...window.history.state,bossIssueView:view},"");},[view]);
  useEffect(()=>{
    const abort=new AbortController();setData(null);setError("");setLoading(true);
    const parameters=new URLSearchParams();if(taskId)parameters.set("task_id",taskId);
    void fetch("/api/boss/ui/task-exceptions?"+parameters,{headers:{Authorization:"Bearer "+getToken()},signal:abort.signal,cache:"no-store"}).then(async response=>{
      if(response.status===401)window.dispatchEvent(new Event("boss-auth-expired"));
      if(!response.ok)throw new Error("任务异常读取失败（HTTP "+response.status+"）");
      const next=await response.json() as Projection;
      if(next.projection!=="task-exceptions"||next.source_type!=="RUNTIME_RECORD")throw new Error("任务异常资料范围无效");
      if(!abort.signal.aborted){setData(next);setLoading(false);}
    }).catch(failure=>{if(!abort.signal.aborted){setError(failure.message);setLoading(false);}});
    return()=>abort.abort();
  },[getToken,taskId,revision,refreshVersion]);
  const current=!loading&&!error?data:null;
  const issues=(current?.issues??[]).filter(row=>(!view.query||[row.id,row.title,row.task_id].some(value=>value?.includes(view.query)))&&(!view.state||row.state===view.state)&&(!view.runId||row.run_id===view.runId));
  const issue=issues.find(row=>row.id===view.selected);
  const runs=!api.loading&&!api.error?api.data:null;
  const run=issue&&runs?.runs.find(row=>row.id===issue.run_id&&row.task_id===issue.task_id&&row.state===issue.state);
  const busy=api.busy||!!api.pending;
  const unknown=Boolean(issue&&["RECONCILING","RESULT_UNKNOWN","CANCEL_REQUESTED"].includes(issue.state));
  const canRetry=Boolean(issue?.retry?.allowed&&current?.namespace&&current.namespace===runs?.namespace&&run&&["FAILED","TIMED_OUT","CANCELED"].includes(run.state)&&!unknown&&!busy);
  const retryCurrent=Boolean(retry&&canRetry&&issue?.id===retry.issueId&&issue.run_id===retry.runId&&issue.state===retry.state&&current?.namespace===retry.namespace&&issue.retry?.expected_task_version===retry.taskVersion&&issue.retry?.authorization_id===retry.authorizationId);
  function refresh(){setRevision(value=>value+1);api.reload();}
  function openRun(){if(!issue?.run_id)return;const url=new URL(window.location.href);url.searchParams.set("bossRun",issue.run_id);window.history.replaceState(window.history.state,"",url);onNavigate("F24");}
  function recover(){if(!issue)return;if(!issue.request_id||!issue.action){refresh();return;}const url=new URL(window.location.href);url.searchParams.set("bossRecoveryRequest",issue.request_id);url.searchParams.set("bossRecoveryAction",issue.action);window.history.replaceState(window.history.state,"",url);onNavigate("D03");}
  return <div className="boss-run-view"><V7ReadState loading={loading} error={error} onReload={refresh}/><V7ReadState loading={api.loading} error={api.error} onReload={api.reload}/>
    {api.pending&&<p className="boss-status boss-status-warn">原运行操作结果需要核查，当前不能发起新尝试。<button className="boss-btn" disabled={api.busy} onClick={()=>{void api.reconcile().then(()=>setRevision(value=>value+1));}}>核查原请求</button></p>}
    {api.receipt&&<p role="status">原操作 {api.receipt.request_id} 已记录，当前运行与正式任务状态分别重读。</p>}
    <details className="boss-panel boss-v7-filter-bar"><summary>切换异常记录</summary><form onSubmit={event=>{event.preventDefault();setView({...form,query:form.query.trim(),selected:""});}}><label>当前问题<input value={form.query} onChange={event=>setForm(value=>({...value,query:event.target.value}))}/></label><label>任务状态<select value={form.state} onChange={event=>setForm(value=>({...value,state:event.target.value}))}><option value="">全部状态</option>{Array.from(new Set(current?.issues.map(row=>row.state)??[])).map(state=><option key={state} value={state}>{state}</option>)}</select></label><label>获准运行<select value={form.runId} onChange={event=>setForm(value=>({...value,runId:event.target.value}))}><option value="">全部获准运行</option>{Array.from(new Set((current?.issues??[]).flatMap(row=>row.run_id?[row.run_id]:[]))).map(id=><option key={id} value={id}>{id}</option>)}</select></label><button className="boss-btn boss-btn-primary" disabled={!current}>查询异常</button></form></details>
    <div className="boss-run-goal"><span>当前异常</span><strong>{issue?issue.title:"请选择需要处理的问题"}</strong>{issue&&<small>{issue.id} · {runTime(issue.created_at)}</small>}</div>
    <div className="boss-run-columns"><div className="boss-column"><V7Panel title="当前对象与有效条件">
      <label className="boss-field">异常记录<select value={issue?.id??""} onChange={event=>{setView(value=>({...value,selected:event.target.value}));setRetry(null);setArtifactsOpen(false);}}><option value="">请选择本次问题</option>{issues.map(row=><option key={row.id} value={row.id}>{row.title} · {row.id}</option>)}</select></label>
      <div className="boss-form-grid boss-run-fields"><V7Fact label="实际原因">{issue?.reason??"尚未选择异常记录"}</V7Fact><V7Fact label="当前任务">{issue?issue.task_id??"没有关联任务":"尚未读取"}</V7Fact><V7Fact label="异常处理状态">{issue?.state??"尚未读取"}</V7Fact><V7Fact label="缺少条件">{issue?issue.missing.join("、")||"没有已记录的缺少条件":"尚未读取"}</V7Fact></div>
      {!issue&&<V7Empty title={loading?"正在读取异常记录":issues.length?"请选择需要处理的问题":current?"当前查询范围没有异常记录":"异常记录尚未读取"}/>}
      {unknown&&<p className="boss-status boss-status-warn" role="status">正在核查执行结果。请查询原请求，当前不能发起同一意图的新尝试。</p>}
      <h3>授权、变更与执行范围</h3><div className="boss-v7-equal-columns">{[{title:"已经执行",items:issue?.executed},{title:"尚未执行",items:issue?.remaining}].map(group=><section key={group.title}><h4>{group.title}</h4>{group.items?.length?group.items.map(row=><article className="boss-workspace-item" key={row.id}><strong>{row.description}</strong><p>{row.id} · {row.state}</p></article>):<p>{issue?"当前服务未返回该范围的动作记录":"选择问题后查看当前动作"}</p>}</section>)}</div><p className="boss-v7-note">动作覆盖：{issue?.action_coverage??"尚未提供完整性信息"}。已经执行的业务结果继续保留，取消仅处理尚未执行步骤。</p>
    </V7Panel><V7Panel title="事件与反馈时间线">{issue?.timeline?.length?<ol className="boss-run-timeline">{issue.timeline.map(item=><li key={item.id}><time>{runTime(item.at)}</time><strong>{item.title} · {item.state}</strong><p>{item.description}</p></li>)}</ol>:<V7Empty title={issue?.timeline?"当前问题没有已记录的事件":"尚未取得当前问题的完整事件时间线"}/>}<div className="boss-actions"><button className="boss-btn" disabled={!issue} onClick={recover}>查询原请求结果</button><button className="boss-btn" disabled={!issue} onClick={()=>setArtifactsOpen(true)}>查看已保存结果</button></div></V7Panel></div>
    <aside className="boss-column"><V7Panel title="来源与依据"><V7Fact label="当前任务">{issue?issue.task_id??"没有关联任务":"尚未选择"}</V7Fact><V7Fact label="任务版本">{issue?.task_version??"尚未提供"}</V7Fact><V7Fact label="获准运行">{issue?.run_id??"尚未取得"}</V7Fact><V7Fact label="原请求">{issue?.request_id??"没有关联请求"}</V7Fact><V7Fact label="记录时间">{runTime(issue?.created_at)}</V7Fact><div className="boss-actions">{issue?.source_ids.map(id=><button className="boss-btn" key={id} onClick={()=>onViewSource(id)}>核查 {id}</button>)}<button className="boss-btn" disabled={!issue?.run_id} onClick={openRun}>查看本次运行</button></div></V7Panel>
      <V7Panel title="状态与核查"><V7Fact label="正式业务状态">{issue?.current_business_state??"尚未读取"}</V7Fact><V7Fact label="当前运行核查">{run?run.state:"尚未匹配当前运行"}</V7Fact><V7Fact label="重复发送">{unknown||busy?"结果未确定，禁止重复执行":"新尝试需要重新核查授权"}</V7Fact><V7Fact label="读取时间">{runTime(current?.read_at)}</V7Fact><h3>缺少对象与材料</h3>
        {issue?.missing.length?<ul>{issue.missing.map((value,index)=><li key={index}>{value}</li>)}</ul>:<p>{issue?"当前记录未列出缺少材料":"尚未选择异常记录"}</p>}
        <p className="boss-v7-note">{issue?.retry?.reason??"当前服务尚未提供关联原意图的新尝试授权与版本。"}</p>
      </V7Panel>
    </aside></div>
    <footer className="boss-v7-footer"><span>{issue?issue.title:"请选择需要处理的问题"}</span><div className="boss-actions"><button className="boss-btn boss-btn-primary" disabled={!issue?.task_id} onClick={()=>{if(issue?.task_id)onOpenTask(issue.task_id);}}>{issue?.missing.length?"补充"+issue.missing[0]:"补充信息"}</button><button className="boss-btn" disabled={loading||api.loading} onClick={refresh}>刷新状态</button><button className="boss-btn" disabled={!canRetry} onClick={()=>{if(issue?.retry&&current?.namespace&&issue.run_id){setReason("");setChecked(false);setRetry({issueId:issue.id,runId:issue.run_id,state:issue.state,namespace:current.namespace,taskVersion:issue.retry.expected_task_version,authorizationId:issue.retry.authorization_id});}}}>按当前内容重新尝试</button><button className="boss-btn boss-btn-danger" disabled={!issue?.can_cancel||!run?.can_cancel||busy} onClick={openRun}>取消未执行步骤</button></div></footer>
    <Dialog.Root open={retry!==null} onOpenChange={open=>{if(!api.busy&&!open)setRetry(null);}}><Dialog.Portal><Dialog.Overlay className="boss-v7-dialog-overlay"/><Dialog.Content className="boss-v7-dialog"><Dialog.Title>核查获准新尝试</Dialog.Title><Dialog.Description>新尝试关联原运行与原意图，保留已有业务结果。服务需要重新检查当前任务版本、授权及已执行动作。</Dialog.Description><V7Fact label="原运行">{retry?.runId}</V7Fact><V7Fact label="原状态">{retry?.state}</V7Fact><V7Fact label="当前任务版本">{retry?.taskVersion??"没有关联任务版本"}</V7Fact><label className="boss-field">本次继续原因<textarea rows={3} value={reason} onChange={event=>setReason(event.target.value)} disabled={busy}/></label><label className="boss-confirm-check"><input type="checkbox" checked={checked} onChange={event=>setChecked(event.target.checked)} disabled={busy}/>本人确认按当前授权继续原意图</label>{!retryCurrent&&<p role="alert">当前条件需要重新核查，原请求尚未确定时不能发起新尝试。</p>}{api.error&&<p role="alert" className="boss-status boss-status-error">{api.error}</p>}<div className="boss-actions"><Dialog.Close asChild><button className="boss-btn" disabled={api.busy}>取消</button></Dialog.Close><button className="boss-btn boss-btn-primary" disabled={!retryCurrent||!reason.trim()||!checked||busy} onClick={()=>{if(!retry||!retryCurrent)return;void api.execute("retry",{run_id:retry.runId,expected_state:retry.state,execution_namespace:retry.namespace,expected_task_version:retry.taskVersion,authorization_id:retry.authorizationId,reason:reason.trim(),confirmation:true}).then(recorded=>{if(recorded){setRetry(null);setRevision(value=>value+1);}});}}>确认新尝试</button></div></Dialog.Content></Dialog.Portal></Dialog.Root>
    <Dialog.Root open={artifactsOpen} onOpenChange={setArtifactsOpen}><Dialog.Portal><Dialog.Overlay className="boss-v7-dialog-overlay"/><Dialog.Content className="boss-v7-dialog"><Dialog.Title>当前问题的已有产物</Dialog.Title><Dialog.Description>{issue?issue.title:"当前问题需要重新读取"}</Dialog.Description>{issue&&<RunArtifacts artifacts={issue.artifacts??run?.artifacts} onOpenTask={onOpenTask} onViewSource={onViewSource}/>}<Dialog.Close asChild><button className="boss-btn">返回异常详情</button></Dialog.Close></Dialog.Content></Dialog.Portal></Dialog.Root>
  </div>;
}
