import {useEffect, useState} from "react";

type SourceRef={source_id:string;version:string};
type Details={purpose:string;starts_at:string;ends_at:string;timezone:string;preparation_due_at:string|null;participant_ids:string[];source_refs:SourceRef[]};
type Meeting={meeting_id:string;owner_id:string;version:string;state:string;purpose?:string;starts_at:string;ends_at:string|null;timezone:string;preparation_due_at:string|null;participant_ids:string[];material_ids:string[]};
type Draft={meeting_id:string;meeting_version:string;version:string;state:string;details:Details;review_sha256:string;review_current:boolean;
  impact:{private_calendar:{version:string;conflict:boolean};overlapping_travel_ids:string[];preparation_deadline_known:boolean;requires_owner_acknowledgement:boolean}};
export type MeetingArrangementProjection={source_type:"SIMULATED";meeting:Meeting;draft:Draft|null;
  contacts:{contact_id:string;name:string;organization:string;responsibility:string}[];
  sources:{source_id:string;version:string;withdrawn:boolean}[];revisions:{version:string;state:string}[];business_at:string;invitation_sent:false};
type Props={data:MeetingArrangementProjection|null;loading:boolean;error:string;onReload:()=>void;
  onCommand:(action:string,payload:Record<string,unknown>)=>Promise<void>;onDirtyChange:(dirty:boolean)=>void};
type Request={action:string;payload:Record<string,unknown>};
const stateText:Record<string,string>={DRAFT:"草稿",SCHEDULED:"已安排",HELD:"已确认举行",CANCELED:"已取消",CONFIRMED:"已确认"};

export function BossMeetingArrangement({data,loading,error,onReload,onCommand,onDirtyChange}:Props){
  const [form,setForm]=useState<Details|null>(null);
  const [dirty,setDirty]=useState(false);
  const [reason,setReason]=useState("");
  const [approved,setApproved]=useState(false);
  const [acknowledged,setAcknowledged]=useState(false);
  const [confirmation,setConfirmation]=useState<"confirm"|"cancel"|"held"|null>(null);
  const [pending,setPending]=useState<Request|null>(null);
  const [busy,setBusy]=useState(false);
  const [failure,setFailure]=useState("");
  const [notice,setNotice]=useState("");
  function load(current:MeetingArrangementProjection){
    const draft=current.draft?.state==="DRAFT"?current.draft.details:null;
    setForm(draft||{purpose:current.meeting.purpose||"",starts_at:current.meeting.starts_at,ends_at:current.meeting.ends_at||"",
      timezone:current.meeting.timezone,preparation_due_at:current.meeting.preparation_due_at,
      participant_ids:current.meeting.participant_ids,
      source_refs:current.sources.filter(source=>current.meeting.material_ids.includes(source.source_id)).map(({source_id,version})=>({source_id,version}))});
    setDirty(false);onDirtyChange(false);
  }
  useEffect(()=>{if(data&&!dirty&&!pending)load(data);},[data]);
  function change(values:Partial<Details>){
    if(!form)return;
    setForm({...form,...values});setDirty(true);onDirtyChange(true);setNotice("");
  }
  async function run(request:Request){
    if(busy)return;
    setPending(request);setBusy(true);setFailure("");
    await onCommand(request.action,request.payload).then(()=>{
      setPending(null);setBusy(false);setConfirmation(null);setApproved(false);setAcknowledged(false);
      setDirty(false);onDirtyChange(false);setNotice("本次结果已保存，可以重新读取当前安排。");onReload();
    },(failure:unknown)=>{setBusy(false);setFailure(String(failure));});
  }
  function save(){
    if(!data||!form)return;
    void run({action:"boss.meeting.draft.save",payload:{client_request_id:"meeting-"+crypto.randomUUID(),
      meeting_id:data.meeting.meeting_id,meeting_version:data.meeting.version,expected_version:data.draft?.version||"0",...form}});
  }
  function submit(){
    if(!data||!confirmation||!approved)return;
    const payload=confirmation==="confirm"?{meeting_id:data.meeting.meeting_id,meeting_version:data.meeting.version,
      draft_version:data.draft?.version,review_sha256:data.draft?.review_sha256,acknowledge_conflict:acknowledged}:
      {meeting_id:data.meeting.meeting_id,expected_version:data.meeting.version,reason};
    void run({action:"boss.meeting."+confirmation,payload:{client_request_id:"meeting-"+crypto.randomUUID(),...payload}});
  }
  const terminal=Boolean(data&&["HELD","CANCELED"].includes(data.meeting.state));
  const disabled=busy||Boolean(pending)||terminal;
  return <section className="boss-panel">
    <div className="boss-panel-head"><h2>本人会议安排</h2><small>SIMULATED · 当前业务时间 {data?.business_at||"待读取"}</small></div>
    <button className="boss-btn" type="button" disabled={loading||busy} onClick={onReload}>读取会议与核查结果</button>
    {loading&&<p role="status">正在读取会议安排</p>}
    {(error||failure)&&<p className="boss-status boss-status-error" role="alert">{error||failure}</p>}
    {notice&&<p role="status">{notice}</p>}
    {pending&&!busy&&<div className="boss-status" role="status"><p>当前请求编号：{String(pending.payload.client_request_id)}</p>
      <button className="boss-btn" type="button" onClick={()=>void run(pending)}>查询并继续当前请求</button></div>}
    {data&&<>
      <div className="boss-kv"><span>当前会议</span><strong>{data.meeting.meeting_id} · v{data.meeting.version} · {stateText[data.meeting.state]||data.meeting.state}</strong></div>
      <p>当前开始：{data.meeting.starts_at}；结束：{data.meeting.ends_at||"尚未提供"}；时区：{data.meeting.timezone}</p>
      <p>准备期限：{data.meeting.preparation_due_at||"尚未提供"}。参会对象接受邀请的状态尚未验证。</p>
      {form&&<fieldset disabled={disabled}>
        <label className="boss-field">会议目的<textarea maxLength={1200} value={form.purpose} onChange={event=>change({purpose:event.target.value})}/></label>
        <label className="boss-field">开始时间（保留UTC时差）<input value={form.starts_at} onChange={event=>change({starts_at:event.target.value})}/></label>
        <label className="boss-field">结束时间（保留UTC时差）<input value={form.ends_at} onChange={event=>change({ends_at:event.target.value})}/></label>
        <label className="boss-field">IANA时区<input value={form.timezone} onChange={event=>change({timezone:event.target.value})}/></label>
        <label className="boss-field">准备期限（可以留空，保留UTC时差）<input value={form.preparation_due_at||""} onChange={event=>change({preparation_due_at:event.target.value||null})}/></label>
        <p>参会对象</p>{data.contacts.map(contact=><label className="boss-confirm-check" key={contact.contact_id}>
          <input type="checkbox" checked={form.participant_ids.includes(contact.contact_id)} onChange={event=>change({participant_ids:event.target.checked?[...form.participant_ids,contact.contact_id]:form.participant_ids.filter(id=>id!==contact.contact_id)})}/>
          {contact.name} · {contact.organization} · {contact.responsibility} · {contact.contact_id}</label>)}
        <p>会议材料</p>{data.sources.map(source=><label className="boss-confirm-check" key={source.source_id}>
          <input type="checkbox" disabled={source.withdrawn&&!form.source_refs.some(ref=>ref.source_id===source.source_id)} checked={form.source_refs.some(ref=>ref.source_id===source.source_id)} onChange={event=>change({source_refs:event.target.checked?[...form.source_refs,{source_id:source.source_id,version:source.version}]:form.source_refs.filter(ref=>ref.source_id!==source.source_id)})}/>
          {source.source_id} · v{source.version} · {source.withdrawn?"已撤销":"当前资料"}</label>)}
        <button className="boss-btn" type="button" disabled={!form.purpose||!form.starts_at||!form.ends_at||!form.participant_ids.length} onClick={save}>保存草稿并核查影响</button>
      </fieldset>}
      {data.draft&&<article className="boss-workspace-item"><h3>保存的会议草稿 · v{data.draft.version}</h3>
        <p>{stateText[data.draft.state]||data.draft.state} · {data.draft.review_current?"核查结果与当前资料一致":"需要重新保存并核查"}</p>
        <p>{data.draft.details.purpose}</p><p>{data.draft.details.starts_at} 至 {data.draft.details.ends_at} · {data.draft.details.timezone}</p>
        <p>私人占用冲突：{data.draft.impact.private_calendar.conflict?"存在":"当前未发现"}；关联行程：{data.draft.impact.overlapping_travel_ids.join("、")||"当前未发现"}</p>
        <p>准备期限：{data.draft.details.preparation_due_at||"尚未提供"}。确认后相关旧材料需要复核。</p></article>}
      <div className="boss-actions">{(["confirm","cancel","held"] as const).map(action=><button className="boss-btn" type="button" key={action}
        disabled={disabled||dirty||(action==="confirm"&&!data.draft?.review_current)||(action==="held"&&data.meeting.state!=="SCHEDULED")}
        onClick={()=>{setConfirmation(action);setApproved(false);setAcknowledged(false);setReason("");}}>{{confirm:"确认当前草稿",cancel:"取消当前会议",held:"确认会议已经举行"}[action]}</button>)}</div>
      {confirmation&&<fieldset disabled={busy||Boolean(pending)}><legend>本人确认本次操作</legend>
        <p>会议 {data.meeting.meeting_id} · 当前版本 {data.meeting.version}。历史交办和消息继续保留。</p>
        {confirmation==="confirm"?<label className="boss-confirm-check"><input type="checkbox" checked={acknowledged} onChange={event=>setAcknowledged(event.target.checked)}/>本人已核查保存草稿中的时间、参会范围、材料及安排冲突</label>:
          <label className="boss-field">本次决定依据<textarea maxLength={1200} value={reason} onChange={event=>setReason(event.target.value)}/></label>}
        <label className="boss-confirm-check"><input type="checkbox" checked={approved} onChange={event=>setApproved(event.target.checked)}/>本人授权本次操作</label>
        <button className="boss-btn boss-btn-primary" type="button" disabled={!approved||(confirmation==="confirm"?!acknowledged:!reason.trim())} onClick={submit}>提交本人决定</button>
        <button className="boss-btn" type="button" onClick={()=>setConfirmation(null)}>继续查看会议</button>
      </fieldset>}
      <p className="boss-helper">保存草稿不会改变当前安排。确认、取消和举行分别记录；外部日历更新与邀请发送尚未执行。</p>
    </>}
  </section>;
}
