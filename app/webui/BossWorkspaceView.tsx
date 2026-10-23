import { useEffect, useRef, useState, type ReactNode } from "react";
import { AlertCircle, ArrowRight, CheckCircle2, Clock3,
  FileSearch, FolderOpen, Loader2, RefreshCw,
  ShieldCheck, Sparkles } from "lucide-react";
import { useClient } from "@/providers/ClientProvider";

// Only these routes have real, role-scoped read projections. Routes absent
// from this map still show the original transparent "not implemented" panel.
export const WORKSPACE_PAGE_ROUTES: Record<string, string> = {
  F02: "notifications",


  F13: "memory", F25: "dataset", F26: "plans",
  F28: "authorizations", F29: "decisions",
  F32: "system", N06: "notifications", N07: "memory",
  N08: "notifications", N09: "plans", N10: "authorizations",
  N11: "decisions", D02: "authorizations", D09: "notifications",
  A01: "system", A02: "tool-catalog", A03: "dataset",
  A09: "tool-catalog",
  A10: "metric-definitions", A11: "relationships",
  A12: "source-index", A14: "audit",
  A16: "system", A04: "relationships", F31: "evaluation",
};

type Role = "BOSS" | "MAINTAINER";
type RecordItem = Record<string, unknown>;
type Source = {
  source_id: string; source_type: string; version: string;
  published_at?: string; withdrawn: boolean; author_contact_id?: string;
};
type DocHit = {
  source_id: string; version: string; source_type: string;
  excerpt: string; published_at?: string;
};
type Memory = {
  memory_id: string; text: string; version: string;
  confirmation_state: string;
};
type Event = {
  event_id: string; version: string; state: string; impact: string;
  due_at: string; task_id?: string;
};
type Reminder = {event_id: string; version: string; state: string; until?: string | null};
type Notification = {
  event_id: string; state?: string; source_type?: string;
  created_at?: string; business_at?: string;
};
type Auth = {
  authorization_id: string; action: string; target_id: string; content_version: string;
  revoked: boolean; valid_until: string; valid_from?: string;
};
type Workspace = {
  source_type: "SIMULATED"; namespace: string; data_version: string;
  projection: string; read_at: string;
  memory?: Memory; effective?: boolean; future_turn_policy?: string;
  physical_secure_erasure_verified?: boolean;
  calendar?: RecordItem;
  sources?: Source[]; results?: DocHit[]; query?: string;
  events?: Event[]; notifications?: Notification[]; reminders?: Reminder[];
  deliveries?: RecordItem[]; rules?: RecordItem[];
  authorizations?: Auth[]; history?: RecordItem[]; messages?: RecordItem[];
  contacts?: RecordItem[]; meeting?: RecordItem | null;
  schedule?: RecordItem; business_clock?: string;
  object_counts?: Record<string, number>; record_counts?: Record<string, number>;
  dataset_id?: string; version?: string; seed?: number; generator_version?: string;
  simulated_event_id?: string; business_periods?: Record<string, string[]>;
  operations?: RecordItem[]; metric_definitions?: RecordItem[];
  entity_counts?: Record<string, number>; technical_links?: Record<string, string>;
  notification_draft_only?: boolean; can_edit?: boolean;
  definition_id?: string;definition_version?:string;
  defined_step_count?:number;defined_assertion_count?:number;
  independent_product_evaluation_completed?:boolean;actual_score?:number|null;
  steps?:{step_id:string;actor:string;action:string}[];coverage?:string;
  simulated_business_time?: string;
  installed_mac_app_verified?: boolean;
  model_connection_verified_here?: boolean;
};

type Pending = {
  action: string; fields: Record<string, unknown>;
  id: string; title: string; scope: string[];
};
function v(value: unknown): string {
  if (value === null || value === undefined || value === "") return "待核查";
  if (typeof value === "boolean") return value ? "是" : "否";
  if (typeof value === "number") return String(value);
  if (typeof value === "string") return value;
  return "需查询";
}
function date(value: unknown): string {
  return typeof value === "string" ? value.replace("T", " ") : "待核查";
}
function dateWithZone(value: string): string {
  if (!/^\d{4}-\d\d-\d\dT\d\d:\d\d$/.test(value)) throw new Error("请选择完整日期和时间");
  return value + ":00+08:00";
}
function Layer({title, children, description}: {
  title: string; description?: string; children: ReactNode;
}) {
  return <section className="boss-panel">
    <div className="boss-panel-head"><h2>{title}</h2>{description&&<small>{description}</small>}</div>
    {children}
  </section>;
}
function Fact({label, children}: {label: string; children?: ReactNode}) {
  return <div className="boss-kv"><span>{label}</span><strong>{children??"待核查"}</strong></div>;
}
function Empty({message}: {message:string}) {
  return <div className="boss-empty"><FolderOpen size={21} aria-hidden="true"/><div>
    <strong>当前范围没有可读取记录</strong><p>{message}</p>
  </div></div>;
}
function Notice({message, error=false}: {message:string;error?:boolean}) {
  return <div role={error?"alert":"status"} className={"boss-status "+(error?"boss-status-error":"boss-status-warn")}>
    {error?<AlertCircle size={16}/>:<Clock3 size={16}/>}<span>{message}</span>
  </div>;
}
const ROLES: Record<string,Role> = {
  memory:"BOSS",calendar:"BOSS",notifications:"BOSS",authorizations:"BOSS",
  decisions:"BOSS",outbox:"BOSS",sources:"BOSS",knowledge:"BOSS",
  organization:"BOSS",plans:"BOSS",dataset:"MAINTAINER",
  "source-index":"MAINTAINER","tool-catalog":"MAINTAINER",
  "metric-definitions":"MAINTAINER",relationships:"MAINTAINER",
  scheduler:"MAINTAINER",audit:"MAINTAINER",system:"MAINTAINER",evaluation:"MAINTAINER",
};

export function BossWorkspaceView({pageId, role, onNavigate, onViewSource}: {
  pageId:string; role:Role;
  onNavigate:(id:string)=>void;
  onViewSource:(id:string)=>void;
}) {
  const route = WORKSPACE_PAGE_ROUTES[pageId];
  const {client,getToken} = useClient();
  const [data,setData] = useState<Workspace|null>(null);
  const [revision,setRevision] = useState(0);
  const [loading,setLoading] = useState(false);
  const [error,setError] = useState("");
  const [notice,setNotice] = useState("");
  const [pending,setPending] = useState<Pending|null>(null);
  const [approved,setApproved] = useState(false);
  const [busy,setBusy] = useState(false);
  const [lookupBusy,setLookupBusy] = useState(false);
  const modalRef = useRef<HTMLElement|null>(null);
  const [draft,setDraft] = useState("");
  const [search,setSearch] = useState("");
  const [searched,setSearched] = useState("");
  const [timeInput,setTimeInput] = useState("");
  const [dirty,setDirty] = useState(false);

  useEffect(()=>{
    if(!route || ROLES[route]!==role) {setError("当前角色不允许访问该业务投影");return;}
    const controller = new AbortController();
    const path = "/api/boss/ui/workspace/"+encodeURIComponent(route)+
      (route==="knowledge"?"?q="+encodeURIComponent(searched):"");
    setLoading(true);setError("");setData(null);
    const token=getToken();
    if(!token){setError("身份过期，请重新认证");setLoading(false);return;}
    void fetch(path,{headers:{"Authorization":"Bearer "+token},cache:"no-store",signal:controller.signal})
      .then(async response=>{
        if(!response.ok)throw new Error("工作区服务拒绝读取（HTTP "+response.status+"）");
        const result=await response.json() as Workspace;
        if(result.source_type!=="SIMULATED"||result.projection!==route)
          throw new Error("业务数据类型或来源不一致");
        return result;
      })
      .then(result=>{
        if(controller.signal.aborted)return;
        setData(result);setLoading(false);
        if(route==="memory"&&!dirty)setDraft(result.memory?.text||"");
      }).catch(e=>{
        if(controller.signal.aborted)return;
        setError(e instanceof Error?e.message:String(e));setLoading(false);
      });
    return ()=>controller.abort();
  },[route,role,revision,searched,getToken]);

  useEffect(()=>{
    if(!pending)return;
    const origin=document.activeElement instanceof HTMLElement?document.activeElement:null;
    modalRef.current?.focus();
    const key=(e:KeyboardEvent)=>{
      if(e.key==="Escape"&&!busy){
        setPending(null);setApproved(false);return;
      }
      if(e.key!=="Tab"||!modalRef.current)return;
      const nodes=Array.from(modalRef.current.querySelectorAll<HTMLElement>(
        'button:not([disabled]), input:not([disabled])')).filter(x=>x.getClientRects().length>0);
      if(!nodes.length){e.preventDefault();modalRef.current.focus();return;}
      if(e.shiftKey&&document.activeElement===nodes[0]){e.preventDefault();nodes[nodes.length-1].focus();}
      else if(!e.shiftKey&&document.activeElement===nodes[nodes.length-1]){e.preventDefault();nodes[0].focus();}
    };
    document.addEventListener("keydown",key);
    return ()=>{document.removeEventListener("keydown",key);origin?.focus();};
  },[pending?.id,busy]);

  function reload(){setRevision(x=>x+1);}
  function propose(action:string, fields:Record<string,unknown>, title:string, scope:string[]){
    if(busy)return;
    setNotice("");setError("");
    setPending({action,fields,title,scope,id:"boss-"+crypto.randomUUID()});
    setApproved(false);
  }
  async function commit(){
    if(!pending||!approved||busy)return;
    setBusy(true);setError("");
    try{
      const out=await client.requestMutation<RecordItem>(pending.action,{
        ...pending.fields,client_request_id:pending.id,
      });
      setNotice("模拟业务动作已提交并保存。返回状态："+v(out.confirmation_state??out.state??out.status)+
        "；版本："+v(out.version)+
        "。已重新请求正式业务状态。");
      setPending(null);setApproved(false);setDirty(false);reload();
    }catch(e){
      // Same id on retry after timeout, never automatically generate a new write.
      setError((e instanceof Error?e.message:String(e))+
        "。执行结果可能未同步；请先重读正式业务状态，再用同一个确认框重试。");
    }finally{setBusy(false);}
  }
  async function reconcile(){
    if(!pending||busy||lookupBusy)return;
    const token=getToken();
    if(!token){setError("身份已过期，无法查找该请求回执");return;}
    setLookupBusy(true);setError("");
    try{
      const qs=new URLSearchParams({
        action:pending.action,client_request_id:pending.id,
      });
      const response=await fetch("/api/boss/ui/operation-status?"+qs.toString(),{
        headers:{Authorization:"Bearer "+token},cache:"no-store",
      });
      if(!response.ok)throw Error("幂等回执核查失败（HTTP "+response.status+"）");
      const data=await response.json() as {
        action:string;client_request_id:string;outcome:string;
      };
      if(data.action!==pending.action||data.client_request_id!==pending.id)
        throw Error("幂等回执与当前动作不匹配");
      if(data.outcome==="RECORDED"){
        setNotice("服务端确认当前动作已持久化，已重新读取正式状态。");
        setPending(null);setApproved(false);setDirty(false);reload();
      }else if(data.outcome==="NOT_FOUND_IN_CURRENT_STORE"){
        setError("当前未查到原请求回执，这不是未执行的证明。请先重读状态，必要时复用同一编号重试。");
        reload();
      }else throw Error("无效回执，不能认定已执行");
    }catch(e){setError(e instanceof Error?e.message:String(e));}
    finally{setLookupBusy(false);}
  }
  function confirmMemory(){
    const current=data?.memory;
    if(!current){setError("当前记忆版本未载入");return;}
    if(draft.trim().length<1||draft.length>4000){
      setError("个人要求须为 1—4000 字");return;
    }
    propose("boss.memory.confirm",{
      expected_version:current.version,text:draft.trim(),
    },"本人确认采用这一条长期要求",[
      "作用范围：本人未来的新会话","现有版本："+current.version,
      "要求："+draft.trim(),
      "模型当前运行中的任务不会自动重新读取此修改。",
    ]);
  }
  function deleteMemory(){
    const current=data?.memory;
    if(!current){setError("当前记忆尚未读取");return;}
    if(current.confirmation_state==="DELETED"){setError("当前记忆已经停止采用");return;}
    propose("boss.memory.delete",{expected_version:current.version},
      "本人确认删除长期要求",[
        "当前版本："+current.version,
        "删除后停止未来采用，不宣称已物理擦除全部备份或日志。",
      ]);
  }
  function actOnReminder(event:Event, action:"ack"|"close"|"snooze"){
    const current=(data?.reminders||[]).find(x=>x.event_id===event.event_id);
    if(current?.state==="CLOSED"){setError("已关闭的提醒不能重新开启");return;}
    const fields:Record<string,unknown>={
      event_id:event.event_id,event_version:event.version,
      reminder_version:current?.version||"0",
    };
    if(action==="snooze"){
      try{fields.until=dateWithZone(timeInput);}catch(e){
        setError(e instanceof Error?e.message:String(e));return;
      }
    }
    propose("boss.reminder."+action,fields,
      action==="ack"?"确认知晓":action==="close"?"确认关闭":"确认暂缓提醒",
      [
        "源事件："+event.event_id,
        "事件版本："+event.version+" · 当前提醒版本："+v(fields.reminder_version),
        action==="snooze"?"暂缓至："+v(fields.until):"当前事件状态："+event.state,
        "保留源事件及历史通知记录；不会假定任何外部消息已经发送。",
      ]);
  }
  function seedEvent(){
    const id=data?.technical_links?.event_id||data?.simulated_event_id;
    if(!id){setError("源数据集未提供真实模拟事件标识");return;}
    propose("boss.simulation.event.seed",{event_id:id},"注入获准模拟事件",[
      "事件标识："+id,
      "只使用当前已批准的数据集，不虚构新事件或联系人的身份。",
      "调度结果由本机 CronService 后续执行，不能提前标记送达。",
    ]);
  }
  function advanceClock(){
    let at="";
    try{at=dateWithZone(timeInput);}catch(e){
      setError(e instanceof Error?e.message:String(e));return;
    }
    propose("boss.simulation.clock.advance",{at},"推进模拟业务时钟",[
      "目标模拟时间："+at,
      "时钟只能前进，最多前进 366 天。",
      "计时与通知由实际调度器决定，不等于立刻产生一条通知。",
    ]);
  }
  if(!route) return <Notice error message="该页面还没有获准的业务读取接口。"/>;
  if(ROLES[route]!==role) return <Notice error message="当前身份不可访问此业务页面。"/>;
  const w=data;
  return <>
    <div className="boss-workspace-toolbar">
      <div className="boss-workspace-note">
        <span className="boss-tag boss-tag-amber">SIMULATED</span>
        <span>{route} · {w?.data_version?"资料版本 "+w.data_version:"等待读取"}</span>
      </div>
      <button className="boss-btn" type="button" onClick={reload} disabled={loading}>
        {loading?<Loader2 className="boss-spin" size={15}/>:<RefreshCw size={15}/>} 重新读取
      </button>
    </div>
    {loading&&<Notice message="正在向本机受权限控制的业务服务读取数据与版本…"/>}
    {error&&<Notice error message={error}/>}
    {notice&&<div className="boss-status boss-status-ok" role="status"><CheckCircle2 size={17}/>{notice}</div>}
    {w&&<div className="boss-columns">
      <div className="boss-column">
        {route==="memory"&&<Layer title="长期决定与个人记忆" description="仅本人可修改 · FR-13">
          <Fact label="业务状态">{v(w.memory?.confirmation_state)}</Fact>
          <Fact label="当前版本">{v(w.memory?.version)}</Fact>
          <Fact label="新会话采用">{w.effective?"本人已经确认采用":"不采用（已删除/未确认）"}</Fact>
          <label className="boss-label" htmlFor="boss-memory-input">本人确认的持续要求</label>
          <textarea id="boss-memory-input" rows={5} value={draft}
            onChange={e=>{setDraft(e.target.value);setDirty(true);}}
            placeholder="例如：每日简报优先关注现金、承诺和待决定事项。"/>
          <div className="boss-actions">
            <button type="button" className="boss-btn boss-btn-primary" onClick={confirmMemory}>
              <ShieldCheck size={15}/> 本人确认并保存当前版本
            </button>
            <button type="button" className="boss-btn" disabled={w.memory?.confirmation_state==="DELETED"}
              onClick={deleteMemory}>本人确认停止采用</button>
          </div>
          <Notice message="本次保存会更新当前业务版本，后续新任务只采用 CONFIRMED。删除会停止未来采用；备份和磁盘级擦除仍需独立验收。"/>
        </Layer>}
        {route==="calendar"&&<Layer title="本人私人安排" description="FR-12 · 不向维护角色展示正文">
          <Fact label="日程标识">{v(w.calendar?.calendar_id)}</Fact>
          <Fact label="时间范围">{date(w.calendar?.starts_at)} — {date(w.calendar?.ends_at)}</Fact>
          <Fact label="时区">{v(w.calendar?.timezone)}</Fact>
          <div className="boss-private-source">
            <strong><ShieldCheck size={16}/> 仅本人可见的正文</strong>
            <p>{v(w.calendar?.private_body)}</p>
          </div>
          <Notice message="真实业务来源已读取。当前尚未实现私人安排新增、编辑和授权共享；不会把私人正文发送给维护端或联系人。"/>
        </Layer>}
        {route==="notifications"&&<Layer title="经营通知与提醒" description="FR-02 · 持续按真实事件版本读取">
          {(w.events||[]).length? (w.events||[]).map(event=>{
            const reminder=w.reminders?.find(r=>r.event_id===event.event_id);
            return <article className="boss-workspace-item" key={event.event_id}>
              <div className="boss-workspace-item-top">
                <strong>{event.event_id}</strong>
                <span className="boss-tag boss-tag-blue">{event.state}</span>
              </div>
              <Fact label="事件版本">{event.version}</Fact>
              <Fact label="事件到期">{date(event.due_at)}</Fact>
              <Fact label="当前提醒决定">{reminder?.state||"尚未处理"}</Fact>
              <Fact label="已交付通知">{(w.notifications||[]).filter(n=>n.event_id===event.event_id).length}</Fact>
              <div className="boss-actions">
                <button className="boss-btn" type="button" disabled={reminder?.state==="CLOSED"}
                  onClick={()=>actOnReminder(event,"ack")}>已知晓</button>
                <button className="boss-btn" type="button" disabled={reminder?.state==="CLOSED"}
                  onClick={()=>actOnReminder(event,"snooze")}>暂缓</button>
                <button className="boss-btn" type="button" disabled={reminder?.state==="CLOSED"}
                  onClick={()=>actOnReminder(event,"close")}>关闭</button>
              </div>
            </article>;
          }):<Empty message="当前模拟空间还没有注入实际事件。维护端需要按获准数据集显式注入，不能制造虚假通知。"/>}
          {(w.events||[]).length>0&&<label className="boss-field">
            <span>暂缓至（Asia/Shanghai）</span>
            <input type="datetime-local" value={timeInput} onChange={e=>setTimeInput(e.target.value)}/>
          </label>}
          <Notice message="知晓、暂缓和关闭按当前事件版本与提醒版本原子保存。关闭不删除历史通知。"/>
        </Layer>}
        {route==="knowledge"&&<Layer title="来源可追溯的资料检索" description="FR-09 · 只检索当前有效模拟资料">
          <form className="boss-workspace-search" onSubmit={e=>{e.preventDefault();setSearched(search.trim());}}>
            <label htmlFor="boss-knowledge-input" className="boss-label">检索词</label>
            <input id="boss-knowledge-input" value={search} onChange={e=>setSearch(e.target.value)}
              placeholder="例如：毛利、会议纪要、资料来源"/>
            <button type="submit" className="boss-btn boss-btn-primary"><FileSearch size={15}/> 检索</button>
          </form>
          {(w.results||[]).length?(w.results||[]).map(row=><div className="boss-workspace-item" key={row.source_id}>
            <div className="boss-workspace-item-top"><strong>{row.source_id}</strong><span className="boss-tag boss-tag-green">{row.source_type}</span></div>
            <p>{row.excerpt}</p><small>版本 {row.version} · {date(row.published_at)}</small>
            <div className="boss-actions"><button className="boss-btn" type="button"
              onClick={()=>onViewSource(row.source_id)}>查看原始依据 <ArrowRight size={15}/></button></div>
          </div>):<Empty message="没有与本次查询匹配的有效来源。不能据此生成没有依据的研究结论。"/>}
        </Layer>}
        {(route==="sources"||route==="source-index")&&<Layer title={role==="BOSS"?"当前资料与证据":"模拟知识源目录"} description="每条资料保留原始版本及撤销状态">
          {(w.sources||[]).map(source=><article className="boss-workspace-item" key={source.source_id}>
            <div className="boss-workspace-item-top"><strong>{source.source_id}</strong>
              <span className={"boss-tag "+(source.withdrawn?"boss-tag-amber":"boss-tag-green")}>{source.withdrawn?"已撤销":"当前有效"}</span></div>
            <Fact label="来源类型">{source.source_type}</Fact>
            <Fact label="资料版本">{source.version}</Fact>
            <Fact label="更新日期">{date(source.published_at)}</Fact>
            {role==="BOSS"&&!source.withdrawn&&<div className="boss-actions">
              <button className="boss-btn" type="button" onClick={()=>onViewSource(source.source_id)}>查看原始来源</button>
            </div>}
          </article>)}
          {!(w.sources||[]).length&&<Empty message="当前没有获准资料源。"/>}
          {role==="MAINTAINER"&&<Notice message="技术目录不返回原文或老板私人记忆。资料发布、撤销和索引传播需要单独的审核与一致性实现。"/>}
        </Layer>}
        {route==="organization"&&<Layer title="会议、人员与来源关系" description="FR-04 · 仅显示已有模拟关系">
          <Fact label="会议编号">{v(w.meeting?.meeting_id)}</Fact>
          <Fact label="开始时间">{date(w.meeting?.starts_at)}</Fact>
          <Fact label="参会人">{Array.isArray(w.meeting?.participant_ids)?w.meeting.participant_ids.join("、"):"未提供"}</Fact>
          {(w.contacts||[]).map(c=><div className="boss-workspace-item" key={v(c.contact_id)}>
            <strong>{v(c.name)} · {v(c.organization)}</strong>
            <small>{v(c.contact_id)} · {v(c.responsibility)}</small>
          </div>)}
          <Notice message="当前仅有可核查的会议、联系人和原始资料关系。会前简报的模型生成、会后纪要分类及审批仍需专业逻辑。"/>
          <div className="boss-actions">
            <button className="boss-btn" type="button" onClick={()=>onNavigate("N04")}>打开会议资料 <ArrowRight size={15}/></button>
          </div>
        </Layer>}
        {route==="outbox"&&<Layer title="已授权模拟发件箱" description="FR-08 · 发送与送达分开">
          {(w.messages||[]).map((row,i)=><div className="boss-workspace-item" key={v(row.message_id)+String(i)}>
            <div className="boss-workspace-item-top"><strong>{v(row.message_id)}</strong>
              <span className="boss-tag boss-tag-green">{v(row.message_status)}</span></div>
            <Fact label="关联交办">{v(row.task_id)}</Fact>
            <Fact label="收件人">{v(row.recipient_id)}</Fact>
            <Fact label="模拟发送时间">{date(row.sent_at)}</Fact>
            <Fact label="任务版本">{v(row.task_version)}</Fact>
          </div>)}
          {!(w.messages||[]).length&&<Empty message="目前没有经过本人授权且已保存的模拟消息。"/>}
          <Notice message="记录中的 SENT 仅为本地模拟发件箱结果，不证明真实外部渠道已投递、送达或回复。"/>
        </Layer>}
        {route==="authorizations"&&<Layer title="本人动作授权" description="FR-28 · 有效期、动作与对象">
          {(w.authorizations||[]).map((a,i)=><div className="boss-workspace-item" key={a.authorization_id+String(i)}>
            <div className="boss-workspace-item-top"><strong>{a.action}</strong>
              <span className={"boss-tag "+(a.revoked?"boss-tag-amber":"boss-tag-blue")}>{a.revoked?"已撤销":"未撤销"}</span></div>
            <Fact label="授权标识">{a.authorization_id}</Fact>
            <Fact label="对象">{a.target_id}</Fact>
            <Fact label="内容版本">{a.content_version}</Fact>
            <Fact label="截止时间">{date(a.valid_until)}</Fact>
          </div>)}
          {!(w.authorizations||[]).length&&<Empty message="尚无明确授权记录。没有记录不代表 Agent 可以自行执行写入。"/>}
          <Notice message="仅返回当前本人获准的授权元信息。撤销尚未执行授权与修改范围的独立操作仍待实现。"/>
        </Layer>}
        {route==="decisions"&&<Layer title="已保存的历史决定" description="N11 · 只读，不重写过去依据">
          {(w.history||[]).map((h,i)=><div className="boss-workspace-item" key={String(i)}>
            <strong>{v(h.action)}</strong>
            <small>顺序号 {v(h.sequence)} · {date(h.at)}</small>
          </div>)}
          {!(w.history||[]).length&&<Empty message="没有经过真实业务动作写入的历史决定。"/>}
          <Notice message="历史只读。曾经的来源与对象版本不会因为今天的新决定自动改写。"/>
        </Layer>}
        {route==="plans"&&<Layer title="本人计划与执行时钟" description="N09 · 读取当前真实计划版本">
          <Fact label="计划 ID">{v(w.schedule?.schedule_id)}</Fact>
          <Fact label="版本">{v(w.schedule?.version)}</Fact>
          <Fact label="是否启用">{v(w.schedule?.enabled)}</Fact>
          <Fact label="是否取消">{v(w.schedule?.canceled)}</Fact>
          <Fact label="计划时区">{v(w.schedule?.timezone)}</Fact>
          <Fact label="当前模拟业务时钟">{date(w.business_clock)}</Fact>
          <Notice message="调度执行与老板的个人计划互相独立。当前尚未提供完整本人计划新增/编辑接口，不显示虚构日程。"/>
        </Layer>}
        {role==="MAINTAINER"&&route==="dataset"&&<Layer title="获准模拟数据集" description="FR-25 · 数据版本、种子与对象数量">
          <Fact label="数据集">{v(w.dataset_id)}</Fact>
          <Fact label="版本">{v(w.version)}</Fact>
          <Fact label="生成器">{v(w.generator_version)}</Fact>
          <Fact label="重现 Seed">{v(w.seed)}</Fact>
          <Fact label="标准模拟事件">{v(w.simulated_event_id)}</Fact>
          {Object.entries(w.object_counts||{}).map(([k,n])=><Fact key={k} label={k}>{n}</Fact>)}
          <Notice message="数据集重置需创建独立 execution_namespace 并处理并发任务；该能力暂未实现，不允许在当前页面直接清库。"/>
        </Layer>}
        {role==="MAINTAINER"&&route==="relationships"&&<Layer title="模拟关系与数据时钟" description="A04/A11 · 有权模拟事件">
          {Object.entries(w.entity_counts||{}).map(([k,n])=><Fact key={k} label={k}>{n}</Fact>)}
          <Fact label="会议 ID">{v(w.technical_links?.meeting_id)}</Fact>
          <Fact label="事件 ID">{v(w.technical_links?.event_id)}</Fact>
          <Fact label="当前业务时钟">{date(w.business_clock)}</Fact>
          <div className="boss-actions">
            <button type="button" className="boss-btn boss-btn-primary" onClick={seedEvent}>
              <Sparkles size={15}/> 注入当前数据集的模拟事件
            </button>
          </div>
          <label className="boss-field"><span>推进模拟业务时钟（Asia/Shanghai）</span>
            <input type="datetime-local" value={timeInput} onChange={e=>setTimeInput(e.target.value)}/></label>
          <div className="boss-actions">
            <button type="button" className="boss-btn" onClick={advanceClock}>
              <Clock3 size={15}/> 核对并推进时钟
            </button>
          </div>
          <Notice message="上述两项属于维护测试输入，不会获得任何老板业务授权，也不保证通知已发送。"/>
        </Layer>}
        {role==="MAINTAINER"&&route==="tool-catalog"&&<Layer title="业务工具目录" description="源自已发布的 JSON Schema">
          {(w.operations||[]).map((op,i)=><div className="boss-workspace-item" key={String(i)}>
            <strong>{v(op.operation_id)}</strong>
            <small>输入：{v(op.input_schema)}</small>
            <small>输出：{v(op.output_schema)}</small>
          </div>)}
          <Notice message="工具目录是实际后端契约；逐项参数测试与激活版本仍需技术维护审查。"/>
        </Layer>}
        {role==="MAINTAINER"&&route==="metric-definitions"&&<Layer title="经营指标、单位与公式" description="Decimal · definition_version=1">
          {(w.metric_definitions||[]).map((row,i)=><div className="boss-workspace-item" key={String(i)}>
            <div className="boss-workspace-item-top"><strong>{v(row.metric_id)}</strong><span className="boss-tag boss-tag-blue">{v(row.unit)}</span></div>
            <Fact label="公式">{v(row.formula)}</Fact>
            <Fact label="统计范围">{v(row.scope)}</Fact>
            <Fact label="核算状态">{v(row.settlement_state)}</Fact>
          </div>)}
          <Notice message="指标的计算责任仍属于后端查询工具。编辑和启用新指标版本需单独开发及验收。"/>
        </Layer>}
        {role==="MAINTAINER"&&route==="scheduler"&&<Layer title="调度器与运行配置" description="A13 · 当前持久化版本">
          <Fact label="计划">{v(w.schedule?.schedule_id)}</Fact>
          <Fact label="当前版本">{v(w.schedule?.version)}</Fact>
          <Fact label="触发方式">{v(w.schedule?.trigger)}</Fact>
          <Fact label="技术开关">{v(w.schedule?.enabled)}</Fact>
          <Fact label="业务时钟">{date(w.simulated_business_time)}</Fact>
          <Notice message="这是数据库配置，不是 CronService 实际运行证明。暂停、取消、重启恢复需由原生调度器执行并独立验证。"/>
        </Layer>}
        {role==="MAINTAINER"&&route==="audit"&&<Layer title="动作与授权追踪元数据" description="A14 · 不展示业务正文">
          {(w.operations||[]).map((x,i)=><div className="boss-workspace-item" key={String(i)}>
            <strong>{v(x.operation)}</strong><small>序号 {v(x.sequence)} · {date(x.created_at)}</small>
          </div>)}
          {!(w.operations||[]).length&&<Empty message="没有已持久化的审计事件。"/>}
        </Layer>}
        {role==="MAINTAINER"&&route==="evaluation"&&<Layer title="独立演示评测规范" description="F31 · 尚未运行正式产品评测">
          <Fact label="定义版本">{v(w.definition_version)}</Fact>
          <Fact label="已定义测试步骤">{v(w.defined_step_count)}</Fact>
          <Fact label="已定义检查断言">{v(w.defined_assertion_count)}</Fact>
          <Fact label="实际产品评测结论">尚未执行</Fact>
          <Fact label="有效评分">未知（不得填写零）</Fact>
          {(w.steps||[]).map(item=><div key={item.step_id} className="boss-workspace-item">
            <div className="boss-workspace-item-top"><strong>{item.step_id}</strong>
              <span className="boss-tag boss-tag-blue">{item.actor}</span></div>
            <p>{item.action}</p>
          </div>)}
          <Notice message="这只是已固定的检查定义，不是执行结果。最终验收需独立准备数据、逐条运行、输出证据和失败用例。"/>
        </Layer>}
        {role==="MAINTAINER"&&route==="system"&&<Layer title="本地系统部署状态" description="安装与系统能力需实测">
          <Fact label="执行空间">{v(w.namespace)}</Fact>
          {Object.entries(w.record_counts||{}).map(([k,n])=><Fact key={k} label={k}>{n}</Fact>)}
          <Fact label="macOS 完整安装是否通过">{v(w.installed_mac_app_verified)}</Fact>
          <Fact label="DeepSeek 本机连通性">{v(w.model_connection_verified_here)}</Fact>
          <Notice message="这里是当前数据集的技术概况，不会推断实际签名、休眠恢复、网路重连或已发行状态。"/>
        </Layer>}
      </div>
      <div className="boss-column">
        <Layer title="来源、状态和当前操作" description="统一的 Desktop v6 信任边界">
          <Fact label="数据来源">{w.source_type}</Fact>
          <Fact label="业务执行空间">{w.namespace}</Fact>
          <Fact label="资料版本">{w.data_version}</Fact>
          <Fact label="本次读取时间">{date(w.read_at)}</Fact>
          <Fact label="当前操作角色">{role==="BOSS"?"老板本人":"技术维护"}</Fact>
          <div className="boss-actions">
            <button type="button" className="boss-btn" onClick={()=>onNavigate(role==="BOSS"?"F01":"A08")}>
              <ArrowRight size={15}/> 返回工作台
            </button>
          </div>
        </Layer>
        {route==="notifications"&&<Layer title="通知状态摘要">
          <Fact label="模拟事件">{(w.events||[]).length}</Fact>
          <Fact label="已生成通知">{(w.notifications||[]).length}</Fact>
          <Fact label="送达回执">{(w.deliveries||[]).length}</Fact>
          <Fact label="已保存的本人提醒决定">{(w.reminders||[]).length}</Fact>
          <Notice message="未触发、静默、冷却和已送达须分别展示；总数为零不能解释为后台故障。"/>
        </Layer>}
        {route==="memory"&&<Layer title="记忆采用及删除边界">
          <Fact label="记忆标识">{v(w.memory?.memory_id)}</Fact>
          <Fact label="未来采用规则">{v(w.future_turn_policy)}</Fact>
          <Fact label="是否已核验磁盘物理擦除">{v(w.physical_secure_erasure_verified)}</Fact>
          <Notice message="个人记忆不得由技术维护员修改；长期要求不可由短期聊天自动推断。"/>
        </Layer>}
        {role==="MAINTAINER"&&route==="dataset"&&<Layer title="事件模拟（需本人二次核对）">
          <Fact label="事件源">{v(w.simulated_event_id)}</Fact>
          <button type="button" className="boss-btn boss-btn-primary" onClick={seedEvent}>
            <Sparkles size={15}/> 模拟事件注入
          </button>
          <Notice message="该操作只写入模拟事件与调度规则，不创建老板审批或真实外部消息。"/>
        </Layer>}
        {role==="MAINTAINER"&&route==="relationships"&&<Layer title="关联对象边界">
          <Fact label="联系人是否拥有登录账号">否</Fact>
          <Fact label="业务执行身份">只有老板</Fact>
          <Fact label="维护者权限">只能录入模拟资料</Fact>
        </Layer>}
        {["organization","knowledge","sources","outbox"].includes(route)&&<Layer title="后续有权操作">
          <div className="boss-workspace-next">
            <button type="button" onClick={()=>onNavigate("N02")} className="boss-btn">
              <Sparkles size={15}/> 进入真正的 Agent 会话
            </button>
            <button type="button" onClick={()=>onNavigate("F06")} className="boss-btn">
              <CheckCircle2 size={15}/> 查看当前交办与授权
            </button>
          </div>
        </Layer>}
        {["tool-catalog","metric-definitions","source-index","scheduler","system"].includes(route)&&
          <Layer title="配置采用和验收">
            <Notice message="页面目前读取的是实际业务/技术状态。新增、校验、启用、重启采用和验收属于独立阶段，不会把只读目录标成完整配置管理。"/>
          </Layer>}
      </div>
    </div>}
    {pending&&<div className="boss-confirm-backdrop">
      <section className="boss-confirm" role="dialog" aria-modal="true"
        aria-labelledby="boss-workspace-confirm" tabIndex={-1} ref={modalRef}>
        <h3 id="boss-workspace-confirm"><ShieldCheck size={19}/>{pending.title}</h3>
        <p>提交将实际写入当前 SIMULATED 数据集。系统会同时验证当前身份、对象版本和幂等请求编号。</p>
        <dl>{pending.scope.map((t,i)=><div key={i}><dd>{t}</dd></div>)}</dl>
        <label className="boss-confirm-check">
          <input type="checkbox" checked={approved} disabled={busy}
            onChange={e=>setApproved(e.target.checked)}/>
          <span>我确认本次具体对象、内容与执行后果。</span>
        </label>
        {error&&<Notice error message={error}/>}
        <footer className="boss-actions">
          <button type="button" className="boss-btn" onClick={()=>{setPending(null);setApproved(false);}} disabled={busy||lookupBusy}>取消</button>
          <button type="button" className="boss-btn" onClick={()=>void reconcile()}
            disabled={busy||lookupBusy}>
            {lookupBusy&&<Loader2 size={15} className="boss-spin"/>} 核查原请求回执
          </button>
          <button type="button" className="boss-btn boss-btn-primary"
            disabled={!approved||busy||lookupBusy} onClick={()=>void commit()}>
            {busy&&<Loader2 size={15} className="boss-spin"/>} 确认并提交
          </button>
        </footer>
      </section>
    </div>}
  </>;
}
