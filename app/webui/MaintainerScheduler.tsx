import { useEffect, useRef, useState } from "react";
import {
  AlertCircle, CheckCircle2, Clock3, FileCheck2, Loader2,
  PauseCircle, PlayCircle, RefreshCw, ShieldCheck, XCircle,
} from "lucide-react";
import { useClient } from "@/providers/ClientProvider";

type Schedule = {
  schedule_id:string;version:string;schedule_version:string;timezone:string;
  trigger:string;enabled:boolean;canceled:boolean;active_draft_version?:string;
};
type Rules = {
  version:string;quiet_start:number;quiet_end:number;
  cooldown_seconds:number;important_escalation:boolean;timezone:string;
};
type Configuration = Omit<Rules,"version"> & {trigger:string};
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
  cron_runtime_verified_here:false;next_run_time:null;
  manual_dispatch_supported_here:false;external_delivery_verified:false;
};
type Result = {version?:string;validation_state?:string;
  enabled?:boolean;canceled?:boolean;schedule_activated?:boolean};
type Pending = {action:string;payload:Record<string,unknown>;title:string;
  id:string;detail:string[]};

const DEFAULT:Configuration = {
  trigger:"EVENT_OR_TIME",timezone:"Asia/Shanghai",
  quiet_start:22,quiet_end:7,cooldown_seconds:3600,
  important_escalation:false,
};
function Kv({label,value}:{label:string;value:string|number|boolean|null|undefined}) {
  return <div className="boss-kv"><span>{label}</span><strong>{
    value===null||value===undefined?"未知":String(value)
  }</strong></div>;
}

export function MaintainerScheduler({onNavigate}:{onNavigate:(page:string)=>void}) {
  const {client,getToken}=useClient();
  const [data,setData]=useState<Scheduler|null>(null);
  const [cfg,setCfg]=useState<Configuration>(DEFAULT);
  const [dirty,setDirty]=useState(false);
  const [revision,setRevision]=useState(0);
  const [loading,setLoading]=useState(false);
  const [busy,setBusy]=useState(false);
  const [checkBusy,setCheckBusy]=useState(false);
  const [error,setError]=useState("");
  const [notice,setNotice]=useState("");
  const [pending,setPending]=useState<Pending|null>(null);
  const [checked,setChecked]=useState(false);
  const dialog=useRef<HTMLElement|null>(null);
  const busyRef=useRef(false);busyRef.current=busy||checkBusy;
  const reload=()=>setRevision(v=>v+1);
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
      if(!dirty){
        setCfg(result.draft?.configuration||
          (result.rules?{
            trigger:result.schedule.trigger,timezone:result.schedule.timezone,
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
  },[revision,getToken]);

  useEffect(()=>{
    if(!pending)return;
    const origin=document.activeElement instanceof HTMLElement?document.activeElement:null;
    dialog.current?.focus();
    const keyboard=(e:KeyboardEvent)=>{
      if(e.key==="Escape"&&!busyRef.current){setPending(null);setChecked(false);return;}
      if(e.key!=="Tab"||!dialog.current)return;
      const nodes=Array.from(dialog.current.querySelectorAll<HTMLElement>(
        "button:not([disabled]),input:not([disabled])"
      )).filter(n=>n.getClientRects().length>0);
      if(!nodes.length)return;
      if(e.shiftKey&&document.activeElement===nodes[0]){
        e.preventDefault();nodes[nodes.length-1].focus();
      }else if(!e.shiftKey&&document.activeElement===nodes[nodes.length-1]){
        e.preventDefault();nodes[0].focus();
      }
    };
    document.addEventListener("keydown",keyboard);
    return ()=>{document.removeEventListener("keydown",keyboard);origin?.focus();};
  },[pending?.id]);

  function edit<K extends keyof Configuration>(field:K,value:Configuration[K]){
    setCfg(old=>({...old,[field]:value}));setDirty(true);
  }
  function propose(action:string,payload:Record<string,unknown>,title:string,detail:string[]){
    if(busy||loading)return;
    setPending({action,payload,title,detail,id:"boss-"+crypto.randomUUID()});
    setChecked(false);setError("");setNotice("");
  }
  async function execute(){
    if(!pending||!checked||busy||checkBusy)return;
    setBusy(true);setError("");
    try{
      const result=await client.requestMutation<Result>(pending.action,{
        ...pending.payload,client_request_id:pending.id,
      });
      setNotice("已从实际 SQLite 确认技术操作结果；版本 "+
        (result.version||"待核查")+"；状态 "+
        (result.validation_state||(result.canceled?"CANCELED":result.enabled?"ENABLED":"PAUSED"))+
        "。正在重读调度与草稿状态。");
      setDirty(false);setPending(null);setChecked(false);reload();
    }catch(e){
      setError((e instanceof Error?e.message:String(e))+
        "。执行回执不确定时请核查原请求编号，不要更换编号重试。");
    }finally{setBusy(false);}
  }
  async function reconcile(){
    if(!pending||busy||checkBusy)return;
    const token=getToken();
    if(!token){setError("维护身份已失效");return;}
    setCheckBusy(true);setError("");
    try{
      const q=new URLSearchParams({action:pending.action,client_request_id:pending.id});
      const res=await fetch("/api/boss/ui/operation-status?"+q.toString(),{
        headers:{Authorization:"Bearer "+token},cache:"no-store",
      });
      if(!res.ok)throw Error("原操作回执查询失败");
      const result=await res.json() as {outcome:string;action:string;client_request_id:string};
      if(result.action!==pending.action||result.client_request_id!==pending.id)
        throw Error("回执标识不一致");
      if(result.outcome==="RECORDED"){
        setNotice("原请求已在SQLite持久化，正在重新读取当前配置。");
        setDirty(false);setPending(null);setChecked(false);reload();
      }else if(result.outcome==="NOT_FOUND_IN_CURRENT_STORE"){
        setError("未检出回执不证明未执行。请核对真实配置后使用相同请求编号重试。");
        reload();
      }else throw Error("无法识别原执行结果");
    }catch(e){setError(e instanceof Error?e.message:String(e));}
    finally{setCheckBusy(false);}
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
  return <>
    <div className="boss-workspace-toolbar">
      <div className="boss-workspace-note"><span className="boss-tag boss-tag-amber">SIMULATED · TECH ONLY</span>
        A13 · 版本化调度草稿与运行开关
      </div>
      <button type="button" className="boss-btn" disabled={loading} onClick={reload}>
        {loading?<Loader2 size={15} className="boss-spin"/>:<RefreshCw size={15}/>} 重新读取
      </button>
    </div>
    {loading&&<div className="boss-status"><Loader2 className="boss-spin" size={15}/>正在读取调度配置…</div>}
    {error&&<div role="alert" className="boss-status boss-status-error"><AlertCircle size={16}/>{error}</div>}
    {notice&&<div role="status" className="boss-status boss-status-ok"><CheckCircle2 size={16}/>{notice}</div>}
    <div className="boss-columns">
      <div className="boss-column">
        <section className="boss-panel">
          <div className="boss-panel-head"><h2>时间与事件触发配置</h2><small>保存、校验和启用各自独立</small></div>
          <div className="boss-form-grid">
            <label>计划对象<input readOnly value={data?.schedule.schedule_id||"待加载"}/></label>
            <label>当前技术版本<input readOnly value={data?.schedule.version||"待加载"}/></label>
            <label>触发条件<select value={cfg.trigger}
              onChange={e=>edit("trigger",e.target.value)}>
              <option value="EVENT_OR_TIME">EVENT_OR_TIME · 事件或时间</option>
            </select></label>
            <label>IANA时区<select value={cfg.timezone}
              onChange={e=>edit("timezone",e.target.value)}>
              <option value="Asia/Shanghai">Asia/Shanghai</option>
            </select></label>
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
          </div>
          <div className="boss-actions">
            <button type="button" className="boss-btn" disabled={!data||busy}
              onClick={save}><FileCheck2 size={16}/> 保存草稿</button>
            <button type="button" className="boss-btn"
              disabled={!data?.draft||data.draft.validation_state!=="DRAFT"||dirty||busy}
              onClick={prepareValidate}><ShieldCheck size={16}/> 校验版本</button>
            <button type="button" className="boss-btn boss-btn-primary"
              disabled={!data?.draft||data.draft.validation_state!=="VALIDATED"||dirty||busy||data.schedule.canceled}
              onClick={prepareActivate}><PlayCircle size={16}/> 启用已验证配置</button>
          </div>
          <div className="boss-status boss-status-warn"><Clock3 size={16}/>
            保存或验证技术配置不代表已经启用和采用。必须由已认证维护角色独立启用；老板任务和个人计划的授权不因此扩大。
          </div>
        </section>
        <section className="boss-panel">
          <div className="boss-panel-head"><h2>运行计划与启停</h2><small>取消后不可在原执行空间恢复</small></div>
          <Kv label="启用状态" value={data?.schedule.enabled}/>
          <Kv label="取消状态" value={data?.schedule.canceled}/>
          <Kv label="当前规则版本" value={data?.rules?.version}/>
          <Kv label="实际生效草稿版本" value={data?.schedule.active_draft_version}/>
          <div className="boss-actions">
            <button type="button" className="boss-btn" disabled={!data?.schedule.enabled||data.schedule.canceled||busy}
              onClick={()=>updateStatus("pause")}><PauseCircle size={15}/> 暂停</button>
            <button type="button" className="boss-btn" disabled={data?.schedule.enabled||data?.schedule.canceled||!data||busy}
              onClick={()=>updateStatus("resume")}><PlayCircle size={15}/> 恢复</button>
            <button type="button" className="boss-btn" disabled={!data||data.schedule.canceled||busy}
              onClick={()=>updateStatus("cancel")}><XCircle size={15}/> 取消本计划</button>
          </div>
        </section>
        <section className="boss-panel">
          <div className="boss-panel-head"><h2>调度记录</h2><small>实际数据库技术状态</small></div>
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
      </div>
      <div className="boss-column">
        <section className="boss-panel">
          <div className="boss-panel-head"><h2>当前草稿与启用状态</h2></div>
          <Kv label="草稿 ID" value={data?.draft?.draft_id}/>
          <Kv label="草稿版本" value={data?.draft?.version}/>
          <Kv label="校验状态" value={data?.draft?.validation_state||"NOT_SAVED"}/>
          <Kv label="调度版本" value={data?.schedule.version}/>
          <Kv label="模拟业务时钟" value={data?.simulated_business_time}/>
          <Kv label="下一次执行时间" value={data?.next_run_time}/>
          <Kv label="CronService 实机运行验证" value={data?.cron_runtime_verified_here}/>
          <Kv label="模拟事件手动触发" value={data?.manual_dispatch_supported_here}/>
          <div className="boss-status boss-status-warn"><AlertCircle size={16}/>
            手动运行尚未接入获准的真实调度执行器，因此本页不提供伪造的“执行成功”按钮。
            下一次执行时间没有验证来源时保持未知。
          </div>
          <div className="boss-actions">
            <button type="button" className="boss-btn" onClick={()=>onNavigate("A04")}>
              查看获准事件与模拟业务时间</button>
            <button type="button" className="boss-btn" onClick={()=>onNavigate("A14")}>
              查看脱敏授权与操作记录</button>
          </div>
        </section>
      </div>
    </div>
    {pending&&<div className="boss-confirm-backdrop">
      <section className="boss-confirm" role="dialog" aria-modal="true"
        aria-labelledby="boss-scheduler-confirm" tabIndex={-1} ref={dialog}>
        <h3 id="boss-scheduler-confirm"><ShieldCheck size={19}/>{pending.title}</h3>
        <p>当前只是有界模拟技术调度配置。没有老板业务授权，操作通过同一持久事务和原请求编号执行。</p>
        <dl>{pending.detail.map((row,i)=><div key={i}><dd>{row}</dd></div>)}</dl>
        <label className="boss-confirm-check">
          <input type="checkbox" checked={checked} disabled={busy||checkBusy}
            onChange={e=>setChecked(e.target.checked)}/>
          <span>我已核实配置版本、操作类型以及对当前计划的影响。</span>
        </label>
        {error&&<p className="boss-validation-error" role="alert">{error}</p>}
        <div className="boss-actions">
          <button type="button" className="boss-btn" disabled={busy||checkBusy}
            onClick={()=>{setPending(null);setChecked(false);}}>取消</button>
          <button type="button" className="boss-btn" disabled={busy||checkBusy}
            onClick={()=>void reconcile()}>
            {checkBusy&&<Loader2 size={15} className="boss-spin"/>} 查询原请求回执</button>
          <button type="button" className="boss-btn boss-btn-primary"
            disabled={!checked||busy||checkBusy} onClick={()=>void execute()}>
            {busy&&<Loader2 size={15} className="boss-spin"/>} 确认并提交</button>
        </div>
      </section>
    </div>}
  </>;
}
