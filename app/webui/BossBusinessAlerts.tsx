import {useEffect,useState} from "react";
import {useClient} from "@/providers/ClientProvider";
import {useTransaction} from "./BossAssignmentFlow";
import {BossNativeNotification} from "./BossDesktopNotifications";

type Row=Record<string,unknown>;
type Configuration={threshold_pp:string;duration_seconds:number;recovery_seconds:number;check_interval_seconds:number;cooldown_seconds:number;timezone:"Asia/Shanghai";quiet_start:number;quiet_end:number;important_escalation:boolean;notify_recovery:boolean};
type Rule={version:string;state:string;configuration:Configuration;created_by_role:string};
type Definition={definition_version:string;seed:number;event_id:string;frames:string[];configuration:Configuration;description:string};
type RuleRead={source_type:"SIMULATED";definition:Definition;draft:Rule|null;active:Rule|null;active_version:string};
type Facts={base_value:string|null;current_value:string|null;change_pp:string|null;unit:string;change_unit:string;comparison_periods:{BASE:string[];CURRENT:string[]};scope:string;metric_data_as_of:string;complete:boolean;confidence:string;handler_id:string|null;impact:string;impact_amount:string|null;impact_currency:string|null;participation:string;participation_reason:string;frame:string};
export type BusinessAlert={event_id:string;event_version:string;episode:number;state:string;facts:Facts|null;observed_at:string;data_as_of:string|null;adoption_state:string;sources:Row[];documents:Row[];evaluation:{phase:string;reason:string;duration_seconds:number|null;condition_since?:string};business_rule:Rule|null;rule_state:string;technical_rule_version:string|null;owner_notice_version:string|null;reminder:{state:string;until?:string|null}|null;reminder_version:string;notification:Row|null;summary:Row|null;existing_measures:Row[];meeting_reference:{meeting_id:string;version:string;adoption_state:string};review_sha256:string;missing_fields:string[];dispatch_history:Row[];recovery_history:Row[];actions:Row[];meeting_links:Row[];assignment_references:Row[]};
export type BusinessAlertRead={source_type:"SIMULATED";business_clock:string;items:BusinessAlert[];coverage_state:string;missing_sources:string[];execution_owner:"CronService"};
type AlertAction="boss.alert.ack"|"boss.alert.snooze"|"boss.alert.close"|"boss.alert.meeting.link"|"boss.alert.assignment.create";
type RuleAction="boss.alert.rule.save"|"boss.alert.rule.validate"|"boss.alert.rule.activate"|"boss.alert.rule.disable"|"boss.simulation.alert.rule.save"|"boss.simulation.alert.rule.validate"|"boss.simulation.alert.rule.activate"|"boss.simulation.alert.rule.disable";
const value=(item:unknown)=>item===null||item===undefined||item===""?"未知":typeof item==="boolean"?(item?"符合":"未符合"):String(item);
function Fact({label,item}:{label:string;item:unknown}){return <div className="boss-kv"><span>{label}</span><strong>{value(item)}</strong></div>;}
function Records({title,rows,fields}:{title:string;rows:Row[];fields:string[]}){return <details className="boss-alert-records"><summary>{title} · {rows.length} 项</summary>{rows.map((row,index)=><article className="boss-workspace-item" key={index}>{fields.map(field=><Fact key={field} label={field} item={row[field]}/>)}</article>)}{!rows.length&&<p className="boss-helper">当前没有已保存记录。</p>}</details>;}
function useRead<T>(path:string,revision:number){
  const {getToken,token}=useClient(),[data,setData]=useState<T|null>(null),[error,setError]=useState("");
  useEffect(()=>{const abort=new AbortController();setData(null);setError("");void fetch(path,{headers:{Authorization:"Bearer "+getToken()},cache:"no-store",signal:abort.signal}).then(async response=>{if(response.status===401)window.dispatchEvent(new Event("boss-auth-expired"));if(!response.ok)throw new Error("当前范围读取失败，HTTP "+response.status);return response.json() as Promise<T>;}).then(result=>{if(!abort.signal.aborted)setData(result);}).catch(failure=>{if(!abort.signal.aborted)setError(failure.message);});return()=>abort.abort();},[path,revision,token,getToken]);
  return {data,error};
}

export function BossBusinessAlertRules({role,revision=0,onSaved,onDirtyChange}:{role:"BOSS"|"MAINTAINER";revision?:number;onSaved?:()=>void;onDirtyChange?:(dirty:boolean)=>void}){
  const [generation,setGeneration]=useState(0),[configuration,setConfiguration]=useState<Configuration|null>(null),[dirty,setDirty]=useState(false);
  const {data,error}=useRead<RuleRead>("/api/boss/ui/business-alert-rules",revision+generation);
  const transaction=useTransaction(()=>{setDirty(false);setGeneration(item=>item+1);onSaved?.();},undefined,undefined,"alertRules");
  useEffect(()=>{if(data&&!dirty)setConfiguration(data.draft?.configuration??data.active?.configuration??data.definition.configuration);},[data,dirty]);
  useEffect(()=>{onDirtyChange?.(dirty||transaction.busy);},[dirty,transaction.busy,onDirtyChange]);
  const prefix=role==="BOSS"?"boss.alert.rule.":"boss.simulation.alert.rule.";
  function propose(action:"save"|"validate"|"activate"|"disable"){
    if(!data||!configuration||transaction.busy)return;
    const payload=action==="save"?{expected_version:data.draft?.version??"0",configuration}:action==="activate"?{expected_version:data.draft?.version??"0",expected_active_version:data.active_version}:{expected_version:action==="disable"?data.active_version:data.draft?.version??"0"};
    transaction.propose((prefix+action) as RuleAction,payload,{save:"保存经营关注规则草稿",validate:"校验当前经营关注草稿",activate:"确认启用经营关注规则",disable:"确认停用经营关注规则"}[action],["当前身份："+role,"当前草稿版本："+(data.draft?.version??"0"),"有效版本："+data.active_version,"参数："+JSON.stringify(configuration),role==="BOSS"?"本人启用与停用分别保存当前范围授权。":"维护仅能使用已授权演示定义中的完整参数。","保存和校验不会自动启用，不改变技术调度及本人通知设置。"]);
  }
  function edit<K extends keyof Configuration>(field:K,item:Configuration[K]){setConfiguration(old=>old?{...old,[field]:item}:old);setDirty(true);}
  return <section className="boss-panel boss-fc04-reminders" aria-label="经营关注规则">
    <header className="boss-panel-head"><h2>经营关注规则</h2><span className="boss-tag boss-tag-amber">SIMULATED</span></header>
    {error&&<p role="alert" className="boss-status boss-status-error">{error}</p>}
    <p>草稿 {data?.draft?.version??"尚未保存"} · {data?.draft?.state??"未保存"}；有效版本 {data?.active_version??"读取中"} · {data?.active?.state??"未启用"}</p>
    {configuration&&<fieldset className="boss-fc04-fieldset" disabled={transaction.busy||role==="MAINTAINER"}><div className="boss-form-grid">
      <label>毛利率下降阈值（百分点）<input value={configuration.threshold_pp} onChange={event=>edit("threshold_pp",event.target.value)}/></label>
      {([["duration_seconds","异常持续时间（秒）"],["recovery_seconds","恢复持续时间（秒）"],["check_interval_seconds","观察间隔（秒）"],["cooldown_seconds","提醒冷却时间（秒）"],["quiet_start","免打扰开始小时"],["quiet_end","免打扰结束小时"]] as const).map(([field,label])=><label key={field}>{label}<input type="number" min="0" step="1" value={configuration[field]} onChange={event=>edit(field,Number(event.target.value))}/></label>)}
      <label>业务时区<input readOnly value={configuration.timezone}/></label>
      <label className="boss-confirm-check"><input type="checkbox" checked={configuration.important_escalation} onChange={event=>edit("important_escalation",event.target.checked)}/>允许重要事项按规则升级</label>
      <label className="boss-confirm-check"><input type="checkbox" checked={configuration.notify_recovery} onChange={event=>edit("notify_recovery",event.target.checked)}/>恢复条件满足时保存恢复通知</label>
    </div></fieldset>}
    <p className="boss-helper">{role==="MAINTAINER"?"维护使用工单授权的固定演示参数。本人自定义草稿和规则正文不会返回维护端。":"本人规则、技术规则与本人通知设置分别生效；免打扰升级需要当前全部条件满足。"}</p>
    {transaction.notice&&<p role="status">{transaction.notice}</p>}
    <div className="boss-actions">
      <button className="boss-btn" disabled={!data||transaction.busy} onClick={()=>propose("save")}>保存经营规则草稿</button>
      <button className="boss-btn" disabled={!data?.draft||data.draft.state!=="DRAFT"||dirty||transaction.busy} onClick={()=>propose("validate")}>校验经营规则草稿</button>
      <button className="boss-btn boss-btn-primary" disabled={!data?.draft||data.draft.state!=="VALIDATED"||dirty||transaction.busy} onClick={()=>propose("activate")}>确认启用经营规则</button>
      <button className="boss-btn" disabled={!data?.active||data.active.state!=="ACTIVE"||dirty||transaction.busy} onClick={()=>propose("disable")}>停用经营规则</button>
      <button className="boss-btn" disabled={transaction.busy} onClick={()=>{setDirty(false);setGeneration(item=>item+1);}}>放弃编辑并读取经营规则</button>
    </div>{transaction.dialog}{transaction.recovery}
  </section>;
}

export function BossBusinessAlertAdministration({onDirtyChange}:{onDirtyChange?:(dirty:boolean)=>void}){
  const [revision,setRevision]=useState(0),[frame,setFrame]=useState(""),[dirty,setDirty]=useState(false),[ruleDirty,setRuleDirty]=useState(false);
  const {data,error}=useRead<{source_type:"SIMULATED";definition:Definition;event_version:string;business_clock:string}>("/api/boss/ui/admin/business-alert-input",revision);
  const transaction=useTransaction(()=>{setDirty(false);setFrame("");setRevision(item=>item+1);},undefined,undefined,"alertInput");
  useEffect(()=>{onDirtyChange?.(dirty||ruleDirty||transaction.busy);},[dirty,ruleDirty,transaction.busy,onDirtyChange]);
  function load(){if(!data||!frame||transaction.busy)return;transaction.propose("boss.simulation.alert.load",{expected_version:data.event_version,mode:"SIMULATED",definition_version:data.definition.definition_version,seed:data.definition.seed,frame},"载入当前获准经营观察",["输入定义："+data.definition.definition_version,"当前事件版本："+data.event_version,"观察类型："+frame,"当前业务时钟："+data.business_clock,"观察来自当前获准明细与明确生成定义，不授予本人决定权限，不声明实际企业情况。"]);}
  return <div className="boss-alert-administration"><BossBusinessAlertRules role="MAINTAINER" onDirtyChange={setRuleDirty}/><section className="boss-panel boss-fc04-reminders" aria-label="经营提醒演示输入">
    <h2>经营提醒演示输入</h2><p>{data?.definition.description??"正在读取获准输入定义。"}</p>
    {error&&<p role="alert">{error}</p>}<Fact label="业务时钟" item={data?.business_clock}/><Fact label="当前事件版本" item={data?.event_version}/>
    <label className="boss-label">获准观察类型<select aria-label="获准观察类型" disabled={transaction.busy} value={frame} onChange={event=>{setFrame(event.target.value);setDirty(true);}}><option value="">请选择观察类型</option>{data?.definition.frames.map(item=><option key={item} value={item}>{item}</option>)}</select></label>
    <p className="boss-helper">每次载入保存当前时钟的一次观察。持续时间必须有完整间隔的连续依据；技术时钟通过已有 A04 页面明确推进。</p>
    {transaction.notice&&<p role="status">{transaction.notice}</p>}<div className="boss-actions"><button className="boss-btn" disabled={!data||!frame||transaction.busy} onClick={load}>核查并载入经营观察</button><button className="boss-btn" disabled={transaction.busy} onClick={()=>{setFrame("");setDirty(false);setRevision(item=>item+1);}}>放弃选择并读取输入状态</button></div>{transaction.dialog}{transaction.recovery}
  </section></div>;
}

export function BossBusinessAlerts({projection,revision,onReload,onNavigate,onOpenTask,onDirtyChange}:{projection:BusinessAlertRead;revision:number;onReload:()=>void;onNavigate:(page:string)=>void;onOpenTask?:(taskId:string)=>void;onDirtyChange?:(dirty:boolean)=>void}){
  const [ruleDirty,setRuleDirty]=useState(false),[dirty,setDirty]=useState(false),[purpose,setPurpose]=useState(""),[due,setDue]=useState(""),[evidence,setEvidence]=useState(""),[until,setUntil]=useState(""),[error,setError]=useState("");
  const transaction=useTransaction(()=>{setDirty(false);setPurpose("");setDue("");setEvidence("");setUntil("");onReload();},undefined,undefined,"alerts");
  useEffect(()=>{onDirtyChange?.(dirty||ruleDirty||transaction.busy);},[dirty,ruleDirty,transaction.busy,onDirtyChange]);
  function decide(event:BusinessAlert,action:AlertAction){
    if(transaction.busy)return;setError("");const fields:Row={event_id:event.event_id,event_version:event.event_version,expected_version:event.reminder_version,review_sha256:event.review_sha256};
    if(action==="boss.alert.snooze"){if(!until){setError("请选择暂缓截止时间。");return;}fields.until=until+":00+08:00";}
    if(action==="boss.alert.meeting.link"){fields.meeting_id=event.meeting_reference.meeting_id;fields.meeting_version=event.meeting_reference.version;}
    if(action==="boss.alert.assignment.create"){if(!purpose.trim()||!due||!evidence.trim()||!event.facts?.handler_id){setError("交办需要当前处理人、用途、期限和产物。");return;}Object.assign(fields,{purpose:purpose.trim(),coordinator_id:event.facts.handler_id,due_at:due+":00+08:00",timezone:"Asia/Shanghai",evidence_requirements:evidence.split("\n").map(item=>item.trim()).filter(Boolean)});}
    transaction.propose(action,fields,{"boss.alert.ack":"确认知晓当前经营提醒","boss.alert.snooze":"确认暂缓当前经营提醒","boss.alert.close":"确认关闭当前经营提醒","boss.alert.meeting.link":"关联当前会议与经营事项","boss.alert.assignment.create":"从当前经营提醒创建交办"}[action],["事件："+event.event_id+" v"+event.event_version,"提醒版本："+event.reminder_version,"经营规则："+value(event.business_rule?.version)+" · "+event.rule_state,"当前检查摘要："+event.review_sha256,...Object.entries(fields).filter(([key])=>!["review_sha256","event_id","event_version","expected_version"].includes(key)).map(([key,item])=>key+"："+value(item)),"提醒、源事件、任务期限与会议安排分别保存。会议关联不安排或发送；新交办为 OPEN，发送需要再次明确确认。"]);
  }
  return <div className="boss-fc04-reminders"><BossBusinessAlertRules role="BOSS" revision={revision} onSaved={onReload} onDirtyChange={setRuleDirty}/>
    <section className="boss-panel" aria-label="当前经营提醒详情"><header className="boss-panel-head"><h2>当前经营事项</h2><span className="boss-tag boss-tag-amber">SIMULATED</span></header>
      <Fact label="当前业务时钟" item={projection.business_clock}/><Fact label="执行服务" item={projection.execution_owner}/><p className="boss-helper">当前资料范围 {projection.coverage_state}。{projection.missing_sources.join("；")}</p>
      {!projection.items.length&&<p>当前范围没有已载入的经营观察。</p>}
      {projection.items.map(event=>{const facts=event.facts,available=event.adoption_state==="CURRENT"&&event.state!=="CANCELED",open=Boolean(event.reminder&&event.reminder.state!=="CLOSED");return <article key={event.event_id} className="boss-alert-detail" id={"boss-notification-"+encodeURIComponent(event.event_id)} tabIndex={-1}>
        <h3>{event.event_id} · v{event.event_version}</h3><Fact label="当前来源采用" item={event.adoption_state}/><Fact label="源事件状态" item={event.state}/><Fact label="资料截至时间" item={event.data_as_of}/><Fact label="业务观察时间" item={event.observed_at}/>
        {facts&&<><Fact label="指标与比较单位" item={"gross_margin · "+facts.unit+" / "+facts.change_unit}/><Fact label="比较期间 BASE" item={facts.comparison_periods.BASE.join(" — ")}/><Fact label="比较期间 CURRENT" item={facts.comparison_periods.CURRENT.join(" — ")}/><Fact label="BASE 毛利率" item={facts.base_value}/><Fact label="CURRENT 毛利率" item={facts.current_value}/><Fact label="变化百分点" item={facts.change_pp}/><Fact label="指标范围" item={facts.scope}/><Fact label="影响等级" item={facts.impact}/><Fact label="影响金额" item={facts.impact_amount}/><Fact label="金额币种" item={facts.impact_currency}/><Fact label="资料完整" item={facts.complete}/><Fact label="演示可信标记" item={facts.confidence}/><Fact label="当前处理人" item={facts.handler_id}/><Fact label="本人参与条件" item={facts.participation}/><p>{facts.participation_reason}</p></>}
        <Fact label="当前判断" item={event.evaluation.phase}/><Fact label="判断原因" item={event.evaluation.reason}/><Fact label="有依据的持续时间（秒）" item={event.evaluation.duration_seconds}/><Fact label="条件开始时间" item={event.evaluation.condition_since}/><Fact label="经营规则版本" item={value(event.business_rule?.version)+" · "+event.rule_state}/><Fact label="技术规则版本" item={event.technical_rule_version}/><Fact label="本人通知设置版本" item={event.owner_notice_version}/><Fact label="提醒状态" item={event.reminder?.state}/><Fact label="提醒版本" item={event.reminder_version}/><Fact label="暂缓截止" item={event.reminder?.until}/><Fact label="通知中心状态" item={event.notification?.state}/><Fact label="进展汇总状态" item={event.summary?.state}/>
        <p className="boss-helper">缺少条件：{event.missing_fields.join("；")||"当前没有缺少条件"}。影响金额未知时保持未知。</p>
        <Records title="来源版本与有效状态" rows={event.sources} fields={["source_id","version","status","sha256"]}/>
        {event.documents.map(document=><details className="boss-alert-records" key={String(document.source_id)}><summary>当前获准原文 · {value(document.source_id)} · v{value(document.version)}</summary><p className="boss-alert-source">{value(document.content)}</p></details>)}
        <Records title="已有处理措施" rows={event.existing_measures} fields={["kind","task_id","plan_id","version","status","state","coordinator_id","due_at","until","authorization_revoked"]}/>
        {event.notification&&available&&<BossNativeNotification eventId={event.event_id} eventVersion={event.event_version}/>}
        <div className="boss-actions"><button className="boss-btn" disabled={!open||!available||transaction.busy} onClick={()=>decide(event,"boss.alert.ack")}>知晓当前经营提醒</button><button className="boss-btn" disabled={!open||transaction.busy} onClick={()=>decide(event,"boss.alert.close")}>关闭当前经营提醒</button></div>
        <fieldset className="boss-fc04-fieldset" disabled={!open||!available||transaction.busy}>
          <label>经营提醒暂缓至（Asia/Shanghai）<input type="datetime-local" value={until} onChange={change=>{setUntil(change.target.value);setDirty(true);}}/></label><div className="boss-actions"><button className="boss-btn" onClick={()=>{setUntil(new Date(Date.parse(projection.business_clock)+30*60000+8*3600000).toISOString().slice(0,16));setDirty(true);}}>选择业务时钟之后三十分钟</button><button className="boss-btn" disabled={!until} onClick={()=>decide(event,"boss.alert.snooze")}>确认暂缓经营提醒</button></div>
          <Fact label="当前会议及版本" item={event.meeting_reference.meeting_id+" v"+event.meeting_reference.version+" · "+event.meeting_reference.adoption_state}/><button className="boss-btn" disabled={event.meeting_reference.adoption_state!=="CURRENT"} onClick={()=>decide(event,"boss.alert.meeting.link")}>将当前事项关联会议</button>
          <h3>从当前事项交办</h3><Fact label="唯一负责人" item={facts?.handler_id}/><label>经营交办用途<textarea value={purpose} onChange={change=>{setPurpose(change.target.value);setDirty(true);}}/></label><label>经营交办期限（Asia/Shanghai）<input type="datetime-local" value={due} onChange={change=>{setDue(change.target.value);setDirty(true);}}/></label><label>经营交办产物（每行一项）<textarea value={evidence} onChange={change=>{setEvidence(change.target.value);setDirty(true);}}/></label><button className="boss-btn" disabled={!purpose.trim()||!due||!evidence.trim()||!facts?.handler_id||event.assignment_references.some(row=>row.episode===event.episode)} onClick={()=>decide(event,"boss.alert.assignment.create")}>核查并创建经营交办</button>
        </fieldset>
        {event.assignment_references.map(reference=><div className="boss-actions" key={String(reference.task_id)}><span>关联任务 {value(reference.task_id)} · v{value(reference.task_version)}</span><button className="boss-btn" onClick={()=>onOpenTask?.(String(reference.task_id))}>打开关联交办</button></div>)}
        <Records title="会议关联" rows={event.meeting_links} fields={["meeting_id","meeting_version","event_version","created_at"]}/><Records title="已保存本人动作" rows={event.actions} fields={["action","event_version","version","authorization_id","business_at"]}/><Records title="调度与抑制记录" rows={event.dispatch_history} fields={["event_version","state","reason","business_at","business_rule_version","rule_version","owner_notice_version"]}/><Records title="恢复记录" rows={event.recovery_history} fields={["event_version","state","business_at","recovered_at","episode"]}/>
      </article>;})}
      {error&&<p role="alert" className="boss-status boss-status-error">{error}</p>}{transaction.notice&&<p role="status">{transaction.notice}</p>}
      <div className="boss-actions"><button className="boss-btn" disabled={transaction.busy} onClick={()=>{setDirty(false);setPurpose("");setDue("");setEvidence("");setUntil("");onReload();}}>放弃经营提醒编辑并读取当前状态</button><button className="boss-btn" onClick={()=>onNavigate("N08")}>查看本人通知设置</button><button className="boss-btn" onClick={()=>onNavigate("N09")}>查看本人计划</button></div>
    </section>{transaction.dialog}{transaction.recovery}
  </div>;
}
