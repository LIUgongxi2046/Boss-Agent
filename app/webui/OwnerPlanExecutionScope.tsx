import {useEffect,useRef,useState} from "react";
import {useClient} from "@/providers/ClientProvider";
import type {OwnerPlan} from "./BossOwnerPlans";
import {RequiredOutputs} from "./RequiredOutputs";
import type {MethodSelection,RequiredOutput} from "./upgrade2-run-client";

const LIMITS=[
  ["model_requests","模型请求次数（次）"],["rounds","执行轮数（轮）"],["tools","工具调用次数（次）"],["seconds","执行时间（秒）"],
  ["concurrency","并发数量（个）"],["context_tokens","上下文数量（token）"],["files","文件数量（个）"],["file_bytes","单个文件大小上限（字节）"],
  ["open_files","单进程打开文件描述符上限（个，至少16）"],["cpu_seconds","单进程 CPU 时间上限（秒）"],
] as const;
type PlanPreview={preview_id:string;plan_id:string;expected_version:string;content_version:string;payload_sha256:string;payload:{purpose:string;event_ids:string[];event_versions:Record<string,string>;timezone:string;not_before:string;conversation_id:string;source_refs:string[];budget:Record<string,number>;stop_conditions:{business_until:string};scope_proof:unknown;required_outputs:RequiredOutput[];method_selection:MethodSelection}};
type PendingExpectation={decision?:"CONFIRM"|"REJECT";version?:string;authorization_id?:string};
type PlanMethod=MethodSelection&{name:string;status:"AVAILABLE"|"UNAVAILABLE";reasons:string[];missing_native_tools:string[];missing_runtime_tools:string[];missing_projections:string[]};

export function OwnerPlanExecutionScope({plan,disabled,onDirtyChange,onReload}:{plan:OwnerPlan;disabled:boolean;onDirtyChange:(dirty:boolean)=>void;onReload:()=>void}){
  const {getToken,token}=useClient();
  const [conversation,setConversation]=useState("");
  const [sources,setSources]=useState("");
  const [until,setUntil]=useState("");
  const [limits,setLimits]=useState<Record<string,string>>({});
  const [outputs,setOutputs]=useState<RequiredOutput[]>([]);
  const [method,setMethod]=useState<MethodSelection|null>(null);
  const [methods,setMethods]=useState<PlanMethod[]|null>(null);
  const [dirty,setDirty]=useState(false);
  const [preview,setPreview]=useState<PlanPreview|null>(null);
  const [authorization,setAuthorization]=useState("");
  const [busy,setBusy]=useState(false);
  const [pending,setPending]=useState("");
  const [pendingPreview,setPendingPreview]=useState("");
  const [pendingAction,setPendingAction]=useState("");
  const [pendingExpectation,setPendingExpectation]=useState<PendingExpectation>({});
  const [notice,setNotice]=useState("");
  const [error,setError]=useState("");
  const epoch=useRef(0);
  const storageKey="boss-plan-execution-pending:"+plan.plan_id;
  function readPending(){
    const raw=localStorage.getItem(storageKey);
    if(raw){const saved=JSON.parse(raw) as {id:string;preview:string;action:string;expectation?:PendingExpectation};if(!saved.id||!saved.preview||!['DECISION','BIND'].includes(saved.action))throw new Error("原计划请求记录无效");return saved;}
    return {id:sessionStorage.getItem(storageKey)??"",preview:sessionStorage.getItem(storageKey+":preview")??"",action:sessionStorage.getItem(storageKey+":action")??""};
  }
  function showPending(){const saved=readPending();setPending(saved.id);setPendingPreview(saved.preview);setPendingAction(saved.action);setPendingExpectation("expectation" in saved&&saved.expectation?saved.expectation:{});}
  async function reserve(id:string,previewId:string,action:string,expectation:PendingExpectation,current:number){
    if(!navigator.locks)throw new Error("当前环境不支持跨窗口请求保护");
    await navigator.locks.request(storageKey,()=>{if(current!==epoch.current)throw new Error("本人身份已经变化");if(readPending().id)throw new Error("已有待核查的原计划请求");localStorage.setItem(storageKey,JSON.stringify({id,preview:previewId,action,expectation}));});
    showPending();
  }
  async function clearPending(id:string,current:number){
    if(!navigator.locks)throw new Error("当前环境不支持跨窗口请求保护");
    await navigator.locks.request(storageKey,()=>{if(current!==epoch.current)throw new Error("本人身份已经变化");if(readPending().id!==id)throw new Error("原计划请求已经变化");localStorage.removeItem(storageKey);sessionStorage.removeItem(storageKey);sessionStorage.removeItem(storageKey+":preview");sessionStorage.removeItem(storageKey+":action");});
    showPending();
  }
  useEffect(()=>{epoch.current++;setConversation("");setSources("");setUntil("");setLimits({});setOutputs([]);setMethod(null);setMethods(null);setDirty(false);setPreview(null);setAuthorization("");showPending();setBusy(false);setNotice("");setError("");
    const changed=(event:StorageEvent)=>{if(event.key===storageKey)showPending();};window.addEventListener("storage",changed);
    return()=>{epoch.current++;window.removeEventListener("storage",changed);};},[token,storageKey]);
  useEffect(()=>{onDirtyChange(dirty);return()=>onDirtyChange(false);},[dirty,onDirtyChange]);
  function change(){setDirty(true);setPreview(null);setAuthorization("");setNotice("");}
  const refs=sources.split("\n").map(value=>value.trim()).filter(Boolean);
  const validLimits=LIMITS.every(([name])=>/^[1-9][0-9]*$/.test(limits[name]??"")&&Number.isSafeInteger(Number(limits[name]))&&(name!=="open_files"||Number(limits[name])>=16));
  const ready=!!conversation.trim()&&!!until&&refs.length>0&&new Set(refs).size===refs.length&&validLimits&&outputs.length>0&&!!method;
  async function post(path:string,body:object){
    const currentToken=getToken();if(!currentToken)throw new Error("本人身份已经失效，请重新认证");
    const response=await fetch(path,{method:"POST",headers:{Authorization:"Bearer "+currentToken,"Content-Type":"application/json"},body:JSON.stringify(body),credentials:"same-origin",cache:"no-store",redirect:"error"});
    if(!response.ok)throw new Error("请求失败（HTTP "+response.status+"）："+await response.text());
    return await response.json() as unknown;
  }
  async function loadMethods(){
    if(disabled||busy||pending||authorization||!conversation.trim()||!refs.length||new Set(refs).size!==refs.length)return;
    const current=epoch.current;setBusy(true);setError("");setMethod(null);setMethods(null);setPreview(null);
    try{
      const result=await post("/api/v2/owner-plans/execution-methods",{plan_id:plan.plan_id,expected_version:plan.version,conversation_id:conversation.trim(),source_refs:refs}) as {plan_id:string;version:string;conversation_id:string;source_refs:string[];methods:PlanMethod[]};
      if(current!==epoch.current)return;
      if(result.plan_id!==plan.plan_id||result.version!==plan.version||result.conversation_id!==conversation.trim()||JSON.stringify(result.source_refs)!==JSON.stringify(refs)||!Array.isArray(result.methods)||result.methods.some(item=>!item||typeof item.sop_id!=="string"||!item.sop_id||typeof item.name!=="string"||!item.name||typeof item.version!=="string"||!item.version||!/^[0-9a-f]{64}$/.test(item.content_sha256)||!["AVAILABLE","UNAVAILABLE"].includes(item.status)||![item.reasons,item.missing_native_tools,item.missing_runtime_tools,item.missing_projections].every(values=>Array.isArray(values)&&values.every(value=>typeof value==="string")))||new Set(result.methods.map(item=>item.sop_id)).size!==result.methods.length)throw new Error("计划方法目录不可核查");
      setMethods(result.methods);
    }catch(failure){if(current===epoch.current)setError(failure instanceof Error?failure.message:String(failure));}
    finally{if(current===epoch.current)setBusy(false);}
  }
  async function createPreview(){
    if(disabled||!ready||busy||pending)return;const current=epoch.current;setBusy(true);setError("");setNotice("");setPreview(null);setAuthorization("");
    try{
      const budget=Object.fromEntries(LIMITS.map(([name])=>[name,Number(limits[name])]));
      const result=await post("/api/v2/owner-plans/execution-preview",{plan_id:plan.plan_id,expected_version:plan.version,conversation_id:conversation.trim(),source_refs:refs,budget,stop_conditions:{business_until:until+":00+08:00"},required_outputs:outputs,method_selection:method}) as PlanPreview;
      if(current!==epoch.current)return;
      if(result.plan_id!==plan.plan_id||result.expected_version!==plan.version||typeof result.content_version!=="string"||typeof result.preview_id!=="string"||!/^[0-9a-f]{64}$/.test(result.payload_sha256)||!result.payload||result.payload.purpose!==plan.purpose||JSON.stringify(result.payload.event_ids)!==JSON.stringify(plan.event_ids)||result.payload.timezone!==plan.timezone||result.payload.not_before!==plan.not_before||result.payload.conversation_id!==conversation.trim()||JSON.stringify(result.payload.source_refs)!==JSON.stringify(refs)||LIMITS.some(([name])=>result.payload.budget?.[name]!==budget[name])||result.payload.stop_conditions?.business_until!==until+":00+08:00"||JSON.stringify(result.payload.required_outputs)!==JSON.stringify(outputs)||!method||result.payload.method_selection?.sop_id!==method.sop_id||result.payload.method_selection?.version!==method.version||result.payload.method_selection?.content_sha256!==method.content_sha256||!result.payload.scope_proof)throw new Error("服务端预览与当前范围不一致");
      setPreview(result);
    }catch(failure){if(current===epoch.current)setError(failure instanceof Error?failure.message:String(failure));}
    finally{if(current===epoch.current)setBusy(false);}
  }
  async function decide(decision:"CONFIRM"|"REJECT"){
    if(disabled||!preview||busy||pending||!getToken())return;const current=epoch.current,id="plan-decision-"+crypto.randomUUID();
    setBusy(true);setError("");
    try{
      await reserve(id,preview.preview_id,"DECISION",{decision},current);if(current!==epoch.current)return;
      const result=await post("/api/v2/owner-plans/execution-decision",{preview_id:preview.preview_id,payload_sha256:preview.payload_sha256,decision,client_request_id:id}) as {preview_id:string;decision:string;authorization_id:string|null};
      if(current!==epoch.current)return;
      if(result.preview_id!==preview.preview_id||result.decision!==decision||decision==="CONFIRM"&&(!result.authorization_id||typeof result.authorization_id!=="string")||decision==="REJECT"&&result.authorization_id!==null)throw new Error("本人决定回执不一致");
      await clearPending(id,current);if(current!==epoch.current)return;setAuthorization(result.authorization_id??"");setNotice(decision==="CONFIRM"?"本人确认已记录，请继续绑定执行范围。":"本人拒绝已记录。");
      if(decision==="REJECT")setPreview(null);
    }catch(failure){if(current===epoch.current)setError((failure instanceof Error?failure.message:String(failure))+"。请保留原操作编号并查询原决定回执。");}
    finally{if(current===epoch.current)setBusy(false);}
  }
  async function bind(){
    if(disabled||!preview||!authorization||busy||pending||!getToken())return;const current=epoch.current,id="plan-bind-"+crypto.randomUUID();
    setBusy(true);setError("");
    try{
      await reserve(id,preview.preview_id,"BIND",{version:preview.content_version,authorization_id:authorization},current);if(current!==epoch.current)return;
      const result=await post("/api/v2/owner-plans/execution-binding",{client_request_id:id,plan_id:preview.plan_id,expected_version:preview.expected_version,conversation_id:preview.payload.conversation_id,source_refs:preview.payload.source_refs,budget:preview.payload.budget,stop_conditions:preview.payload.stop_conditions,required_outputs:preview.payload.required_outputs,method_selection:preview.payload.method_selection,authorization_id:authorization}) as {plan_id:string;version:string;authorization_id:string;state:string};
      if(current!==epoch.current)return;
      if(result.plan_id!==preview.plan_id||result.version!==preview.content_version||result.authorization_id!==authorization||result.state!=="ACTIVE")throw new Error("计划绑定回执不一致");
      await clearPending(id,current);if(current!==epoch.current)return;setPreview(null);setAuthorization("");setDirty(false);setNotice("执行范围已经绑定，正在重新读取计划。当前调度执行条件仍需核查。");onReload();
    }catch(failure){if(current===epoch.current)setError((failure instanceof Error?failure.message:String(failure))+"。请保留原操作编号并查询原绑定回执。");}
    finally{if(current===epoch.current)setBusy(false);}
  }
  async function readReceipt(){
    if(!pending||!pendingPreview||!['DECISION','BIND'].includes(pendingAction)||busy)return;
    const current=epoch.current;const currentToken=getToken();if(!currentToken){setError("本人身份已经失效，请重新认证");return;}
    const operation=pendingAction==="DECISION"?"decision":"binding";
    setBusy(true);setError("");
    try{
      const response=await fetch("/api/v2/owner-plans/"+encodeURIComponent(plan.plan_id)+"/execution-receipts/"+operation+"/"+encodeURIComponent(pending),{headers:{Authorization:"Bearer "+currentToken},credentials:"same-origin",cache:"no-store",redirect:"error"});
      if(!response.ok)throw new Error(response.status===404?"当前没有原请求回执，请保留编号继续核查。":"原请求查询失败（HTTP "+response.status+"）："+await response.text());
      const value=await response.json() as {plan_id:string;client_request_id:string;operation:string;receipt:{preview_id?:string;decision?:string;authorization_id?:string|null;plan_id?:string;version?:string;state?:string}};
      if(current!==epoch.current)return;
      if(value.plan_id!==plan.plan_id||value.client_request_id!==pending||value.operation!==operation||!value.receipt)throw new Error("原请求回执不一致");
      if(operation==="decision"){
        const receipt=value.receipt;
        if(!pendingExpectation.decision)throw new Error("原请求缺少决定信息，请保留编号并核查本人决定。");
        if(receipt.preview_id!==pendingPreview||receipt.decision!==pendingExpectation.decision||receipt.decision==="CONFIRM"&&(!receipt.authorization_id||typeof receipt.authorization_id!=="string")||receipt.decision==="REJECT"&&receipt.authorization_id!==null)throw new Error("本人决定回执不一致");
        await clearPending(pending,current);if(current!==epoch.current)return;
        if(receipt.decision==="CONFIRM"&&preview?.preview_id===pendingPreview){setAuthorization(receipt.authorization_id!);setNotice("本人确认已重读，请继续绑定执行范围。");}
        else{setPreview(null);setAuthorization("");setNotice(receipt.decision==="REJECT"?"本人拒绝已重读。":"本人确认已重读；当前预览未保留，请重新核查范围及授权有效性。");}
      }else{
        const receipt=value.receipt;
        if(!pendingExpectation.version||!pendingExpectation.authorization_id)throw new Error("原请求缺少绑定版本或授权信息，请保留编号并核查计划。");
        if(receipt.plan_id!==plan.plan_id||receipt.version!==pendingExpectation.version||receipt.authorization_id!==pendingExpectation.authorization_id||receipt.state!=="ACTIVE")throw new Error("原绑定回执不一致");
        await clearPending(pending,current);if(current!==epoch.current)return;
        setPreview(null);setAuthorization("");setDirty(false);setNotice("执行范围绑定回执已重读，正在重新读取计划。当前调度执行条件仍需核查。");onReload();
      }
    }catch(failure){if(current===epoch.current)setError(failure instanceof Error?failure.message:String(failure));}
    finally{if(current===epoch.current)setBusy(false);}
  }
  return <section className="boss-panel" aria-label="计划执行范围">
    <div className="boss-panel-head"><h2>计划执行范围与本人决定</h2></div>
    <p>计划：{plan.purpose} · {plan.plan_id} · 版本 {plan.version}</p>
    <p>计划时间：{plan.not_before} · {plan.timezone}；关联事项：{plan.event_ids.join("、")}</p>
    {disabled&&<p role="status">当前计划需要重新读取或完成编辑，暂时不能修改执行范围。</p>}
    <fieldset disabled={disabled||busy||!!pending||!!authorization}>
    <label className="boss-label">已订阅会话编号<input className="boss-single-input" value={conversation} onChange={event=>{setConversation(event.target.value);setMethods(null);setMethod(null);change();}}/></label>
    <label className="boss-label">资料来源编号，每行一项<textarea value={sources} onChange={event=>{setSources(event.target.value);setMethods(null);setMethod(null);change();}}/></label>
    <RequiredOutputs value={outputs} onChange={value=>{setOutputs(value);change();}} disabled={disabled||busy||!!pending||!!authorization}/>
    <button className="boss-btn" type="button" disabled={!conversation.trim()||!refs.length||new Set(refs).size!==refs.length} onClick={()=>void loadMethods()}>读取当前可用方法</button>
    {methods&&<label>执行方法<select value={method?.sop_id??""} onChange={event=>{const selected=methods.find(item=>item.sop_id===event.target.value&&item.status==="AVAILABLE");setMethod(selected?{sop_id:selected.sop_id,version:selected.version,content_sha256:selected.content_sha256}:null);change();}}><option value="">请选择方法</option>{methods.map(item=><option key={item.sop_id} value={item.sop_id} disabled={item.status!=="AVAILABLE"}>{item.name} · {item.sop_id} · 版本 {item.version}{item.status!=="AVAILABLE"?" · 不可用":""}</option>)}</select></label>}
    {method&&<p>方法版本 {method.version} · 内容摘要 {method.content_sha256}</p>}
    {methods?.filter(item=>item.status!=="AVAILABLE").map(item=><p key={item.sop_id}>{item.name} 不可用：{[...item.reasons,...item.missing_native_tools,...item.missing_runtime_tools,...item.missing_projections].join("、")}</p>)}
    {!method&&<p role="status">请选择当前可用方法后生成预览。</p>}
    <div className="boss-form-grid">{LIMITS.map(([name,label])=><label key={name}>{label}<input type="number" min={name==="open_files"?"16":"1"} step="1" value={limits[name]??""} onChange={event=>{setLimits({...limits,[name]:event.target.value});change();}}/></label>)}</div>
    <label className="boss-label">停止时间（Asia/Shanghai）<input type="datetime-local" value={until} onChange={event=>{setUntil(event.target.value);change();}}/></label></fieldset>
    <p>服务需要核查当前本人会话订阅、来源范围、计划版本、全部预算和停止时间，再返回完整范围与摘要。</p>
    <p>计划触发仍需满足正式运行条件；文件描述符和 CPU 限额按单个进程核查。</p>
    <button className="boss-btn" type="button" disabled={disabled||!ready||busy||!!pending||!!authorization} onClick={()=>void createPreview()}>生成服务端范围预览</button>
    {dirty&&!authorization&&<button className="boss-btn" type="button" disabled={busy||!!pending} onClick={()=>{setConversation("");setSources("");setUntil("");setLimits({});setOutputs([]);setMethod(null);setMethods(null);setPreview(null);setDirty(false);}}>放弃当前范围填写</button>}
    {preview&&<article aria-label="服务端计划范围预览"><h3>本人核查完整范围</h3><p>预览编号：{preview.preview_id} · 内容摘要：{preview.payload_sha256}</p><pre style={{whiteSpace:"pre-wrap",overflowWrap:"anywhere"}}>{JSON.stringify(preview.payload,null,2)}</pre>
      {!authorization&&<div className="boss-actions"><button className="boss-btn" disabled={disabled||busy||!!pending} onClick={()=>void decide("CONFIRM")}>确认此执行范围</button><button className="boss-btn" disabled={disabled||busy||!!pending} onClick={()=>void decide("REJECT")}>拒绝此执行范围</button></div>}
      {authorization&&<div><p>本人授权编号：{authorization}</p><button className="boss-btn" disabled={disabled||busy||!!pending} onClick={()=>void bind()}>绑定已确认范围</button><button className="boss-btn" disabled={busy||!!pending} onClick={()=>{setAuthorization("");setPreview(null);setNotice("已结束本次范围绑定，已记录的本人授权仍按服务有效期管理。");}}>结束本次绑定</button></div>}</article>}
    {pending&&<div role="status"><p>原操作：{pendingAction} · 操作编号：{pending} · 预览编号：{pendingPreview}。结果尚待核查，需要保持原会话订阅。</p><button className="boss-btn" type="button" disabled={busy||!pendingPreview} onClick={()=>void readReceipt()}>查询原操作回执</button></div>}
    {error&&<p role="alert">{error}</p>}{notice&&<p role="status">{notice}</p>}
  </section>;
}
