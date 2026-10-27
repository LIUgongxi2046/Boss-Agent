import { useEffect, useRef, useState } from "react";
import { AlertCircle, CheckCircle2, FileSearch, History, Loader2, RefreshCw, Save, ShieldCheck, Square } from "lucide-react";
import {V7Empty,V7Fact,V7Panel} from "./BossV7UI";

type HistoryVersion={history_id:string;method_version:string;content_sha256:string;recorded_at:string;origin:string};
type Draft={draft_version:string;method_version:string;description:string;body:string;content_sha256:string;
  state:string;validation_status:string;change_note:string;missing_tools?:string[];errors?:{code:string;missing?:string[];unknown?:string[];sections?:string[]}[];restored_from:string|null};
type Data={projection:"sop-method-editor";source_type:"RUNTIME_RECORD";external_api_mode:"SIMULATED";sop_id:string;
  current_dependencies:{missing_tools:string[];missing_projections:string[];context_eligible:boolean};
  active:{name:string;version:string;description:string;body:string;content_sha256:string;enabled:boolean};
  draft:Draft|null;history:HistoryVersion[];sections:{heading:string;body:string}[];read_operations:string[];command_operations:string[];
  active_assessment:{missing_tools:string[]};pending_activations:{client_request_id:string;state:string;draft_version:string;prepared_at:string}[];
  global_pending_activations:{client_request_id:string;sop_id:string;state:string;draft_version:string;prepared_at:string}[]};
type HistoryBody=HistoryVersion&{description:string;body:string};
type Pending={action:string;payload:Record<string,unknown>;clientRequestId:string;label:string;details:string[];submitted:boolean};
type Props={getToken:()=>string|null;identityKey:string;mutate:(action:string,payload:Record<string,unknown>)=>Promise<Record<string,unknown>>;
  onNavigate?:(page:"A15",reference?:{sop_id:string})=>void;initialSopId?:string;
  onSopChange?:(sopId:string)=>void;onDirtyChange?:(dirty:boolean)=>void};
const METHODS=["今日工作","经营提醒","经营查询","会前准备","会议纪要","交办跟进","待审材料","沟通","战略研究","人员会面","出行接待","私人安排","历史与记忆"];
function validationLabel(value?:string|null){
  if(value==="VALIDATED_STATIC_ONLY")return "静态校验通过";
  if(value==="NOT_RUN"||value==="INVALID")return value==="INVALID"?"静态校验发现错误":"尚未校验";
  return value??"尚未校验";
}
function stateLabel(value?:string|null){
  if(value==="DRAFT")return "草稿";
  if(value==="ACTIVE")return "已启用";
  return value??"尚未读取";
}

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
  function prepare(action:string,fields:Record<string,unknown>,label:string,details:string[]=[]){
    if(!data){setError("请先加载当前方法");return;}
    setPending({action,payload:{sop_id:sop,...fields},clientRequestId:"sop-"+crypto.randomUUID(),label,details,submitted:false});
    setApproved(false);setError("");setNotice("");
  }
  function save(){
    if(!data)return;
    if(!methodVersion.trim()||!description.trim()||!body.trim()||!note.trim()){
      setError("请填写新方法版本、说明、完整方法正文和变更说明");return;
    }
    prepare("save",{expected_draft_version:data.draft?.draft_version??"0",expected_active_sha256:data.active.content_sha256,
      method_version:methodVersion.trim(),description,body,change_note:note},"保存方法草稿",[
      "保存返回草稿版本；当前启用方法版本不变，保存不同时启用。",
    ]);
  }
  function discardEditing(){
    if(!data)return;
    setMethodVersion(data.draft?.method_version??"");
    setDescription(data.draft?.description??data.active.description);
    setBody(data.draft?.body??data.active.body);
    setNote(data.draft?.change_note??"");
    setDirty(false);setError("");setNotice("已放弃本次编辑；已保存草稿和当前启用方法保持不变。");
  }
  function validateDraft(){
    if(!data?.draft||dirty){setError("请先保存修改并重新读取当前草稿");return;}
    prepare("validate",{expected_draft_version:data.draft.draft_version,expected_content_sha256:data.draft.content_sha256},"校验此草稿",[
      "检查步骤、工具引用、前置条件与必要字段；错误定位到具体步骤。",
      "静态校验通过不代表真实模型执行通过。",
    ]);
  }
  function activateDraft(){
    if(!data?.draft||dirty){setError("请先保存修改并重新读取当前草稿");return;}
    prepare("activate",{expected_draft_version:data.draft.draft_version,expected_content_sha256:data.draft.content_sha256,
      expected_active_sha256:data.active.content_sha256},"启用此版本",[
      "适用任务："+methodLabel(),
      "启用方法版本：v"+data.draft.method_version+"（草稿 v"+data.draft.draft_version+"）",
      "替换当前启用版本：v"+data.active.version+"（"+(data.active.enabled?"已启用":"当前已停用")+"）",
      "静态校验结果："+validationLabel(data.draft.validation_status)+"；静态通过不代表执行通过。",
    ]);
  }
  function enableNative(){
    if(!data)return;
    prepare("enable",{expected_active_sha256:data.active.content_sha256},"启用此方法版本",[
      "启用方法版本：v"+data.active.version,
      "适用任务："+methodLabel()+"（"+sop+"）",
      "当前状态：已停用；启用后下一上下文读取采用此方法。",
    ]);
  }
  function disableNative(){
    if(!data)return;
    prepare("disable",{expected_active_sha256:data.active.content_sha256},"停用此方法",[
      "停用方法版本：v"+data.active.version,
      "受影响任务："+methodLabel()+"（"+sop+"）的新上下文",
      "已有运行继续保留原方法与执行证据；停用不删除历史方法。",
    ]);
  }
  function methodLabel(){return METHODS[Number(sop.slice(3))-1]??sop;}
  async function commit(){
    if(!pending||!approved||busy)return;
    const current=identity.current;const operation={...pending,submitted:true};setPending(operation);setLastOperation(operation);setBusy(true);setError("");
    try{
      const result=await mutate(operation.action,{...operation.payload,client_request_id:operation.clientRequestId});
      if(!alive.current||current!==identity.current)return;
      setPending(null);setLastOperation(null);setApproved(false);setDirty(false);
      if(operation.action==="save"){
        const saved=typeof result.draft_version==="string"?" v"+result.draft_version:"";
        setNotice("已保存方法草稿"+saved+"；当前启用方法版本 v"+(data?.active.version??"待读取")+" 不变，正在重读。");
      }else if(operation.action==="validate"){
        setNotice("静态校验结果："+(typeof result.validation_status==="string"?validationLabel(result.validation_status):"已记录")+"；不表示执行通过，正在重读。");
      }else if(operation.action==="activate"){
        setNotice("启用操作已记录"+(typeof result.method_version==="string"?"，正式方法版本 v"+result.method_version:"")+"；正在重读正式采用状态。");
      }else{
        setNotice("方法状态变更已记录，正在重读正式采用状态。");
      }
      await read();
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
  const globalPending=!!data?.global_pending_activations.length;
  const draft=data?.draft??null;
  const active=data?.active??null;
  const activationBlocker=disabled?"正在读取方法或等待回执，操作暂不可用。":globalPending?"存在待恢复的方法启用操作，先继续或取消原操作。":dirty?"存在未保存修改，先保存或放弃本次编辑。":!draft?"尚未保存方法草稿。":!methodVersion.trim()?"草稿缺少方法版本。":draft.state==="ACTIVE"?"当前草稿版本已经启用。":draft.validation_status!=="VALIDATED_STATIC_ONLY"?"草稿尚未通过静态校验。":(draft.missing_tools?.length??0)>0?"草稿引用的工具尚未注册："+(draft.missing_tools??[]).join("、"):"";
  const nativeEnableBlocker=disabled?"正在读取方法或等待回执，操作暂不可用。":globalPending?"存在待恢复的方法启用操作，先继续或取消原操作。":dirty?"存在未保存修改，先保存或放弃本次编辑。":!data||data.active.enabled?"":data.active_assessment.missing_tools.length>0?"当前方法缺少工具引用："+data.active_assessment.missing_tools.join("、"):data.current_dependencies.missing_projections.length>0?"当前方法缺少工作投影："+data.current_dependencies.missing_projections.join("、"):"";
  const deactivateBlocker=disabled?"正在读取方法或等待回执，操作暂不可用。":globalPending?"存在待恢复的方法启用操作，先继续或取消原操作。":dirty?"存在未保存修改，先保存或放弃本次编辑。":active?.enabled?"":"当前方法已经停用。";
  const saveBlocker=disabled?"正在读取方法或等待回执，操作暂不可用。":!data?"尚未加载当前方法。":dirty?"":"当前没有未保存修改；修改版本、说明、正文或变更说明后才能保存。";
  const validateBlocker=disabled?"正在读取方法或等待回执，操作暂不可用。":!draft?"尚未保存方法草稿。":dirty?"存在未保存修改，先保存新草稿版本。":"";
  const sectionText=(label:string)=>data?.sections.filter(section=>section.heading.includes(label)).map(section=>section.body).join("\n\n")||"当前方法尚未提供此字段";
  return <div className="boss-maintainer-records boss-sop-workspace">
    <div className="boss-workspace-toolbar"><div className="boss-workspace-note"><span className="boss-tag">MAINTAINER · A06</span>
      <span>SOP 与 Skills · 技术配置不授予本人业务权限</span></div>
      {loading&&<div className="boss-actions"><button className="boss-btn" type="button" onClick={cancelRead}>取消本次读取</button></div>}</div>
    {error&&!pending&&<div className="boss-status boss-status-error" role="alert"><AlertCircle size={16}/>{error}</div>}
    {notice&&<div className="boss-status boss-status-ok" role="status"><CheckCircle2 size={16}/>{notice}</div>}
    {loading&&<div className="boss-status" role="status"><Loader2 size={16} className="boss-spin"/>正在读取当前配置</div>}
    <div className="boss-v7-filter-bar boss-maintainer-filters"><label htmlFor="sop-method-select">可选方法目录
      <select id="sop-method-select" className="boss-single-input" value={sop} disabled={disabled} onChange={event=>select(event.target.value)}>
        {METHODS.map((label,index)=>{const id="SOP"+String(index+1).padStart(2,"0");return <option key={id} value={id}>{id} · {label}</option>;})}</select></label>
      <button type="button" className="boss-btn" disabled={disabled} onClick={()=>select(sop,true)}>{loading?"加载中…":"加载所选方法"}</button>
      <span className="boss-helper">当前生效版本：{data?.active.version??"尚未读取"}</span></div>
    <p className="boss-v7-note">选择方法只切换目录，不会自动启用方法。农业资料方法尚未获准方法定义，当前不提供选择。</p>
    {!data&&!loading&&!error&&<V7Empty title="尚未加载所选方法">选择方法后点击“加载所选方法”，读取版本、依赖与采用状态。</V7Empty>}
    {data&&<div className="boss-maintainer-columns"><div className="boss-column"><V7Panel title="流程步骤与执行条件" action={<button type="button" className="boss-btn" disabled={disabled||dirty||!data} onClick={()=>void read()}><RefreshCw size={15}/>{loading?"刷新中…":"刷新采用状态"}</button>}><div className="boss-sop-checks"><V7Fact label="方法步骤">{data?"当前保存正文已读取":"尚未读取"}</V7Fact><V7Fact label="方法依赖">{data?data.current_dependencies.missing_tools.length||data.current_dependencies.missing_projections.length?"存在缺少引用":"引用已经注册":"尚未读取"}</V7Fact><V7Fact label="版本采用">{data?data.current_dependencies.context_eligible?"符合下一上下文条件":"当前不能采用":"尚未读取"}</V7Fact><V7Fact label="引用核查">{data?.draft?validationLabel(data.draft.validation_status):"尚无草稿校验记录"}</V7Fact></div><div className="boss-v7-table-scroll"><table className="boss-v7-table" aria-label="已保存方法步骤与条件"><thead><tr><th>步骤</th><th>触发与输入</th><th>工具引用</th><th>授权条件</th><th>输出与结束条件</th></tr></thead><tbody>{data&&<tr><td><strong>{sop} · 当前保存方法</strong><p>{sectionText("步骤")}</p></td><td>{sectionText("触发")}</td><td>{[...data.read_operations,...data.command_operations].join("\n")||"当前没有工具引用"}</td><td>{sectionText("授权")}</td><td>{sectionText("输出")}</td></tr>}</tbody></table></div>{!data&&<V7Empty title="尚未读取当前方法与执行条件"/>}<p className="boss-v7-note">表格使用服务端解析的完整方法正文和已注册工具引用；当前编辑内容需保存后重新核查。{dirty?"存在未保存修改：刷新采用状态不会覆盖编辑，先保存或放弃本次编辑。":""}</p></V7Panel><section className="boss-panel">
      <div className="boss-panel-head"><h2>责任与质量约束</h2><small>当前方法的草稿编辑区</small></div>
      <p className="boss-helper">适用任务：{methodLabel()}（{sop}）。</p>
      <div className="boss-form-grid"><label>新方法版本<input aria-label="新方法版本" value={methodVersion} disabled={!data||disabled}
        placeholder="填写高于当前生效版本的新版本" onChange={event=>{setMethodVersion(event.target.value);setDirty(true);}}/></label>
        <label>方法说明<input aria-label="方法说明" value={description} disabled={!data||disabled} onChange={event=>{setDescription(event.target.value);setDirty(true);}}/></label></div>
      <p className="boss-helper">版本需要高于当前生效版本；同一个方法只保存一个草稿版本，历史版本不能原地覆盖。</p>
      <label className="boss-label" htmlFor="sop-method-body">方法正文：触发、输入、步骤、工具引用、授权、输出与结束条件</label>
      <textarea id="sop-method-body" rows={16} value={body} disabled={!data||disabled} onChange={event=>{setBody(event.target.value);setDirty(true);}}/>
      <label className="boss-label" htmlFor="sop-method-note">变更说明</label>
      <textarea id="sop-method-note" rows={2} value={note} disabled={!data||disabled} onChange={event=>{setNote(event.target.value);setDirty(true);}}/>
      <div className="boss-actions"><button type="button" className={"boss-btn"+(dirty?" boss-btn-primary":"")} disabled={Boolean(saveBlocker)} onClick={save}><Save size={15}/>保存方法草稿</button>
        <button type="button" className={"boss-btn"+(dirty||!draft||draft.validation_status==="VALIDATED_STATIC_ONLY"?"":" boss-btn-primary")} disabled={Boolean(validateBlocker)} onClick={validateDraft}><FileSearch size={15}/>校验此草稿</button>
        {dirty&&<button type="button" className="boss-btn" disabled={disabled} onClick={discardEditing}>放弃本次编辑</button>}</div>
      {saveBlocker&&<p className="boss-helper">保存方法草稿暂不可用：{saveBlocker}</p>}
      {validateBlocker&&<p className="boss-helper">校验此草稿暂不可用：{validateBlocker}</p>}
      {!saveBlocker&&!validateBlocker&&<p className="boss-helper">保存返回新的草稿版本；校验结果绑定草稿内容，修改并保存后需要重新校验。</p>}
      {dirty&&<p role="status">当前存在未保存修改。</p>}
    </section><details className="boss-sop-history"><summary>方法历史与完整字段</summary><V7Panel title="已保存方法字段">{data?.sections.map((section,index)=><article key={index}><h3>{section.heading}</h3><pre>{section.body}</pre></article>)}{!data&&<V7Empty title="尚未读取方法"/>}</V7Panel><section className="boss-panel"><div className="boss-panel-head"><h2>方法历史</h2><History size={17}/></div>
      <label className="boss-label" htmlFor="sop-history-select">选择历史版本</label>
      <select id="sop-history-select" className="boss-single-input" value={historyId} disabled={disabled} onChange={event=>{setHistoryId(event.target.value);setHistory(null);}}>
        <option value="">请选择当前方法的历史版本</option>{data?.history.map(item=><option key={item.history_id} value={item.history_id}>{item.method_version} · {item.origin} · {item.recorded_at}</option>)}</select>
      <div className="boss-actions"><button className="boss-btn" type="button" disabled={!historyId||disabled} onClick={()=>void showHistory()}>查看历史正文</button>
        <button className="boss-btn" type="button" disabled={!historyId||!data||disabled||!methodVersion.trim()||!note.trim()}
          onClick={()=>prepare("restore",{history_id:historyId,expected_draft_version:data!.draft?.draft_version??"0",expected_active_sha256:data!.active.content_sha256,
            method_version:methodVersion.trim(),change_note:note},"恢复历史为新草稿",[
            "历史正文保存为填写的新方法版本草稿，当前未保存编辑将被替代。",
            "恢复生成新草稿，不原地覆盖历史方法，也不同时启用。",
          ])}>恢复历史为新草稿</button></div>
      {!historyId&&<p className="boss-helper">选择历史版本后可查看正文，或恢复为新草稿。</p>}
      {!!historyId&&(!methodVersion.trim()||!note.trim())&&<p className="boss-helper">恢复历史为新草稿需要填写新方法版本和变更说明。</p>}
      {history&&<article aria-label="历史方法正文"><p>历史版本：{history.method_version}</p><p>内容摘要：{history.content_sha256}</p><pre style={{whiteSpace:"pre-wrap",overflowWrap:"anywhere"}}>{history.body}</pre></article>}
    </section></details></div><aside className="boss-column"><V7Panel title="来源与依据"><V7Fact label="依赖关系">{data?data.current_dependencies.missing_tools.join("、")||"工具引用已经注册":"尚未读取"}</V7Fact><V7Fact label="工作投影">{data?data.current_dependencies.missing_projections.join("、")||"当前投影引用完整":"尚未读取"}</V7Fact><V7Fact label="授权范围">每项业务动作检查本人有效授权</V7Fact><V7Fact label="关联评测">当前方法读取没有执行模型评测</V7Fact><V7Fact label="生效内容摘要">{data?.active.content_sha256??"尚未读取"}</V7Fact><V7Fact label="草稿内容摘要">{data?.draft?.content_sha256??"尚未取得保存草稿"}</V7Fact></V7Panel><section className="boss-panel"><div className="boss-panel-head"><h2>版本启用与状态核查</h2><small>{data?"RUNTIME_RECORD":"尚未读取"}</small></div>
      <div className="boss-kv"><span>当前生效方法版本</span><strong>{data?.active.version??"尚未读取"}</strong></div>
      <div className="boss-kv"><span>当前启用状态</span><strong>{data?(data.active.enabled?"已启用":"已停用"):"尚未读取"}</strong></div>
      <div className="boss-kv"><span>草稿保存版本</span><strong>{data?.draft?.draft_version??"尚无已读取草稿"}</strong></div>
      <div className="boss-kv"><span>草稿方法版本</span><strong>{data?.draft?.method_version??"尚未读取"}</strong></div>
      <div className="boss-kv"><span>草稿状态</span><strong>{data?.draft?stateLabel(data.draft.state):"尚未读取"}</strong></div>
      <div className="boss-kv"><span>静态校验</span><strong>{data?.draft?validationLabel(data.draft.validation_status):"尚未读取"}</strong></div>
      <div className="boss-kv"><span>真实模型采用</span><strong>未验证</strong></div>
      <div className="boss-kv"><span>下一上下文采用条件</span><strong>{!data?"尚未读取":data.global_pending_activations.length?"待恢复，当前不可采用":data.current_dependencies.context_eligible?"可供下一上下文读取":"停用或当前引用缺少"}</strong></div>
      {draft&&draft.state!=="ACTIVE"&&<div className="boss-actions"><button type="button" className={"boss-btn"+(activationBlocker?"":" boss-btn-primary")} disabled={Boolean(activationBlocker)} onClick={activateDraft}><ShieldCheck size={15}/>启用此版本</button></div>}
      {draft&&draft.state==="ACTIVE"&&<p className="boss-helper">草稿 v{draft.draft_version}（方法版本 v{draft.method_version}）已经启用；修改后保存会产生新草稿，历史运行保留原采用版本。</p>}
      {!draft&&<p className="boss-helper">尚未保存方法草稿；保存并校验后才能启用新版本。</p>}
      {activationBlocker&&draft&&draft.state!=="ACTIVE"&&<p className="boss-helper" role="status">启用此版本暂不可用：{activationBlocker}</p>}
      {active&&!active.enabled&&<div className="boss-actions"><button type="button" className="boss-btn" disabled={Boolean(nativeEnableBlocker)} onClick={enableNative}>启用此方法版本 v{active.version}</button></div>}
      {active&&!active.enabled&&nativeEnableBlocker&&<p className="boss-helper" role="status">启用此方法版本暂不可用：{nativeEnableBlocker}</p>}
      {active?.enabled&&<details className="boss-sop-history"><summary>当前启用版本的更多操作</summary><p className="boss-helper">停用后，{methodLabel()}（{sop}）的新上下文不再采用当前方法；已有运行继续保留原方法与执行证据，历史方法不删除。</p><button type="button" className="boss-btn" disabled={Boolean(deactivateBlocker)} onClick={disableNative}><Square size={15}/>停用此方法</button>{deactivateBlocker&&<p className="boss-helper" role="status">停用此方法暂不可用：{deactivateBlocker}</p>}</details>}
      {data&&<><p>当前正文摘要：{data.active.content_sha256}</p><p>草稿摘要：{data.draft?.content_sha256??"尚无草稿"}</p>
        <h3>工具引用与权限</h3><p>读取：{data.read_operations.join("、")}</p><p>命令：{data.command_operations.join("、")||"无业务写入命令"}</p>
        <p>缺少工具：{(data.draft?.missing_tools??data.active_assessment.missing_tools).join("、")||"当前引用已经注册"}</p>
        <p>当前缺少工作投影：{data.current_dependencies.missing_projections.join("、")||"当前投影引用完整"}</p>
        {data.draft?.errors?.map((item,index)=><p role="alert" key={index}>{item.code}：{[...(item.missing??[]),...(item.unknown??[]),...(item.sections??[])].join("、")}</p>)}</>}
      <p>保存、静态校验、启用和模型采用分别记录。启用作用于下一次上下文读取，已有会话与业务结果保持各自状态。</p>
      {onNavigate&&<button className="boss-btn" type="button" onClick={()=>onNavigate("A15",{sop_id:sop})}>查看采用此版本的步骤记录</button>}
      <p className="boss-helper">运行记录当前按方法编号进入A15；正式记录尚未提供方法版本筛选，步骤与产物需要按实际run_id核对。</p>
    </section>{lastOperation&&!pending&&<section className="boss-panel"><h2>原操作查询</h2><p>操作：{lastOperation.action}</p><p>原操作编号：{lastOperation.clientRequestId}</p>
      <button type="button" className="boss-btn" onClick={()=>{setPending(lastOperation);setApproved(false);setError("");}}>查询尚待核查的原操作</button></section>}
      <section className="boss-panel"><div className="boss-panel-head"><h2>待恢复的启用操作</h2></div>
      {data?.global_pending_activations.filter(item=>item.sop_id!==sop).map(item=><div key={item.client_request_id}>
        <p>{item.sop_id} 存在待恢复操作，当前全部新上下文暂停采用。</p>
        <button className="boss-btn" type="button" disabled={disabled} onClick={()=>select(item.sop_id,true)}>查看 {item.sop_id} 待恢复操作</button></div>)}
      {!data?<p>尚未读取</p>:data.pending_activations.length===0?<p>当前没有待恢复操作。</p>:data.pending_activations.map(item=><article key={item.client_request_id}>
        <p>原操作编号：{item.client_request_id}</p><p>草稿版本：{item.draft_version} · {item.state}</p>
        <div className="boss-actions"><button className="boss-btn" type="button" disabled={disabled} onClick={()=>prepare("recover",{activation_request_id:item.client_request_id},"继续原启用操作",["继续原启用操作会完成尚未完成的启用步骤。"])}>继续原启用操作</button>
          <button className="boss-btn" type="button" disabled={disabled} onClick={()=>prepare("cancel",{activation_request_id:item.client_request_id},"取消原启用并恢复此前方法",["取消原启用并恢复此前方法，不删除历史方法与执行证据。"])}>取消原启用</button></div></article>)}</section></aside></div>}
    {(pending||discard)&&<div className="boss-confirm-backdrop"><section ref={modalRef} className="boss-confirm" role="dialog" aria-modal="true" aria-labelledby="sop-modal-title" tabIndex={-1}>
      <h3 id="sop-modal-title">{pending?.label??"放弃本次编辑"}</h3>
      {discard?<><p>当前未保存修改将被清理，数据库与当前生效方法保持现有状态。</p><div className="boss-actions">
        <button className="boss-btn" type="button" onClick={()=>setDiscard(null)}>继续编辑</button><button className="boss-btn boss-btn-primary" type="button"
          onClick={()=>{const next=discard;setDiscard(null);clear();setSop(next.sop);if(next.reload)void read(next.sop);}}>放弃本次编辑并切换</button></div></>:pending&&<>
        <p>方法：{sop} · {methodLabel()} · 请求编号：{pending.clientRequestId}</p><p>操作仅更改技术方法配置，不授予老板业务权限。</p>
        <p>当前启用版本：v{data?.active.version??"尚未读取"}（{data?.active.enabled?"已启用":"已停用"}） · 草稿版本：{data?.draft?`v${data.draft.draft_version} / 方法 v${data.draft.method_version}`:"尚无草稿"}</p>
        {pending.details.map((line,index)=><p key={index}>{line}</p>)}
        {error&&<div className="boss-status boss-status-error" role="alert">{error}</div>}
        <label className="boss-confirm-check"><input type="checkbox" checked={approved} disabled={busy} onChange={event=>setApproved(event.target.checked)}/>已核查当前方法、版本和操作范围</label>
        <div className="boss-actions"><button className="boss-btn" type="button" disabled={busy} onClick={()=>{const submitted=pending.submitted;setPending(null);setApproved(false);if(submitted){setDirty(false);void read();}}}>{pending.submitted?"结束本次等待并重读":"取消本次操作"}</button>
          <button className="boss-btn boss-btn-primary" type="button" disabled={busy||!approved} onClick={()=>void commit()}>{busy?"正在处理":"确认执行技术操作"}</button>
          <button className="boss-btn" type="button" disabled={busy} onClick={()=>void reconcile()}>查询原操作回执</button></div>
        {pending.submitted&&<p>本次请求已经提交。关闭等待不会撤销已执行步骤，结果需要查询原操作回执。</p>}
      </>}
    </section></div>}
  </div>;
}
