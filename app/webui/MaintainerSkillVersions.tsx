import { useEffect, useRef, useState } from "react";
import { AlertCircle, CheckCircle2, FileSearch, History, Loader2, RefreshCw, Save, ShieldCheck, Square } from "lucide-react";

type HistoryVersion={history_id:string;method_version:string;content_sha256:string;recorded_at:string;origin:string};
type Draft={draft_version:string;method_version:string;description:string;body:string;content_sha256:string;
  state:string;validation_status:string;change_note:string;missing_tools?:string[];errors?:{code:string;missing?:string[];unknown?:string[];sections?:string[]}[];restored_from:string|null};
type Data={projection:"sop-method-editor";source_type:"RUNTIME_RECORD";external_api_mode:"SIMULATED";sop_id:string;
  active:{name:string;version:string;description:string;body:string;content_sha256:string;enabled:boolean};
  draft:Draft|null;history:HistoryVersion[];sections:{heading:string;body:string}[];read_operations:string[];command_operations:string[];
  active_assessment:{missing_tools:string[]};pending_activations:{client_request_id:string;state:string;draft_version:string;prepared_at:string}[];
  global_pending_activations:{client_request_id:string;sop_id:string;state:string;draft_version:string;prepared_at:string}[]};
type HistoryBody=HistoryVersion&{description:string;body:string};
type Pending={action:string;payload:Record<string,unknown>;clientRequestId:string;label:string;submitted:boolean};
type Props={getToken:()=>string|null;identityKey:string;mutate:(action:string,payload:Record<string,unknown>)=>Promise<Record<string,unknown>>;
  onNavigate?:(page:"A15",reference?:{sop_id:string})=>void;initialSopId?:string;
  onSopChange?:(sopId:string)=>void;onDirtyChange?:(dirty:boolean)=>void};
const METHODS=["今日工作","经营提醒","经营查询","会前准备","会议纪要","交办跟进","待审材料","沟通","战略研究","人员会面","出行接待","私人安排","历史与记忆"];

export function MaintainerSkillVersions({getToken,identityKey,mutate,onNavigate,initialSopId,onSopChange,onDirtyChange}:Props){
  const [sop,setSop]=useState(()=>METHODS.some((_,index)=>initialSopId==="SOP"+String(index+1).padStart(2,"0"))?initialSopId!:"SOP03");
  const [data,setData]=useState<Data|null>(null);
  const [methodVersion,setMethodVersion]=useState("");
  const [description,setDescription]=useState("");
  const [body,setBody]=useState("");
  const [note,setNote]=useState("");
  const [dirty,setDirty]=useState(false);
  const [loading,setLoading]=useState(false);
  const [busy,setBusy]=useState(false);
  const [error,setError]=useState("");
  const [notice,setNotice]=useState("");
  const [pending,setPending]=useState<Pending|null>(null);
  const [lastOperation,setLastOperation]=useState<Pending|null>(null);
  const [approved,setApproved]=useState(false);
  const [historyId,setHistoryId]=useState("");
  const [history,setHistory]=useState<HistoryBody|null>(null);
  const [discard,setDiscard]=useState<{sop:string;reload:boolean}|null>(null);
  const identity=useRef({identityKey,getToken,mutate});
  const alive=useRef(true);
  const abort=useRef<AbortController|null>(null);
  const modalRef=useRef<HTMLElement|null>(null);
  if(identity.current.identityKey!==identityKey||identity.current.getToken!==getToken||identity.current.mutate!==mutate)
    identity.current={identityKey,getToken,mutate};

  function clear(){
    abort.current?.abort();identity.current={...identity.current};
    setData(null);setMethodVersion("");setDescription("");setBody("");setNote("");setHistoryId("");setHistory(null);
    setDirty(false);setPending(null);setLastOperation(null);setApproved(false);setDiscard(null);setBusy(false);setLoading(false);setNotice("");
  }
  useEffect(()=>{alive.current=true;return()=>{alive.current=false;abort.current?.abort();};},[]);
  useEffect(()=>{clear();setError("");},[identityKey,getToken,mutate]);
  useEffect(()=>{onDirtyChange?.(dirty);},[dirty,onDirtyChange]);
  useEffect(()=>()=>onDirtyChange?.(false),[onDirtyChange]);
  useEffect(()=>{onSopChange?.(sop);},[sop,onSopChange]);
  useEffect(()=>{
    if(!pending&&!discard)return;
    const origin=document.activeElement instanceof HTMLElement?document.activeElement:null;
    modalRef.current?.focus();
    function keyboard(event:KeyboardEvent){
      if(event.key==="Escape"&&!busy&&!pending?.submitted){setPending(null);setDiscard(null);setApproved(false);}
      if(event.key!=="Tab"||!modalRef.current)return;
      const controls=Array.from(modalRef.current.querySelectorAll<HTMLElement>('button:not([disabled]),input:not([disabled])'));
      if(!controls.length){event.preventDefault();modalRef.current.focus();return;}
      if(event.shiftKey&&document.activeElement===controls[0]){event.preventDefault();controls[controls.length-1].focus();}
      else if(!event.shiftKey&&document.activeElement===controls[controls.length-1]){event.preventDefault();controls[0].focus();}
    }
    document.addEventListener("keydown",keyboard);
    return()=>{document.removeEventListener("keydown",keyboard);origin?.focus();};
  },[pending?.clientRequestId,discard?.sop,busy,pending?.submitted]);

  async function read(next=sop){
    const token=getToken();if(!token){clear();setError("技术维护身份已失效");return;}
    abort.current?.abort();const controller=new AbortController();abort.current=controller;
    const current=identity.current;setLoading(true);setError("");setHistory(null);
    try{
      const response=await fetch("/api/boss/ui/admin/sop-method?"+new URLSearchParams({sop_id:next}),{
        headers:{Authorization:"Bearer "+token},cache:"no-store",signal:controller.signal});
      if(!alive.current||controller.signal.aborted||current!==identity.current)return;
      if(response.status===401||response.status===403){clear();setError("方法读取失败（HTTP "+response.status+"）");return;}
      if(!response.ok)throw Error("方法读取失败（HTTP "+response.status+"）");
      const value=await response.json() as Data;
      if(value.projection!=="sop-method-editor"||value.source_type!=="RUNTIME_RECORD"||value.external_api_mode!=="SIMULATED"||value.sop_id!==next)
        throw Error("方法来源或当前编号不符");
      if(!alive.current||controller.signal.aborted||current!==identity.current)return;
      setData(value);setSop(next);setMethodVersion(value.draft?.method_version??"");
      setDescription(value.draft?.description??value.active.description);setBody(value.draft?.body??value.active.body);
      setNote(value.draft?.change_note??"");setHistoryId("");setDirty(false);
    }catch(failure){if(alive.current&&!controller.signal.aborted&&current===identity.current)setError(failure instanceof Error?failure.message:String(failure));}
    finally{if(alive.current&&current===identity.current&&!controller.signal.aborted)setLoading(false);}
  }
  function select(next:string,reload=false){
    if(dirty){setDiscard({sop:next,reload});return;}
    clear();setSop(next);setError("");if(reload)void read(next);
  }
  function cancelRead(){abort.current?.abort();setLoading(false);setNotice("本次读取已经取消。");}
  function prepare(action:string,fields:Record<string,unknown>,label:string){
    if(!data){setError("请读取当前方法");return;}
    setPending({action,payload:{sop_id:sop,...fields},clientRequestId:"sop-"+crypto.randomUUID(),label,submitted:false});
    setApproved(false);setError("");setNotice("");
  }
  function save(){
    if(!data)return;
    if(!methodVersion.trim()||!description.trim()||!body.trim()||!note.trim()){
      setError("请填写新方法版本、说明、完整方法正文和变更说明");return;
    }
    prepare("save",{expected_draft_version:data.draft?.draft_version??"0",expected_active_sha256:data.active.content_sha256,
      method_version:methodVersion.trim(),description,body,change_note:note},"保存方法草稿");
  }
  function savedAction(action:"validate"|"activate"){
    if(!data?.draft||dirty){setError("请保存修改并重新读取当前草稿");return;}
    prepare(action,{expected_draft_version:data.draft.draft_version,expected_content_sha256:data.draft.content_sha256,
      ...(action==="activate"?{expected_active_sha256:data.active.content_sha256}:{})},action==="activate"?"启用当前已校验方法":"校验当前方法引用");
  }
  async function commit(){
    if(!pending||!approved||busy)return;
    const current=identity.current;const operation={...pending,submitted:true};setPending(operation);setLastOperation(operation);setBusy(true);setError("");
    try{
      await mutate(operation.action,{...operation.payload,client_request_id:operation.clientRequestId});
      if(!alive.current||current!==identity.current)return;
      setPending(null);setLastOperation(null);setApproved(false);setDirty(false);setNotice("技术操作已保存，正在重读当前方法与版本。");await read();
    }catch(failure){
      if(alive.current&&current===identity.current){
        if(typeof failure==="object"&&failure!==null&&"status" in failure&&(failure.status===401||failure.status===403))clear();
        setError((failure instanceof Error?failure.message:String(failure))+"。请查询原操作回执并重读状态。");
      }
    }finally{if(alive.current&&current===identity.current)setBusy(false);}
  }
  async function reconcile(){
    if(!pending||busy)return;
    const current=identity.current;const token=getToken();if(!token){clear();setError("技术维护身份已失效");return;}
    setBusy(true);setError("");
    try{
      const response=await fetch("/api/boss/ui/admin/sop-operation-status?"+new URLSearchParams({action:pending.action,client_request_id:pending.clientRequestId}),{
        headers:{Authorization:"Bearer "+token},cache:"no-store"});
      if(!alive.current||current!==identity.current)return;
      if(response.status===401||response.status===403){clear();setError("方法操作回执读取失败（HTTP "+response.status+"）");return;}
      if(!response.ok)throw Error("方法操作回执读取失败（HTTP "+response.status+"）");
      const receipt=await response.json() as {action:string;client_request_id:string;outcome:string};
      if(!alive.current||current!==identity.current)return;
      if(receipt.action!==pending.action||receipt.client_request_id!==pending.clientRequestId)throw Error("原操作回执编号不符");
      if(receipt.outcome==="RECORDED"||receipt.outcome==="PREPARED"){
        setPending(null);setLastOperation(null);setApproved(false);setDirty(false);setNotice(receipt.outcome==="PREPARED"?"原启用操作需要维护明确继续或取消。":"已确认原操作回执。");await read();
      }else setError("当前未发现原回执，请重读状态并保留本次操作编号。");
    }catch(failure){if(alive.current&&current===identity.current)setError(failure instanceof Error?failure.message:String(failure));}
    finally{if(alive.current&&current===identity.current)setBusy(false);}
  }
  async function showHistory(){
    if(!historyId||loading)return;
    const current=identity.current;const token=getToken();const requested=historyId;
    if(!token){clear();setError("技术维护身份已失效");return;}
    setLoading(true);setError("");setHistory(null);abort.current?.abort();const controller=new AbortController();abort.current=controller;
    try{
      const response=await fetch("/api/boss/ui/admin/sop-history?"+new URLSearchParams({sop_id:sop,history_id:requested}),{
        headers:{Authorization:"Bearer "+token},cache:"no-store",signal:controller.signal});
      if(!alive.current||current!==identity.current||controller.signal.aborted)return;
      if(response.status===401||response.status===403){clear();setError("历史方法读取失败（HTTP "+response.status+"）");return;}
      if(!response.ok)throw Error("历史方法读取失败（HTTP "+response.status+"）");
      const value=await response.json() as HistoryBody;
      if(value.history_id!==requested)throw Error("历史方法编号不符");
      if(alive.current&&current===identity.current&&!controller.signal.aborted)setHistory(value);
    }catch(failure){if(alive.current&&current===identity.current&&!controller.signal.aborted)setError(failure instanceof Error?failure.message:String(failure));}
    finally{if(alive.current&&current===identity.current&&!controller.signal.aborted)setLoading(false);}
  }
  const disabled=loading||busy||pending!==null;
  return <>
    <div className="boss-workspace-toolbar"><div className="boss-workspace-note"><span className="boss-tag">MAINTAINER · A06</span>
      <span>SOP 与 Skills · 技术配置不授予本人业务权限</span></div>
      <div className="boss-actions"><button className="boss-btn" type="button" disabled={disabled} onClick={()=>select(sop,true)}><RefreshCw size={15}/>读取当前方法</button>
        {loading&&<button className="boss-btn" type="button" onClick={cancelRead}>取消本次读取</button>}</div></div>
    {error&&!pending&&<div className="boss-status boss-status-error" role="alert"><AlertCircle size={16}/>{error}</div>}
    {notice&&<div className="boss-status boss-status-ok" role="status"><CheckCircle2 size={16}/>{notice}</div>}
    {loading&&<div className="boss-status" role="status"><Loader2 size={16} className="boss-spin"/>正在读取当前配置</div>}
    <div className="boss-columns"><div className="boss-column"><section className="boss-panel">
      <div className="boss-panel-head"><h2>SOP 与 Skills</h2><small>秘书任务方法</small></div>
      <label className="boss-label" htmlFor="sop-method-select">选择方法</label>
      <select id="sop-method-select" className="boss-single-input" value={sop} disabled={disabled} onChange={event=>select(event.target.value)}>
        {METHODS.map((label,index)=>{const id="SOP"+String(index+1).padStart(2,"0");return <option key={id} value={id}>{id} · {label}</option>;})}</select>
      {!data&&<div className="boss-status">尚未读取当前方法。农业资料方法等待获准方法定义。</div>}
      {data&&<div style={{overflowX:"auto"}}><table aria-label="已保存方法步骤表"><thead><tr><th>方法字段</th><th>已保存正文</th></tr></thead>
        <tbody>{data.sections.map((section,index)=><tr key={index}><th scope="row">{section.heading}</th><td style={{whiteSpace:"pre-wrap",overflowWrap:"anywhere"}}>{section.body}</td></tr>)}</tbody></table></div>}
      <div className="boss-form-grid"><label>新方法版本<input aria-label="新方法版本" value={methodVersion} disabled={!data||disabled}
        placeholder="填写高于当前生效版本的新版本" onChange={event=>{setMethodVersion(event.target.value);setDirty(true);}}/></label>
        <label>方法说明<input aria-label="方法说明" value={description} disabled={!data||disabled} onChange={event=>{setDescription(event.target.value);setDirty(true);}}/></label></div>
      <label className="boss-label" htmlFor="sop-method-body">方法正文：触发、输入、步骤、工具引用、授权、输出与结束条件</label>
      <textarea id="sop-method-body" rows={16} value={body} disabled={!data||disabled} onChange={event=>{setBody(event.target.value);setDirty(true);}}/>
      <label className="boss-label" htmlFor="sop-method-note">变更说明</label>
      <textarea id="sop-method-note" rows={2} value={note} disabled={!data||disabled} onChange={event=>{setNote(event.target.value);setDirty(true);}}/>
      <div className="boss-actions"><button type="button" className="boss-btn" disabled={!data||disabled} onClick={save}><Save size={15}/>保存方法草稿</button>
        <button type="button" className="boss-btn" disabled={!data?.draft||dirty||disabled} onClick={()=>savedAction("validate")}><FileSearch size={15}/>校验当前草稿</button>
        <button type="button" className="boss-btn boss-btn-primary" disabled={!data?.draft||dirty||disabled||data.draft.state==="ACTIVE"||data.draft.validation_status!=="VALIDATED_STATIC_ONLY"||(data.draft.missing_tools?.length??0)>0}
          onClick={()=>savedAction("activate")}><ShieldCheck size={15}/>启用当前草稿</button>
        <button type="button" className="boss-btn" disabled={!data||data.active.enabled||dirty||disabled||data.active_assessment.missing_tools.length>0}
          onClick={()=>prepare("enable",{expected_active_sha256:data!.active.content_sha256},"启用当前原生方法")}>启用当前方法</button>
        <button type="button" className="boss-btn" disabled={!data?.active.enabled||dirty||disabled}
          onClick={()=>prepare("disable",{expected_active_sha256:data!.active.content_sha256},"停用当前方法")}><Square size={15}/>停用当前方法</button></div>
      {dirty&&<p role="status">当前存在未保存修改。</p>}
    </section><section className="boss-panel"><div className="boss-panel-head"><h2>方法历史</h2><History size={17}/></div>
      <label className="boss-label" htmlFor="sop-history-select">选择历史版本</label>
      <select id="sop-history-select" className="boss-single-input" value={historyId} disabled={disabled} onChange={event=>{setHistoryId(event.target.value);setHistory(null);}}>
        <option value="">请选择当前方法的历史版本</option>{data?.history.map(item=><option key={item.history_id} value={item.history_id}>{item.method_version} · {item.origin} · {item.recorded_at}</option>)}</select>
      <div className="boss-actions"><button className="boss-btn" type="button" disabled={!historyId||disabled} onClick={()=>void showHistory()}>查看历史正文</button>
        <button className="boss-btn" type="button" disabled={!historyId||!data||disabled||!methodVersion.trim()||!note.trim()}
          onClick={()=>prepare("restore",{history_id:historyId,expected_draft_version:data!.draft?.draft_version??"0",expected_active_sha256:data!.active.content_sha256,
            method_version:methodVersion.trim(),change_note:note},"恢复历史为新草稿")}>恢复历史为新草稿</button></div>
      {history&&<article aria-label="历史方法正文"><p>历史版本：{history.method_version}</p><p>内容摘要：{history.content_sha256}</p><pre style={{whiteSpace:"pre-wrap",overflowWrap:"anywhere"}}>{history.body}</pre></article>}
    </section></div><div className="boss-column"><section className="boss-panel"><div className="boss-panel-head"><h2>配置与采用状态</h2><small>{data?"RUNTIME_RECORD · 外部依赖 SIMULATED":"尚未读取"}</small></div>
      <div className="boss-kv"><span>当前生效方法版本</span><strong>{data?.active.version??"尚未读取"}</strong></div>
      <div className="boss-kv"><span>当前启用状态</span><strong>{data?(data.active.enabled?"已启用":"已停用"):"尚未读取"}</strong></div>
      <div className="boss-kv"><span>草稿保存版本</span><strong>{data?.draft?.draft_version??"尚无已读取草稿"}</strong></div>
      <div className="boss-kv"><span>草稿方法版本</span><strong>{data?.draft?.method_version??"尚未读取"}</strong></div>
      <div className="boss-kv"><span>草稿状态</span><strong>{data?.draft?.state??"尚未读取"}</strong></div>
      <div className="boss-kv"><span>静态校验</span><strong>{data?.draft?.validation_status??"尚未读取"}</strong></div>
      <div className="boss-kv"><span>真实模型采用</span><strong>未验证</strong></div>
      <div className="boss-kv"><span>下一上下文采用条件</span><strong>{!data?"尚未读取":data.global_pending_activations.length?"待恢复，当前不可采用":data.active.enabled&&data.active_assessment.missing_tools.length===0?"可供下一上下文读取":"停用或工具引用缺少"}</strong></div>
      {data&&<><p>当前正文摘要：{data.active.content_sha256}</p><p>草稿摘要：{data.draft?.content_sha256??"尚无草稿"}</p>
        <h3>工具引用与权限</h3><p>读取：{data.read_operations.join("、")}</p><p>命令：{data.command_operations.join("、")||"无业务写入命令"}</p>
        <p>缺少工具：{(data.draft?.missing_tools??data.active_assessment.missing_tools).join("、")||"当前引用已经注册"}</p>
        {data.draft?.errors?.map((item,index)=><p role="alert" key={index}>{item.code}：{[...(item.missing??[]),...(item.unknown??[]),...(item.sections??[])].join("、")}</p>)}</>}
      <p>保存、静态校验、启用和模型采用分别记录。启用作用于下一次上下文读取，已有会话与业务结果保持各自状态。</p>
      {onNavigate&&<button className="boss-btn" type="button" onClick={()=>onNavigate("A15",{sop_id:sop})}>查看实际步骤记录</button>}
    </section>{lastOperation&&!pending&&<section className="boss-panel"><h2>原操作查询</h2><p>操作：{lastOperation.action}</p><p>原操作编号：{lastOperation.clientRequestId}</p>
      <button type="button" className="boss-btn" onClick={()=>{setPending(lastOperation);setApproved(false);setError("");}}>查询尚待核查的原操作</button></section>}
      <section className="boss-panel"><div className="boss-panel-head"><h2>待恢复的启用操作</h2></div>
      {data?.global_pending_activations.filter(item=>item.sop_id!==sop).map(item=><div key={item.client_request_id}>
        <p>{item.sop_id} 存在待恢复操作，当前全部新上下文暂停采用。</p>
        <button className="boss-btn" type="button" disabled={disabled} onClick={()=>select(item.sop_id,true)}>查看 {item.sop_id} 待恢复操作</button></div>)}
      {!data?<p>尚未读取</p>:data.pending_activations.length===0?<p>当前没有待恢复操作。</p>:data.pending_activations.map(item=><article key={item.client_request_id}>
        <p>原操作编号：{item.client_request_id}</p><p>草稿版本：{item.draft_version} · {item.state}</p>
        <div className="boss-actions"><button className="boss-btn" type="button" disabled={disabled} onClick={()=>prepare("recover",{activation_request_id:item.client_request_id},"继续原启用操作")}>继续原启用操作</button>
          <button className="boss-btn" type="button" disabled={disabled} onClick={()=>prepare("cancel",{activation_request_id:item.client_request_id},"取消原启用并恢复此前方法")}>取消原启用</button></div></article>)}</section></div></div>
    {(pending||discard)&&<div className="boss-confirm-backdrop"><section ref={modalRef} className="boss-confirm" role="dialog" aria-modal="true" aria-labelledby="sop-modal-title" tabIndex={-1}>
      <h3 id="sop-modal-title">{pending?.label??"取消未保存修改"}</h3>
      {discard?<><p>当前未保存修改将被清理，数据库与当前生效方法保持现有状态。</p><div className="boss-actions">
        <button className="boss-btn" type="button" onClick={()=>setDiscard(null)}>继续编辑</button><button className="boss-btn boss-btn-primary" type="button"
          onClick={()=>{const next=discard;setDiscard(null);clear();setSop(next.sop);if(next.reload)void read(next.sop);}}>确认取消修改</button></div></>:pending&&<>
        <p>方法：{sop} · 请求编号：{pending.clientRequestId}</p><p>操作仅更改技术方法配置，不授予老板业务权限。</p>
        <p>草稿保存版本：{String(pending.payload.expected_draft_version??"不适用")} · 方法版本：{String(pending.payload.method_version??data?.draft?.method_version??data?.active.version??"尚未读取")}</p>
        {error&&<div className="boss-status boss-status-error" role="alert">{error}</div>}
        {pending.action==="restore"&&<p>历史正文将保存为填写的新方法版本草稿，当前未保存编辑将被替代。</p>}
        <label className="boss-confirm-check"><input type="checkbox" checked={approved} disabled={busy} onChange={event=>setApproved(event.target.checked)}/>已核查当前方法、版本和操作范围</label>
        <div className="boss-actions"><button className="boss-btn" type="button" disabled={busy} onClick={()=>{const submitted=pending.submitted;setPending(null);setApproved(false);if(submitted){setDirty(false);void read();}}}>{pending.submitted?"结束本次等待并重读":"取消未提交操作"}</button>
          <button className="boss-btn boss-btn-primary" type="button" disabled={busy||!approved} onClick={()=>void commit()}>{busy?"正在处理":"确认执行技术操作"}</button>
          <button className="boss-btn" type="button" disabled={busy} onClick={()=>void reconcile()}>查询原操作回执</button></div>
        {pending.submitted&&<p>本次请求已经提交。关闭等待不会撤销已执行步骤，结果需要查询原操作回执。</p>}
      </>}
    </section></div>}
  </>;
}
