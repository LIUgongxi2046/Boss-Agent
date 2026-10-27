import {useEffect,type ReactNode,useState} from "react";
import * as Dialog from "@radix-ui/react-dialog";
import type {AssignmentContext,AssignmentTask,TaskDueEvent,TaskFeedback,TaskLinkedMessage} from "./BossAssignmentFlow";
import type {AssignmentDraft} from "./BossAssignmentPicker";
import {BossAssignmentPreparation} from "./BossAssignmentPreparation";
import {V7Metric, V7Panel, V7Steps} from "./BossV7UI";

export type AssignmentExtensions={task_id:string;task_version:string;due_at:string;decisions:{decision_id:string;feedback_id:string;decision:"APPROVE"|"REJECT";old_due_at:string;new_due_at:string;reason:string|null;request_reason:string;decided_at:string;previous_task_version:string;task_version:string}[]};
type Props={rows:AssignmentTask[];selectedTaskId:string;current?:AssignmentTask;context:AssignmentContext|null;draft:AssignmentDraft;feedback:TaskFeedback[];messages:TaskLinkedMessage[];taskDue?:TaskDueEvent;extensions:AssignmentExtensions|null;extension?:TaskFeedback;completed?:TaskFeedback;clock?:string;overdue:boolean|null;sourceIds:string[];meetingId:string|null;eventIds:string[];editable:boolean;loading:boolean;stale:boolean;busy:boolean;morningBlocked:boolean;messagesEnabled:boolean;sourceReview?:ReactNode;conversation?:ReactNode;edit:(field:keyof AssignmentDraft,value:string)=>void;onSelect:(id:string)=>void;onSource:(id:string)=>void;onNavigate:(id:string)=>void;onNew:(task?:AssignmentTask)=>void;onDiscard:()=>void;onCoordinator:()=>void;onDue:()=>void;onMessages:()=>void;onCreate:()=>void;onSend:()=>void;onNudge:()=>void;onFollowup:()=>void;onComplete:()=>void;onExtend:(decision:"APPROVE"|"REJECT")=>void;onCancel:(reason:string)=>void};
type Difference={label:string;before:string;after:string};
const statusNames:Record<string,string>={OPEN:"尚未发送",WAITING_FEEDBACK:"等待反馈",IN_PROGRESS:"正在进行",RESULT_SUBMITTED:"已提交结果",COMPLETED_CONFIRMED:"本人已确认完成",CANCELED:"已取消"};
const feedbackNames:Record<string,string>={PROGRESS:"进展反馈",EXTENSION_REQUEST:"延期申请",RESULT_SUBMITTED:"结果提交"};
function Fact({label,children}:{label:string;children:ReactNode}){return <div className="boss-kv"><span>{label}</span><strong>{children??"尚未提供"}</strong></div>;}
function displayTime(value?:string){return value?value.replace("T"," "):"待核查";}
function newDueValid(value:string,clock?:string){
  if(!/^\d{4}-\d\d-\d\dT\d\d:\d\d(?::\d\d)?(?:Z|[+-]\d{2}:\d{2})$/.test(value))return false;
  if(!Number.isFinite(Date.parse(value))||!clock||!Number.isFinite(Date.parse(clock)))return false;
  return Date.parse(value)>Date.parse(clock);
}

export function BossAssignmentDetails(props:Props){
  const {rows,selectedTaskId,current,context,draft,feedback,messages,taskDue,extensions,extension,completed,clock,overdue,sourceIds,meetingId,eventIds,editable,loading,stale,busy,morningBlocked,messagesEnabled,edit}=props;
  const [evidenceOpen,setEvidenceOpen]=useState(true);
  const [discardMode,setDiscardMode]=useState<"edit"|"stale"|null>(null);
  const [cancelReason,setCancelReason]=useState("");
  useEffect(()=>{setEvidenceOpen(true);setCancelReason("");setDiscardMode(null);},[current?.task_id,current?.version]);
  const terminal=Boolean(current&&["CANCELED","COMPLETED_CONFIRMED"].includes(current.status));
  const missing=Boolean(selectedTaskId&&!current),canEdit=editable&&!missing;
  const sourceBlocked=Boolean(current&&current.source_reference_state!=="CURRENT");
  const currentSources=current?.source_refs??sourceIds;
  const contactText=(id?:string)=>{
    if(!id)return "尚未选择";
    const contact=context?.contacts.find(item=>item.contact_id===id);
    return contact?contact.name+" · "+contact.organization+" · "+contact.responsibility:id;
  };
  const completeReason=!current?"创建交办并取得结果后可以验收完成。":current.status!=="RESULT_SUBMITTED"?"当前状态尚不允许验收完成。":!completed?"负责人尚未提交含证据的结果，请先要求补充。":current.result_evidence_requires_resubmission?"结果证据已经变化，需要负责人重新提交。":current.source_reference_state!=="CURRENT"?"交办来源需要重新核查后才能验收。":null;
  const resultFeedback=feedback.filter(item=>item.kind==="RESULT_SUBMITTED");
  const missingCreate=[
    !draft.purpose.trim()?"目的":null,
    !draft.coordinator?"唯一负责人":null,
    !draft.due||!draft.timezone?"截止时间与时区":null,
    !draft.evidence.trim()?"验收依据":null,
  ].filter((value):value is string=>Boolean(value));
  const createReason=morningBlocked?"正在核查当前晨间事项与来源版本，暂不能创建交办。":!context?"尚未读取业务资料与联系人。":!sourceIds.length?"尚未取得获准来源。":missingCreate.length?"尚缺少："+missingCreate.join("、")+"。":null;
  const actionReason=(()=>{
    if(!current||terminal)return null;
    if(current.status==="RESULT_SUBMITTED"){
      if(completeReason)return completeReason;
      return draft.body.trim()?null:"填写补充材料请求正文后才能保存补材料草稿。";
    }
    if(sourceBlocked)return "当前任务来源已经变化，请先在来源与版本核查区确认后才能发送或催办。";
    if(!draft.body.trim())return current.status==="OPEN"?"填写模拟发送正文后才能发送。":"填写催办正文后才能准备催办。";
    return null;
  })();
  const approveReason=extension?(sourceBlocked?"批准延期前需要先确认当前任务来源。":!draft.newDue.trim()?"批准延期需要填写新的完整期限。":!newDueValid(draft.newDue,clock)?"新期限需要包含UTC时差，并且晚于当前业务时钟。":null):null;
  const draftBasisTask=(()=>{
    if(!draft.basis)return null;
    const value:unknown=JSON.parse(draft.basis);
    if(!Array.isArray(value)||value.length<3)return null;
    const task=value[2] as Partial<AssignmentTask>|null;
    return task&&typeof task.task_id==="string"?task as AssignmentTask:null;
  })();
  const basisDiff:Difference[]=(()=>{
    if(!stale)return [];
    const rows:Difference[]=[];
    if(draftBasisTask&&current){
      if((draftBasisTask.version??"")!==(current.version??""))rows.push({label:"任务版本",before:draftBasisTask.version??"待核查",after:current.version??"待核查"});
      if((draftBasisTask.status??"")!==(current.status??""))rows.push({label:"任务状态",before:statusNames[draftBasisTask.status]??draftBasisTask.status,after:statusNames[current.status]??current.status});
      if((draftBasisTask.purpose??"")!==(current.purpose??""))rows.push({label:"交办目的",before:draftBasisTask.purpose||"没有填写",after:current.purpose||"没有填写"});
      if((draftBasisTask.coordinator_id??"")!==(current.coordinator_id??""))rows.push({label:"唯一负责人",before:contactText(draftBasisTask.coordinator_id),after:contactText(current.coordinator_id)});
      if((draftBasisTask.due_at??"")!==(current.due_at??""))rows.push({label:"截止时间",before:displayTime(draftBasisTask.due_at),after:displayTime(current.due_at)});
      if((draftBasisTask.source_reference_state??"")!==(current.source_reference_state??""))rows.push({label:"来源核查状态",before:draftBasisTask.source_reference_state??"待核查",after:current.source_reference_state??"待核查"});
    }
    if(!rows.length)rows.push(draftBasisTask?{label:"草稿基线",before:"编辑时的任务与来源版本",after:"当前读取的任务与来源版本"}:{label:"草稿基线",before:"编辑时的来源与联系人资料",after:"当前读取的来源与联系人资料"});
    return rows;
  })();
  const flowSteps=[
    {title:"创建交办",description:current?"已创建 · 版本 "+(current.version??"待核查"):"创建记录不代表已经发送",state:current?"complete" as const:"waiting" as const},
    {title:"发送及送达",description:messages.length?"已记录 "+messages.length+" 条模拟发送；真实送达待查询":"等待真实发送记录查询",state:messages.length?"complete" as const:current?"current" as const:"waiting" as const},
    {title:"收到反馈",description:feedback.length?"已记录 "+feedback.length+" 条反馈":"尚未收到负责人反馈",state:feedback.length?"complete" as const:"waiting" as const},
    {title:"结果提交",description:completed?"已取得含证据的结果":resultFeedback.length?"已提交结果，证据待本人核查":"等待负责人提交结果与证据",state:completed?"complete" as const:resultFeedback.length?"current" as const:"waiting" as const},
    {title:"本人确认完成",description:current?.status==="COMPLETED_CONFIRMED"?"已经确认完成":current?.status==="CANCELED"?"交办已经取消，历史结果只读":"仅证据完整并由本人确认后完成",state:current?.status==="COMPLETED_CONFIRMED"?"complete" as const:"waiting" as const},
  ];
  return <>
    <div className="boss-assignment-toolbar"><label>当前任务<select value={selectedTaskId} disabled={loading||busy} onChange={event=>{if(event.target.value)props.onSelect(event.target.value);}}><option value="">请选择已保存的交办</option>{rows.map(task=><option key={task.task_id} value={task.task_id}>{task.purpose||task.task_id} · {statusNames[task.status]??task.status}</option>)}</select></label><button type="button" className="boss-btn" disabled={loading||busy} onClick={()=>props.onNew()}>创建交办</button><span className="boss-tag boss-tag-blue">他人交办</span><span className="boss-tag">{current?statusNames[current.status]??current.status:"草稿"}</span><span className="boss-helper">{current?.version?"当前版本 "+current.version:"尚未创建"}</span><div className="boss-actions"><button type="button" className="boss-btn" onClick={()=>props.onNavigate("N05")}>返回任务列表</button></div></div>
    {loading&&<p role="status" className="boss-status">正在读取当前交办与反馈。</p>}
    {missing&&!loading&&<p role="alert" className="boss-status boss-status-warn">当前目录没有所选任务，请重新读取或返回任务列表。</p>}
    {stale&&<div role="alert" className="boss-status boss-status-warn">当前任务或资料版本已经变化，未提交内容继续保留。查看最新版本只展示差异，明确选择放弃本次修改后才采用当前读取的任务与资料。<button type="button" className="boss-btn" onClick={()=>setDiscardMode("stale")}>查看最新版本</button></div>}
    <div className="boss-assignment-columns"><div className="boss-column">
      <section className="boss-panel"><div className="boss-panel-head"><h2>当前交办任务</h2><small>{current?.task_id??"填写目的、负责人、截止时间与验收依据"}</small></div>
        {current?<><h3>{current.purpose||"未提供交办目的"}</h3><div className="boss-form-grid"><Fact label="唯一负责人">{contactText(current.coordinator_id)}</Fact><Fact label="当前有效期限">{displayTime(current.due_at)+" · "+(current.timezone??"时区待核查")}</Fact><Fact label="期限时区">{current.timezone??"尚未提供"}</Fact><Fact label="验收依据">{current.evidence_requirements?.join("；")||"尚未提供"}</Fact><Fact label="关联会议">{current.related_meeting_id||"没有已读取的关联会议"}</Fact><Fact label="关联事件">{current.related_event_ids?.join("、")||"没有已读取的关联事件"}</Fact></div>{current.related_task_id&&<Fact label="原关联任务">{current.related_task_id}</Fact>}
          {current.origin_minute_id&&<details className="boss-assignment-details"><summary>已确认纪要关联</summary><Fact label="纪要与条目">{current.origin_minute_id} · {current.origin_entry_id}</Fact><Fact label="纪要版本">{current.origin_minute_version}</Fact><Fact label="原文来源">{current.origin_source_id} · 版本 {current.origin_source_version}</Fact></details>}
          <Fact label="依据版本状态">{current.source_reference_state??"需要核查"}</Fact>{current.source_reference_state!=="CURRENT"&&<p className="boss-status boss-status-warn" role="status">{current.source_reference_reasons?.join("；")||"当前依据缺少可核查版本。"}</p>}
          {!terminal&&<label className="boss-assignment-field">{current.status==="OPEN"?"模拟发送正文":current.status==="RESULT_SUBMITTED"?"补充材料请求正文":"催办正文"}<textarea rows={3} value={draft.body} disabled={!canEdit} onChange={event=>edit("body",event.target.value)} placeholder={current.status==="OPEN"?"填写交给唯一负责人的具体内容":"填写本次沟通或补充材料要求"} /></label>}
        </>:!missing?<><label className="boss-assignment-field">目的<textarea rows={3} disabled={!canEdit} value={draft.purpose} onChange={event=>edit("purpose",event.target.value)} placeholder="说明这次交办要解决的事项与范围"/></label><div className="boss-form-grid"><Fact label="唯一负责人">{draft.coordinator?contactText(draft.coordinator):"尚未选择负责人"}</Fact><Fact label="截止时间">{draft.due?displayTime(draft.due)+" · "+(draft.timezone||"时区待核查"):"尚未选择时间与时区"}</Fact><Fact label="关联会议">{meetingId??"没有关联会议"}</Fact><Fact label="关联事件">{eventIds.join("、")||"没有关联事件"}</Fact></div><div className="boss-actions"><button type="button" className="boss-btn" disabled={!canEdit} onClick={props.onCoordinator}>选择唯一负责人</button><button type="button" className="boss-btn" disabled={!canEdit} onClick={props.onDue}>选择截止时间与时区</button></div><label className="boss-assignment-field">验收依据<textarea rows={3} disabled={!canEdit} value={draft.evidence} onChange={event=>edit("evidence",event.target.value)} placeholder="每行一项，最多8项，每项最多160字"/></label>{draft.relatedTask&&<Fact label="关联原任务">{draft.relatedTask} · 版本 {draft.relatedTaskVersion}</Fact>}<p className="boss-helper">创建与发送分别处理。创建成功后保留当前任务，再核查消息正文与唯一收件人。</p></>:null}
        <div className="boss-actions">{currentSources.map(id=><button type="button" className="boss-btn" key={id} onClick={()=>props.onSource(id)}>查看依据：{id}</button>)}</div>{!currentSources.length&&<p className="boss-helper">尚未取得获准来源。</p>}
        {current&&Object.keys(current.source_versions??{}).length>0&&<p className="boss-helper">依据版本：{Object.entries(current.source_versions??{}).map(([id,version])=>id+" v"+version).join("、")}</p>}
        {props.sourceReview&&<details className="boss-assignment-details" open={current?.source_reference_state!=="CURRENT"}><summary>来源与版本核查</summary>{props.sourceReview}</details>}
      </section>
      <section className="boss-panel" id="assignment-result-evidence" tabIndex={-1}><div className="boss-panel-head"><h2>结果提交与证据</h2><small>进展、结果与本人确认分别记录</small></div><div className="boss-form-grid"><Fact label="结果提交">{completed?"已取得含证据的当前结果":resultFeedback.length?"已提交结果，证据待本人核查":"尚未取得含证据的当前结果"}</Fact><Fact label="本人确认">{current?.status==="COMPLETED_CONFIRMED"?"已经确认完成":current?.status==="CANCELED"?"交办已经取消":"尚未确认完成"}</Fact></div>
        {feedback.length?<details className="boss-assignment-details" open={evidenceOpen} onToggle={event=>setEvidenceOpen(event.currentTarget.open)}><summary>负责人反馈、结果与证据（{feedback.length}）</summary>{feedback.map(item=><article className="boss-feedback" key={item.feedback_id}><div><span className="boss-tag boss-tag-blue">{feedbackNames[item.kind]??item.kind}</span><small>{item.submitted_at??"时间尚未提供"}</small></div><p>{item.content||"未提供正文"}</p><small>作者 {item.author_contact_id?contactText(item.author_contact_id):"待核查"} · 提交时任务版本 {item.task_version??"待核查"} · {item.historical_only?"历史反馈，不改变当前任务":"当前反馈"}</small>{item.evidence_refs?.length?<div className="boss-actions">{item.evidence_refs.map(id=><button type="button" className="boss-btn" key={id} onClick={()=>props.onSource(id)}>查看依据：{id}</button>)}</div>:null}{item.evidence_refs?.length?<p className="boss-helper">证据版本：{item.evidence_refs.map(id=>id+" v"+(item.evidence_versions?.[id]??"待核查")+"（"+(item.evidence_states?.[id]??"待核查")+"）").join("；")}</p>:null}{item.proposed_due_at&&<Fact label="申请期限">{displayTime(item.proposed_due_at)}</Fact>}</article>)}</details>:<p className="boss-helper">尚无署名反馈或结果证据；负责人提交结果后在此查看作者、时间、版本与证据。</p>}
      </section>
      <section className="boss-panel"><div className="boss-panel-head"><h2>延期与有效期限</h2><small>批准前保留原期限</small></div><div className="boss-form-grid"><Fact label="当前有效期限">{current?displayTime(current.due_at)+" · "+(current.timezone??"时区待核查"):"尚未创建交办"}</Fact><Fact label="申请的新期限">{extension?displayTime(extension.proposed_due_at)+" · "+(current?.timezone??"时区待核查"):"尚无待决定的延期申请"}</Fact><Fact label="逾期属性">{terminal?"任务已经结束":overdue===null?"缺少有效期限或业务时钟":overdue?"已逾期":"尚未逾期"}</Fact></div><Fact label="采用业务时钟">{clock}</Fact>
        {current&&!extensions&&<p role="status" className="boss-helper">延期决定尚未成功读取，批准与拒绝操作暂不可用。</p>}
        {extension&&<p>申请 {extension.feedback_id} · 作者 {extension.author_contact_id?contactText(extension.author_contact_id):"待核查"}：{extension.content??"未提供申请理由"}</p>}
        {!extension&&current&&<p className="boss-helper">当前没有待本人决定的延期申请。</p>}
        {current&&!terminal&&extension&&<><div className="boss-form-grid"><label>批准后的完整期限<input value={draft.newDue} disabled={!canEdit} onChange={event=>edit("newDue",event.target.value)} placeholder="包含明确UTC时差"/></label><label>本人决定理由<input value={draft.reason} disabled={!canEdit} onChange={event=>edit("reason",event.target.value)} placeholder="填写本次决定的具体理由"/></label></div>{!draft.reason.trim()&&<p className="boss-helper" role="status">填写本人决定理由后才能批准或拒绝延期。</p>}{draft.reason.trim()&&approveReason&&<p className="boss-helper" role="status">{approveReason}</p>}<div className="boss-actions"><button type="button" className="boss-btn" disabled={!canEdit||sourceBlocked||!draft.reason.trim()||!newDueValid(draft.newDue,clock)} onClick={()=>props.onExtend("APPROVE")}>批准延期</button><button type="button" className="boss-btn" disabled={!canEdit||!draft.reason.trim()} onClick={()=>props.onExtend("REJECT")}>拒绝延期</button></div></>}
        {extensions?.decisions.map(decision=><article className="boss-feedback" key={decision.decision_id}><p>{decision.decision==="APPROVE"?"批准延期":"拒绝延期"} · {decision.decided_at}</p><Fact label="申请与决定编号">{decision.feedback_id} · {decision.decision_id}</Fact><Fact label="原期限">{displayTime(decision.old_due_at)}</Fact><Fact label="决定后期限">{displayTime(decision.new_due_at)}</Fact><Fact label="任务版本">{decision.previous_task_version} → {decision.task_version}</Fact><p>申请理由：{decision.request_reason}</p><p>本人理由：{decision.reason??"当时未记录"}</p></article>)}
        <p className="boss-helper">取消或本人确认完成后终止后续催办；已经发送的消息、产物和历史反馈继续保留。</p>
      </section>
    </div><aside className="boss-column"><section className="boss-panel"><div className="boss-panel-head"><h2>执行记录</h2></div><Fact label="创建交办">{current?"已创建 · 版本 "+(current.version??"待核查"):"尚未创建"}</Fact><Fact label="模拟发件">{messages.length?messages.length+"条记录":"尚无已读取的记录"}</Fact><Fact label="收到反馈">{feedback.length?feedback.length+"条记录":"尚无反馈"}</Fact>
      {messages.map(message=><details className="boss-assignment-details" key={message.message_id}><summary>{message.type} · {message.sent_at}</summary><Fact label="消息编号">{message.message_id}</Fact><p>{message.body??"未提供正文"}</p><Fact label="本人授权">{message.authorization_id??"当时未记录"}</Fact><Fact label="收件人">{contactText(message.recipient_id)}</Fact><Fact label="模拟发送">{message.send_state}</Fact><Fact label="真实送达">{message.delivery_state}</Fact><Fact label="回复">{message.reply_state}</Fact></details>)}
      {taskDue?<details className="boss-assignment-details"><summary>到期提醒与调度结果</summary><Fact label="到期事件">{taskDue.event_id} · 版本 {taskDue.event_version}</Fact><Fact label="同步任务版本">{taskDue.task_version_at_sync}</Fact><Fact label="到期时间">{taskDue.due_at}</Fact><Fact label="事件状态">{taskDue.event_state}</Fact><Fact label="派发检查">{taskDue.dispatch_state}</Fact><Fact label="抑制原因">{taskDue.dispatch_reason??"没有已记录原因"}</Fact></details>:<p className="boss-helper">尚无已登记的到期事件。</p>}
      <p className="boss-helper">模拟发送只记录本地发件。真实送达与负责人回复分别核查。</p>
      <div className="boss-actions">{current&&messagesEnabled&&<button type="button" className="boss-btn" onClick={props.onMessages}>查看消息与回复</button>}{current&&<button type="button" className="boss-btn" onClick={()=>props.onNavigate("D03")}>查询执行结果</button>}</div>
    </section><section className="boss-panel"><div className="boss-panel-head"><h2>继续任务</h2></div>{props.conversation}{current?.version&&<details className="boss-assignment-details"><summary>当前任务与授权准备</summary><BossAssignmentPreparation key={current.task_id} taskId={current.task_id} taskVersion={current.version}/></details>}{terminal&&<div className="boss-actions"><button type="button" className="boss-btn boss-btn-primary" disabled={busy} onClick={()=>props.onNew(current)}>创建关联交办</button></div>}{terminal&&<p className="boss-helper">当前任务已经结束，后续工作通过关联交办建立。</p>}</section></aside></div>
    <div className="boss-actions boss-assignment-footer">{!current?<button type="button" className="boss-btn boss-btn-primary" disabled={!canEdit||morningBlocked||!context||!sourceIds.length} onClick={props.onCreate}>核对并创建交办</button>:<>
      {current.status==="OPEN"&&<button type="button" className="boss-btn boss-btn-primary" disabled={!canEdit||sourceBlocked||!draft.body.trim()} onClick={props.onSend}>核对并模拟发送</button>}
      {["WAITING_FEEDBACK","IN_PROGRESS"].includes(current.status)&&<button type="button" className="boss-btn boss-btn-primary" disabled={!canEdit||sourceBlocked||!draft.body.trim()} onClick={props.onNudge}>准备催办</button>}
      {messagesEnabled&&["WAITING_FEEDBACK","IN_PROGRESS","RESULT_SUBMITTED"].includes(current.status)&&<button type="button" className="boss-btn" disabled={!canEdit||!draft.body.trim()||current.status!=="RESULT_SUBMITTED"&&sourceBlocked} onClick={props.onFollowup}>{current.status==="RESULT_SUBMITTED"?"保存补材料草稿":"保存沟通草稿"}</button>}
      <button type="button" className="boss-btn" disabled={!resultFeedback.length} onClick={()=>{setEvidenceOpen(true);const node=document.getElementById("assignment-result-evidence");node?.scrollIntoView?.({block:"start"});node?.focus();}}>查看结果证据</button>
      {current.status==="RESULT_SUBMITTED"&&!terminal&&<button type="button" className="boss-btn boss-btn-primary" disabled={!canEdit||Boolean(completeReason)} onClick={props.onComplete}>验收并确认完成</button>}
      {!terminal&&<details className="boss-more-actions"><summary className="boss-btn">更多操作</summary><p className="boss-v7-note">取消交办只处理未来催办和未执行步骤，已经发送的消息、已提交产物和历史反馈继续保留。</p><label className="boss-assignment-field">取消原因<textarea rows={2} value={cancelReason} disabled={!canEdit} onChange={event=>setCancelReason(event.target.value)} placeholder="说明取消原因"/></label>{!cancelReason.trim()&&<p className="boss-helper">填写取消原因后才能取消交办。</p>}<button type="button" className="boss-btn" disabled={!canEdit||!cancelReason.trim()} onClick={()=>props.onCancel(cancelReason.trim())}>取消交办</button></details>}
    </>}{draft.basis&&<button type="button" className="boss-btn" disabled={busy} onClick={()=>setDiscardMode("edit")}>放弃本次修改</button>}</div>
    {current&&!resultFeedback.length&&<p className="boss-helper">当前任务尚未提交结果与证据，暂无可查看的产物。</p>}
    {current&&!terminal&&current.status==="RESULT_SUBMITTED"&&completeReason&&<p className="boss-helper" role="status">{completeReason}</p>}
    {current&&!terminal&&actionReason&&actionReason!==completeReason&&<p className="boss-helper" role="status">{actionReason}</p>}
    {!current&&!missing&&createReason&&<p className="boss-helper" role="status">{createReason}</p>}
    <div className="boss-v7-addendum">
      <V7Panel title="交办全流程与有效授权核查" description="创建、发送、反馈、结果提交和本人确认分别记录，发送与完成都需要独立授权。">
        <V7Steps steps={flowSteps}/>
        <div className="boss-v7-metrics">
          <V7Metric label="原有效期限" value={extensions?.decisions[0]?displayTime(extensions.decisions[0].old_due_at):current?displayTime(current.due_at):"待核查"}/>
          <V7Metric label="延期申请" value={extension?"待本人决定":extensions?.decisions.length?"已有决定记录":"尚未批准"}/>
          <V7Metric label="证据完整性" value={current?current.result_evidence_requires_resubmission?"需要重新提交":completed?"已取得完成记录":"待核查":"尚未创建"}/>
          <V7Metric label="确认完成" value={current?.status==="COMPLETED_CONFIRMED"?"已确认":current?.status==="CANCELED"?"已取消":"未确认"}/>
        </div>
      </V7Panel>
      <div className="boss-v7-equal-columns">
        <V7Panel title="结果产物与证据索引">
          {resultFeedback.length?resultFeedback.map(item=><article className="boss-feedback" key={item.feedback_id}><p>{item.content||"未提供正文"}</p><p className="boss-helper">作者 {item.author_contact_id?contactText(item.author_contact_id):"待核查"} · 提交时间 {item.submitted_at??"待核查"} · 任务版本 {item.task_version??"待核查"}</p>{item.evidence_refs?.length?<div className="boss-actions">{item.evidence_refs.map(id=><button type="button" className="boss-btn" key={id} onClick={()=>props.onSource(id)}>查看依据：{id}</button>)}</div>:null}{item.evidence_refs?.length?<p className="boss-helper">证据版本：{item.evidence_refs.map(id=>id+" v"+(item.evidence_versions?.[id]??"待核查")+"（"+(item.evidence_states?.[id]??"待核查")+"）").join("；")}</p>:null}</article>):<p className="boss-helper">尚无已记录的提交产物；取得结果后在此核查作者、时间、版本与证据，不得在缺少资料时确认完成。</p>}
        </V7Panel>
        <V7Panel title="取消交办的影响">
          <p>取消只作用于未来催办和未执行步骤，既有历史消息、已提交产物和日志继续可读。</p>
        </V7Panel>
      </div>
    </div>
    <Dialog.Root open={discardMode!==null} onOpenChange={open=>{if(!open)setDiscardMode(null);}}><Dialog.Portal><Dialog.Overlay className="boss-v7-dialog-overlay"/><Dialog.Content className="boss-v7-dialog"><Dialog.Title>{discardMode==="stale"?"查看最新版本":"放弃本次修改"}</Dialog.Title><Dialog.Description>{discardMode==="stale"?"当前任务或资料版本已经变化。下面是草稿基线与当前读取结果的差异；查看差异不会清除编辑，明确选择放弃后才恢复当前读取的任务与资料。":"清除当前交办表单中尚未提交的内容，并采用当前读取的任务及资料版本。已经保存的任务和反馈继续保留。"}</Dialog.Description>{discardMode==="stale"&&<div>{basisDiff.map(row=><div className="boss-kv" key={row.label}><span>{row.label}</span><strong>{row.before} → {row.after}</strong></div>)}</div>}<div className="boss-actions"><Dialog.Close asChild><button type="button" className="boss-btn">保留本次修改</button></Dialog.Close><button type="button" className="boss-btn boss-btn-primary" disabled={busy} onClick={()=>{props.onDiscard();setDiscardMode(null);}}>{discardMode==="stale"?"放弃本次修改并采用最新版本":"确认放弃本次修改"}</button></div></Dialog.Content></Dialog.Portal></Dialog.Root>
  </>;
}
