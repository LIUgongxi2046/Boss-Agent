import { useEffect, useRef, useState } from "react";
import { AlertCircle, CheckCircle2, Clock3, FileSearch,
  Loader2, RefreshCw, ShieldCheck, Trash2 } from "lucide-react";
import { useClient } from "@/providers/ClientProvider";

// A07 technical metadata only: no query returns private source body.
type SourceRow = {
  source_id:string;version:string;withdrawn:boolean;
  index_state:string;created_by_role:string|null;title:string|null;
  published_at:string|null;source_type:"SIMULATED";
};
type SourceIndex = {
  projection:"source-index";source_type:"SIMULATED";data_version:string;
  sources:SourceRow[];count:number;original_body_available_here:false;
  available_simulated_author_ids:string[];
};
type Pending = {
  key:string;action:"boss.knowledge.source.create"|
    "boss.knowledge.source.revise"|"boss.knowledge.source.withdraw";
  title:string;payload:Record<string,unknown>;details:string[];
};
type Status = {
  status?:string;source_id?:string;version?:string;
  index_state?:string;withdrawn?:boolean;
};

export function MaintainerKnowledgeEditor() {
  const {client,getToken}=useClient();
  const [index,setIndex]=useState<SourceIndex|null>(null);
  const [revision,setRevision]=useState(0);
  const [loading,setLoading]=useState(false);
  const [error,setError]=useState("");
  const [notice,setNotice]=useState("");
  const [sourceId,setSourceId]=useState("");
  const [title,setTitle]=useState("");
  const [author,setAuthor]=useState("");
  const [publishedAt,setPublishedAt]=useState("");
  const [content,setContent]=useState("");
  const [pending,setPending]=useState<Pending|null>(null);
  const [approved,setApproved]=useState(false);
  const [busy,setBusy]=useState(false);
  const [lookupBusy,setLookupBusy]=useState(false);
  const confirmRef=useRef<HTMLElement|null>(null);
  const source=index?.sources.find(x=>x.source_id===sourceId);
  const isOwnedSource=Boolean(source?.created_by_role==="MAINTAINER"
    && sourceId.startsWith("sim-doc-"));
  const canRevise=isOwnedSource && !source?.withdrawn;

  useEffect(()=>{
    const abort=new AbortController();
    const token=getToken();
    if(!token){setError("维护身份失效，拒绝查询来源目录");return;}
    setLoading(true);setError("");
    void fetch("/api/boss/ui/workspace/source-index",{
      headers:{Authorization:"Bearer "+token},cache:"no-store",signal:abort.signal,
    }).then(async response=>{
      if(!response.ok)throw Error("技术资料元数据读取失败（HTTP "+response.status+"）");
      const result=await response.json() as SourceIndex;
      if(result.projection!=="source-index"||result.source_type!=="SIMULATED"
         ||result.original_body_available_here!==false)
        throw Error("当前资料元数据包含了超出授权的字段");
      return result;
    }).then(result=>{
      if(abort.signal.aborted)return;
      setIndex(result);setLoading(false);
    }).catch(e=>{
      if(abort.signal.aborted)return;
      setLoading(false);setError(e instanceof Error?e.message:String(e));
    });
    return ()=>abort.abort();
  },[revision,getToken]);

  useEffect(()=>{
    if(!pending)return;
    const previous=document.activeElement instanceof HTMLElement
      ? document.activeElement:null;
    confirmRef.current?.focus();
    const key=(e:KeyboardEvent)=>{
      if(e.key==="Escape"&&!busy&&!lookupBusy){
        e.preventDefault();setPending(null);setApproved(false);
      }
      if(e.key!=="Tab"||!confirmRef.current)return;
      const controls=Array.from(confirmRef.current.querySelectorAll<HTMLElement>(
        'button:not([disabled]), input:not([disabled])'
      )).filter(x=>x.getClientRects().length>0);
      if(controls.length&&e.shiftKey&&document.activeElement===controls[0]){
        e.preventDefault();controls[controls.length-1].focus();
      }else if(controls.length&&!e.shiftKey&&document.activeElement===controls[controls.length-1]){
        e.preventDefault();controls[0].focus();
      }
    };
    document.addEventListener("keydown",key);
    return ()=>{document.removeEventListener("keydown",key);previous?.focus();};
  },[pending?.key,busy,lookupBusy]);

  function loadSource(id:string){
    setSourceId(id);setContent("");
    const found=index?.sources.find(x=>x.source_id===id);
    if(found&&found.created_by_role==="MAINTAINER"){
      setTitle(found.title||"");
      setPublishedAt(found.published_at?.slice(0,10)||"");
    }else{setTitle("");setPublishedAt("");}
  }

  function prepare(mode:"create"|"revise"|"withdraw"){
    setError("");setNotice("");
    const id=sourceId.trim();
    if(!/^sim-doc-[a-z0-9][a-z0-9-]{2,59}$/.test(id)){
      setError("本次维护只能创建或管理 sim-doc-* 格式的模拟资料标识");return;
    }
    const revisionAction=mode!=="create";
    if((!revisionAction&&source) || (revisionAction&&!canRevise)){
      setError("当前来源已存在、已撤销，或不是维护端获准修订的模拟资料");return;
    }
    let payload:Record<string,unknown>;
    const details=[
      "来源："+id,
      "执行身份：MAINTAINER · SIMULATED",
      "当前技术目录不允许读取既有老板资料原文。",
    ];
    if(mode==="withdraw"){
      payload={source_id:id,expected_version:source!.version};
      details.push("撤销当前版本："+source!.version,
        "原文从当前检索索引移除，但历史审计仍保留。");
    }else{
      if(!title.trim()||title.length>120||
         content.trim().length<30||content.length>12000||
         !index?.available_simulated_author_ids.includes(author)||
         !/^\d{4}-\d\d-\d\d$/.test(publishedAt)){
        setError("请补齐标题、当前模拟作者 ID、有效日期和30—12000字的明确原文。");return;
      }
      payload={
        source_id:id,title:title.trim(),author_contact_id:author,
        published_at:publishedAt,content:content.trim(),
        ...(revisionAction?{expected_version:source!.version}:{}),
      };
      details.push(
        "标题："+title,"作者 ID："+author,"发布日期："+publishedAt,
        "拟保存的完整模拟资料："+content,
        revisionAction?"当前版本："+source!.version+" → 自动递增":"创建版本 v1",
        "这只是明确输入的模拟材料，不会自动采集互联网或授权老板执行动作。",
      );
    }
    const action=("boss.knowledge.source."+mode) as Pending["action"];
    setPending({key:"boss-"+crypto.randomUUID(),action,title:{
      create:"确认摄取新的模拟知识来源",
      revise:"确认以新版本替换模拟知识来源",
      withdraw:"确认撤销模拟知识来源",
    }[mode],payload,details});
    setApproved(false);
  }

  function onSaved(result:Status){
    setNotice("来源处理回执已记录："+(result.source_id||sourceId)+
      " v"+(result.version||"未知")+" · "+(result.index_state||result.status||"状态待读取")+
      "。已请求重新读取数据库和检索索引。");
    setPending(null);setApproved(false);setContent("");
    setRevision(x=>x+1);
  }
  async function commit(){
    if(!pending||!approved||busy||lookupBusy)return;
    setBusy(true);setError("");
    try{
      const result=await client.requestMutation<Status>(pending.action,{
        ...pending.payload,client_request_id:pending.key,
      });
      onSaved(result);
    }catch(e){
      setError((e instanceof Error?e.message:String(e))+
        "。本次可能已经落库；请先按原请求编号核对回执。");
    }finally{setBusy(false);}
  }
  async function reconcile(){
    if(!pending||busy||lookupBusy)return;
    const token=getToken();
    if(!token){setError("维护身份过期，不能核查原请求");return;}
    setLookupBusy(true);setError("");
    try{
      const q=new URLSearchParams({action:pending.action,client_request_id:pending.key});
      const res=await fetch("/api/boss/ui/operation-status?"+q.toString(),{
        headers:{Authorization:"Bearer "+token},cache:"no-store",
      });
      if(!res.ok)throw Error("当前请求回执读取失败（HTTP "+res.status+"）");
      const body=await res.json() as {
        action:string;client_request_id:string;outcome:string;result?:Status;
      };
      if(body.action!==pending.action||body.client_request_id!==pending.key)
        throw Error("回执动作或标识与当前确认不一致");
      if(body.outcome==="RECORDED"&&body.result){
        onSaved(body.result);
      }else if(body.outcome==="NOT_FOUND_IN_CURRENT_STORE"){
        setError("当前未查到持久回执，但这不是未执行的证明。请重读来源版本，再以原编号重试。");
        setRevision(x=>x+1);
      }else throw Error("未知回执状态，不能推定成功");
    }catch(e){setError(e instanceof Error?e.message:String(e));}
    finally{setLookupBusy(false);}
  }

  return <>
    <div className="boss-columns">
      <div className="boss-column">
        <section className="boss-panel">
          <div className="boss-panel-head">
            <h2>Knowledge Base · 受控来源摄取</h2>
            <small>A07 · 模拟资料 · 技术维护</small>
          </div>
          <p className="boss-helper">仅允许录入明确提供的模拟资料，保留作者、发布日期、来源版本和当前索引状态。管理端只读取目录元数据，无法查看老板已有来源正文。</p>
          <div className="boss-form-grid">
            <label>来源 ID（sim-doc-*）
              <input value={sourceId} onChange={e=>loadSource(e.target.value)}
                placeholder="sim-doc-operational-note"/>
            </label>
            <label>模拟资料作者 ID
              <select value={author} onChange={e=>setAuthor(e.target.value)}>
                <option value="">请选择已存在模拟作者</option>
                {(index?.available_simulated_author_ids||[]).map(id=>
                  <option value={id} key={id}>{id}</option>)}
              </select>
            </label>
            <label>当前资料标题
              <input value={title} onChange={e=>setTitle(e.target.value)}
                placeholder="明确提供的标题，不生成"/>
            </label>
            <label>资料发布日期
              <input type="date" value={publishedAt}
                onChange={e=>setPublishedAt(e.target.value)}/>
            </label>
          </div>
          <label className="boss-label" htmlFor="boss-knowledge-technical-body">
            本次明确录入的模拟原文（维护端不能读取此前老板原文）
          </label>
          <textarea id="boss-knowledge-technical-body" rows={5}
            value={content} onChange={e=>setContent(e.target.value)}
            placeholder="粘贴本次明确提供的模拟文本，30—12000 字。不能包含 API Key 或真实私人信息。"/>
          <div className="boss-actions">
            <button type="button" className="boss-btn boss-btn-primary"
              disabled={busy||loading} onClick={()=>prepare("create")}>
              <ShieldCheck size={15}/> 核对并创建来源
            </button>
            <button type="button" className="boss-btn" disabled={!canRevise||busy||loading}
              onClick={()=>prepare("revise")}>
              <FileSearch size={15}/> 校验并保存新版本
            </button>
            <button type="button" className="boss-btn" disabled={!canRevise||busy||loading}
              onClick={()=>prepare("withdraw")}>
              <Trash2 size={15}/> 明确撤销来源
            </button>
          </div>
          {error&&<div className="boss-status boss-status-error" role="alert">
            <AlertCircle size={16}/>{error}
          </div>}
          {notice&&<div className="boss-status boss-status-ok" role="status">
            <CheckCircle2 size={16}/>{notice}
          </div>}
        </section>
      </div>
      <div className="boss-column">
        <section className="boss-panel">
          <div className="boss-panel-head">
            <h2>索引与来源版本</h2><small>受限技术元信息</small>
          </div>
          {loading&&<div className="boss-status" role="status">
            <Loader2 size={16} className="boss-spin"/> 正在读取实际持久来源目录
          </div>}
          <div className="boss-kv"><span>当前执行空间</span><strong>ui-check</strong></div>
          <div className="boss-kv"><span>有效资料数量（含固定资料）</span>
            <strong>{index?.sources.filter(x=>!x.withdrawn).length??"待核查"}</strong></div>
          {(index?.sources||[]).map(row=><button
            key={row.source_id} type="button"
            className={"boss-task-row "+(sourceId===row.source_id?"selected":"")}
            onClick={()=>loadSource(row.source_id)}>
            <span className="boss-task-icon"><FileSearch size={15}/></span>
            <span>
              <strong>{row.title||row.source_id}</strong>
              <small>{row.source_id} · v{row.version} · {row.index_state}</small>
              <small>{row.withdrawn?"已撤销 · 当前不检索":"当前来源元信息"} · {row.published_at||"日期待核查"}</small>
            </span>
          </button>)}
          <button className="boss-btn" type="button" disabled={loading}
            onClick={()=>setRevision(x=>x+1)}>
            <RefreshCw size={15}/> 重读实际版本
          </button>
          <div className="boss-status boss-status-warn">
            <Clock3 size={16}/> 当前只有 SQLite 内明确提供的合成来源。
            来源修订和撤销会影响老板端当前检索；历史审计不等于来源仍然有效。
          </div>
        </section>
      </div>
    </div>
    {pending&&<div className="boss-confirm-backdrop">
      <section ref={confirmRef} tabIndex={-1} role="dialog" aria-modal="true"
        aria-labelledby="boss-knowledge-confirm" className="boss-confirm">
        <h3 id="boss-knowledge-confirm"><ShieldCheck size={18}/>{pending.title}</h3>
        <p>服务端再次校验业务对象、当前版本、模拟范围及幂等编号。此操作不会调用真实外部知识抓取，也不会替老板批准交办。</p>
        <dl>{pending.details.map((v,i)=><div key={i}><dd>{v}</dd></div>)}</dl>
        <label className="boss-confirm-check">
          <input type="checkbox" checked={approved} disabled={busy||lookupBusy}
            onChange={e=>setApproved(e.target.checked)}/>
          <span>我确认当前模拟资料、作者、版本以及索引变化范围。</span>
        </label>
        {error&&<p className="boss-validation-error" role="alert">{error}</p>}
        <footer className="boss-actions">
          <button className="boss-btn" type="button" disabled={busy||lookupBusy}
            onClick={()=>setPending(null)}>取消</button>
          <button className="boss-btn" type="button" disabled={busy||lookupBusy}
            onClick={()=>void reconcile()}>
            {lookupBusy&&<Loader2 size={15} className="boss-spin"/>} 核查原请求回执
          </button>
          <button className="boss-btn boss-btn-primary" type="button"
            disabled={!approved||busy||lookupBusy} onClick={()=>void commit()}>
            {busy&&<Loader2 size={15} className="boss-spin"/>} 确认当前版本写入
          </button>
        </footer>
      </section>
    </div>}
  </>;
}
