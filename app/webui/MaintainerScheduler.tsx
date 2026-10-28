import { useEffect, useRef, useState } from "react";
import {
  AlertCircle, CheckCircle2, Clock3, FileCheck2, Loader2,
  PauseCircle, PlayCircle, RefreshCw, ShieldCheck, XCircle,
} from "lucide-react";
import { useClient } from "@/providers/ClientProvider";
import {useTransaction} from "./BossAssignmentFlow";
import {BossBusinessAlertAdministration} from "./BossBusinessAlerts";
import {deliveredPage} from "./delivered-navigation";
import {CurrentBusinessRecords,type CurrentBusinessRecord} from "./MaintainerCurrentFacts";

type Schedule = {
  schedule_id:string;version:string;schedule_version:string;timezone:string;
  trigger:string;enabled:boolean;canceled:boolean;active_draft_version?:string;
  name:string;executor_component:string;expression:string;authorized_scope:string[];restart_policy:string;
};
type Rules = {
  version:string;quiet_start:number;quiet_end:number;
  cooldown_seconds:number;important_escalation:boolean;timezone:string;
};
type Configuration = Omit<Rules,"version"> & {trigger:string;name:string;executor_component:string;expression:string;authorized_scope:string[];restart_policy:string};
type Draft = {
  draft_id:string;version:string;configuration:Configuration;
  validation_state:"DRAFT"|"VALIDATED"|"ACTIVE";
  saved_at:string;validated_at:string|null;activated_at:string|null;
};
type Runtime = {
  state:string;active_run_count:number;resume_checked_at:string|null;quit_behavior:string;
  schedule_version?:string;started_at?:string|null;
};
type Scheduler = {
  current_events:CurrentBusinessRecord[];
  source_type:"SIMULATED";projection:"scheduler";schedule:Schedule;
  draft:Draft|null;rules:Rules|null;simulated_business_time:string;
  recent_dispatches:{event_id:string;event_version:string;state:string;
    reason?:string;business_at:string}[];
  cron_runtime_verified_here:boolean;next_run_time:string|null;
  executors:{id:string;label:string}[];authorized_scopes:{id:string;label:string}[];
  restart_policies:{id:string;label:string}[];runtime:Runtime;
  manual_dispatch_supported_here:boolean;external_delivery_verified:false;
  available_manual_events:{event_id:string;version:string;due_at:string;state:string}[];
};
type SchedulerAction="boss.scheduler.draft.save"|"boss.scheduler.draft.validate"|"boss.scheduler.activate"|"boss.scheduler.manual_run"|"boss.scheduler.pause"|"boss.scheduler.resume"|"boss.scheduler.cancel";

const DEFAULT:Configuration = {
  trigger:"EVENT_OR_TIME",timezone:"Asia/Shanghai",
  quiet_start:22,quiet_end:7,cooldown_seconds:1800,
  important_escalation:false,
  name:"",executor_component:"",expression:"",authorized_scope:[],restart_policy:"",
};
function Kv({label,value}:{label:string;value:string|number|boolean|null|undefined}) {
  return <div className="boss-kv"><span>{label}</span><strong>{
    value===null||value===undefined?"未知":String(value)
  }</strong></div>;
}
function scheduleState(data:Scheduler|null):string {
  if(!data)return "尚未读取";
  if(data.schedule.canceled)return "已取消";
  return data.schedule.enabled?"运行中":"已暂停";
}
function adoptedVersion(data:Scheduler|null):string {
  if(!data)return "尚未读取";
  if(data.runtime.state==="NOT_ATTACHED")return "未连接执行责任组件";
  if(!data.runtime.schedule_version)return "运行组件未报告采用版本";
  if(data.runtime.schedule_version!==data.schedule.version)
    return `待生效（运行组件仍采用 v${data.runtime.schedule_version}）`;
  return `已采用 v${data.runtime.schedule_version}`;
}
function timezoneValid(timezone:string):boolean {
  try{new Intl.DateTimeFormat("en-US",{timeZone:timezone});return true;}catch{return false;}
}
function configurationError(cfg:Configuration,data:Scheduler|null):string {
  if(!data)return "调度配置尚未读取";
  if(!cfg.name.trim())return "计划名称不能为空";
  if(!data.executors.some(row=>row.id===cfg.executor_component))
    return "唯一执行责任组件必须从当前可选组件中选择";
  if(cfg.trigger!=="EVENT"&&!cfg.expression.trim())return "当前触发条件需要填写调度表达式";
  if(!timezoneValid(cfg.timezone))return "IANA 时区无效，请填写例如 Asia/Shanghai";
  if(!cfg.restart_policy)return "请选择重启恢复行为";
  if(!cfg.authorized_scope.length)return "至少选择一个获准任务范围";
  return "";
}

export function MaintainerScheduler({onNavigate,onDirtyChange}:{onNavigate:(page:string)=>void;onDirtyChange?:(dirty:boolean)=>void}) {
  const {getToken,token}=useClient();
  const [data,setData]=useState<Scheduler|null>(null);
  const [cfg,setCfg]=useState<Configuration>(DEFAULT);
  const [dirty,setDirty]=useState(false);
  const [revision,setRevision]=useState(0);
  const [loading,setLoading]=useState(false);
  const [error,setError]=useState("");
  const [selectedEvent,setSelectedEvent]=useState("");
  const [alertDirty,setAlertDirty]=useState(false);
  const manualPanel=useRef<HTMLDetailsElement>(null);
  const reload=()=>setRevision(v=>v+1);
  const transaction=useTransaction(()=>{setDirty(false);onDirtyChange?.(false);reload();},undefined,undefined,"scheduler");
  const busy=transaction.busy,notice=transaction.notice;
  useEffect(()=>{onDirtyChange?.(dirty||busy||alertDirty);},[dirty,busy,alertDirty,onDirtyChange]);
  useEffect(()=>{
    const abort=new AbortController();
    const token=getToken();
    if(!token){setError("技术维护身份已失效");return;}
    setLoading(true);setError("");
    void fetch("/api/boss/ui/workspace/scheduler",{
      headers:{Authorization:"Bearer "+token},
      cache:"no-store",signal:abort.signal,
    }).then(async res=>{
      if(!res.ok)throw Error("无法读取有权调度配置（HTTP "+res.status+"）");
      const result=await res.json() as Scheduler;
      if(result.source_type!=="SIMULATED"||result.projection!=="scheduler")
        throw Error("调度配置来源无效");
      return result;
    }).then(result=>{
      if(abort.signal.aborted)return;
      setData(result);setLoading(false);
      setSelectedEvent(old=>result.available_manual_events.some(x=>x.event_id===old)?old:"");
      if(!dirty){
        setCfg(result.draft?.configuration||
          (result.rules?{
            trigger:result.schedule.trigger,timezone:result.schedule.timezone,
            name:result.schedule.name,executor_component:result.schedule.executor_component,
            expression:result.schedule.expression,authorized_scope:result.schedule.authorized_scope,
            restart_policy:result.schedule.restart_policy,
            quiet_start:result.rules.quiet_start,quiet_end:result.rules.quiet_end,
            cooldown_seconds:result.rules.cooldown_seconds,
            important_escalation:result.rules.important_escalation,
          }:DEFAULT));
      }
    }).catch(e=>{
      if(abort.signal.aborted)return;
      setError(e instanceof Error?e.message:String(e));setLoading(false);
    });
    return ()=>abort.abort();
  },[revision,getToken,token]);

  function edit<K extends keyof Configuration>(field:K,value:Configuration[K]){
    setCfg(old=>({...old,[field]:value}));setDirty(true);
  }
  function propose(action:string,payload:Record<string,unknown>,title:string,detail:string[]){
    if(busy||loading)return;
    setError("");transaction.propose(action as SchedulerAction,payload,title,detail);
  }

  function save(){
    if(!data)return;
    const invalid=configurationError(cfg,data);
    if(invalid){setError(invalid);return;}
    if([cfg.quiet_start,cfg.quiet_end,cfg.cooldown_seconds].some(
      x=>!Number.isInteger(x))||cfg.quiet_start<0||cfg.quiet_start>23||
      cfg.quiet_end<0||cfg.quiet_end>23||
      cfg.cooldown_seconds<0||cfg.cooldown_seconds>86400){
      setError("静默时间必须是0—23整数，冷却秒数为0—86400整数。");return;
    }
    propose("boss.scheduler.draft.save",{
      expected_version:data.draft?.version||"0",...cfg,
    },"保存调度配置草稿",[
      "当前草稿版本："+(data.draft?.version||"0"),
      "触发类型："+cfg.trigger,"时区："+cfg.timezone,
      "调度表达式："+cfg.expression,
      "唯一执行责任组件："+cfg.executor_component,
      "静默时段："+cfg.quiet_start+":00 — "+cfg.quiet_end+":00",
      "冷却去重："+cfg.cooldown_seconds+"秒",
      "重要升级："+String(cfg.important_escalation),
      "保存不会直接启用、发送业务消息或扩大老板授权。",
    ]);
  }
  function prepareValidate(){
    if(!data?.draft||data.draft.validation_state!=="DRAFT"||dirty){
      setError("只有已保存、未修改的 DRAFT 版本可以验证");return;
    }
    propose("boss.scheduler.draft.validate",{
      expected_version:data.draft.version,
    },"验证调度与授权条件",[
      "草稿："+data.draft.draft_id+" v"+data.draft.version,
      "核对表达式："+data.draft.configuration.expression,
      "核对时区："+data.draft.configuration.timezone,
      "核对唯一执行责任组件："+data.draft.configuration.executor_component,
      "核对事件范围与当前有效授权；验证结果绑定该草稿版本。",
      "验证不会启用调度，也不会产生业务动作。",
    ]);
  }
  function prepareActivate(){
    if(!data?.draft||data.draft.validation_state!=="VALIDATED"||dirty){
      setError("启用前须先保存并通过验证");return;
    }
    if(!data.rules){setError("当前没有可核对的提醒规则版本，不能启用");return;}
    if(data.schedule.canceled){setError("已取消的原计划不能重新启用");return;}
    propose("boss.scheduler.activate",{
      expected_draft_version:data.draft.version,
      expected_schedule_version:data.schedule.version,
      expected_rules_version:data.rules.version,
    },"启用此调度版本",[
      "当前技术计划："+data.schedule.schedule_id+" v"+data.schedule.version,
      "已验证草稿版本："+data.draft.version,
      "提醒规则版本："+data.rules.version,
      "启用后下一次触发：待核查（当前页面未核实执行责任组件）。",
      "影响范围：只改变本机事件调度与通知规则，不发送真实外部消息，也不授予老板业务动作。",
      "回执后重新读取，核对运行组件实际采用的版本。",
    ]);
  }
  function prepareManualRun(){
    if(!data?.manual_dispatch_supported_here||data.schedule.canceled){
      setError("当前没有获准可用的模拟技术调度器");return;
    }
    const event=data.available_manual_events.find(x=>x.event_id===selectedEvent);
    if(!event){setError("先选择当前批准的数据集事件");return;}
    propose("boss.scheduler.manual_run",{
      event_id:event.event_id,event_version:event.version,
      expected_schedule_version:data.schedule.version,
      expected_rules_version:data.rules?.version||"0",
    },"立即触发一次获准检查",[
      "本次触发输入："+event.event_id+" v"+event.version,
      "到期时间："+event.due_at,
      "当前模拟时钟："+data.simulated_business_time,
      "授权范围："+(data.schedule.authorized_scope.map(id=>data.authorized_scopes.find(row=>row.id===id)?.label??id).join("、")||"没有获准范围"),
      "技术计划："+data.schedule.schedule_id+" v"+data.schedule.version,
      "本次触发与定时触发共享同一去重规则；未到期显示 NOT_DUE，已送达的版本被抑制。",
      "不接入实际外部通知，不给维护者添加老板业务授权。",
    ]);
  }
  function updateStatus(action:"pause"|"resume"|"cancel"){
    if(!data)return;
    propose("boss.scheduler."+action,{
      expected_version:data.schedule.version,
    },action==="cancel"?"取消此调度计划":action==="pause"?"暂停后续触发":"恢复后续触发",[
      "计划："+data.schedule.schedule_id+" v"+data.schedule.version,
      action==="cancel"?"取消与暂停不同：取消后不能恢复，后续不再触发；已执行结果、历史运行与回执继续保留。":
        action==="pause"?"暂停只抑制后续触发，不删除已有事件，也不撤销已经执行的结果。":
          "恢复会重新核查当前授权与错过触发规则；不会自动补执行历史写入。",
      "不会代老板确认任务完成或模拟真实消息送达。",
    ]);
  }
  function openManual(){if(manualPanel.current){manualPanel.current.open=true;manualPanel.current.scrollIntoView({block:"center",behavior:"smooth"});document.getElementById("boss-scheduler-event")?.focus();}}
  const manualHint=!data?"调度配置尚未读取"
    :data.schedule.canceled?"此计划已取消，不能再触发"
      :!data.manual_dispatch_supported_here?"立即触发需要已验证并启用的调度版本；当前不满足"
        :busy?"操作处理中":dirty?"有未保存的配置修改，先保存或放弃":"";
  const activateHint=busy||loading?"操作处理中，请等待当前读取或操作完成"
    :!data?"调度配置尚未读取"
      :data.schedule.canceled?"此计划已取消，不能再启用"
        :!data.draft?"当前没有已保存的调度草稿，先保存技术配置"
          :data.draft.validation_state!=="VALIDATED"?"当前草稿尚未通过验证，先选择“验证调度与授权条件”"
            :dirty?"草稿有未保存修改，先保存或放弃":"";
  const operationHint=busy?"操作处理中":loading?"调度状态读取中":dirty?"有未保存的配置修改，先保存或放弃":"";
  const validateHint=dirty?"草稿有未保存修改，验证前需要先保存"
    :!data?.draft?"当前没有已保存的调度草稿，先保存技术配置"
      :data.draft.validation_state!=="DRAFT"?`当前草稿状态为 ${data.draft.validation_state}，不能重复验证`
        :"";
  return <div className="boss-scheduler-workspace">
    {data&&<CurrentBusinessRecords records={data.current_events} title="当前业务事件与期限"/>}
    <div className="boss-workspace-toolbar">
      <div className="boss-workspace-note"><span className="boss-tag boss-tag-amber">SIMULATED · TECH ONLY</span>
        A13 · 版本化调度草稿与运行开关
      </div>
      <button type="button" className="boss-btn" disabled={loading||busy} aria-busy={loading} onClick={reload}>
        {loading?<Loader2 size={15} className="boss-spin"/>:<RefreshCw size={15}/>} {loading?"刷新中…":"刷新调度状态"}
      </button>
    </div>
    {loading&&<div className="boss-status"><Loader2 className="boss-spin" size={15}/>正在读取调度配置、执行责任与实际采用版本…</div>}
    {error&&<div role="alert" className="boss-status boss-status-error"><AlertCircle size={16}/>{error}</div>}
    {notice&&<div role="status" className="boss-status boss-status-ok"><CheckCircle2 size={16}/>{notice}</div>}
    <div className="boss-columns">
      <div className="boss-column">
        <section className="boss-panel">
          <div className="boss-panel-head"><h2>调度状态</h2><small>配置、执行责任与实际采用分别判断</small></div>
          <Kv label="计划状态" value={scheduleState(data)}/>
          <Kv label="计划版本" value={data?`v${data.schedule.version}`:null}/>
          <Kv label="唯一执行责任组件" value={data?data.executors.find(row=>row.id===data.schedule.executor_component)?.label??data.schedule.executor_component:null}/>
          <Kv label="实际采用版本" value={adoptedVersion(data)}/>
          <Kv label="最近心跳" value={data?.runtime.resume_checked_at??"运行组件未报告"}/>
          <Kv label="下一次触发" value={data?(data.cron_runtime_verified_here?data.next_run_time??"运行组件未报告":"待核查（当前页面未核实执行责任组件）"):null}/>
          <Kv label="IANA时区" value={data?.schedule.timezone}/>
          <Kv label="调度表达式" value={data?.schedule.expression}/>
          <Kv label="授权范围" value={data?.schedule.authorized_scope.map(id=>data.authorized_scopes.find(row=>row.id===id)?.label??id).join("、")}/>
          <p className="boss-helper">下一次触发在核实现行执行责任前保持待核查；运行组件报告的原始时间见调度证据区，不能据此推算确定的业务执行时间。</p>
        </section>
        <section className="boss-panel">
          <div className="boss-panel-head"><h2>技术计划配置</h2><small>保存与验证分开执行</small></div>
          <fieldset className="boss-fc04-fieldset" disabled={busy||loading||!data}><div className="boss-form-grid">
            <label>计划名称<input value={cfg.name??""} onChange={event=>edit("name",event.target.value)}/></label>
            <label>唯一执行责任组件<select value={cfg.executor_component??""} onChange={event=>edit("executor_component",event.target.value)}><option value="">请选择</option>{data?.executors?.map(row=><option key={row.id} value={row.id}>{row.label}</option>)}</select></label>
            <label>触发条件<select value={cfg.trigger}
              onChange={e=>edit("trigger",e.target.value)}>
              <option value="EVENT_OR_TIME">EVENT_OR_TIME · 事件或时间</option>
              <option value="CRON">定时计划</option><option value="EVENT">业务事件</option>
            </select></label>
            <label>IANA时区<input value={cfg.timezone} onChange={event=>edit("timezone",event.target.value)}/></label>
            <label>调度表达式<input disabled={cfg.trigger==="EVENT"} value={cfg.expression??""} onChange={event=>edit("expression",event.target.value)}/></label>
          </div></fieldset>
          <p className="boss-helper">调度表达式的可读解释与未来触发预览需要服务端计算，当前接口没有提供，页面不展示推算结果；保存与验证时由服务端核对表达式与时区。</p>
          {cfg.trigger==="EVENT"&&<p className="boss-helper">触发条件为业务事件时不使用调度表达式，因此表达式输入停用。</p>}
        </section>
        <section className="boss-panel">
          <div className="boss-panel-head"><h2>执行规则</h2><small>只在当前获准范围内生效</small></div>
          <fieldset className="boss-fc04-fieldset" disabled={busy||loading||!data}><div className="boss-form-grid">
            <label>重启恢复行为<select value={cfg.restart_policy??""} onChange={event=>edit("restart_policy",event.target.value)}><option value="">请选择</option>{data?.restart_policies?.map(row=><option key={row.id} value={row.id}>{row.label}</option>)}</select></label>
            <label>静默开始小时<input type="number" min="0" max="23" step="1"
              value={cfg.quiet_start} onChange={e=>edit("quiet_start",Number(e.target.value))}/></label>
            <label>静默结束小时<input type="number" min="0" max="23" step="1"
              value={cfg.quiet_end} onChange={e=>edit("quiet_end",Number(e.target.value))}/></label>
            <label>重复抑制冷却（秒）<input type="number" min="0" max="86400" step="1"
              value={cfg.cooldown_seconds} onChange={e=>edit("cooldown_seconds",Number(e.target.value))}/></label>
            <label>重要提醒升级
              <select value={String(cfg.important_escalation)}
                onChange={e=>edit("important_escalation",e.target.value==="true")}>
                <option value="false">关闭（默认）</option><option value="true">允许 IMPORTANT 事件升级</option>
              </select>
            </label>
          </div><fieldset className="boss-v7-check-list"><legend>获准任务范围</legend>{data?.authorized_scopes?.map(row=><label key={row.id}><input type="checkbox" checked={cfg.authorized_scope?.includes(row.id)??false} onChange={event=>edit("authorized_scope",event.target.checked?[...(cfg.authorized_scope??[]),row.id]:(cfg.authorized_scope??[]).filter(id=>id!==row.id))}/>{row.label}</label>)}</fieldset></fieldset>
          <div className="boss-status boss-status-warn"><Clock3 size={16}/>
            错过触发按所选重启恢复行为处理：{data?.restart_policies.find(row=>row.id===cfg.restart_policy)?.label??"尚未选择"}。
            暂停与重启都不自动补发历史消息；事件按稳定编号去重，重复触发只保留一次执行。
          </div>
          <div className="boss-actions">
            <button type="button" className="boss-btn boss-btn-primary" disabled={!data||busy||loading||!dirty}
              onClick={save}><FileCheck2 size={16}/> 保存计划草稿</button>
            <button type="button" className="boss-btn"
              disabled={!data?.draft||data.draft.validation_state!=="DRAFT"||dirty||busy||loading}
              onClick={prepareValidate}><ShieldCheck size={16}/> 验证调度与授权条件</button>
            <button type="button" className="boss-btn" disabled={!dirty||busy||loading} onClick={()=>{setDirty(false);reload();}}>放弃本次配置编辑</button>
          </div>
          {!dirty&&<p className="boss-helper">当前没有未保存的配置修改。</p>}
          {dirty&&<p className="boss-helper">保存草稿不会启用调度；验证只核对当前草稿版本。</p>}
          {validateHint&&<p className="boss-helper">{validateHint}</p>}
        </section>
      </div><aside className="boss-column">
        <section className="boss-panel">
          <div className="boss-panel-head"><h2>已保存草稿与启用</h2><small>启用只改变本机技术调度</small></div>
          <Kv label="草稿编号及版本" value={data?.draft?`${data.draft.draft_id} · v${data.draft.version}`:"尚未保存"}/>
          <Kv label="草稿验证状态" value={data?.draft?.validation_state??"尚未保存"}/>
          <Kv label="最后保存时间" value={data?.draft?.saved_at}/>
          <Kv label="验证时间" value={data?.draft?.validated_at}/>
          <Kv label="启用时间" value={data?.draft?.activated_at}/>
          <Kv label="当前规则版本" value={data?.rules?.version}/>
          <div className="boss-actions">
            <button type="button" className="boss-btn boss-btn-primary" disabled={!!activateHint} onClick={prepareActivate}><PlayCircle size={16}/> 启用此调度版本</button>
          </div>
          {activateHint&&<p className="boss-helper">{activateHint}</p>}
          <p className="boss-helper">启用后下一次触发：待核查（当前页面未核实执行责任组件）；回执后重新读取以核对实际采用版本。</p>
        </section>
        <section className="boss-panel">
          <div className="boss-panel-head"><h2>执行控制</h2><small>暂停与恢复按当前状态互斥显示</small></div>
          <Kv label="应用退出后的状态" value={data?.runtime?.quit_behavior}/>
          <Kv label="当前在途运行" value={data?.runtime?.active_run_count}/>
          <Kv label="启用状态" value={data?.schedule.enabled}/>
          <Kv label="取消状态" value={data?.schedule.canceled}/>
          <Kv label="实际生效草稿版本" value={data?.schedule.active_draft_version}/>
          <div className="boss-actions">
            {data&&!data.schedule.canceled&&(data.schedule.enabled
              ? <button type="button" className="boss-btn" disabled={busy||loading||dirty}
                onClick={()=>updateStatus("pause")}><PauseCircle size={15}/> 暂停后续触发</button>
              : <button type="button" className="boss-btn" disabled={busy||loading||dirty}
                onClick={()=>updateStatus("resume")}><PlayCircle size={15}/> 恢复后续触发</button>)}
            {data?.manual_dispatch_supported_here
              && <button type="button" className="boss-btn" disabled={busy||loading||dirty} onClick={openManual}>立即触发一次获准检查</button>}
          </div>
          {operationHint&&(data&&!data.schedule.canceled)&&<p className="boss-helper">{operationHint}</p>}
          {!data?.manual_dispatch_supported_here&&manualHint&&<p className="boss-helper">{manualHint}</p>}
          {data?.schedule.canceled&&<p className="boss-helper">此计划已取消，不能再暂停或恢复；历史运行与回执继续保留。</p>}
          <details className="boss-runtime-metadata"><summary>更多操作</summary>
            <p>取消与暂停不同：暂停只抑制后续触发且可以恢复；取消后不能恢复，后续不再触发。</p>
            <p>取消后保留历史运行与回执，不影响老板计划，也不撤销老板的业务授权。</p>
            {data&&!data.schedule.canceled
              ? <button type="button" className="boss-btn" disabled={busy||loading||dirty}
                onClick={()=>updateStatus("cancel")}><XCircle size={15}/> 取消此调度计划</button>
              : <p className="boss-helper">此计划已取消。</p>}
          </details>
        </section>
        <section className="boss-panel"><div className="boss-panel-head"><h2>关联记录</h2></div><div className="boss-actions"><button className="boss-btn" onClick={()=>onNavigate("A15")}>运行记录</button><button className="boss-btn" onClick={()=>onNavigate("A04")}>获准事件与业务时间</button>{deliveredPage("A14","MAINTAINER")&&<button className="boss-btn" onClick={()=>onNavigate("A14")}>授权与操作记录</button>}</div>
          <p className="boss-helper">关联记录按当前页面的计划编号进入对应页面核查；当前导航未携带计划编号。老板个人计划的元信息不在当前技术投影内，管理员只读取获准范围摘要。</p>
        </section>
      </aside></div>
        <details className="boss-panel" ref={manualPanel}>
          <summary>本次触发输入与授权</summary><p>使用与CronService相同的到期、静默及重复抑制规则。</p>
          <label className="boss-label" htmlFor="boss-scheduler-event">当前批准模拟事件</label>
          <select id="boss-scheduler-event" className="boss-single-input"
            disabled={busy||loading||dirty} value={selectedEvent} onChange={e=>setSelectedEvent(e.target.value)}>
            <option value="">请选择已有模拟事件</option>
            {(data?.available_manual_events||[]).map(item=><option value={item.event_id} key={item.event_id}>
              {item.event_id} · v{item.version} · {item.state} · {item.due_at}
            </option>)}
          </select>
          <Kv label="本次授权范围" value={data?.schedule.authorized_scope.map(id=>data.authorized_scopes.find(row=>row.id===id)?.label??id).join("、")}/>
          <div className="boss-actions">
            <button type="button" className="boss-btn boss-btn-primary"
              disabled={!!manualHint||!selectedEvent}
              onClick={prepareManualRun}>
              <PlayCircle size={15}/> 核对输入并触发本次检查</button>
          </div>
          {(!selectedEvent&&!manualHint)&&<p className="boss-helper">先选择本次要检查的获准事件。</p>}
          <div className="boss-status boss-status-warn">
            <Clock3 size={16}/> 模拟时钟未到期、静默时间或老板已关闭的提醒不会伪造成送达。
            这里的 DELIVERED 仅为模拟内部通知，不代表桌面系统通知或外部收件人已收到。
          </div>
        </details>
        <section className="boss-panel">
          <div className="boss-panel-head"><h2>调度证据</h2><small>派发结果与运行边界</small></div>
          <div className="boss-scheduler-checks"><Kv label="执行责任组件" value={data?.schedule.executor_component}/><Kv label="当前计划时区" value={data?.schedule.timezone}/><Kv label="当前草稿版本" value={data?.draft?.version}/><Kv label="草稿校验状态" value={data?.draft?.validation_state??"尚未保存"}/><Kv label="重复抑制窗口" value={data?.rules?`${data.rules.cooldown_seconds} 秒`:null}/><Kv label="重启恢复方式" value={data?.restart_policies.find(row=>row.id===data.schedule.restart_policy)?.label??data?.schedule.restart_policy}/><Kv label="模拟业务时钟" value={data?.simulated_business_time}/><Kv label="CronService 运行核查" value={data?.cron_runtime_verified_here?"已经核实":"当前页面未核实"}/><Kv label="运行组件报告的运行状态" value={data?.runtime?.state}/><Kv label="运行组件报告的下一次触发" value={data?.next_run_time??"运行组件未报告"}/></div>
          {(data?.recent_dispatches||[]).map((row,i)=><div className="boss-workspace-item"
            key={row.event_id+"-"+i}>
            <strong>{row.event_id}</strong>
            <Kv label="版本" value={row.event_version}/>
            <Kv label="执行状态" value={row.state}/>
            <Kv label="抑制原因" value={row.reason||"无"}/>
            <Kv label="模拟业务时间" value={row.business_at}/>
          </div>)}
          {!data?.recent_dispatches?.length&&<p className="boss-helper">
            当前没有已写入数据库的调度结果；不能推定 CronService 运行成功。
          </p>}
          <p className="boss-helper">当前派发记录没有关联运行编号与业务产物；需要核查运行编号时进入运行记录页面。</p>
        </section>
    <details className="boss-panel"><summary>经营提醒调度管理</summary><BossBusinessAlertAdministration onDirtyChange={setAlertDirty}/></details>
    {transaction.dialog}{transaction.recovery}
  </div>;
}
