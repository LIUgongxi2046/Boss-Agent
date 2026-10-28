import { useCallback, useEffect, useRef, useState } from "react";
import {
  AlertCircle, CheckCircle2, ClipboardCheck, Clock3, FileSearch,
  Loader2, RefreshCw, ShieldCheck, Square, WandSparkles,
} from "lucide-react";
import { useClient } from "@/providers/ClientProvider";
import {diffLines} from "diff";
import * as Dialog from "@radix-ui/react-dialog";
import {V7Empty,V7Panel,V7Tabs} from "./BossV7UI";
import {CurrentRuntimeConfiguration,type EffectiveRuntime} from "./MaintainerCurrentFacts";

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
  effective_runtime:EffectiveRuntime;
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

function validationLabel(value?:string|null){
  if(value==="DRAFT_UNVALIDATED")return "草稿尚未校验";
  if(value==="VALIDATED_STATIC_ONLY")return "静态校验通过";
  return value??"尚未校验";
}
function lineCounts(parts:{added?:boolean;removed?:boolean;value:string}[]){
  let added=0,removed=0;
  for(const part of parts){
    const lines=part.value.split("\n").filter(line=>line.length>0).length;
    if(part.added)added+=lines;
    if(part.removed)removed+=lines;
  }
  return {added,removed};
}
function adoptionLabel(value?:string){
  if(value==="RUNTIME_CONTEXT_PROVIDER_INVOKED")return "已观察到上下文Provider载入";
  if(value==="NOT_OBSERVED")return "尚未观察到载入";
  return value??"尚未读取";
}
function exclusionLabel(value:string){
  const labels:Record<string,string>={
    NOT_CONFIGURED:"当前类别没有启用配置",
    DISABLED:"当前类别已经停用",
    DRAFT_MISSING:"启用指向的草稿不存在",
    DRAFT_VERSION_CHANGED:"启用指向的草稿版本已经变化",
    DRAFT_NOT_VALIDATED:"启用指向的草稿尚未通过静态校验",
    SOURCE_MISSING:"引用资料不存在",
    SOURCE_FORBIDDEN:"引用资料不在当前获准范围",
    SOURCE_EXPIRED:"引用资料已经过期",
    SOURCE_WITHDRAWN:"引用资料已经撤销",
    SOURCE_RECEIVED:"引用资料尚未到生效时间",
    SOURCE_INCOMPLETE:"引用资料缺少有效时间",
    SOURCE_VERSION_CHANGED:"引用资料版本已经变化",
  };
  return labels[value]??value;
}
function validityLabel(value:string){
  const labels:Record<string,string>={
    VALID:"当前有效",EXPIRED:"已经过期",WITHDRAWN:"已经撤销",RECEIVED:"尚未到生效时间",
    INCOMPLETE:"缺少有效时间",MISSING:"资料不存在",FORBIDDEN:"不在获准范围",
  };
  return labels[value]??value;
}

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
  const [diffLeft,setDiffLeft]=useState("");
  const [diffRight,setDiffRight]=useState("");
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
    setBusy(false);setLookupBusy(false);setLoading(false);setNotice("");keyRef.current=null;setDiffLeft("");setDiffRight("");
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
  const versionMap=new Map<string,Prompt>();
  for(const row of data?.revisions??[])if(row.prompt_id===chosen)versionMap.set(row.version,row);
  if(prompt)versionMap.set(prompt.version,prompt);
  const versions=[...versionMap.values()].sort((a,b)=>Number(a.version)-Number(b.version));
  const previous=[...versions].reverse().find(row=>!prompt||row.version!==prompt.version);
  const compareLeft=versionMap.get(diffLeft)??previous??versions[0];
  const compareRight=versionMap.get(diffRight)??prompt??versions[versions.length-1];
  const differences=compareLeft&&compareRight?diffLines(compareLeft.instruction_text,compareRight.instruction_text):[];
  const {added:addedLines,removed:removedLines}=lineCounts(differences);
  const active=data?.active.find(a=>a.kind===kind);
  const candidates=data?.drafts.filter(p=>p.kind===kind)||[];
  const eligibility=data?.runtime_eligibility.items.find(row=>row.kind===kind);
  const kindLabel=KINDS.find(row=>row.id===kind)?.label??kind;
  const stale=!!chosen&&(!prompt||prompt.version!==editingVersion);
  const unavailable=busy||lookupBusy||loading||!!pending||!data;
  const activeSame=!!prompt&&!!active?.enabled&&active.prompt_id===prompt.prompt_id&&active.prompt_version===prompt.version;
  const canCompare=versions.length>=2;

  function versionCount(target:Kind){
    const numbers=new Set<string>();
    for(const row of data?.drafts??[])if(row.kind===target)numbers.add(row.version);
    for(const row of data?.revisions??[])if(row.kind===target)numbers.add(row.version);
    return numbers.size;
  }
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
  function openCompare(){
    const right=prompt?.version??versions[versions.length-1]?.version??"";
    const left=previous?.version??versions.find(row=>row.version!==right)?.version??"";
    setDiffLeft(left);setDiffRight(right);setCompareOpen(true);
  }
  function prepare(action:string,fields:Record<string,unknown>,label:string,scope:string[]){
    setPending({key:"boss-"+crypto.randomUUID(),action,fields,title:label,details:scope});
    setApproved(false);setError("");setNotice("");
  }
  function save() {
    setError("");
    if(!data){setError("配置列表尚未读取");return;}
    if(stale){setError("当前草稿版本已经变化，请放弃本次编辑并重新选择。");return;}
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
    },"保存新草稿版本",[
      "类别："+kindLabel,"ID："+(prompt?.prompt_id||"新建Prompt"),
      "当前版本："+(prompt?.version||"0"),"适用来源："+(sourceIds.join("、")||"没有引用资料"),
      "变更原因："+changeNote,"正文："+body.trim(),
      "保存返回新的草稿版本；当前启用版本不变，不表示校验或运行时采用。维护配置不能扩大老板授权。",
    ]);
  }
  function validate() {
    if(!data){setError("版本列表尚未读取");return;}
    if(!prompt){setError("必须先保存并读取已有草稿");return;}
    if(dirty){setError("存在未保存的改动，先保存新版本");return;}
    prepare("boss.prompt.validate",{
      prompt_id:prompt.prompt_id,expected_version:prompt.version,
      expected_content_sha256:prompt.content_sha256,
    },"对当前Prompt执行静态校验",[
      "Prompt："+prompt.prompt_id+" v"+prompt.version,
      "检查格式、必要字段和当前来源引用；结果不包含模型质量、真实运行或防注入审核结论。",
    ]);
  }
  function activate() {
    if(!data){setError("版本列表尚未读取");return;}
    if(!prompt){setError("先保存草稿并完成静态校验");return;}
    if(dirty){setError("当前有未保存的草稿修改，先保存新草稿版本");return;}
    if(prompt.validation_status!=="VALIDATED_STATIC_ONLY"){
      setError("当前版本尚未通过静态校验");return;
    }
    const counts=previous?lineCounts(diffLines(previous.instruction_text,prompt.instruction_text)):{added:0,removed:0};
    prepare("boss.prompt.activate",{
      prompt_id:prompt.prompt_id,expected_version:prompt.version,
      expected_content_sha256:prompt.content_sha256,
      expected_active_version:active?.active_version||"0",
    },"启用此版本",[
      "适用任务："+kindLabel,
      "当前候选："+prompt.prompt_id+" v"+prompt.version,
      "替代启用版本："+(active?.enabled?active.prompt_id+" v"+active.prompt_version:"当前类别尚未启用"),
      previous?`与上一保存版本 v${previous.version} 相比：新增 ${counts.added} 行、移除 ${counts.removed} 行`:"没有可比较的上一保存版本",
      "独立模型评测："+(data.model_evaluation_completed?"已记录":"尚未执行"),
      "启用只影响以后新调用的 Agent 上下文；实际采用另行记录，不代表已有会话重放或模型执行成功。",
    ]);
  }
  function deactivate() {
    if(!active?.enabled){setError("当前类别没有已启用版本");return;}
    prepare("boss.prompt.deactivate",{
      kind,expected_active_version:active.active_version,
    },"停用当前类别",[
      "类别："+kindLabel,"当前有效版："+active.prompt_id+" v"+active.prompt_version,
      "停用后，"+kindLabel+"类新会话不再采用当前版本；已有运行继续记录原采用版本，历史草稿保留。老板权限不改变。",
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
      if(pending.action==="boss.prompt.save")
        setNotice(typeof value.version==="string"?`已保存草稿版本 v${value.version}；当前启用版本不变，正在重读版本列表。`:"已保存新的草稿版本；当前启用版本不变，正在重读版本列表。");
      else if(pending.action==="boss.prompt.validate")
        setNotice("静态校验结果已记录；静态校验不包含模型质量结论。正在重读版本列表。");
      else if(pending.action==="boss.prompt.activate")
        setNotice("启用操作已记录；正在重读正式启用状态与实际采用记录。");
      else setNotice("停用操作已记录；正在重读正式启用状态与实际采用记录。");
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
  function actionHint(){
    if(!data)return "版本列表尚未读取，先刷新版本列表。";
    if(loading)return "正在读取版本列表…";
    if(pending)return "有待确认的技术操作，完成或取消后才能继续编辑。";
    if(busy||lookupBusy)return "正在处理技术操作，暂不能重复提交。";
    if(stale)return "当前编辑版本与已读取版本不同，先放弃本次编辑并重新选择。";
    if(!dirty)return prompt?"当前没有未保存修改；修改标题、正文或引用后才能保存新的草稿版本。":"填写标题和正文后保存第一个草稿版本。";
    return "保存会生成新的草稿版本，当前启用版本不变；保存后可执行静态校验。";
  }
  function activationHint(){
    if(!prompt)return "保存草稿并通过静态校验后，才显示“启用此版本”。";
    if(activeSame)return "当前版本已经启用；新会话按此版本组装，实际采用记录在右侧。";
    if(prompt.validation_status!=="VALIDATED_STATIC_ONLY")return "当前草稿尚未通过静态校验，校验通过后才能启用。";
    if(dirty)return "存在未保存修改，先保存新草稿版本再校验和启用。";
    return "启用前请在确认框中核对适用任务、替代版本和版本差异。";
  }
  return <div className="boss-prompt-workspace">
    <div className="boss-workspace-toolbar">
      <div className="boss-workspace-note">
        <span className="boss-tag boss-tag-amber">MAINTAINER · A05</span>
        <span>Prompt 版本 · 技术指导不扩大本人业务授权</span>
      </div>
      <div className="boss-actions">
        <button type="button" className="boss-btn" disabled={loading||busy||lookupBusy||!!pending||dirty} onClick={reload}>
          {loading?<Loader2 size={15} className="boss-spin"/>:<RefreshCw size={15}/>} {loading?"刷新中…":"刷新版本列表"}
        </button>
      </div>
    </div>
    {dirty&&<p className="boss-helper">存在未保存编辑：刷新版本列表不会覆盖当前编辑；先保存或放弃本次编辑。</p>}
    {error&&<div className="boss-status boss-status-error" role="alert"><AlertCircle size={16}/>{error}</div>}
    {notice&&<div className="boss-status boss-status-ok" role="status"><CheckCircle2 size={16}/>{notice}</div>}
    {loading&&<div className="boss-status" role="status"><Loader2 className="boss-spin" size={16}/> 正在获取已授权技术配置…</div>}
    {dirty&&stale&&<p role="alert" className="boss-status boss-status-warn">当前编辑版本与已读取版本不同，请放弃本次编辑后重新选择。</p>}
    {!data&&!loading&&!error&&<V7Empty title="尚未读取Prompt版本">点击“刷新版本列表”读取已保存版本与采用状态。</V7Empty>}
    {data&&<CurrentRuntimeConfiguration value={data.effective_runtime}/>}
    {data&&<div className="boss-prompt-columns">
      <aside className="boss-column"><V7Panel title="内容目录"><nav className="boss-prompt-directory" aria-label="Prompt内容目录">{KINDS.map(row=>{const count=versionCount(row.id);const current=data?.active.find(item=>item.kind===row.id);return <button type="button" key={row.id} className="boss-btn" aria-current={row.id===kind?"page":undefined} disabled={busy||lookupBusy||!!pending} onClick={()=>changeKind(row.id)}><span>{row.label}</span><small>{count?`${count} 个已保存版本`:"尚无已保存版本 · 新增"}{current?.enabled?` · 有效 v${current.prompt_version}`:" · 未启用"}</small></button>;})}</nav><p className="boss-v7-note">数量表示已保存版本；草稿、启用版本与实际采用记录分别显示。</p><Detail label="当前类别" value={kindLabel}/><Detail label="当前草稿" value={dirty?"存在未保存修改":prompt?`v${prompt.version} · ${validationLabel(prompt.validation_status)}`:"尚未保存"}/><button type="button" className="boss-btn" onClick={showAdoption}>查看实际采用</button></V7Panel></aside>
      <div className="boss-column">
        <section className="boss-panel">
          <div className="boss-panel-head"><h2>版本内容</h2><small>{dirty?"未保存修改":prompt?`v${prompt.version} · ${validationLabel(prompt.validation_status)}`:"新建草稿"}</small></div>
          <V7Tabs label="Prompt版本内容" value={tab} onChange={setTab} items={[{id:"content",title:"内容"},{id:"tasks",title:"适用任务"},{id:"sources",title:"引用资料"},{id:"changes",title:"变更说明"}]}/>
          <label className="boss-label" htmlFor="boss-prompt-select">当前类别已保存的版本</label>
          <select className="boss-single-input" id="boss-prompt-select"
            value={chosen} disabled={unavailable} onChange={e=>selectPrompt(e.target.value)}>
            <option value="">新建未保存草稿</option>
            {candidates.map(row=><option key={row.prompt_id} value={row.prompt_id}>
              {row.title} · v{row.version} · {validationLabel(row.validation_status)}
            </option>)}
          </select>
          {!loading&&data&&!candidates.length&&<p className="boss-helper">当前类别尚无已保存版本。填写标题与正文后保存，生成第一个草稿版本。</p>}
          <fieldset className="boss-v7-form-fieldset" disabled={unavailable}>
          <div hidden={tab!=="content"}>
            <p className="boss-helper">标题与正文属于同一个草稿版本；保存会生成新版本，历史版本只读。</p>
            <label className="boss-field">Prompt 标题<input value={title} maxLength={120}
              onChange={e=>{setTitle(e.target.value);setDirty(true);}}
              placeholder="秘书职责、表达风格或任务约束"/></label>
          <label className="boss-label" htmlFor="boss-prompt-text">版本正文（20—5000 字）</label>
          <textarea id="boss-prompt-text" rows={12} maxLength={5000} value={body}
            onChange={e=>{setBody(e.target.value);setDirty(true);}}
            placeholder="填写当前类别的技术指导内容"/>
          </div>
          <div hidden={tab!=="tasks"}><Detail label="适用任务" value={kindLabel}/><Detail label="采用优先规则" value={active?.adoption_policy}/><Detail label="当前启用内容" value={active?.enabled?`${active.prompt_id} · v${active.prompt_version}`:data?"当前类别尚未启用":null}/><Detail label="启用内容来源" value={!data?null:active?data.drafts.some(item=>item.prompt_id===active.prompt_id)?"已保存的自定义版本":"内置或已撤回版本，来源待核查":"尚未启用"}/><p className="boss-v7-note">四个页签共用当前这一个草稿版本。新任务按当前启用配置和有效来源组装上下文；具体任务约束通过当前类别正文表达，业务动作仍检查本人授权。</p><button type="button" className="boss-btn" onClick={()=>onNavigate("A06")}>查看SOP与Skills</button></div>
          <div hidden={tab!=="sources"}><label className="boss-field">引用资料：获准知识来源 ID（逗号分隔）<input value={sources} onChange={e=>{setSources(e.target.value);setDirty(true);}} placeholder="可留空，最多5项"/></label><p className="boss-helper">保存时绑定资料当前版本；资料失效或版本变化时服务拒绝保存和启用。</p>{prompt?.source_refs.map(row=>{const status=eligibility?.source_status.find(item=>item.source_id===row.source_id);return <Detail key={row.source_id} label={row.source_id} value={status?`引用 v${status.pinned_version} · 当前 ${status.current_version?`v${status.current_version}`:"不可见"} · ${validityLabel(status.validity_state)}`:`引用 v${row.version} · 当前有效状态尚未读取`}/>;})}{!prompt?.source_refs.length&&<V7Empty title="当前保存版本没有来源引用"/>}<button type="button" className="boss-btn" onClick={()=>onNavigate("A07")}>查看获准资料目录</button></div>
          <div hidden={tab!=="changes"}>
          <label className="boss-label" htmlFor="boss-prompt-change">变更说明</label>
          <textarea id="boss-prompt-change" rows={4} maxLength={360} value={changeNote}
            onChange={e=>{setChangeNote(e.target.value);setDirty(true);}}
            placeholder="说明本次版本修改的范围和理由。"/>
          <Detail label="最近保存时间" value={prompt?.updated_at}/><Detail label="最近校验时间" value={prompt?.validated_at}/>
          </div>
          </fieldset>
          <div className="boss-actions">
            <button type="button" className={"boss-btn"+(dirty?" boss-btn-primary":"")} disabled={unavailable||stale||!dirty} onClick={save}>
              <ClipboardCheck size={15}/> 保存新草稿版本
            </button>
            {prompt&&prompt.validation_status!=="VALIDATED_STATIC_ONLY"&&
              <button type="button" className="boss-btn boss-btn-primary" disabled={unavailable||dirty||stale}
                onClick={validate}><FileSearch size={15}/> 静态校验</button>}
            {prompt&&prompt.validation_status==="VALIDATED_STATIC_ONLY"&&!activeSame&&
              <button type="button" className="boss-btn boss-btn-primary"
                disabled={unavailable||dirty||stale}
                onClick={activate}><WandSparkles size={15}/> 启用此版本</button>}
            {dirty&&<button type="button" className="boss-btn" disabled={busy||lookupBusy||!!pending} onClick={()=>selectPrompt(chosen,true)}>放弃本次编辑</button>}
          </div>
          <p className="boss-helper">{actionHint()}</p>
          <p className="boss-helper">{activationHint()}</p>
          <div className="boss-status boss-status-warn"><AlertCircle size={16}/>
            草稿保存、结构校验、启用和实际采用各自记录。技术维护不能授权老板业务动作。
          </div>
        </section>
      </div>
      <aside className="boss-column">
        <V7Panel title="来源与依据"><Detail label="工具权限边界" value="服务端检查本人有效授权"/><Detail label="关联评测" value={data?data.model_evaluation_completed?"已记录模型评测":"尚无已通过模型评测记录":null}/><div className="boss-actions"><button type="button" className="boss-btn" onClick={()=>onNavigate("A16")}>查看评测管理</button><button type="button" className="boss-btn" onClick={()=>onNavigate("A09")}>查看工具范围</button><button type="button" className="boss-btn" onClick={()=>onNavigate("A08")}>模型连接与验证</button></div><p className="boss-v7-note">评测、工具范围、模型连接与实际运行分别核查；进入A16、A09或A08后按当前标题与版本核对，目标页尚未接收当前Prompt版本参数。</p><details className="boss-sop-history"><summary>当前来源采用条件</summary><Detail label="实际检查时间" value={data?.runtime_eligibility.checked_at}/><Detail label="当前启用引用" value={eligibility?.prompt_id?`${eligibility.prompt_id} · v${eligibility.prompt_version}`:data?"没有启用引用":null}/><Detail label="采用条件" value={eligibility?eligibility.future_context_eligible?"符合当前条件":"当前不能采用":null}/>{eligibility?.exclusion_reasons.map(reason=><p key={reason}>{exclusionLabel(reason)}（{reason}）</p>)}{eligibility?.source_status.map(source=><Detail key={source.source_id} label={source.source_id} value={`引用 v${source.pinned_version} · 当前 ${source.current_version??"不可见"} · ${validityLabel(source.validity_state)}`}/>)}</details></V7Panel>
        <section ref={adoptionRef} tabIndex={-1} className="boss-panel">
          <div className="boss-panel-head"><h2>版本与实际采用</h2><small>{data?.runtime_eligibility.checked_at??"尚未读取"}</small></div>
          <Detail label="当前类别" value={`${kindLabel}（${kind}）`}/>
          <Detail label="草稿内容版本" value={prompt?.version}/>
          <Detail label="草稿校验结果" value={prompt?validationLabel(prompt.validation_status):null}/>
          <Detail label="已启用配置" value={data?active?.enabled?"已启用":"未启用（停用）":null}/>
          <Detail label="启用内容版本" value={active?.prompt_version}/>
          <Detail label="启用指针版本（技术）" value={active?.active_version}/>
          <Detail label="新会话可采用" value={data?active&&data.adoptable_current_ids.includes(active.prompt_id)?"是":"否":null}/>
          <Detail label="真实上下文载入记录" value={active?adoptionLabel(active.runtime_context_adoption):null}/>
          <Detail label="已观察到载入次数" value={active?.context_load_count}/>
          <Detail label="最近一次载入时间" value={active?.last_context_at}/>
          <Detail label="独立模型评测" value={data?data.model_evaluation_completed?"已完成":"未执行":null}/>
          <Detail label="版本差异" value={compareLeft&&compareRight?`v${compareLeft.version} → v${compareRight.version}`:"尚无可比较版本"}/>
          <div className="boss-actions"><button type="button" className="boss-btn" disabled={!canCompare} onClick={openCompare}>查看版本差异</button><button type="button" className="boss-btn" onClick={()=>onNavigate("A15")}>查看采用本版本的运行</button></div>
          {!canCompare&&<p className="boss-helper">当前类别少于两个保存版本，暂时不能比较差异。</p>}
          <div className="boss-status"><Clock3 size={16}/>
            载入次数来自 Boss Agent 上下文 Provider 的实际记录。当前服务未返回最近运行 ID，运行关联需在 A15 按实际 run_id 核对；模型响应和业务结果也在对应运行中核查。
          </div>
          <details className="boss-sop-history"><summary>当前生效版本的更多操作</summary><p className="boss-helper">停用后，{kindLabel}类新会话不再采用已启用版本；已有运行继续记录原采用版本，历史草稿保留。</p>{active?.enabled?<button type="button" className="boss-btn" disabled={unavailable||dirty} onClick={deactivate}><Square size={15}/> 停用当前类别</button>:<p className="boss-helper">当前类别没有已启用版本，无需停用。</p>}{dirty&&<p className="boss-helper">存在未保存修改，先保存或放弃本次编辑。</p>}</details>
        </section>
      </aside>
    </div>}
    <Dialog.Root open={compareOpen} onOpenChange={setCompareOpen}><Dialog.Portal><Dialog.Overlay className="boss-v7-dialog-overlay"/><Dialog.Content className="boss-v7-dialog boss-prompt-diff"><Dialog.Title>查看版本差异</Dialog.Title><Dialog.Description>{prompt?`${prompt.title} · 选择两个准确版本比较内容`:"尚无可比较的保存版本"}</Dialog.Description>{canCompare?<><div className="boss-form-grid"><label>历史版本<select className="boss-single-input" value={compareLeft?.version??""} onChange={event=>setDiffLeft(event.target.value)}>{versions.map(row=><option key={row.version} value={row.version}>v{row.version} · {row.validation_status==="VALIDATED_STATIC_ONLY"?"静态校验通过":"草稿"}</option>)}</select></label><label>当前查看版本<select className="boss-single-input" value={compareRight?.version??""} onChange={event=>setDiffRight(event.target.value)}>{versions.map(row=><option key={row.version} value={row.version}>v{row.version} · {row.validation_status==="VALIDATED_STATIC_ONLY"?"静态校验通过":"草稿"}</option>)}</select></label></div><Detail label="历史内容摘要" value={compareLeft?.content_sha256}/><Detail label="当前内容摘要" value={compareRight?.content_sha256}/><p className="boss-helper">新增 {addedLines} 行，移除 {removedLines} 行。</p>{addedLines+removedLines?<div className="boss-prompt-diff-content">{differences.map((part,index)=><section key={index} data-change={part.added?"added":part.removed?"removed":"unchanged"}><strong>{part.added?"新增内容":part.removed?"移除内容":"相同内容"}</strong><pre>{part.value}</pre></section>)}</div>:<V7Empty title="两个版本内容相同"/>}</>:<V7Empty title="尚无可比较的历史版本"/>}<div className="boss-actions"><Dialog.Close asChild><button className="boss-btn">关闭比较</button></Dialog.Close></div></Dialog.Content></Dialog.Portal></Dialog.Root>
    {discardIntent&&<div className="boss-confirm-backdrop">
      <section className="boss-confirm" role="dialog" aria-modal="true"
        aria-labelledby="boss-a05-discard-title">
        <h3 id="boss-a05-discard-title"><AlertCircle size={18}/> 放弃本次编辑</h3>
        <p>当前 Prompt 草稿已编辑但尚未保存。离开后不会保留本次输入，
          服务端仍保持上一次正式保存的内容和版本。</p>
        <div className="boss-actions">
          <button type="button" className="boss-btn" onClick={()=>setDiscardIntent(null)}>
            返回继续编辑
          </button>
          <button type="button" className="boss-btn boss-btn-primary"
            onClick={confirmDiscard}>放弃本次编辑并切换</button>
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
            onClick={()=>setPending(null)}>取消本次操作</button>
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
