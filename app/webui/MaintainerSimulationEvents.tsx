import {useEffect,useRef,useState,type ReactNode} from "react";
import * as Dialog from "@radix-ui/react-dialog";
import {V7Empty,V7Fact,V7Panel,V7Pagination,V7ReadState} from "./BossV7UI";
import {useTechnicalWorkspace} from "./useTechnicalWorkspace";

type Action="inject"|"reply"|"advance-clock";
type Versioned={id:string;title:string;version:string};
type Target=Versioned&{kind:string;author_ids:string[];source_ids:string[]};
type Source=Versioned&{as_of:string;state:string};
type Outcome={state:string;ids:string[];error:string|null};
type EventRecord={id:string;action:Action;event_type:string;namespace:string;request_id:string;created_at:string;target_id:string|null;
  source_id:string|null;source_version:string|null;saved:Outcome;tasks:Outcome;notifications:Outcome;simulation:Outcome;agent:Outcome;run_ids:string[]};
type Projection={projection:"simulation-events";private_body_available_here:false;source_type:"SIMULATED";namespace:string;dataset_id:string;dataset_version:string;
  business_clock:{at:string;version:string};event_types:{id:string;title:string;actions:Action[];target_kinds:string[]}[];
  targets:Target[];authors:Versioned[];sources:Source[];records:EventRecord[];allowed_actions:Action[];read_at:string};
type Draft={eventType:string;targetId:string;targetVersion:string;authorId:string;authorVersion:string;sourceId:string;sourceVersion:string;eventAt:string;content:string};
type Context={namespace:string;dataset_id:string;dataset_version:string};
type Confirmation={action:Action;payload:Record<string,unknown>;basis:string;preview:string[]};
const EMPTY:Draft={eventType:"",targetId:"",targetVersion:"",authorId:"",authorVersion:"",sourceId:"",sourceVersion:"",eventAt:"",content:""};
function context(value:Projection):Context{return {namespace:value.namespace,dataset_id:value.dataset_id,dataset_version:value.dataset_version};}
function timestamp(value:string){const at=value+":00+08:00";if(!value||!Number.isFinite(new Date(at).getTime()))throw new Error("请填写完整业务时间");return at;}

export function MaintainerSimulationEvents({onNavigate,onOpenRun,onDirtyChange,children}:{onNavigate:(page:string)=>void;onOpenRun:(id:string)=>void;onDirtyChange:(dirty:boolean)=>void;children:ReactNode}){
  const api=useTechnicalWorkspace<Projection>("simulation-events");
  const [draft,setDraft]=useState<Draft>(EMPTY),[draftContext,setDraftContext]=useState<Context|null>(null);
  const [clock,setClock]=useState(""),[clockBasis,setClockBasis]=useState<{context:Context;version:string}|null>(null);
  const [error,setError]=useState(""),[confirmation,setConfirmation]=useState<Confirmation|null>(null),[approved,setApproved]=useState(false);
  const [selected,setSelected]=useState(""),[page,setPage]=useState(1);
  const eventForm=useRef<HTMLFormElement>(null),clockForm=useRef<HTMLFormElement>(null),focusApplied=useRef(false);
  const data=api.data;
  if(data&&data.source_type!=="SIMULATED")throw new Error("当前事件资料来源不符合模拟维护范围");
  const definition=data?.event_types.find(row=>row.id===draft.eventType),target=data?.targets.find(row=>row.id===draft.targetId);
  const author=data?.authors.find(row=>row.id===draft.authorId),source=data?.sources.find(row=>row.id===draft.sourceId);
  const busy=api.loading||api.busy||!!api.pending;
  const contextCurrent=!!data&&!!draftContext&&JSON.stringify(draftContext)===JSON.stringify(context(data));
  const versionsCurrent=!!target&&target.version===draft.targetVersion&&!!author&&author.version===draft.authorVersion&&!!source&&source.version===draft.sourceVersion;
  const draftCurrent=contextCurrent&&versionsCurrent&&!!definition&&definition.target_kinds.includes(target!.kind)&&target!.author_ids.includes(author!.id)&&target!.source_ids.includes(source!.id)&&source!.state==="CURRENT";
  const clockCurrent=!!data&&!!clockBasis&&JSON.stringify(clockBasis.context)===JSON.stringify(context(data))&&clockBasis.version===data.business_clock.version;
  const record=data?.records.find(row=>row.id===selected&&row.namespace===data.namespace);
  const records=data?.records.filter(row=>row.namespace===data.namespace)??[];
  const currentPage=Math.min(page,Math.max(1,Math.ceil(records.length/10)));
  const dirty=draftContext!==null||clockBasis!==null;
  const basis=data?JSON.stringify({context:context(data),clock:data.business_clock,definition,target,author,source}):"";
  const confirmationCurrent=!!confirmation&&confirmation.basis===basis&&!!data?.allowed_actions.includes(confirmation.action);
  useEffect(()=>{onDirtyChange(dirty);},[dirty,onDirtyChange]);
  useEffect(()=>{if(!data||!api.receipt)return;const saved=data.records.find(row=>row.request_id===api.receipt!.request_id&&row.namespace===data.namespace);if(saved)setSelected(saved.id);},[data,api.receipt]);
  useEffect(()=>{if(focusApplied.current||!data)return;const section=new URLSearchParams(window.location.search).get("bossSimulationSection");if(!section||!["clock","event","feedback"].includes(section))return;const element=section==="clock"?clockForm.current:section==="feedback"?eventForm.current?.querySelector<HTMLTextAreaElement>("textarea"):eventForm.current;if(element){focusApplied.current=true;element.scrollIntoView({block:"start"});element.focus();}},[data]);
  function edit(values:Partial<Draft>){if(!data)return;setDraftContext(previous=>previous??context(data));setDraft(previous=>({...previous,...values}));setError("");}
  function discard(){setDraft(EMPTY);setDraftContext(null);setClock("");setClockBasis(null);setError("");setConfirmation(null);setApproved(false);}
  function propose(action:Action){
    if(!data||busy||!data.allowed_actions.includes(action))return;
    setError("");setApproved(false);
    if(action==="advance-clock"){
      if(!clockForm.current?.reportValidity())return;
      if(!clockCurrent){setError("当前时钟或执行空间已经变化，请取消编辑并重新读取。");return;}
      const at=timestamp(clock),difference=new Date(at).getTime()-new Date(data.business_clock.at).getTime();
      if(difference<0||difference>366*86400000){setError("业务时钟只能前进，单次最多366天。");return;}
      setConfirmation({action,basis,payload:{...context(data),expected_clock_version:clockBasis!.version,at},preview:["当前业务时间："+data.business_clock.at,"目标业务时间："+at,"执行空间："+data.namespace,"通知与任务的实际处理结果另行读取。"]});return;
    }
    if(!eventForm.current?.reportValidity())return;
    if(!draftCurrent||!definition?.actions.includes(action)){setError("当前对象、作者、资料或数据集版本需要重新核查，请取消编辑并重新选择。");return;}
    if(!draft.content.trim()){setError("请填写事件或模拟回复内容。");return;}
    const at=timestamp(draft.eventAt);
    setConfirmation({action,basis,payload:{...context(data),event_type:draft.eventType,target_id:target!.id,target_version:draft.targetVersion,author_id:author!.id,author_version:draft.authorVersion,source_id:source!.id,source_version:draft.sourceVersion,source_at:source!.as_of,event_at:at,content:draft.content.trim(),expected_clock_version:data.business_clock.version},preview:["事件类型："+definition.title,"关联事项："+target!.id+" · v"+draft.targetVersion,"模拟作者："+author!.id+" · v"+draft.authorVersion,"来源："+source!.id+" · v"+draft.sourceVersion,"业务时间："+at,"来源资料时间："+source!.as_of,"执行空间："+data.namespace,draft.content.trim()]});
  }
  function submit(){if(!confirmation||!confirmationCurrent||!approved||busy)return;const value=confirmation;setConfirmation(null);setApproved(false);void api.execute(value.action,value.payload).then(recorded=>{if(recorded){if(value.action==="advance-clock"){setClock("");setClockBasis(null);}else{setDraft(EMPTY);setDraftContext(null);}}});}
  const controls=<><button className="boss-btn boss-btn-primary" disabled={busy||!data?.allowed_actions.includes("inject")||!definition?.actions.includes("inject")} onClick={()=>propose("inject")}>注入事件</button><button className="boss-btn" disabled={busy||!data?.allowed_actions.includes("reply")||!definition?.actions.includes("reply")} onClick={()=>propose("reply")}>提供模拟回复</button></>;
  const outcomes:readonly [string,Outcome|undefined][]=[["事件保存结果",record?.saved],["触发任务",record?.tasks],["系统通知",record?.notifications],["模拟执行结果",record?.simulation],["Agent 处理结果",record?.agent]];
  return <div className="boss-simulation-events">
    <V7ReadState loading={api.loading} error={api.error} onReload={api.reload}/>
    {api.pending&&<p role="status" className="boss-status boss-status-warn">原请求 {api.pending.request_id} 尚需核查。<button className="boss-btn" disabled={api.busy} onClick={()=>void api.reconcile()}>查询原请求</button></p>}
    {api.receipt&&<p className="boss-status">操作已经记录：{api.receipt.request_id}。任务、通知及Agent处理结果以各自记录为准。</p>}
    {error&&<p role="alert" className="boss-status boss-status-error">{error}</p>}
    {draftContext&&!contextCurrent&&<p role="alert" className="boss-status boss-status-warn">编辑内容属于先前数据集或执行空间，请取消编辑后重新选择。</p>}
    <div className="boss-columns"><div className="boss-column">
      <V7Panel title="注入事件与模拟回复" action={<span className="boss-tag boss-tag-amber">SIMULATED</span>}>
        <form ref={eventForm} tabIndex={-1} id="boss-simulation-event" onSubmit={event=>event.preventDefault()}><fieldset disabled={busy||!data} className="boss-v7-form-fieldset"><div className="boss-form-grid">
          <label>事件类型<select required value={draft.eventType} onChange={event=>edit({...EMPTY,eventType:event.target.value})}><option value="">请选择事件类型</option>{data?.event_types.map(row=><option key={row.id} value={row.id}>{row.title}</option>)}</select></label>
          <label>关联事项<select required value={draft.targetId} onChange={event=>{const value=data?.targets.find(row=>row.id===event.target.value);edit({targetId:event.target.value,targetVersion:value?.version??"",authorId:"",authorVersion:"",sourceId:"",sourceVersion:""});}}><option value="">请选择获准对象</option>{data?.targets.filter(row=>definition?.target_kinds.includes(row.kind)).map(row=><option key={row.id} value={row.id}>{row.title} · v{row.version}</option>)}</select></label>
          <label>反馈作者<select required value={draft.authorId} onChange={event=>edit({authorId:event.target.value,authorVersion:data?.authors.find(row=>row.id===event.target.value)?.version??""})}><option value="">请选择模拟作者</option>{data?.authors.filter(row=>target?.author_ids.includes(row.id)).map(row=><option key={row.id} value={row.id}>{row.title} · v{row.version}</option>)}</select></label>
          <label>资料版本<select required value={draft.sourceId} onChange={event=>edit({sourceId:event.target.value,sourceVersion:data?.sources.find(row=>row.id===event.target.value)?.version??""})}><option value="">请选择获准来源</option>{data?.sources.filter(row=>target?.source_ids.includes(row.id)&&row.state==="CURRENT").map(row=><option key={row.id} value={row.id}>{row.title} · v{row.version}</option>)}</select></label>
          <label>业务事件时间（Asia/Shanghai）<input required type="datetime-local" value={draft.eventAt} onChange={event=>edit({eventAt:event.target.value})}/></label>
          <label>来源资料时间<input readOnly value={source?.as_of??"尚未选择来源"}/></label>
        </div><label className="boss-field">事件或模拟回复内容<textarea id="boss-simulation-feedback" required maxLength={2400} rows={4} value={draft.content} onChange={event=>edit({content:event.target.value})} placeholder="填写当前获准模拟事件或回复的具体内容"/></label><div className="boss-actions">{controls}</div></fieldset></form>
        <p className="boss-v7-note">仅在获准的模拟空间保存。模拟作者不能代替老板授权、批准延期或确认完成。</p>
      </V7Panel>
      <V7Panel title="推进业务时钟"><form ref={clockForm} tabIndex={-1} id="boss-simulation-clock" onSubmit={event=>{event.preventDefault();propose("advance-clock");}}><fieldset disabled={busy||!data} className="boss-v7-form-fieldset"><div className="boss-form-grid"><label>当前业务时钟<input readOnly value={data?.business_clock.at??"尚未读取"}/></label><label>目标业务时钟（Asia/Shanghai）<input required type="datetime-local" value={clock} onChange={event=>{if(data){setClock(event.target.value);setClockBasis(previous=>previous??{context:context(data),version:data.business_clock.version});}}}/></label></div><V7Fact label="影响范围">{data?`${data.dataset_id} · v${data.dataset_version} · ${data.namespace}`:"尚未读取当前范围"}</V7Fact><div className="boss-actions"><button type="submit" className="boss-btn" disabled={busy||!data?.allowed_actions.includes("advance-clock")}>推进时钟</button></div></fieldset></form><p className="boss-v7-note">时间推进改变模拟业务时钟，系统时间保持当前设备时间。</p></V7Panel>
    </div><aside className="boss-column"><V7Panel title="模拟与 Agent 处理结果"><label className="boss-field">选择实际操作<select value={selected} onChange={event=>setSelected(event.target.value)}><option value="">请选择已记录操作</option>{records.map(row=><option key={row.id} value={row.id}>{row.created_at} · {row.action} · {row.id}</option>)}</select></label>{outcomes.map(([label,value])=><div key={label}><V7Fact label={label}>{value?.state??"尚未选择实际记录"}</V7Fact>{value?.ids.length? <p className="boss-v7-note">{value.ids.join("、")}</p>:null}{value?.error&&<p role="alert" className="boss-status boss-status-error">{value.error}</p>}</div>)}<V7Fact label="原请求">{record?.request_id??"尚未选择"}</V7Fact><V7Fact label="来源与版本">{record?.source_id?`${record.source_id} · v${record.source_version}`:"没有已选择来源记录"}</V7Fact><div className="boss-actions">{record?.run_ids.map(id=><button className="boss-btn" key={id} onClick={()=>onOpenRun(id)}>查看运行 {id}</button>)}<button className="boss-btn" onClick={()=>onNavigate("A15")}>关联运行记录</button></div></V7Panel>
      <V7Panel title="权限边界"><V7Fact label="当前身份">技术维护</V7Fact><V7Fact label="可用范围">模拟资料与获准维护</V7Fact><V7Fact label="老板决定">必须由老板入口完成</V7Fact><V7Fact label="执行空间">{data?.namespace??"尚未读取"}</V7Fact><V7Fact label="资料读取时间">{data?.read_at??"尚未读取"}</V7Fact><p className="boss-v7-note">场景保存、模拟执行与Agent处理分别显示各自状态，失败原因持续可查。</p></V7Panel>
    </aside></div>
    <details className="boss-simulation-records"><summary>查看实际事件与回复记录</summary><div className="boss-v7-table-scroll"><table className="boss-v7-table"><thead><tr><th>操作</th><th>对象</th><th>保存状态</th><th>Agent 状态</th><th>时间</th></tr></thead><tbody>{records.slice((currentPage-1)*10,currentPage*10).map(row=><tr key={row.id} aria-selected={row.id===selected}><td><button className="boss-v7-text-button" onClick={()=>setSelected(row.id)}>{row.action} · {row.id}</button></td><td>{row.target_id??"无关联对象"}</td><td>{row.saved.state}</td><td>{row.agent.state}</td><td>{row.created_at}</td></tr>)}</tbody></table></div>{!records.length&&<V7Empty title="尚无已读取的操作记录"/>}<V7Pagination page={currentPage} total={records.length} pageSize={10} onChange={setPage}/></details>
    <details className="boss-simulation-records"><summary>经营场景、标准事件与已有对象回复</summary>{children}</details>
    <footer className="boss-maintainer-actions"><span>{dirty?"当前表单包含未提交修改":"SIMULATED · 获准维护"}</span><button className="boss-btn" disabled={api.busy||!dirty} onClick={discard}>取消编辑</button><button className="boss-btn" disabled={api.busy||dirty} onClick={api.reload}>重新读取</button><button className="boss-btn" onClick={()=>onNavigate("F25")}>模拟中心</button>{controls}</footer>
    <Dialog.Root open={!!confirmation} onOpenChange={open=>{if(!open&&!api.busy){setConfirmation(null);setApproved(false);}}}><Dialog.Portal><Dialog.Overlay className="boss-v7-dialog-overlay"/><Dialog.Content className="boss-v7-dialog"><Dialog.Title>{confirmation?.action==="advance-clock"?"确认推进业务时钟":confirmation?.action==="reply"?"确认提供模拟回复":"确认注入模拟事件"}</Dialog.Title><Dialog.Description>核查当前空间、对象和版本。本次操作不授予老板业务权限。</Dialog.Description>{confirmation?.preview.map((line,index)=><p key={index}>{line}</p>)}{!confirmationCurrent&&<p role="alert">当前依据已经变化，请关闭确认并重新核查。</p>}<label className="boss-confirm-check"><input type="checkbox" checked={approved} onChange={event=>setApproved(event.target.checked)}/><span>确认以上模拟内容、影响范围与时间。</span></label><div className="boss-actions"><Dialog.Close asChild><button className="boss-btn">取消</button></Dialog.Close><button className="boss-btn boss-btn-primary" disabled={!approved||!confirmationCurrent||busy} onClick={submit}>确认并保存</button></div></Dialog.Content></Dialog.Portal></Dialog.Root>
  </div>;
}
