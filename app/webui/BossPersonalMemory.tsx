import {useEffect,useRef,useState} from "react";
import * as Dialog from "@radix-ui/react-dialog";
import {V7Empty,V7Fact,V7Panel,V7Pagination,V7ReadState,V7Tabs} from "./BossV7UI";
import {useOwnerWorkspace} from "./useTechnicalWorkspace";

type Memory={memory_id:string;version:string;text:string;state:string;visibility:"BOSS_ONLY"|"AUTHORIZED_SHARED";valid_until:string|null;source_note:string;confirmed_at:string|null;authorization_id:string|null;source_ids:string[]};
type Projection={projection:"personal-memory";private_body_available_here:true;current:Memory|null;candidate:Memory|null;history:Memory[];
  archived_history:(Memory&{namespace:string;dataset_id:string;dataset_version:string;archived_at:string;effective_state:"READ_ONLY_HISTORY";current_evidence_eligible:false})[];
  adoption:{session_id:string;memory_version:string;adopted_at:string;scope:string}[];
  deletion:{state:string;future_adoption:string;index_state:string;failure_reason:string|null;requested_at:string|null;
    loaded_sessions:string;sessions_checked:number|null;sessions_checked_at:string|null;backups:string};read_at:string};

function MemoryPropagation({deletion}:{deletion:Projection["deletion"]|undefined}){
  const labels:Record<string,string>={NATIVE_REPLAY_AND_CONTEXT_CLEARED:"会话上下文已清理，原消息保留供本人查阅",IN_PROGRESS:"正在清理",FAILED:"清理失败，需要重新核查",REQUIRES_CONTEXT_REFRESH:"等待清理会话上下文",NOT_VERIFIED:"尚未验证",NOT_REQUESTED:"没有删除请求"};
  return <><V7Fact label="会话上下文">{deletion?labels[deletion.loaded_sessions]??deletion.loaded_sessions:"尚未读取"}</V7Fact><V7Fact label="已核查会话">{deletion?.sessions_checked??"尚未核查"}</V7Fact><V7Fact label="会话核查时间">{deletion?.sessions_checked_at??"尚未核查"}</V7Fact><V7Fact label="备份传播">{deletion?labels[deletion.backups]??deletion.backups:"尚未读取"}</V7Fact></>;
}

function editableMemory(value:Memory|null|undefined){
  const validUntil=value?.valid_until?new Date(new Date(value.valid_until).getTime()+8*60*60*1000).toISOString().slice(0,16):"";
  return {text:value?.text??"",visibility:value?.visibility??"BOSS_ONLY",valid_until:validUntil,source_note:value?.source_note??""};
}

export function BossPersonalMemory({onNavigate,onViewSource,onDirtyChange}:{onNavigate:(page:string)=>void;onViewSource:(id:string)=>void;onDirtyChange:(dirty:boolean)=>void}){
  const api=useOwnerWorkspace<Projection>("personal-memory");
  const [tab,setTab]=useState<"candidate"|"current"|"history"|"deletion">("candidate");
  const [values,setValues]=useState({text:"",visibility:"BOSS_ONLY",valid_until:"",source_note:""});
  const [dirty,setDirty]=useState(false);
  const [action,setAction]=useState<"confirm"|"delete"|null>(null);
  const [checked,setChecked]=useState(false);
  const [adoptionOpen,setAdoptionOpen]=useState(false);
  const [historyNamespace,setHistoryNamespace]=useState("");
  const [historyPage,setHistoryPage]=useState(1);
  const base=useRef({current:"0",candidate:"0"});
  const contentField=useRef<HTMLTextAreaElement>(null);
  const candidate=api.data?.candidate,current=api.data?.current;
  const effective=current?.state==="CONFIRMED";
  const latestAdoption=api.data?.adoption.find(row=>row.memory_version===current?.version);
  useEffect(()=>{if(dirty)return;setValues(editableMemory(candidate??current));base.current={current:current?.version??"0",candidate:candidate?.version??"0"};onDirtyChange(false);},[candidate,current,dirty,onDirtyChange]);
  const busy=api.busy||!!api.pending;
  const archived=(api.data?.archived_history??[]).filter(row=>!historyNamespace||row.namespace===historyNamespace);
  const currentHistoryPage=Math.min(historyPage,Math.max(1,Math.ceil(archived.length/10)));
  function edit(key:keyof typeof values,value:string){setValues(old=>({...old,[key]:value}));setDirty(true);onDirtyChange(true);}
  function submit(){
    if(!action||!checked)return;
    const confirmedValues={...values,valid_until:values.valid_until?new Date(values.valid_until+"+08:00").toISOString():null};
    void api.execute(action,{expected_version:base.current.current,expected_candidate_version:base.current.candidate,...(action==="confirm"?{values:confirmedValues}:{}),confirmation:true}).then(saved=>{if(saved){setDirty(false);onDirtyChange(false);}});setAction(null);setChecked(false);
  }
  return <><V7ReadState loading={api.loading} error={api.error} onReload={api.reload}/>{api.pending&&<p className="boss-status boss-status-warn">原请求等待核查。<button className="boss-btn" disabled={api.busy} onClick={()=>void api.reconcile()}>核查本人决定</button></p>}{api.receipt&&<p role="status" className="boss-status boss-status-ok">本人决定已记录 · {api.receipt.request_id}</p>}
    <div className="boss-columns boss-memory"><div className="boss-column"><V7Panel title="个人要求与版本"><V7Tabs label="个人记忆状态" value={tab} onChange={setTab} items={[{id:"candidate",title:"候选待确认"},{id:"current",title:"当前有效"},{id:"history",title:"历史版本"},{id:"deletion",title:"删除传播"}]}/>
      {tab==="candidate"&&<>
        <div className="boss-workspace-item"><strong>候选要求</strong><p>{candidate?`版本 ${candidate.version} · ${candidate.state}`:"尚无保存的候选要求"}</p></div>
        <form onSubmit={event=>{event.preventDefault();setAction("confirm");setChecked(false);}}>
          <fieldset className="boss-v7-form-fieldset" disabled={busy||!api.data}>
            <div className="boss-memory-form">
              <label><span>要求具体内容</span><textarea ref={contentField} required rows={3} maxLength={4000} value={values.text} onChange={event=>edit("text",event.target.value)}/></label>
              <label><span>可见范围</span><select value={values.visibility} onChange={event=>edit("visibility",event.target.value)}><option value="BOSS_ONLY">本人专用</option><option value="AUTHORIZED_SHARED">获准共享</option></select></label>
              <label><span>有效期限</span><input type="datetime-local" value={values.valid_until} onChange={event=>edit("valid_until",event.target.value)}/><small>Asia/Shanghai（UTC+08:00）；留空表示持续有效，直到本人撤销。</small></label>
              <label><span>来源说明</span><input required value={values.source_note} onChange={event=>edit("source_note",event.target.value)}/></label>
            </div>
            <div className="boss-actions">
              <button className="boss-btn boss-btn-primary" type="submit" disabled={!values.text.trim()||!values.source_note.trim()}>确认当前要求</button>
              <button className="boss-btn" type="button" onClick={()=>contentField.current?.focus()}>修改要求</button>
              <button className="boss-btn boss-btn-danger" type="button" disabled={!current||current.state==="DELETED"} onClick={()=>{setAction("delete");setChecked(false);}}>删除要求</button>
              {dirty&&<button className="boss-btn" type="button" onClick={()=>{setValues(editableMemory(candidate??current));setDirty(false);onDirtyChange(false);}}>取消本次修改</button>}
            </div>
          </fieldset>
        </form>
      </>}
      {tab==="current"&&(current?<><V7Fact label="当前版本">{current.version}</V7Fact><V7Fact label="有效状态">{current.state}</V7Fact><blockquote className="boss-source">{current.text}</blockquote><V7Fact label="可见范围">{current.visibility==="BOSS_ONLY"?"本人专用":"仅获准共享范围"}</V7Fact><V7Fact label="有效期限">{current.valid_until??"持续有效，直到本人撤销"}</V7Fact><V7Fact label="来源说明">{current.source_note}</V7Fact><div className="boss-actions"><button className="boss-btn" onClick={()=>setTab("candidate")}>修改要求</button><button className="boss-btn" disabled={busy||current.state==="DELETED"} onClick={()=>{setAction("delete");setChecked(false);}}>删除要求</button>{current.source_ids.map(id=><button className="boss-btn" key={id} onClick={()=>onViewSource(id)}>打开 {id}</button>)}</div></>:<V7Empty title="当前没有有效个人要求"/>)}
      {tab==="history"&&<><h3>当前空间历史版本</h3>{api.data?.history.length?api.data.history.map(row=><article className="boss-workspace-item" key={row.memory_id+row.version}><strong>v{row.version} · {row.state}</strong><p>{row.text}</p><small>{row.confirmed_at??"没有确认时间"} · {row.source_note}</small></article>):<V7Empty title="尚无历史版本记录"/>}<h3>归档空间个人要求</h3><p className="boss-status">仅供本人只读查询。归档内容不参与当前会话与任务采用。</p><label className="boss-field">原执行空间<select value={historyNamespace} onChange={event=>{setHistoryNamespace(event.target.value);setHistoryPage(1);}}><option value="">全部获准归档空间</option>{[...new Set(api.data?.archived_history.map(row=>row.namespace)??[])].map(value=><option key={value}>{value}</option>)}</select></label>{archived.slice((currentHistoryPage-1)*10,currentHistoryPage*10).map(row=><article className="boss-workspace-item" key={row.namespace+":"+row.memory_id+":"+row.version}><strong>v{row.version} · {row.state} · 归档只读</strong><V7Fact label="原执行空间">{row.namespace}</V7Fact><V7Fact label="原数据集">{row.dataset_id} · v{row.dataset_version}</V7Fact><V7Fact label="归档时间">{row.archived_at}</V7Fact>{row.state==="DELETED"?<p>本人已删除该要求，正文不再展示。</p>:<><blockquote className="boss-source">{row.text}</blockquote><small>{row.confirmed_at??"没有确认时间"} · {row.source_note}</small></>}</article>)}{!archived.length&&<V7Empty title="当前条件下没有归档个人要求"/>}<V7Pagination page={currentHistoryPage} total={archived.length} pageSize={10} onChange={setHistoryPage}/><button className="boss-btn" onClick={()=>onNavigate("N11")}>查看历史决定</button></>}
      {tab==="deletion"&&<><V7Fact label="删除请求">{api.data?.deletion.state??"尚未读取"}</V7Fact><V7Fact label="后续采用">{api.data?.deletion.future_adoption??"尚未读取"}</V7Fact><V7Fact label="索引传播">{api.data?.deletion.index_state??"尚未读取"}</V7Fact><MemoryPropagation deletion={api.data?.deletion}/><V7Fact label="传播失败原因">{api.data?.deletion.failure_reason??"没有已记录失败"}</V7Fact><div className="boss-actions"><button className="boss-btn" disabled={busy} onClick={api.reload}>重新核查传播状态</button><button className="boss-btn" disabled={busy||current?.state!=="DELETED"} onClick={()=>void api.execute("reconcile",{expected_version:current?.version})}>再次清理会话上下文</button></div></>}
    </V7Panel>
    <V7Panel title="来源、确认和采用">
      <V7Fact label="本人确认记录">{current?.authorization_id??"尚未确认"}{current?.confirmed_at&&<small className="boss-memory-confirmed-at">{current.confirmed_at}</small>}</V7Fact>
      <V7Fact label="当前有效版本">{effective?current.version:"尚无有效版本"}</V7Fact>
      <V7Fact label="新会话采用时间">{latestAdoption?.adopted_at??"尚无当前版本采用记录"}</V7Fact>
      <V7Fact label="采用范围">{effective?(current.visibility==="BOSS_ONLY"?"本人专用":"获准共享"):"尚未生效"}</V7Fact>
      <div className="boss-actions"><button className="boss-btn" aria-expanded={adoptionOpen} onClick={()=>setAdoptionOpen(value=>!value)}>查看新会话采用记录</button><button className="boss-btn" onClick={()=>onNavigate("N02")}>聊天交办</button></div>
      {adoptionOpen&&(api.data?.adoption.length?api.data.adoption.map(row=><article className="boss-workspace-item" key={row.session_id+row.adopted_at}><strong>{row.session_id}</strong><p>v{row.memory_version} · {row.scope}</p><small>{row.adopted_at}</small></article>):<V7Empty title="尚无新会话采用记录"/>)}
    </V7Panel></div>
    <aside className="boss-column"><V7Panel title="删除与传播状态"><V7Fact label="后续采用">{api.data?.deletion.future_adoption??"尚未读取"}</V7Fact><V7Fact label="索引传播">{api.data?.deletion.index_state??"尚未读取"}</V7Fact><V7Fact label="传播失败原因">{api.data?.deletion.failure_reason??"没有已记录失败"}</V7Fact><p className="boss-v7-note">删除后停止后续采用，传播中的索引状态持续可查。</p></V7Panel></aside></div>
    <Dialog.Root open={action!==null} onOpenChange={open=>{if(!open)setAction(null);}}><Dialog.Portal><Dialog.Overlay className="boss-v7-dialog-overlay"/><Dialog.Content className="boss-v7-dialog"><Dialog.Title>{action==="delete"?"删除个人要求":"确认当前个人要求"}</Dialog.Title><Dialog.Description>{action==="delete"?"该要求将停止用于后续任务，已有授权记录与历史运行按原归属保留。":"确认后，后续任务在当前有效期和获准范围内采用该要求。"}</Dialog.Description>{action==="confirm"&&<blockquote>{values.text}</blockquote>}<label className="boss-confirm-check"><input type="checkbox" checked={checked} onChange={event=>setChecked(event.target.checked)}/>本人确认当前内容、范围和操作后果</label><div className="boss-actions"><Dialog.Close asChild><button className="boss-btn">取消</button></Dialog.Close><button className="boss-btn boss-btn-primary" disabled={!checked||busy} onClick={submit}>确认并保存决定</button></div></Dialog.Content></Dialog.Portal></Dialog.Root>
  </>;
}
