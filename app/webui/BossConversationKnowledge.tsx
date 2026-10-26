import {useEffect,useRef,useState} from "react";
import * as Dialog from "@radix-ui/react-dialog";
import {BookOpen,Search} from "lucide-react";
import {useClient} from "@/providers/ClientProvider";

type SourceRef={source_id:string;version:string};
type Source=SourceRef&{title:string;source_type:"SIMULATED"|"PUBLIC_SOURCE"|"RUNTIME_RECORD";author:string|null;published_at:string|null;validity_state:string;allowed:boolean;reason:string|null};
type Catalogue={projection:"conversation-sources";chat_id:string;session_id:string;execution_namespace:string;dataset_version:string;context_version:string;catalogue_version:string;query:string;sources:Source[];selected_sources:SourceRef[];coverage:"COMPLETE"|"PARTIAL";can_bind:boolean;unavailable_reason:string|null;business_authorization_granted:false;business_mutation_performed:false};
type Receipt={client_request_id:string;chat_id:string;session_id:string;outcome:"RECORDED"|"REJECTED"|"UNKNOWN";binding_id?:string;context_version?:string;source_refs?:SourceRef[];reason?:string;business_authorization_granted:false;business_mutation_performed:false;write_performed_by_lookup?:false};
type Props={chatId:string|null;active:boolean;onSource:(id:string,version?:string)=>void};
const pendingKey=(chatId:string)=>"boss.conversation.sources.pending.v1:"+chatId;
const sourceKey=(source:SourceRef)=>JSON.stringify([source.source_id,source.version]);
function verifyReceipt(value:Receipt,chatId:string,requestId:string,lookup:boolean){
  if(value.chat_id!==chatId||value.session_id!=="websocket:"+chatId||value.client_request_id!==requestId||value.business_authorization_granted!==false||value.business_mutation_performed!==false||lookup&&value.write_performed_by_lookup!==false||!["RECORDED","REJECTED","UNKNOWN"].includes(value.outcome))throw new Error("资料绑定回执与原会话请求不符。");
  if(value.outcome==="RECORDED"&&(!value.binding_id||!value.context_version||!Array.isArray(value.source_refs)))throw new Error("资料绑定回执缺少正式对象与版本。");
}

export function BossConversationKnowledge(props:Props){
  const {token}=useClient();
  return <KnowledgeSelection key={String(token)+":"+props.chatId} {...props}/>;
}
function KnowledgeSelection({chatId,active,onSource}:Props){
  const {client}=useClient();
  const [open,setOpen]=useState(false),[query,setQuery]=useState(""),[applied,setApplied]=useState(""),[revision,setRevision]=useState(0);
  const [catalogue,setCatalogue]=useState<Catalogue|null>(null),[loading,setLoading]=useState(false),[error,setError]=useState("");
  const [selected,setSelected]=useState<SourceRef[]>([]),[basis,setBasis]=useState<{namespace:string;context:string;catalogue:string;dataset:string}|null>(null);
  const [pending,setPending]=useState(()=>chatId?window.localStorage.getItem(pendingKey(chatId)):null),[busy,setBusy]=useState(false),[receipt,setReceipt]=useState<Receipt|null>(null);
  const mounted=useRef(true),currentActive=useRef(active),sequence=useRef(0),currentBasis=useRef(basis);
  currentActive.current=active;currentBasis.current=basis;
  useEffect(()=>{mounted.current=true;return()=>{mounted.current=false;sequence.current++;};},[]);
  useEffect(()=>{
    const current=++sequence.current;setCatalogue(null);setLoading(false);setError("");
    if(!active||!open||!chatId)return;
    setLoading(true);
    void client.requestMutation<Catalogue>("boss.conversation.sources.list",{chat_id:chatId,query:applied}).then(value=>{
      if(!mounted.current||!currentActive.current||sequence.current!==current)return;
      if(value.projection!=="conversation-sources"||value.chat_id!==chatId||value.session_id!=="websocket:"+chatId||value.query!==applied||!value.execution_namespace||!value.dataset_version||!value.context_version||!value.catalogue_version||!Array.isArray(value.sources)||!Array.isArray(value.selected_sources)||value.business_authorization_granted!==false||value.business_mutation_performed!==false)throw new Error("知识库目录与当前会话范围不符。");
      setCatalogue(value);setLoading(false);
      if(!currentBasis.current){setSelected(value.selected_sources);setBasis({namespace:value.execution_namespace,context:value.context_version,catalogue:value.catalogue_version,dataset:value.dataset_version});}
    }).then(undefined,failure=>{if(mounted.current&&sequence.current===current){setCatalogue(null);setLoading(false);setError(failure instanceof Error?failure.message:String(failure));}});
  },[client,chatId,active,open,applied,revision]);
  const valid=active&&catalogue&&basis&&catalogue.execution_namespace===basis.namespace&&catalogue.context_version===basis.context&&catalogue.catalogue_version===basis.catalogue&&catalogue.dataset_version===basis.dataset;
  function accept(value:Receipt,requestId:string,lookup:boolean,expected?:SourceRef[]){
    if(!chatId)throw new Error("资料绑定缺少会话编号。");
    verifyReceipt(value,chatId,requestId,lookup);
    if(value.outcome==="RECORDED"&&expected&&JSON.stringify(value.source_refs!.map(sourceKey).sort())!==JSON.stringify(expected.map(sourceKey).sort()))throw new Error("正式绑定的来源与本次选择不符，请查询原请求。");
    setReceipt(value);
    if(value.outcome==="UNKNOWN"){setError("原资料绑定结果尚未确定，请继续查询原请求。");return;}
    window.localStorage.removeItem(pendingKey(chatId));setPending(null);
    if(value.outcome==="REJECTED"){setError(value.reason??"原资料绑定请求已被拒绝，请重新核查来源。");return;}
    setBasis(null);setSelected(value.source_refs!);setRevision(value=>value+1);setOpen(false);
  }
  function submit(){
    if(!chatId||!valid||!basis||!catalogue?.can_bind||busy||pending)return;
    const requestId=crypto.randomUUID();window.localStorage.setItem(pendingKey(chatId),requestId);setPending(requestId);setBusy(true);setError("");setReceipt(null);
    void client.requestMutation<Receipt>("boss.conversation.sources.bind",{chat_id:chatId,client_request_id:requestId,execution_namespace:basis.namespace,dataset_version:basis.dataset,expected_context_version:basis.context,expected_catalogue_version:basis.catalogue,source_refs:selected}).then(value=>{
      if(mounted.current&&currentActive.current)accept(value,requestId,false,selected);
    }).then(undefined,failure=>{if(mounted.current)setError((failure instanceof Error?failure.message:String(failure))+"；原请求保留，请查询正式结果。");}).finally(()=>{if(mounted.current)setBusy(false);});
  }
  function reconcile(){
    if(!chatId||!pending||!active||busy)return;
    const requestId=pending;setBusy(true);setError("");
    void client.requestMutation<Receipt>("boss.conversation.sources.receipt",{chat_id:chatId,client_request_id:requestId}).then(value=>{
      if(mounted.current&&currentActive.current)accept(value,requestId,true);
    }).then(undefined,failure=>{if(mounted.current)setError(failure instanceof Error?failure.message:String(failure));}).finally(()=>{if(mounted.current)setBusy(false);});
  }
  return <div className="boss-chat-knowledge">
    <button className="boss-btn" disabled={!active||!chatId||busy} onClick={()=>{setReceipt(null);setOpen(true);}}><BookOpen size={16}/>引用知识库</button>
    {!chatId&&<span>选择或创建会话后可以引用资料。</span>}
    {receipt?.outcome==="RECORDED"&&<p role="status">已保存本会话资料选择，版本 {receipt.context_version}。后续读取继续核查来源有效性。</p>}
    {pending&&<p className="boss-n02-note warn" role="status">资料选择结果待核查，原请求 {pending}。<button className="boss-btn" disabled={!active||busy} onClick={reconcile}>查询原绑定结果</button></p>}
    {error&&!open&&<p className="boss-n02-note error" role="alert">{error}</p>}
    <Dialog.Root open={open&&active} onOpenChange={value=>{setOpen(value);if(!value){setBasis(null);setSelected([]);}}}><Dialog.Portal><Dialog.Overlay className="boss-n02-dialog-overlay"/><Dialog.Content className="boss-n02-dialog boss-chat-knowledge-dialog"><Dialog.Title>选择本会话引用资料</Dialog.Title><Dialog.Description>保留所选来源和版本。资料选择供当前会话读取，具体业务操作继续核查本人授权。</Dialog.Description>
      <form className="boss-chat-knowledge-search" onSubmit={event=>{event.preventDefault();setApplied(query.trim());setRevision(value=>value+1);}}><label>查询获准资料<input value={query} onChange={event=>setQuery(event.target.value)} disabled={busy}/></label><button className="boss-btn" disabled={!active||busy}><Search size={16}/>查询</button></form>
      {loading&&<p role="status">正在读取当前获准来源及已保存选择。</p>}{error&&<p className="boss-n02-note error" role="alert">{error}</p>}
      {!active&&<p className="boss-n02-note warn">当前连接尚未恢复，资料目录和选择等待重新核查。</p>}
      {catalogue&&<><p>目录覆盖：{catalogue.coverage==="COMPLETE"?"当前查询完整目录":"部分资料，完整范围待核查"}</p>{!valid&&<p className="boss-n02-note warn">资料目录、会话选择或执行空间已经变化。保留当前选择，请重新读取后核查。</p>}{!catalogue.can_bind&&<p>{catalogue.unavailable_reason??"当前资料选择尚不可保存。"}</p>}<div className="boss-chat-knowledge-list">{catalogue.sources.map(source=><article className="boss-workspace-item" key={sourceKey(source)}><label><input type="checkbox" disabled={!valid||!source.allowed||busy||!!pending} checked={selected.some(item=>sourceKey(item)===sourceKey(source))} onChange={event=>setSelected(current=>event.target.checked?[...current.filter(item=>item.source_id!==source.source_id),{source_id:source.source_id,version:source.version}]:current.filter(item=>sourceKey(item)!==sourceKey(source)))}/><strong>{source.title}</strong></label><p>{source.source_type} · 版本 {source.version} · {source.validity_state}</p><p>{source.author??"作者未提供"} · {source.published_at??"发布时间未提供"}</p>{source.reason&&<p>{source.reason}</p>}<button className="boss-btn" disabled={!source.allowed} onClick={()=>{setOpen(false);onSource(source.source_id,source.version);}}>核查来源原文</button></article>)}</div>{!catalogue.sources.length&&<p>当前查询没有可列出的获准资料。</p>}</>}
      <details><summary>本次选择（{selected.length} 项）</summary>{selected.length?selected.map(source=><p key={sourceKey(source)}>{source.source_id} · 版本 {source.version}<button className="boss-btn" disabled={busy||!!pending} onClick={()=>setSelected(current=>current.filter(item=>sourceKey(item)!==sourceKey(source)))}>移除此项选择</button></p>):<p>当前没有所选资料；保存后清除本会话的显式资料选择。</p>}</details>
      <footer className="boss-n02-actions"><Dialog.Close asChild><button className="boss-btn">取消并返回会话</button></Dialog.Close><button className="boss-btn" disabled={!active||busy||!!pending} onClick={()=>{setBasis(null);setRevision(value=>value+1);}}>重新读取已保存选择</button>{pending?<button className="boss-btn boss-btn-primary" disabled={!active||busy} onClick={reconcile}>查询原绑定结果</button>:<button className="boss-btn boss-btn-primary" disabled={!valid||!catalogue?.can_bind||busy||loading} onClick={submit}>采用所选资料</button>}</footer>
    </Dialog.Content></Dialog.Portal></Dialog.Root>
  </div>;
}
