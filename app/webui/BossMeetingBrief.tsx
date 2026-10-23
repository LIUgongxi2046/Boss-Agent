import { useEffect, useRef, useState, type ReactNode } from "react";
import { AlertCircle, ArrowLeft, CheckCircle2, Clock3, FileSearch,
  FolderOpen, Loader2, RefreshCw, ShieldCheck, Send, ClipboardList } from "lucide-react";
import { useClient } from "@/providers/ClientProvider";

type Source={source_id:string;version:string|null;status:string;published_at?:string;
  author_contact_id?:string;excerpt:string|null};
type Commitment={task_id:string;status:string;due_at:string;is_historical:boolean;
  evidence_requirements:string[]};
type Participant={contact_id:string;name?:string;organization?:string;
  responsibility?:string;status:string};
type Metrics={available:boolean;reason?:string;
  values:{period_scope:string;date_range:string[];source_id:string;
  source_version:string;definition_version:string;
  metrics:Record<string,{value:string|null;unit:string}>;
  detail_refs:string[]}[];unexplained_causes:string[]};
type Compiled={meeting:{meeting_id:string;version:string;starts_at:string;timezone:string;ends_at?:string|null;state?:string;preparation_due_at?:string|null};
  participants:Participant[];sources:Source[];commitments:Commitment[];
  event:{event_id:string;status:string;origin:string};metrics:Metrics;
  travel_impacts?:{travel_id:string;version:string;meeting_end_known:boolean}[];
  owner_goal_reference?:{status:string;active_version:string|null;scope:string|null;goal_count?:number;topic_count?:number};
  people_meeting_impacts?:{brief_id:string;version:string;contact_id:string;
    meeting_version:string;source_state:string;
    pinned_source_versions:{source_id:string;version:string}[]}[];
  missing_items:string[];needs_review:boolean;source_type:"SIMULATED"};
type Saved={brief_id:string;meeting_id:string;version:string;state:string;
  prepared_at:string;reviewed_by_owner:false;meeting_occurred:boolean;
  message_sent:false;compiled:Compiled};
type Briefing={source_type:"SIMULATED";projection:"briefing";data_version:string;
  saved:boolean;saved_brief:Saved|null;current:Compiled;current_status:string;
  needs_review:boolean;source_changed?:boolean;participant_changed?:boolean;
  business_changed?:boolean;revisions:{version:string;state:string;prepared_at:string}[];
  meeting_occurred:boolean;material_request_sent:false};
type Pending={action:string;payload:Record<string,unknown>;id:string;
  title:string;details:string[]};
type Receipt={action:string;client_request_id:string;outcome:string;result?:{
  version?:string;state?:string;status?:string;draft_id?:string;
}};
type Props={onNavigate:(page:string)=>void;onViewSource:(id:string)=>void;onMessageDraftCreated:(id:string)=>void;refreshVersion?:number};

const textTime=(raw:string)=>raw.replace("T"," ");
function Panel({title,children,note}:{title:string;note?:string;children:ReactNode}){
  return <section className="boss-panel">
    <div className="boss-panel-head"><h2>{title}</h2>{note&&<small>{note}</small>}</div>
    {children}
  </section>;
}
function Fact({label,value}:{label:string;value:string|number|null|undefined}){
  return <div className="boss-kv"><span>{label}</span><strong>{value??"未知"}</strong></div>;
}
export function BossMeetingBrief({onNavigate,onViewSource,onMessageDraftCreated,refreshVersion=0}:Props){
  const {client,getToken}=useClient();
  const [data,setData]=useState<Briefing|null>(null);
  const [revision,setRevision]=useState(0);
  const [loading,setLoading]=useState(false);
  const [error,setError]=useState("");
  const [notice,setNotice]=useState("");
  const [selectedContact,setSelectedContact]=useState("");
  const [tab,setTab]=useState<"议题"|"历史承诺"|"待决定"|"材料缺口">("议题");
  const [pending,setPending]=useState<Pending|null>(null);
  const [approved,setApproved]=useState(false);
  const [busy,setBusy]=useState(false);
  const [checking,setChecking]=useState(false);
  const modalRef=useRef<HTMLElement|null>(null);
  const reload=()=>setRevision(x=>x+1);
  useEffect(()=>{
    const controller=new AbortController();
    const token=getToken();
    if(!token){setError("老板身份已失效");return;}
    setLoading(true);setError("");setData(null);
    void fetch("/api/boss/ui/workspace/briefing",{
      headers:{Authorization:"Bearer "+token},cache:"no-store",
      signal:controller.signal,
    }).then(async r=>{
      if(!r.ok)throw Error("会前材料读取失败，HTTP "+r.status);
      const result=await r.json() as Briefing;
      if(result.projection!=="briefing"||result.source_type!=="SIMULATED")
        throw Error("资料来源不符合本次获准业务范围");
      return result;
    }).then(result=>{
      if(controller.signal.aborted)return;
      setData(result);setLoading(false);
    }).catch(e=>{
      if(controller.signal.aborted)return;
      setError(e instanceof Error?e.message:String(e));setLoading(false);
    });
    return ()=>controller.abort();
  },[revision,getToken,refreshVersion]);

  useEffect(()=>{
    if(!pending)return;
    const before=document.activeElement instanceof HTMLElement?document.activeElement:null;
    modalRef.current?.focus();
    const key=(e:KeyboardEvent)=>{
      if(e.key==="Escape"&&!busy&&!checking){setPending(null);setApproved(false);return;}
      if(e.key!=="Tab"||!modalRef.current)return;
      const nodes=Array.from(modalRef.current.querySelectorAll<HTMLElement>(
        "button:not([disabled]),input:not([disabled])")).filter(x=>x.getClientRects().length>0);
      if(!nodes.length)return;
      if(e.shiftKey&&document.activeElement===nodes[0]){
        e.preventDefault();nodes[nodes.length-1].focus();
      }else if(!e.shiftKey&&document.activeElement===nodes[nodes.length-1]){
        e.preventDefault();nodes[0].focus();
      }
    };
    document.addEventListener("keydown",key);
    return ()=>{document.removeEventListener("keydown",key);before?.focus();};
  },[pending?.id,busy,checking]);

  function propose(action:string,payload:Record<string,unknown>,title:string,details:string[]){
    if(busy)return;
    setPending({action,payload,id:"boss-"+crypto.randomUUID(),title,details});
    setApproved(false);setNotice("");setError("");
  }
  async function submit(){
    if(!pending||!approved||busy||checking)return;
    setBusy(true);setError("");
    try{
      const r=await client.requestMutation<{state?:string;status?:string;version?:string;
        draft_id?:string}>(pending.action,{...pending.payload,client_request_id:pending.id});
      if(pending.action==="boss.message.draft.save"&&r.draft_id)onMessageDraftCreated(r.draft_id);
      setNotice("已保存实际模拟业务结果："+(r.state||r.status||"DRAFT")+
        "；版本 "+(r.version||"1")+
        "。资料请求只成为草稿，不会发送。");
      setPending(null);setApproved(false);reload();
    }catch(e){
      setError((e instanceof Error?e.message:String(e))+
        "。本次可能已执行；请查询同一请求的回执，不要换编号盲目重试。");
    }finally{setBusy(false);}
  }
  async function reconcile(){
    if(!pending||busy||checking)return;
    const token=getToken();
    if(!token){setError("已失去认证，不能核查回执");return;}
    setChecking(true);setError("");
    try{
      const params=new URLSearchParams({
        action:pending.action,client_request_id:pending.id,
      });
      const res=await fetch("/api/boss/ui/operation-status?"+params.toString(),{
        headers:{Authorization:"Bearer "+token},cache:"no-store",
      });
      if(!res.ok)throw Error("原请求回执查询失败（HTTP "+res.status+"）");
      const outcome=await res.json() as Receipt;
      if(outcome.action!==pending.action||outcome.client_request_id!==pending.id)
        throw Error("操作标识不匹配");
      if(outcome.outcome==="RECORDED"){
        if(pending.action==="boss.message.draft.save"&&outcome.result?.draft_id)onMessageDraftCreated(outcome.result.draft_id);
        setNotice("服务端确认当前动作已落库，正在重读正式业务状态。");
        setPending(null);setApproved(false);reload();
      }else if(outcome.outcome==="NOT_FOUND_IN_CURRENT_STORE"){
        setError("没有查到当前请求回执，不代表肯定未执行。请核对业务页面并用同一个请求编号重试。");
        reload();
      }else throw Error("未知操作结果，不能当作成功");
    }catch(e){setError(e instanceof Error?e.message:String(e));}
    finally{setChecking(false);}
  }

  function prepare(){
    if(!data)return;
    const meeting=data.current.meeting;
    propose("boss.meeting.brief.prepare",{
      meeting_id:meeting.meeting_id,meeting_version:meeting.version,
      expected_version:data.saved_brief?.version||"0",
    },"保存当前来源版本的会前材料",[
      "会议："+meeting.meeting_id+" v"+meeting.version,
      "材料数量："+data.current.sources.length,
      "已有承诺："+data.current.commitments.length,
      "待补资料："+data.current.missing_items.length,
      "此操作只保存当前快照，不会创建任务、修改会议或自动发送消息。",
    ]);
  }
  function requestMaterials(){
    if(!data)return;
    if(!data.current.missing_items.length){
      setError("当前没有已发现的缺失资料；请勿生成无依据的资料请求");return;
    }
    const person=data.current.participants.find(x=>x.contact_id===selectedContact);
    if(!person||person.status!=="CURRENT"){
      setError("请选择会议资料中有效的唯一联系人ID");return;
    }
    const body="关于会议 "+data.current.meeting.meeting_id+
      "，请补充以下待核查资料："+data.current.missing_items.join("；")+
      "。请说明有效来源版本和预计提供时间。";
    propose("boss.message.draft.save",{
      draft_id:null,expected_version:"0",recipient_id:person.contact_id,
      related_task_id:null,body,attachment_refs:[],visibility:"RECIPIENT_ONLY",
    },"保存会前缺失资料请求草稿",[
      "收件人："+person.contact_id+" / "+(person.organization||"待核查"),
      "请求正文："+body,
      "保存为 F08 DRAFT；绝不代表已经发送或送达。",
    ]);
  }
  const b=data?.current;
  const saved=data?.saved_brief;
  return <>
    <div className="boss-workspace-toolbar">
      <span className="boss-workspace-note">
        <span className="boss-tag boss-tag-amber">SIMULATED · BOSS ONLY</span>
        F04 · 会议与资料 · 有据可查的会前准备
      </span>
      <button type="button" className="boss-btn" onClick={reload} disabled={loading}>
        {loading?<Loader2 size={15} className="boss-spin"/>:<RefreshCw size={15}/>} 重读当前来源
      </button>
    </div>
    {loading&&<div className="boss-status"><Loader2 size={16} className="boss-spin"/>正在校验参会人、承诺与来源…</div>}
    {error&&<div className="boss-status boss-status-error" role="alert"><AlertCircle size={16}/>{error}</div>}
    {notice&&<div className="boss-status boss-status-ok" role="status"><CheckCircle2 size={16}/>{notice}</div>}
    <section className="boss-panel boss-meeting-filters">
      <div className="boss-form-grid">
        <label>会议对象<select value={b?.meeting.meeting_id||""} onChange={()=>reload()}>
          <option value={b?.meeting.meeting_id||""}>{b?.meeting.meeting_id||"等待选择会议"}</option>
        </select></label>
        <label>日期时间<input readOnly value={b?.meeting.starts_at?textTime(b.meeting.starts_at):"待查询"}/></label>
        <label>时区<input readOnly value={b?.meeting.timezone||"待查询"}/></label>
        <label>参会联系人<input readOnly value={b?.participants.map(x=>x.contact_id).join("、")||"待查询"}/></label>
      </div>
      <div className="boss-actions">
        <button type="button" className="boss-btn boss-btn-primary" onClick={reload} disabled={loading}>
          <RefreshCw size={15}/> 查询 / 应用当前会议
        </button>
      </div>
    </section>
    <div className="boss-columns">
      <div className="boss-column">
        <nav className="boss-minutes-tabs" aria-label="F04会前材料分类">
          {(["议题","历史承诺","待决定","材料缺口"] as const).map(item=>
            <button type="button" key={item} aria-current={tab===item?"page":undefined}
              className={tab===item?"selected":""} onClick={()=>setTab(item)}>
              {item}
              <span>{item==="历史承诺"?b?.commitments.length??0:
                item==="材料缺口"?b?.missing_items.length??0:
                item==="议题"?b?.sources.length??0:"—"}</span>
            </button>)}
        </nav>
    
        <div className="boss-tab-view" hidden={tab!=="议题"}>
        <Panel title="会议资料与准备状态" note="会议标识、时间、参会联系人">
          <Fact label="会议 ID" value={b?.meeting.meeting_id}/>
          <Fact label="会议版本" value={b?.meeting.version}/>
          <Fact label="开始时间" value={b?textTime(b.meeting.starts_at):null}/>
          <Fact label="结束时间" value={b?.meeting.ends_at?textTime(b.meeting.ends_at):"尚未提供"}/>
          <Fact label="会议状态" value={b?.meeting.state||"DRAFT"}/>
          <Fact label="IANA 时区" value={b?.meeting.timezone}/>
          <Fact label="已保存材料版本" value={saved?.version||"尚未准备"}/>
          <Fact label="当前资料状态" value={data?.current_status||"待读取"}/>
          {(b?.participants||[]).map(person=><div className="boss-workspace-item" key={person.contact_id}>
            <strong>{person.name||"身份待核对"} · {person.organization||"未知"}</strong>
            <small>{person.contact_id} · {person.responsibility||"缺少角色"} · {person.status}</small>
          </div>)}
          {data?.needs_review&&<div role="status" className="boss-status boss-status-warn">
            <AlertCircle size={16}/> 当前材料需要核查；历史已保存快照不会被静默覆盖。
          </div>}
          <div className="boss-actions">
            <button type="button" className="boss-btn boss-btn-primary" disabled={!b||busy}
              onClick={prepare}><ShieldCheck size={15}/> 保存当前会前材料</button>
            <button type="button" className="boss-btn" onClick={()=>onNavigate("F05")}>
              <ArrowLeft size={15}/> 进入会后纪要</button>
          </div>
        </Panel>
        </div>
        <div className="boss-tab-view" hidden={tab!=="议题"&&tab!=="材料缺口"}>
        <Panel title="议题资料与原始证据" note="只能引用本会议当前获准的来源">
          {(b?.sources||[]).map(source=><div key={source.source_id} className="boss-workspace-item">
            <div className="boss-workspace-item-top">
              <strong>{source.source_id}</strong>
              <span className={"boss-tag "+(source.status==="CURRENT"?"boss-tag-green":"boss-tag-amber")}>{source.status}</span>
            </div>
            <Fact label="来源版本" value={source.version}/>
            <Fact label="材料作者" value={source.author_contact_id}/>
            {source.excerpt?<p>{source.excerpt}</p>:
              <p>资料不可读或已撤销，保留条目与缺口；不生成替代内容。</p>}
            {source.status==="CURRENT"&&<div className="boss-actions">
              <button type="button" className="boss-btn" onClick={()=>onViewSource(source.source_id)}>
                <FileSearch size={15}/> 打开有效原文</button>
            </div>}
          </div>)}
          {!b?.sources.length&&<div className="boss-empty"><FolderOpen size={20}/>
            <div><strong>当前无获准会议资料</strong><p>不能将无来源的数字和建议标为 READY。</p></div>
          </div>}
        </Panel>
        </div>
        <div className="boss-tab-view" hidden={tab!=="历史承诺"}>
        <Panel title="历史承诺、事件与状态" note="不得将材料准备完成等同于会议已召开">
          <Fact label="当前事件" value={b?.event.event_id}/>
          <Fact label="事件状态" value={b?.event.status}/>
          {(b?.commitments||[]).map(item=><div className="boss-workspace-item" key={item.task_id}>
            <strong>{item.task_id}</strong>
            <Fact label="承诺状态" value={item.status}/>
            <Fact label="截止时间" value={textTime(item.due_at)}/>
            <Fact label="依据" value={item.is_historical?"经批准的历史业务快照":"当前 SQLite 交办"}/>
          </div>)}
          <div className="boss-actions">
            <button type="button" className="boss-btn" onClick={()=>onNavigate("F06")}>
              <ClipboardList size={15}/> 交办、延期和完成核查</button>
          </div>
        </Panel>
        </div>
        <div className="boss-tab-view" hidden={tab!=="议题"}>
        <Panel title="本人会议目标版本" note="N07 独立本人确认 · 仅在适用范围内进入当前会议准备">
          <Fact label="适用状态" value={b?.owner_goal_reference?.status||"待核对"}/>
          <Fact label="本人确认的目标版本" value={b?.owner_goal_reference?.active_version||"无适用版本"}/>
          <Fact label="适用范围" value={b?.owner_goal_reference?.scope||"尚未确认"}/>
          <Fact label="目标数量" value={b?.owner_goal_reference?.goal_count??0}/>
          <div className="boss-actions">
            <button type="button" className="boss-btn" onClick={()=>onNavigate("N07")}>核对 N07 本人目标</button>
          </div>
        </Panel>
        <Panel title="已关联会面议题与行程影响" note="F10 / F11 的实际 SQLite 版本，不自动改期或发邀请">
          {(b?.people_meeting_impacts||[]).map(item=><div className="boss-workspace-item"
            key={item.brief_id}>
            <strong>会面议题：{item.contact_id} · {item.brief_id}</strong>
            <small>材料 v{item.version} · 会议 v{item.meeting_version} · 来源 {item.source_state}</small>
            {(item.pinned_source_versions||[]).map(source=><small key={source.source_id}>
              资料 {source.source_id} v{source.version}
            </small>)}
          </div>)}
          {(b?.travel_impacts||[]).map(item=><div className="boss-workspace-item"
            key={item.travel_id}>
            <strong>行程影响：{item.travel_id}</strong>
            <small>行程 v{item.version} · {item.meeting_end_known?"已经提供会议结束时间":"会议结束时间尚未提供"}，准备时间须核查</small>
          </div>)}
          {!b?.people_meeting_impacts?.length&&!b?.travel_impacts?.length&&
            <p className="boss-helper">当前没有由 F10 关联的会面议题或 F11 已确认行程影响。</p>}
          <div className="boss-actions">
            <button type="button" className="boss-btn" onClick={()=>onNavigate("F10")}>
              查看人员会面</button>
            <button type="button" className="boss-btn" onClick={()=>onNavigate("F11")}>
              核查行程影响</button>
          </div>
        </Panel>
        <Panel title="当前可复算经营指标" note="同一已核验模拟数据集 · 原因缺少时不推测">
          {b?.metrics.available?
            b.metrics.values.map(period=><div className="boss-workspace-item" key={period.period_scope}>
              <strong>{period.period_scope} · {period.date_range.join(" — ")}</strong>
              <Fact label="收入" value={period.metrics.revenue.value+" CNY"}/>
              <Fact label="毛利" value={period.metrics.gross_profit.value+" CNY"}/>
              <Fact label="毛利率" value={period.metrics.gross_margin.value+"%"}/>
              <Fact label="销量" value={period.metrics.sales_quantity.value+" 吨"}/>
              <small>计算口径 v{period.definition_version} · 来源 {period.source_id} v{period.source_version}</small>
            </div>):
            <div className="boss-status boss-status-warn">
              <AlertCircle size={15}/> {b?.metrics.reason||"当前没有可用指标来源"}
            </div>}
          <p className="boss-helper">{b?.metrics.unexplained_causes.join("；")||"待实际来源核实"}</p>
        </Panel>
        </div>
        <div className="boss-tab-view" hidden={tab!=="待决定"}>
          <Panel title="当前需要本人决定的事项" note="只核对实际记录和已知资料关系">
            <Fact label="本人历史承诺" value={b?.commitments.length}/>
            <Fact label="关联事件" value={b?.event.event_id}/>
            <Fact label="当前是否已有明确会议决策" value="未提供确认依据"/>
            <div className="boss-status boss-status-warn">
              <AlertCircle size={16}/> 当前演示会议资料没有经过核查的申请关联或新决策记录。
              不能把建议、缺少依据的原因或草稿直接当作老板已决定事项。
            </div>
            <div className="boss-actions">
              <button type="button" className="boss-btn" onClick={()=>onNavigate("F07")}>
                查看独立审批记录
              </button>
              <button type="button" className="boss-btn" onClick={()=>onNavigate("F05")}>
                打开会后纪要分类
              </button>
            </div>
          </Panel>
        </div>
      </div>
      <div className="boss-column">
        <Panel title="资料完整度与准备期限">
          <Fact label="有效材料" value={b?.sources.filter(x=>x.status==="CURRENT").length}/>
          <Fact label="待补清单" value={b?.missing_items.length}/>
          <Fact label="当前需复核" value={data?.needs_review?"是":"否"}/>
          <Fact label="材料准备期限" value={b?.meeting.preparation_due_at?textTime(b.meeting.preparation_due_at):"尚未提供"}/>
          <Fact label="会议已举行" value={data?.meeting_occurred?"本人已经确认":"尚未确认"}/>
          <Fact label="资料请求已发送" value="否（仅草稿）"/>
          {(b?.missing_items||[]).map(x=><div className="boss-workspace-item" key={x}>{x}</div>)}
          <label className="boss-label" htmlFor="boss-brief-request-contact">资料请求联系人</label>
          <select id="boss-brief-request-contact" className="boss-single-input"
            value={selectedContact} onChange={e=>setSelectedContact(e.target.value)}>
            <option value="">请选择当前有权参会联系人</option>
            {(b?.participants||[]).filter(x=>x.status==="CURRENT").map(x=>
              <option key={x.contact_id} value={x.contact_id}>
                {x.name} · {x.organization} [{x.contact_id}]
              </option>)}
          </select>
          <div className="boss-actions">
            <button type="button" className="boss-btn" disabled={!b?.missing_items.length||busy}
              onClick={requestMaterials}><Send size={15}/> 准备资料请求草稿</button>
            <button type="button" className="boss-btn" onClick={()=>onNavigate("F08")}>
              打开消息编辑</button>
          </div>
          <div className="boss-status boss-status-warn">
            <Clock3 size={16}/> F04 保存资料请求只会生成 DRAFT。老板仍需在 F08 按当前收件人和内容重新确认模拟发送；真实外部渠道没有接入。
          </div>
        </Panel>
        <Panel title="来源变化与版本历史">
          <Fact label="已保存快照状态" value={saved?.state||"无"}/>
          <Fact label="准备时间" value={saved?.prepared_at?textTime(saved.prepared_at):null}/>
          <Fact label="原文版本变化" value={data?.source_changed?"是":"未观察到"}/>
          <Fact label="参会人状态变化" value={data?.participant_changed?"是":"未观察到"}/>
          <Fact label="关联交办/事件变化" value={data?.business_changed?"是":"未观察到"}/>
          {(data?.revisions||[]).map(r=><div key={r.version} className="boss-workspace-item">
            <strong>v{r.version} · {r.state}</strong><small>{textTime(r.prepared_at)}</small>
          </div>)}
          <div className="boss-actions">
            <button type="button" className="boss-btn" onClick={()=>onNavigate("N04")}>
              <ArrowLeft size={15}/> 返回会议资料</button>
          </div>
        </Panel>
      </div>
    </div>
    {pending&&<div className="boss-confirm-backdrop">
      <section className="boss-confirm" role="dialog" aria-modal="true" ref={modalRef}
        tabIndex={-1} aria-labelledby="boss-brief-confirm-title">
        <h3 id="boss-brief-confirm-title"><ShieldCheck size={18}/>{pending.title}</h3>
        <p>当前 SIMULATED 事务需要本人核查来源、对象与版本；不允许自动发送。</p>
        <dl>{pending.details.map((detail,i)=><div key={i}><dd>{detail}</dd></div>)}</dl>
        <label className="boss-confirm-check">
          <input type="checkbox" checked={approved} disabled={busy}
            onChange={e=>setApproved(e.target.checked)}/>
          <span>我已确认这次材料范围与操作后果。</span>
        </label>
        {error&&<p className="boss-validation-error" role="alert">{error}</p>}
        <footer className="boss-actions">
          <button type="button" className="boss-btn" disabled={busy||checking}
            onClick={()=>setPending(null)}>取消</button>
          <button type="button" className="boss-btn" disabled={busy||checking}
            onClick={()=>void reconcile()}>
            {checking&&<Loader2 size={15} className="boss-spin"/>} 查原请求回执</button>
          <button type="button" className="boss-btn boss-btn-primary"
            disabled={!approved||busy||checking} onClick={()=>void submit()}>
            {busy&&<Loader2 size={15} className="boss-spin"/>} 确认并保存
          </button>
        </footer>
      </section>
    </div>}
  </>;
}
