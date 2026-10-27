import {useEffect,useRef,useState} from "react";
import * as Dialog from "@radix-ui/react-dialog";
import {useTransaction} from "./BossAssignmentFlow";
import {V7Empty,V7Fact,V7Panel} from "./BossV7UI";
import {sectorBasis,type SectorAction,type SectorProjection} from "./sector-types";

const COMMANDS={COORDINATE:"boss.sector.coordinate.create",REVIEW:"boss.sector.review.schedule",MEETING:"boss.sector.meeting.prepare",DECISION:"boss.sector.decision.save"} as const;
const SUBMIT_LABELS={COORDINATE:"核对并创建交办",REVIEW:"核对并创建复查计划",MEETING:"核查并保存会议草稿",DECISION:"核对并记录决定"} as const;
const EMPTY={purpose:"",coordinator:"",due:"",timezone:"",evidence:"",output:"",starts:"",ends:"",location:"",option:"",opinion:"",attendees:[] as string[]};
type Props={data:SectorProjection|null;action:SectorAction|null;onAction:(action:SectorAction|null)=>void;onDirtyChange:(value:boolean)=>void;onReload:()=>void;onNavigate:(page:string)=>void;onOpenTask:(id:string)=>void;onViewSource:(id:string)=>void};

export function BossSectorFollowUp({data,action,onAction,onDirtyChange,onReload,onNavigate,onOpenTask,onViewSource}:Props){
  const [form,setForm]=useState({...EMPTY}),[basis,setBasis]=useState(""),[dirty,setDirty]=useState(false),[error,setError]=useState(""),[discard,setDiscard]=useState(false);
  const formRef=useRef<HTMLDivElement>(null);
  const transaction=useTransaction(recorded=>{if(recorded){setForm({...EMPTY});setBasis("");setDirty(false);onAction(null);}onReload();},undefined,undefined,"sectorOperation");
  const locked=transaction.busy||Boolean(transaction.dialog),stale=Boolean(basis&&data&&basis!==sectorBasis(data));
  const currentAction=action&&data?.followup_actions?.find(item=>item.code===action.code&&item.kind===action.kind);
  const disabled=!data||!currentAction?.allowed||!data.query_id||stale||locked;
  const times=action?.kind==="MEETING"?[["开始时间",form.starts],["结束时间",form.ends]]:[["期限或复查时间",form.due]];
  const timePreview=data?.timezones?.includes(form.timezone)?times.filter(([,value])=>Boolean(value)&&Number.isFinite(Date.parse(value))&&/(Z|[+-]\d{2}:\d{2})$/.test(value)).map(([label,value])=>({label,local:new Intl.DateTimeFormat("zh-CN",{timeZone:form.timezone,dateStyle:"full",timeStyle:"long"}).format(new Date(value)),owner:data.owner_timezone?new Intl.DateTimeFormat("zh-CN",{timeZone:data.owner_timezone,dateStyle:"full",timeStyle:"long"}).format(new Date(value)):"本人时区尚未提供",utc:new Date(value).toISOString()})):[];
  useEffect(()=>{onDirtyChange(dirty||locked);return()=>onDirtyChange(false);},[dirty,locked,onDirtyChange]);
  useEffect(()=>{if(action)requestAnimationFrame(()=>{formRef.current?.scrollIntoView({block:"start",behavior:"smooth"});formRef.current?.querySelector<HTMLElement>("textarea,input,select")?.focus();});},[action?.code]);
  function change(patch:Partial<typeof EMPTY>){if(!data||locked)return;if(!dirty)setBasis(sectorBasis(data));setForm(value=>({...value,...patch}));setDirty(true);setError("");}
  function clear(){setForm({...EMPTY});setBasis("");setDirty(false);setError("");setDiscard(false);onAction(null);}
  function validTime(value:string,label:string){
    if(!value||!/(Z|[+-]\d{2}:\d{2})$/.test(value)||!Number.isFinite(Date.parse(value))){setError("请填写包含UTC时差的完整"+label+"。");return false;}
    if(!data?.business_clock||!Number.isFinite(Date.parse(data.business_clock))){setError("业务时钟尚未提供，请重新读取。");return false;}
    if(Date.parse(value)<=Date.parse(data.business_clock)){setError(label+"必须晚于当前业务时钟。");return false;}
    return true;
  }
  function submit(){
    if(disabled||!data||!action)return;
    setError("");
    if(!form.purpose.trim()){setError("请填写本次目的与需要核查的问题。");return;}
    const contacts=data.contacts??[],coordinator=contacts.find(item=>item.contact_id===form.coordinator&&item.eligible);
    const timed=action.kind!=="DECISION";
    if(timed&&!data.timezones?.includes(form.timezone.trim())){setError("请选择服务提供的有效IANA时区。");return;}
    if(timed)new Intl.DateTimeFormat("zh-CN",{timeZone:form.timezone.trim()});
    if(["COORDINATE","REVIEW"].includes(action.kind)){
      if(!coordinator){setError("请选择当前获准目录中的唯一统筹负责人。");return;}
      if(!validTime(form.due,action.kind==="REVIEW"?"复查时间":"交办期限"))return;
      if(!form.evidence.trim()||!form.output.trim()){setError("请填写预期产物与证据检查要求。");return;}
    }
    if(action.kind==="MEETING"){
      if(!form.attendees.length||form.attendees.some(id=>!contacts.some(person=>person.contact_id===id&&person.eligible))){setError("请选择获准目录中的参会人。");return;}
      if(!validTime(form.starts,"会议开始时间")||!validTime(form.ends,"会议结束时间"))return;
      if(Date.parse(form.ends)<=Date.parse(form.starts)){setError("会议结束时间必须晚于开始时间。");return;}
      if(!form.location.trim()){setError("请填写会议地点或线上方式。");return;}
    }
    const option=data.resource_options?.find(item=>item.option_id===form.option);
    if(currentAction?.option_required&&!option){setError("请选择当前版本的资源选项。");return;}
    if(action.kind==="DECISION"&&!form.opinion.trim()){setError("请填写本次项目或资源决定及适用条件。");return;}
    const payload={page_id:data.page_id,execution_namespace:data.namespace,dataset_version:data.dataset_version,query_id:data.query_id,action_code:action.code,filters:data.applied_filters,overview_reference:data.overview_reference??null,source_refs:data.sources.map(source=>({source_id:source.source_id,version:source.version})),purpose:form.purpose.trim(),...(timed?{timezone:form.timezone.trim()}:{}),...(["COORDINATE","REVIEW"].includes(action.kind)?{coordinator_id:coordinator!.contact_id,coordinator_version:coordinator!.version,due_at:form.due,expected_output:form.output.trim(),evidence_requirements:form.evidence.trim()}:{}),...(action.kind==="MEETING"?{attendee_refs:form.attendees.map(id=>({contact_id:id,version:contacts.find(person=>person.contact_id===id)!.version})),starts_at:form.starts,ends_at:form.ends,location:form.location.trim()}:{}),...(option?{option_id:option.option_id,option_version:option.version}:{}),...(action.kind==="DECISION"?{decision:form.opinion.trim()}:{} )};
    transaction.propose(COMMANDS[action.kind],payload,action.label,["专题："+data.title+" / "+data.page_id,"查询版本："+data.dataset_version+" / "+data.query_id,"目的："+form.purpose.trim(),...(coordinator?["统筹负责人："+coordinator.display_name+" · "+coordinator.organization+" / "+coordinator.contact_id]:[]),...(timed?["时间："+(action.kind==="MEETING"?form.starts+" — "+form.ends:form.due)+" · "+form.timezone]:[]),...(action.kind==="MEETING"?["参会人："+form.attendees.map(id=>contacts.find(person=>person.contact_id===id)!.display_name).join("、"),"地点或方式："+form.location]:[]),...(option?["资源选项："+option.title+" / v"+option.version]:[]),...(action.kind==="DECISION"?["决定与条件："+form.opinion]:["预期产物："+(form.output||"会议草稿与准备材料"),"证据要求："+(form.evidence||"采用本次查询来源版本")]),"保存不发送消息，不执行资金交易、设备控制或专业处置；专业结果与协调任务分别查询。"]);
  }
  return <>
    {transaction.notice&&<p className="boss-status" role="status">{transaction.notice}</p>}{transaction.recovery}
    {action&&<div ref={formRef} className="boss-sector-followup"><V7Panel title={action.label} description="核查当前查询范围、资料版本及本次操作后保存。">
      <V7Fact label="当前查询">{data?.query_id??"尚未取得正式查询编号"}</V7Fact>
      {(!currentAction?.allowed||stale)&&<p className="boss-status boss-status-warn">{stale?"查询资料或操作条件已经变化，当前输入继续保留；请核查新资料后重新填写。":currentAction?.reason??"当前服务尚未提供此项操作的有效条件。"}</p>}
      <fieldset disabled={disabled}><div className="boss-form-grid">
        <label className="boss-form-field">目的与核查问题<textarea value={form.purpose} maxLength={2400} onChange={event=>change({purpose:event.target.value})}/></label>
        {["COORDINATE","REVIEW"].includes(action.kind)&&<><label className="boss-form-field">统筹负责人<select value={form.coordinator} onChange={event=>change({coordinator:event.target.value})}><option value="">请选择唯一负责人</option>{data?.contacts?.filter(person=>person.eligible).map(person=><option key={person.contact_id} value={person.contact_id}>{person.display_name} · {person.organization} · {person.responsibility} / {person.contact_id}</option>)}</select></label><label className="boss-form-field">{action.kind==="REVIEW"?"复查时间":"交办期限"}<input value={form.due} placeholder="完整ISO时间，包含UTC时差" onChange={event=>change({due:event.target.value})}/></label><label className="boss-form-field">预期产物<textarea value={form.output} maxLength={2400} onChange={event=>change({output:event.target.value})}/></label><label className="boss-form-field">证据与检查要求<textarea value={form.evidence} maxLength={2400} onChange={event=>change({evidence:event.target.value})}/></label></>}
        {action.kind==="MEETING"&&<><fieldset className="boss-sector-attendees"><legend>参会人</legend>{data?.contacts?.filter(person=>person.eligible).map(person=><label key={person.contact_id}><input type="checkbox" checked={form.attendees.includes(person.contact_id)} onChange={event=>change({attendees:event.target.checked?[...form.attendees,person.contact_id]:form.attendees.filter(id=>id!==person.contact_id)})}/>{person.display_name} · {person.organization} / {person.contact_id}</label>)}{!data?.contacts?.some(person=>person.eligible)&&<p>当前没有获准参会人。</p>}</fieldset><label className="boss-form-field">会议开始时间<input value={form.starts} placeholder="完整ISO时间，包含UTC时差" onChange={event=>change({starts:event.target.value})}/></label><label className="boss-form-field">会议结束时间<input value={form.ends} placeholder="完整ISO时间，包含UTC时差" onChange={event=>change({ends:event.target.value})}/></label><label className="boss-form-field">地点或线上方式<input value={form.location} maxLength={500} onChange={event=>change({location:event.target.value})}/></label></>}
        {action.kind!=="DECISION"&&<label className="boss-form-field">IANA时区<select value={form.timezone} onChange={event=>change({timezone:event.target.value})}><option value="">请选择本次安排的时区</option>{data?.timezones?.map(zone=><option key={zone} value={zone}>{zone}</option>)}</select>{!data?.timezones?.length&&<small>当前服务尚未提供可用时区。</small>}</label>}
        {(currentAction?.option_required||Boolean(data?.resource_options?.length))&&<label className="boss-form-field">资源选项<select value={form.option} onChange={event=>change({option:event.target.value})}><option value="">请选择适用选项</option>{data?.resource_options?.map(option=><option key={option.option_id} value={option.option_id}>{option.title} / v{option.version} · {option.state}</option>)}</select></label>}
        {action.kind==="DECISION"&&<label className="boss-form-field">决定与适用条件<textarea value={form.opinion} maxLength={2400} onChange={event=>change({opinion:event.target.value})}/></label>}
      </div></fieldset>
      {action.kind!=="DECISION"&&timePreview.map(value=><div className="boss-sector-section" key={value.label}><strong>{value.label}</strong><V7Fact label={"当地时间 · "+form.timezone}>{value.local}</V7Fact><V7Fact label={"本人时间 · "+(data?.owner_timezone??"尚未提供")}>{value.owner}</V7Fact><V7Fact label="UTC时间">{value.utc}</V7Fact></div>)}
      {error&&<p role="alert" className="boss-validation-error">{error}</p>}
      <div className="boss-actions"><button className="boss-btn boss-btn-primary" disabled={disabled||!dirty} onClick={submit}>{SUBMIT_LABELS[action.kind]}</button><button className="boss-btn" disabled={locked} onClick={()=>dirty?setDiscard(true):clear()}>取消本次编辑</button></div>
    </V7Panel></div>}
    <details className="boss-sector-followup-history"><summary>查看协调、复查、会议与项目决定</summary>{data?.followups?.length?data.followups.map(row=><article key={row.record_id} className="boss-workspace-item"><strong>{row.title}</strong><V7Fact label="当前记录">{row.record_id} / v{row.version} · {row.state}</V7Fact><V7Fact label="保存时间">{row.created_at}</V7Fact><div className="boss-actions">{row.task_id&&<button className="boss-btn" onClick={()=>onOpenTask(row.task_id!)}>打开协调任务</button>}{row.plan_id&&<button className="boss-btn" onClick={()=>onNavigate("N09")}>查看复查计划</button>}{row.meeting_id&&<button className="boss-btn" onClick={()=>onNavigate("N04")}>查看会议资料</button>}{row.source_ids.map(id=><button key={id} className="boss-v7-text-button" aria-label={"查看依据："+id} onClick={()=>onViewSource(id)}>查看依据</button>)}</div></article>):<V7Empty title="当前范围没有已读取的后续记录">保存后按正式对象及版本查询。</V7Empty>}</details>
    {transaction.dialog}
    <Dialog.Root open={discard} onOpenChange={setDiscard}><Dialog.Portal><Dialog.Overlay className="boss-confirm-backdrop"/><Dialog.Content className="boss-confirm"><Dialog.Title>放弃本次编辑</Dialog.Title><Dialog.Description>仅清除当前尚未提交的后续事项输入，已保存记录继续保留。</Dialog.Description><div className="boss-actions"><Dialog.Close asChild><button className="boss-btn boss-btn-primary">继续编辑</button></Dialog.Close><button className="boss-btn" onClick={clear}>确认放弃</button></div></Dialog.Content></Dialog.Portal></Dialog.Root>
  </>;
}
