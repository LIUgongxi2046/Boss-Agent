import {useEffect,useRef,useState,type ReactNode} from "react";
import * as Dialog from "@radix-ui/react-dialog";
import {ArrowLeft,FileText,History,MessageCircle,Plus,RefreshCw,Search,X} from "lucide-react";
import {useClient} from "@/providers/ClientProvider";
import "./boss-n02.css";

export type ConversationActions={onOpenTask:(id:string)=>void;onOpenSource:(id:string)=>void;onOpenMessages:()=>void;onReturn:()=>void};
type Session={key:string;chatId:string;title:string;updatedAt:string};
type Reference={kind:"query"|"task"|"morning_list"|"message"|"message_draft";id:string;recorded_version:string|null};
type ContextReference={kind:string;id:string;recorded_version:string|null;current_version:string|null;reference_state:string;adoption_state:string;current_validity:string|null;current_object_state:string|null;source_metadata:Record<string,string|null>|null;source_refs:{source_id:string;version:string|null;current_version:string|null;status:string}[];support:{origin:string;tool_id:string|null;tool_call_id:string|null}[]};
type Run={run_id:string;status:string;stop_reason:string|null;started_at:string;finished_at:string|null;configuration_id:string;configuration_version:string;tool_steps:{tool_id:string;tool_call_id:string;status:string;version?:string;task_version?:string}[];tool_errors:{tool_id:string;error_type:string}[];artifacts:Reference[];context_references:ContextReference[];origin_references:Record<string,Record<string,unknown>>};
type View={session_id:string;chat_id:string;runs:Run[];business_authorization_granted:false;business_mutation_performed:false};
type RequestReceipt={client_request_id:string;outcome:"RECORDED";request_state:string;run_id:string|null;chat_id:string;session_id:string;turn_id:string;write_performed_by_lookup:false;business_authority_granted:false};
type Attachment={attachment_id:string;stored_name:string|null;original_name:string|null;mime_type:string|null;size_bytes:number|null;content_sha256:string|null;recorded_size_bytes:number|null;recorded_content_sha256:string|null;user_message_index:number|null;processing_state:"STORED"|"MISSING"|"CHANGED"|"REFERENCE_UNAVAILABLE"};
type Artifact={run_id:string;kind:Reference["kind"];id:string;data:Record<string,unknown>;evidence:{sources:{source_id:string;version:string;published_at?:string;author_contact_id?:string}[]}|null};
type Props={role:"BOSS"|"MAINTAINER";visible:boolean;activeKey:string|null;sessions:Session[];onNewChat:()=>void;onSelectChat:(key:string)=>void;onSearch:()=>void;actions:ConversationActions;children:ReactNode};
const stateLabel:Record<string,string>={RUNNING:"正在执行",QUEUED:"正在排队",SUCCEEDED:"运行完成",WAITING_INPUT:"等待补充条件",FAILED:"运行失败",CANCELED:"已经取消",TIMED_OUT:"执行超时",UNKNOWN:"结果待核查",INTERRUPTED:"执行中断",CURRENT:"当前可以读取",NEEDS_REVIEW:"需要重新核查",UNAVAILABLE:"当前无法采用",VERSION_CHANGED:"当前版本已经变化",VERSION_UNRECORDED:"原版本未记录",INACTIVE:"当前已经停用",MISSING_OR_FORBIDDEN:"当前无法访问",UNSUPPORTED_KIND:"当前种类无法读取"};
const kindLabel:Record<Reference["kind"],string>={query:"查询结果",task:"交办任务",morning_list:"晨间清单",message:"已保存消息",message_draft:"消息草稿"};
const label=(value:string)=>stateLabel[value]??value;
const fileState={STORED:"已经保存",MISSING:"文件缺少",CHANGED:"内容已经变化，需要重新核查",REFERENCE_UNAVAILABLE:"文件引用无法确认"};
function Row({name,value}:{name:string;value:ReactNode}){return <div className="boss-n02-kv"><span>{name}</span><strong>{value}</strong></div>;}
export function BossConversationWorkspace({role,visible,activeKey,sessions,onNewChat,onSelectChat,onSearch,actions,children}:Props){
  const {client,token}=useClient();
  const session=sessions.find(value=>value.key===activeKey),chatId=session?.chatId??(activeKey?.startsWith("websocket:")?activeKey.slice(10):null);
  const [view,setView]=useState<View|null>(null),[attachments,setAttachments]=useState<Attachment[]>([]),[error,setError]=useState(""),[revision,setRevision]=useState(0);
  const [receipts,setReceipts]=useState<RequestReceipt[]>([]);
  const [artifact,setArtifact]=useState<Artifact|null>(null),[artifactOpen,setArtifactOpen]=useState(false),[artifactError,setArtifactError]=useState(""),[artifactLoading,setArtifactLoading]=useState(false);
  const [historyOpen,setHistoryOpen]=useState(false),[selectedRunId,setSelectedRunId]=useState("");
  const scope=useRef<{client:typeof client;token:typeof token;chatId:string|null;role:typeof role}|null>(null);
  const workspace=useRef<HTMLDivElement|null>(null),businessReturn=useRef<{chatId:string|null;focus:HTMLElement|null;scrollTop:number}|null>(null);
  const generation=useRef(0),artifactGeneration=useRef(0),progress=useRef<HTMLDivElement|null>(null),artifactFocus=useRef<HTMLElement|null>(null);
  useEffect(()=>{
    const current=++generation.current;++artifactGeneration.current;setArtifact(null);setArtifactOpen(false);setArtifactError("");
    if(scope.current?.client!==client||scope.current?.token!==token||scope.current?.chatId!==chatId||scope.current?.role!==role){
      scope.current={client,token,chatId,role};setView(null);setAttachments([]);setReceipts([]);setError("");setSelectedRunId("");businessReturn.current=null;
    }
    if(role!=="BOSS"||!visible||!chatId)return;
    let disposed=false,timer:ReturnType<typeof setTimeout>|undefined,attachmentRevision:string|null=null;
    const read=async()=>{
      try{
        const [result,requests]=await Promise.all([client.requestMutation<View>("boss.conversation.read",{chat_id:chatId}),client.requestMutation<RequestReceipt[]>("boss.conversation.requests",{chat_id:chatId})]);
        if(disposed||generation.current!==current)return;
        if(result.chat_id!==chatId||result.session_id!=="websocket:"+chatId||result.business_authorization_granted!==false||result.business_mutation_performed!==false)throw new Error("当前会话读取范围不符");
        if(requests.some(row=>row.chat_id!==chatId||row.session_id!=="websocket:"+chatId||row.write_performed_by_lookup!==false||row.business_authority_granted!==false))throw new Error("原请求记录与当前会话范围不符");
        const last=result.runs.at(-1),nextAttachmentRevision=last?last.run_id+":"+last.status+":"+last.finished_at:"NO_RUN";
        if(nextAttachmentRevision!==attachmentRevision){
          const files=await client.requestMutation<{attachments:Attachment[]}>("boss.conversation.attachments",{chat_id:chatId});
          if(disposed||generation.current!==current)return;
          setAttachments(files.attachments);attachmentRevision=nextAttachmentRevision;
        }
        setView(result);setReceipts(requests);setError("");timer=setTimeout(()=>void read(),2000);
      }catch(failure){if(!disposed&&generation.current===current){setView(null);setAttachments([]);setReceipts([]);setError(failure instanceof Error?failure.message:String(failure));}}
    };
    void read();return()=>{disposed=true;if(timer)clearTimeout(timer);};
  },[role,visible,chatId,client,token,revision]);
  useEffect(()=>()=>{++artifactGeneration.current;},[]);
  useEffect(()=>{
    const saved=businessReturn.current;
    if(visible&&saved?.chatId===chatId){if(workspace.current)workspace.current.scrollTop=saved.scrollTop;saved.focus?.focus({preventScroll:true});businessReturn.current=null;}
  },[visible,chatId]);
  const openBusiness=(action:()=>void)=>{businessReturn.current={chatId,focus:document.activeElement instanceof HTMLElement?document.activeElement:null,scrollTop:workspace.current?.scrollTop??0};action();};
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
  const latest=view?.runs.find(run=>run.run_id===selectedRunId)??view?.runs.at(-1),origin=latest?.origin_references.morning_context,selected=origin?.selected_item_ref as {object_id?:string;version?:string;source_refs?:{kind:string;id:string;version:string|null}[]}|undefined;
  const contextRefs=latest?.context_references??[],taskRefs=contextRefs.filter(ref=>ref.kind==="task"),documentRefs=contextRefs.filter(ref=>ref.kind==="document");
  return <div className="boss-n02" aria-label="聊天交办工作区" ref={workspace}>
    <div className="boss-n02-main">
      <section className="boss-n02-panel boss-n02-context" aria-labelledby="boss-n02-context-title">
        <header className="boss-n02-heading"><h2 id="boss-n02-context-title">当前会话与关联事项</h2></header>
        <Row name="关联事项" value={selected?.object_id??(contextRefs.length?contextRefs.map(ref=>ref.id).join("、"):origin?.date?"晨间事项 · "+String(origin.date):"尚未关联")}/><Row name="资料版本" value={selected?.version??(documentRefs.length?documentRefs.map(ref=>ref.id+" · 原版本 "+(ref.recorded_version??"未知")+" / 当前 "+(ref.current_version??"未知")).join("；"):origin?.snapshot_sha256?"已保存当前清单快照":"待读取")}/><Row name="任务对象" value={[...new Set([...taskRefs.map(ref=>ref.id),...latest?.artifacts.filter(value=>value.kind==="task").map(value=>value.id)??[]])].join("、")||"尚未关联交办"}/>
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
          <div className="boss-n02-message-column"><h2>交办消息</h2><div className="boss-n02-thread" aria-label="交办消息">{children}</div></div>
        </div>
        <div className="boss-n02-progress" ref={progress} tabIndex={-1} aria-labelledby="boss-n02-progress-title">
          <h2 id="boss-n02-progress-title">可观察执行步骤</h2>
          {!!view?.runs.length&&<label className="boss-n02-session-select">关联运行<select aria-label="关联运行" value={latest?.run_id??""} onChange={event=>setSelectedRunId(event.target.value)}>{view.runs.map(run=><option key={run.run_id} value={run.run_id}>{run.started_at} · {label(run.status)}</option>)}</select></label>}
          {error?<div className="boss-n02-note error" role="alert">{error}<button className="boss-btn" onClick={()=>setRevision(value=>value+1)}>重新读取当前记录</button></div>:chatId&&!view?<p role="status">正在核查当前会话与运行记录</p>:!latest?<p className="boss-n02-note">尚未产生运行记录。可以输入问题、补充材料或说明需要推进的事项。</p>:<>
            <Row name="运行编号" value={latest.run_id}/><Row name="执行结果" value={label(latest.status)}/><Row name="结束原因" value={latest.stop_reason??"尚未结束"}/><Row name="开始时间" value={latest.started_at}/><Row name="结束时间" value={latest.finished_at??"尚未结束"}/><Row name="采用配置" value={latest.configuration_id+" · 版本 "+latest.configuration_version}/>
            {latest.tool_steps.length?<ol className="boss-n02-steps">{latest.tool_steps.map((step,index)=><li key={step.tool_call_id+index}><FileText size={16}/><span>{step.tool_id}</span><strong>{step.status?label(step.status):"结果已保存"}</strong></li>)}</ol>:<p>本次没有已记录的工具步骤。</p>}
            <div className="boss-n02-actions">{latest.artifacts.map(reference=><button className="boss-btn" key={reference.kind+reference.id} onClick={()=>void openArtifact(latest,reference)}>{kindLabel[reference.kind]}<span>{reference.id}</span></button>)}</div>
          </>}
        </div>
      </section>
    </div>
    <aside className="boss-n02-aside">
      <section className="boss-n02-panel" aria-labelledby="boss-n02-latest-title"><h2 id="boss-n02-latest-title">持续进展与异常</h2><Row name="运行状态" value={latest?label(latest.status):"尚未运行"}/><Row name="必要决定" value="通过对应业务入口核查"/><Row name="历史阅读位置" value="返回时保留"/>
        <div className="boss-n02-actions"><button className="boss-btn" onClick={()=>{setSelectedRunId("");progress.current?.scrollIntoView({block:"nearest"});progress.current?.focus();}}>查看最新进展</button><button className="boss-btn" onClick={()=>setRevision(value=>value+1)}><RefreshCw size={16}/>读取原执行结果</button></div>
        {latest?.tool_errors.map((value,index)=><p className="boss-n02-note error" key={value.tool_id+index}>{value.tool_id} · {value.error_type}</p>)}<p className="boss-n02-note warn">执行结果未知时，请读取原记录核查。发送、送达、回复和交办完成分别记录。</p>
        <details aria-label="原请求记录"><summary>原请求记录（{receipts.length}）</summary>{receipts.length?receipts.map(receipt=><div className="boss-n02-source" key={receipt.client_request_id}><strong>{receipt.client_request_id}</strong><span>{receipt.request_state==="ADMITTED"?"已经接收":label(receipt.request_state)}</span><span>原轮次 {receipt.turn_id}</span>{receipt.run_id?<button className="boss-btn" onClick={()=>{setSelectedRunId(receipt.run_id!);progress.current?.scrollIntoView({block:"nearest"});progress.current?.focus();}}>读取关联运行</button>:<p>当前没有已建立的运行记录。读取原请求不会重新执行。</p>}</div>):<p>当前会话没有一般请求记录。晨间绑定按原业务记录核查。</p>}</details>
        <div className="boss-n02-actions"><button className="boss-btn" onClick={()=>openBusiness(actions.onOpenMessages)}>查看消息草稿与回复</button><button className="boss-btn" onClick={()=>openBusiness(()=>actions.onOpenTask(""))}>准备交办</button></div>
      </section>
      <section className="boss-n02-panel" aria-label="来源与依据"><h2>来源与依据</h2>{contextRefs.length?contextRefs.map(reference=><ContextReferenceDetails key={reference.kind+reference.id+reference.recorded_version} reference={reference} onOpenSource={id=>openBusiness(()=>actions.onOpenSource(id))} onOpenTask={id=>openBusiness(()=>actions.onOpenTask(id))}/>):selected?.source_refs?.length?selected.source_refs.map(source=><div className="boss-n02-source" key={source.kind+source.id}><strong>{source.id}</strong><span>版本 {source.version??"未知"}</span>{source.kind==="document"&&<button className="boss-btn" onClick={()=>openBusiness(()=>actions.onOpenSource(source.id))}>核查来源</button>}</div>):<p>当前运行没有已记录的来源或对象引用。</p>}<p className="boss-n02-note">上下文关联及工具读取分别记录，附件保存状态和业务来源采用分别核查。</p>
        <details aria-label="当前已保存附件"><summary>当前已保存附件（{attachments.length}）</summary>{attachments.length?attachments.map(file=><div className="boss-n02-source" key={file.attachment_id}><strong>{file.original_name??file.stored_name??"附件名称未知"}</strong><span>{file.mime_type??"类型未知"} · {file.size_bytes===null?"当前大小未知":file.size_bytes+" bytes"} · {fileState[file.processing_state]}</span>{file.processing_state!=="STORED"&&<p className="boss-n02-note warn">上传记录大小：{file.recorded_size_bytes===null?"未知":file.recorded_size_bytes+" bytes"}。当前附件不能作为已核查的业务依据。</p>}</div>):<p>尚无已保存附件。当前选择及未发送附件保留在输入区域。</p>}</details>
      </section>
    </aside>
    <Dialog.Root open={artifactOpen&&visible} onOpenChange={open=>{setArtifactOpen(open);if(!open)++artifactGeneration.current;}}><Dialog.Portal><Dialog.Overlay className="boss-n02-dialog-overlay"/><Dialog.Content className="boss-n02-dialog" onCloseAutoFocus={event=>{event.preventDefault();if(visible&&artifactFocus.current?.isConnected)artifactFocus.current.focus({preventScroll:true});}}><Dialog.Title>当前产物与依据</Dialog.Title><Dialog.Description>根据当前会话的原运行引用，重新核查实际对象与来源。</Dialog.Description><Dialog.Close className="boss-icon-button" aria-label="关闭产物详情"><X size={18}/></Dialog.Close>
      {artifactLoading&&<p role="status">正在核查当前产物</p>}{artifactError&&<p role="alert" className="boss-n02-note error">{artifactError}</p>}{artifact&&<><Row name="产物类型" value={kindLabel[artifact.kind]}/><Row name="对象编号" value={artifact.id}/>{["status","version","purpose","body","send_state","delivery_state","reply_state"].filter(key=>artifact.data[key]!==undefined).map(key=><Row key={key} name={{status:"当前状态",version:"当前版本",purpose:"交办目的",body:"消息正文",send_state:"发送状态",delivery_state:"送达状态",reply_state:"回复状态"}[key]??key} value={artifact.data[key]===null?"当前不能采用":String(artifact.data[key])}/>)}{artifact.kind==="task"&&<button className="boss-btn" onClick={()=>{setArtifactOpen(false);actions.onOpenTask(artifact.id);}}>查看交办详情</button>}{artifact.evidence?.sources.map(source=><div className="boss-n02-source" key={source.source_id}><strong>{source.source_id}</strong><span>版本 {source.version} · {source.published_at??"发布时间未知"} · {source.author_contact_id??"作者待核查"}</span><button className="boss-btn" onClick={()=>{setArtifactOpen(false);actions.onOpenSource(source.source_id);}}>查看来源原文</button></div>)}</>}
      {artifact?.kind==="query"&&<QueryDetails data={artifact.data}/>}
    </Dialog.Content></Dialog.Portal></Dialog.Root>
  </div>;
}

function ContextReferenceDetails({reference:ref,onOpenSource,onOpenTask}:{reference:ContextReference;onOpenSource:(id:string)=>void;onOpenTask:(id:string)=>void}){
  const names:Record<string,string>={source_type:"资料类型",author_contact_id:"作者编号",author_kind:"作者类型",author_display_name:"作者名称",generator_version:"生成器版本",published_at:"发布时间",observed_at:"观察时间",business_as_of:"业务时间",valid_from:"有效开始",valid_until:"有效结束",coverage:"资料范围",business_basis:"业务口径",business_basis_description:"口径说明",allowed_use:"允许用途"};
  return <div className="boss-n02-source" data-reference-id={ref.id}><strong>{ref.id}</strong><span>原版本 {ref.recorded_version??"未知"} · 当前版本 {ref.current_version??"无法读取"}</span><span>{label(ref.reference_state)} · {label(ref.adoption_state)}{ref.current_validity?" · "+ref.current_validity:""}{ref.current_object_state?" · "+ref.current_object_state:""}</span><span>{ref.support.some(item=>item.origin==="TOOL_RESULT")?"包含实际工具读取关系":"可信上下文选定关系"}</span><details><summary>查看引用元信息</summary>{ref.source_metadata?Object.entries(names).map(([field,name])=><Row key={field} name={name} value={ref.source_metadata?.[field]??"未知"}/>):<p>当前元信息不可采用，原引用记录保留。</p>}{ref.source_refs.map(source=><p key={source.source_id}>{source.source_id} · 原版本 {source.version??"未知"} / 当前 {source.current_version??"未知"} · {source.status}</p>)}</details>{ref.kind==="document"&&<button className="boss-btn" disabled={ref.current_version===null} onClick={()=>onOpenSource(ref.id)}>核查来源原文</button>}{ref.kind==="task"&&<button className="boss-btn" disabled={ref.adoption_state!=="CURRENT"} onClick={()=>onOpenTask(ref.id)}>查看交办详情</button>}</div>;
}

function QueryDetails({data}:{data:Record<string,unknown>}){
  const query=data as {context_snapshot:Record<string,unknown>;values:{metric_id:string;period_scope:string;scope_description:string;value:string|null;unit:string;formula:string;definition_version:string;display_rounding:string}[];comparison:{state:string;reasons:string[]};missing_fields:string[];unexplained_causes:string[];detail_refs:string[]};
  const fields:Record<string,string>={period_start:"查询开始",period_end:"查询结束",comparison_start:"比较开始",comparison_end:"比较结束",region_id:"区域",region_ids:"全部区域",product_ids:"产品",metric_ids:"指标",legal_entity_id:"法人主体",currency:"币种",quantity_unit:"数量单位",trade_scope:"交易范围",definition_version:"指标定义版本",business_basis:"业务口径",settlement_state:"结算状态",parent_query_id:"父查询",scenario_id:"经营资料范围"};
  return <section aria-label="查询完整结果"><h3>查询条件与结果</h3>{Object.entries(fields).filter(([field])=>query.context_snapshot[field]!==undefined).map(([field,name])=><Row key={field} name={name} value={Array.isArray(query.context_snapshot[field])?(query.context_snapshot[field] as string[]).join("、"):String(query.context_snapshot[field])}/>)}<div className="boss-n02-query-table"><table><thead><tr>{["指标","期间","范围","数值","单位","公式","定义版本","显示规则"].map(name=><th key={name}>{name}</th>)}</tr></thead><tbody>{query.values.map((value,index)=><tr key={index}><th>{value.metric_id}</th><td>{value.period_scope}</td><td>{value.scope_description}</td><td>{value.value??"当前无法确定"}</td><td>{value.unit}</td><td>{value.formula}</td><td>{value.definition_version}</td><td>{value.display_rounding}</td></tr>)}</tbody></table></div><Row name="比较状态" value={query.comparison.state}/>{query.comparison.reasons.map(reason=><p key={reason}>{reason}</p>)}<Row name="资料缺口" value={query.missing_fields.join("、")||"没有已记录缺口"}/>{query.unexplained_causes.map(value=><p key={value}>{value}</p>)}<details><summary>查看结果明细编号</summary>{query.detail_refs.map(id=><p key={id}>{id}</p>)}</details></section>;
}
