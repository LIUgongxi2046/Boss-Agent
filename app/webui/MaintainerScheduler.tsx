import { useEffect, useRef, useState } from "react";
import {
  AlertCircle, CheckCircle2, Clock3, FileCheck2, Loader2,
  PauseCircle, PlayCircle, RefreshCw, ShieldCheck, XCircle,
} from "lucide-react";
import { useClient } from "@/providers/ClientProvider";
import {useTransaction} from "./BossAssignmentFlow";
import {BossBusinessAlertAdministration} from "./BossBusinessAlerts";
import {deliveredPage} from "./delivered-navigation";

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
type Scheduler = {
  source_type:"SIMULATED";projection:"scheduler";schedule:Schedule;
  draft:Draft|null;rules:Rules|null;simulated_business_time:string;
  recent_dispatches:{event_id:string;event_version:string;state:string;
    reason?:string;business_at:string}[];
  cron_runtime_verified_here:boolean;next_run_time:string|null;
  executors:{id:string;label:string}[];authorized_scopes:{id:string;label:string}[];
  restart_policies:{id:string;label:string}[];runtime:{state:string;active_run_count:number;resume_checked_at:string|null;quit_behavior:string};
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
    setLoading(true);setError("");setData(null);
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
    if([cfg.quiet_start,cfg.quiet_end,cfg.cooldown_seconds].some(
      x=>!Number.isInteger(x))||cfg.quiet_start<0||cfg.quiet_start>23||
      cfg.quiet_end<0||cfg.quiet_end>23||
      cfg.cooldown_seconds<0||cfg.cooldown_seconds>86400){
      setError("静默时间必须是0—23整数，冷却秒数为0—86400整数。");return;
    }
    propose("boss.scheduler.draft.save",{
      expected_version:data.draft?.version||"0",...cfg,
    },"仅保存调度配置草稿",[
      "当前草稿版本："+(data.draft?.version||"0"),
      "触发类型："+cfg.trigger,"时区："+cfg.timezone,
      "静默时段："+cfg.quiet_start+":00 — "+cfg.quiet_end+":00",
      "冷却去重："+cfg.cooldown_seconds+"秒",
      "重要升级："+String(cfg.important_escalation),
      "保存不会直接启用、发送业务消息或扩大老板授权。",
    ]);
  }
  function prepareValidate(){
    if(!data?.draft||data.draft.validation_state!=="DRAFT"||dirty){
      setError("只有已保存、未修改的 DRAFT 版本可校验");return;
    }
    propose("boss.scheduler.draft.validate",{
      expected_version:data.draft.version,
    },"校验当前调度草稿",[
      "草稿："+data.draft.draft_id+" v"+data.draft.version,
      "仅核对规则与当前本机执行空间，不会启用调度。",
    ]);
  }
  function prepareActivate(){
    if(!data?.draft||data.draft.validation_state!=="VALIDATED"||dirty){
      setError("启用前须先保存并通过服务端校验");return;
    }
    if(data.schedule.canceled){setError("已取消的原计划不能重新启用");return;}
    propose("boss.scheduler.activate",{
      expected_draft_version:data.draft.version,
      expected_schedule_version:data.schedule.version,
      expected_rules_version:data.rules?.version||"0",
    },"启用已经验证的技术调度规则",[
      "当前技术计划："+data.schedule.schedule_id+" v"+data.schedule.version,
      "已验证草稿版本："+data.draft.version,
      "提醒规则版本："+(data.rules?.version||"0"),
      "仅修改本机事件调度与通知规则，不发送真实外部消息，也不授予老板业务动作。",
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
    },"按当前事件版本执行模拟调度",[
      "模拟事件："+event.event_id+" v"+event.version,
      "到期时间："+event.due_at,
      "当前模拟时钟："+data.simulated_business_time,
      "技术计划："+data.schedule.schedule_id+" v"+data.schedule.version,
      "本次调用共享真实Cron规则；未到期显示 NOT_DUE，已送达的版本抑制重复。",
      "不接入实际外部通知，不给维护者添加老板业务授权。",
    ]);
  }
  function updateStatus(action:"pause"|"resume"|"cancel"){
    if(!data)return;
    propose("boss.scheduler."+action,{
      expected_version:data.schedule.version,
    },action==="cancel"?"永久取消当前执行空间计划":action==="pause"?"暂停本机调度":"恢复当前未取消的调度",[
      "计划："+data.schedule.schedule_id+" v"+data.schedule.version,
      action==="cancel"?"取消不可在当前执行空间恢复。":
        action==="pause"?"暂停后新的到期通知被抑制，不删除已有事件。":
          "仅恢复已存在且未取消的技术计划；业务发送仍独立授权。",
      "不会代老板确认任务完成或模拟真实消息送达。",
    ]);
  }
  function openManual(){if(manualPanel.current){manualPanel.current.open=true;manualPanel.current.scrollIntoView({block:"center",behavior:"smooth"});document.getElementById("boss-scheduler-event")?.focus();}}
  return <div className="boss-scheduler-workspace">
    <div className="boss-workspace-toolbar">
      <div className="boss-workspace-note"><span className="boss-tag boss-tag-amber">SIMULATED · TECH ONLY</span>
        A13 · 版本化调度草稿与运行开关
      </div>
      <button type="button" className="boss-btn" disabled={loading||dirty||busy} onClick={reload}>
        {loading?<Loader2 size={15} className="boss-spin"/>:<RefreshCw size={15}/>} 重新读取
      </button>
    </div>
    {loading&&<div className="boss-status"><Loader2 className="boss-spin" size={15}/>正在读取调度配置…</div>}
    {error&&<div role="alert" className="boss-status boss-status-error"><AlertCircle size={16}/>{error}</div>}
    {notice&&<div role="status" className="boss-status boss-status-ok"><CheckCircle2 size={16}/>{notice}</div>}
    <div className="boss-columns">
      <div className="boss-column">
        <section className="boss-panel">
          <div className="boss-panel-head"><h2>调度对象与责任</h2><small>保存、校验和启用各自独立</small></div>
          <fieldset className="boss-fc04-fieldset" disabled={busy||loading||!data}><div className="boss-form-grid">
            <label>计划名称<input value={cfg.name??""} onChange={event=>edit("name",event.target.value)}/></label>
            <label>唯一执行责任组件<select value={cfg.executor_component??""} onChange={event=>edit("executor_component",event.target.value)}><option value="">请选择</option>{data?.executors?.map(row=><option key={row.id} value={row.id}>{row.label}</option>)}</select></label>
            <label>当前计划版本<input readOnly value={data?.schedule.version??"尚未读取"}/></label>
            <label>下次触发时间<input readOnly value={data?.next_run_time??"尚未确认"}/></label>
          </div></fieldset>
          <Kv label="计划对象" value={data?.schedule.schedule_id}/>
          <Kv label="当前获准范围" value={data?.schedule.authorized_scope.map(id=>data.authorized_scopes.find(row=>row.id===id)?.label??id).join("、")}/>
        </section>
        <section className="boss-panel">
          <div className="boss-panel-head"><h2>条件、时区和去重</h2></div>
          <fieldset className="boss-fc04-fieldset" disabled={busy||loading||!data}><div className="boss-form-grid">
            <label>触发条件<select value={cfg.trigger}
              onChange={e=>edit("trigger",e.target.value)}>
              <option value="EVENT_OR_TIME">EVENT_OR_TIME · 事件或时间</option>
              <option value="CRON">定时计划</option><option value="EVENT">业务事件</option>
            </select></label>
            <label>IANA时区<input value={cfg.timezone} onChange={event=>edit("timezone",event.target.value)}/></label>
            <label>调度表达式<input disabled={cfg.trigger==="EVENT"} value={cfg.expression??""} onChange={event=>edit("expression",event.target.value)}/></label>
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
          <div className="boss-actions">
            <button type="button" className="boss-btn boss-btn-primary" disabled={!data||busy||!dirty}
              onClick={save}><FileCheck2 size={16}/> 保存计划草稿</button>
            <button type="button" className="boss-btn"
              disabled={!data?.draft||data.draft.validation_state!=="DRAFT"||dirty||busy}
              onClick={prepareValidate}><ShieldCheck size={16}/> 验证条件</button>
            <button type="button" className="boss-btn" disabled={!dirty||busy||loading} onClick={()=>{setDirty(false);reload();}}>取消本次修改</button>
          </div>
          <div className="boss-status boss-status-warn"><Clock3 size={16}/>
            保存或验证技术配置不代表已经启用和采用。必须由已认证维护角色独立启用；老板任务和个人计划的授权不因此扩大。
          </div>
        </section>
      </div><aside className="boss-column">
        <section className="boss-panel">
          <div className="boss-panel-head"><h2>执行控制</h2><small>取消后不可在原执行空间恢复</small></div>
          <Kv label="计划状态" value={data?data.schedule.canceled?"已取消":data.schedule.enabled?"已启用":"未启用 / 已暂停":null}/>
          <Kv label="应用退出后的状态" value={data?.runtime?.quit_behavior}/>
          <Kv label="休眠恢复检查" value={data?.runtime?.resume_checked_at}/>
          <Kv label="当前在途运行" value={data?.runtime?.active_run_count}/>
          <Kv label="启用状态" value={data?.schedule.enabled}/>
          <Kv label="取消状态" value={data?.schedule.canceled}/>
          <Kv label="当前规则版本" value={data?.rules?.version}/>
          <Kv label="实际生效草稿版本" value={data?.schedule.active_draft_version}/>
          <div className="boss-actions">
            <button type="button" className="boss-btn boss-btn-primary" disabled={!data?.draft||data.draft.validation_state!=="VALIDATED"||dirty||busy||loading||data.schedule.canceled} onClick={prepareActivate}><PlayCircle size={16}/> 启用计划</button>
            <button type="button" className="boss-btn" disabled={!data?.schedule.enabled||data.schedule.canceled||busy||dirty}
              onClick={()=>updateStatus("pause")}><PauseCircle size={15}/> 暂停</button>
            <button type="button" className="boss-btn" disabled={data?.schedule.enabled||data?.schedule.canceled||!data||busy||dirty}
              onClick={()=>updateStatus("resume")}><PlayCircle size={15}/> 恢复</button>
            <button type="button" className="boss-btn" disabled={!data||data.schedule.canceled||busy||dirty}
              onClick={()=>updateStatus("cancel")}><XCircle size={15}/> 取消本计划</button>
            <button type="button" className="boss-btn" disabled={!data?.manual_dispatch_supported_here||busy||dirty} onClick={openManual}>获准手动执行</button>
          </div>
        </section>
        <section className="boss-panel"><div className="boss-panel-head"><h2>关联记录</h2></div><div className="boss-actions"><button className="boss-btn" disabled title="本人计划由老板身份查看">本人计划</button><button className="boss-btn" onClick={()=>onNavigate("A15")}>运行记录</button><button className="boss-btn" onClick={()=>onNavigate("A04")}>获准事件与业务时间</button>{deliveredPage("A14","MAINTAINER")&&<button className="boss-btn" onClick={()=>onNavigate("A14")}>授权与操作记录</button>}</div></section>
      </aside></div>
        <details className="boss-panel" ref={manualPanel}>
          <summary>获准手动模拟执行</summary><p>使用与CronService相同的到期、静默及重复抑制规则。</p>
          <label className="boss-label" htmlFor="boss-scheduler-event">当前批准模拟事件</label>
          <select id="boss-scheduler-event" className="boss-single-input"
            disabled={busy||loading||dirty} value={selectedEvent} onChange={e=>setSelectedEvent(e.target.value)}>
            <option value="">请选择已有模拟事件</option>
            {(data?.available_manual_events||[]).map(item=><option value={item.event_id} key={item.event_id}>
              {item.event_id} · v{item.version} · {item.state} · {item.due_at}
            </option>)}
          </select>
          <div className="boss-actions">
            <button type="button" className="boss-btn boss-btn-primary"
              disabled={!data?.manual_dispatch_supported_here||!selectedEvent||busy||loading||dirty||data.schedule.canceled}
              onClick={prepareManualRun}>
              <PlayCircle size={15}/> 核对并手动模拟触发</button>
          </div>
          <div className="boss-status boss-status-warn">
            <Clock3 size={16}/> 模拟时钟未到期、静默时间或老板已关闭的提醒不会伪造成送达。
            这里的 DELIVERED 仅为模拟内部通知，不代表桌面系统通知或外部收件人已收到。
          </div>
        </details>
        <section className="boss-panel">
          <div className="boss-panel-head"><h2>调度运行、去重及恢复记录</h2></div>
          <div className="boss-scheduler-checks"><Kv label="执行责任组件" value={data?.schedule.executor_component}/><Kv label="当前计划时区" value={data?.schedule.timezone}/><Kv label="当前草稿版本" value={data?.draft?.version}/><Kv label="草稿校验状态" value={data?.draft?.validation_state??"尚未保存"}/><Kv label="重复抑制窗口" value={data?.rules?`${data.rules.cooldown_seconds} 秒`:null}/><Kv label="重启恢复方式" value={data?.restart_policies.find(row=>row.id===data.schedule.restart_policy)?.label??data?.schedule.restart_policy}/><Kv label="模拟业务时钟" value={data?.simulated_business_time}/><Kv label="CronService 运行核查" value={data?.cron_runtime_verified_here}/></div>
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
        </section>
    <details className="boss-panel"><summary>经营提醒调度管理</summary><BossBusinessAlertAdministration onDirtyChange={setAlertDirty}/></details>
    {transaction.dialog}{transaction.recovery}
  </div>;
}
