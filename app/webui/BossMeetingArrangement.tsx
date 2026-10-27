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
function changes(details:Details,meeting:Meeting){
  const rows:string[]=[];
  if((meeting.purpose??"")!==details.purpose)rows.push("会议目的");
  if(meeting.starts_at!==details.starts_at)rows.push("开始时间");
  if((meeting.ends_at??"")!==details.ends_at)rows.push("结束时间");
  if(meeting.timezone!==details.timezone)rows.push("IANA时区");
  if((meeting.preparation_due_at??"")!==(details.preparation_due_at??""))rows.push("准备期限");
  if(meeting.participant_ids.slice().sort().join(",")!==details.participant_ids.slice().sort().join(","))rows.push("参会联系人");
  if(meeting.material_ids.slice().sort().join(",")!==details.source_refs.map(ref=>ref.source_id).sort().join(","))rows.push("会议材料");
  return rows;
}
export function BossMeetingArrangement({data,loading,error,onReload,onDirtyChange,otherBusy}:Props){
  const [form,setForm]=useState<Details|null>(null),[basis,setBasis]=useState("");
  const [dirty,setDirty]=useState(false),dirtyRef=useRef(false),[reason,setReason]=useState("");
  const [acknowledged,setAcknowledged]=useState(false),[confirmation,setConfirmation]=useState<"confirm"|"cancel"|"held"|null>(null);
  const [failure,setFailure]=useState(""),[editing,setEditing]=useState(false),[discardOpen,setDiscardOpen]=useState(false);
  const transaction=useTransaction(recorded=>{if(recorded){dirtyRef.current=false;setDirty(false);setReason("");setConfirmation(null);setAcknowledged(false);setForm(null);setBasis("");setEditing(false);setDiscardOpen(false);}onReload();},undefined,undefined,"meetingArrangement");
  const current=!loading&&!error?data:null,edited=dirty||Boolean(reason.trim())||confirmation!==null;
  dirtyRef.current=edited;
  function load(value:MeetingArrangementProjection){
    const draft=value.draft?.state==="DRAFT"?value.draft.details:null;
    setForm(draft??{purpose:value.meeting.purpose??"",starts_at:value.meeting.starts_at,ends_at:value.meeting.ends_at??"",timezone:value.meeting.timezone,preparation_due_at:value.meeting.preparation_due_at,participant_ids:value.meeting.participant_ids,source_refs:value.sources.filter(source=>value.meeting.material_ids.includes(source.source_id)).map(({source_id,version})=>({source_id,version}))});
    setBasis(signature(value));setDirty(false);dirtyRef.current=false;setReason("");setConfirmation(null);setAcknowledged(false);setFailure("");setDiscardOpen(false);
  }
  useEffect(()=>{if(current&&!dirtyRef.current&&!transaction.busy)load(current);},[current]);
  useEffect(()=>{onDirtyChange(edited||transaction.busy);return()=>onDirtyChange(false);},[edited,transaction.busy,onDirtyChange]);
  const stale=Boolean(current&&basis&&signature(current)!==basis),terminal=Boolean(current&&["HELD","CANCELED"].includes(current.meeting.state));
  const disabled=!current||!form||!basis||stale||terminal||transaction.busy||otherBusy;
  const openEditor=editing||edited;
  const draftReady=Boolean(current?.draft&&current.draft.state==="DRAFT"&&current.draft.review_current),confirmedDraft=Boolean(current?.draft&&current.draft.state==="CONFIRMED");
  const started=Boolean(current&&Number.isFinite(Date.parse(current.meeting.starts_at))&&Date.parse(current.meeting.starts_at)<=Date.parse(current.business_at));
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
      if(confirmation==="held"&&(current.meeting.state!=="SCHEDULED"||!started))return;
      transaction.propose(confirmation==="cancel"?"boss.meeting.cancel":"boss.meeting.held",{meeting_id:current.meeting.meeting_id,expected_version:current.meeting.version,reason:reason.trim()},confirmation==="cancel"?"取消当前会议":"确认会议已经举行",confirmation==="cancel"?["会议："+current.meeting.meeting_id+" · v"+current.meeting.version,"当前状态："+(STATES[current.meeting.state]??current.meeting.state),"本人依据："+reason.trim(),"已选会议材料："+(current.meeting.material_ids.join("、")||"未选择"),"关联行程："+(current.draft?.impact.overlapping_travel_ids.join("、")||"当前未返回"),"外部邀请："+(current.invitation_sent?"当前记录为已经发送":"当前记录为尚未发送"),"会议状态单独记录，历史材料、交办与消息继续保留。"]:["会议："+current.meeting.meeting_id+" · v"+current.meeting.version,"当前状态："+(STATES[current.meeting.state]??current.meeting.state),"本人依据："+reason.trim(),"已选会议材料："+(current.meeting.material_ids.join("、")||"未选择"),"会议状态单独记录，历史材料、交办与消息继续保留。"]);
    }
  }
  const saveReason=!current?"会议安排尚未读取":terminal?"当前会议已经举行或取消，不能再修改安排":stale?"会议或核查依据已经变化，请放弃本次修改后重新核查":!dirty?"当前没有待保存的修改":transaction.busy||otherBusy?"正在处理其他操作，请稍后再保存":"";
  const confirmReason=!current?"会议安排尚未读取":terminal?"当前会议已经举行或取消，不能再确认安排":!current.draft?"当前没有已保存的会议安排草稿，请先保存安排草稿":current.draft.state!=="DRAFT"?"已保存草稿不是待确认版本，请重新保存安排草稿":!current.draft.review_current?"已保存草稿的核查依据已经变化，请重新保存安排草稿":stale?"会议或核查依据已经变化，请放弃本次修改后重新核查":dirty?"存在未保存修改，请先保存安排草稿":transaction.busy||otherBusy?"正在处理其他操作，请稍后再确认":"";
  const heldReason=!current?"会议安排尚未读取":!started?"会议开始时间尚未到达，当前业务时间为"+current.business_at:stale?"会议或核查依据已经变化，请放弃本次修改后重新核查":transaction.busy||otherBusy?"正在处理其他操作，请稍后再记录":"";
  const editReason=!current?"会议安排尚未读取":terminal?"当前会议已经举行或取消，不能再修改安排":transaction.busy||otherBusy?"正在处理其他操作，请稍后再编辑":"";
  const participantNames=(ids:string[])=>ids.map(id=>{const contact=current?.contacts.find(value=>value.contact_id===id);return contact?contact.name:id;}).join("、")||"尚未提供";
  return <div className="boss-meeting-arrangement">
    <div className="boss-panel-head"><h3>会议安排</h3><button type="button" className="boss-btn" disabled={Boolean(editReason)||edited} onClick={()=>setEditing(value=>!value)}>{openEditor?"收起编辑":"编辑会议安排"}</button></div>
    {loading&&<p role="status">正在读取当前会议安排…</p>}{(error||failure)&&<p role="alert" className="boss-status boss-status-error">{error||failure}</p>}{transaction.notice&&<p role="status" className="boss-status boss-status-ok">{transaction.notice}</p>}
    {stale&&<p role="alert" className="boss-status boss-status-warn">会议或核查依据已经变化，编辑内容已保留。请放弃本次修改后重新核查版本。</p>}
    {!loading&&editReason&&!openEditor&&<p className="boss-helper">{editReason}</p>}
    {edited&&<p className="boss-helper">编辑中：保存安排草稿或放弃本次修改后返回会议安排摘要。</p>}
    {current&&<div className="boss-v7-equal-columns">
      <div className="boss-kv"><span>会议状态</span><strong>{STATES[current.meeting.state]??current.meeting.state}</strong></div>
      <div className="boss-kv"><span>会议版本</span><strong>v{current.meeting.version}</strong></div>
      <div className="boss-kv"><span>开始时间</span><strong>{current.meeting.starts_at}</strong></div>
      <div className="boss-kv"><span>结束时间</span><strong>{current.meeting.ends_at??"尚未提供"}</strong></div>
      <div className="boss-kv"><span>IANA时区</span><strong>{current.meeting.timezone}</strong></div>
      <div className="boss-kv"><span>准备期限</span><strong>{current.meeting.preparation_due_at??"尚未提供"}</strong></div>
      <div className="boss-kv"><span>参会联系人</span><strong>{participantNames(current.meeting.participant_ids)}</strong></div>
      <div className="boss-kv"><span>会议材料</span><strong>{current.meeting.material_ids.join("、")||"尚未选择"}</strong></div>
    </div>}
    {current&&<p className="boss-helper">会议目的：{current.meeting.purpose||"尚未提供"}</p>}
    {openEditor&&form&&<fieldset disabled={disabled||confirmation!==null} className="boss-meeting-form"><label className="boss-meeting-wide">会议目的<textarea maxLength={1200} value={form.purpose} onChange={event=>change({purpose:event.target.value})}/></label><label>开始时间（含UTC时差）<input value={form.starts_at} onChange={event=>change({starts_at:event.target.value})}/></label><label>结束时间（含UTC时差）<input value={form.ends_at} onChange={event=>change({ends_at:event.target.value})}/></label><label>IANA时区<input value={form.timezone} onChange={event=>change({timezone:event.target.value})}/></label><label>准备期限（含UTC时差）<input value={form.preparation_due_at??""} onChange={event=>change({preparation_due_at:event.target.value||null})}/></label><div><h4>参会联系人</h4>{current?.contacts.map(contact=><label className="boss-confirm-check" key={contact.contact_id}><input type="checkbox" checked={form.participant_ids.includes(contact.contact_id)} onChange={event=>change({participant_ids:event.target.checked?[...form.participant_ids,contact.contact_id]:form.participant_ids.filter(id=>id!==contact.contact_id)})}/>{contact.name} · {contact.organization} · {contact.responsibility}</label>)}</div><div><h4>会议材料</h4>{current?.sources.map(source=>{const selected=form.source_refs.find(ref=>ref.source_id===source.source_id);return <label className="boss-confirm-check" key={source.source_id}><input type="checkbox" checked={Boolean(selected)} disabled={source.withdrawn&&!selected} onChange={event=>change({source_refs:event.target.checked?[...form.source_refs,{source_id:source.source_id,version:source.version}]:form.source_refs.filter(ref=>ref.source_id!==source.source_id)})}/>{source.source_id} · 当前v{source.version}{selected?" · 已选v"+selected.version:""} · {source.withdrawn?"已撤销":"待逐项核查"}</label>;})}</div></fieldset>}
    {openEditor&&<div className="boss-actions"><button type="button" className="boss-btn boss-btn-primary" disabled={disabled||confirmation!==null} onClick={save}>保存安排草稿</button>{edited?<button type="button" className="boss-btn" disabled={!current||transaction.busy||otherBusy} onClick={()=>setDiscardOpen(true)}>放弃本次修改</button>:null}</div>}
    {(openEditor&&(saveReason||(dirty&&!discardOpen)))&&<p className="boss-helper">{dirty&&!discardOpen?"当前修改尚未保存，保存后才会核查会议影响。":saveReason}</p>}
    {discardOpen&&<div className="boss-actions"><span className="boss-helper">放弃本次修改将恢复已保存的会议安排{current?.draft?"（草稿v"+current.draft.version+"）":"（会议v"+(current?.meeting.version??"")+"）"}，未经确认不会清空编辑。</span><button type="button" className="boss-btn" disabled={!current||transaction.busy||otherBusy} onClick={()=>{if(current)load(current);setEditing(false);setDiscardOpen(false);}}>确认放弃</button><button type="button" className="boss-btn" onClick={()=>setDiscardOpen(false)}>继续编辑</button></div>}
    {current?.draft&&<article className="boss-workspace-item"><h4>已保存草稿 · v{current.draft.version}</h4><p>{STATES[current.draft.state]??current.draft.state} · {current.draft.review_current?"当前依据已经核查":"需要重新保存核查"}</p><p>{current.draft.details.purpose}</p><p>{current.draft.details.starts_at} 至 {current.draft.details.ends_at} · {current.draft.details.timezone}</p><p>私人占用冲突：{current.draft.impact.private_calendar.conflict?"存在":"当前未发现"}；关联行程：{current.draft.impact.overlapping_travel_ids.join("、")||"当前未发现"}</p><p>准备期限：{current.draft.details.preparation_due_at??"尚未提供"}</p></article>}
    {current&&!terminal&&!confirmedDraft&&<div className="boss-actions"><button type="button" className={"boss-btn"+(draftReady&&current.meeting.state!=="SCHEDULED"?" boss-btn-primary":"")} disabled={disabled||dirty||!draftReady} onClick={()=>{setConfirmation("confirm");setReason("");setAcknowledged(false);}}>确认会议安排</button>{current.meeting.state==="SCHEDULED"&&<button type="button" className={"boss-btn"+(started?" boss-btn-primary":"")} disabled={disabled||dirty||!started} onClick={()=>{setConfirmation("held");setReason("");setAcknowledged(false);}}>记录会议已举行</button>}</div>}
    {current&&!terminal&&confirmedDraft&&<p className="boss-helper">当前会议安排已经确认（草稿v{current.draft?.version}）；如需调整，请重新保存安排草稿。</p>}
    {current&&!terminal&&!confirmedDraft&&(disabled||dirty||!draftReady)&&<p className="boss-helper">{confirmReason}</p>}
    {current&&current.meeting.state==="SCHEDULED"&&(disabled||dirty||!started)&&<p className="boss-helper">{heldReason}</p>}
    {current&&!terminal&&<details><summary>更多操作</summary><div className="boss-actions"><button type="button" className="boss-btn" disabled={disabled||dirty} onClick={()=>{setConfirmation("cancel");setReason("");setAcknowledged(false);}}>取消会议</button></div><p className="boss-helper">取消会议是危险操作：影响的准备事项、已选会议材料与关联行程会在确认卡中列出，会议状态单独记录，历史材料、交办与消息继续保留。</p></details>}
    {confirmation&&<fieldset className="boss-meeting-confirm" disabled={disabled}><legend>核查本次决定</legend><p>会议 {current?.meeting.meeting_id} · 当前版本 {current?.meeting.version}</p>
      {confirmation==="confirm"&&current?.draft?<>
        <p className="boss-helper">待确认草稿：v{current.draft.version} · 安排时间 {current.draft.details.starts_at} 至 {current.draft.details.ends_at} · {current.draft.details.timezone}</p>
        <p className="boss-helper">与当前已保存安排的差异：{changes(current.draft.details,current.meeting).join("、")||"未观察到字段变化"}</p>
        <p className="boss-helper">参会联系人：{participantNames(current.draft.details.participant_ids)}；准备期限：{current.draft.details.preparation_due_at??"尚未指定"}</p>
        <p className="boss-helper">采用资料：{current.draft.details.source_refs.map(ref=>ref.source_id+" · v"+ref.version).join("、")||"尚未选择"}</p>
        <p className="boss-helper">安排冲突：私人占用{current.draft.impact.private_calendar.conflict?"存在":"当前未发现"}；关联行程{current.draft.impact.overlapping_travel_ids.join("、")||"当前未发现"}</p>
        <label className="boss-confirm-check"><input type="checkbox" checked={acknowledged} onChange={event=>setAcknowledged(event.target.checked)}/>本人已核查已保存草稿中的时间、参会范围、材料与安排冲突</label>
      </>:null}
      {confirmation==="cancel"&&<><p className="boss-helper">影响的准备与行程：准备期限{current?.meeting.preparation_due_at??"尚未提供"}；已选会议材料{current?.meeting.material_ids.length??0}份；关联行程{current?.draft?.impact.overlapping_travel_ids.join("、")||"当前未返回"}；外部邀请{current?.invitation_sent?"当前记录为已经发送":"当前记录为尚未发送"}。</p><label>本次决定依据<textarea maxLength={1200} value={reason} onChange={event=>setReason(event.target.value)}/></label></>}
      {confirmation==="held"&&<><p className="boss-helper">记录会议已举行只改变会议状态；不会自动确认纪要、创建交办或发送消息。</p><label>本次决定依据<textarea maxLength={1200} value={reason} onChange={event=>setReason(event.target.value)}/></label></>}
      <div className="boss-actions"><button className="boss-btn boss-btn-primary" type="button" disabled={confirmation==="confirm"?!acknowledged:!reason.trim()} onClick={submit}>核查并提交本人决定</button><button className="boss-btn" type="button" onClick={()=>{setConfirmation(null);setReason("");setAcknowledged(false);}}>取消本次编辑</button></div></fieldset>}
    {transaction.recovery}{transaction.dialog}
    <p className="boss-helper">保存草稿、确认安排和记录会议举行分别记录。外部日历与邀请发送状态需要单独核查。</p>
  </div>;
}
