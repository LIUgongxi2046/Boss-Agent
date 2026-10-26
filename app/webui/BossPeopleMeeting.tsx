import {useEffect,useRef,useState,type ReactNode} from "react";
import * as Dialog from "@radix-ui/react-dialog";
import {AlertCircle,ClipboardCheck,FileSearch,Loader2,Plus,RefreshCw,ShieldCheck,Trash2,Users,XCircle} from "lucide-react";
import {useClient} from "@/providers/ClientProvider";
import {useTransaction} from "./BossAssignmentFlow";
import {readLibraryContext} from "./library-context";

type Contact={contact_id:string;name:string;organization:string;responsibility:string;valid_from:string;valid_until:string};
type SourceRef={source_id:string;version:string};
type Source=SourceRef&{excerpt:string|null;author_contact_id?:string;published_at?:string;source_type:"SIMULATED";access_state?:string;reference_state?:string};
type Task={task_id:string;version:string;status:string;due_at?:string;evidence_requirements:string[];is_historical:boolean};
type Compiled={
  contact:Contact;purpose:string;meeting:{meeting_id:string|null;version:string|null;contact_is_participant:boolean};
  goals:string[];sources:Source[];tasks:Task[];
  feedback:{feedback_id:string;task_id:string;kind:string;author_contact_id?:string;evidence_source_ids:string[];content?:string;submitted_at?:string}[];
  questions:{task_id:string;text:string;question_is_generated_from_status_only?:boolean}[];
  has_original_evidence:boolean;
  commitments?:{commitment_id:string;version:string;status:string;text:string;due_at?:string;source_refs:SourceRef[]}[];
  responsibility_history?:{contact_id:string;organization:string;responsibility:string;valid_from:string;valid_until:string;source_refs:SourceRef[]}[];
  missing_items?:string[];
};
type Brief={brief_id:string;version:string;state:string;compiled:Compiled;compiled_sha256:string;linked_meeting_version:string|null;live_evidence_current:boolean;prepared_at:string};
type Meeting={meeting_id:string;version:string;participant_ids:string[];starts_at:string;state?:string};
type Projection={projection:"people";source_type:"SIMULATED";data_version:string;execution_namespace?:string;briefs:Brief[];contacts:Contact[];meeting:Meeting;business_clock:string;available_sources?:SourceRef[];meetings?:Meeting[]};
type Form={contactId:string;purpose:string;meetingId:string;sources:SourceRef[];basis:string};
type Props={onNavigate:(page:string)=>void;onViewSource:(source:string,anchor?:{version:string;start:number;end:number})=>void;onOpenTask:(id:string)=>void;onDirtyChange?:(dirty:boolean)=>void;refreshVersion?:number};
const EMPTY:Form={contactId:"",purpose:"",meetingId:"",sources:[],basis:""};
function Panel({title,children}:{title:string;children:ReactNode}){return <section className="boss-panel"><div className="boss-panel-head"><h2>{title}</h2></div>{children}</section>;}
function Fact({label,value}:{label:string;value?:string|number|null}){return <div className="boss-kv"><span>{label}</span><strong>{value??"尚未提供"}</strong></div>;}
function time(value?:string){return value?new Intl.DateTimeFormat("zh-CN",{dateStyle:"medium",timeStyle:"short",timeZone:"Asia/Shanghai"}).format(new Date(value)):"尚未提供";}
function signature(data:Projection,id:string,contactId:string,meetingId:string){
  const saved=data.briefs.find(value=>value.brief_id===id);
  return JSON.stringify([data.execution_namespace,data.data_version,id,saved?.version,saved?.compiled_sha256,saved?.live_evidence_current,saved?.linked_meeting_version,data.contacts.find(value=>value.contact_id===contactId),(data.meetings??[data.meeting]).find(value=>value.meeting_id===meetingId),data.available_sources]);
}
function savedForm(data:Projection,id:string):Form{
  const saved=data.briefs.find(value=>value.brief_id===id),compiled=saved?.compiled;
  const form={contactId:compiled?.contact.contact_id??"",purpose:compiled?.purpose??"",meetingId:compiled?.meeting.meeting_id??"",sources:compiled?.sources.map(value=>({source_id:value.source_id,version:value.version}))??[],basis:""};
  return {...form,basis:signature(data,id,form.contactId,form.meetingId)};
}
export function BossPeopleMeeting(props:Props){
  const {token}=useClient(),identity=useRef({token,version:0});
  if(identity.current.token!==token)identity.current={token,version:identity.current.version+1};
  return <PeopleMeeting key={identity.current.version} {...props}/>;
}
function PeopleMeeting({onNavigate,onViewSource,onOpenTask,onDirtyChange,refreshVersion}:Props){
  const {getToken}=useClient();
  const [data,setData]=useState<Projection|null>(null),[revision,setRevision]=useState(0),[loading,setLoading]=useState(true),[error,setError]=useState("");
  const [briefId,setBriefId]=useState(""),briefRef=useRef("");
  const [form,setForm]=useState<Form>(EMPTY),[dirty,setDirty]=useState(false),dirtyRef=useRef(false);
  const [sourceIndex,setSourceIndex]=useState(""),[unlinkReason,setUnlinkReason]=useState(""),[nextBrief,setNextBrief]=useState<string|null>(null);
  const reload=()=>setRevision(value=>value+1);
  const transaction=useTransaction(recorded=>{if(recorded){dirtyRef.current=false;setDirty(false);setUnlinkReason("");setForm(value=>({...value,basis:""}));}reload();},id=>{briefRef.current=id;setBriefId(id);setSourceIndex("");},undefined,"people");
  dirtyRef.current=dirty||Boolean(unlinkReason.trim());
  const edited=dirty||Boolean(unlinkReason.trim());
  useEffect(()=>{onDirtyChange?.(edited||transaction.busy);return()=>onDirtyChange?.(false);},[edited,transaction.busy,onDirtyChange]);
  useEffect(()=>{if(!edited&&!transaction.busy)return;const guard=(event:BeforeUnloadEvent)=>{event.preventDefault();event.returnValue="";};window.addEventListener("beforeunload",guard);return()=>window.removeEventListener("beforeunload",guard);},[edited,transaction.busy]);
  useEffect(()=>{
    const controller=new AbortController(),token=getToken();setData(null);setLoading(true);setError("");
    if(!token){setLoading(false);setError("老板身份已过期，请重新认证");return;}
    void fetch("/api/boss/ui/workspace/people",{headers:{Authorization:"Bearer "+token},signal:controller.signal,cache:"no-store"}).then(async response=>{
      if(response.status===401)window.dispatchEvent(new Event("boss-auth-expired"));
      if(!response.ok)throw new Error("会面材料读取失败（HTTP "+response.status+"）");
      const value=await response.json() as Projection;
      if(value.source_type!=="SIMULATED"||value.projection!=="people")throw new Error("资料不属于获准的会面范围");
      return value;
    }).then(value=>{if(controller.signal.aborted)return;setData(value);setLoading(false);if(!dirtyRef.current){const context=readLibraryContext();const target=context?.kind==="people"?value.briefs.find(row=>row.brief_id===context.id):undefined;if(target&&!briefRef.current){briefRef.current=target.brief_id;setBriefId(target.brief_id);}else if(context?.kind==="people"&&!target){setError("原会面记录不在当前目录，请重新选择");return;}if(briefRef.current&&!value.briefs.some(row=>row.brief_id===briefRef.current)){setError("当前获准材料中没有原会面记录，请重新选择");return;}setForm(savedForm(value,briefRef.current));}}).catch(reason=>{if(controller.signal.aborted)return;setLoading(false);setError(reason instanceof Error?reason.message:String(reason));});
    return()=>controller.abort();
  },[revision,refreshVersion,getToken]);
  const current=!loading?data:null,selected=current?.briefs.find(value=>value.brief_id===briefId),compiled=selected?.compiled;
  const contact=current?.contacts.find(value=>value.contact_id===form.contactId);
  const meetings=current?(current.meetings??[current.meeting]):[],meeting=meetings.find(value=>value.meeting_id===form.meetingId);
  const stale=Boolean(current&&form.basis&&form.basis!==signature(current,briefId,form.contactId,form.meetingId));
  const disabled=transaction.busy||!current||!form.basis||stale;
  const linked=selected?.linked_meeting_version!=null;
  const source=compiled?.sources.find(value=>JSON.stringify([value.source_id,value.version])===sourceIndex);
  const contactCurrent=Boolean(contact&&current&&contact.valid_from<=current.business_clock.slice(0,10)&&current.business_clock.slice(0,10)<=contact.valid_until);
  const savedMeeting=meetings.find(value=>value.meeting_id===compiled?.meeting.meeting_id);
  const canAttach=Boolean(selected&&selected.live_evidence_current&&!linked&&!dirty&&compiled?.meeting.meeting_id&&savedMeeting&&savedMeeting.version===compiled.meeting.version&&!['CANCELED','HELD'].includes(savedMeeting.state??"")&&["READY_FOR_REVIEW","MATERIALS_MISSING"].includes(selected.state));
  function edit(change:Partial<Form>){if(!current||disabled||linked)return;setForm(value=>{const next={...value,...change};return {...next,basis:signature(current,briefId,next.contactId,next.meetingId)};});dirtyRef.current=true;setDirty(true);setError("");}
  function select(id:string){if(!current||transaction.busy)return;briefRef.current=id;setBriefId(id);setForm(savedForm(current,id));setDirty(false);dirtyRef.current=false;setUnlinkReason("");setSourceIndex("");setNextBrief(null);setError("");}
  function choose(id:string){if(edited)setNextBrief(id);else select(id);}
  function prepare(){
    if(disabled||linked||!current)return;setError("");
    if(!contact||!contactCurrent){setError("请选择当前职责有效的联系人");return;}
    if(!form.purpose.trim()||form.purpose.trim().length>1200){setError("请填写1—1200字的会面目的");return;}
    if(form.meetingId&&!meeting){setError("所选会议已经不在当前获准范围");return;}
    const refs=form.sources.map(value=>({source_id:value.source_id.trim(),version:value.version.trim()}));
    if(refs.length>8||refs.some(value=>!value.source_id||!value.version)||new Set(refs.map(value=>value.source_id)).size!==refs.length){setError("最多选择8份资料，每份资料需要独立来源编号和版本");return;}
    transaction.propose("boss.people.prepare",{brief_id:briefId||null,expected_version:selected?.version??"0",contact_id:contact.contact_id,purpose:form.purpose.trim(),meeting_id:form.meetingId||null,source_refs:refs},"准备会面材料",["会面对象："+contact.name+" · "+contact.organization+" · "+contact.contact_id,"当前职责："+contact.responsibility+"；有效期："+contact.valid_from+" 至 "+contact.valid_until,"会面目的："+form.purpose.trim(),"拟关联会议："+(meeting?meeting.meeting_id+" · v"+meeting.version:"未选择"),"资料："+(refs.map(value=>value.source_id+" · v"+value.version).join("、")||"未选择原文资料"),"保存工作材料和版本；会议议题关联需要单独确认。"]);
  }
  function attach(){
    if(disabled||!canAttach||!selected||!compiled)return;
    transaction.propose("boss.people.attach",{brief_id:selected.brief_id,expected_version:selected.version,meeting_id:compiled.meeting.meeting_id,meeting_version:compiled.meeting.version,compiled_sha256:selected.compiled_sha256},"加入获准会议议题",["会面对象："+compiled.contact.name+" · "+compiled.contact.contact_id,"会议："+compiled.meeting.meeting_id+" · v"+compiled.meeting.version,"材料："+selected.brief_id+" · v"+selected.version,"本次登记会议议题，原有参会名单保持当前状态，邀请需要另行处理。"]);
  }
  function detach(){
    if(disabled||!selected||!linked)return;if(!unlinkReason.trim()){setError("请填写解除关联的原因");return;}
    transaction.propose("boss.people.detach",{brief_id:selected.brief_id,expected_version:selected.version,reason:unlinkReason.trim()},"解除会议议题关联",["材料："+selected.brief_id+" · v"+selected.version,"会议："+selected.compiled.meeting.meeting_id,"原因："+unlinkReason.trim(),"解除当前应用内议题关联，历史材料和本人决定继续保留。"]);
  }
  function openSource(){if(source?.excerpt&&selected?.live_evidence_current)onViewSource(source.source_id,{version:source.version,start:0,end:Array.from(source.excerpt).length});}
  function sourceButtons(refs:SourceRef[]){return <div className="boss-actions">{refs.map(value=><button key={JSON.stringify([value.source_id,value.version])} type="button" className="boss-btn" disabled={!compiled?.sources.some(row=>row.source_id===value.source_id&&row.version===value.version)} onClick={()=>setSourceIndex(JSON.stringify([value.source_id,value.version]))}>{value.source_id} · v{value.version}</button>)}</div>;}
  return <div className="boss-people-view">
    <div className="boss-workspace-toolbar"><span className="boss-tag boss-tag-amber">SIMULATED</span><label>会面材料<select value={briefId} disabled={loading||transaction.busy} onChange={event=>choose(event.target.value)}><option value="">新建会面准备</option>{current?.briefs.map(value=><option key={value.brief_id} value={value.brief_id}>{value.compiled.contact.name} · {value.compiled.contact.organization} · v{value.version}</option>)}</select></label><button type="button" className="boss-btn" disabled={loading||transaction.busy} onClick={reload}>{loading?<Loader2 size={15} className="boss-spin"/>:<RefreshCw size={15}/>}重读材料</button></div>
    {error&&<div role="alert" className="boss-status boss-status-error"><AlertCircle size={16}/>{error}</div>}
    {transaction.notice&&<div role="status" className="boss-status boss-status-ok">{transaction.notice}</div>}
    {stale&&<div role="alert" className="boss-status boss-status-warn">材料、职责或会议版本已经变化。输入内容已保留，请核查后恢复当前保存内容。</div>}
    <fieldset className="boss-people-filters" disabled={disabled||linked}><label>会面对象<select value={form.contactId} onChange={event=>edit({contactId:event.target.value})}><option value="">请选择明确对象</option>{current?.contacts.map(value=><option key={value.contact_id} value={value.contact_id}>{value.name} · {value.organization} · {value.contact_id}</option>)}</select></label><label>当前职责<input readOnly value={contact?.responsibility??"等待选择联系人"}/></label><label>会面目的<input maxLength={1200} value={form.purpose} onChange={event=>edit({purpose:event.target.value})} placeholder="沟通问题与期望结果"/></label></fieldset>
    <div className="boss-people-columns"><main className="boss-column">
      <Panel title="内容与配置">
        <Fact label="已保存材料对象" value={compiled?compiled.contact.name+" · "+compiled.contact.organization+" · "+compiled.contact.contact_id:null}/>
        {dirty&&<p className="boss-status boss-status-warn">编辑内容尚未保存，以下为已保存材料。</p>}{selected&&!selected.live_evidence_current&&<p className="boss-status boss-status-warn">来源或工作事实已经变化。已保存记录仅供核查，当前依据需要重新准备。</p>}
        <section className="boss-people-section"><h3>会面目标</h3><p>{compiled?.purpose??"选择会面对象并明确沟通目的后准备材料。"}</p>{compiled?.goals.length?<ul>{compiled.goals.map(value=><li key={value}>{value}</li>)}</ul>:<p className="boss-helper">{selected?"当前材料没有采用本人目标。":"本人目标将在准备材料后核查。"}</p>}</section>
        <section className="boss-people-section"><h3>历史交办与工作事项</h3>{compiled?.tasks.length?compiled.tasks.map(task=><article className="boss-workspace-item" key={task.task_id}><strong>{task.task_id} · {task.status}</strong><p>版本 {task.version} · {task.is_historical?"历史工作记录":"准备时的任务记录"}</p><Fact label="有效期限" value={time(task.due_at)}/><p className="boss-helper">证据要求：{task.evidence_requirements.join("、")||"尚未提供"}</p><button type="button" className="boss-btn" disabled={task.is_historical} onClick={()=>onOpenTask(task.task_id)}>打开关联事项</button>{task.is_historical&&<p className="boss-helper">历史原事项入口尚未提供。</p>}</article>):<p className="boss-helper">{selected?"当前材料没有返回该联系人的交办记录。":"准备材料后显示获准交办及其版本。"}</p>}</section>
        <section className="boss-people-section"><h3>承诺</h3>{compiled?.commitments?.map(value=><article className="boss-workspace-item" key={value.commitment_id}><strong>{value.text}</strong><Fact label="承诺版本" value={value.version}/><Fact label="状态" value={value.status}/><Fact label="有效期限" value={time(value.due_at)}/>{sourceButtons(value.source_refs)}</article>)}{!compiled?.commitments?.length&&<p className="boss-helper">{compiled?.commitments?"当前材料未包含承诺记录。":"承诺材料尚未提供。"}</p>}</section>
        <section className="boss-people-section"><h3>当前反馈</h3>{compiled?.feedback.length?compiled.feedback.map(value=><article className="boss-workspace-item" key={value.feedback_id}><strong>{value.kind} · {value.feedback_id}</strong><Fact label="作者" value={value.author_contact_id}/><Fact label="关联事项" value={value.task_id}/><Fact label="提交时间" value={time(value.submitted_at)}/><p>{value.content??"反馈正文尚未提供。"}</p><p className="boss-helper">反馈来源：{value.evidence_source_ids.join("、")||"尚未提供"}</p></article>):<p className="boss-helper">{selected?"当前材料没有返回反馈记录。":"准备材料后查看获准反馈。"}</p>}</section>
        <section className="boss-people-section"><h3>待回答问题</h3>{compiled?.questions.length?compiled.questions.map(value=><article className="boss-workspace-item" key={value.task_id}><strong>{value.task_id}</strong><p>{value.text}</p>{value.question_is_generated_from_status_only&&<p className="boss-helper">依据任务状态生成，具体工作情况需要核查。</p>}</article>):<p className="boss-helper">{selected?"当前材料未列出待回答问题，完整覆盖仍需核查。":"准备材料后显示需要本人判断的问题。"}</p>}</section>
        <h3>编辑内容与说明</h3><fieldset className="boss-people-editor" disabled={disabled||linked}><label>本次会面目的<textarea rows={3} maxLength={1200} value={form.purpose} onChange={event=>edit({purpose:event.target.value})}/></label><label>获准会议<select value={form.meetingId} onChange={event=>edit({meetingId:event.target.value})}><option value="">暂不选择</option>{meetings.map(value=><option key={value.meeting_id} value={value.meeting_id}>{value.meeting_id} · v{value.version} · {time(value.starts_at)}</option>)}</select></label><div className="boss-people-source-editor"><span className="boss-label">原文资料与版本</span>{form.sources.map((value,index)=><div className="boss-people-source-row" key={index}><label>来源编号<input maxLength={128} value={value.source_id} onChange={event=>edit({sources:form.sources.map((row,position)=>position===index?{...row,source_id:event.target.value}:row)})}/></label><label>版本<input maxLength={40} value={value.version} onChange={event=>edit({sources:form.sources.map((row,position)=>position===index?{...row,version:event.target.value}:row)})}/></label><button type="button" className="boss-btn" aria-label={"移除第"+(index+1)+"份资料"} onClick={()=>edit({sources:form.sources.filter((_,position)=>position!==index)})}><Trash2 size={15}/></button></div>)}<button type="button" className="boss-btn" disabled={form.sources.length>=8} onClick={()=>edit({sources:[...form.sources,{source_id:"",version:""}]})}><Plus size={15}/>添加资料</button><p className="boss-helper">最多8份获准资料，保存时逐项核查来源与版本。</p></div></fieldset>
        <div className="boss-actions"><button type="button" className="boss-btn" disabled={!current||transaction.busy||(!edited&&!stale)} onClick={()=>select(briefId)}>恢复当前保存内容</button>{linked&&<span className="boss-helper">材料已关联会议，修改前需要解除当前关联。</span>}</div>
      </Panel>
      <Panel title="关联内容与处理边界"><Fact label="材料中选择的会议" value={compiled?.meeting.meeting_id}/><Fact label="准备时会议版本" value={compiled?.meeting.version}/><Fact label="当前获准会议版本" value={savedMeeting?.version}/><Fact label="是否现有参会人员" value={compiled?compiled.meeting.contact_is_participant?"已在名单中":"未在名单中":null}/><Fact label="议题关联版本" value={selected?selected.linked_meeting_version??"未关联":null}/><p className="boss-helper">登记会面材料作为会议议题。联系人账号、参会名单和外部邀请分别处理。</p><button type="button" className="boss-btn" onClick={()=>onNavigate("F04")}><Users size={15}/>查看会前材料</button>{linked&&<div className="boss-people-detach"><label>解除关联原因<input maxLength={400} value={unlinkReason} disabled={disabled} onChange={event=>setUnlinkReason(event.target.value)}/></label><button className="boss-btn" type="button" disabled={disabled||!unlinkReason.trim()} onClick={detach}><XCircle size={15}/>解除议题关联</button></div>}</Panel>
    </main><aside className="boss-column">
      <Panel title="来源与依据"><label className="boss-label" htmlFor="boss-people-source">原文资料</label><select id="boss-people-source" className="boss-single-input" value={source?sourceIndex:""} onChange={event=>setSourceIndex(event.target.value)} disabled={!compiled?.sources.length}><option value="">请选择原文</option>{compiled?.sources.map(value=><option key={JSON.stringify([value.source_id,value.version])} value={JSON.stringify([value.source_id,value.version])}>{value.source_id} · v{value.version}</option>)}</select>{source?<><Fact label="作者" value={source.author_contact_id}/><Fact label="发布日期" value={time(source.published_at)}/><Fact label="版本" value={source.version}/>{source.excerpt!==null?<p className="boss-people-excerpt">{source.excerpt}</p>:<p className="boss-status boss-status-warn">原文当前不可读取，请重新核查来源权限与有效性。</p>}{source.access_state&&<Fact label="读取状态" value={source.access_state}/>}</>:<p className="boss-helper">选择原文后查看作者、日期和来源版本。</p>}<h3>职责与有效期</h3><Fact label="当前联系人" value={contact?contact.name+" · "+contact.contact_id:null}/><Fact label="当前组织" value={contact?.organization}/><Fact label="当前职责" value={contact?.responsibility}/><Fact label="有效期限" value={contact?contact.valid_from+" 至 "+contact.valid_until:null}/><Fact label="当前职责有效性" value={contact?contactCurrent?"当前有效":"需要核查":null}/>{compiled&&<><Fact label="准备时联系人" value={compiled.contact.contact_id}/><Fact label="准备时职责" value={compiled.contact.responsibility}/><Fact label="准备时有效期限" value={compiled.contact.valid_from+" 至 "+compiled.contact.valid_until}/></>}{compiled?.responsibility_history?.map((value,index)=><div className="boss-workspace-item" key={value.contact_id+value.valid_from+index}><strong>{value.organization} · {value.responsibility}</strong><p>{value.valid_from} 至 {value.valid_until}</p>{sourceButtons(value.source_refs)}</div>)}{!compiled?.responsibility_history&&<p className="boss-helper">完整职责变更记录尚未提供。</p>}</Panel>
      <Panel title="状态与核查"><Fact label="材料编号" value={selected?.brief_id}/><Fact label="材料版本" value={selected?.version}/><Fact label="材料状态" value={selected?.state}/><Fact label="来源与工作事实" value={selected?selected.live_evidence_current?"当前有效":"需要重新核查":null}/><Fact label="准备时间" value={time(selected?.prepared_at)}/><Fact label="业务时间" value={time(current?.business_clock)}/>{compiled?.missing_items?.map(value=><p className="boss-helper" key={value}>{value}</p>)}{!compiled?.missing_items&&<p className="boss-helper">完整材料缺口尚未提供。</p>}{transaction.recovery}</Panel>
    </aside></div>
    <footer className="boss-people-footer boss-actions"><button type="button" className="boss-btn boss-btn-primary" disabled={disabled||linked||!contactCurrent} onClick={prepare}><ClipboardCheck size={15}/>准备材料</button><button type="button" className="boss-btn" disabled={!source?.excerpt||!selected?.live_evidence_current||transaction.busy} onClick={openSource}><FileSearch size={15}/>打开原文</button><button type="button" className="boss-btn" disabled={disabled||!canAttach} onClick={attach}><ShieldCheck size={15}/>加入会议</button><button type="button" className="boss-btn" onClick={()=>onNavigate("N04")}>返回会议与资料</button></footer>
    {transaction.dialog}
    <Dialog.Root open={nextBrief!==null} onOpenChange={open=>{if(!open)setNextBrief(null);}}><Dialog.Portal><Dialog.Overlay className="boss-v7-dialog-overlay"/><Dialog.Content className="boss-v7-dialog"><Dialog.Title>当前材料存在未保存编辑</Dialog.Title><Dialog.Description>可以继续编辑，或者放弃本次尚未保存内容并选择其他会面材料。</Dialog.Description><div className="boss-actions"><Dialog.Close asChild><button type="button" className="boss-btn">继续编辑</button></Dialog.Close><button type="button" className="boss-btn" disabled={transaction.busy||!current} onClick={()=>{if(nextBrief!==null)select(nextBrief);}}>放弃编辑并切换材料</button></div></Dialog.Content></Dialog.Portal></Dialog.Root>
  </div>;
}
