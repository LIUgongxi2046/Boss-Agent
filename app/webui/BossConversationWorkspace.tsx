import {useEffect,useRef,useState,type ReactNode} from "react";
import * as Dialog from "@radix-ui/react-dialog";
import {ArrowLeft,FileText,History,MessageCircle,Plus,RefreshCw,Search,X} from "lucide-react";
import {useClient} from "@/providers/ClientProvider";
import {verifyTaskContext,type TaskConversationContext} from "./BossTaskConversationEntry";
import {useConversationReturn} from "./BossConversationPosition";
import {BossArchivedSessions} from "./BossArchivedSessions";
import {BossConversationMetrics} from "./BossConversationMetrics";
import {BossConversationKnowledge} from "./BossConversationKnowledge";
import {verifyBusinessContext,type BusinessContext} from "./BusinessConversationEntry";
import {isActiveN02Scope,mayDisplayCurrentTaskReference,sameActiveN02Scope,shouldCancelN02PositionOnInteraction,type N02Scope} from "./n02-context-guard";
import {shouldRefreshN02Attachments,validateN02AttachmentRead,type N02Attachment,type N02AttachmentReadMarker} from "./n02-attachments";
import type {ThreadReadingController} from "@/components/thread/ThreadViewport";
import "./boss-n02.css";

export type ConversationActions={onOpenTask:(id:string)=>void;onOpenSource:(id:string,version?:string)=>void;onOpenMessages:()=>void;onOpenPage:(page:"F24"|"F29"|"F28"|"F03"|"N10",runId?:string)=>void;onReturn:()=>void};
type Session={key:string;chatId:string;title:string;updatedAt:string};
type Reference={kind:"query"|"task"|"morning_list"|"message"|"message_draft";id:string;recorded_version:string|null};
type ContextReference={kind:string;id:string;recorded_version:string|null;current_version:string|null;reference_state:string;adoption_state:string;current_validity:string|null;current_object_state:string|null;source_metadata:Record<string,string|null>|null;source_refs:{source_id:string;version:string|null;current_version:string|null;status:string}[];support:{origin:string;tool_id:string|null;tool_call_id:string|null}[]};
type Run={run_id:string;status:string;stop_reason:string|null;started_at:string;finished_at:string|null;configuration_id:string;configuration_version:string;tool_steps:{tool_id:string;tool_call_id:string;status:string;version?:string;task_version?:string}[];tool_errors:{tool_id:string;error_type:string}[];artifacts:Reference[];context_references:ContextReference[];origin_references:Record<string,Record<string,unknown>>;authorization_summary?:{state:string;target_label:string;waiting_inputs:string[];coverage:"COMPLETE"|"PARTIAL"}};
type View={session_id:string;chat_id:string;runs:Run[];business_authorization_granted:false;business_mutation_performed:false};
type RequestReceipt={client_request_id:string;outcome:"RECORDED";request_state:string;run_id:string|null;chat_id:string;session_id:string;turn_id:string;write_performed_by_lookup:false;business_authority_granted:false};
type Attachment=N02Attachment;
type Artifact={run_id:string;chat_id:string;session_id:string;business_authorization_granted:false;business_mutation_performed:false;kind:Reference["kind"];id:string;data:Record<string,unknown>;evidence:{sources:{source_id:string;version:string;published_at?:string;author_contact_id?:string}[]}|null};
type Props=ThreadReadingController&{role:"BOSS"|"MAINTAINER";visible:boolean;activeKey:string|null;sessions:Session[];onNewChat:()=>void;onSelectChat:(key:string)=>void;onSearch:()=>void;actions:ConversationActions;children:ReactNode};
const stateLabel:Record<string,string>={RUNNING:"正在执行",QUEUED:"正在排队",SUCCEEDED:"运行完成",WAITING_INPUT:"等待补充条件",FAILED:"运行失败",CANCELED:"已经取消",TIMED_OUT:"执行超时",UNKNOWN:"结果待核查",INTERRUPTED:"执行中断",CURRENT:"当前可以读取",NEEDS_REVIEW:"需要重新核查",UNAVAILABLE:"当前无法采用",VERSION_CHANGED:"当前版本已经变化",VERSION_UNRECORDED:"原版本未记录",INACTIVE:"当前已经停用",MISSING_OR_FORBIDDEN:"当前无法访问",UNSUPPORTED_KIND:"当前种类无法读取"};
const kindLabel:Record<Reference["kind"],string>={query:"查询结果",task:"交办任务",morning_list:"晨间清单",message:"已保存消息",message_draft:"消息草稿"};
const label=(value:string)=>stateLabel[value]??value;
const returnNames:Record<string,string>={F01:"返回今日工作",N03:"返回经营关注",N04:"返回会议与资料",N05:"返回任务与承诺",N06:"返回通知中心",F02:"返回经营提醒",F03:"返回经营查询",F06:"返回交办",F07:"返回申请审阅",F09:"返回专题研究",F10:"返回人员会面",F11:"返回行程安排",F12:"返回私人安排",F13:"返回个人记忆",A03:"返回数据集",A07:"返回知识资料",A15:"返回运行记录"};
function conversationReturn(){const page=new URLSearchParams(window.location.search).get("bossReturn");return page?{page,label:returnNames[page]??"返回业务页面"}:null;}
const fileState={STORED:"已经保存",MISSING:"文件缺少",CHANGED:"内容已经变化，需要重新核查",REFERENCE_UNAVAILABLE:"文件引用无法确认"};
function Row({name,value}:{name:string;value:ReactNode}){return <div className="boss-n02-kv"><span>{name}</span><strong>{value}</strong></div>;}
export function BossConversationWorkspace({role,visible,activeKey,sessions,onNewChat,onSelectChat,onSearch,actions,children,captureReadingPosition,restoreReadingPosition}:Props){
  const {client,token}=useClient();
  const [connectionStatus,setConnectionStatus]=useState(client.status);
  const session=sessions.find(value=>value.key===activeKey),chatId=session?.chatId??(activeKey?.startsWith("websocket:")?activeKey.slice(10):null);
  const latestScope=useRef<N02Scope>({client,token,chatId,role,visible,connectionStatus});
  latestScope.current={client,token,chatId,role,visible,connectionStatus};
  const [view,setView]=useState<View|null>(null),[attachments,setAttachments]=useState<Attachment[]>([]),[attachmentError,setAttachmentError]=useState(""),[attachmentLoading,setAttachmentLoading]=useState(false),[error,setError]=useState(""),[revision,setRevision]=useState(0);
  const [receipts,setReceipts]=useState<RequestReceipt[]>([]);
  const [taskContext,setTaskContext]=useState<TaskConversationContext|null>(null),[taskContextError,setTaskContextError]=useState(""),[taskContextChecking,setTaskContextChecking]=useState(false);
  const [businessContext,setBusinessContext]=useState<BusinessContext|null>(null),[businessContextError,setBusinessContextError]=useState("");
  const [artifact,setArtifact]=useState<Artifact|null>(null),[artifactOpen,setArtifactOpen]=useState(false),[artifactError,setArtifactError]=useState(""),[artifactLoading,setArtifactLoading]=useState(false);
  const [historyOpen,setHistoryOpen]=useState(false),[selectedRunId,setSelectedRunId]=useState("");
  const scope=useRef<{client:typeof client;token:typeof token;chatId:string|null;role:typeof role}|null>(null);
  const taskScope=useRef<{client:typeof client;token:typeof token;chatId:string|null;role:typeof role}|null>(null);
  const workspace=useRef<HTMLDivElement|null>(null);
  const generation=useRef(0),artifactGeneration=useRef(0),artifactFocus=useRef<HTMLElement|null>(null);
  useEffect(()=>client.onStatus(setConnectionStatus),[client]);
  useEffect(()=>{if(role==="BOSS"&&visible&&chatId&&connectionStatus==="open")client.attach(chatId);},[client,role,visible,chatId,connectionStatus]);
  useEffect(()=>{
    let active=true;setBusinessContext(null);setBusinessContextError("");
    if(role!=="BOSS"||!visible||!chatId||connectionStatus!=="open")return;
    void client.requestMutation<BusinessContext>("boss.conversation.business.read",{chat_id:chatId}).then(result=>{
      if(!active)return;verifyBusinessContext(result,chatId);setBusinessContext(result);
    }).catch(reason=>{if(active)setBusinessContextError(reason instanceof Error?reason.message:String(reason));});
    return()=>{active=false;};
  },[client,token,chatId,role,visible,connectionStatus,revision]);
  useEffect(()=>{
    const current=++generation.current;++artifactGeneration.current;setArtifact(null);setArtifactOpen(false);setArtifactError("");
    if(scope.current?.client!==client||scope.current?.token!==token||scope.current?.chatId!==chatId||scope.current?.role!==role){
      scope.current={client,token,chatId,role};setView(null);setAttachments([]);setAttachmentError("");setAttachmentLoading(false);setReceipts([]);setError("");setSelectedRunId("");
    }
    if(!isActiveN02Scope(latestScope.current)){
      // 身份或连接变化后，重新核查运行、附件与原请求范围。
      setView(null);setAttachments([]);setAttachmentError("");setAttachmentLoading(false);setReceipts([]);
      setError(role==="BOSS"&&visible&&chatId
        ?"会话连接中断，正在恢复。":"");
      return;
    }
    let disposed=false,timer:ReturnType<typeof setTimeout>|undefined;
    let lastAttachmentRead:N02AttachmentReadMarker|null=null;
    const originalScope={...latestScope.current};
    const active=()=>!disposed&&generation.current===current
      &&sameActiveN02Scope(originalScope,latestScope.current);
    const read=async()=>{
      try{
        const [result,requests]=await Promise.all([client.requestMutation<View>("boss.conversation.read",{chat_id:chatId}),client.requestMutation<RequestReceipt[]>("boss.conversation.requests",{chat_id:chatId})]);
        if(!active())return;
        if(result.chat_id!==chatId||result.session_id!=="websocket:"+chatId||result.business_authorization_granted!==false||result.business_mutation_performed!==false||!Array.isArray(result.runs))throw new Error("当前会话读取范围不符");
        if(!Array.isArray(requests)||requests.some(row=>row.chat_id!==chatId||row.session_id!=="websocket:"+chatId||row.write_performed_by_lookup!==false||row.business_authority_granted!==false))throw new Error("原请求记录与当前会话范围不符");
        // 运行与回执分别采用已经核查的读取结果。
        setView(result);setReceipts(requests);setError("");
        const last=result.runs.at(-1),runMarker=last?last.run_id+":"+last.status+":"+last.finished_at:"NO_RUN";
        if(shouldRefreshN02Attachments(lastAttachmentRead,runMarker,Date.now())){
          setAttachmentLoading(true);
          try{
            const envelope=await client.requestMutation<unknown>("boss.conversation.attachments",{chat_id:chatId});
            if(!active())return;
            setAttachments(validateN02AttachmentRead(envelope,chatId));
            setAttachmentError("");
          }catch(failure){
            if(!active())return;
            // 附件读取失败后清除原列表，保留明确错误。
            setAttachments([]);
            setAttachmentError(failure instanceof Error?failure.message:String(failure));
          }finally{
            if(active()){setAttachmentLoading(false);lastAttachmentRead={runMarker,checkedAt:Date.now()};}
          }
        }
        if(active())timer=setTimeout(()=>void read(),2000);
      }catch(failure){
        if(active()){
          setView(null);setAttachments([]);setAttachmentError("");setAttachmentLoading(false);
          setReceipts([]);setError(failure instanceof Error?failure.message:String(failure));
        }
      }
    };
    void read();return()=>{disposed=true;if(timer)clearTimeout(timer);};
  },[role,visible,chatId,client,token,revision,connectionStatus]);
  useEffect(()=>()=>{++artifactGeneration.current;},[]);
  useEffect(()=>{
    let disposed=false,timer:ReturnType<typeof setTimeout>|undefined;
    if(taskScope.current?.client!==client||taskScope.current?.token!==token||taskScope.current?.chatId!==chatId||taskScope.current?.role!==role){
      taskScope.current={client,token,chatId,role};setTaskContext(null);setTaskContextError("");
    }
    const ready=role==="BOSS"&&visible&&Boolean(chatId)&&connectionStatus==="open";
    setTaskContextChecking(ready);
    if(!ready||!chatId){setTaskContext(null);setTaskContextError("");return;}
    // 刷新或重新连接时重新核查当前任务与会话关系。
    setTaskContext(null);setTaskContextError("");
    const read=async()=>{
      try{
        const result=await client.requestMutation<TaskConversationContext>("boss.conversation.task.read",{chat_id:chatId});
        if(disposed)return;
        verifyTaskContext(result,chatId);setTaskContext(result);setTaskContextError("");setTaskContextChecking(false);timer=setTimeout(()=>void read(),2000);
      }catch(failure){if(!disposed){setTaskContext(null);setTaskContextError(failure instanceof Error?failure.message:String(failure));setTaskContextChecking(false);}}
    };
    void read();return()=>{disposed=true;if(timer)clearTimeout(timer);};
  },[client,token,chatId,role,visible,revision,connectionStatus]);
  const returnPosition=useConversationReturn({client,token,role,visible,chatId,loadedSessionId:view?.session_id,
    runIds:view?.runs.map(run=>run.run_id)??[],selectedRunId:view?.runs.find(run=>run.run_id===selectedRunId)?.run_id??view?.runs.at(-1)?.run_id??null,
    selectRun:setSelectedRunId,historyOpen,selectHistoryOpen:setHistoryOpen,workspace,captureReadingPosition,restoreReadingPosition});
  const {openBusiness,cancelForInteraction}=returnPosition;
  const openArtifact=async(run:Run,reference:Reference)=>{
    if(!chatId)throw new Error("当前产物缺少会话编号");
    const current=++artifactGeneration.current,readGeneration=generation.current;
    artifactFocus.current=document.activeElement instanceof HTMLElement?document.activeElement:null;
    setArtifactOpen(true);setArtifact(null);setArtifactError("");setArtifactLoading(true);
    try{
      const result=await client.requestMutation<Artifact>("boss.conversation.artifact",{chat_id:chatId,run_id:run.run_id,kind:reference.kind,id:reference.id});
      if(current!==artifactGeneration.current||readGeneration!==generation.current)return;
      if(result.chat_id!==chatId||result.session_id!=="websocket:"+chatId||result.business_authorization_granted!==false||result.business_mutation_performed!==false||result.run_id!==run.run_id||result.kind!==reference.kind||result.id!==reference.id)throw new Error("当前产物与原运行引用不符");
      setArtifact(result);
    }catch(failure){if(current===artifactGeneration.current&&readGeneration===generation.current)setArtifactError(failure instanceof Error?failure.message:String(failure));}
    finally{if(current===artifactGeneration.current&&readGeneration===generation.current)setArtifactLoading(false);}
  };
  if(role!=="BOSS")return <>{children}</>;
  const latest=view?.runs.find(run=>run.run_id===selectedRunId)??view?.runs.at(-1),origin=latest?.origin_references.morning_context,selected=origin?.selected_item_ref as {object_id?:string;version?:string;source_refs?:{kind:string;id:string;version:string|null}[]}|undefined;
  const contextRefs=latest?.context_references??[],taskRefs=contextRefs.filter(ref=>ref.kind==="task"),documentRefs=contextRefs.filter(ref=>ref.kind==="document");
  const taskEntry=mayDisplayCurrentTaskReference(taskContext,latestScope.current,taskContextChecking,taskContextError)
    ?taskContext?.entry:null;
  const currentBusinessContext=isActiveN02Scope(latestScope.current)&&!businessContextError?businessContext:null;
  return <div className={"boss-n02 boss-chat-v7"+(!historyOpen?" boss-chat-without-history":"")} aria-label="聊天交办工作区" ref={workspace}
    onPointerDownCapture={event=>{if(!(event.target instanceof Element&&event.target.closest("button,a,input,select,textarea")))cancelForInteraction();}}
    onClickCapture={event=>{
      const retry=event.target instanceof Element&&Boolean(event.target.closest("[data-n02-position-retry]"));
      if(shouldCancelN02PositionOnInteraction("click",null,retry))cancelForInteraction();
    }} onWheelCapture={cancelForInteraction} onKeyDownCapture={event=>{
      const retry=event.target instanceof Element&&Boolean(event.target.closest("[data-n02-position-retry]"));
      if(shouldCancelN02PositionOnInteraction("keydown",event.key,retry))cancelForInteraction();
    }}>
    <div className="boss-n02-main">
      <section className="boss-n02-panel boss-n02-context" aria-labelledby="boss-n02-context-title">
        <header className="boss-n02-heading"><div className="boss-chat-context-heading"><span className="boss-chat-context-icon"><MessageCircle size={24}/></span><div><h2 id="boss-n02-context-title">当前会话与关联事项</h2><p>{session?.title??"开始新的交办对话"}</p></div></div><span className="boss-n02-chip">{latest?label(latest.status):"等待输入"}</span></header>
        {returnPosition.error&&<div className="boss-n02-note error" role="alert">{returnPosition.error}<button className="boss-btn" type="button" data-n02-position-retry onClick={returnPosition.retry}>重新定位原消息</button><button className="boss-btn" onClick={returnPosition.clear}>结束位置恢复</button></div>}
        {returnPosition.restoring&&<p role="status">正在读取原会话并恢复原消息位置<button className="boss-btn" onClick={returnPosition.clear}>结束位置恢复</button></p>}
        {taskEntry&&<div className="boss-n02-source" aria-label="固定任务上下文"><strong>{taskEntry.task_reference.id} · 原任务版本 {taskEntry.task_reference.version}</strong><span>{taskContextError?"当前有效性核查失败，原选择仅供核查":taskContextChecking?"正在核查原任务与来源的当前有效性":"当前任务与来源版本已经核查"}</span><button className="boss-btn" data-conversation-return={"task:"+taskEntry.return_reference.task_id} onClick={()=>openBusiness(()=>actions.onOpenTask(taskEntry.return_reference.task_id))}>返回关联任务</button></div>}
        {taskContextError&&<div className="boss-n02-note error" role="alert">{taskContextError}<button className="boss-btn" onClick={()=>setRevision(value=>value+1)}>刷新任务上下文</button></div>}
        {currentBusinessContext?.entry&&<div className="boss-n02-source" aria-label="固定经营上下文"><strong>经营范围 {currentBusinessContext.entry.applied_scope.legal_entity_id} · {currentBusinessContext.entry.applied_scope.period_start} 至 {currentBusinessContext.entry.applied_scope.period_end}</strong><span>专题 {currentBusinessContext.entry.topic_reference?.page_id??"经营总览"} · 用途 {currentBusinessContext.entry.topic_reference?.use??"当前范围"} · 当前正式版本已经核查</span><span>原请求编号 {currentBusinessContext.entry.client_request_id}</span>{!currentBusinessContext.current_selection_active&&<><p>当前连接尚未采用此会话的原范围，请明确核查后继续。</p><button className="boss-btn" onClick={()=>{
          if(!chatId)throw new Error("经营会话缺少当前编号");
          const selectedChat=chatId,originalScope={...latestScope.current};
          void client.requestMutation<BusinessContext>("boss.conversation.business.read",{chat_id:selectedChat,adopt_selection:true}).then(result=>{
            if(!sameActiveN02Scope(originalScope,latestScope.current))return;
            verifyBusinessContext(result,selectedChat);setBusinessContext(result);setBusinessContextError("");
          }).catch(reason=>{
            if(sameActiveN02Scope(originalScope,latestScope.current)){
              setBusinessContext(null);
              setBusinessContextError(reason instanceof Error?reason.message:String(reason));
            }
          });
        }}>核查并采用此会话原范围</button></>}</div>}
        {businessContextError&&<div className="boss-n02-note error" role="alert">{businessContextError}<button className="boss-btn" onClick={()=>setRevision(value=>value+1)}>刷新经营上下文</button></div>}
        <details className="boss-chat-context-details"><summary>查看关联事项、资料版本与任务对象</summary>
        <Row name="关联事项" value={taskEntry?.task_reference.id??selected?.object_id??(contextRefs.length?contextRefs.map(ref=>ref.id).join("、"):origin?.date?"晨间事项 · "+String(origin.date):"尚未关联")}/>
        <Row name="资料版本" value={taskEntry?taskEntry.source_references.map(ref=>ref.id+" · 原版本 "+ref.version).join("；"):selected?.version??(documentRefs.length?documentRefs.map(ref=>ref.id+" · 原版本 "+(ref.recorded_version??"未知")+" / 当前 "+(ref.current_version??"未知")).join("；"):origin?.snapshot_sha256?"已保存当前清单快照":"待读取")}/>
        <Row name="任务对象" value={[...new Set([...(taskEntry?[taskEntry.task_reference.id]:[]),...taskRefs.map(ref=>ref.id),...latest?.artifacts.filter(value=>value.kind==="task").map(value=>value.id)??[]])].join("、")||"尚未关联交办"}/>
        </details>
        <div className="boss-n02-actions">{conversationReturn()&&<button className="boss-btn" onClick={actions.onReturn}><ArrowLeft size={16}/>{conversationReturn()?.label}</button>}</div>
      </section>
      <section className="boss-n02-panel boss-n02-conversation" aria-labelledby="boss-n02-conversation-title">
        <header className="boss-n02-heading"><h2 id="boss-n02-conversation-title">对话与任务运行</h2></header>
        <div className={"boss-n02-conversation-grid "+(!historyOpen?"boss-n02-history-hidden":"")}>
          <aside className="boss-n02-history" hidden={!historyOpen} aria-label="历史对话">
            <div className="boss-n02-heading"><h3>会话与任务</h3></div>
            <button className="boss-chat-search" onClick={onSearch}><Search size={16}/><span>搜索历史会话</span></button>
            {role==="BOSS"&&visible&&<BossArchivedSessions/>}
            {sessions.length?<ul>{sessions.map(value=><li key={value.key}><button aria-current={value.key===activeKey?"page":undefined} onClick={()=>onSelectChat(value.key)}><MessageCircle size={16}/><span>{value.title}<small>{value.updatedAt}</small></span></button></li>)}</ul>:<p className="boss-n02-empty">尚无可用会话</p>}
            <div className="boss-chat-history-note"><p>会话与对象分别保存</p><span>返回会话时恢复原消息位置；资料版本与已确认决定沿用对应业务记录。</span></div>
          </aside>
          <div className="boss-n02-message-column"><header className="boss-chat-thread-heading"><div><h2>{session?.title??"和 Boss Agent 聊天"}</h2><p>直接说你想处理的事</p></div><div className="boss-chat-toolbar"><button className="boss-btn" type="button" onClick={onNewChat}><Plus size={16}/>新对话</button><button className="boss-btn" type="button" aria-expanded={historyOpen} onClick={()=>setHistoryOpen(value=>!value)}><History size={16}/>{historyOpen?"收起历史":"历史对话"}</button>{conversationReturn()&&<button className="boss-btn" type="button" onClick={actions.onReturn}><ArrowLeft size={16}/>{conversationReturn()?.label}</button>}<span className="boss-n02-chip">{connectionStatus==="open"?"已连接":"连接中"}</span></div></header><div className="boss-n02-thread" aria-label="交办消息">{children}</div><AgentProcess run={latest} runs={view?.runs??[]} onSelect={setSelectedRunId}/><BossConversationKnowledge chatId={chatId} active={isActiveN02Scope(latestScope.current)} onSource={(id,version)=>openBusiness(()=>actions.onOpenSource(id,version))}/></div>
        </div>
        {error&&<div className="boss-n02-note error" role="alert">{error}<button className="boss-btn" onClick={()=>setRevision(value=>value+1)}>刷新结果</button></div>}
      </section>
    </div>
    <aside className="boss-n02-aside">
      <section className="boss-n02-panel" aria-labelledby="boss-n02-latest-title"><h2 id="boss-n02-latest-title">任务执行</h2><Row name="运行状态" value={latest?label(latest.status):"尚未运行"}/><Row name="已记录步骤" value={latest?latest.tool_steps.length+" 项":"尚未读取"}/>
        {latest?.tool_steps.length?<ol className="boss-chat-side-steps">{latest.tool_steps.slice(-3).map((step,index)=><li key={step.tool_call_id+index}><span>{String(latest.tool_steps.length-Math.min(latest.tool_steps.length,3)+index+1).padStart(2,"0")}</span><div><strong>{step.tool_id}</strong><p>{label(step.status)}</p></div></li>)}</ol>:<p>取得实际工具记录后显示执行步骤。</p>}
        {latest&&<button className="boss-btn" data-conversation-return="run:details" onClick={()=>openBusiness(()=>actions.onOpenPage("F24",latest.run_id))}>查看过程</button>}
        <div className="boss-n02-actions"><button className="boss-btn" onClick={()=>setRevision(value=>value+1)}><RefreshCw size={16}/>刷新结果</button></div>
        <details aria-label="原请求记录"><summary>原请求记录（{receipts.length}）</summary>{receipts.length?receipts.map(receipt=><div className="boss-n02-source" key={receipt.client_request_id}><strong>{receipt.client_request_id}</strong><span>{receipt.request_state==="ADMITTED"?"已经接收":label(receipt.request_state)}</span><span>原轮次 {receipt.turn_id}</span>{receipt.run_id?<button className="boss-btn" onClick={()=>setSelectedRunId(receipt.run_id!)}>读取关联运行</button>:<p>当前没有已建立的运行记录。读取原请求不会重新执行。</p>}</div>):<p>当前会话没有一般请求记录。晨间绑定按原业务记录核查。</p>}</details>
      </section>
      <section className="boss-n02-panel" aria-label="授权与必要决定"><h2>授权与必要决定</h2><Row name="执行对象" value={latest?.authorization_summary?.target_label??taskEntry?.task_reference.id??"尚未核查"}/><Row name="有效授权" value={latest?.authorization_summary?label(latest.authorization_summary.state):"尚未取得当前授权结果"}/><Row name="待补条件" value={latest?.authorization_summary?latest.authorization_summary.waiting_inputs.length+" 项":"尚未取得完整条件"}/>{latest?.authorization_summary?.waiting_inputs.map((item,index)=><p className="boss-n02-note warn" key={index}>{item}</p>)}{latest?.authorization_summary?.coverage==="PARTIAL"&&<p>当前条件清单尚不完整。</p>}<div className="boss-n02-actions"><button className="boss-btn" data-conversation-return="decisions" onClick={()=>openBusiness(()=>actions.onOpenPage("F28"))}>核对并确认</button><button className="boss-btn" data-conversation-return="authorizations" onClick={()=>openBusiness(()=>actions.onOpenPage("N10"))}>查看授权详情</button></div></section>
      <section className="boss-n02-panel" aria-label="来源与依据" tabIndex={-1}><h2>资料与产物</h2><Row name="已保存产物" value={latest?latest.artifacts.length+" 项":"尚未读取"}/><Row name="来源引用" value={latest?documentRefs.length+" 项":"尚未读取"}/>
        {taskEntry?.source_references.map(source=><div className="boss-n02-source" key={"task-entry-"+source.id} data-task-entry-source={source.id}><strong>{source.id}</strong><span>任务入口原来源版本 {source.version} · {taskContextError||taskContextChecking?"当前有效性待核查":"当前固定来源已经核查"}</span><button className="boss-btn" data-conversation-return={"entry-source:"+source.id} onClick={()=>openBusiness(()=>actions.onOpenSource(source.id,source.version))}>查看依据</button></div>)}
        {contextRefs.length?contextRefs.map(reference=><ContextReferenceDetails key={reference.kind+reference.id+reference.recorded_version} reference={reference} onOpenSource={(id,version)=>openBusiness(()=>actions.onOpenSource(id,version))} onOpenTask={id=>openBusiness(()=>actions.onOpenTask(id))}/>):selected?.source_refs?.length?selected.source_refs.map(source=><div className="boss-n02-source" key={source.kind+source.id}><strong>{source.id}</strong><span>版本 {source.version??"未知"}</span>{source.kind==="document"&&<button className="boss-btn" data-conversation-return={"morning-source:"+source.id} onClick={()=>openBusiness(()=>actions.onOpenSource(source.id,source.version??undefined))}>核查来源</button>}</div>):<p>当前运行没有已记录的来源或对象引用。</p>}
        <p className="boss-n02-note">上下文关联及工具读取分别记录，附件保存状态和业务来源采用分别核查。</p>
        <details aria-label="当前已保存附件"><summary>当前已保存附件（{attachmentError?"待核查":attachments.length}）</summary>
          {attachmentLoading&&<p role="status">正在重新核查此会话保存的附件及原始文件状态。</p>}
          {attachmentError&&<div role="alert" className="boss-n02-note error">附件读取失败，不能判定当前附件为空：{attachmentError}<button className="boss-btn" type="button" onClick={()=>setRevision(value=>value+1)}>重新读取当前附件</button></div>}
          {!attachmentError&&(attachments.length?attachments.map(file=><div className="boss-n02-source" key={file.attachment_id}><strong>{file.original_name??file.stored_name??"附件名称未知"}</strong><span>{file.mime_type??"类型未知"} · {file.size_bytes===null?"当前大小未知":file.size_bytes+" bytes"} · {fileState[file.processing_state]}</span>{file.processing_state!=="STORED"&&<p className="boss-n02-note warn">上传记录大小：{file.recorded_size_bytes===null?"未知":file.recorded_size_bytes+" bytes"}。当前附件不能作为已核查的业务依据。</p>}</div>):!attachmentLoading&&<p>本次读取确认暂无已保存附件。当前选择及未发送附件保留在输入区域。</p>)}</details>
      </section>
    </aside>
    <div className="boss-chat-below">
    <section className="boss-n02-panel boss-chat-deliverables" aria-labelledby="boss-chat-deliverables-title">
      <header className="boss-n02-heading"><h2 id="boss-chat-deliverables-title">关联资料与产物</h2><span className="boss-n02-chip">当前运行</span></header>
      <p>从已保存的执行记录打开业务结果，核查当前对象和来源。</p>
      {latest?.artifacts.length?<div className="boss-chat-artifact-grid">{latest.artifacts.map(reference=><button className="boss-chat-artifact" key={reference.kind+reference.id} data-conversation-return={"deliverable:"+latest.run_id+":"+reference.kind+":"+reference.id} onClick={()=>void openArtifact(latest,reference)}><span className="boss-chat-file-icon"><FileText size={20}/></span><span><strong>{kindLabel[reference.kind]}</strong><small>{reference.id}</small></span><span>查看产物</span></button>)}</div>:<p className="boss-n02-empty">当前尚无已保存的产物。结果生成后可以在这里查看。</p>}
    </section>
    <section className="boss-n02-panel boss-chat-metrics" aria-labelledby="boss-chat-metrics-title">
      <header className="boss-n02-heading"><h2 id="boss-chat-metrics-title">经营指标与来源核查</h2><button className="boss-btn" data-conversation-return="query" onClick={()=>openBusiness(()=>actions.onOpenPage("F03"))}>查看查询明细</button></header><p>查看本次查询的指标、期间、范围和计算依据。</p>
      <BossConversationMetrics key={String(token)+":"+chatId+":"+latest?.run_id} chatId={chatId} runId={latest?.run_id??null} queries={latest?.artifacts.filter(reference=>reference.kind==="query")??[]} active={isActiveN02Scope(latestScope.current)} refreshVersion={revision} onSource={(id,version)=>openBusiness(()=>actions.onOpenSource(id,version))} onOpen={id=>{const reference=latest?.artifacts.find(item=>item.kind==="query"&&item.id===id);if(latest&&reference)void openArtifact(latest,reference);}}/>
    </section>
    </div>
    <Dialog.Root open={artifactOpen&&visible} onOpenChange={open=>{setArtifactOpen(open);if(!open)++artifactGeneration.current;}}><Dialog.Portal><Dialog.Overlay className="boss-n02-dialog-overlay"/><Dialog.Content className="boss-n02-dialog" onCloseAutoFocus={event=>{event.preventDefault();if(visible&&artifactFocus.current?.isConnected)artifactFocus.current.focus({preventScroll:true});}}><Dialog.Title>当前产物与依据</Dialog.Title><Dialog.Description>根据当前会话的原运行引用，重新核查实际对象与来源。</Dialog.Description><Dialog.Close className="boss-icon-button" aria-label="关闭产物详情"><X size={18}/></Dialog.Close>
      {artifactLoading&&<p role="status">正在核查当前产物</p>}
      {artifactError&&<p role="alert" className="boss-n02-note error">{artifactError}</p>}
      {artifact&&<>
        <Row name="产物类型" value={kindLabel[artifact.kind]}/><Row name="对象编号" value={artifact.id}/>
        {["status","version","purpose","body","send_state","delivery_state","reply_state"].filter(key=>artifact.data[key]!==undefined).map(key=><Row key={key} name={{status:"当前状态",version:"当前版本",purpose:"交办目的",body:"消息正文",send_state:"发送状态",delivery_state:"送达状态",reply_state:"回复状态"}[key]??key} value={artifact.data[key]===null?"当前不能采用":String(artifact.data[key])}/>)}
        {artifact.kind==="task"&&<button className="boss-btn" onClick={()=>{setArtifactOpen(false);openBusiness(()=>actions.onOpenTask(artifact.id),artifactFocus.current);}}>打开交办</button>}
        {artifact.evidence?.sources.map(source=><div className="boss-n02-source" key={source.source_id}><strong>{source.source_id}</strong><span>版本 {source.version} · {source.published_at??"发布时间未知"} · {source.author_contact_id??"作者待核查"}</span><button className="boss-btn" onClick={()=>{setArtifactOpen(false);openBusiness(()=>actions.onOpenSource(source.source_id,source.version),artifactFocus.current);}}>查看依据</button></div>)}
      </>}
      {artifact?.kind==="query"&&<QueryDetails data={artifact.data}/>}
    </Dialog.Content></Dialog.Portal></Dialog.Root>
  </div>;
}

function ContextReferenceDetails({reference:ref,onOpenSource,onOpenTask}:{reference:ContextReference;onOpenSource:(id:string,version?:string)=>void;onOpenTask:(id:string)=>void}){
  const names:Record<string,string>={source_type:"资料类型",author_contact_id:"作者编号",author_kind:"作者类型",author_display_name:"作者名称",generator_version:"生成器版本",published_at:"发布时间",observed_at:"观察时间",business_as_of:"业务时间",valid_from:"有效开始",valid_until:"有效结束",coverage:"资料范围",business_basis:"业务口径",business_basis_description:"口径说明",allowed_use:"允许用途"};
  return <div className="boss-n02-source" data-reference-id={ref.id}>
    <strong>{ref.id}</strong><span>原版本 {ref.recorded_version??"未知"} · 当前版本 {ref.current_version??"无法读取"}</span>
    <span>{label(ref.reference_state)} · {label(ref.adoption_state)}{ref.current_validity?" · "+ref.current_validity:""}{ref.current_object_state?" · "+ref.current_object_state:""}</span>
    <span>{ref.support.some(item=>item.origin==="TOOL_RESULT")?"包含实际工具读取关系":"可信上下文选定关系"}</span>
    <details><summary>查看引用元信息</summary>
      {ref.source_metadata?Object.entries(names).map(([field,name])=><Row key={field} name={name} value={ref.source_metadata?.[field]??"未知"}/>):ref.kind==="document"&&<p>当前元信息不可采用，原引用记录保留。</p>}
      {ref.source_refs.map(source=><div key={source.source_id}><p>{source.source_id} · 原版本 {source.version??"未知"} / 当前 {source.current_version??"未知"} · {source.status}</p><button className="boss-btn" data-conversation-return={"reference-link:"+ref.kind+":"+ref.id+":"+source.source_id} disabled={source.current_version===null} onClick={()=>onOpenSource(source.source_id,source.version??undefined)}>核查关联来源 {source.source_id}</button></div>)}
    </details>
    {ref.kind==="document"&&<button className="boss-btn" data-conversation-return={"reference-document:"+ref.id} disabled={ref.current_version===null} onClick={()=>onOpenSource(ref.id,ref.recorded_version??undefined)}>查看依据</button>}
    {ref.kind==="task"&&<button className="boss-btn" data-conversation-return={"reference-task:"+ref.id} disabled={ref.adoption_state!=="CURRENT"} onClick={()=>onOpenTask(ref.id)}>打开交办</button>}
  </div>;
}

function QueryDetails({data}:{data:Record<string,unknown>}){
  const query=data as {context_snapshot:Record<string,unknown>;values:{metric_id:string;period_scope:string;scope_description:string;value:string|null;unit:string;formula:string;definition_version:string;display_rounding:string}[];comparison:{state:string;reasons:string[]};missing_fields:string[];unexplained_causes:string[];detail_refs:string[]};
  const fields:Record<string,string>={period_start:"查询开始",period_end:"查询结束",comparison_start:"比较开始",comparison_end:"比较结束",region_id:"区域",region_ids:"全部区域",product_ids:"产品",metric_ids:"指标",legal_entity_id:"法人主体",currency:"币种",quantity_unit:"数量单位",trade_scope:"交易范围",definition_version:"指标定义版本",business_basis:"业务口径",settlement_state:"结算状态",parent_query_id:"父查询",scenario_id:"经营资料范围"};
  return <section aria-label="查询完整结果"><h3>查询条件与结果</h3>{Object.entries(fields).filter(([field])=>query.context_snapshot[field]!==undefined).map(([field,name])=><Row key={field} name={name} value={Array.isArray(query.context_snapshot[field])?(query.context_snapshot[field] as string[]).join("、"):String(query.context_snapshot[field])}/>)}<div className="boss-n02-query-table"><table><thead><tr>{["指标","期间","范围","数值","单位","公式","定义版本","显示规则"].map(name=><th key={name}>{name}</th>)}</tr></thead><tbody>{query.values.map((value,index)=><tr key={index}><th>{value.metric_id}</th><td>{value.period_scope}</td><td>{value.scope_description}</td><td>{value.value??"当前无法确定"}</td><td>{value.unit}</td><td>{value.formula}</td><td>{value.definition_version}</td><td>{value.display_rounding}</td></tr>)}</tbody></table></div><Row name="比较状态" value={query.comparison.state}/>{query.comparison.reasons.map(reason=><p key={reason}>{reason}</p>)}<Row name="资料缺口" value={query.missing_fields.join("、")||"没有已记录缺口"}/>{query.unexplained_causes.map(value=><p key={value}>{value}</p>)}<details><summary>查看结果明细编号</summary>{query.detail_refs.map(id=><p key={id}>{id}</p>)}</details></section>;
}

const toolNames:Record<string,string>={query_metrics:"查询经营数据",read_evidence:"读取资料原文",bossSectorRead:"读取专题数据",bossTasksRead:"读取任务与承诺",bossMeetingsRead:"读取会议资料",bossEvidenceRead:"读取来源原文",bossWorkspaceRead:"读取工作资料",conversationRead:"读取会话记录",create_assignment:"创建交办",send_assignment:"发送交办",read_assignment:"读取交办状态",morningListRead:"读取晨间清单",morningDetailRead:"读取事项详情",morningSourceRead:"读取事项来源",todayRead:"读取今日工作",ownerPlansRead:"读取本人计划",assignmentSourcesRead:"读取交办来源",businessOverviewRead:"读取经营概览"};

const runNames:Record<string,string>={RUNNING:"正在处理",QUEUED:"等待中",SUCCEEDED:"已完成",FAILED:"未完成",CANCELED:"已取消",WAITING_INPUT:"等待补充",TIMED_OUT:"超时",INTERRUPTED:"已中断",UNKNOWN:"待确认"};
function AgentProcess({run,runs,onSelect}:{run:Run|undefined;runs:Run[];onSelect:(id:string)=>void}){
  if(!runs.length)return null;
  const steps=run?.tool_steps??[];
  const running=run?.status==="RUNNING"||run?.status==="QUEUED";
  const state=run?.status?(runNames[run.status]??"已完成"):"等待中";
  const stepState=(status:string)=>status==="SUCCEEDED"?"已完成":runNames[status]??"已完成";
  return <section className="boss-n02-agent" aria-label="处理过程" aria-live="polite">
    <header className="boss-n02-agent-head"><h3>处理过程</h3>
      {runs.length>1&&<select aria-label="选择运行" value={run?.run_id??""} onChange={event=>onSelect(event.target.value)}>{runs.map(item=><option key={item.run_id} value={item.run_id}>{item.started_at} · {runNames[item.status]??"已完成"}</option>)}</select>}
      <span className={"boss-n02-chip"+(running?" boss-n02-chip-active":"")}>{state}</span>
    </header>
    <ol className="boss-n02-agent-steps">
      {steps.map((step,index)=><li key={step.tool_call_id+index} data-state={step.status}><span className="boss-n02-agent-index">{String(index+1).padStart(2,"0")}</span><div><strong>{toolNames[step.tool_id]??step.tool_id}</strong><small>{step.status?stepState(step.status):"已完成"}</small></div></li>)}
      {!steps.length&&run&&<li data-state={run.status}><span className="boss-n02-agent-index">··</span><div><strong>{running?"正在理解需求":"本次未调用工具"}</strong><small>{state}</small></div></li>}
    </ol>
    {run?.tool_errors.length?<div className="boss-n02-agent-errors">{run.tool_errors.map((error,index)=><p key={error.tool_id+index}>{(toolNames[error.tool_id]??error.tool_id)+"未完成"} · {error.error_type}</p>)}</div>:null}
  </section>;
}
