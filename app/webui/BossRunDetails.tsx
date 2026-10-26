import {useEffect,useRef,useState} from "react";
import * as Dialog from "@radix-ui/react-dialog";
import {useClient} from "@/providers/ClientProvider";
import {V7Empty,V7Fact,V7Panel,V7Pagination,V7ReadState} from "./BossV7UI";
import {useOwnerWorkspace} from "./useTechnicalWorkspace";

type RunAction={id:string;description:string;state:string};
export type RunArtifact={id:string;title:string;source_id:string|null;task_id:string|null;state:string};
type Run={id:string;task_id:string|null;task_version:string|null;goal:string;state:string;started_at:string;ended_at:string|null;provider:string;model_id:string;
  waiting_inputs:string[];termination_reason:string|null;can_cancel:boolean;request_id:string|null;action:string|null;
  current_business_state?:string;executed_actions?:RunAction[];remaining_actions?:RunAction[];action_coverage?:"COMPLETE"|"PARTIAL";
  steps:{id:string;title:string;state:string;tool_name:string|null;input:string|null;output:string|null;error:string|null;started_at:string|null;ended_at:string|null}[];
  usage:{id:string;resource:string;quantity:string|null;unit:string;cache:string|null;pricing_date:string|null;cost:string|null;currency:string|null;state:string}[];
  artifacts:RunArtifact[];source_ids:string[]};
export type RunProjection={projection:"runs";private_body_available_here:true;namespace:string;runs:Run[];read_at:string};
type Props={taskId:string;onNavigate:(page:string)=>void;onOpenTask:(id:string)=>void;onViewSource:(id:string)=>void;refreshVersion?:number};
type View={task:string;runId:string;date:string;namespace:string;usagePage:number};
const DATE=new Intl.DateTimeFormat("sv-SE",{timeZone:"Asia/Shanghai",year:"numeric",month:"2-digit",day:"2-digit"});
const TIME=new Intl.DateTimeFormat("zh-CN",{timeZone:"Asia/Shanghai",dateStyle:"short",timeStyle:"medium"});
export function runTime(value:string|null|undefined){return value?TIME.format(new Date(value))+" · Asia/Shanghai":"尚未提供";}
export function RunArtifacts({artifacts,onOpenTask,onViewSource}:{artifacts:RunArtifact[]|undefined;onOpenTask:(id:string)=>void;onViewSource:(id:string)=>void}){
  return artifacts?.length?<div>{artifacts.map(item=><article className="boss-workspace-item" key={item.id}><strong>{item.title}</strong><p>{item.state}</p><div className="boss-actions">{item.source_id&&<button className="boss-btn" onClick={()=>onViewSource(item.source_id!)}>打开产物原文</button>}{item.task_id&&<button className="boss-btn" onClick={()=>onOpenTask(item.task_id!)}>打开关联事项</button>}</div>{!item.source_id&&!item.task_id&&<p className="boss-v7-note">已记录产物标识，当前服务尚未提供可访问入口。</p>}</article>)}</div>:<V7Empty title={artifacts?"当前运行没有已保存产物":"尚未取得已有产物清单"}/>;
}
export function BossRunDetails(props:Props){
  const {token}=useClient(),identity=useRef({token,sequence:0});
  if(identity.current.token!==token)identity.current={token,sequence:identity.current.sequence+1};
  return <RunDetails key={props.taskId+":"+identity.current.sequence} {...props}/>;
}
function RunDetails({taskId,onNavigate,onOpenTask,onViewSource,refreshVersion}:Props){
  const api=useOwnerWorkspace<RunProjection>("runs");
  const [view,setView]=useState<View>(()=>window.history.state?.bossRunView??{task:taskId,runId:new URL(window.location.href).searchParams.get("bossRun")??"",date:"",namespace:"",usagePage:1});
  const [form,setForm]=useState({task:view.task,runId:view.runId,date:view.date});
  const [cancel,setCancel]=useState<{id:string;state:string;namespace:string}|null>(null),[checked,setChecked]=useState(false),[artifactsOpen,setArtifactsOpen]=useState(false);
  const previousRefresh=useRef(refreshVersion);
  useEffect(()=>{if(previousRefresh.current!==refreshVersion){previousRefresh.current=refreshVersion;api.reload();}},[refreshVersion,api.reload]);
  useEffect(()=>{window.history.replaceState({...window.history.state,bossRunView:view},"");},[view]);
  const data=!api.loading&&!api.error?api.data:null;
  useEffect(()=>{if(data&&!view.namespace&&view.runId&&data.runs.some(row=>row.id===view.runId))setView(current=>({...current,namespace:data.namespace}));},[data,view.namespace,view.runId]);
  function matches(row:Run,filter:{task:string;date:string}){return (!filter.task||[row.task_id,row.goal].some(value=>value?.includes(filter.task)))&&(!filter.date||DATE.format(new Date(row.started_at))===filter.date);}
  const options=(data?.runs??[]).filter(row=>matches(row,form));
  const run=data&&view.namespace===data.namespace?data.runs.find(row=>row.id===view.runId&&matches(row,view)):undefined;
  const usagePage=Math.min(view.usagePage,Math.max(1,Math.ceil((run?.usage.length??0)/10)));
  const busy=api.busy||!!api.pending,disabled=busy||!data;
  const cancelRun=cancel&&data?.namespace===cancel.namespace?data.runs.find(row=>row.id===cancel.id):undefined;
  const cancelCurrent=Boolean(cancelRun&&cancelRun.state===cancel?.state&&cancelRun.can_cancel);
  function recover(){
    if(!run)return;
    if(!run.request_id||!run.action){api.reload();return;}
    const url=new URL(window.location.href);url.searchParams.set("bossRecoveryRequest",run.request_id);url.searchParams.set("bossRecoveryAction",run.action);window.history.replaceState(window.history.state,"",url);onNavigate("D03");
  }
  return <div className="boss-run-view"><V7ReadState loading={api.loading} error={api.error} onReload={api.reload}/>
    {api.pending&&<p className="boss-status boss-status-warn">原取消操作等待核查。<button className="boss-btn" disabled={api.busy} onClick={()=>void api.reconcile()}>核查原请求</button></p>}
    {api.receipt&&<p role="status">取消请求 {api.receipt.request_id} 已记录，实际终止状态以当前运行记录为准。</p>}
    <form className="boss-panel boss-v7-filter-bar" onSubmit={event=>{event.preventDefault();setView({...form,task:form.task.trim(),namespace:data?.namespace??"",usagePage:1});setCancel(null);setArtifactsOpen(false);}}>
      <label>当前任务<input value={form.task} onChange={event=>setForm(current=>({...current,task:event.target.value,runId:""}))}/></label>
      <label>run_id<select value={form.runId} onChange={event=>setForm(current=>({...current,runId:event.target.value}))}><option value="">请选择实际运行</option>{options.map(row=><option key={row.id} value={row.id}>{row.id} · {row.state}</option>)}</select></label>
      <label>开始日期（Asia/Shanghai）<input type="date" value={form.date} onChange={event=>setForm(current=>({...current,date:event.target.value,runId:""}))}/></label><button className="boss-btn boss-btn-primary" disabled={!data}>查询 / 应用</button>
    </form>
    <div className="boss-run-columns"><div className="boss-column">
      <V7Panel title="执行概览"><div className="boss-form-grid boss-run-fields"><label>任务目标<input readOnly value={run?.goal??"尚未选择运行"}/></label><label>运行状态<input readOnly value={run?.state??"尚未读取"}/></label><label>当前任务版本<input readOnly value={run?run.task_version??"未关联任务版本":"尚未读取"}/></label><label>待输入条件<textarea readOnly rows={2} value={run?run.waiting_inputs.join("、")||"没有已记录条件":"尚未读取"}/></label></div>
        <h3>运行步骤与工具结果</h3>{run?.steps.length?run.steps.map(step=><details className="boss-workspace-item" key={step.id}><summary>{step.title} · {step.state}</summary><V7Fact label="工具">{step.tool_name??"模型处理"}</V7Fact><V7Fact label="开始时间">{runTime(step.started_at)}</V7Fact><V7Fact label="结束时间">{runTime(step.ended_at)}</V7Fact><h4>请求</h4><pre className="boss-v7-code">{step.input??"未提供可见请求内容"}</pre><h4>返回</h4><pre className="boss-v7-code">{step.output??"没有已记录返回"}</pre>{step.error&&<p role="alert" className="boss-status boss-status-error">{step.error}</p>}</details>):<V7Empty title={run?"当前运行尚无可见步骤":api.loading?"正在读取运行记录":data?.runs.length?"请选择一次实际运行":"尚无可读取的运行记录"}/>}
        {run&&<details><summary>已执行与未执行动作</summary><div className="boss-v7-equal-columns">{([{title:"已经执行",items:run.executed_actions},{title:"尚未执行",items:run.remaining_actions}]).map(group=><section key={group.title}><h4>{group.title}</h4>{group.items?.length?group.items.map(item=><article key={item.id} className="boss-workspace-item"><strong>{item.description}</strong><p>{item.id} · {item.state}</p></article>):<p>{group.items?"当前清单没有记录":"服务尚未提供完整动作清单"}</p>}</section>)}</div><p className="boss-v7-note">动作覆盖：{run.action_coverage??"尚未提供"}。工具返回与业务动作结果分别核查。</p></details>}
      </V7Panel>
      <V7Panel title="用量与分项计费"><div className="boss-v7-table-scroll"><table className="boss-v7-table"><thead><tr><th>资源类型</th><th>用量</th><th>缓存</th><th>计价日期</th><th>费用</th><th>状态</th></tr></thead><tbody>{run?.usage.slice((usagePage-1)*10,usagePage*10).map(row=><tr key={row.id}><td>{row.resource}</td><td>{row.quantity??"未提供"} {row.unit}</td><td>{row.cache??"未提供"}</td><td>{row.pricing_date??"未提供"}</td><td>{row.cost===null?"无法核算":row.cost+" "+(row.currency??"币种未提供")}</td><td>{row.state}</td></tr>)}</tbody></table></div>{!run?.usage.length&&<V7Empty title={run?"尚无实际用量记录":"选择运行后查看用量"}/>}<p className="boss-v7-note">用量或计价来源缺少时，完整费用保持未知。</p>{run&&<V7Pagination page={usagePage} total={run.usage.length} pageSize={10} onChange={page=>setView(current=>({...current,usagePage:page}))}/>}</V7Panel>
    </div><aside className="boss-column"><V7Panel title="来源与依据"><V7Fact label="run_id">{run?.id??"尚未选择"}</V7Fact><V7Fact label="开始时间">{runTime(run?.started_at)}</V7Fact><V7Fact label="结束时间">{runTime(run?.ended_at)}</V7Fact><V7Fact label="运行记录">{run?run.provider+" / "+run.model_id:"尚未读取"}</V7Fact><V7Fact label="终止原因">{run?run.termination_reason??"没有已记录原因":"尚未读取"}</V7Fact><div className="boss-actions">{run?.source_ids.map(id=><button className="boss-btn" key={id} onClick={()=>onViewSource(id)}>打开 {id}</button>)}</div>{run&&!run.source_ids.length&&<p>当前记录没有引用资料。</p>}</V7Panel>
      <V7Panel title="状态与核查"><V7Fact label="执行步骤">{run?.steps.length??"尚未读取"}</V7Fact><V7Fact label="已执行动作">{run?.executed_actions?.length??"尚未提供完整清单"}</V7Fact><V7Fact label="未执行动作">{run?.remaining_actions?.length??"尚未提供完整清单"}</V7Fact><V7Fact label="正式任务状态">{run?.current_business_state??"尚未提供"}</V7Fact><V7Fact label="原取消请求">{run?.request_id??"没有已记录请求"}</V7Fact><V7Fact label="读取时间">{runTime(data?.read_at)}</V7Fact><p className="boss-v7-note">运行结束、取消请求已记录与本人确认任务完成分别核查。</p><button className="boss-btn" disabled={api.loading} onClick={api.reload}>重新查询运行</button></V7Panel>
    </aside></div>
    <footer className="boss-v7-footer"><span>{run?"当前运行："+run.id:"请选择当前获准运行"}</span><div className="boss-actions"><button className="boss-btn boss-btn-primary" disabled={!run?.task_id} title={!run?.task_id?"当前运行尚未关联可补充的任务":undefined} onClick={()=>{if(run?.task_id)onOpenTask(run.task_id);}}>补充输入</button><button className="boss-btn boss-btn-danger" disabled={disabled||!run?.can_cancel} onClick={()=>{if(run&&data){setChecked(false);setCancel({id:run.id,state:run.state,namespace:data.namespace});}}}>取消未执行步骤</button><button className="boss-btn" disabled={!run||api.loading} onClick={recover}>查询执行结果</button><button className="boss-btn" disabled={!run} onClick={()=>setArtifactsOpen(true)}>打开产物</button></div></footer>
    <Dialog.Root open={cancel!==null} onOpenChange={open=>{if(!open)setCancel(null);}}><Dialog.Portal><Dialog.Overlay className="boss-v7-dialog-overlay"/><Dialog.Content className="boss-v7-dialog"><Dialog.Title>取消尚未执行的步骤</Dialog.Title><Dialog.Description>运行 {cancel?.id}，核查时状态 {cancel?.state}。已经执行的动作与产物保留，取消结果通过原请求查询。</Dialog.Description>{!cancelCurrent&&<p role="alert">当前运行状态或执行空间需要重新核查，请返回读取后重新选择。</p>}<label className="boss-confirm-check"><input type="checkbox" checked={checked} onChange={event=>setChecked(event.target.checked)}/>本人确认取消当前运行的后续步骤</label><div className="boss-actions"><Dialog.Close asChild><button className="boss-btn">返回</button></Dialog.Close><button className="boss-btn boss-btn-danger" disabled={!checked||disabled||!cancelCurrent} onClick={()=>{if(!cancel||!cancelCurrent)return;void api.execute("cancel",{run_id:cancel.id,expected_state:cancel.state,confirmation:true});setCancel(null);}}>确认取消</button></div></Dialog.Content></Dialog.Portal></Dialog.Root>
    <Dialog.Root open={artifactsOpen} onOpenChange={setArtifactsOpen}><Dialog.Portal><Dialog.Overlay className="boss-v7-dialog-overlay"/><Dialog.Content className="boss-v7-dialog"><Dialog.Title>当前运行产物</Dialog.Title><Dialog.Description>{run?"原运行 "+run.id+" 中已保存的获准产物。":"当前运行需要重新读取。"}</Dialog.Description>{run&&<RunArtifacts artifacts={run.artifacts} onOpenTask={onOpenTask} onViewSource={onViewSource}/>}<Dialog.Close asChild><button className="boss-btn">返回运行详情</button></Dialog.Close></Dialog.Content></Dialog.Portal></Dialog.Root>
  </div>;
}
