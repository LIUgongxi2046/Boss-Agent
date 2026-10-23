import {useId, useState} from "react";

type SourceStatus="VALID"|"RECEIVED"|"INCOMPLETE"|"CONFLICTED"|"SUPERSEDED"|"WITHDRAWN"|"EXPIRED"|"MISSING"|"FORBIDDEN";
type Source={source_id:string;pinned_version:string|null;current_version:string|null;source_status:SourceStatus;excerpt:string|null;
  published_at:string|null;valid_from:string|null;valid_until:string|null;is_minute_origin:boolean;
  adoption_state:"NOT_APPLICABLE"|"CURRENT"|"NEEDS_REIMPORT";adoption_dependencies:{source_id:string;version:string;status:string}[]};
export type AssignmentSourceReviewProjection={source_type:"SIMULATED";task:{task_id:string;version:string;status:string;purpose:string};
  binding_state:"MISSING"|"CURRENT"|"NEEDS_REVIEW";sources:Source[];can_confirm:boolean;review_sha256:string;business_at:string;
  result_evidence_current:boolean|null;result_evidence_requires_resubmission:boolean;confirmed_reason:string|null;read_at:string;
  history:{before_task_version:string;source_versions:Record<string,string>;archived_at:string;origin_source:{source_id:string;version:string}|null;review_reason:string|null}[]};
type Payload={client_request_id:string;task_id:string;task_version:string;review_sha256:string;reason:string};
type Receipt={action:string;client_request_id:string;outcome:string};
type Props={data:AssignmentSourceReviewProjection|null;loading:boolean;error:string;onReload:()=>void;
  onCommand:(action:string,payload:Record<string,unknown>)=>Promise<void>;
  onReceipt:(action:string,clientRequestId:string)=>Promise<Receipt>;onOpenSource:(sourceId:string)=>void;onDirtyChange:(dirty:boolean)=>void};
const ACTION="boss.assignment.sources.confirm";
const SOURCE_LABELS:Record<SourceStatus,string>={VALID:"当前可用",RECEIVED:"尚未生效",INCOMPLETE:"资料不完整",CONFLICTED:"存在冲突",
  SUPERSEDED:"已经换版",WITHDRAWN:"已经撤销",EXPIRED:"已经到期",MISSING:"没有找到资料",FORBIDDEN:"当前没有权限"};

function definiteRejection(error:unknown){
  return error instanceof Error&&error.name==="WebUIMutationError"&&"status" in error&&typeof error.status==="number"
    &&[400,401,403,404,409,410,413,422].includes(error.status);
}

export function BossAssignmentSourceReview({data,loading,error,onReload,onCommand,onReceipt,onOpenSource,onDirtyChange}:Props){
  const heading=useId();
  const [reason,setReason]=useState("");
  const [approvedFor,setApprovedFor]=useState<string|null>(null);
  const [busy,setBusy]=useState(false);
  const [failure,setFailure]=useState("");
  const [pending,setPending]=useState<Payload|null>(null);
  const approved=data!==null&&approvedFor===data.review_sha256;
  const targetChanged=Boolean(pending&&data&&pending.task_id!==data.task.task_id);
  function saved(){setPending(null);setReason("");setApprovedFor(null);setBusy(false);setFailure("");onDirtyChange(false);onReload();}
  async function submit(){
    if(busy||loading||!data||targetChanged||(!pending&&(!data.can_confirm||!approved||!reason.trim())))return;
    const payload=pending||{client_request_id:"source-review-"+crypto.randomUUID(),task_id:data.task.task_id,
      task_version:data.task.version,review_sha256:data.review_sha256,reason:reason.trim()};
    setPending(payload);setBusy(true);setFailure("");onDirtyChange(true);
    await onCommand(ACTION,payload).then(saved,(error:unknown)=>{
      setBusy(false);setFailure(error instanceof Error?error.message:String(error));
      if(definiteRejection(error)){setPending(null);setApprovedFor(null);onReload();}
    });
  }
  async function reconcile(){
    if(!pending||busy)return;
    setBusy(true);setFailure("");
    await onReceipt(ACTION,pending.client_request_id).then(receipt=>{
      setBusy(false);
      if(receipt.action!==ACTION||receipt.client_request_id!==pending.client_request_id){
        setFailure("原请求回执与当前请求标识不符，需要继续核查。");return;
      }
      if(receipt.outcome==="RECORDED"){saved();return;}
      setFailure(receipt.outcome==="NOT_FOUND_IN_CURRENT_STORE"?
        "当前没有查到回执，执行结果仍未确定。请重新读取交办，并使用原请求编号继续核查。":"原请求结果没有得到确认。");
      onReload();
    },(error:unknown)=>{setBusy(false);setFailure(error instanceof Error?error.message:String(error));});
  }
  return <section className="boss-panel" aria-labelledby={heading}>
    <div className="boss-panel-head"><h2 id={heading}>核查交办来源</h2><button className="boss-btn" type="button" disabled={busy||loading} onClick={onReload}>重新读取当前资料</button></div>
    {loading&&<p role="status">正在读取交办与来源版本</p>}
    {(error||failure)&&<p className="boss-status boss-status-error" role="alert">{error||failure}</p>}
    {!data&&!loading&&<p>选择交办后查看当前来源。</p>}
    {data&&<>
      <p><strong>{data.task.purpose}</strong></p><p className="boss-helper">交办版本 {data.task.version} · 当前状态 {data.task.status}</p>
      <p>{data.binding_state==="MISSING"?"历史来源没有完整记录。请核查当前资料后独立确认。":
        data.binding_state==="NEEDS_REVIEW"?"当前资料与此前确认内容存在变化，需要本人重新核查。":"当前来源与本人确认版本一致。"}</p>
      {data.sources.map(source=><article className="boss-workspace-item" key={source.source_id}>
        <strong>{source.source_id}{source.is_minute_origin?" · 原始纪要来源":""}</strong>
        <p><span className="boss-tag boss-tag-amber">{SOURCE_LABELS[source.source_status]}</span> 此前版本 {source.pinned_version??"未知"} · 当前版本 {source.current_version??"未知"}</p>
        <p className="boss-helper">发布 {source.published_at??"未知"} · 有效起点 {source.valid_from??"未知"} · 有效终点 {source.valid_until??"未知"}</p>
        {source.excerpt!==null&&<blockquote>{source.excerpt}</blockquote>}
        {source.adoption_state==="NEEDS_REIMPORT"&&<p role="status">关联资料已经变化，需要重新导入当前外部记录。</p>}
        {source.adoption_dependencies.filter(reference=>reference.status!=="VALID").map(reference=><p className="boss-helper" key={reference.source_id}>{reference.source_id} · 采用版本 {reference.version} · 当前状态 {reference.status}</p>)}
        {source.source_status==="VALID"&&source.adoption_state!=="NEEDS_REIMPORT"&&<button className="boss-btn" type="button" disabled={busy} onClick={()=>onOpenSource(source.source_id)}>查看当前原始资料</button>}
      </article>)}
      {data.result_evidence_requires_resubmission&&<p className="boss-status boss-status-error" role="status">结果证据需要负责人重新提交。来源确认保存后，交办继续保留当前业务状态。</p>}
      <fieldset disabled={busy||Boolean(pending)||loading||!data.can_confirm}>
        <label className="boss-field">本次核查依据<textarea maxLength={400} value={reason} onChange={event=>{
          setReason(event.target.value);setApprovedFor(null);onDirtyChange(Boolean(event.target.value));}}/></label>
        <label className="boss-confirm-check"><input type="checkbox" checked={approved} onChange={event=>{
          setApprovedFor(event.target.checked?data.review_sha256:null);onDirtyChange(Boolean(reason)||event.target.checked);}}/>本人已经核查当前资料，确认用于此项交办</label>
      </fieldset>
      <p className="boss-helper">来源确认保存当前采用范围。发送、完成及其他业务决定各自保留独立确认。</p>
      <div className="boss-actions"><button className="boss-btn boss-btn-primary" type="button" disabled={busy||loading||targetChanged||(!pending&&(!data.can_confirm||!approved||!reason.trim()))}
        onClick={()=>void submit()}>{busy?"正在核查":pending?"使用原请求编号继续确认":"本人确认当前来源"}</button>
        {pending&&<button className="boss-btn" type="button" disabled={busy} onClick={()=>void reconcile()}>查询原请求回执</button>}</div>
      {pending&&<p className="boss-helper" role="status">待核查交办：{pending.task_id}；请求编号：{pending.client_request_id}</p>}
      {data.confirmed_reason&&<p>已保存核查依据：{data.confirmed_reason}</p>}
      {data.history.length>0&&<details><summary>已知来源历史（{data.history.length}）</summary>{data.history.map(item=><p key={item.before_task_version}>
        交办版本 {item.before_task_version} 之前保存的来源：{Object.entries(item.source_versions).map(([identifier,version])=>identifier+" v"+version).join("、")}
        {item.origin_source&&"；原始纪要 "+item.origin_source.source_id+" v"+item.origin_source.version} · {item.archived_at}{item.review_reason&&"；核查依据："+item.review_reason}</p>)}</details>}
    </>}
  </section>;
}
