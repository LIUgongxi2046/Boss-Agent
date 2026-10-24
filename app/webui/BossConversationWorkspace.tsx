import {useEffect,useRef,useState,type ReactNode} from "react";
import * as Dialog from "@radix-ui/react-dialog";
import {ArrowLeft,FileText,History,MessageCircle,Plus,RefreshCw,Search,X} from "lucide-react";
import {useClient} from "@/providers/ClientProvider";
import "./boss-n02.css";

export type ConversationActions={onOpenTask:(id:string)=>void;onOpenSource:(id:string)=>void;onOpenMessages:()=>void;onReturn:()=>void};
type Session={key:string;chatId:string;title:string;updatedAt:string};
type Reference={kind:"query"|"task"|"morning_list"|"message"|"message_draft";id:string;recorded_version:string|null};
type Run={run_id:string;status:string;stop_reason:string|null;started_at:string;finished_at:string|null;configuration_id:string;configuration_version:string;tool_steps:{tool_id:string;tool_call_id:string;status:string;version?:string;task_version?:string}[];tool_errors:{tool_id:string;error_type:string}[];artifacts:Reference[];origin_references:Record<string,Record<string,unknown>>};
type View={session_id:string;chat_id:string;runs:Run[];business_authorization_granted:false;business_mutation_performed:false};
type Attachment={attachment_id:string;stored_name:string|null;original_name:string|null;mime_type:string|null;size_bytes:number|null;content_sha256:string|null;recorded_size_bytes:number|null;recorded_content_sha256:string|null;user_message_index:number|null;processing_state:"STORED"|"MISSING"|"CHANGED"|"REFERENCE_UNAVAILABLE"};
type Artifact={run_id:string;kind:Reference["kind"];id:string;data:Record<string,unknown>;evidence:{sources:{source_id:string;version:string;published_at?:string;author_contact_id?:string}[]}|null};
type Props={role:"BOSS"|"MAINTAINER";visible:boolean;activeKey:string|null;sessions:Session[];onNewChat:()=>void;onSelectChat:(key:string)=>void;onSearch:()=>void;actions:ConversationActions;children:ReactNode};
const stateLabel:Record<string,string>={RUNNING:"正在执行",QUEUED:"正在排队",SUCCEEDED:"运行完成",FAILED:"运行失败",CANCELED:"已经取消",TIMED_OUT:"执行超时",UNKNOWN:"结果待核查",INTERRUPTED:"执行中断"};
const kindLabel:Record<Reference["kind"],string>={query:"查询结果",task:"交办任务",morning_list:"晨间清单",message:"已保存消息",message_draft:"消息草稿"};
const label=(value:string)=>stateLabel[value]??value;
const fileState={STORED:"已经保存",MISSING:"文件缺少",CHANGED:"内容已经变化，需要重新核查",REFERENCE_UNAVAILABLE:"文件引用无法确认"};
function Row({name,value}:{name:string;value:ReactNode}){return <div className="boss-n02-kv"><span>{name}</span><strong>{value}</strong></div>;}
export function BossConversationWorkspace({role,visible,activeKey,sessions,onNewChat,onSelectChat,onSearch,actions,children}:Props){
  const {client,token}=useClient();
  const session=sessions.find(value=>value.key===activeKey),chatId=session?.chatId??(activeKey?.startsWith("websocket:")?activeKey.slice(10):null);
  const [view,setView]=useState<View|null>(null),[attachments,setAttachments]=useState<Attachment[]>([]),[error,setError]=useState(""),[revision,setRevision]=useState(0);
  const [artifact,setArtifact]=useState<Artifact|null>(null),[artifactOpen,setArtifactOpen]=useState(false),[artifactError,setArtifactError]=useState(""),[artifactLoading,setArtifactLoading]=useState(false);
  const [historyOpen,setHistoryOpen]=useState(true);
  const generation=useRef(0),artifactGeneration=useRef(0),progress=useRef<HTMLDivElement|null>(null),artifactFocus=useRef<HTMLElement|null>(null);
  useEffect(()=>{
    const current=++generation.current;++artifactGeneration.current;setView(null);setAttachments([]);setError("");setArtifact(null);setArtifactOpen(false);setArtifactError("");
    if(role!=="BOSS"||!visible||!chatId)return;
    let disposed=false,timer:ReturnType<typeof setTimeout>|undefined,attachmentRevision:string|null=null;
    const read=async()=>{
      try{
        const result=await client.requestMutation<View>("boss.conversation.read",{chat_id:chatId});
        if(disposed||generation.current!==current)return;
        if(result.chat_id!==chatId||result.session_id!=="websocket:"+chatId||result.business_authorization_granted!==false||result.business_mutation_performed!==false)throw new Error("当前会话读取范围不符");
        const last=result.runs.at(-1),nextAttachmentRevision=last?last.run_id+":"+last.status+":"+last.finished_at:"NO_RUN";
        if(nextAttachmentRevision!==attachmentRevision){
          const files=await client.requestMutation<{attachments:Attachment[]}>("boss.conversation.attachments",{chat_id:chatId});
          if(disposed||generation.current!==current)return;
          setAttachments(files.attachments);attachmentRevision=nextAttachmentRevision;
        }
        setView(result);setError("");timer=setTimeout(()=>void read(),2000);
      }catch(failure){if(!disposed&&generation.current===current){setView(null);setAttachments([]);setError(failure instanceof Error?failure.message:String(failure));}}
    };
    void read();return()=>{disposed=true;if(timer)clearTimeout(timer);};
  },[role,visible,chatId,client,token,revision]);
  useEffect(()=>()=>{++artifactGeneration.current;},[]);
  const openArtifact=async(run:Run,reference:Reference)=>{
    if(!chatId)throw new Error("当前产物缺少会话编号");
    const current=++artifactGeneration.current,readGeneration=generation.current;
    artifactFocus.current=document.activeElement instanceof HTMLElement?document.activeElement:null;
    setArtifactOpen(true);setArtifact(null);setArtifactError("");setArtifactLoading(true);
    try{
      const result=await client.requestMutation<Artifact>("boss.conversation.artifact",{chat_id:chatId,run_id:run.run_id,kind:reference.kind,id:reference.id});
      if(current!==artifactGeneration.current||readGeneration!==generation.current)return;
      if(result.run_id!==run.run_id||result.kind!==reference.kind||result.id!==reference.id)throw new Error("当前产物与原运行引用不符");
      setArtifact(result);
    }catch(failure){if(current===artifactGeneration.current&&readGeneration===generation.current)setArtifactError(failure instanceof Error?failure.message:String(failure));}
    finally{if(current===artifactGeneration.current&&readGeneration===generation.current)setArtifactLoading(false);}
  };
  if(role!=="BOSS")return <>{children}</>;
  const latest=view?.runs.at(-1),origin=latest?.origin_references.morning_context,selected=origin?.selected_item_ref as {object_id?:string;version?:string;source_refs?:{kind:string;id:string;version:string|null}[]}|undefined;
  return <div className="boss-n02" aria-label="聊天交办工作区">
    <div className="boss-n02-main">
      <section className="boss-n02-panel boss-n02-context" aria-labelledby="boss-n02-context-title">
        <header className="boss-n02-heading"><h2 id="boss-n02-context-title">当前会话与关联事项</h2></header>
        <Row name="关联事项" value={selected?.object_id??(origin?.date?"晨间事项 · "+String(origin.date):"尚未关联")}/><Row name="资料版本" value={selected?.version??(origin?.snapshot_sha256?"已保存当前清单快照":"待读取")}/><Row name="任务对象" value={latest?.artifacts.filter(value=>value.kind==="task").map(value=>value.id).join("、")||"尚未产生交办"}/>
        <div className="boss-n02-actions"><button className="boss-btn" onClick={actions.onReturn}><ArrowLeft size={16}/>返回业务页面</button><button className="boss-btn" onClick={onNewChat}><Plus size={16}/>新建会话</button><button className="boss-btn" type="button" aria-expanded={historyOpen} onClick={()=>setHistoryOpen(value=>!value)}><History size={16}/>历史会话</button></div>
      </section>
      <section className="boss-n02-panel boss-n02-conversation" aria-labelledby="boss-n02-conversation-title">
        <header className="boss-n02-heading"><h2 id="boss-n02-conversation-title">对话与任务运行</h2><span className="boss-n02-chip">语音输入暂停</span></header>
        <div className={"boss-n02-conversation-grid "+(!historyOpen?"boss-n02-history-hidden":"")}>
          <aside className="boss-n02-history" hidden={!historyOpen} aria-label="历史会话">
            <div className="boss-n02-heading"><h3>历史会话</h3><button className="boss-btn" aria-label="搜索会话" onClick={onSearch}><Search size={16}/></button></div>
            <label className="boss-n02-session-select">当前会话<select aria-label="当前会话" value={activeKey??""} onChange={event=>event.target.value?onSelectChat(event.target.value):onNewChat()}><option value="">新会话</option>{sessions.map(value=><option key={value.key} value={value.key}>{value.title}</option>)}</select></label>
            {sessions.length?<ul>{sessions.map(value=><li key={value.key}><button aria-current={value.key===activeKey?"page":undefined} onClick={()=>onSelectChat(value.key)}><MessageCircle size={16}/><span>{value.title}<small>{value.updatedAt}</small></span></button></li>)}</ul>:<p className="boss-n02-empty">尚无可用会话</p>}
          </aside>
          <div className="boss-n02-thread" aria-label="交办消息">{children}</div>
        </div>
        <div className="boss-n02-progress" ref={progress} tabIndex={-1} aria-labelledby="boss-n02-progress-title">
          <h3 id="boss-n02-progress-title">可观察执行步骤</h3>
          {error?<div className="boss-n02-note error" role="alert">{error}<button className="boss-btn" onClick={()=>setRevision(value=>value+1)}>重新读取当前记录</button></div>:chatId&&!view?<p role="status">正在核查当前会话与运行记录</p>:!latest?<p className="boss-n02-note">尚未产生运行记录。可以输入问题、补充材料或说明需要推进的事项。</p>:<>
            <Row name="执行结果" value={label(latest.status)}/><Row name="结束原因" value={latest.stop_reason??"尚未结束"}/>
            {latest.tool_steps.length?<ol className="boss-n02-steps">{latest.tool_steps.map((step,index)=><li key={step.tool_call_id+index}><FileText size={16}/><span>{step.tool_id}</span><strong>{label(step.status)}</strong></li>)}</ol>:<p>本次没有已记录的工具步骤。</p>}
            <div className="boss-n02-actions">{latest.artifacts.map(reference=><button className="boss-btn" key={reference.kind+reference.id} onClick={()=>void openArtifact(latest,reference)}>{kindLabel[reference.kind]}<span>{reference.id}</span></button>)}</div>
          </>}
        </div>
      </section>
    </div>
    <aside className="boss-n02-aside">
      <section className="boss-n02-panel" aria-labelledby="boss-n02-latest-title"><h2 id="boss-n02-latest-title">持续进展与异常</h2><Row name="运行状态" value={latest?label(latest.status):"尚未运行"}/><Row name="必要决定" value="通过对应业务入口核查"/><Row name="历史阅读位置" value="返回时保留"/>
        <div className="boss-n02-actions"><button className="boss-btn" onClick={()=>{progress.current?.scrollIntoView({block:"nearest"});progress.current?.focus();}}>查看最新进展</button><button className="boss-btn" onClick={()=>setRevision(value=>value+1)}><RefreshCw size={16}/>读取原执行结果</button></div>
        {latest?.tool_errors.map((value,index)=><p className="boss-n02-note error" key={value.tool_id+index}>{value.tool_id} · {value.error_type}</p>)}<p className="boss-n02-note warn">执行结果未知时，请读取原记录核查。发送、送达、回复和交办完成分别记录。</p>
        <button className="boss-btn" onClick={actions.onOpenMessages}>查看消息草稿与回复</button>
      </section>
      <section className="boss-n02-panel" aria-label="来源与依据"><h2>来源与依据</h2>{selected?.source_refs?.length?selected.source_refs.map(source=><div className="boss-n02-source" key={source.kind+source.id}><strong>{source.id}</strong><span>版本 {source.version??"未知"}</span>{source.kind==="document"&&<button className="boss-btn" onClick={()=>actions.onOpenSource(source.id)}>核查来源</button>}</div>):<p>选择实际产物后，可以核查其当前来源与版本。</p>}<p className="boss-n02-note">附件保存状态和业务来源采用分别核查。</p>
        <details aria-label="当前已保存附件"><summary>当前已保存附件（{attachments.length}）</summary>{attachments.length?attachments.map(file=><div className="boss-n02-source" key={file.attachment_id}><strong>{file.original_name??file.stored_name??"附件名称未知"}</strong><span>{file.mime_type??"类型未知"} · {file.size_bytes===null?"当前大小未知":file.size_bytes+" bytes"} · {fileState[file.processing_state]}</span>{file.processing_state!=="STORED"&&<p className="boss-n02-note warn">上传记录大小：{file.recorded_size_bytes===null?"未知":file.recorded_size_bytes+" bytes"}。当前附件不能作为已核查的业务依据。</p>}</div>):<p>尚无已保存附件。当前选择及未发送附件保留在输入区域。</p>}</details>
      </section>
    </aside>
    <Dialog.Root open={artifactOpen&&visible} onOpenChange={open=>{setArtifactOpen(open);if(!open)++artifactGeneration.current;}}><Dialog.Portal><Dialog.Overlay className="boss-n02-dialog-overlay"/><Dialog.Content className="boss-n02-dialog" onCloseAutoFocus={event=>{event.preventDefault();if(visible&&artifactFocus.current?.isConnected)artifactFocus.current.focus({preventScroll:true});}}><Dialog.Title>当前产物与依据</Dialog.Title><Dialog.Description>根据当前会话的原运行引用，重新核查实际对象与来源。</Dialog.Description><Dialog.Close className="boss-icon-button" aria-label="关闭产物详情"><X size={18}/></Dialog.Close>
      {artifactLoading&&<p role="status">正在核查当前产物</p>}{artifactError&&<p role="alert" className="boss-n02-note error">{artifactError}</p>}{artifact&&<><Row name="产物类型" value={kindLabel[artifact.kind]}/><Row name="对象编号" value={artifact.id}/>{["status","version","purpose","body","send_state","delivery_state","reply_state"].filter(key=>artifact.data[key]!==undefined).map(key=><Row key={key} name={{status:"当前状态",version:"当前版本",purpose:"交办目的",body:"消息正文",send_state:"发送状态",delivery_state:"送达状态",reply_state:"回复状态"}[key]??key} value={artifact.data[key]===null?"当前不能采用":String(artifact.data[key])}/>)}{artifact.kind==="task"&&<button className="boss-btn" onClick={()=>{setArtifactOpen(false);actions.onOpenTask(artifact.id);}}>查看交办详情</button>}{artifact.evidence?.sources.map(source=><div className="boss-n02-source" key={source.source_id}><strong>{source.source_id}</strong><span>版本 {source.version} · {source.published_at??"发布时间未知"} · {source.author_contact_id??"作者待核查"}</span><button className="boss-btn" onClick={()=>{setArtifactOpen(false);actions.onOpenSource(source.source_id);}}>查看来源原文</button></div>)}</>}
    </Dialog.Content></Dialog.Portal></Dialog.Root>
  </div>;
}
