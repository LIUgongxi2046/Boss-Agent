import {
  useEffect, useRef, useState, type ReactNode,
} from "react";
import {
  AlertCircle, BellRing, CheckCircle2, FileClock,
  History, Loader2, RefreshCw, ShieldCheck, SlidersHorizontal,
} from "lucide-react";
import { useClient } from "@/providers/ClientProvider";
import {useTransaction} from "./BossAssignmentFlow";
import {deliveredPage} from "./delivered-navigation";

type GoalSettings = {
  goals: string[]; topics: string[]; reading_requirement: string;
  scope: "OWNER_WORKSPACE"|"DAILY_BRIEF"|"MEETING_PREP";
  valid_until: string|null; source: string;
};
type NoticeSettings = {
  timezone: string; quiet_start: number; quiet_end: number;
  notifications_enabled: boolean; important_during_quiet: boolean;
  reading_format: "ACTIONS_FIRST"|"SUMMARY"|"DETAIL";
  visibility: "BOSS_ONLY"; calendar_share_limit:"BUSY_ONLY";
  valid_until: string|null; source: string;
};
type Settings = GoalSettings|NoticeSettings;
type RecordState = {
  id:string;version:string;state:string;content:Settings;
  content_sha256:string;source_draft_version?:string;
  confirmed_at?:string; saved_at?:string;
};
type Projection = {
  source_type:"SIMULATED";projection:"owner-goals"|"owner-notice";
  draft:RecordState|null;active:RecordState|null;active_is_effective:boolean;
  current_owner_profile?:{owner_confirmation:string;active_version:string|null};
  runtime_context_observation?:{context_load_count:number;
    observation:string;actual_model_compliance_verified:boolean};
  technical_rules?:Record<string,unknown>;
  technical_schedule?:Record<string,unknown>;
  history:{version:string;state:string;confirmed_at?:string}[];
  fixture_goals_are_owner_confirmed?:boolean;
  calendar_share_per_contact_requires_F12?:boolean;
};
type Result={
  version:string;state:string;content_sha256?:string;
  authorization_id?:string;source_draft_version?:string;
};
type Pending={
  action:string;key:string;payload:Record<string,unknown>;
  title:string;details:string[];
};
type Props={
  pageId:"N07"|"N08";onNavigate:(page:string)=>void;
  onDirtyChange:(dirty:boolean)=>void;
};

function Panel({title,note,children}:{
  title:string;note?:string;children:ReactNode;
}) {
  return <section className="boss-panel">
    <div className="boss-panel-head"><h2>{title}</h2>{note&&<small>{note}</small>}</div>
    {children}
  </section>;
}
function Value({label,children}:{label:string;children:ReactNode}){
  return <div className="boss-kv"><span>{label}</span><strong>{children}</strong></div>;
}
function validUntil(local:string){
  if(!local)return null;
  if(!/^\d{4}-\d\d-\d\dT\d\d:\d\d$/.test(local))
    throw new Error("截止时间缺少日期或分钟");
  return local+":00+08:00";
}
function asLocal(input:string|null|undefined){
  return input?input.slice(0,16):"";
}
function lines(raw:string){
  return raw.split("\n").map(x=>x.trim()).filter(Boolean);
}
function isGoals(value:Settings):value is GoalSettings{
  return "goals" in value;
}

export function BossOwnerPreferences({pageId,onNavigate,onDirtyChange}:Props){
  const {client,getToken}=useClient();
  const isGoal=pageId==="N07";
  const route=isGoal?"owner-goals":"owner-notice";
  const [data,setData]=useState<Projection|null>(null);
  const [revision,setRevision]=useState(0);
  const [loading,setLoading]=useState(false);
  const [dirty,setDirty]=useState(false);
  const [error,setError]=useState("");
  const [notice,setNotice]=useState("");
  const [goals,setGoals]=useState("");
  const [topics,setTopics]=useState("");
  const [reading,setReading]=useState("");
  const [scope,setScope]=useState<GoalSettings["scope"]>("OWNER_WORKSPACE");
  const [validUntilLocal,setValidUntilLocal]=useState("");
  const [timezone,setTimezone]=useState("Asia/Shanghai");
  const [quietStart,setQuietStart]=useState(22);
  const [quietEnd,setQuietEnd]=useState(7);
  const [enabled,setEnabled]=useState(true);
  const [important,setImportant]=useState(false);
  const [format,setFormat]=useState<NoticeSettings["reading_format"]>("ACTIONS_FIRST");
  const [pending,setPending]=useState<Pending|null>(null);
  const [approved,setApproved]=useState(false);
  const [busy,setBusy]=useState(false);
  const [checking,setChecking]=useState(false);
  const modalRef=useRef<HTMLElement|null>(null);
  const reload=()=>setRevision(x=>x+1);
  const noticeTx=useTransaction(()=>{setDirty(false);onDirtyChange(false);reload();},undefined,undefined,isGoal?"ownerGoalsReadonly":"ownerNotice");

  useEffect(()=>{onDirtyChange(dirty||(!isGoal&&noticeTx.busy));},[dirty,isGoal,noticeTx.busy,onDirtyChange]);
  useEffect(()=>{
    const onBeforeUnload=(event:BeforeUnloadEvent)=>{
      if(dirty||pending||(!isGoal&&noticeTx.busy)){event.preventDefault();event.returnValue="";}
    };
    window.addEventListener("beforeunload",onBeforeUnload);
    return ()=>window.removeEventListener("beforeunload",onBeforeUnload);
  },[dirty,pending,isGoal,noticeTx.busy]);

  function hydrate(record:RecordState|null){
    if(!record)return;
    const c=record.content;
    setValidUntilLocal(asLocal(c.valid_until));
    if(isGoals(c)){
      setGoals(c.goals.join("\n"));setTopics(c.topics.join("\n"));
      setReading(c.reading_requirement);setScope(c.scope);
    }else{
      setTimezone(c.timezone);setQuietStart(c.quiet_start);
      setQuietEnd(c.quiet_end);setEnabled(c.notifications_enabled);
      setImportant(c.important_during_quiet);setFormat(c.reading_format);
    }
  }

  useEffect(()=>{
    const controller=new AbortController();
    const token=getToken();
    if(!token){setError("当前身份已经失效，请重新认证");return;}
    setLoading(true);
    void fetch("/api/boss/ui/workspace/"+route,{
      headers:{Authorization:"Bearer "+token},cache:"no-store",
      signal:controller.signal,
    }).then(async r=>{
      if(!r.ok)throw new Error("读取本人设置失败，HTTP "+r.status);
      const result=await r.json() as Projection;
      if(result.source_type!=="SIMULATED"||result.projection!==route)
        throw new Error("设置来源或页面范围不匹配");
      return result;
    }).then(result=>{
      if(controller.signal.aborted)return;
      setData(result);setLoading(false);
      if(!dirty){
        hydrate(result.draft||result.active);
      }
    }).catch(e=>{
      if(controller.signal.aborted)return;
      setError(e instanceof Error?e.message:String(e));setLoading(false);
    });
    return ()=>controller.abort();
  },[route,revision,getToken]);

  useEffect(()=>{
    if(!pending)return;
    const previous=document.activeElement instanceof HTMLElement?document.activeElement:null;
    modalRef.current?.focus();
    const handler=(event:KeyboardEvent)=>{
      if(event.key==="Escape"&&!busy&&!checking){
        setPending(null);setApproved(false);return;
      }
      if(event.key!=="Tab"||!modalRef.current)return;
      const nodes=Array.from(modalRef.current.querySelectorAll<HTMLElement>(
        "input:not([disabled]),button:not([disabled])"
      )).filter(n=>n.getClientRects().length>0);
      if(nodes.length===0)return;
      if(event.shiftKey&&document.activeElement===nodes[0]){
        event.preventDefault();nodes[nodes.length-1].focus();
      }else if(!event.shiftKey&&document.activeElement===nodes[nodes.length-1]){
        event.preventDefault();nodes[0].focus();
      }
    };
    document.addEventListener("keydown",handler);
    return ()=>{document.removeEventListener("keydown",handler);previous?.focus();};
  },[pending?.key,busy,checking]);

  function changed(update:()=>void){
    update();setDirty(true);setNotice("");
  }
  function propose(action:string,payload:Record<string,unknown>,
                   title:string,details:string[]){
    if(!isGoal){if(noticeTx.busy)return;if(action!=="boss.owner.notice.save"&&action!=="boss.owner.notice.confirm")throw new Error("当前通知设置动作无效");noticeTx.propose(action,payload,title,details);return;}
    setPending({action,payload,title,details,key:"boss-"+crypto.randomUUID()});
    setApproved(false);setError("");setNotice("");
  }
  function saveDraft(){
    if(loading||busy)return;
    try{
      const expiry=validUntil(validUntilLocal);
      const common={
        expected_version:data?.draft?.version||"0",
        valid_until:expiry,
      };
      if(isGoal){
        const gs=lines(goals);const ts=lines(topics);
        if(!gs.length||gs.some(x=>x.length>160)||gs.length>8)
          throw new Error("请填写 1—8 项目标，每项最多160字");
        if(ts.length>10||ts.some(x=>x.length>120))
          throw new Error("关注主题最多10项，每项最多120字");
        if(!reading.trim()||reading.length>800)
          throw new Error("阅读要求须填写 1—800 字");
        propose("boss.owner.goals.save",{
          ...common,goals:gs,topics:ts,
          reading_requirement:reading.trim(),scope,
        },"保存目标与关注要求草稿",[
          "适用范围："+scope,"目标："+gs.join("；"),
          "关注主题："+(ts.join("；")||"未指定"),
          "阅读要求："+reading.trim(),
          "保存后为 DRAFT，不会修改当前生效版本，也不会被新模型任务采用。",
        ]);
      }else{
        propose("boss.owner.notice.save",{
          ...common,timezone:timezone.trim(),
          quiet_start:quietStart,quiet_end:quietEnd,
          notifications_enabled:enabled,
          important_during_quiet:important,reading_format:format,
          visibility:"BOSS_ONLY",calendar_share_limit:"BUSY_ONLY",
        },"保存通知要求草稿",[
          "IANA 时区："+timezone,
          "免打扰："+quietStart+":00 — "+quietEnd+":00",
          "通知状态："+(enabled?"允许按技术规则提醒":"本人暂停通知"),
          "重要事件允许穿透本人免打扰："+(important?"是（技术规则仍可限制）":"否"),
          "分享范围：仅 BUSY_ONLY；F12 单独按收件人授权。",
          "保存仅为草稿，不会影响当前后台调度。",
        ]);
      }
    }catch(e){setError(e instanceof Error?e.message:String(e));}
  }
  function confirmDraft(){
    if(!data?.draft||dirty){setError("请先保存并重读本次草稿");return;}
    propose(isGoal?"boss.owner.goals.confirm":"boss.owner.notice.confirm",{
      expected_draft_version:data.draft.version,
      expected_active_version:data.active?.version||"0",
      content_sha256:data.draft.content_sha256,
    },isGoal?"本人确认长期目标与阅读要求":"本人确认通知与可见范围",[
      "待确认草稿 v"+data.draft.version,
      "当前有效版本 "+(data.active?.version||"无"),
      "目标摘要哈希："+data.draft.content_sha256.slice(0,16),
      isGoal?
        "此后仅在有效期及适用范围内采用于 F01、F04 及新任务上下文。模型是否遵守需独立验证。":
        "确认后下次模拟调度读取该版本；只能增加老板侧的暂停/静默限制，不能解除技术限制。",
      "本人确认与保存草稿是两个独立动作。",
    ]);
  }
  function applied(result:Result){
    setPending(null);setApproved(false);setDirty(false);
    onDirtyChange(false);
    setNotice("当前模拟 SQLite 回执："+result.state+" · v"+result.version+
      "。请重新读取有效版本和实际采用/抑制记录。");
    reload();
  }
  async function submit(){
    if(!pending||!approved||busy||checking)return;
    setBusy(true);setError("");
    try{
      const result=await client.requestMutation<Result>(pending.action,{
        ...pending.payload,client_request_id:pending.key,
      });
      applied(result);
    }catch(e){
      setError((e instanceof Error?e.message:String(e))+
        "。执行结果可能未知，请优先查询同一幂等请求回执，不更换编号盲目重复提交。");
    }finally{setBusy(false);}
  }
  async function reconcile(){
    if(!pending||busy||checking)return;
    const token=getToken();
    if(!token){setError("身份已失效，无法查询原请求");return;}
    setChecking(true);setError("");
    try{
      const params=new URLSearchParams({
        action:pending.action,client_request_id:pending.key,
      });
      const response=await fetch("/api/boss/ui/operation-status?"+params,{
        headers:{Authorization:"Bearer "+token},cache:"no-store",
      });
      if(!response.ok)throw new Error("查询失败 HTTP "+response.status);
      const record=await response.json() as {
        action:string;client_request_id:string;outcome:string;result?:Result;
      };
      if(record.action!==pending.action||record.client_request_id!==pending.key)
        throw new Error("请求回执的动作或标识不一致");
      if(record.outcome==="RECORDED"&&record.result)applied(record.result);
      else if(record.outcome==="NOT_FOUND_IN_CURRENT_STORE"){
        setError("当前执行空间尚无原请求回执，不代表原操作未执行。请核对正式业务对象，必要时沿用原请求编号重试。");
        reload();
      }else throw new Error("未知回执状态，禁止自动提交第二次");
    }catch(e){setError(e instanceof Error?e.message:String(e));}
    finally{setChecking(false);}
  }

  return <div className={!isGoal?"boss-fc04-reminders":undefined}>
    <div className="boss-workspace-toolbar">
      <span className="boss-workspace-note">
        <span className="boss-tag boss-tag-amber">SIMULATED · BOSS ONLY</span>
        {pageId} · {isGoal?"本人目标与关注要求":"通知要求与可见范围"}
      </span>
      <button type="button" className="boss-btn" disabled={loading}
        onClick={reload}>
        {loading?<Loader2 size={15} className="boss-spin"/>:
          <RefreshCw size={15}/>} 重新读取当前版本
      </button>
    </div>
    {error&&<div className="boss-status boss-status-error" role="alert">
      <AlertCircle size={16}/>{error}
    </div>}
    {notice&&<div className="boss-status boss-status-ok" role="status">
      <CheckCircle2 size={16}/>{notice}
    </div>}
    {dirty&&<div className="boss-status boss-status-warn" role="status">
      <AlertCircle size={16}/> 当前编辑有未保存内容。离开本页需要明确放弃草稿；仅点击保存还不会正式启用。
    </div>}
    <div className="boss-columns">
      <div className="boss-column">
        <Panel title={isGoal?"目标、关注主题及长期阅读要求":"通知时间、升级与阅读格式"}
          note="Desktop v6 原版编辑表单 · 保存 / 本人确认分离">
          <fieldset className="boss-owner-setting-fields" disabled={busy||(!isGoal&&noticeTx.busy)}>
          {isGoal?<>
            <label className="boss-field">
              <span>目标内容（每行一项，最多8项）</span>
              <textarea rows={5} value={goals} maxLength={1600}
                onChange={e=>changed(()=>setGoals(e.target.value))}
                placeholder="请输入本人明确确认的工作目标；不自动采用演示建议。"/>
            </label>
            <div className="boss-form-grid">
              <label>适用范围<select value={scope}
                onChange={e=>changed(()=>setScope(e.target.value as GoalSettings["scope"]))}>
                <option value="OWNER_WORKSPACE">本人全部工作区</option>
                <option value="DAILY_BRIEF">晨间简报</option>
                <option value="MEETING_PREP">会议准备</option>
              </select></label>
              <label>关注主题（每行一项，最多10项）
                <textarea rows={3} value={topics} onChange={e=>changed(()=>setTopics(e.target.value))}
                  placeholder="明确的本人关注事项，当前为空则不推断"/>
              </label>
            </div>
            <label className="boss-field">
              <span>阅读与表达要求</span>
              <textarea rows={4} value={reading} maxLength={800}
                onChange={e=>changed(()=>setReading(e.target.value))}
                placeholder="例如：先写待本人决定的事项，再列证据缺口。"/>
            </label>
          </>:<>
            <div className="boss-form-grid">
              <label>IANA 通知时区<input value={timezone}
                onChange={e=>changed(()=>setTimezone(e.target.value))}
                placeholder="Asia/Shanghai" maxLength={80}/></label>
              <label>本人阅读格式<select value={format}
                onChange={e=>changed(()=>setFormat(e.target.value as NoticeSettings["reading_format"]))}>
                <option value="ACTIONS_FIRST">待行动事项优先</option>
                <option value="SUMMARY">简要汇总</option>
                <option value="DETAIL">详细模式</option>
              </select></label>
              <label>免打扰开始（整点）<select value={quietStart}
                onChange={e=>changed(()=>setQuietStart(Number(e.target.value)))}>
                {Array.from({length:24},(_,i)=><option key={i} value={i}>{i}:00</option>)}
              </select></label>
              <label>免打扰结束（整点）<select value={quietEnd}
                onChange={e=>changed(()=>setQuietEnd(Number(e.target.value)))}>
                {Array.from({length:24},(_,i)=><option key={i} value={i}>{i}:00</option>)}
              </select></label>
            </div>
            <div className="boss-workspace-item">
              <label className="boss-confirm-check"><input type="checkbox"
                checked={enabled} onChange={e=>changed(()=>setEnabled(e.target.checked))}/>
                <span>允许本人通知（取消后对本机模拟事件增加暂停限制）</span>
              </label>
              <label className="boss-confirm-check"><input type="checkbox"
                checked={important} onChange={e=>changed(()=>setImportant(e.target.checked))}/>
                <span>重要事件可跳过本人免打扰（技术规则仍必须独立允许）</span>
              </label>
            </div>
            <Value label="资料可见范围">仅本人 BOSS_ONLY</Value>
            <Value label="分享字段范围">仅 F12 已明确授权的 BUSY_ONLY</Value>
            <p className="boss-helper">这页不会创建接收者共享授权。
              收件人、用途和有效期仍须在 F12 逐项核对；暂停本人通知不会暂停技术 CronService。</p>
          </>}
          <label className="boss-field">
            <span>本人设置有效期（北京时间，可留空）</span>
            <input type="datetime-local" value={validUntilLocal}
              onChange={e=>changed(()=>setValidUntilLocal(e.target.value))}/>
          </label>
          <p className="boss-helper">截止时间基于获准模拟业务时钟 Asia/Shanghai，
            到期自动停止本次本人设置的后续采用，不删除历史审计记录。</p>
          <div className="boss-actions">
            <button type="button" className="boss-btn" disabled={loading||busy}
              onClick={()=>{hydrate(data?.draft||data?.active||null);setDirty(false);onDirtyChange(false);}}>
              <History size={15}/> 恢复最近保存内容
            </button>
            <button type="button" className="boss-btn boss-btn-primary"
              disabled={loading||busy||!data} onClick={saveDraft}>
              <SlidersHorizontal size={15}/> 保存配置草稿
            </button>
            <button type="button" className="boss-btn boss-btn-primary"
              disabled={!data?.draft||dirty||busy||loading}
              onClick={confirmDraft}>
              <ShieldCheck size={15}/> 本人确认启用当前草稿
            </button>
          </div>
          </fieldset>
        </Panel>
        <Panel title={isGoal?"当前要求与版本状态":"通知策略当前版本"}
          note="草稿、有效版本、实际采用分别记录">
          <Value label="草稿版本">{data?.draft?.version||"尚未保存"}</Value>
          <Value label="草稿状态">{data?.draft?.state||"未设置"}</Value>
          <Value label="本人已确认版本">{data?.active?.version||"尚未确认"}</Value>
          <Value label="有效状态">{data?.active_is_effective?"已确认且在有效期内":"不采用"}</Value>
          <Value label="确认记录时间">{data?.active?.confirmed_at||"尚未确认"}</Value>
          {isGoal?<>
            <Value label="后续上下文加载次数">{data?.runtime_context_observation?.context_load_count??0}</Value>
            <Value label="采用观测">{data?.runtime_context_observation?.observation||"NOT_OBSERVED"}</Value>
            <p className="boss-helper">仅确认运行时上下文提供器确实被调用；
              不代表模型已经正确遵守阅读要求，也不是 DeepSeek 质量验收。</p>
          </>:<>
            <Value label="技术调度状态">{data?.technical_schedule?.enabled?"启用":"停用或待核查"}</Value>
            <Value label="技术静默规则版本">{String(data?.technical_rules?.version||"尚未设置")}</Value>
            <p className="boss-helper">本人配置与技术调度规则取交集；
              后台原始业务事件和任务不因本人通知暂停而被删除。</p>
          </>}
        </Panel>
      </div>
      <div className="boss-column">
        <Panel title="保存结果与实际采用" note={isGoal?"N07 → F01 / F04 / Agent":"N08 → F02 / N06 / Cron"}>
          {data?.active_is_effective&&data.active&&<>
            <Value label="生效版本">{data.active.version}</Value>
            {isGoal&&isGoals(data.active.content)?<>
              {(data.active.content.goals||[]).map((x,i)=>
                <div className="boss-workspace-item" key={i}><strong>目标 {i+1}</strong><p>{x}</p></div>)}
              <Value label="范围">{data.active.content.scope}</Value>
            </>:!isGoals(data.active.content)&&<>
              <Value label="免打扰">
                {data.active.content.quiet_start}:00 — {data.active.content.quiet_end}:00
              </Value>
              <Value label="老板通知">{data.active.content.notifications_enabled?"按技术规则允许":"本人暂停"}</Value>
            </>}
          </>}
          {!data?.active_is_effective&&
            <p className="boss-helper">当前没有在有效期内、由本人亲自确认的配置。
              即使演示数据存在也不会把它标为新的本人授权。</p>}
          <div className="boss-actions">
            {isGoal?<>
              <button type="button" className="boss-btn" onClick={()=>onNavigate("F01")}>
                <FileClock size={15}/> 查看晨间工作
              </button>
              {deliveredPage("F04","BOSS")&&<button type="button" className="boss-btn" onClick={()=>onNavigate("F04")}>
                查看会前材料</button>}
              {deliveredPage("F13","BOSS")&&<button type="button" className="boss-btn" onClick={()=>onNavigate("F13")}>
                个人记忆</button>}
            </>:<>
              <button type="button" className="boss-btn" onClick={()=>onNavigate("N06")}>
                <BellRing size={15}/> 查看通知记录</button>
              <button type="button" className="boss-btn" onClick={()=>onNavigate("N09")}>
                查看本人计划</button>
              {deliveredPage("F12","BOSS")&&<button type="button" className="boss-btn" onClick={()=>onNavigate("F12")}>
                查看私人日程授权</button>}
            </>}
          </div>
        </Panel>
        <Panel title="历史已确认版本" note="历史只读；不能冒充当前生效设置">
          {(data?.history||[]).length?data?.history.map(x=>
            <div className="boss-workspace-item" key={x.version}>
              <strong>v{x.version} · {x.state}</strong>
              <small>{x.confirmed_at||"历史确认时间未保存"}</small>
            </div>):<p className="boss-helper">尚无被新版本替代的有效配置。</p>}
          <p className="boss-helper">当前设置只由 BOSS 身份保存与确认；
            技术维护端无权读取本人具体目标或替老板启用通知。</p>
        </Panel>
      </div>
    </div>
    {!isGoal&&noticeTx.notice&&<p className="boss-status boss-status-ok" role="status">{noticeTx.notice}</p>}
    {!isGoal&&noticeTx.dialog}
    {!isGoal&&noticeTx.recovery}
    {pending&&<div className="boss-confirm-backdrop">
      <section ref={modalRef} role="dialog" aria-modal="true" tabIndex={-1}
        className="boss-confirm" aria-labelledby="boss-owner-setting-title">
        <h3 id="boss-owner-setting-title"><ShieldCheck size={18}/>{pending.title}</h3>
        <p>此处的保存与启用是两个独立动作。系统验证角色、当前内容、版本与原请求幂等编号。</p>
        <dl>{pending.details.map((line,i)=><div key={i}><dd>{line}</dd></div>)}</dl>
        <label className="boss-confirm-check">
          <input type="checkbox" checked={approved} disabled={busy}
            onChange={e=>setApproved(e.target.checked)}/>
          <span>我已核对本次内容、适用范围及执行后果。</span>
        </label>
        {error&&<p className="boss-validation-error" role="alert">{error}</p>}
        <footer className="boss-actions">
          <button type="button" className="boss-btn" disabled={busy||checking}
            onClick={()=>{setPending(null);setApproved(false);}}>取消</button>
          <button type="button" className="boss-btn" disabled={busy||checking}
            onClick={()=>void reconcile()}>
            {checking&&<Loader2 size={14} className="boss-spin"/>} 查询原请求回执
          </button>
          <button type="button" className="boss-btn boss-btn-primary"
            disabled={!approved||busy||checking} onClick={()=>void submit()}>
            {busy&&<Loader2 size={14} className="boss-spin"/>} 确认并执行
          </button>
        </footer>
      </section>
    </div>}
  </div>;
}
