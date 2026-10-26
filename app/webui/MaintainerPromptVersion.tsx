import { useCallback, useEffect, useRef, useState } from "react";
import {
  AlertCircle, CheckCircle2, ClipboardCheck, Clock3, FileSearch,
  Loader2, RefreshCw, ShieldCheck, Square, WandSparkles,
} from "lucide-react";
import { useClient } from "@/providers/ClientProvider";
import {diffLines} from "diff";
import * as Dialog from "@radix-ui/react-dialog";
import {V7Empty,V7Panel,V7Tabs} from "./BossV7UI";

type Kind = "SECRETARY_ROLE" | "EXPRESSION" | "TASK_HINTS";
const KINDS: {id:Kind;label:string}[] = [
  {id:"SECRETARY_ROLE",label:"秘书职责"},
  {id:"EXPRESSION",label:"表达要求"},
  {id:"TASK_HINTS",label:"任务提示"},
];
type Prompt = {
  prompt_id:string;kind:Kind;title:string;instruction_text:string;
  version:string;content_sha256:string;
  source_refs:{source_id:string;version:string}[];
  change_note:string;validation_status:string;validated_at?:string|null;
  updated_at:string;
};
type Active = {
  kind:Kind;prompt_id:string;prompt_version:string;active_version:string;
  enabled:boolean;adoption_policy:string;
  runtime_context_adoption:"NOT_OBSERVED"|"RUNTIME_CONTEXT_PROVIDER_INVOKED";
  context_load_count:number;last_context_at:string|null;
  actual_model_evaluation_passed:false;
};
type Data = {
  source_type:"SIMULATED";projection:"prompt-versions";data_version:string;
  kinds:Kind[];drafts:Prompt[];revisions:Prompt[];active:Active[];adoptable_current_ids:string[];
  model_evaluation_completed:false;full_security_evaluation_completed:false;
  runtime_eligibility:{projection:"prompt-technical-status";checked_at:string;items:{kind:Kind;enabled:boolean;prompt_id:string|null;prompt_version:string|null;active_version:string|null;future_context_eligible:boolean;exclusion_reasons:string[];source_status:{source_id:string;pinned_version:string;current_version:string|null;validity_state:string}[]}[]};
};
type Receipt = {action:string;client_request_id:string;outcome:string;result?:Record<string,unknown>};
type Pending = {key:string;action:string;title:string;
  fields:Record<string,unknown>;details:string[]};
type Props={onNavigate:(page:string)=>void;onDirtyChange:(dirty:boolean)=>void};

function detailsLabel({label,value}:{label:string;value?:string|number|null}) {
  return <div className="boss-kv"><span>{label}</span><strong>{value??"待核查"}</strong></div>;
}
const Detail=detailsLabel;

export function MaintainerPromptVersion({onNavigate,onDirtyChange}:Props) {
  const {client,getToken,token}=useClient();
  const [data,setData]=useState<Data|null>(null);
  const [loading,setLoading]=useState(false);
  const [error,setError]=useState("");
  const [notice,setNotice]=useState("");
  const [revision,setRevision]=useState(0);
  const [kind,setKind]=useState<Kind>("SECRETARY_ROLE");
  const [chosen,setChosen]=useState("");
  const [title,setTitle]=useState("");
  const [body,setBody]=useState("");
  const [changeNote,setChangeNote]=useState("");
  const [sources,setSources]=useState("");
  const [dirty,setDirty]=useState(false);
  const [editingVersion,setEditingVersion]=useState("0");
  const [tab,setTab]=useState<"content"|"tasks"|"sources"|"changes">("content");
  const [compareOpen,setCompareOpen]=useState(false);
  const dirtyRef=useRef(dirty),chosenRef=useRef(chosen);dirtyRef.current=dirty;chosenRef.current=chosen;
  const adoptionRef=useRef<HTMLElement>(null);
  useEffect(()=>onDirtyChange(dirty),[dirty,onDirtyChange]);
  const [pending,setPending]=useState<Pending|null>(null);
  const [discardIntent,setDiscardIntent]=useState<{kind:Kind;chosen:string}|null>(null);
  const [approved,setApproved]=useState(false);
  const [busy,setBusy]=useState(false);
  const [lookupBusy,setLookupBusy]=useState(false);
  const modalRef=useRef<HTMLElement|null>(null);
  const keyRef=useRef<string|null>(null);
  const identityRef=useRef({client,token});
  const mountedRef=useRef(true);
  if(identityRef.current.client!==client||identityRef.current.token!==token)
    identityRef.current={client,token};
  const reload=()=>setRevision(v=>v+1);

  const clearConfiguration=useCallback(()=>{
    identityRef.current={...identityRef.current};
    setData(null);setChosen("");setTitle("");setBody("");setChangeNote("");setSources("");
    setDirty(false);setEditingVersion("0");setPending(null);setDiscardIntent(null);setApproved(false);setCompareOpen(false);
    setBusy(false);setLookupBusy(false);setLoading(false);setNotice("");keyRef.current=null;
  },[]);

  useEffect(()=>{
    mountedRef.current=true;
    return ()=>{mountedRef.current=false;};
  },[]);

  useEffect(()=>{
    clearConfiguration();
  },[client,token,clearConfiguration]);

  useEffect(()=>{
    const abort=new AbortController();const currentToken=getToken();
    const identity=identityRef.current;
    if(!currentToken){setError("技术维护身份已失效");setLoading(false);return;}
    setLoading(true);setError("");setData(null);
    void fetch("/api/boss/ui/workspace/prompt-versions",{
      headers:{Authorization:"Bearer "+currentToken},cache:"no-store",signal:abort.signal,
    }).then(async response=>{
      if(abort.signal.aborted||identity!==identityRef.current)return null;
      if(response.status===401||response.status===403){
        clearConfiguration();setError("Prompt版本读取失败（HTTP "+response.status+"）");
      }
      if(!response.ok)throw Error("Prompt版本读取失败（HTTP "+response.status+"）");
      const value=await response.json() as Data;
      if(value.projection!=="prompt-versions"||value.source_type!=="SIMULATED"||value.runtime_eligibility?.projection!=="prompt-technical-status")
        throw Error("来源与身份不符，禁止把设计示例当真实状态");
      return value;
    }).then(value=>{
      if(abort.signal.aborted||identity!==identityRef.current||value===null)return;
      setData(value);setLoading(false);
      const selected=value.drafts.find(item=>item.prompt_id===(keyRef.current??chosenRef.current));
      if(selected&&!dirtyRef.current){setChosen(selected.prompt_id);setTitle(selected.title);setBody(selected.instruction_text);setChangeNote(selected.change_note);setSources(selected.source_refs.map(row=>row.source_id).join(", "));setEditingVersion(selected.version);}
      keyRef.current=null;
    }).catch(e=>{
      if(abort.signal.aborted||identity!==identityRef.current)return;
      setError(e instanceof Error?e.message:String(e));setLoading(false);
    });
    return ()=>abort.abort();
  },[revision,getToken,client,token,clearConfiguration]);

  useEffect(()=>{
    if(!pending)return;
    const origin=document.activeElement instanceof HTMLElement?document.activeElement:null;
    modalRef.current?.focus();
    const handler=(e:KeyboardEvent)=>{
      if(e.key==="Escape"&&!busy&&!lookupBusy){setPending(null);setApproved(false);return;}
      if(e.key!=="Tab"||!modalRef.current)return;
      const items=Array.from(modalRef.current.querySelectorAll<HTMLElement>(
        'button:not([disabled]),input:not([disabled])')).filter(x=>x.getClientRects().length>0);
      if(!items.length){e.preventDefault();modalRef.current.focus();return;}
      if(e.shiftKey&&document.activeElement===items[0]){e.preventDefault();items[items.length-1].focus();}
      else if(!e.shiftKey&&document.activeElement===items[items.length-1]){
        e.preventDefault();items[0].focus();
      }
    };
    document.addEventListener("keydown",handler);
    return ()=>{document.removeEventListener("keydown",handler);origin?.focus();};
  },[pending?.key,busy,lookupBusy]);

  const prompt=data?.drafts.find(p=>p.prompt_id===chosen);
  const previous=data?.revisions.filter(p=>p.prompt_id===chosen)
    .sort((a,b)=>Number(b.version)-Number(a.version))[0];
  const differences=prompt&&previous?diffLines(previous.instruction_text,prompt.instruction_text):[];
  const active=data?.active.find(a=>a.kind===kind);
  const candidates=data?.drafts.filter(p=>p.kind===kind)||[];
  const eligibility=data?.runtime_eligibility.items.find(row=>row.kind===kind);
  const stale=!!chosen&&(!prompt||prompt.version!==editingVersion);
  const unavailable=busy||lookupBusy||loading||!!pending||!data;
  function showAdoption(){adoptionRef.current?.scrollIntoView({block:"start",behavior:"smooth"});adoptionRef.current?.focus();}
  function selectPrompt(id:string,force=false) {
    if(dirty&&!force){setDiscardIntent({kind,chosen:id});return;}
    setChosen(id);const selected=data?.drafts.find(p=>p.prompt_id===id);
    setTitle(selected?.title||"");setBody(selected?.instruction_text||"");
    setChangeNote(selected?.change_note||"");
    setSources(selected?.source_refs.map(x=>x.source_id).join(", ")||"");
    setEditingVersion(selected?.version??"0");setDirty(false);setError("");setNotice("");
  }
  function changeKind(next:Kind,force=false){
    if(next===kind)return;
    if(dirty&&!force){setDiscardIntent({kind:next,chosen:""});return;}
    setKind(next);setChosen("");setTitle("");setBody("");
    setChangeNote("");setSources("");setEditingVersion("0");setDirty(false);
    setError("");setNotice("");
  }
  function confirmDiscard(){
    const next=discardIntent;
    setDiscardIntent(null);
    if(!next)return;
    if(next.kind!==kind)changeKind(next.kind,true);
    else selectPrompt(next.chosen,true);
  }
  function prepare(action:string,fields:Record<string,unknown>,label:string,scope:string[]){
    setPending({key:"boss-"+crypto.randomUUID(),action,fields,title:label,details:scope});
    setApproved(false);setError("");setNotice("");
  }
  function save() {
    setError("");
    if(!data){setError("配置列表尚未读取");return;}
    if(stale){setError("当前草稿版本已经变化，请取消编辑并重新读取。");return;}
    const sourceIds=sources.split(/[,，\n]/g).map(s=>s.trim()).filter(Boolean);
    if(body.trim().length<20||body.length>5000||title.trim().length<1||title.length>120||
       changeNote.trim().length<1||changeNote.length>360||sourceIds.length>5){
      setError("须填写标题、20—5000字正文和变更说明，最多引用5个获准来源");return;
    }
    if(new Set(sourceIds).size!==sourceIds.length){setError("来源ID重复");return;}
    prepare("boss.prompt.save",{
      prompt_id:prompt?.prompt_id||null,expected_version:editingVersion,
      kind,title:title.trim(),instruction_text:body.trim(),
      change_note:changeNote.trim(),source_ids:sourceIds,
    },"保存技术Prompt草稿",[
      "类别："+kind,"ID："+(prompt?.prompt_id||"新建Prompt"),
      "当前版本："+(prompt?.version||"0"),"适用来源："+sourceIds.join("、"),
      "变更原因："+changeNote,"正文："+body.trim(),
      "只保存 DRAFT_UNVALIDATED，不表示校验或运行时采用。维护配置不能扩大老板授权。",
    ]);
  }
  function validate() {
    if(!prompt){setError("必须先保存并读取已有草稿");return;}
    if(dirty){setError("存在未保存的改动，先保存新版本");return;}
    prepare("boss.prompt.validate",{
      prompt_id:prompt.prompt_id,expected_version:prompt.version,
      expected_content_sha256:prompt.content_sha256,
    },"对当前Prompt执行结构与引用校验",[
      "Prompt："+prompt.prompt_id+" v"+prompt.version,
      "只验证字段结构和当前来源引用，不代表模型质量评测或防注入审核通过。",
    ]);
  }
  function activate() {
    if(!prompt){setError("先选择已校验Prompt");return;}
    if(dirty){setError("当前有未保存的草稿修改");return;}
    if(prompt.validation_status!=="VALIDATED_STATIC_ONLY"){
      setError("当前版本尚未通过结构校验");return;
    }
    prepare("boss.prompt.activate",{
      prompt_id:prompt.prompt_id,expected_version:prompt.version,
      expected_content_sha256:prompt.content_sha256,
      expected_active_version:active?.active_version||"0",
    },"启用当前已校验版本",[
      "当前候选："+prompt.prompt_id+" v"+prompt.version,
      "类别："+prompt.kind,"替代活跃版本："+(active?.active_version||"0"),
      "仅对以后新调用的 Agent 上下文可用；不代表已有会话重放或模型执行成功。",
    ]);
  }
  function deactivate() {
    if(!active?.enabled){setError("当前类别没有已启用版本");return;}
    prepare("boss.prompt.deactivate",{
      kind,expected_active_version:active.active_version,
    },"停用当前Prompt版本",[
      "类别："+kind,"有效版："+active.prompt_id+" v"+active.prompt_version,
      "停用后新会话不采用；既有业务写入、老板权限均不改变。",
    ]);
  }
  async function commit(){
    if(!pending||!approved||busy||lookupBusy)return;
    const identity=identityRef.current;
    setBusy(true);setError("");
    try{
      const value=await client.requestMutation<Record<string,unknown>>(pending.action,{
        ...pending.fields,client_request_id:pending.key,
      });
      if(!mountedRef.current||identity!==identityRef.current)return;
      if(pending.action==="boss.prompt.save"&&typeof value.prompt_id==="string")
        keyRef.current=value.prompt_id;
      setNotice("已保存当前技术操作："+pending.action+"。重读已持久化配置与版本。");
      setPending(null);setApproved(false);setDirty(false);reload();
    }catch(e){
      if(!mountedRef.current||identity!==identityRef.current)return;
      setError((e instanceof Error?e.message:String(e))+
        "。可能已写入，请优先查询本次幂等回执，不要生成新请求重试。");
    }finally{if(mountedRef.current&&identity===identityRef.current)setBusy(false);}
  }
  async function reconcile(){
    if(!pending||busy||lookupBusy)return;
    const identity=identityRef.current;
    const currentToken=getToken();
    if(!currentToken){clearConfiguration();setError("身份过期，无法核查");return;}
    setLookupBusy(true);setError("");
    try{
      const qs=new URLSearchParams({
        action:pending.action,client_request_id:pending.key,
      });
      const response=await fetch("/api/boss/ui/operation-status?"+qs.toString(),{
        headers:{Authorization:"Bearer "+currentToken},cache:"no-store",
      });
      if(!mountedRef.current||identity!==identityRef.current)return;
      if(response.status===401||response.status===403){
        clearConfiguration();setError("当前版本回执读取失败（HTTP "+response.status+"）");
      }
      if(!response.ok)throw Error("当前版本回执读取失败（HTTP "+response.status+"）");
      const receipt=await response.json() as Receipt;
      if(!mountedRef.current||identity!==identityRef.current)return;
      if(receipt.action!==pending.action||receipt.client_request_id!==pending.key)
        throw Error("当前回执与操作编号不匹配");
      if(receipt.outcome==="RECORDED"){
        if(pending.action==="boss.prompt.save"&&typeof receipt.result?.prompt_id==="string")
          keyRef.current=receipt.result.prompt_id;
        setNotice("已从数据库确认本次技术动作完成，现核对启用与采用状态。");
        setPending(null);setApproved(false);setDirty(false);reload();
      }else if(receipt.outcome==="NOT_FOUND_IN_CURRENT_STORE"){
        setError("当前未发现回执，不代表绝对未执行。请重读技术配置并使用同编号重试。");
        reload();
      }else throw Error("无法确定原操作结果");
    }catch(e){if(mountedRef.current&&identity===identityRef.current)setError(e instanceof Error?e.message:String(e));}
    finally{if(mountedRef.current&&identity===identityRef.current)setLookupBusy(false);}
  }
  return <div className="boss-prompt-workspace">
    <div className="boss-workspace-toolbar">
      <div className="boss-workspace-note">
        <span className="boss-tag boss-tag-amber">MAINTAINER · A05</span>
        <span>Prompt 版本 · 技术指导不扩大本人业务授权</span>
      </div>
      <button type="button" className="boss-btn" disabled={loading||busy||lookupBusy||!!pending||dirty} onClick={reload}>
        {loading?<Loader2 size={15} className="boss-spin"/>:<RefreshCw size={15}/>} 重读正式版本
      </button>
    </div>
    {error&&<div className="boss-status boss-status-error" role="alert"><AlertCircle size={16}/>{error}</div>}
    {notice&&<div className="boss-status boss-status-ok" role="status"><CheckCircle2 size={16}/>{notice}</div>}
    {loading&&<div className="boss-status" role="status"><Loader2 className="boss-spin" size={16}/> 正在获取已授权技术配置…</div>}
    {dirty&&stale&&<p role="alert" className="boss-status boss-status-warn">当前编辑版本与已读取版本不同，请取消编辑后重新选择。</p>}
    <div className="boss-prompt-columns">
      <aside className="boss-column"><V7Panel title="内容目录"><nav className="boss-prompt-directory" aria-label="Prompt内容目录">{KINDS.map(row=><button type="button" key={row.id} className="boss-btn" aria-current={row.id===kind?"page":undefined} disabled={busy||lookupBusy||!!pending} onClick={()=>changeKind(row.id)}>{row.label}<small>{data?.drafts.filter(item=>item.kind===row.id).length??"待查询"}</small></button>)}<button type="button" className="boss-btn" onClick={showAdoption}>启用版本</button></nav><p className="boss-v7-note">草稿、启用版本与实际采用记录分别显示。</p><Detail label="当前类别" value={KINDS.find(row=>row.id===kind)?.label}/><Detail label="当前草稿" value={prompt?.version??"尚未保存"}/></V7Panel></aside>
      <div className="boss-column">
        <section className="boss-panel">
          <div className="boss-panel-head"><h2>版本内容</h2><small>{dirty?"未保存修改":prompt?`v${prompt.version}`:"新建草稿"}</small></div>
          <V7Tabs label="Prompt版本内容" value={tab} onChange={setTab} items={[{id:"content",title:"内容"},{id:"tasks",title:"适用任务"},{id:"sources",title:"引用资料"},{id:"changes",title:"变更说明"}]}/>
          <label className="boss-label" htmlFor="boss-prompt-select">当前类别已保存的版本</label>
          <select className="boss-single-input" id="boss-prompt-select"
            value={chosen} disabled={unavailable} onChange={e=>selectPrompt(e.target.value)}>
            <option value="">新建未保存草稿</option>
            {candidates.map(row=><option key={row.prompt_id} value={row.prompt_id}>
              {row.title} · v{row.version} · {row.validation_status}
            </option>)}
          </select>
          <fieldset className="boss-v7-form-fieldset" disabled={unavailable}>
          <div hidden={tab!=="content"}>
            <label className="boss-field">Prompt 标题<input value={title} maxLength={120}
              onChange={e=>{setTitle(e.target.value);setDirty(true);}}
              placeholder="秘书职责、表达风格或任务约束"/></label>
          <label className="boss-label" htmlFor="boss-prompt-text">版本正文（20—5000 字）</label>
          <textarea id="boss-prompt-text" rows={12} maxLength={5000} value={body}
            onChange={e=>{setBody(e.target.value);setDirty(true);}}
            placeholder="填写当前类别的技术指导内容"/>
          </div>
          <div hidden={tab!=="tasks"}><Detail label="适用类别" value={KINDS.find(row=>row.id===kind)?.label}/><Detail label="启用采用规则" value={active?.adoption_policy}/><Detail label="当前启用内容" value={active?.enabled?`${active.prompt_id} · v${active.prompt_version}`:data?"当前类别尚未启用":null}/><p className="boss-v7-note">新任务按当前启用配置和有效来源组装上下文。具体任务约束通过当前类别正文表达，业务动作仍检查本人授权。</p><button type="button" className="boss-btn" onClick={()=>onNavigate("A06")}>查看SOP与Skills</button></div>
          <div hidden={tab!=="sources"}><label className="boss-field">获准知识来源 ID（逗号分隔）<input value={sources} onChange={e=>{setSources(e.target.value);setDirty(true);}} placeholder="可留空，最多5项"/></label>{prompt?.source_refs.map(row=><Detail key={row.source_id} label={row.source_id} value={"已保存引用 v"+row.version}/>)}{!prompt?.source_refs.length&&<V7Empty title="当前保存版本没有来源引用"/>}<button type="button" className="boss-btn" onClick={()=>onNavigate("A07")}>查看获准资料目录</button></div>
          <div hidden={tab!=="changes"}>
          <label className="boss-label" htmlFor="boss-prompt-change">变更说明</label>
          <textarea id="boss-prompt-change" rows={4} maxLength={360} value={changeNote}
            onChange={e=>{setChangeNote(e.target.value);setDirty(true);}}
            placeholder="说明本次版本修改的范围和理由。"/>
          <Detail label="最近保存时间" value={prompt?.updated_at}/><button type="button" className="boss-btn" disabled={!prompt||!previous} onClick={()=>setCompareOpen(true)}>查看保存版本差异</button>
          </div>
          </fieldset>
          <div className="boss-actions">
            <button type="button" className="boss-btn" disabled={unavailable||stale} onClick={save}>
              <ClipboardCheck size={15}/> 保存新草稿版本
            </button>
            <button type="button" className="boss-btn" disabled={unavailable||!prompt||dirty||stale}
              onClick={validate}><FileSearch size={15}/> 静态校验当前版本</button>
            <button type="button" className="boss-btn boss-btn-primary"
              disabled={unavailable||!prompt||dirty||stale||prompt.validation_status!=="VALIDATED_STATIC_ONLY"}
              onClick={activate}><WandSparkles size={15}/> 启用已校验版本</button>
            <button type="button" className="boss-btn" disabled={unavailable||dirty||!active?.enabled}
              onClick={deactivate}><Square size={15}/> 停用当前类别</button>
          </div>
          <div className="boss-status boss-status-warn"><AlertCircle size={16}/>
            草稿保存、结构校验、启用和实际采用各自记录。技术维护不能授权老板业务动作。
          </div>
        </section>
      </div>
      <aside className="boss-column">
        <V7Panel title="来源与依据"><Detail label="版本差异" value={prompt&&previous?`v${previous.version} → v${prompt.version}`:"尚无可比较版本"}/><button type="button" className="boss-btn" disabled={!prompt||!previous} onClick={()=>setCompareOpen(true)}>查看版本差异</button><Detail label="工具权限边界" value="服务端检查本人有效授权"/><Detail label="关联评测" value={data?"尚无已通过模型评测记录":null}/><div className="boss-actions"><button type="button" className="boss-btn" onClick={()=>onNavigate("A16")}>查看评测管理</button><button type="button" className="boss-btn" onClick={()=>onNavigate("A09")}>查看工具范围</button></div><details><summary>当前来源采用条件</summary><Detail label="实际检查时间" value={data?.runtime_eligibility.checked_at}/><Detail label="当前启用引用" value={eligibility?.prompt_id?`${eligibility.prompt_id} · v${eligibility.prompt_version}`:data?"没有启用引用":null}/><Detail label="采用条件" value={eligibility?eligibility.future_context_eligible?"符合当前条件":"当前不能采用":null}/>{eligibility?.exclusion_reasons.map(reason=><p key={reason}>{reason}</p>)}{eligibility?.source_status.map(source=><Detail key={source.source_id} label={source.source_id} value={`引用 v${source.pinned_version} · 当前 ${source.current_version??"不可见"} · ${source.validity_state}`}/>)}</details></V7Panel>
        <section ref={adoptionRef} tabIndex={-1} className="boss-panel">
          <div className="boss-panel-head"><h2>版本与实际采用</h2></div>
          <Detail label="当前类别" value={kind}/>
          <Detail label="草稿内容版本" value={prompt?.version}/>
          <Detail label="草稿校验结果" value={prompt?.validation_status}/>
          <Detail label="已启用配置" value={data?active?.enabled?"是":"否":null}/>
          <Detail label="启用内容版本" value={active?.prompt_version}/>
          <Detail label="启用指针版本" value={active?.active_version}/>
          <Detail label="新会话可采用" value={data?active&&data.adoptable_current_ids.includes(active.prompt_id)?"是":"否":null}/>
          <Detail label="真实上下文载入记录" value={active?.runtime_context_adoption}/>
          <Detail label="已观察到载入次数" value={active?.context_load_count}/>
          <Detail label="最近一次载入时间" value={active?.last_context_at}/>
          <Detail label="独立模型评测" value={data?"未执行":null}/>
          <div className="boss-status"><Clock3 size={16}/>
            载入次数来自nanobot上下文Provider的实际记录。模型响应和业务结果在对应运行中核查。
          </div>
        </section>
          <div className="boss-actions">
            <button type="button" className="boss-btn"
              onClick={()=>onNavigate("A08")}>检查实际模型连接</button>
            <button type="button" className="boss-btn"
              onClick={()=>onNavigate("A15")}>查看真实运行记录</button>
          </div>
      </aside>
    </div>
    <footer className="boss-maintainer-actions"><span>{dirty?"当前草稿尚未保存":"Prompt版本与实际采用分别核查"}</span><button type="button" className="boss-btn" disabled={busy||lookupBusy||!!pending||!dirty} onClick={()=>selectPrompt(chosen,true)}>取消编辑</button><button type="button" className="boss-btn" disabled={unavailable||stale} onClick={save}>保存草稿</button><button type="button" className="boss-btn" disabled={unavailable||!prompt||dirty||stale} onClick={validate}>校验</button><button type="button" className="boss-btn boss-btn-primary" disabled={unavailable||!prompt||dirty||stale||prompt.validation_status!=="VALIDATED_STATIC_ONLY"} onClick={activate}>启用</button><button type="button" className="boss-btn" onClick={showAdoption}>查看实际采用</button></footer>
    <Dialog.Root open={compareOpen} onOpenChange={setCompareOpen}><Dialog.Portal><Dialog.Overlay className="boss-v7-dialog-overlay"/><Dialog.Content className="boss-v7-dialog boss-prompt-diff"><Dialog.Title>保存版本差异</Dialog.Title><Dialog.Description>{prompt&&previous?`${prompt.title} · 历史 v${previous.version} / 当前 v${prompt.version}`:"尚无可比较的保存版本"}</Dialog.Description>{prompt&&previous?<><Detail label="历史内容摘要" value={previous.content_sha256}/><Detail label="当前内容摘要" value={prompt.content_sha256}/><div className="boss-prompt-diff-content">{differences.map((part,index)=><section key={index} data-change={part.added?"added":part.removed?"removed":"unchanged"}><strong>{part.added?"新增内容":part.removed?"移除内容":"相同内容"}</strong><pre>{part.value}</pre></section>)}</div></>:<V7Empty title="尚无可比较的历史版本"/>}<div className="boss-actions"><Dialog.Close asChild><button className="boss-btn">关闭比较</button></Dialog.Close></div></Dialog.Content></Dialog.Portal></Dialog.Root>
    {discardIntent&&<div className="boss-confirm-backdrop">
      <section className="boss-confirm" role="dialog" aria-modal="true"
        aria-labelledby="boss-a05-discard-title">
        <h3 id="boss-a05-discard-title"><AlertCircle size={18}/> 未保存修改（D06）</h3>
        <p>当前 Prompt 草稿已编辑但尚未保存。离开后不会保留本次输入，
          服务端仍保持上一次正式保存的内容和版本。</p>
        <div className="boss-actions">
          <button type="button" className="boss-btn" onClick={()=>setDiscardIntent(null)}>
            返回继续编辑
          </button>
          <button type="button" className="boss-btn boss-btn-primary"
            onClick={confirmDiscard}>明确放弃草稿并切换</button>
        </div>
      </section>
    </div>}
    {pending&&<div className="boss-confirm-backdrop">
      <section className="boss-confirm" ref={modalRef} tabIndex={-1} role="dialog" aria-modal="true"
        aria-labelledby="boss-a05-confirm-title">
        <h3 id="boss-a05-confirm-title"><ShieldCheck size={18}/>{pending.title}</h3>
        <p>本次操作绑定当前技术身份、对象内容和版本；后台配置无权代老板执行任务。</p>
        <dl>{pending.details.map((line,i)=><div key={i}><dd>{line}</dd></div>)}</dl>
        <label className="boss-confirm-check">
          <input type="checkbox" checked={approved} disabled={busy}
            onChange={e=>setApproved(e.target.checked)}/>
          <span>我已核对当前配置正文、版本、来源及启停后果。</span>
        </label>
        {error&&<p className="boss-validation-error" role="alert">{error}</p>}
        <div className="boss-actions">
          <button type="button" className="boss-btn" disabled={busy||lookupBusy}
            onClick={()=>setPending(null)}>取消</button>
          <button type="button" className="boss-btn" disabled={busy||lookupBusy}
            onClick={()=>void reconcile()}>
            {lookupBusy&&<Loader2 size={15} className="boss-spin"/>} 核查原请求回执
          </button>
          <button type="button" className="boss-btn boss-btn-primary"
            disabled={busy||lookupBusy||!approved} onClick={()=>void commit()}>
            {busy&&<Loader2 size={15} className="boss-spin"/>} 确认执行
          </button>
        </div>
      </section>
    </div>}
  </div>;
}
