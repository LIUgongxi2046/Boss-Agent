import {useEffect,useRef,useState,type ReactNode} from "react";
import {AlertCircle,ArrowLeft,ClipboardList,FileSearch,Send,ShieldCheck} from "lucide-react";
import {useClient} from "@/providers/ClientProvider";
import {useTransaction} from "./BossAssignmentFlow";
import {BossMeetingArrangement,type MeetingArrangementProjection} from "./BossMeetingArrangement";
import {readLibraryContext} from "./library-context";

type Source={source_id:string;version:string|null;status:string;published_at?:string;valid_from?:string|null;valid_until?:string|null;author_contact_id?:string;excerpt:string|null};
type Commitment={task_id:string;status:string;due_at:string;is_historical:boolean;evidence_requirements:string[]};
type Participant={contact_id:string;name?:string;organization?:string;responsibility?:string;status:string};
type Evidence={source_id:string;version:string};
type Topic={id:string;title:string;content:string;source_refs:Evidence[]};
type Compiled={
  meeting:{meeting_id:string;version:string;starts_at:string;timezone:string;ends_at?:string|null;state?:string;preparation_due_at?:string|null};
  participants:Participant[];sources:Source[];commitments:Commitment[];event:{event_id:string;status:string;origin:string};
  metrics:{available:boolean;reason?:string;values:{period_scope:string;date_range:string[];source_id:string;source_version:string;definition_version:string;metrics:Record<string,{value:string|null;unit:string}>;detail_refs:string[]}[];unexplained_causes:string[]};
  travel_impacts?:{travel_id:string;version:string;meeting_end_known:boolean}[];
  owner_goal_reference?:{status:string;active_version:string|null;scope:string|null;goal_count?:number;topic_count?:number};
  people_meeting_impacts?:{brief_id:string;version:string;contact_id:string;meeting_version:string;source_state:string;pinned_source_versions:Evidence[]}[];
  topics?:Topic[];consensus?:Topic[];conflicts?:Topic[];pending_decisions?:{application_id:string;version:string;summary:string;state:string;source_refs:Evidence[]}[];
  missing_items:string[];needs_review:boolean;source_type:"SIMULATED";
};
type Saved={brief_id:string;meeting_id:string;version:string;state:string;prepared_at:string;reviewed_by_owner:false;meeting_occurred:boolean;message_sent:false;compiled:Compiled};
type Briefing={source_type:"SIMULATED";projection:"briefing";data_version:string;execution_namespace?:string;saved:boolean;saved_brief:Saved|null;current:Compiled;current_status:string;needs_review:boolean;source_changed?:boolean;participant_changed?:boolean;business_changed?:boolean;revisions:{version:string;state:string;prepared_at:string}[];meeting_occurred:boolean;material_request_sent:boolean};
type Props={onNavigate:(page:string)=>void;onViewSource:(id:string,anchor?:{version:string;start:number;end:number})=>void;onOpenTask:(id:string)=>void;onMessageDraftCreated:(id:string)=>void;refreshVersion?:number;arrangement:MeetingArrangementProjection|null;arrangementLoading:boolean;arrangementError:string;onReloadArrangement:()=>void;onDirtyChange:(dirty:boolean)=>void};
const TABS=["议题","历史承诺","待决定","材料缺口"] as const;
type Tab=typeof TABS[number];
const METRICS:Record<string,string>={revenue:"收入",gross_profit:"毛利",gross_margin:"毛利率",sales_quantity:"销量",operating_profit:"营业利润",net_profit:"净利润"};
function time(value?:string|null,timezone="Asia/Shanghai"){return value?new Intl.DateTimeFormat("zh-CN",{dateStyle:"medium",timeStyle:"short",timeZone:timezone}).format(new Date(value)):"尚未提供";}
function Panel({title,children}:{title:string;children:ReactNode}){return <section className="boss-panel"><div className="boss-panel-head"><h2>{title}</h2></div>{children}</section>;}
function Fact({label,value}:{label:string;value?:string|number|null}){return <div className="boss-kv"><span>{label}</span><strong>{value??"尚未提供"}</strong></div>;}
function sourceKey(value:Evidence){return JSON.stringify([value.source_id,value.version]);}
function initialTab():Tab{const value=window.history.state?.bossBriefTab;return TABS.includes(value)?value:"议题";}
export function BossMeetingBrief(props:Props){const {token}=useClient(),identity=useRef({token,version:0});if(identity.current.token!==token)identity.current={token,version:identity.current.version+1};return <MeetingBrief key={identity.current.version} {...props}/>;}
function MeetingBrief({onNavigate,onViewSource,onOpenTask,onMessageDraftCreated,refreshVersion,arrangement,arrangementLoading,arrangementError,onReloadArrangement,onDirtyChange}:Props){
  const {getToken}=useClient();
  const [data,setData]=useState<Briefing|null>(null),[revision,setRevision]=useState(0),[loading,setLoading]=useState(true),[error,setError]=useState("");
  const [selectedContact,setSelectedContact]=useState(""),[tab,setTab]=useState<Tab>(initialTab),[arrangementDirty,setArrangementDirty]=useState(false);
  const [gapPick,setGapPick]=useState<{key:string;ids:string[]}>({key:"",ids:[]}),[draftId,setDraftId]=useState("");
  const reload=()=>{setRevision(value=>value+1);onReloadArrangement();};
  const transaction=useTransaction(()=>{setSelectedContact("");reload();},undefined,id=>{setDraftId(id);onMessageDraftCreated(id);},"meetingBrief");
  useEffect(()=>{onDirtyChange(arrangementDirty||transaction.busy);return()=>onDirtyChange(false);},[arrangementDirty,transaction.busy,onDirtyChange]);
  useEffect(()=>{const restore=()=>setTab(initialTab());window.addEventListener("popstate",restore);return()=>window.removeEventListener("popstate",restore);},[]);
  useEffect(()=>{
    const controller=new AbortController(),token=getToken();setData(null);setLoading(true);setError("");
    if(!token){setLoading(false);setError("老板身份已过期，请重新认证");return;}
    void fetch("/api/boss/ui/workspace/briefing",{headers:{Authorization:"Bearer "+token},cache:"no-store",signal:controller.signal}).then(async response=>{
      if(response.status===401)window.dispatchEvent(new Event("boss-auth-expired"));
      if(!response.ok)throw new Error("会前材料读取失败（HTTP "+response.status+"）");
      const value=await response.json() as Briefing;if(value.projection!=="briefing"||value.source_type!=="SIMULATED")throw new Error("资料来源不符合当前获准范围");return value;
    }).then(value=>{if(controller.signal.aborted)return;setData(value);setLoading(false);const context=readLibraryContext();if(context?.kind==="meeting"&&(context.id!==value.current.meeting.meeting_id||context.version!==value.current.meeting.version)){setError("原会议不在当前目录或版本已经变化，请返回会议资料重新选择。");}}).catch(reason=>{if(controller.signal.aborted)return;setLoading(false);setError(reason instanceof Error?reason.message:String(reason));});
    return()=>controller.abort();
  },[revision,refreshVersion,getToken]);
  const current=!loading?data:null,b=current?.current,saved=current?.saved_brief;
  const arrangementCurrent=!arrangementLoading&&!arrangementError?arrangement:null;
  const versionMismatch=Boolean(b&&arrangementCurrent&&(b.meeting.meeting_id!==arrangementCurrent.meeting.meeting_id||b.meeting.version!==arrangementCurrent.meeting.version||current?.execution_namespace&&arrangementCurrent.execution_namespace&&current.execution_namespace!==arrangementCurrent.execution_namespace));
  const disabled=transaction.busy||arrangementDirty||!b||!arrangementCurrent||versionMismatch;
  const gapKey=(b?.missing_items??[]).join("|");
  const gaps=gapPick.key===gapKey?gapPick.ids:(b?.missing_items??[]);
  const reason=!b?"尚未读取当前会议的会前材料，请先确认当前会议。":!arrangementCurrent?"会议安排尚未读取"+(arrangementError?"："+arrangementError:"，请等待读取完成"):versionMismatch?"会议安排与会前材料采用的版本不同，请刷新会议材料后核查。":arrangementDirty?"会议安排存在未保存修改，请先保存或放弃本次修改。":transaction.busy?"正在核对并提交上一项操作。":"";
  const gapCount=b?(b.missing_items.length||!current?.needs_review?b.missing_items.length:"待整理"):"待整理";
  const counts:Record<Tab,string|number>={"议题":b?.topics?.length??"待整理","历史承诺":b?.commitments.length??"待整理","待决定":b?.pending_decisions?.length??"待整理","材料缺口":gapCount};
  function changeTab(value:Tab){setTab(value);window.history.replaceState({...window.history.state,bossBriefTab:value},"",window.location.href);}
  function toggleGap(value:string){setGapPick({key:gapKey,ids:gaps.includes(value)?gaps.filter(item=>item!==value):[...gaps,value]});}
  function prepare(){
    if(disabled||!current||!b)return;setError("");
    transaction.propose("boss.meeting.brief.prepare",{meeting_id:b.meeting.meeting_id,meeting_version:b.meeting.version,expected_version:saved?.version??"0"},"生成当前会前材料",["会议："+b.meeting.meeting_id+" · v"+b.meeting.version,"来源数量："+b.sources.length,"承诺记录："+b.commitments.length,"缺少资料："+(b.missing_items.join("；")||"当前未列出，完整覆盖仍需本人核查"),"保存当前材料版本供本人核查，会议举行及资料发送分别记录。"]);
  }
  function requestMaterials(){
    if(disabled||!b)return;setError("");
    if(!b.missing_items.length){setError("当前没有返回缺少资料，请核查会议范围");return;}
    if(!gaps.length){setError("请选择本次请求的缺少材料");return;}
    const person=b.participants.find(value=>value.contact_id===selectedContact&&value.status==="CURRENT");if(!person){setError("请选择当前有效的资料请求联系人");return;}
    const body="关于会议 "+b.meeting.meeting_id+"（版本 "+b.meeting.version+"），请补充以下待核查资料："+gaps.join("；")+"。请说明有效来源版本和预计提供时间。";
    if(body.length>2400){setError("资料请求超过2400字，请调整本次资料范围");return;}
    transaction.propose("boss.message.draft.save",{draft_id:null,expected_version:"0",recipient_id:person.contact_id,related_task_id:null,body,attachment_refs:[],visibility:"RECIPIENT_ONLY"},"准备会前资料请求草稿",["收件人："+(person.name??person.contact_id)+" · "+(person.organization??"组织待核查"),"联系人编号："+person.contact_id,"缺少材料："+gaps.join("；"),"请求内容："+body,"保存为消息草稿，发送需要本人在消息页面另行审核。"]);
  }
  function sourceReason(row:Source){if(row.status!=="CURRENT")return "来源已经需要复核，原文不作为当前依据";if(!row.version)return "当前来源版本未知";if(!row.excerpt)return "当前原文不可采用";return "";}
  function evidenceReason(ref:Evidence){
    const row=b?.sources.find(value=>value.source_id===ref.source_id&&value.version===ref.version);
    if(!row)return "当前材料未返回该来源版本";
    return sourceReason(row);
  }
  function openEvidence(ref:Evidence){
    const row=b?.sources.find(value=>value.source_id===ref.source_id&&value.version===ref.version);
    if(!row||sourceReason(row))return;
    if(!row.version||!row.excerpt)return;
    onViewSource(row.source_id,{version:row.version,start:0,end:Array.from(row.excerpt).length});
  }
  function evidenceActions(refs:Evidence[]){
    const rows=refs.map(ref=>({ref,reason:evidenceReason(ref)}));
    return <div className="boss-actions">{rows.map(row=><button key={sourceKey(row.ref)} type="button" className="boss-btn" disabled={Boolean(row.reason)} onClick={()=>openEvidence(row.ref)}><FileSearch size={15}/>查看原文：{row.ref.source_id} · v{row.ref.version}</button>)}{rows.some(row=>row.reason)&&<p className="boss-helper">{rows.filter(row=>row.reason).map(row=>row.ref.source_id+" v"+row.ref.version+"："+row.reason).join("；")}</p>}</div>;
  }
  function topics(title:string,rows:Topic[]|undefined){return <section className="boss-brief-section"><h3>{title}</h3>{rows?.map(row=><article className="boss-workspace-item" key={row.id}><strong>{row.title}</strong><p>{row.content}</p>{evidenceActions(row.source_refs)}</article>)}{!rows?.length&&<p className="boss-helper">{rows?"当前材料未返回相关记录。":"当前服务尚未提供该类材料。"}</p>}</section>;}
  const draftNote=!b?"尚未读取当前会议材料":!b.missing_items.length?"当前会议没有返回缺少资料，起草入口保持不可用。":!gaps.length?"请选择至少一项缺少材料。":!selectedContact?"请选择当前有效的资料请求联系人。":disabled?reason||"当前无法保存新的消息草稿。":"选择收件人和缺少项后保存为消息草稿；发送在消息编辑中由本人另行确认。";
  return <div className="boss-brief-view">
    <div className="boss-workspace-toolbar"><button className="boss-btn" type="button" onClick={()=>onNavigate("N04")}><ArrowLeft size={15}/>返回会议与资料</button><span className="boss-tag boss-tag-amber">SIMULATED</span></div>
    {error&&<div role="alert" className="boss-status boss-status-error"><AlertCircle size={16}/>{error}</div>}{transaction.notice&&<div role="status" className="boss-status boss-status-ok">{transaction.notice}</div>}{versionMismatch&&<div role="alert" className="boss-status boss-status-warn">会议安排与材料采用的版本不同，请重新读取后核查。</div>}
    <div className="boss-brief-filters"><div className="boss-kv"><span>会议对象</span><strong>{b?.meeting.meeting_id??"尚未读取"}</strong></div><div className="boss-kv"><span>日期时间</span><strong>{time(b?.meeting.starts_at,b?.meeting.timezone)}</strong></div><div className="boss-kv"><span>IANA时区</span><strong>{b?.meeting.timezone??"尚未提供"}</strong></div><div className="boss-kv"><span>参会联系人</span><strong>{b?.participants.map(value=>value.name??value.contact_id).join("、")||"尚未提供"}</strong></div></div>
    <div className="boss-brief-columns"><main className="boss-column"><Panel title="内容与配置">
      <nav className="boss-minutes-tabs" aria-label="会前材料分类">{TABS.map(value=><button key={value} type="button" className={tab===value?"selected":""} aria-current={tab===value?"page":undefined} onClick={()=>changeTab(value)}>{value}<span>{counts[value]}</span></button>)}</nav>
      {loading&&<p role="status" className="boss-helper">正在读取会议材料与当前状态…</p>}
      {tab==="议题"&&<>
        {topics("议题资料",b?.topics)}{topics("已确认共识",b?.consensus)}{topics("冲突与待核查依据",b?.conflicts)}
        <section className="boss-brief-section"><h3>参会联系人</h3>{b?.participants.map(person=><article className="boss-workspace-item" key={person.contact_id}><strong>{person.name??"身份待核查"} · {person.organization??"组织尚未提供"}</strong><p>{person.contact_id} · {person.responsibility??"职责尚未提供"} · {person.status}</p></article>)}{b&&!b.participants.length&&<p className="boss-helper">当前材料没有返回参会联系人。</p>}
          <h4>会议关联会面材料</h4>
          {b?.people_meeting_impacts?.map(value=><article className="boss-workspace-item" key={value.brief_id}><strong>{value.contact_id} · {value.brief_id}</strong><p>会面材料v{value.version} · 会议v{value.meeting_version} · {value.source_state}</p>{evidenceActions(value.pinned_source_versions)}</article>)}
          {b&&!b.people_meeting_impacts?.length&&<p className="boss-helper">当前会议没有返回会面材料；可从人员会面按本会议参会人建立会面材料。</p>}
          <div className="boss-actions"><button type="button" className="boss-btn" onClick={()=>onNavigate("F10")}>查看人员会面</button></div></section>
        <section className="boss-brief-section"><h3>当前经营指标</h3>{b?.metrics.available?b.metrics.values.map(period=><article className="boss-workspace-item" key={period.period_scope}><strong>{period.period_scope} · {period.date_range.join(" — ")}</strong>{Object.entries(period.metrics).map(([key,value])=><Fact key={key} label={METRICS[key]??key} value={value.value===null?null:value.value+" "+value.unit}/>)}<p className="boss-helper">计算口径v{period.definition_version} · 来源{period.source_id} v{period.source_version}</p>{evidenceActions([{source_id:period.source_id,version:period.source_version}])}</article>):<p className="boss-helper">{b?.metrics.reason??"经营指标尚未提供。"}</p>}{b?.metrics.unexplained_causes.map(value=><p key={value} className="boss-helper">{value}</p>)}</section>
        <section className="boss-brief-section"><h3>议题原文资料</h3>{b?.sources.map(value=><article className="boss-workspace-item" key={value.source_id}><strong>{value.source_id} · {value.status}</strong><p className="boss-helper">版本 {value.version??"版本未知"} · 作者 {value.author_contact_id??"尚未提供"} · 发布 {time(value.published_at)} · 有效 {value.valid_from??"尚未提供"} 至 {value.valid_until??"尚未提供"}</p>{value.excerpt?<p className="boss-brief-excerpt">{value.excerpt}</p>:<p className="boss-helper">当前原文不可采用，资料条目继续保留。</p>}<div className="boss-actions"><button type="button" className="boss-btn" disabled={Boolean(sourceReason(value))} onClick={()=>{if(value.version)openEvidence({source_id:value.source_id,version:value.version});}}><FileSearch size={15}/>查看原文</button></div>{sourceReason(value)&&<p className="boss-helper">{sourceReason(value)}</p>}</article>)}{b&&!b.sources.length&&<p className="boss-helper">当前没有获准会议资料。</p>}</section>
      </>}
      {tab==="历史承诺"&&<section className="boss-brief-section"><h3>历史承诺与当前交办</h3>{b?.commitments.map(value=><article className="boss-workspace-item" key={value.task_id}><strong>{value.task_id}</strong><Fact label="状态" value={value.status}/><Fact label="期限" value={time(value.due_at,b?.meeting.timezone)}/><Fact label="记录范围" value={value.is_historical?"历史业务记录":"当前交办"}/><p className="boss-helper">证据要求：{value.evidence_requirements.join("、")||"尚未提供"}</p><div className="boss-actions"><button type="button" className="boss-btn" disabled={value.is_historical} onClick={()=>onOpenTask(value.task_id)}>查看关联交办</button></div>{value.is_historical&&<p className="boss-helper">历史原事项入口尚未提供。</p>}</article>)}{b&&!b.commitments.length&&<p className="boss-helper">当前材料没有返回承诺记录。</p>}<div className="boss-actions">{b&&!b.commitments.some(value=>!value.is_historical)&&<button type="button" className="boss-btn" onClick={()=>onOpenTask("")}><ClipboardList size={15}/>准备交办</button>}<button type="button" className="boss-btn" onClick={()=>onNavigate("N05")}>在任务与承诺中查看</button></div><p className="boss-helper">{b&&!b.commitments.some(value=>!value.is_historical)?"当前会议没有关联的当前交办，可准备新的交办并在交办详情中核对负责人、期限和证据要求。":"当前交办逐项显示关联任务；历史记录只保留原事项说明。"}</p></section>}
      {tab==="待决定"&&<section className="boss-brief-section"><h3>需要本人决定的事项</h3>{b?.pending_decisions?.map(value=><article className="boss-workspace-item" key={value.application_id}><strong>{value.summary}</strong><Fact label="申请编号" value={value.application_id}/><Fact label="申请版本" value={value.version}/><Fact label="状态" value={value.state}/>{evidenceActions(value.source_refs)}</article>)}{!b?.pending_decisions?.length&&<p className="boss-helper">{b?.pending_decisions?"当前材料没有待决定记录。":"会议关联的待决定事项尚未提供。"}</p>}<div className="boss-actions"><button type="button" className="boss-btn" onClick={()=>onNavigate("F07")}>查看申请审阅</button><button type="button" className="boss-btn" onClick={()=>onNavigate("F05")}>查看纪要分类</button></div></section>}
      {tab==="材料缺口"&&<section className="boss-brief-section"><h3>缺少资料与准备期限</h3><Fact label="准备期限" value={time(b?.meeting.preparation_due_at,b?.meeting.timezone)}/>
        <h4>缺少材料</h4>
        {b?.missing_items.map(value=><label className="boss-confirm-check" key={value}><input type="checkbox" checked={gaps.includes(value)} onChange={()=>toggleGap(value)}/>{value}</label>)}
        {b&&!b.missing_items.length&&<p className="boss-helper">当前未列出缺少资料，完整覆盖仍需本人核查。</p>}
        <h4>起草补材料消息</h4>
        <label className="boss-label" htmlFor="boss-brief-recipient">资料请求收件人</label>
        <select id="boss-brief-recipient" className="boss-single-input" disabled={disabled||!b?.participants.some(value=>value.status==="CURRENT")} value={selectedContact} onChange={event=>setSelectedContact(event.target.value)}><option value="">请选择获准参会联系人</option>{b?.participants.filter(value=>value.status==="CURRENT").map(value=><option key={value.contact_id} value={value.contact_id}>{value.name??value.contact_id} · {value.organization??"组织待核查"}</option>)}</select>
        {b&&!b.participants.some(value=>value.status==="CURRENT")&&<p className="boss-helper">当前没有状态有效的参会联系人，不能选择收件人起草补材料消息。</p>}
        <div className="boss-actions"><button type="button" className="boss-btn" disabled={disabled||!b?.missing_items.length||!gaps.length||!selectedContact} onClick={requestMaterials}><Send size={15}/>起草补材料消息</button>{draftId&&<button type="button" className="boss-btn" onClick={()=>onNavigate("F08")}><FileSearch size={15}/>打开草稿</button>}</div>
        <p className="boss-helper">{draftNote}</p>{draftId&&<p className="boss-helper">已保存草稿编号：{draftId}</p>}
      </section>}
      <BossMeetingArrangement data={arrangement} loading={arrangementLoading} error={arrangementError} onReload={onReloadArrangement} onDirtyChange={setArrangementDirty} otherBusy={transaction.busy}/>
    </Panel><Panel title="关联内容与处理边界">
      <section className="boss-brief-section"><h3>本人目标</h3><Fact label="本人目标采用状态" value={b?.owner_goal_reference?.status}/><Fact label="本人确认的目标版本" value={b?.owner_goal_reference?.active_version}/><Fact label="目标适用范围" value={b?.owner_goal_reference?.scope}/><Fact label="目标数量" value={b?.owner_goal_reference?.goal_count}/><div className="boss-actions"><button type="button" className="boss-btn" onClick={()=>onNavigate("N07")}>核查本人目标</button></div>{!b?.owner_goal_reference?.status&&<p className="boss-helper">当前未返回本人目标采用状态；可从本人目标核查并建立本次会议适用目标。</p>}</section>
      <section className="boss-brief-section"><h3>关联事件</h3><Fact label="关联事件" value={b?.event.event_id}/><Fact label="事件状态" value={b?.event.status}/><Fact label="事件来源" value={b?.event.origin}/></section>
      <section className="boss-brief-section"><h3>时间冲突与行程</h3>{b?.travel_impacts?.map(value=><article className="boss-workspace-item" key={value.travel_id}><strong>行程{value.travel_id} · v{value.version}</strong><p>{value.meeting_end_known?"会议结束时间已提供":"会议结束时间需要补充"}</p></article>)}{b&&!b.travel_impacts?.length&&<p className="boss-helper">当前会议没有返回关联行程；可从行程安排建立与本次会议时间关联的行程。</p>}<div className="boss-actions"><button type="button" className="boss-btn" onClick={()=>onNavigate("F11")}>核查行程影响</button></div></section>
      <p className="boss-helper">材料准备、本人决定和会议举行分别记录。资料请求保存为草稿，发送需要本人单独确认。</p>
    </Panel></main><aside className="boss-column"><Panel title="来源与版本记录">
      <details><summary>材料版本记录（{current?.revisions.length??"未知"}）</summary>{current?.revisions.map(value=><article className="boss-workspace-item" key={value.version}><strong>v{value.version} · {value.state}</strong><p>{time(value.prepared_at)}</p></article>)}{current&&!current.revisions.length&&<p className="boss-helper">尚无历史材料版本。</p>}</details>
      <p className="boss-helper">每项材料的版本、作者和有效期显示在议题原文资料中，点击“查看原文”直接打开该项版本。</p>
    </Panel><Panel title="状态与核查">
      <Fact label="当前会议版本" value={b?.meeting.version}/><Fact label="会议状态" value={b?.meeting.state}/><Fact label="已保存材料版本" value={saved?.version}/><Fact label="已保存材料状态" value={saved?.state}/><Fact label="当前资料状态" value={current?.current_status}/><Fact label="准备期限" value={time(b?.meeting.preparation_due_at,b?.meeting.timezone)}/><Fact label="有效材料" value={b?.sources.filter(value=>value.status==="CURRENT").length}/><Fact label="待补项目" value={b?.missing_items.length}/><Fact label="会议已举行" value={current?current.meeting_occurred?"本人已经确认":"尚未确认":null}/><Fact label="来源版本变化" value={current?.source_changed===undefined?null:current.source_changed?"需要复核":"未观察到"}/><Fact label="参会人变化" value={current?.participant_changed===undefined?null:current.participant_changed?"需要复核":"未观察到"}/><Fact label="关联业务变化" value={current?.business_changed===undefined?null:current.business_changed?"需要复核":"未观察到"}/>{current?.needs_review&&<p className="boss-status boss-status-warn">当前材料需要复核，旧版本继续按原依据保留。</p>}
      {transaction.recovery}
    </Panel></aside></div>
    <footer className="boss-brief-footer boss-actions"><button type="button" className="boss-btn boss-btn-primary" disabled={disabled} onClick={prepare}><ShieldCheck size={15}/>让大鹏准备会前材料</button>{disabled&&reason&&<p className="boss-helper">{reason}</p>}</footer>
    {transaction.dialog}
  </div>;
}
