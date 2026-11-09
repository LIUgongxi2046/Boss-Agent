import {useId,useState, type FormEvent} from "react";
import {orderRunEvents, type RunEvent} from "./upgrade2-run-events";
import type {RunResultEvent,RunRequirements,RequiredOutput,CitationCheck,DomainIntentPreview,RunSnapshot} from "./upgrade2-run-client";
import {RequiredOutputs,describeRequiredOutputs} from "./RequiredOutputs";
import {BIRecordContent} from "./BIRecordContent";
import "./upgrade2-run-panel.css";

export type Upgrade2RunStatus = "QUEUED" | "RUNNING" | "WAITING_INPUT" | "WAITING_CONFIRMATION" | "CANCEL_REQUESTED" | "RECONCILING" | "SUCCEEDED" | "FAILED" | "CANCELED" | "INTERRUPTED";
export type Upgrade2RunAction = "SUPPLY_INPUT" | "CANCEL" | "CONFIRM" | "REJECT" | "RESUME" | "OPEN_ARTIFACT" | "EXPORT_ARTIFACT" | "READ_ORIGINAL_RESULT";
export type Upgrade2Source = {source_id: string; revision: string; locator: string; result_event_id?:string; content_sha256?:string};
export type Upgrade2Intent = {
  intent_id: string; revision: number; payload_digest: string; status: string;
  action: string; object_label: string; content: string; assignee: string; deadline: string;
  impact: string; source_refs: Upgrade2Source[]; simulation_label: string;
  interface_id: string; review_sha256: string; preparation_sha256: string; evidence_requirements: string[]; owner_page: string;
  domain?:DomainIntentPreview;
};
export type Upgrade2Artifact = {
  artifact_id: string; run_id: string; version: number; media_type: string; size_bytes: number; sha256: string;
  verification_status: string; status: "DRAFT" | "VERIFIED" | "PUBLISHED" | "REVOKED" | "FAILED";
  source_refs: (Upgrade2Source & {classification: string; sha256: string})[];
};
export type Upgrade2RunView = {
  run_id: string; goal: string; revision: number; goal_revision: number; status: Upgrade2RunStatus;
  allowed_actions: readonly Upgrade2RunAction[]; waiting_inputs: readonly string[];
  intent: Upgrade2Intent | null; artifacts: readonly Upgrade2Artifact[]; projection_ready?: boolean;
  requirements?:RunRequirements;
  method_selection?:RunSnapshot["method_selection"];
  cancel_requested_at: string | null;
};
export type Upgrade2RunPanelProps = {
  run: Upgrade2RunView | null;
  events: readonly RunEvent[];
  result?: RunResultEvent | null;
  citationChecks?:CitationCheck[]|null;
  event_base_seq: number;
  connection: "CONNECTED" | "RECONNECTING" | "DISCONNECTED";
  loading: boolean;
  busy: boolean;
  error: string | null;
  supplement: string;
  onSupplementChange?: (value: string) => void;
  onSupplement?: (runId: string, input: string, expectedGoalRevision: number, outputs:RequiredOutput[]) => void;
  supplementOutputs?:RequiredOutput[];
  onSupplementOutputsChange?:(outputs:RequiredOutput[])=>void;
  onCancel?: (runId: string, expectedRevision: number) => void;
  onResume?: (runId: string, expectedRevision: number) => void;
  onDecision?: (intentId: string, decision: "CONFIRM" | "REJECT", expectedRevision: number, payloadDigest: string,acknowledgeConflict?:boolean) => void;
  onReadOriginal?: (runId: string, intentId: string) => void;
  onOpenArtifact?: (artifactId: string, version: number) => void;
  onExportArtifact?: (artifactId: string, version: number) => void;
  onOpenSource?: (source: Upgrade2Source) => void;
  onReload?: () => void;
};

const labels: Record<Upgrade2RunStatus, string> = {
  QUEUED: "正在排队", RUNNING: "正在执行", WAITING_INPUT: "等待补充", WAITING_CONFIRMATION: "等待本人决定",
  CANCEL_REQUESTED: "正在取消", RECONCILING: "执行结果待核查", SUCCEEDED: "运行完成", FAILED: "运行失败",
  CANCELED: "已取消", INTERRUPTED: "运行中断",
};

function runTime(value: string): string {
  return new Intl.DateTimeFormat("zh-CN", {timeZone: "Asia/Shanghai", dateStyle: "short", timeStyle: "medium"}).format(new Date(value));
}

function cancellationNotice(run: Upgrade2RunView): string | null {
  if (!run.cancel_requested_at) return null;
  if (run.status === "CANCEL_REQUESTED") return "取消请求已记录于 " + runTime(run.cancel_requested_at) + "；服务正在核查已开始的动作，完成前不能视为全部取消。";
  if (run.status === "RECONCILING") return "取消请求已记录于 " + runTime(run.cancel_requested_at) + "；正在核查原业务动作的结果，不能重复提交。";
  if (run.status === "CANCELED") return "取消请求记录于 " + runTime(run.cancel_requested_at) + "；取消前已经完成的业务动作继续保留。";
  return null;
}

function methodReadEvent(event:RunEvent) {
  const payload=event.payload;
  if(event.type!=="TOOL_FINISHED"||!payload||typeof payload!=="object"||Array.isArray(payload)||payload.tool_id!=="read_enabled_method"||payload.outcome!=="RETURNED")return null;
  const reference=payload.method_ref;
  if(!reference||typeof reference!=="object"||Array.isArray(reference)||typeof payload.goal_revision!=="number"||!Number.isSafeInteger(payload.goal_revision)||payload.goal_revision<1||
    typeof reference.sop_id!=="string"||!reference.sop_id.trim()||typeof reference.name!=="string"||!reference.name.trim()||typeof reference.version!=="string"||!reference.version.trim()||typeof reference.content_sha256!=="string"||!/^[a-f0-9]{64}$/.test(reference.content_sha256))return null;
  return {goalRevision:payload.goal_revision,sopId:reference.sop_id,name:reference.name,version:reference.version,sha256:reference.content_sha256};
}

export function Upgrade2RunPanel(props: Upgrade2RunPanelProps) {
  const inputId = useId();
  const [conflictApproval,setConflictApproval]=useState<{intentId:string;digest:string;checked:boolean}|null>(null);
  const {run, loading, busy, error, connection} = props;
  if (!run) return <section className="upgrade2-run-panel" aria-label="任务执行" aria-busy={loading}>
    <h2>任务执行</h2>{loading ? <p role="status">正在读取运行</p> : error ? <p role="alert">{error}</p> : connection !== "CONNECTED" ? <p role="status">连接已中断，尚未读取运行。</p> : <p>当前没有运行记录。</p>}
  </section>;
  const ordered = orderRunEvents(run.run_id, props.event_base_seq, props.events);
  const available = (action: Upgrade2RunAction) => !loading && !busy && !error && connection === "CONNECTED" && run.allowed_actions.includes(action);
  const submit = (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    if (available("SUPPLY_INPUT") && props.onSupplement && props.supplement.trim()) {
      props.onSupplement(run.run_id, props.supplement.trim(), run.goal_revision,props.supplementOutputs??[]);
    }
  };
  const contentAvailable = !loading && !busy && !error && connection === "CONNECTED";
  const cancelNotice = contentAvailable ? cancellationNotice(run) : null;
  const intent = contentAvailable ? run.intent : null;
  const domain=intent?.domain;
  const needsConflict=domain?.action==="boss.meeting.confirm"&&domain.impact?.requires_owner_acknowledgement===true;
  const conflictAcknowledged=Boolean(intent&&conflictApproval?.intentId===intent.intent_id&&conflictApproval.digest===intent.payload_digest&&conflictApproval.checked);
  const lastFailure=run.status==="FAILED"?[...ordered.contiguous].reverse().find(item=>item.type==="RUN_FAILED"):undefined;
  const laterStatus=lastFailure&&ordered.contiguous.some(item=>item.seq>lastFailure.seq&&item.type==="STATUS_CHANGED"&&item.payload&&typeof item.payload==="object"&&!Array.isArray(item.payload)&&item.payload.to!=="FAILED");
  const failureEvent=laterStatus?undefined:lastFailure;
  const failurePayload=failureEvent?.payload;
  const failureCode=failurePayload&&typeof failurePayload==="object"&&!Array.isArray(failurePayload)&&typeof failurePayload.error_code==="string"&&failurePayload.error_code.trim()?failurePayload.error_code:null;
  const methodReads=ordered.contiguous.flatMap(event=>{const method=methodReadEvent(event);return method?[{event,method}]:[];});
  return <section className="upgrade2-run-panel" aria-label="任务执行" aria-busy={loading || busy}>
    <header className="upgrade2-run-header"><div><h2>任务执行</h2><p>{run.goal}</p></div><strong>{labels[run.status]}</strong></header>
    {run.status==="WAITING_INPUT"&&!loading&&!busy&&!error&&connection==="CONNECTED"&&<p className="upgrade2-run-notice" role="status">{run.requirements?.state==="PENDING_CONFIRMATION"?(run.allowed_actions.includes("SUPPLY_INPUT")?"等待本人选择必要成果。请补充要求并选择所需成果。":"等待本人选择必要成果，当前不能提交补充。"):run.requirements?.state==="UNAVAILABLE"?"成果要求服务尚未安装，当前无法确认必要成果。":run.requirements?.state==="CONFIRMED"?(run.allowed_actions.includes("RESUME")?"当前目标的必要成果已经确认，可按当前允许操作继续运行。":"当前目标的必要成果已经确认，尚无可用的继续运行操作。"):"运行正在等待补充，具体条件尚未取得。"}</p>}
    {run.requirements&&<section className="upgrade2-run-card"><h3>当前目标的必要成果</h3>{loading||busy||error||connection!=="CONNECTED"?<p>当前目标的必要成果尚未核查，请重新读取运行。</p>:<p>目标版本 {run.requirements.goal_revision} · {run.requirements.state==="CONFIRMED"&&run.requirements.required_outputs?"本人已选择："+describeRequiredOutputs(run.requirements.required_outputs):run.requirements.state==="UNAVAILABLE"?"成果要求服务尚未安装，当前无法核查选择。":"等待本人选择。"}</p>}</section>}
    {connection !== "CONNECTED" && <p className="upgrade2-run-notice" role="status">{connection === "RECONNECTING" ? "连接正在恢复，请等待事件重放。" : "连接已中断，请恢复连接后核查原运行。"}</p>}
    {error && <p className="upgrade2-run-error" role="alert">{error}</p>}
    {run.status==="FAILED"&&!loading&&!error&&connection==="CONNECTED"&&<p className="upgrade2-run-error" role="alert">{failureCode?"运行失败记录："+failureCode+" · 事件序号 "+failureEvent!.seq:"运行失败，服务尚未提供可显示的失败原因。"}</p>}
    {cancelNotice && <p className="upgrade2-run-notice" role="status">{cancelNotice}</p>}
    {run.projection_ready === false && <p className="upgrade2-run-notice" role="status">尚未取得当前版本的完整待处理条件和成果信息。</p>}
    {ordered.missing_seq !== null && <p className="upgrade2-run-notice" role="status">运行事件缺少序号 {ordered.missing_seq}，等待重新读取。</p>}
    <div className="upgrade2-run-columns"><div className="upgrade2-run-main">
      <section className="upgrade2-run-card" aria-label="当前目标的运行结果"><h3>运行结果</h3>
        {props.result && !loading && !busy && !error && connection === "CONNECTED" ? <>
          <p>目标版本 {props.result.payload.goal_revision} · 资料集 {props.result.payload.dataset_id} · 版本 {props.result.payload.dataset_version}</p>
          <div className="upgrade2-run-result-text">{props.result.payload.text}</div>
          <p>来源版本与定位由运行记录提供，事实和定位仍需核查。</p>
          {props.result.payload.source_pins.length ? <ul className="upgrade2-run-sources">{props.result.payload.source_pins.map(pin=><li key={pin.source_id}><button type="button" disabled={busy || !props.onOpenSource} onClick={()=>props.onOpenSource?.({source_id:pin.source_id,revision:pin.version,locator:""})}>运行来源 {pin.source_id} · 版本 {pin.version}</button><p>来源摘要 {pin.content_sha256}</p></li>)}</ul> : <p>当前运行没有所选来源。</p>}
          {props.result.payload.citations.length ? <ul className="upgrade2-run-sources">{props.result.payload.citations.map((citation,index)=>{
            const pin = props.result!.payload.source_pins.find(source=>source.source_id===citation.source_id)!;
            return <li key={citation.source_id+":"+index}><button type="button" disabled={busy || !props.onOpenSource} onClick={()=>props.onOpenSource?.({source_id:pin.source_id,revision:pin.version,locator:citation.locator,result_event_id:props.result!.event_id,content_sha256:pin.content_sha256})}>来源 {pin.source_id} · 版本 {pin.version} · {citation.locator}</button><p>{props.citationChecks?.[index]?.locator_verification==="NOT_VERIFIED"?"原文位置未经核查。":"引用核查记录未提供，原文位置尚不可核查。"}</p><p>来源摘要 {pin.content_sha256}</p></li>;
          })}</ul> : <p>当前结果没有来源定位记录。</p>}
        </> : <div>{loading || busy ? <p>正在核查当前结果。</p> : error ? <><p>当前结果无法核查，来源撤销或版本变化后旧正文已经隐藏。</p>{props.onReload&&<button type="button" className="boss-btn" disabled={connection!=="CONNECTED"||loading||busy} onClick={props.onReload}>重新读取运行结果</button>}</> : <p>当前目标尚无可显示的结果。</p>}</div>}
      </section>
      <section className="upgrade2-run-card" aria-labelledby={inputId + "-progress"}>
        <h3 id={inputId + "-progress"}>执行进展</h3>
        {ordered.contiguous.length ? <ol>{ordered.contiguous.map(item => <li key={item.event_id}><strong>{item.type}</strong><time dateTime={item.occurred_at}>{item.occurred_at}</time><span>事件序号 {item.seq}</span></li>)}</ol> : <p>{run.status === "QUEUED" ? "正在等待执行。" : "当前没有可显示的连续事件。"}</p>}
      </section>
      <section className="upgrade2-run-card" aria-label="方法读取记录"><h3>方法读取记录</h3>
        {contentAvailable&&run.method_selection&&<><p>{run.method_selection.goal_revision===run.goal_revision?"当前目标":"历史目标"}版本 {run.method_selection.goal_revision} 的方法选择：{run.method_selection.sop_id} · {run.method_selection.name} · 版本 {run.method_selection.version}</p><p>方法摘要 {run.method_selection.content_sha256}。已选择，实际采用仍需核查。</p></>}
        {loading||busy||error||connection!=="CONNECTED"||ordered.missing_seq!==null?<p>当前方法记录尚未核查，请重新读取运行。</p>:methodReads.length?<><ul>{methodReads.map(({event,method})=><li key={event.event_id}><strong>{method.sopId} · {method.name} · 版本 {method.version}</strong><p>{method.goalRevision===run.goal_revision?"当前目标版本":"历史目标版本"} {method.goalRevision} · 事件序号 {event.seq}</p><p>方法摘要 {method.sha256}</p></li>)}</ul><p>记录表示服务端已经读取方法；模型实际采用尚未核查。方法选择与工具依赖状态以服务返回信息为准。</p></>:<p>当前没有可核查的方法读取记录；方法选择与工具依赖状态尚未提供。</p>}
      </section>
      {contentAvailable && run.waiting_inputs.length > 0 && <section className="upgrade2-run-card"><h3>需要补充的条件</h3><ul>{run.waiting_inputs.map((item, index) => <li key={index}>{item}</li>)}</ul></section>}
      <form className="upgrade2-run-compose" onSubmit={submit}>
        <label htmlFor={inputId}>继续对话或补充要求</label>
        <textarea id={inputId} value={props.supplement} onChange={event => props.onSupplementChange?.(event.target.value)} disabled={!available("SUPPLY_INPUT") || !props.onSupplementChange || !props.onSupplement}/>
        {props.onSupplementOutputsChange&&<RequiredOutputs value={props.supplementOutputs??[]} onChange={props.onSupplementOutputsChange} disabled={!available("SUPPLY_INPUT")||run.requirements?.state==="UNAVAILABLE"}/>}
        <div className="upgrade2-run-actions"><button type="submit" disabled={!available("SUPPLY_INPUT") || !props.onSupplementChange || !props.onSupplement || !props.supplement.trim()}>提交补充</button>
          <button type="button" disabled={!available("CANCEL") || !props.onCancel} onClick={() => props.onCancel?.(run.run_id, run.revision)}>取消未执行步骤</button>
          {(run.status==="WAITING_INPUT"||run.allowed_actions.includes("RESUME")) && <button type="button" disabled={!available("RESUME") || !props.onResume} onClick={() => props.onResume?.(run.run_id, run.revision)}>继续运行</button>}
        </div>
      </form>
    </div><aside className="upgrade2-run-side">
      <section className="upgrade2-run-card"><h3>授权与必要决定</h3>{intent&&domain ? <>
        <dl className="upgrade2-run-facts"><div><dt>意图编号</dt><dd>{intent.intent_id}</dd></div><div><dt>意图版本</dt><dd>{intent.revision}</dd></div><div><dt>内容摘要</dt><dd>{intent.payload_digest}</dd></div></dl>
        <DomainIntentContent domain={domain}/>
        <SourceList sources={intent.source_refs} onOpenSource={props.onOpenSource} disabled={loading || busy || connection !== "CONNECTED"}/>
        {needsConflict&&<label><input type="checkbox" checked={conflictAcknowledged} disabled={!available("CONFIRM")||!props.onDecision} onChange={event=>setConflictApproval({intentId:intent.intent_id,digest:intent.payload_digest,checked:event.target.checked})}/>本人已经核查并确认会议安排冲突</label>}
        <div className="upgrade2-run-actions" role="group" aria-label="本人决定"><button type="button" disabled={!available("CONFIRM")||!props.onDecision||needsConflict&&!conflictAcknowledged} onClick={()=>props.onDecision?.(intent.intent_id,"CONFIRM",intent.revision,intent.payload_digest,needsConflict?conflictAcknowledged:undefined)}>确认</button><button type="button" disabled={!available("REJECT")||!props.onDecision} onClick={()=>props.onDecision?.(intent.intent_id,"REJECT",intent.revision,intent.payload_digest)}>拒绝</button></div>
      </> : intent ? <>
        <dl className="upgrade2-run-facts"><div><dt>意图编号</dt><dd>{intent.intent_id}</dd></div><div><dt>意图版本</dt><dd>{intent.revision}</dd></div><div><dt>内容摘要</dt><dd>{intent.payload_digest}</dd></div><div><dt>动作</dt><dd>{intent.action}</dd></div><div><dt>接口</dt><dd>{intent.interface_id}</dd></div><div><dt>对象</dt><dd>{intent.object_label}</dd></div><div><dt>内容</dt><dd>{intent.content}</dd></div><div><dt>负责人</dt><dd>{intent.assignee}</dd></div><div><dt>期限</dt><dd>{intent.deadline}</dd></div><div><dt>证据要求</dt><dd>{intent.evidence_requirements.join("；")}</dd></div><div><dt>核查摘要</dt><dd>{intent.review_sha256}</dd></div><div><dt>准备摘要</dt><dd>{intent.preparation_sha256}</dd></div><div><dt>业务页面</dt><dd>{intent.owner_page}</dd></div><div><dt>影响</dt><dd>{intent.impact}</dd></div><div><dt>业务标识</dt><dd>{intent.simulation_label}</dd></div><div><dt>状态</dt><dd>{intent.status}</dd></div></dl>
        <SourceList sources={intent.source_refs} onOpenSource={props.onOpenSource} disabled={loading || busy || connection !== "CONNECTED"}/>
        <div className="upgrade2-run-actions" role="group" aria-label="本人决定"><button type="button" disabled={!available("CONFIRM") || !props.onDecision} onClick={() => props.onDecision?.(intent.intent_id, "CONFIRM", intent.revision, intent.payload_digest)}>确认</button><button type="button" disabled={!available("REJECT") || !props.onDecision} onClick={() => props.onDecision?.(intent.intent_id, "REJECT", intent.revision, intent.payload_digest)}>拒绝</button></div>
        {run.allowed_actions.includes("READ_ORIGINAL_RESULT") && <button type="button" disabled={!available("READ_ORIGINAL_RESULT") || !props.onReadOriginal} onClick={() => props.onReadOriginal?.(run.run_id, intent.intent_id)}>查询原执行结果</button>}
      </> : <p>{!contentAvailable ? "决定信息尚未核查，请重新读取运行。" : run.projection_ready === false ? "尚未取得决定信息。" : "当前没有待显示的决定。"}</p>}</section>
      <section className="upgrade2-run-card"><h3>资料与成果</h3>{!contentAvailable?<p>成果信息尚未核查，请重新读取运行。</p>:run.artifacts.length ? <ul className="upgrade2-run-artifacts">{run.artifacts.map(item => <li key={item.artifact_id + ":" + item.version}><strong>成果 {item.artifact_id}</strong><p>{item.media_type} · {item.size_bytes} 字节 · 版本 {item.version}</p><p>状态 {item.status} · 核查 {item.verification_status}</p><p>文件摘要 {item.sha256}</p>{item.run_id !== run.run_id && <p role="alert">成果与当前运行不一致，无法打开或导出。</p>}<SourceList sources={item.source_refs} onOpenSource={props.onOpenSource} disabled={loading || busy || connection !== "CONNECTED"}/><div className="upgrade2-run-actions"><button type="button" disabled={item.run_id !== run.run_id || item.status !== "PUBLISHED" || item.verification_status !== "VERIFIED" || !available("OPEN_ARTIFACT") || !props.onOpenArtifact} onClick={() => props.onOpenArtifact?.(item.artifact_id, item.version)}>打开成果</button><button type="button" disabled={item.run_id !== run.run_id || item.status !== "PUBLISHED" || item.verification_status !== "VERIFIED" || !available("EXPORT_ARTIFACT") || !props.onExportArtifact} onClick={() => props.onExportArtifact?.(item.artifact_id, item.version)}>导出成果</button></div></li>)}</ul> : <p>{run.projection_ready === false ? "尚未取得成果信息。" : "当前没有已记录的成果。"}</p>}</section>
    </aside></div>
  </section>;
}

export function DomainIntentContent({domain}:{domain:DomainIntentPreview}) {
  return <><dl className="upgrade2-run-facts"><div><dt>业务动作</dt><dd>{ {"boss.meeting.confirm":"确认会议安排","boss.meeting.cancel":"取消会议","boss.meeting.held":"确认会议已举行","boss.minutes.confirm":"确认会议纪要","boss.minutes.assignment.create":"由纪要创建交办","boss.assignment.create":"创建交办"}[domain.action]}</dd></div><div><dt>目标版本</dt><dd>{domain.goal_revision}</dd></div><div><dt>业务对象</dt><dd>{domain.object_id} · 版本 {domain.object_revision}</dd></div></dl>
    {(domain.action==="boss.meeting.cancel"||domain.action==="boss.meeting.held")&&<p>会议开始时间 {String(domain.details.starts_at)} · 本人决定依据 {String(domain.details.reason)}。{domain.action==="boss.meeting.held"?"服务按业务时钟核查会议是否可以确认举行。":""}</p>}
    <h4>本人审阅内容</h4><BIRecordContent value={domain.details}/><h4>本次操作内容</h4><BIRecordContent value={domain.params}/>
    {domain.action==="boss.meeting.confirm"&&domain.impact&&<p>私人日程冲突：{(domain.impact.private_calendar as {conflict:boolean}).conflict?"存在":"当前未发现"}；关联行程：{(domain.impact.overlapping_travel_ids as string[]).join("、")||"当前未发现"}。</p>}
    {domain.impact!==null&&<><h4>安排影响</h4><BIRecordContent value={domain.impact}/></>}
  </>;
}

export function SourceList({sources, onOpenSource, disabled}: {sources: readonly Upgrade2Source[]; onOpenSource?: (source: Upgrade2Source) => void; disabled: boolean}) {
  return sources.length > 0 ? <ul className="upgrade2-run-sources">{sources.map((source, index) => <li key={source.source_id + ":" + source.revision + ":" + index}><button type="button" disabled={disabled || !onOpenSource} onClick={() => onOpenSource?.(source)}>来源 {source.source_id} · 版本 {source.revision} · {source.locator}</button>{"classification" in source && typeof source.classification === "string" && <><p>来源类型 {source.classification}</p><p>原文位置未经核查；可在成果列表查看引用版本。</p></>}{"sha256" in source && typeof source.sha256 === "string" && <p>来源摘要 {source.sha256}</p>}</li>)}</ul> : <p>当前没有来源引用。</p>;
}
