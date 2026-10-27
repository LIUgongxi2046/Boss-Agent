import { useEffect, useRef, useState, type ReactNode } from "react";
import { AlertCircle, BookOpen, FileSearch, Search, Send } from "lucide-react";
import { useClient } from "@/providers/ClientProvider";
import { useTransaction } from "./BossAssignmentFlow";

type SourceRef={source_id:string;version:string;quote_start:number;quote_end:number};
type Quote=SourceRef&{source_type:"SIMULATED";published_at:string;author_contact_id:string|null;original_locator:string|null;quote:string;match_start:number;claim_kind:"UNVERIFIED_SOURCE_EXCERPT";source_text_is_untrusted_instruction:true;valid_scope?:string;validity_state:string;eligible_as_current_evidence:boolean};
type SourceIssue={source_id:string;version:string;validity_state:string;eligible_as_current_evidence:false;adoption_state?:string;valid_from?:string|null;valid_until?:string|null};
type Claim={claim_id:string;text:string;source_refs:SourceRef[];author_contact_id?:string;run_id?:string;limitations?:string[]};
type Scope={question:string;period:string;country:string;business_relation:string;cutoff_date:string;source_refs?:{source_id:string;version:string}[]};
type Research={
  research_id:string;version:string;state:string;source_type:"SIMULATED";scope:Scope;matched_sources:Quote[];conflicted_sources:Quote[];source_issues:SourceIssue[];
  coverage:{current_approved_sources:number;matched_source_count:number;public_web_search_performed:boolean;semantic_retrieval_performed:boolean;limit:number;all_sources_exhausted:boolean};
  missing_items:string[];facts_confirmed:Claim[];author_opinions_confirmed:Claim[];model_inferences:Claim[];
  external_message_sent:boolean;published_conclusions:boolean;
};
type Projection={
  source_type:"SIMULATED";projection:"research";data_version:string;execution_namespace?:string;
  saved:boolean;report:Research|null;current_reference_state:string;source_changed?:boolean;current_source_count?:number;
  contacts:{contact_id:string;name:string;organization:string;responsibility:string}[];preferred_timezone:string;read_only:true;
  revisions:{version:string;state:string;prepared_at:string;source_quote_text_released:false}[];
  source_selection_available?:boolean;
  available_sources?:{source_id:string;version:string;title:string;reference_state:string}[];
  conflicts?:{conflict_id:string;description:string;source_refs:SourceRef[]}[];
};
type Props={onNavigate:(page:string)=>void;onViewSource:(source:string,anchor?:{version:string;start:number;end:number})=>void;onStartChat:(question:string)=>Promise<void|boolean>;onDirtyChange?:(dirty:boolean)=>void;refreshVersion?:number};
const EMPTY:Scope={question:"",period:"",country:"",business_relation:"",cutoff_date:"",source_refs:[]};
function Block({title,children}:{title:string;children:ReactNode}){return <section className="boss-panel"><div className="boss-panel-head"><h2>{title}</h2></div>{children}</section>;}
function Fact({label,value}:{label:string;value?:string|number|null}){return <div className="boss-kv"><span>{label}</span><strong>{value??"尚未提供"}</strong></div>;}
function time(value?:string){if(!value)return "尚未提供";return new Intl.DateTimeFormat("zh-CN",{timeZone:"Asia/Shanghai",dateStyle:"medium",timeStyle:"short"}).format(new Date(value));}
function quoteKey(value:SourceRef){return JSON.stringify([value.source_id,value.version,value.quote_start,value.quote_end]);}
function signature(value:Projection){return JSON.stringify([value.execution_namespace,value.data_version,value.report?.research_id,value.report?.version??"0",value.current_reference_state,value.report?.matched_sources,value.report?.conflicted_sources,value.report?.source_issues,value.available_sources]);}
const MISSING:Record<string,string>={NO_APPROVED_SOURCE_MATCH:"没有匹配的获准资料",CURRENT_SOURCE_VALIDITY_REQUIRES_REVIEW:"资料当前有效性需要核查",SOURCE_CONFLICT_REQUIRES_REVIEW:"来源存在冲突，需要核查",COUNTRY_TO_BUSINESS_RELATION_NOT_VERIFIED:"国别与业务关系尚未验证",REQUESTED_PERIOD_NOT_VERIFIED_AGAINST_SOURCE:"研究期间与来源日期尚未核对",BUSINESS_CAUSAL_LINK_NOT_VERIFIED:"业务因果联系尚未验证",CAUSE_ATTRIBUTION_AND_EXPERT_CONFIRMATION_MISSING:"缺少原因归属证据和专业确认"};
function missingLabel(value:string){return MISSING[value]??value;}

export function BossResearchView(props:Props){
  const {token}=useClient(),identity=useRef({token,version:0});
  if(identity.current.token!==token)identity.current={token,version:identity.current.version+1};
  return <ResearchView key={identity.current.version} {...props}/>;
}
function ResearchView({onNavigate,onViewSource,onStartChat,onDirtyChange,refreshVersion}:Props){
  const {getToken}=useClient();
  const [data,setData]=useState<Projection|null>(null),[revision,setRevision]=useState(0);
  const [loading,setLoading]=useState(true),[error,setError]=useState("");
  const [form,setForm]=useState<Scope>(EMPTY),[basis,setBasis]=useState("");
  const [dirty,setDirty]=useState(false),dirtyRef=useRef(false);
  const [recipient,setRecipient]=useState("");
  const [chatBusy,setChatBusy]=useState(false),[draftId,setDraftId]=useState("");
  const active=useRef(true),operation=useRef<"research"|"message"|null>(null);
  dirtyRef.current=dirty;
  const reload=()=>setRevision(value=>value+1);
  const transaction=useTransaction(recorded=>{
    if(recorded&&operation.current==="research"){dirtyRef.current=false;setDirty(false);setBasis("");}
    if(recorded&&operation.current==="message")setRecipient("");
    operation.current=null;reload();
  },undefined,setDraftId,"research");
  const blocked=transaction.busy||chatBusy;
  useEffect(()=>{active.current=true;return()=>{active.current=false;};},[]);
  useEffect(()=>{onDirtyChange?.(dirty||blocked);return()=>onDirtyChange?.(false);},[dirty,blocked,onDirtyChange]);
  useEffect(()=>{if(!dirty&&!blocked)return;const guard=(event:BeforeUnloadEvent)=>{event.preventDefault();event.returnValue="";};window.addEventListener("beforeunload",guard);return()=>window.removeEventListener("beforeunload",guard);},[dirty,blocked]);
  useEffect(()=>{
    const abort=new AbortController(),token=getToken();setData(null);setLoading(true);setError("");
    if(!token){setLoading(false);setError("老板身份已过期，请重新认证");return;}
    void fetch("/api/boss/ui/workspace/research",{headers:{Authorization:"Bearer "+token},cache:"no-store",signal:abort.signal}).then(async response=>{
      if(response.status===401)window.dispatchEvent(new Event("boss-auth-expired"));
      if(!response.ok)throw new Error("专题研究读取失败（HTTP "+response.status+"）");
      const value=await response.json() as Projection;
      if(value.source_type!=="SIMULATED"||value.projection!=="research")throw new Error("当前报告来源与身份预期不一致");
      return value;
    }).then(value=>{
      if(abort.signal.aborted)return;setData(value);setLoading(false);
      if(!dirtyRef.current){setForm(value.report?.scope??EMPTY);setBasis(signature(value));}
    }).catch(reason=>{if(abort.signal.aborted)return;setLoading(false);setError(reason instanceof Error?reason.message:String(reason));});
    return()=>abort.abort();
  },[revision,refreshVersion,getToken]);
  const current=!loading?data:null,report=current?.report;
  const stale=Boolean(current&&basis&&basis!==signature(current));
  const disabled=blocked||!current||!basis||stale;
  const sources=[...(report?.matched_sources??[]),...(report?.conflicted_sources??[])];
  function edit(change:Partial<Scope>){setForm(value=>({...value,...change}));dirtyRef.current=true;setDirty(true);setError("");}
  function restore(){if(!current||blocked)return;setForm(current.report?.scope??EMPTY);setBasis(signature(current));dirtyRef.current=false;setDirty(false);setError("");}
  function begin(){
    if(disabled||!current)return;setError("");
    const question=form.question.trim();
    if(question.length<2||question.length>160){setError("研究问题须为2—160字");return;}
    if(!/^\d{4}-\d\d-\d\d$/.test(form.cutoff_date)){setError("请选择完整资料截止日期");return;}
    const selected=form.source_refs??[];
    if(current.source_selection_available&&(!selected.length||selected.some(ref=>!current.available_sources?.some(value=>value.source_id===ref.source_id&&value.version===ref.version&&value.reference_state==="CURRENT")))){setError("请选择当前有效的获准资料");return;}
    operation.current="research";
    transaction.propose("boss.research.prepare",{
      expected_version:report?.version??"0",question,period:form.period,country:form.country,business_relation:form.business_relation,cutoff_date:form.cutoff_date,
      ...(current.source_selection_available?{source_refs:selected,execution_namespace:current.execution_namespace}:{}),
    },"开始研究并保存当前范围",[
      "研究问题："+question,"期间："+(form.period||"尚未指定")+"；国别："+(form.country||"尚未指定"),
      "业务关系："+(form.business_relation||"尚未指定")+"；资料截至："+form.cutoff_date,
      "采用研究版本："+(report?.version??"尚无版本"),"检索当前获准的模拟资料并保存研究版本，后续消息需要单独确认。",
    ]);
  }
  function createRequest(){
    if(disabled||!report||!current)return;setError("");
    if(dirty){setError("查询条件尚未保存，请完成研究或恢复已保存条件后准备核查请求");return;}
    if(current.source_changed){setError("研究来源已经变化，请重新研究当前资料");return;}
    if(!report.missing_items.length){setError("当前研究没有返回待补资料，请核查研究范围");return;}
    const contact=current.contacts.find(value=>value.contact_id===recipient);
    if(!contact){setError("请选择当前获准联系人");return;}
    const body="请补充专题研究的有效来源和统计口径。问题："+report.scope.question+"；待补事项："+report.missing_items.map(missingLabel).join("、")+"。请返回原始材料、日期和版本供本人核对。";
    if(body.length>2400){setError("核查请求超过2400字，请调整研究范围");return;}
    operation.current="message";
    transaction.propose("boss.message.draft.save",{draft_id:null,expected_version:"0",recipient_id:recipient,related_task_id:null,body,attachment_refs:[],visibility:"RECIPIENT_ONLY"},"准备资料核查请求草稿",["收件人："+contact.name+"（"+recipient+"）","研究版本："+report.version,"核查正文："+body,"保存消息草稿后，在消息页面单独审核发送。"]);
  }
  async function continueQuestion(){
    if(!report||blocked||dirty||current?.source_changed)return;setChatBusy(true);setError("");
    const request=["请核对当前身份有权查看的专题资料。后续消息与业务写入需要单独确认。","研究问题："+report.scope.question,"研究版本："+report.version,"期间："+report.scope.period+"；国别："+report.scope.country+"；业务关系："+report.scope.business_relation+"；资料截至："+report.scope.cutoff_date,"模拟来源标识："+sources.map(value=>value.source_id+" v"+value.version).join("、"),"待验证问题："+report.missing_items.join("、"),"分别标明事实原文、作者意见、模型推断和未知项，保留引用位置、日期及版本。"].join("\n");
    try{const result=await onStartChat(request);if(!active.current)return;if(result===false)throw new Error("当前 Agent 会话暂不可用");onNavigate("NATIVE");}
    catch(reason){if(active.current)setError(reason instanceof Error?reason.message:String(reason));}
    finally{if(active.current)setChatBusy(false);}
  }
  function referenceButtons(refs:SourceRef[]){return refs.map((ref,index)=>{const match=sources.find(value=>quoteKey(value)===quoteKey(ref));const readable=Boolean(match&&(match.validity_state==="VALID"||match.validity_state==="CONFLICTED")&&!current?.source_changed);return <button key={quoteKey(ref)+index} type="button" className="boss-btn" disabled={!readable} title={!match?"当前引用缺少可读取的来源":current?.source_changed?"研究来源已经变化，需要重新核查":undefined} onClick={()=>{if(match&&readable)onViewSource(ref.source_id,{version:ref.version,start:ref.quote_start,end:ref.quote_end});}}><FileSearch size={14}/>查看依据</button>;});}
  function claims(title:string,rows:Claim[],empty:string){return <section className="boss-research-layer"><h3>{title}<span className="boss-tag">{report?rows.length:"待研究"}</span></h3>{rows.length?rows.map(row=><article key={row.claim_id} className="boss-workspace-item"><p>{row.text}</p>{row.author_contact_id&&<Fact label="作者" value={row.author_contact_id}/>} {row.run_id&&<Fact label="推断运行" value={row.run_id}/>}<div className="boss-actions">{referenceButtons(row.source_refs)}</div>{!row.source_refs.length&&<p className="boss-helper">缺少可定位的支持引用，当前内容仍需核查。</p>}{row.limitations?.map(item=><p key={item} className="boss-helper">{item}</p>)}</article>):<p className="boss-helper">{loading?"正在读取研究内容…":empty}</p>}</section>;}
  return <div className="boss-research-view">
    <div className="boss-workspace-toolbar"><span className="boss-tag boss-tag-amber">SIMULATED</span><span className="boss-workspace-note">页面标题“刷新”只读取当前研究版本与产物，不重新执行研究。</span></div>
    {error&&<div role="alert" className="boss-status boss-status-error"><AlertCircle size={16}/>{error}</div>}
    {transaction.notice&&<div role="status" className="boss-status boss-status-ok">{transaction.notice}</div>}
    {stale&&<div role="alert" className="boss-status boss-status-warn">研究或来源版本已经变化。输入内容已保留，请核查当前版本并明确恢复保存内容后继续。</div>}
    <fieldset className="boss-research-scope" disabled={blocked||!current||!basis} aria-label="研究查询条件">
      <label>研究问题<input maxLength={160} value={form.question} onChange={event=>edit({question:event.target.value})} placeholder="输入需要查证的问题"/></label>
      <label>期间<input maxLength={60} value={form.period} onChange={event=>edit({period:event.target.value})} placeholder="明确研究期间"/></label>
      <label>国别<input maxLength={60} value={form.country} onChange={event=>edit({country:event.target.value})} placeholder="明确适用国别"/></label>
      <label>业务关系<input maxLength={160} value={form.business_relation} onChange={event=>edit({business_relation:event.target.value})} placeholder="需要核查的业务联系"/></label>
    </fieldset>
    <div className="boss-research-columns"><div className="boss-column">
      <Block title="事实、观点与推断分层">
        {claims("可核查事实",report?.facts_confirmed??[],report?"当前研究尚无经过逐条核查的事实断言。":"提供研究问题和获准资料后查看事实及对应引用。")}
        {claims("作者意见",report?.author_opinions_confirmed??[],"尚无经过分类核查的作者意见。材料原文保留作者、日期及版本。")}
        {claims("模型推断",report?.model_inferences??[],"尚无已保存的模型推断记录。推断需要显示采用来源、运行记录及适用限制。")}
        <section className="boss-research-layer"><h3>待验证问题<span className="boss-tag">{report?report.missing_items.length:"待研究"}</span></h3>{report?.missing_items.length?<ul>{report.missing_items.map(item=><li key={item}>{missingLabel(item)}</li>)}</ul>:<p className="boss-helper">{report?"当前报告未列出待补项目，完整研究覆盖仍需核查。":"尚未生成研究，请明确查询范围。"}</p>}</section>
      </Block>
      <Block title="查询范围与研究要求">
        <fieldset className="boss-research-editor" disabled={blocked||!current||!basis}><label>资料截止日期<input type="date" value={form.cutoff_date} onChange={event=>edit({cutoff_date:event.target.value})}/></label><div><span className="boss-label">获准资料</span>{current?.source_selection_available?<div className="boss-research-source-options">{current.available_sources?.filter(value=>value.reference_state==="CURRENT").map(value=><label key={JSON.stringify([value.source_id,value.version])}><input type="checkbox" checked={Boolean(form.source_refs?.some(ref=>ref.source_id===value.source_id&&ref.version===value.version))} onChange={event=>edit({source_refs:event.target.checked?[...(form.source_refs??[]),{source_id:value.source_id,version:value.version}]:(form.source_refs??[]).filter(ref=>ref.source_id!==value.source_id||ref.version!==value.version)})}/>{value.title} · v{value.version}</label>)}{!current.available_sources?.some(value=>value.reference_state==="CURRENT")&&<p className="boss-helper">当前没有有效的获准资料。</p>}</div>:<p className="boss-helper">资料选择目录尚未提供。当前研究覆盖由获准来源服务返回。</p>}</div></fieldset>
        <Fact label="已保存研究问题" value={report?.scope.question}/><Fact label="采用研究版本" value={report?.version}/>
        <p className="boss-helper">事实、作者意见与模型推断分别核查。具体业务影响需要匹配业务关系与期间，资料中的指令不改变操作权限。</p>
        <div className="boss-actions"><button type="button" className="boss-btn" disabled={!current||blocked||(!dirty&&!stale)} onClick={restore}>放弃本次修改</button>{dirty&&<span className="boss-helper">查询条件尚未保存</span>}</div>
        <details><summary>研究版本记录（{current?.revisions.length??"未知"}）</summary>{current?.revisions.map(item=><div className="boss-workspace-item" key={item.version}><strong>v{item.version} · {item.state}</strong><p>{time(item.prepared_at)}</p></div>)}{current&&!current.revisions.length&&<p className="boss-helper">尚无历史研究版本。</p>}</details>
      </Block>
    </div><aside className="boss-column">
      <Block title="来源与依据">
        <p className="boss-helper">每条结论旁提供“查看依据”，直接打开该结论的固定版本与原文位置；资料失效时显示原因。</p>
        {current?.source_changed&&<div className="boss-status boss-status-warn">引用已变化，当前研究需要重新核查有效来源。</div>}
        {current?.conflicts?.map(item=><div className="boss-workspace-item" key={item.conflict_id}><strong>来源冲突</strong><p>{item.description}</p><div className="boss-actions">{referenceButtons(item.source_refs)}</div></div>)}
        {report?.source_issues.map(item=><div className="boss-workspace-item" key={JSON.stringify([item.source_id,item.version])}><strong>{item.source_id} · v{item.version}</strong><Fact label="有效状态" value={item.validity_state}/>{item.adoption_state&&<Fact label="采用状态" value={item.adoption_state}/>}<Fact label="有效起始" value={item.valid_from}/><Fact label="有效截至" value={item.valid_until}/><p className="boss-helper">当前不能作为确定依据。</p></div>)}
        {!current?.conflicts&&<p className="boss-helper">来源当前状态按原记录展示，逐项冲突说明尚未提供。</p>}
      </Block>
      <Block title="状态与核查">
        <Fact label="研究状态" value={report?.state}/><Fact label="当前依据" value={current?.current_reference_state}/><Fact label="获准来源数" value={report?.coverage.current_approved_sources}/><Fact label="匹配来源数" value={report?.coverage.matched_source_count}/><Fact label="公开网页检索" value={report?report.coverage.public_web_search_performed?"已执行":"未执行":null}/><Fact label="语义检索" value={report?report.coverage.semantic_retrieval_performed?"已执行":"未执行":null}/>
        <label className="boss-label" htmlFor="boss-research-contact">起草核查消息的收件人</label><select id="boss-research-contact" className="boss-single-input" value={recipient} disabled={!current||blocked} onChange={event=>setRecipient(event.target.value)}><option value="">请选择获准联系人</option>{current?.contacts.map(person=><option key={person.contact_id} value={person.contact_id}>{person.name} · {person.organization}</option>)}</select><p className="boss-helper">核查消息保存为消息草稿，发送需要本人另行审核。</p>
        {draftId&&<p className="boss-helper">已保存消息草稿：{draftId}</p>}<button type="button" className="boss-btn" onClick={()=>onNavigate("F08")}>打开草稿</button>
        {transaction.recovery}
      </Block>
    </aside></div>
    <footer className="boss-research-footer boss-actions"><button type="button" className="boss-btn boss-btn-primary" disabled={disabled} onClick={begin}><Search size={15}/>开始研究</button><button type="button" className="boss-btn" disabled={!report||blocked||dirty||Boolean(current?.source_changed)} onClick={()=>void continueQuestion()}><BookOpen size={15}/>继续追问</button><button type="button" className="boss-btn" disabled={disabled||!report?.missing_items.length||dirty||Boolean(current?.source_changed)} onClick={createRequest}><Send size={15}/>起草核查消息</button></footer>
    {transaction.dialog}
  </div>;
}
