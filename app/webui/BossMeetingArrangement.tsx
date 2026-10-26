import {useEffect,useRef,useState} from "react";
import {useTransaction} from "./BossAssignmentFlow";

type SourceRef={source_id:string;version:string};
type Details={purpose:string;starts_at:string;ends_at:string;timezone:string;preparation_due_at:string|null;participant_ids:string[];source_refs:SourceRef[]};
type Meeting={meeting_id:string;owner_id:string;version:string;state:string;purpose?:string;starts_at:string;ends_at:string|null;timezone:string;preparation_due_at:string|null;participant_ids:string[];material_ids:string[]};
type Draft={meeting_id:string;meeting_version:string;version:string;state:string;details:Details;review_sha256:string;review_current:boolean;impact:{private_calendar:{version:string;conflict:boolean};overlapping_travel_ids:string[];preparation_deadline_known:boolean;requires_owner_acknowledgement:boolean}};
export type MeetingArrangementProjection={source_type:"SIMULATED";execution_namespace?:string;meeting:Meeting;draft:Draft|null;contacts:{contact_id:string;name:string;organization:string;responsibility:string}[];sources:{source_id:string;version:string;withdrawn:boolean}[];revisions:{version:string;state:string}[];business_at:string;invitation_sent:false};
type Props={data:MeetingArrangementProjection|null;loading:boolean;error:string;onReload:()=>void;onDirtyChange:(dirty:boolean)=>void;otherBusy:boolean};
const STATES:Record<string,string>={DRAFT:"草稿",SCHEDULED:"已安排",HELD:"已确认举行",CANCELED:"已取消",CONFIRMED:"已确认"};
function signature(value:MeetingArrangementProjection){return JSON.stringify([value.execution_namespace,value.meeting,value.draft,value.contacts,value.sources]);}
export function BossMeetingArrangement({data,loading,error,onReload,onDirtyChange,otherBusy}:Props){
  const [form,setForm]=useState<Details|null>(null),[basis,setBasis]=useState("");
  const [dirty,setDirty]=useState(false),dirtyRef=useRef(false),[reason,setReason]=useState("");
  const [acknowledged,setAcknowledged]=useState(false),[confirmation,setConfirmation]=useState<"confirm"|"cancel"|"held"|null>(null);
  const [failure,setFailure]=useState("");
  const transaction=useTransaction(recorded=>{if(recorded){dirtyRef.current=false;setDirty(false);setReason("");setConfirmation(null);setAcknowledged(false);setForm(null);setBasis("");}onReload();},undefined,undefined,"meetingArrangement");
  const current=!loading&&!error?data:null,edited=dirty||Boolean(reason.trim())||confirmation!==null;
  dirtyRef.current=edited;
  function load(value:MeetingArrangementProjection){
    const draft=value.draft?.state==="DRAFT"?value.draft.details:null;
    setForm(draft??{purpose:value.meeting.purpose??"",starts_at:value.meeting.starts_at,ends_at:value.meeting.ends_at??"",timezone:value.meeting.timezone,preparation_due_at:value.meeting.preparation_due_at,participant_ids:value.meeting.participant_ids,source_refs:value.sources.filter(source=>value.meeting.material_ids.includes(source.source_id)).map(({source_id,version})=>({source_id,version}))});
    setBasis(signature(value));setDirty(false);dirtyRef.current=false;setReason("");setConfirmation(null);setAcknowledged(false);setFailure("");
  }
  useEffect(()=>{if(current&&!dirtyRef.current&&!transaction.busy)load(current);},[current]);
  useEffect(()=>{onDirtyChange(edited||transaction.busy);return()=>onDirtyChange(false);},[edited,transaction.busy,onDirtyChange]);
  const stale=Boolean(current&&basis&&signature(current)!==basis),terminal=Boolean(current&&["HELD","CANCELED"].includes(current.meeting.state));
  const disabled=!current||!form||!basis||stale||terminal||transaction.busy||otherBusy;
  function change(values:Partial<Details>){if(!form||disabled)return;setForm({...form,...values});setDirty(true);dirtyRef.current=true;setFailure("");}
  function save(){
    if(disabled||!current||!form)return;setFailure("");
    if(!form.purpose.trim()||!form.participant_ids.length){setFailure("请填写会议目的并选择参会联系人");return;}
    const start=Date.parse(form.starts_at),end=Date.parse(form.ends_at),clock=Date.parse(current.business_at),due=form.preparation_due_at?Date.parse(form.preparation_due_at):null;
    if(!Number.isFinite(start)||!Number.isFinite(end)||start<clock||end<=start||end-start>31*86400000||due!==null&&(!Number.isFinite(due)||due<clock||due>start)){setFailure("请核查会议开始、结束和准备期限；需要保留日期、时间与UTC时差");return;}
    if(!form.timezone.trim()){setFailure("请提供会议采用的IANA时区");return;}
    if(form.source_refs.length>8||form.source_refs.some(ref=>!current.sources.some(source=>source.source_id===ref.source_id&&source.version===ref.version&&!source.withdrawn))){setFailure("请选择最多8份当前有效版本的会议材料");return;}
    transaction.propose("boss.meeting.draft.save",{meeting_id:current.meeting.meeting_id,meeting_version:current.meeting.version,expected_version:current.draft?.version??"0",...form,purpose:form.purpose.trim()},"保存会议草稿并核查影响",["会议："+current.meeting.meeting_id+" · v"+current.meeting.version,"目的："+form.purpose.trim(),"时间："+form.starts_at+" 至 "+form.ends_at+" · "+form.timezone,"准备期限："+(form.preparation_due_at??"未指定"),"参会联系人："+form.participant_ids.join("、"),"资料版本："+(form.source_refs.map(ref=>ref.source_id+" · v"+ref.version).join("、")||"未选择"),"保存草稿和影响核查结果，正式会议安排由本人另行确认。"]);
  }
  function submit(){
    if(disabled||!current||!confirmation||dirty)return;setFailure("");
    if(confirmation==="confirm"){
      if(!current.draft?.review_current||current.draft.state!=="DRAFT"||!acknowledged)return;
      transaction.propose("boss.meeting.confirm",{meeting_id:current.meeting.meeting_id,meeting_version:current.meeting.version,draft_version:current.draft.version,review_sha256:current.draft.review_sha256,acknowledge_conflict:acknowledged},"确认当前会议草稿",["会议："+current.meeting.meeting_id+" · v"+current.meeting.version,"草稿版本："+current.draft.version,"时间："+current.draft.details.starts_at+" 至 "+current.draft.details.ends_at+" · "+current.draft.details.timezone,"私人占用冲突："+(current.draft.impact.private_calendar.conflict?"存在":"当前未发现"),"关联行程："+(current.draft.impact.overlapping_travel_ids.join("、")||"当前未发现"),"本人已核查当前草稿中的参会范围、资料、期限和安排冲突。"]);
    }else{
      if(!reason.trim()){setFailure("请填写本次决定依据");return;}
      if(confirmation==="held"&&current.meeting.state!=="SCHEDULED")return;
      transaction.propose(confirmation==="cancel"?"boss.meeting.cancel":"boss.meeting.held",{meeting_id:current.meeting.meeting_id,expected_version:current.meeting.version,reason:reason.trim()},confirmation==="cancel"?"取消当前会议":"确认会议已经举行",["会议："+current.meeting.meeting_id+" · v"+current.meeting.version,"当前状态："+(STATES[current.meeting.state]??current.meeting.state),"本人依据："+reason.trim(),"会议状态单独记录，历史材料、交办与消息继续保留。"]);
    }
  }
  return <div className="boss-meeting-arrangement">
    <h3>编辑内容与说明</h3>
    {loading&&<p role="status">正在读取当前会议安排…</p>}{(error||failure)&&<p role="alert" className="boss-status boss-status-error">{error||failure}</p>}{transaction.notice&&<p role="status" className="boss-status boss-status-ok">{transaction.notice}</p>}
    {stale&&<p role="alert" className="boss-status boss-status-warn">会议或核查依据已经变化，编辑内容已保留。请恢复当前保存内容并核查版本。</p>}
    {form&&<fieldset disabled={disabled||confirmation!==null} className="boss-meeting-form"><label className="boss-meeting-wide">会议目的<textarea maxLength={1200} value={form.purpose} onChange={event=>change({purpose:event.target.value})}/></label><label>开始时间（含UTC时差）<input value={form.starts_at} onChange={event=>change({starts_at:event.target.value})}/></label><label>结束时间（含UTC时差）<input value={form.ends_at} onChange={event=>change({ends_at:event.target.value})}/></label><label>IANA时区<input value={form.timezone} onChange={event=>change({timezone:event.target.value})}/></label><label>准备期限（含UTC时差）<input value={form.preparation_due_at??""} onChange={event=>change({preparation_due_at:event.target.value||null})}/></label><div><h4>参会联系人</h4>{current?.contacts.map(contact=><label className="boss-confirm-check" key={contact.contact_id}><input type="checkbox" checked={form.participant_ids.includes(contact.contact_id)} onChange={event=>change({participant_ids:event.target.checked?[...form.participant_ids,contact.contact_id]:form.participant_ids.filter(id=>id!==contact.contact_id)})}/>{contact.name} · {contact.organization} · {contact.responsibility}</label>)}</div><div><h4>会议材料</h4>{current?.sources.map(source=>{const selected=form.source_refs.find(ref=>ref.source_id===source.source_id);return <label className="boss-confirm-check" key={source.source_id}><input type="checkbox" checked={Boolean(selected)} disabled={source.withdrawn&&!selected} onChange={event=>change({source_refs:event.target.checked?[...form.source_refs,{source_id:source.source_id,version:source.version}]:form.source_refs.filter(ref=>ref.source_id!==source.source_id)})}/>{source.source_id} · 当前v{source.version}{selected?" · 已选v"+selected.version:""} · {source.withdrawn?"已撤销":"待逐项核查"}</label>;})}</div></fieldset>}
    <div className="boss-actions"><button type="button" className="boss-btn" disabled={disabled||confirmation!==null} onClick={save}>保存草稿并核查影响</button><button type="button" className="boss-btn" disabled={!current||transaction.busy||otherBusy||(!edited&&!stale)} onClick={()=>{if(current)load(current);}}>恢复当前保存内容</button><button type="button" className="boss-btn" disabled={loading||transaction.busy||otherBusy} onClick={onReload}>重读会议安排</button></div>
    {current?.draft&&<article className="boss-workspace-item"><h4>已保存草稿 · v{current.draft.version}</h4><p>{STATES[current.draft.state]??current.draft.state} · {current.draft.review_current?"当前依据已经核查":"需要重新保存核查"}</p><p>{current.draft.details.purpose}</p><p>{current.draft.details.starts_at} 至 {current.draft.details.ends_at} · {current.draft.details.timezone}</p><p>私人占用冲突：{current.draft.impact.private_calendar.conflict?"存在":"当前未发现"}；关联行程：{current.draft.impact.overlapping_travel_ids.join("、")||"当前未发现"}</p><p>准备期限：{current.draft.details.preparation_due_at??"尚未提供"}</p></article>}
    <div className="boss-actions">{(["confirm","cancel","held"] as const).map(action=><button key={action} type="button" className="boss-btn" disabled={disabled||dirty||(action==="confirm"&&(!current?.draft?.review_current||current.draft.state!=="DRAFT"))||(action==="held"&&current?.meeting.state!=="SCHEDULED")} onClick={()=>{setConfirmation(action);setReason("");setAcknowledged(false);}}>{{confirm:"确认当前草稿",cancel:"取消当前会议",held:"确认会议已经举行"}[action]}</button>)}</div>
    {confirmation&&<fieldset className="boss-meeting-confirm" disabled={disabled}><legend>核查本次决定</legend><p>会议 {current?.meeting.meeting_id} · 当前版本 {current?.meeting.version}</p>{confirmation==="confirm"?<label className="boss-confirm-check"><input type="checkbox" checked={acknowledged} onChange={event=>setAcknowledged(event.target.checked)}/>本人已核查已保存草稿中的时间、参会范围、材料与安排冲突</label>:<label>本次决定依据<textarea maxLength={1200} value={reason} onChange={event=>setReason(event.target.value)}/></label>}<div className="boss-actions"><button className="boss-btn boss-btn-primary" type="button" disabled={confirmation==="confirm"?!acknowledged:!reason.trim()} onClick={submit}>核查并提交本人决定</button><button className="boss-btn" type="button" onClick={()=>{setConfirmation(null);setReason("");setAcknowledged(false);}}>取消本次编辑</button></div></fieldset>}
    {transaction.recovery}{transaction.dialog}
    <p className="boss-helper">保存草稿、确认安排和确认举行分别记录。外部日历与邀请发送状态需要单独核查。</p>
  </div>;
}
