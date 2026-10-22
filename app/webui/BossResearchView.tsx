import { useEffect, useRef, useState, type ReactNode } from "react";
import { AlertCircle, ArrowRight, BookOpen, CheckCircle2,
  Clock3, FileSearch, FolderOpen, Loader2, RefreshCw,
  Search, ShieldCheck, Send } from "lucide-react";
import { useClient } from "@/providers/ClientProvider";

type Quote = {
  source_id:string;source_type:"SIMULATED";version:string;
  published_at:string;author_contact_id:string|null;
  original_locator:string|null;quote_start:number;quote_end:number;
  quote:string;match_start:number;claim_kind:"UNVERIFIED_SOURCE_EXCERPT";
  source_text_is_untrusted_instruction:true;
};
type Research = {
  research_id:string;version:string;state:string;source_type:"SIMULATED";
  scope:{question:string;period:string;country:string;
    business_relation:string;cutoff_date:string};
  matched_sources:Quote[];
  coverage:{current_approved_sources:number;matched_source_count:number;
    public_web_search_performed:false;semantic_retrieval_performed:false};
  missing_items:string[];
  facts_confirmed:unknown[];author_opinions_confirmed:unknown[];
  model_inferences:unknown[];
  external_message_sent:false;published_conclusions:false;
};
type Contact={contact_id:string;name:string;organization:string;responsibility:string};
type Projection={
  source_type:"SIMULATED";projection:"research";data_version:string;
  saved:boolean;report:Research|null;current_reference_state:string;
  source_changed?:boolean;current_source_count?:number;
  contacts:Contact[];preferred_timezone:string;read_only:true;
  revisions:{version:string;state:string;prepared_at:string;
    source_quote_text_released:false}[];
};
type Pending={
  action:"boss.research.prepare"|"boss.message.draft.save";
  id:string;title:string;fields:Record<string,unknown>;details:string[];
};
type Props={
  onNavigate:(page:string)=>void;onViewSource:(source:string)=>void;
  onStartChat:(question:string)=>Promise<void|boolean>;
};

function Block({title,note,children}:{
  title:string;note?:string;children:ReactNode;
}) {
  return <section className="boss-panel">
    <div className="boss-panel-head"><h2>{title}</h2>{note&&<small>{note}</small>}</div>
    {children}
  </section>;
}
function Fact({label,value}:{
  label:string;value?:string|number|boolean|null;
}) {
  return <div className="boss-kv"><span>{label}</span><strong>{value??"未核查"}</strong></div>;
}
export function BossResearchView({onNavigate,onViewSource,onStartChat}:Props){
  const {client,getToken}=useClient();
  const [data,setData]=useState<Projection|null>(null);
  const [revision,setRevision]=useState(0);
  const [loading,setLoading]=useState(false);
  const [error,setError]=useState("");
  const [notice,setNotice]=useState("");
  const [question,setQuestion]=useState("");
  const [period,setPeriod]=useState("");
  const [country,setCountry]=useState("");
  const [relation,setRelation]=useState("");
  const [cutoff,setCutoff]=useState("");
  const [recipient,setRecipient]=useState("");
  const [researchTab,setResearchTab]=useState<"SOURCE"|"FACT"|"OPINION"|"INFERENCE"|"MISSING">("SOURCE");
  const [pending,setPending]=useState<Pending|null>(null);
  const [approved,setApproved]=useState(false);
  const [busy,setBusy]=useState(false);
  const [lookupBusy,setLookupBusy]=useState(false);
  const modal=useRef<HTMLElement|null>(null);
  const reload=()=>setRevision(x=>x+1);
  useEffect(()=>{
    const abort=new AbortController();
    const token=getToken();
    if(!token){setError("老板身份过期，必须重新认证");return;}
    setLoading(true);setError("");setData(null);
    void fetch("/api/boss/ui/workspace/research",{
      headers:{Authorization:"Bearer "+token},cache:"no-store",signal:abort.signal,
    }).then(async res=>{
      if(!res.ok)throw Error("专题研究读取失败（HTTP "+res.status+"）");
      const value=await res.json() as Projection;
      if(value.source_type!=="SIMULATED"||value.projection!=="research")
        throw Error("当前报告来源与身份预期不一致");
      return value;
    }).then(value=>{
      if(abort.signal.aborted)return;
      setData(value);setLoading(false);
      if(value.report){
        const scope=value.report.scope;
        setQuestion(scope.question);setPeriod(scope.period);setCountry(scope.country);
        setRelation(scope.business_relation);setCutoff(scope.cutoff_date);
      }
    }).catch(e=>{
      if(abort.signal.aborted)return;
      setLoading(false);setError(e instanceof Error?e.message:String(e));
    });
    return ()=>abort.abort();
  },[revision,getToken]);
  useEffect(()=>{
    if(!pending)return;
    const focus=document.activeElement instanceof HTMLElement?document.activeElement:null;
    modal.current?.focus();
    const handler=(event:KeyboardEvent)=>{
      if(event.key==="Escape"&&!busy&&!lookupBusy){
        setPending(null);setApproved(false);return;
      }
      if(event.key!=="Tab"||!modal.current)return;
      const items=Array.from(modal.current.querySelectorAll<HTMLElement>(
        "button:not([disabled]),input:not([disabled])")).filter(x=>x.getClientRects().length>0);
      if(!items.length)return;
      if(event.shiftKey&&document.activeElement===items[0]){
        event.preventDefault();items[items.length-1].focus();
      }else if(!event.shiftKey&&document.activeElement===items[items.length-1]){
        event.preventDefault();items[0].focus();
      }
    };
    document.addEventListener("keydown",handler);
    return ()=>{document.removeEventListener("keydown",handler);focus?.focus();};
  },[pending?.id,busy,lookupBusy]);
  function propose(action:Pending["action"],fields:Record<string,unknown>,
                   title:string,details:string[]){
    setError("");setNotice("");setPending({
      action,fields,title,details,id:"boss-"+crypto.randomUUID(),
    });
    setApproved(false);
  }
  function begin(){
    if(!data){setError("正式研究状态尚未读取");return;}
    if(question.trim().length<2||question.length>160){setError("研究问题须为2—160字");return;}
    if(!/^\d{4}-\d\d-\d\d$/.test(cutoff)){setError("须选择完整资料截止日期");return;}
    propose("boss.research.prepare",{
      expected_version:data.report?.version||"0",question:question.trim(),
      period,country,business_relation:relation,cutoff_date:cutoff,
    },"保存当前有权范围的研究任务",[
      "研究问题："+question.trim(),
      "期间："+(period||"尚未指定")+" · 国别："+(country||"尚未指定"),
      "业务关系："+(relation||"尚未指定")+" · 来源截至 "+cutoff,
      "将检索获准来源并保存版本；不会推断因果或发布未经核实的结论。",
    ]);
  }
  function createRequest(){
    const report=data?.report;
    if(!report||!report.missing_items.length){
      setError("没有可供核查的研究缺口");return;
    }
    if(!data?.contacts.some(p=>p.contact_id===recipient)){
      setError("请选择当前资料中的稳定联系人 ID");return;
    }
    const message="请补充专题研究的有效来源和统计口径。问题："+report.scope.question+
      "；待补事项："+report.missing_items.join("、")+
      "。请返回原始材料、日期和版本供本人核对。";
    if(message.length>2400){setError("核查请求内容过长，须人工缩减范围");return;}
    propose("boss.message.draft.save",{
      draft_id:null,expected_version:"0",recipient_id:recipient,
      related_task_id:null,body:message,
      attachment_refs:[],visibility:"RECIPIENT_ONLY",
    },"准备资料核查请求草稿",[
      "唯一收件人："+recipient,"核查正文："+message,
      "仅保存 F08 DRAFT；不会自动发送或声称消息已经送达。",
    ]);
  }
  async function commit(){
    if(!pending||!approved||busy||lookupBusy)return;
    setBusy(true);setError("");
    try{
      const out=await client.requestMutation<{state?:string;status?:string;version?:string;
        research_id?:string;draft_id?:string}>(pending.action,{
        ...pending.fields,client_request_id:pending.id,
      });
      setNotice("已写入 SIMULATED 工作区："+(out.state||out.status||"DRAFT")+
        "。请查看回读状态；这不代表模型完成研究或对外发送。");
      setPending(null);setApproved(false);reload();
    }catch(e){
      setError((e instanceof Error?e.message:String(e))+
        "。网络中断时先查原请求回执，保留相同请求编号。");
    }finally{setBusy(false);}
  }
  async function reconcile(){
    if(!pending||busy||lookupBusy)return;
    const token=getToken();
    if(!token){setError("身份已过期，无法核对原请求");return;}
    setLookupBusy(true);setError("");
    try{
      const qs=new URLSearchParams({
        action:pending.action,client_request_id:pending.id,
      });
      const res=await fetch("/api/boss/ui/operation-status?"+qs.toString(),{
        headers:{Authorization:"Bearer "+token},cache:"no-store",
      });
      if(!res.ok)throw Error("查询原请求回执失败（HTTP "+res.status+"）");
      const rec=await res.json() as {
        action:string;client_request_id:string;outcome:string;
      };
      if(rec.action!==pending.action||rec.client_request_id!==pending.id)
        throw Error("回执与当前授权意图不匹配");
      if(rec.outcome==="RECORDED"){
        setNotice("已查到实际 SQLite 幂等回执，现重读研究或草稿版本。");
        setPending(null);setApproved(false);reload();
      }else if(rec.outcome==="NOT_FOUND_IN_CURRENT_STORE"){
        setError("没有原请求回执不能证明未执行；请先核查正式记录，必要时保持原编号重试。");
        reload();
      }else throw Error("回执状态不明确，不能自动重试");
    }catch(e){setError(e instanceof Error?e.message:String(e));}
    finally{setLookupBusy(false);}
  }
  async function continueQuestion(){
    if(!data?.report)return;
    setError("");
    const report=data.report;
    const request=[
      "仅进行当前身份有权的专题资料核对；不批准、不发送任何消息，也不执行工具写入。",
      "研究问题："+report.scope.question,
      "已有模拟来源标识："+report.matched_sources.map(s=>s.source_id+" v"+s.version).join("、"),
      "待验证问题："+report.missing_items.join("、"),
      "请分别标明可引用的事实原文、作者意见、模型推断和未知项。",
      "外部数据、当前行情与真实因果没有证据时必须说明尚未验证。",
    ].join("\n");
    try{
      const sent=await onStartChat(request);
      if(sent===false)throw Error("当前 Agent 会话暂不可用");
      onNavigate("NATIVE");
    }catch(e){setError(e instanceof Error?e.message:String(e));}
  }
  const report=data?.report;
  const sources=report?.matched_sources||[];
  return <>
    <div className="boss-workspace-toolbar">
      <div className="boss-workspace-note"><span className="boss-tag boss-tag-amber">SIMULATED</span>
        F09 · 专题研究 · 来源与因果分离
      </div>
      <button type="button" className="boss-btn" disabled={loading} onClick={reload}>
        {loading?<Loader2 size={15} className="boss-spin"/>:<RefreshCw size={15}/>} 重读当前版本
      </button>
    </div>
    {error&&<div role="alert" className="boss-status boss-status-error"><AlertCircle size={16}/>{error}</div>}
    {notice&&<div role="status" className="boss-status boss-status-ok"><CheckCircle2 size={16}/>{notice}</div>}
    {loading&&<div role="status" className="boss-status"><Loader2 size={16} className="boss-spin"/>读取当前来源和研究版本…</div>}
    <section className="boss-panel">
      <div className="boss-panel-head"><h2>研究范围</h2><small>原 Desktop v6 四条件筛选</small></div>
      <div className="boss-research-filters">
        <label>研究问题<input value={question} onChange={e=>setQuestion(e.target.value)}
          placeholder="明确需要查证的词句或问题（2—160字）"/></label>
        <label>期间<input value={period} onChange={e=>setPeriod(e.target.value)}
          placeholder="如需限定，请明确期间"/></label>
        <label>国别<input value={country} onChange={e=>setCountry(e.target.value)}
          placeholder="无可靠国别关联时留空"/></label>
        <label>业务关系<input value={relation} onChange={e=>setRelation(e.target.value)}
          placeholder="明确需验证的业务联系"/></label>
        <label>来源截止日期<input type="date" value={cutoff} onChange={e=>setCutoff(e.target.value)}/></label>
      </div>
      <div className="boss-actions">
        <button type="button" className="boss-btn boss-btn-primary"
          disabled={!data||busy} onClick={begin}>
          <Search size={15}/> 开始来源研究并保存版本
        </button>
        <button type="button" className="boss-btn" disabled={!report}
          onClick={()=>void continueQuestion()}>
          <BookOpen size={15}/> 在 Agent 中继续追问
        </button>
      </div>
      <p className="boss-helper">当前本机数据范围只覆盖获准的合成来源；不在此处伪造公开网页检索、模型推断、经营原因或跨国数据。</p>
    </section>
    <div className="boss-columns">
      <div className="boss-column">
        <div className="boss-minutes-tabs boss-research-tabs">
          {([
            ["SOURCE","原文引用"],["FACT","可核查事实"],
            ["OPINION","作者意见"],["INFERENCE","模型推断"],
            ["MISSING","待验证问题"],
          ] as const).map(([id,label])=><button key={id} type="button"
            className={researchTab===id?"selected":""} onClick={()=>setResearchTab(id)}>
            {label}
          </button>)}
        </div>
        {researchTab==="SOURCE"&&<Block title="可打开的原始引用" note="准确定位 · 来源时间与版本">
          {sources.length?sources.map(row=><div key={row.source_id} className="boss-workspace-item">
            <div className="boss-workspace-item-top">
              <strong>{row.source_id}</strong><span className="boss-tag boss-tag-green">原文未分类</span>
            </div>
            <p className="boss-research-quote">{row.quote}</p>
            <Fact label="原文偏移">{row.quote_start+" — "+row.quote_end}</Fact>
            <Fact label="引用版本">{row.version}</Fact>
            <Fact label="作者 ID">{row.author_contact_id}</Fact>
            <Fact label="发布日期">{row.published_at.replace("T"," ")}</Fact>
            <div className="boss-actions"><button type="button" className="boss-btn"
              onClick={()=>onViewSource(row.source_id)}>
              <FileSearch size={15}/> 打开当前有效原文
            </button></div>
          </div>):<div className="boss-empty"><FolderOpen size={20}/>
            <div><strong>当前没有匹配的有效来源</strong>
              <p>不能把搜索结果为空解释成已证实无风险或结论为零。</p></div>
          </div>}
        </Block>}
        {researchTab==="FACT"&&<Block title="可核查事实" note="只接受逐条独立验证的来源命题">
          <div className="boss-empty"><FileSearch size={18}/><div>
            <strong>没有已经单独确认的事实断言</strong>
            <p>上方的来源摘录仅为材料原文，未经逐条核验不得直接改名为真实事实。</p>
          </div></div>
        </Block>}
        {researchTab==="OPINION"&&<Block title="作者意见" note="保留来源、作者、日期与原文位置">
          <div className="boss-empty"><FolderOpen size={18}/><div>
            <strong>作者意见尚未完成分类审核</strong>
            <p>不能默认将材料作者的描述视作专家结论或老板决定。</p>
          </div></div>
        </Block>}
        {researchTab==="INFERENCE"&&<Block title="模型推断" note="模型内容与客观来源分别记录">
          <div className="boss-empty"><AlertCircle size={18}/><div>
            <strong>当前没有经过本机真实模型执行的推断记录</strong>
            <p>如果需要进一步分析，可打开原生 Agent 会话；会话回答不自动作为经过证实的结论保存。</p>
          </div></div>
        </Block>}
        {researchTab==="MISSING"&&<Block title="待验证问题与资料缺口" note="范围和适用性由用户明确">
          {(report?.missing_items||[]).map(item=><div className="boss-workspace-item" key={item}>{item}</div>)}
          {!report?.missing_items.length&&<div className="boss-empty"><FolderOpen size={18}/>
            <div><strong>当前没有已保存研究</strong><p>请先输入问题和来源截止日期。</p></div>
          </div>}
        </Block>}
      </div>
      <div className="boss-column">
        <Block title="来源与版本完整性" note="右侧来源属性、日期和失效状态">
          <Fact label="研究版本" value={report?.version}/>
          <Fact label="研究状态" value={data?.current_reference_state||"NOT_PREPARED"}/>
          <Fact label="本次范围" value={report?.scope.question}/>
          <Fact label="合规当前来源数" value={report?.coverage.current_approved_sources}/>
          <Fact label="匹配来源数" value={report?.coverage.matched_source_count}/>
          <Fact label="外部网页检索" value="未执行"/>
          <Fact label="已发布研究结论" value="无"/>
          <Fact label="支持具体因果结论" value="未核验"/>
          {data?.source_changed&&<div className="boss-status boss-status-warn">
            <AlertCircle size={15}/> 历史引用已失效，旧摘录不再展示，请重新检查来源。
          </div>}
          <div className="boss-actions">
            <button className="boss-btn" type="button" onClick={()=>onNavigate("F03")}>
              <ArrowRight size={15}/> 查看现有经营查询
            </button>
          </div>
        </Block>
        <Block title="准备资料核查请求" note="保存 DRAFT · 不自动对外发送">
          <label className="boss-label" htmlFor="boss-research-contact">选择获准联系人</label>
          <select id="boss-research-contact" className="boss-single-input" value={recipient}
            onChange={e=>setRecipient(e.target.value)}>
            <option value="">请选择稳定联系人 ID</option>
            {(data?.contacts||[]).map(person=><option key={person.contact_id} value={person.contact_id}>
              {person.name} · {person.organization} [{person.contact_id}]
            </option>)}
          </select>
          <div className="boss-actions">
            <button type="button" className="boss-btn"
              disabled={!report||busy} onClick={createRequest}>
              <Send size={15}/> 保存核查请求草稿
            </button>
            <button type="button" className="boss-btn" onClick={()=>onNavigate("F08")}>打开 F08 消息</button>
          </div>
          <div className="boss-status boss-status-warn">
            <ShieldCheck size={15}/> 核查请求仍需本人在 F08 独立审核后才可进行模拟发送；不代表实际投递。
          </div>
        </Block>
        <Block title="历史研究版本">
          {(data?.revisions||[]).map(item=><div className="boss-workspace-item" key={item.version}>
            <strong>研究 v{item.version}</strong>
            <Fact label="准备时间" value={item.prepared_at.replace("T"," ")}/>
            <p>历史来源只保留版本元信息，失效摘录不重新放出。</p>
          </div>)}
          {!(data?.revisions||[]).length&&<p className="boss-helper">暂无历史版本。</p>}
        </Block>
      </div>
    </div>
    {pending&&<div className="boss-confirm-backdrop">
      <section className="boss-confirm" ref={modal} tabIndex={-1} role="dialog"
        aria-modal="true" aria-labelledby="boss-research-review">
        <h3 id="boss-research-review"><ShieldCheck size={18}/>{pending.title}</h3>
        <p>本次只是模拟研究资料准备或准备请求草稿。来源将由服务端重新核验，不能跳过授权。</p>
        <dl>{pending.details.map((line,i)=><div key={i}><dd>{line}</dd></div>)}</dl>
        <label className="boss-confirm-check">
          <input type="checkbox" checked={approved} disabled={busy}
            onChange={e=>setApproved(e.target.checked)}/>
          <span>我确认当前问题、来源范围及本次操作后果。</span>
        </label>
        {error&&<p className="boss-validation-error" role="alert">{error}</p>}
        <div className="boss-actions">
          <button type="button" className="boss-btn" disabled={busy||lookupBusy}
            onClick={()=>setPending(null)}>取消（无业务写入）</button>
          <button type="button" className="boss-btn" disabled={busy||lookupBusy}
            onClick={()=>void reconcile()}>
            {lookupBusy&&<Loader2 size={15} className="boss-spin"/>} 核查原请求回执
          </button>
          <button type="button" className="boss-btn boss-btn-primary"
            disabled={!approved||busy||lookupBusy} onClick={()=>void commit()}>
            {busy&&<Loader2 size={15} className="boss-spin"/>} 确认并保存
          </button>
        </div>
      </section>
    </div>}
  </>;
}
