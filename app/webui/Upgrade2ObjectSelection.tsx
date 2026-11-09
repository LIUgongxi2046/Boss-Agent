import {useEffect,useRef,useState,type FormEvent} from "react";
import {validateRunResponse,type ObjectCandidates,type ObjectReceipt,type ObjectReference,type ObjectSource,type RunSnapshot,Upgrade2RunClient} from "./upgrade2-run-client";

type Pending={request_key:string;goal_revision:number;objects:ObjectReference[];sources:ObjectSource[][]};
const labels:Record<ObjectReference["entity_type"],string>={task:"任务",metric_detail:"指标详情",event:"事件",travel_plan:"出行计划",owner_goals_active:"本人目标",meeting_context:"会议上下文"};
const reasonLabels:Record<ObjectCandidates["unavailable_reasons"][number],string>={RUN_CANCELED:"运行已请求取消",RUN_STATE_UNAVAILABLE:"当前运行状态不允许新增对象选择",GOAL_ALREADY_SELECTED:"当前目标已经选择对象"};

export function MeetingScopeDetails({candidate}:{candidate:ObjectCandidates["objects"][number]}) {
  const {meeting,participants,members}=candidate.data;
  if(candidate.entity_type!=="meeting_context"||!meeting||typeof meeting!=="object"||Array.isArray(meeting)||!("meeting_id" in meeting)||meeting.meeting_id!==candidate.object_id||!("version" in meeting)||meeting.version!==candidate.version||!Array.isArray(participants)||!Array.isArray(members))throw new Error("会议候选内容与编号或版本不一致");
  return <div><h4>会议资料</h4><pre>{JSON.stringify(meeting,null,2)}</pre><h4>参会人员</h4>{participants.length?participants.map((person,index)=><pre key={index}>{JSON.stringify(person,null,2)}</pre>):<p>没有参会人员记录。</p>}<h4>关联对象</h4>{members.length?members.map((member,index)=><pre key={index}>{JSON.stringify(member,null,2)}</pre>):<p>没有关联对象记录。</p>}</div>;
}

export function ObjectSelectionAvailability({catalog}:{catalog:ObjectCandidates}) {
  return catalog.selection_allowed?<p>当前运行允许选择对象。</p>:<div role="status"><p>当前运行暂不可选择对象：</p><ul>{catalog.unavailable_reasons.map(reason=><li key={reason}>{reasonLabels[reason]}（{reason}）</li>)}</ul></div>;
}

export function ObjectChoices({catalog,selected,canSelect,onChange,onSubmit}:{catalog:ObjectCandidates;selected:string[];canSelect:boolean;onChange:(keys:string[])=>void;onSubmit:(event:FormEvent<HTMLFormElement>)=>void}) {
  const allowed=canSelect&&catalog.selection_allowed;
  return <form onSubmit={onSubmit}>{catalog.objects.map(item=>{const key=JSON.stringify([item.entity_type,item.object_id]);return <article key={key}>
    <label><input type="checkbox" disabled={!allowed} checked={selected.includes(key)} onChange={event=>onChange(event.target.checked?[...selected,key]:selected.filter(value=>value!==key))}/>{labels[item.entity_type]} · {item.object_id} · 版本 {item.version}</label>
    <p>摘要 {item.sha256}</p><p>来源 {item.source_refs.length?item.source_refs.map(source=>source.source_id+" · 版本 "+source.version+" · 摘要 "+source.sha256).join("；"):"该对象没有来源引用"}</p>
    <details><summary>查看对象内容</summary><pre>{JSON.stringify(item.data,null,2)}</pre></details>
  </article>;})}<button type="submit" disabled={!allowed||selected.length===0||selected.length>100}>确认对象选择</button></form>;
}

function readPending(key:string):Pending|null {
  const raw=sessionStorage.getItem(key);
  if(raw===null)return null;
  const value=JSON.parse(raw) as Pending;
  validateRunResponse("object_scope_request",{expected_goal_revision:value.goal_revision,request_key:value.request_key,objects:value.objects});
  if(!Array.isArray(value.sources)||value.sources.length!==value.objects.length)throw new Error("原对象选择来源记录无效");
  validateRunResponse("object_scope_receipt",{run_id:"pending",goal_revision:value.goal_revision,request_key:value.request_key,objects:value.objects.map((item,index)=>({...item,source_refs:value.sources[index]}))});
  return value;
}

export function Upgrade2ObjectSelection({client,snapshot,connected,enabled,token,getToken,pendingScopeKey,onBlockChange}:{client:Upgrade2RunClient;snapshot:RunSnapshot;connected:boolean;enabled:boolean;token:string;getToken:()=>string;pendingScopeKey:string;onBlockChange:(value:boolean)=>void}) {
  const storageKey="boss:upgrade2:object-scope:"+JSON.stringify([pendingScopeKey,snapshot.run_id]);
  const [pending,setPending]=useState<Pending|null>(()=>readPending(storageKey));
  const [catalog,setCatalog]=useState<ObjectCandidates|null>(null);
  const [meetingCatalog,setMeetingCatalog]=useState<ObjectCandidates|null>(null);
  const [meetingId,setMeetingId]=useState("");
  const [meetingMessage,setMeetingMessage]=useState("");
  const [meetingBusy,setMeetingBusy]=useState(false);
  const [selected,setSelected]=useState<string[]>([]);
  const [receipt,setReceipt]=useState<ObjectReceipt|null>(null);
  const [message,setMessage]=useState("");
  const [busy,setBusy]=useState(false);
  const [scopeBlocked,setScopeBlocked]=useState(true);
  const [refreshIndex,setRefreshIndex]=useState(0);
  const generation=useRef(0);
  const meetingGeneration=useRef(0);
  const live=useRef(true);
  useEffect(()=>{live.current=true;return()=>{live.current=false;};},[]);
  const latest=useRef({connected,token,getToken,run:snapshot.run_id,goal:snapshot.goal_revision});
  latest.current={connected,token,getToken,run:snapshot.run_id,goal:snapshot.goal_revision};
  const access=connected&&getToken()===token;
  useEffect(()=>{onBlockChange(!!pending||busy);return()=>onBlockChange(false);},[pending,busy,onBlockChange]);
  function invalidateScope(){
    ++generation.current;++meetingGeneration.current;
    setScopeBlocked(true);setCatalog(null);setMeetingCatalog(null);setReceipt(null);setSelected([]);
  }
  useEffect(()=>{
    const sequence=++generation.current;
    ++meetingGeneration.current;
    setScopeBlocked(true);setCatalog(null);setMeetingCatalog(null);setSelected([]);setReceipt(null);setMeetingMessage("");setMessage("正在读取对象候选；连接不可用时请重新读取运行。");
    if(!access)return;
    void client.objectCandidates(snapshot.run_id,snapshot.goal_revision).then(response=>{
      if(sequence!==generation.current||!latest.current.connected||latest.current.getToken()!==token)return;
      if(!response.ok){setMessage("对象候选不可用：HTTP "+response.status+"。"+response.message);return;}
      if(response.value.objects.some(item=>item.source_refs.some(source=>!snapshot.selected_refs.includes(source.source_id))))throw new Error("对象候选来源不属于当前运行范围");
      setCatalog(response.value);setScopeBlocked(false);setMessage("");
    });
    return()=>{++generation.current;};
  },[client,snapshot.run_id,snapshot.goal_revision,access,token,refreshIndex]);

  function complete(response:{ok:true;value:ObjectReceipt}|{ok:false;status:number;message:string},request:Pending){
    if(!live.current||!latest.current.connected||latest.current.getToken()!==token||latest.current.run!==snapshot.run_id)return;
    if(!response.ok){if([401,403,404,409,410].includes(response.status))invalidateScope();setMessage("对象选择结果待核查：HTTP "+response.status+"。"+response.message);return;}
    if(response.value.objects.some((item,index)=>item.source_refs.length!==request.sources[index].length||item.source_refs.some((source,sourceIndex)=>{const expected=request.sources[index][sourceIndex];return source.source_id!==expected.source_id||source.version!==expected.version||source.sha256!==expected.sha256;})))throw new Error("对象选择回执的来源与原请求不一致");
    setPending(null);setReceipt(response.value);setSelected([]);setScopeBlocked(false);setMessage("");
  }
  function submit(event:FormEvent<HTMLFormElement>){
    event.preventDefault();
    if(!access||!enabled||scopeBlocked||busy||pending||!catalog||!catalog.selection_allowed||catalog.goal_revision!==snapshot.goal_revision||!["QUEUED","WAITING_INPUT"].includes(snapshot.status)||snapshot.cancel_requested_at!==null)return;
    if(meetingCatalog&&!meetingCatalog.selection_allowed&&selected.some(key=>meetingCatalog.objects.some(item=>JSON.stringify([item.entity_type,item.object_id])===key)))return;
    const chosen=[...catalog.objects,...(meetingCatalog?.objects??[])].filter(item=>selected.includes(JSON.stringify([item.entity_type,item.object_id])));
    const objects=chosen.map(({entity_type,object_id,version,sha256})=>({entity_type,object_id,version,sha256}));
    if(!objects.length||objects.length>100)return;
    const request={request_key:crypto.randomUUID(),goal_revision:snapshot.goal_revision,objects,sources:chosen.map(item=>item.source_refs)};
    sessionStorage.setItem(storageKey,JSON.stringify(request));setPending(request);setBusy(true);setMessage("正在提交；结果未知时查询原请求。");
    void client.bindObjects(snapshot.run_id,request.goal_revision,request.request_key,request.objects).then(response=>complete(response,request)).finally(()=>{if(live.current)setBusy(false);});
  }
  function readMeeting(event:FormEvent<HTMLFormElement>){
    event.preventDefault();
    const id=meetingId.trim();
    if(!access||!enabled||scopeBlocked||busy||meetingBusy||pending||!id||[...id].length>128)return;
    const sequence=++meetingGeneration.current;
    setMeetingCatalog(null);setSelected(previous=>previous.filter(key=>!key.startsWith('["meeting_context",')));setMeetingBusy(true);setMeetingMessage("正在读取指定会议范围。");
    void client.meetingCandidate(snapshot.run_id,snapshot.goal_revision,id).then(response=>{
      if(!live.current||sequence!==meetingGeneration.current||!latest.current.connected||latest.current.getToken()!==token||latest.current.goal!==snapshot.goal_revision)return;
      if(!response.ok){if([401,403,410].includes(response.status))invalidateScope();setMeetingMessage("会议候选不可用：HTTP "+response.status+"。"+response.message);return;}
      if(response.value.objects.some(item=>item.source_refs.some(source=>!snapshot.selected_refs.includes(source.source_id))))throw new Error("会议候选来源不属于当前运行范围");
      setMeetingCatalog(response.value);setMeetingMessage(response.value.objects.length?"":"当前会议没有可用候选。");
    }).finally(()=>{if(live.current)setMeetingBusy(false);});
  }
  function reconcile(){
    if(!access||busy||!pending)return;
    setBusy(true);setMessage("正在查询原请求。");
    void client.objectReceipt(snapshot.run_id,pending.goal_revision,pending.request_key,pending.objects).then(response=>complete(response,pending)).finally(()=>{if(live.current)setBusy(false);});
  }
  const canSelect=access&&enabled&&!scopeBlocked&&!busy&&!meetingBusy&&!pending&&receipt?.goal_revision!==snapshot.goal_revision&&!!catalog&&catalog.selection_allowed&&catalog.goal_revision===snapshot.goal_revision&&["QUEUED","WAITING_INPUT"].includes(snapshot.status)&&snapshot.cancel_requested_at===null;
  return <section className="upgrade2-run-card"><h3>选择业务对象</h3>
    {message&&<p role="status">{message}</p>}
    {pending&&<p>原请求 {pending.request_key} · 目标版本 {pending.goal_revision}；保留原请求，查询结果后继续。</p>}
    {pending&&<button type="button" disabled={!access||busy} onClick={reconcile}>查询对象选择原回执</button>}
    {access&&(scopeBlocked||!catalog)&&<button type="button" disabled={busy||meetingBusy} onClick={()=>setRefreshIndex(value=>value+1)}>重新核查对象范围</button>}
    {access&&enabled&&<><form onSubmit={readMeeting}><label>会议编号<input value={meetingId} maxLength={128} onChange={event=>{setMeetingId(event.target.value);setMeetingCatalog(null);setSelected(previous=>previous.filter(key=>!key.startsWith('["meeting_context",')));setMeetingMessage("");++meetingGeneration.current;}}/></label><button type="submit" disabled={scopeBlocked||busy||meetingBusy||!!pending||!meetingId.trim()}>读取会议范围</button></form>{meetingMessage&&<p role="status">{meetingMessage}</p>}
      {meetingCatalog&&<><ObjectSelectionAvailability catalog={meetingCatalog}/>{meetingCatalog.objects.map(item=><MeetingScopeDetails key={item.object_id} candidate={item}/>)}<ObjectChoices catalog={meetingCatalog} selected={selected} canSelect={canSelect&&meetingCatalog.selection_allowed} onChange={setSelected} onSubmit={submit}/></>}</>}
    {access&&enabled&&!scopeBlocked&&catalog&&<><p>目标版本 {catalog.goal_revision}；仅显示当前来源范围内可读取的对象。所选对象只用于当前运行读取范围。</p>
      <ObjectSelectionAvailability catalog={catalog}/>
      {!catalog.objects.length&&<p>当前来源范围没有可读取的候选对象；服务未提供逐项不可用原因。</p>}
      <ObjectChoices catalog={catalog} selected={selected} canSelect={canSelect} onChange={setSelected} onSubmit={submit}/></>}
    {access&&!canSelect&&!pending&&<p>当前运行暂不可提交对象选择；服务会核查运行状态、目标版本和来源。</p>}
    {access&&enabled&&!scopeBlocked&&receipt&&<div role="status"><p>对象选择已记录 · 请求 {receipt.request_key} · 目标版本 {receipt.goal_revision}</p>{receipt.objects.map(item=><div key={JSON.stringify([item.entity_type,item.object_id])}><p>{labels[item.entity_type]} · {item.object_id} · 版本 {item.version} · 摘要 {item.sha256}</p>{item.source_refs.map(source=><p key={JSON.stringify([source.source_id,source.version])}>来源 {source.source_id} · 版本 {source.version} · 摘要 {source.sha256}</p>)}</div>)}</div>}
  </section>;
}
