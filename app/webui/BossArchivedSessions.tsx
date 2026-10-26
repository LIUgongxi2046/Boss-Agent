import {useEffect,useRef,useState} from "react";
import * as Dialog from "@radix-ui/react-dialog";
import {useClient} from "@/providers/ClientProvider";
import {V7Empty,V7Fact,V7Pagination,V7ReadState} from "./BossV7UI";

type Attachment={attachment_id:string;original_name:string|null;stored_name:string|null;mime_type:string|null;
  recorded_size_bytes:number|null;recorded_content_sha256:string|null;processing_state:string;download_available:boolean;user_message_index:number|null};
type History={projection:"session-history";private_body_available_here:true;namespace:string;historical_namespace:string|null;
  session_key:string|null;state:"READ_ONLY_HISTORY";current_evidence_eligible:false;page:number;page_size:number;total:number;
  spaces:{namespace:string;dataset_id:string;dataset_version:string;archived_at:string;session_count:number}[];
  sessions:{key:string;created_at:string;updated_at:string}[];
  messages:{index:number;role:"user"|"assistant";content:string;timestamp:string|null}[];
  attachments:Attachment[];attachments_state:string;
  dataset_id?:string;dataset_version?:string;archived_at?:string};

function DownloadAttachment({namespace,sessionKey,item}:{namespace:string;sessionKey:string;item:Attachment}){
  const {token,getToken}=useClient();
  const [busy,setBusy]=useState(false),[error,setError]=useState("");
  const controller=useRef<AbortController|null>(null);
  const scope=useRef({token,namespace,sessionKey});
  if(scope.current.token!==token||scope.current.namespace!==namespace||scope.current.sessionKey!==sessionKey)scope.current={token,namespace,sessionKey};
  useEffect(()=>{setBusy(false);setError("");return()=>controller.current?.abort();},[token,namespace,sessionKey]);
  async function download(){
    if(busy||!item.download_available)return;
    const origin=scope.current,abort=new AbortController();controller.current=abort;setBusy(true);setError("");
    const query=new URLSearchParams({namespace,session_key:sessionKey,attachment_id:item.attachment_id});
    await fetch("/api/boss/ui/owner/session-history?"+query,{headers:{Authorization:"Bearer "+getToken()},cache:"no-store",signal:abort.signal}).then(async response=>{
      if(response.status===401)window.dispatchEvent(new Event("boss-auth-expired"));
      if(!response.ok)throw new Error("历史附件读取失败（HTTP "+response.status+"）");
      const result=await response.json() as History&{download:{attachment_id:string;filename:string;size_bytes:number;content_sha256:string;encoding:string;content:string}};
      const file=result.download;
      if(result.projection!=="session-history"||result.private_body_available_here!==true||result.current_evidence_eligible!==false||result.historical_namespace!==namespace||result.session_key!==sessionKey||file?.attachment_id!==item.attachment_id||file.encoding!=="base64"||file.content_sha256!==item.recorded_content_sha256||file.size_bytes!==item.recorded_size_bytes)throw new Error("附件与原会话保存记录不符");
      if(typeof file.filename!=="string"||!file.filename||/[\/\\\u0000]/.test(file.filename))throw new Error("原附件文件名无效");
      const bytes=Uint8Array.from(atob(file.content),character=>character.charCodeAt(0));
      const digest=await crypto.subtle.digest("SHA-256",bytes);
      const sha=Array.from(new Uint8Array(digest),byte=>byte.toString(16).padStart(2,"0")).join("");
      if(bytes.length!==file.size_bytes||sha!==file.content_sha256)throw new Error("下载内容与原附件摘要不符");
      if(abort.signal.aborted||scope.current!==origin)return;
      const url=URL.createObjectURL(new Blob([bytes],{type:"application/octet-stream"}));
      const anchor=document.createElement("a");anchor.href=url;anchor.download=file.filename;document.body.append(anchor);anchor.click();anchor.remove();window.setTimeout(()=>URL.revokeObjectURL(url),1000);
    }).then(()=>{if(!abort.signal.aborted&&scope.current===origin)setBusy(false);},reason=>{if(!abort.signal.aborted&&scope.current===origin){setBusy(false);setError(reason.message);}});
  }
  return <><button className="boss-btn" disabled={busy||!item.download_available} onClick={()=>void download()}>{busy?"正在核查原附件":"下载原附件"}</button>{error&&<p role="alert" className="boss-status boss-status-error">{error}</p>}</>;
}

function ArchiveReader(){
  const {token,getToken}=useClient();
  const [namespace,setNamespace]=useState("");
  const [sessionKey,setSessionKey]=useState("");
  const [page,setPage]=useState(1);
  const [revision,setRevision]=useState(0);
  const [state,setState]=useState<{scope:string;token:typeof token;data:History|null;loading:boolean;error:string}|null>(null);
  const parameters=new URLSearchParams();
  if(namespace)parameters.set("namespace",namespace);
  if(sessionKey)parameters.set("session_key",sessionKey);
  if(page!==1)parameters.set("page",String(page));
  const scope=parameters.toString();
  useEffect(()=>{
    const abort=new AbortController();
    setState({scope,token,data:null,loading:true,error:""});
    void fetch("/api/boss/ui/owner/session-history"+(scope?"?"+scope:""),{
      headers:{Authorization:"Bearer "+getToken()},cache:"no-store",signal:abort.signal,
    }).then(async response=>{
      if(response.status===401)window.dispatchEvent(new Event("boss-auth-expired"));
      if(!response.ok)throw new Error("归档会话读取失败（HTTP "+response.status+"）");
      const data=await response.json() as History;
      if(data.projection!=="session-history"||data.private_body_available_here!==true||data.state!=="READ_ONLY_HISTORY"||data.current_evidence_eligible!==false||data.historical_namespace!==(namespace||null)||data.session_key!==(sessionKey||null)||data.page!==page)throw new Error("归档会话返回范围不符");
      if(!abort.signal.aborted)setState({scope,token,data,loading:false,error:""});
    }).then(undefined,reason=>{if(!abort.signal.aborted)setState({scope,token,data:null,loading:false,error:reason.message});});
    return()=>abort.abort();
  },[scope,token,getToken,revision,namespace,sessionKey,page]);
  const visible=state?.scope===scope&&state.token===token?state:null;
  const data=visible?.data;
  return <>
    <V7ReadState loading={!visible||visible.loading} error={visible?.error??""} onReload={()=>setRevision(value=>value+1)}/>
    <p className="boss-status">原执行空间的会话仅供本人查询，不参与当前任务。工具内部内容与模型内部推理不在此处展示。</p>
    <label className="boss-field">原执行空间<select value={namespace} disabled={!data} onChange={event=>{setNamespace(event.target.value);setSessionKey("");setPage(1);}}><option value="">选择获准归档空间</option>{data?.spaces.map(space=><option key={space.namespace} value={space.namespace}>{space.namespace} · {space.dataset_id} v{space.dataset_version} · {space.session_count}个会话</option>)}</select></label>
    {data?.historical_namespace&&<div className="boss-form-grid"><V7Fact label="原执行空间">{data.historical_namespace}</V7Fact><V7Fact label="原数据集">{data.dataset_id} · v{data.dataset_version}</V7Fact><V7Fact label="归档时间">{data.archived_at}</V7Fact><V7Fact label="当前执行空间">{data.namespace}</V7Fact></div>}
    {sessionKey&&<div className="boss-actions"><button className="boss-btn" onClick={()=>{setSessionKey("");setPage(1);}}>返回归档会话列表</button><V7Fact label="原会话编号">{sessionKey}</V7Fact></div>}
    {data&&(sessionKey?<div className="boss-v7-timeline">{data.messages.map(message=><article key={message.index}><strong>{message.role==="user"?"本人消息":"Agent回复"}</strong><time>{message.timestamp??"未记录时间"}</time><blockquote className="boss-source" style={{whiteSpace:"pre-wrap"}}>{message.content}</blockquote></article>)}</div>:<div className="boss-v7-table-scroll"><table className="boss-v7-table"><thead><tr><th>原会话编号</th><th>创建时间</th><th>更新时间</th></tr></thead><tbody>{data.sessions.map(session=><tr key={session.key}><td><button className="boss-v7-text-button" onClick={()=>{setSessionKey(session.key);setPage(1);}}>{session.key}</button></td><td>{session.created_at}</td><td>{session.updated_at}</td></tr>)}</tbody></table></div>)}
    {data&&data.total===0&&<V7Empty title={!namespace?"选择原执行空间后查询历史会话":sessionKey?"该会话没有可展示的文字消息":"当前空间没有归档聊天会话"}/>}
    {data&&namespace&&<V7Pagination page={page} total={data.total} pageSize={data.page_size} onChange={setPage}/>}
    {data&&sessionKey&&<section aria-label="归档会话附件"><h3>原会话附件</h3><p>原文件与当前保存摘要一致时可以下载。附件不作为当前任务依据。</p>{data.attachments_state==="MEDIA_DIRECTORY_UNRECORDED"&&<p className="boss-status boss-status-warn">原媒体目录没有归档记录，当前只能显示保存的附件信息。</p>}{data.attachments.map(item=><article className="boss-workspace-item" key={item.attachment_id}><strong>{item.original_name??item.stored_name??item.attachment_id}</strong><V7Fact label="原文件类型">{item.mime_type??"未记录"}</V7Fact><V7Fact label="原文件大小">{item.recorded_size_bytes===null?"未记录":item.recorded_size_bytes+" bytes"}</V7Fact><V7Fact label="当前文件状态">{{STORED:"文件存在且已经核查",MISSING:"文件缺少",CHANGED:"内容已经变化",REFERENCE_UNAVAILABLE:"文件引用无法核查"}[item.processing_state]??item.processing_state}</V7Fact><V7Fact label="原文件摘要">{item.recorded_content_sha256??"未记录"}</V7Fact><DownloadAttachment namespace={namespace} sessionKey={sessionKey} item={item}/></article>)}{!data.attachments.length&&<V7Empty title="原会话没有可读取的附件记录"/>}</section>}
  </>;
}

export function BossArchivedSessions(){
  const [open,setOpen]=useState(false);
  return <Dialog.Root open={open} onOpenChange={setOpen}><Dialog.Trigger asChild><button className="boss-btn">归档空间会话</button></Dialog.Trigger><Dialog.Portal><Dialog.Overlay className="boss-v7-dialog-overlay"/><Dialog.Content className="boss-v7-dialog"><Dialog.Title>归档空间会话</Dialog.Title><Dialog.Description>按原数据集、执行空间和会话编号查看本人历史消息。</Dialog.Description>{open&&<ArchiveReader/>}<div className="boss-actions"><Dialog.Close asChild><button className="boss-btn">返回当前会话</button></Dialog.Close></div></Dialog.Content></Dialog.Portal></Dialog.Root>;
}
