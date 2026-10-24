import {useCallback,useEffect,useRef,useState,type ReactNode} from "react";
import {useClient} from "@/providers/ClientProvider";
import {BossToday,morningReason,type TodayItem,type TodayOrderReceipt,type TodayProjection} from "./BossToday";

type Day={date:string;timezone:string};
export type MorningReference={list_id:string;list_version:string;item_id:string;snapshot_sha256:string};
type Document={source_id:string;version:string;content?:string;published_at?:string;observed_at?:string;valid_from?:string;valid_until?:string;author_contact_id?:string;author_display_name?:string;author_kind?:string;allowed_use?:string;original_locator?:unknown};
type Source={source_id:string;version:string|null;status:string;author_contact_id:string|null;published_at:string|null;observed_at:string|null;locator:unknown};
type Item=TodayItem&{kind:string;starts_at:string|null;ends_at:string|null;goal_matches:string[];existing_measures:{kind:string;id:string;version:string;state:string}[]};
type View=Omit<TodayProjection,"items">&{items:Item[];list_id:string|null;list_version:string|null;business_clock:string;data_as_of:string|null;day_start:string;day_end:string;
  profile:{owner_confirmation?:string;goals?:string[];topics?:string[];reading_requirement?:string|null};
  source_statuses:Source[];source_coverage:{region_id:string;state:string;data_as_of?:string|null}[];
  conflicts:{item_ids:string[];starts_at:string;ends_at:string;scope:string}[];excluded_items:{kind:string;id:string;version:string;reason:string}[];
  preparation_materials:{item_id:string;documents:Source[];requirements:string[];preparation_due_at:string|null}[]};
type Read={adoption_state:string;result:View;current_order:{version:string;item_ids:string[]}|null};
type Receipt={client_request_id:string;request_state:string;run_id:string|null;receipt:{outcome:string;result:{list_id:string;list_version:string;date:string;timezone:string}|null};write_performed_by_lookup:false};
type History={requests:{request_id:string;date:string;timezone:string;created_at:string;run_id:string|null}[]};
type Detail={list_id:string;list_version:string;snapshot_sha256:string;item:Item;documents:Document[];objects:{reference:{kind:string;id:string;version:string};data:Record<string,unknown>}[]};
function Panel({title,children}:{title:string;children:ReactNode}){return <section className="boss-panel"><header className="boss-panel-head"><h2>{title}</h2></header>{children}</section>;}
function remember(values:Record<string,string|null>){const address=new URL(window.location.href);for(const [key,value] of Object.entries(values)){if(value===null)address.searchParams.delete(key);else address.searchParams.set(key,value);}window.history.replaceState(null,"",address);}
const statusLabels:Record<string,string>={CURRENT:"当前可采用",HISTORICAL_REQUIRES_REQUERY:"历史内容需要重新查询",PARTIAL:"部分覆盖",UNAVAILABLE:"资料不足",NOT_UPDATED:"尚未更新",UNSYNCHRONIZED:"尚未同步",VALID:"当前有效",FORBIDDEN:"无权访问",MISSING:"资料缺少",WITHDRAWN:"已经撤销",EXPIRED:"已经到期",INSUFFICIENT_EVIDENCE:"证据不足",CONFLICTS_FOUND:"存在时间冲突",NO_CONFLICT_IN_PROVIDED_RANGES:"所提供时段没有冲突"};
const label=(value:string)=>statusLabels[value]??value;

export function BossMorningView({onNavigate,onDirtyChange,onPrepare,refreshVersion}:{onNavigate:(page:string,id:string)=>void;onDirtyChange:(value:boolean)=>void;onPrepare:(item:TodayItem,reference:MorningReference)=>void;refreshVersion:number}){
  const {client,getToken,token}=useClient();
  const [day,setDay]=useState<Day|null>(null),[view,setView]=useState<View|null>(null),[list,setList]=useState<Read|null>(null);
  const [question,setQuestion]=useState("今天有哪些事情需要本人处理"),[receipt,setReceipt]=useState<Receipt|null>(null),[history,setHistory]=useState<History>({requests:[]});
  const [requestId,setRequestId]=useState(""),[selected,setSelected]=useState(""),[sourceId,setSourceId]=useState("");
  const [detail,setDetail]=useState<Detail|null>(null),[document,setDocument]=useState<Document|null>(null);
  const [error,setError]=useState(""),[loading,setLoading]=useState(false),[busy,setBusy]=useState(false),[uncertain,setUncertain]=useState(false),[orderDirty,setOrderDirty]=useState(false),[denied,setDenied]=useState(false),[revision,setRevision]=useState(0);
  const epoch=useRef(0),generation=useRef(0),receiptSequence=useRef(0),deniedRef=useRef(false),bound=useRef<Read|null>(null);
  bound.current=list;
  const clear=useCallback(()=>{setView(null);setList(null);bound.current=null;setDetail(null);setDocument(null);setHistory({requests:[]});setReceipt(null);setSelected("");setSourceId("");},[]);
  const read=useCallback(async<T,>(path:string,signal?:AbortSignal):Promise<T>=>{
    const response=await fetch(path,{headers:{Authorization:"Bearer "+getToken()},cache:"no-store",signal});
    if(response.status===401||response.status===403){deniedRef.current=true;setDenied(true);generation.current++;clear();if(response.status===401)window.dispatchEvent(new Event("boss-auth-expired"));throw new Error("当前身份无法读取晨间资料");}
    const body=await response.json();if(!response.ok)throw new Error("HTTP "+response.status+" · "+body.error);return body as T;
  },[getToken,clear]);
  const restore=useCallback(async(key:string,signal?:AbortSignal,adoptDay=false)=>{
    const current=epoch.current,version=generation.current,sequence=++receiptSequence.current;
    const active=()=>current===epoch.current&&version===generation.current&&sequence===receiptSequence.current&&!signal?.aborted&&!deniedRef.current;
    const saved=await read<Receipt>("/api/boss/ui/morning/request?"+new URLSearchParams({client_request_id:key}),signal);
    if(!active())return;
    if(saved.client_request_id!==key||saved.write_performed_by_lookup!==false)throw new Error("晨间原回执与当前编号不符");
    const terminal=["SUCCEEDED","FAILED","CANCELED","TIMED_OUT"].includes(saved.request_state);
    setReceipt(saved);setRequestId(key);setUncertain(!terminal);if(terminal)setBusy(false);
    const result=saved.receipt.result;
    if(result){
      const value=await read<Read>("/api/boss/ui/morning/list?"+new URLSearchParams({list_id:result.list_id,historical:"true"}),signal);
      if(!active())return;
      if(adoptDay){setDay({date:result.date,timezone:result.timezone});remember({morningDate:result.date,morningTimezone:result.timezone});}
      setList(value);setView(value.result);bound.current=value;
    }
  },[read]);
  useEffect(()=>{
    const current=++epoch.current,abort=new AbortController();generation.current++;deniedRef.current=false;setDenied(false);clear();setDay(null);setBusy(false);setOrderDirty(false);setLoading(true);setError("");setUncertain(false);
    const parameters=new URLSearchParams(window.location.search),key=parameters.get("morningRequest")??"";
    setRequestId(key);setSelected(parameters.get("morningItem")??"");setSourceId(parameters.get("morningSource")??"");
    const active=()=>current===epoch.current&&!abort.signal.aborted&&!deniedRef.current;
    void read<Day>("/api/boss/ui/today",abort.signal).then(async value=>{
      if(!active())return;
      const date=parameters.get("morningDate")??value.date,timezone=parameters.get("morningTimezone")??value.timezone;
      setDay({date,timezone});
      if(key){setUncertain(true);await restore(key,abort.signal,true);}
    }).catch(failure=>{if(active())setError(failure.message);}).finally(()=>{if(active())setLoading(false);});
    void read<History>("/api/boss/ui/morning/history",abort.signal).then(value=>{if(active())setHistory(value);},failure=>{if(active())setError(failure.message);});
    return()=>{epoch.current++;generation.current++;receiptSequence.current++;abort.abort();};
  },[token,read,restore,clear]);
  useEffect(()=>{onDirtyChange(orderDirty||busy||uncertain);},[onDirtyChange,orderDirty,busy,uncertain]);
  useEffect(()=>{
    if(!day||deniedRef.current)return;
    const abort=new AbortController(),current=epoch.current,version=generation.current;
    const active=()=>current===epoch.current&&version===generation.current&&!abort.signal.aborted&&!deniedRef.current;
    setLoading(true);setError("");setDetail(null);setDocument(null);
    const currentList=bound.current;
    const path=currentList?"/api/boss/ui/morning/list?"+new URLSearchParams({list_id:currentList.result.list_id!,historical:"true"}):"/api/boss/ui/morning/preview?"+new URLSearchParams(day);
    void read<Read|View>(path,abort.signal).then(value=>{if(!active()||!currentList&&bound.current)return;if("result" in value){setList(value);setView(value.result);}else setView(value);},failure=>{if(active()){setView(null);setList(null);setError(failure.message);}}).finally(()=>{if(active())setLoading(false);});
    return()=>abort.abort();
  },[day,revision,refreshVersion,read]);
  useEffect(()=>{
    if(!selected||!list||list.adoption_state!=="CURRENT"||!view?.list_id)return;
    const abort=new AbortController(),current=epoch.current,version=generation.current,listId=view.list_id;
    setDetail(null);setDocument(null);
    void read<Detail>("/api/boss/ui/morning/detail?"+new URLSearchParams({list_id:listId,item_id:selected}),abort.signal).then(value=>{
      if(current===epoch.current&&version===generation.current&&!abort.signal.aborted&&bound.current?.result.list_id===listId)setDetail(value);
    },failure=>{if(current===epoch.current&&!abort.signal.aborted)setError(failure.message);});
    return()=>abort.abort();
  },[selected,list,view?.list_id,read]);
  useEffect(()=>{
    if(!sourceId||!list||list.adoption_state!=="CURRENT"||!view?.list_id)return;
    const abort=new AbortController(),current=epoch.current,version=generation.current;
    setDocument(null);
    void read<{document:Document}>("/api/boss/ui/morning/source?"+new URLSearchParams({list_id:view.list_id,source_id:sourceId}),abort.signal).then(value=>{
      if(current===epoch.current&&version===generation.current&&!abort.signal.aborted)setDocument(value.document);
    },failure=>{if(current===epoch.current&&!abort.signal.aborted)setError(failure.message);});
    return()=>abort.abort();
  },[sourceId,list,view?.list_id,read]);
  function changeDay(next:Day){
    generation.current++;receiptSequence.current++;setView(null);setList(null);bound.current=null;setReceipt(null);setRequestId("");setSelected("");setSourceId("");setDetail(null);setDocument(null);setUncertain(false);setDay(next);
    remember({morningDate:next.date,morningTimezone:next.timezone,morningRequest:null,morningItem:null,morningSource:null,todayOrderRequest:null});
  }
  async function submit(discuss=false){
    if(!day||busy||orderDirty||uncertain||!view||deniedRef.current||!question.trim())return;
    const current=epoch.current,version=++generation.current,key="morning-"+crypto.randomUUID(),listId=discuss?view.list_id:null;
    receiptSequence.current++;setRequestId(key);setBusy(true);setUncertain(true);setError("");setReceipt(null);setList(null);bound.current=null;setView(null);setDetail(null);setDocument(null);setSelected("");setSourceId("");
    remember({morningRequest:key,morningDate:day.date,morningTimezone:day.timezone,morningItem:null,morningSource:null,todayOrderRequest:null});
    await client.requestMutation<Receipt>("boss.morning.query",{client_request_id:key,...day,question,...(listId?{list_id:listId}:{})}).then(async()=>{
      if(current===epoch.current&&version===generation.current){await restore(key);setRevision(value=>value+1);}
    },failure=>{
      if(current!==epoch.current||version!==generation.current)return;
      setError(failure.message+"；请读取原晨间请求 "+key);
      if([400,401,403,404,409,410,413].includes(failure.status)){setUncertain(false);setRevision(value=>value+1);}
      if([401,403].includes(failure.status)){deniedRef.current=true;setDenied(true);clear();}
    });
    if(current===epoch.current&&version===generation.current){setBusy(false);await read<History>("/api/boss/ui/morning/history").then(value=>{if(current===epoch.current)setHistory(value);},failure=>{if(current===epoch.current)setError(failure.message);});}
  }
  async function recover(key=requestId,adoptDay=false){if(!key||orderDirty||deniedRef.current)return;const current=epoch.current;generation.current++;setError("");setDetail(null);setDocument(null);setSelected("");setSourceId("");remember({morningRequest:key,morningItem:null,morningSource:null});await restore(key,undefined,adoptDay).then(()=>{if(current===epoch.current&&!deniedRef.current)setRevision(value=>value+1);},failure=>{if(current===epoch.current)setError(failure.message);});}
  async function cancelQuery(){const current=epoch.current,version=generation.current;await client.requestMutation("boss.morning.cancel",{client_request_id:requestId}).then(()=>{if(current===epoch.current&&version===generation.current)setError("取消已经请求，请读取原晨间请求确认结果。");},failure=>{if(current===epoch.current&&version===generation.current)setError(failure.message);});}
  const current=list?.adoption_state==="CURRENT",order=list?.current_order;
  const ordered=view&&order?{...view,order_version:order.version,items:order.item_ids.map(id=>view.items.find(item=>item.item_id===id)).filter((item):item is Item=>Boolean(item))}:view;
  const disabled=busy||uncertain||orderDirty||denied;
  const counts={DECIDE:0,COORDINATE:0,INFORM:0};for(const item of view?.items??[])counts[item.category]++;
  const chooseItem=(item:TodayItem)=>{setSelected(item.item_id);setDetail(null);setSourceId("");setDocument(null);remember({morningItem:item.item_id,morningSource:null});};
  const chooseSource=(id:string)=>{setSourceId(id);setDocument(null);remember({morningSource:id});};
  const readOrder=useCallback((key:string,signal?:AbortSignal)=>read<TodayOrderReceipt>("/api/boss/ui/morning/receipt?"+new URLSearchParams({action:"boss.today.reorder",client_request_id:key}),signal),[read]);
  return <div className="boss-morning-view">
    <Panel title="业务日期与资料范围"><span className="boss-tag boss-tag-amber">SIMULATED · 晨间事项</span>
      <div className="boss-form-grid boss-morning-fields"><label>业务日期<input aria-label="业务日期" type="date" required value={day?.date??""} disabled={disabled||!day} onChange={event=>day&&changeDay({...day,date:event.target.value})}/></label>
        <label>IANA 时区<input aria-label="IANA 时区" required value={day?.timezone??""} disabled={disabled||!day} onChange={event=>day&&changeDay({...day,timezone:event.target.value})}/></label></div>
      <p>业务日 {view?.day_start??"等待读取"} 至 {view?.day_end??"等待读取"}</p><p>资料截至 {view?.data_as_of??"来源更新时间不完整"} · 业务时钟 {view?.business_clock??"等待读取"}</p>
      {error&&<p role="alert" className="boss-status boss-status-error">{error}</p>}
      {loading&&<p role="status">正在读取当前日期资料</p>}
      <form onSubmit={event=>{event.preventDefault();void submit();}}><label>晨间问题<textarea aria-label="晨间问题" required maxLength={4000} value={question} disabled={busy||denied} onChange={event=>setQuestion(event.target.value)}/></label>
        <div className="boss-actions"><button className="boss-btn boss-btn-primary" type="submit" disabled={disabled||loading||!view||!question.trim()}>整理晨间事项</button>
          <button className="boss-btn" type="button" disabled={!busy} onClick={()=>void cancelQuery()}>取消晨间查询</button>
          <button className="boss-btn" type="button" disabled={disabled||!current} onClick={()=>void submit(true)}>继续讨论当前清单</button></div></form>
      <p>待本人决定 {counts.DECIDE} · 待本人协调 {counts.COORDINATE} · 需要知晓 {counts.INFORM}</p>
      <p>{list?label(list.adoption_state):"当前日期预览，提交晨间问题后形成可查询清单。"} · 清单版本 {view?.list_version??"尚未生成"}</p>
    </Panel>
    <BossToday key={token+":"+(view?.list_id??day?.date??"")} data={ordered} loading={loading} error="" onReload={()=>setRevision(value=>value+1)} onNavigate={onNavigate}
      onDirtyChange={setOrderDirty} orderEnabled={Boolean(current)&&!busy&&!uncertain} onSelectItem={chooseItem}
      orderScope={current&&view?.list_id?{list_id:view.list_id,date:view.date,timezone:view.timezone}:undefined}
      onReadOrder={readOrder} onReorder={payload=>client.requestMutation("boss.today.reorder",payload).then(()=>undefined)}/>
    <div className="boss-columns"><div className="boss-column">
      <Panel title="当前事项详情">{detail?<><h3>{detail.item.title}</h3><p>{detail.item.reason}</p><p>清单 {detail.list_id} · 版本 {detail.list_version} · 对象 {detail.item.object_id} · 版本 {detail.item.version??"未知"}</p>
        <p>处理人 {detail.item.coordinator_id??"尚未提供"} · 状态 {detail.item.state} · 期限 {detail.item.due_at??"尚未提供"}</p>
        <p>时间 {detail.item.starts_at??"尚未提供"} 至 {detail.item.ends_at??"尚未提供"}</p>
        {detail.item.sorting_reasons?.map(reason=><p key={reason}>{morningReason(reason)}</p>)}{detail.item.goal_matches.map(goal=><p key={goal}>关联本人目标：{goal}</p>)}
        {detail.item.existing_measures.map(measure=><p key={measure.kind+measure.id}>已有措施 {measure.id} · 版本 {measure.version} · {measure.state}</p>)}
        <div className="boss-actions"><button className="boss-btn" onClick={()=>onNavigate(detail.item.page_id,detail.item.target_id||detail.item.object_id)}>打开关联事项</button>
          {detail.item.kind==="meeting"&&<button className="boss-btn" onClick={()=>onNavigate("F04",detail.item.object_id)}>打开关联会议</button>}
          <button className="boss-btn" onClick={()=>onPrepare(detail.item,{list_id:detail.list_id,list_version:detail.list_version,item_id:detail.item.item_id,snapshot_sha256:detail.snapshot_sha256})}>准备交办</button></div>
        <p>准备交办后需要核查当前对象、来源和期限，并由本人单独确认。</p>
        {detail.documents.map(value=><button className="boss-btn" key={value.source_id} onClick={()=>chooseSource(value.source_id)}>查看依据：{value.source_id} · v{value.version}</button>)}
      </>:<p>{current?"选择事项查看当前清单对应的对象与来源。":"提交晨间查询并取得有效清单后可以查看详情。"}</p>}</Panel>
      <Panel title="会议、承诺与准备材料">{view?.items.filter(item=>["meeting","self_commitment","historical_task","private_calendar","travel_plan"].includes(item.kind)).map(item=><div className="boss-workspace-item" key={item.item_id}><h3>{item.title}</h3><p>{item.starts_at??item.due_at??"时间尚未提供"} 至 {item.ends_at??"结束时间尚未提供"}</p><button className="boss-btn" disabled={!current} onClick={()=>chooseItem(item)}>查看本项准备材料</button></div>)}
        {view?.preparation_materials.filter(value=>!selected||value.item_id===selected).map(value=><article className="boss-workspace-item" key={value.item_id}><strong>{view.items.find(item=>item.item_id===value.item_id)?.title}</strong><p>准备期限 {value.preparation_due_at??"尚未提供"}</p>{value.requirements.map(text=><p key={text}>{text}</p>)}
          {value.documents.length===0&&<p>准备材料尚未提供。</p>}{value.documents.map(source=><button className="boss-btn" disabled={!current||source.status!=="VALID"} key={source.source_id} onClick={()=>chooseSource(source.source_id)}>查看准备依据：{source.source_id} · {label(source.status)}</button>)}</article>)}</Panel>
      <Panel title="当前来源原文">{document?<article id="morning-source"><h3>{document.source_id} · v{document.version}</h3><p>作者 {document.author_display_name??document.author_contact_id??document.author_kind??"尚未提供"} · 用途 {document.allowed_use??"以当前资料权限为准"}</p><p>发布 {document.published_at??"未知"} · 更新 {document.observed_at??"未知"}</p><p>有效时间 {document.valid_from??"未知"} 至 {document.valid_until??"未知"}</p><p>引用位置 {document.original_locator===undefined?"尚未提供":JSON.stringify(document.original_locator)}</p><blockquote>{document.content??"原文未提供"}</blockquote></article>:<p>选择当前清单的有效来源后读取原文。</p>}</Panel>
    </div><div className="boss-column">
      <Panel title="大鹏的工作状态"><div className="boss-mascot-work"><img src={busy||loading?"/boss-brand/03-思考分析.webp":"/boss-brand/01-待机悬浮.webp"} alt=""/><div><strong>{busy?"正在整理晨间事项":loading?"正在读取当前资料":"等候本人指令"}</strong><p>当前结果以实际清单与原请求回执为准。</p></div></div></Panel>
      <Panel title="本人目标与阅读要求"><p>{view?.profile.owner_confirmation==="CONFIRMED"?"当前有效本人确认目标":"本人目标尚未设置或当前确认不适用"}</p>{view?.profile.goals?.map(goal=><p key={goal}>{goal}</p>)}{view?.profile.topics?.map(topic=><p key={topic}>关注 {topic}</p>)}<p>{view?.profile.reading_requirement??"阅读要求尚未提供"}</p><button className="boss-btn" onClick={()=>onNavigate("N07","")}>管理本人目标与阅读要求</button></Panel>
      <Panel title="日程冲突"><p>{label(view?.conflict_state??"INSUFFICIENT_EVIDENCE")}</p>{view?.conflicts.map((conflict,index)=><article className="boss-workspace-item" key={index}><p>{conflict.starts_at} 至 {conflict.ends_at}</p>{conflict.item_ids.map(id=><p key={id}>{view.items.find(item=>item.item_id===id)?.title??id}</p>)}<p>检查范围：当前所提供时段</p></article>)}<p>完整外部日历覆盖尚未验证。</p></Panel>
      <Panel title="数据与来源状态"><p>覆盖 {label(view?.coverage_state??"UNAVAILABLE")}</p>{view?.source_coverage.map(region=><p key={region.region_id}>{region.region_id} · {label(region.state)} · 截至 {region.data_as_of??"未知"}</p>)}{view?.missing_sources.map(value=><p className="boss-helper" key={value}>{morningReason(value)}</p>)}
        {view?.source_statuses.map(source=><article className="boss-workspace-item" key={source.source_id}><p>{source.source_id} · v{source.version??"未知"} · {label(source.status)}</p><p>作者 {source.author_contact_id??"未知"} · 发布 {source.published_at??"未知"} · 更新 {source.observed_at??"未知"}</p><button className="boss-btn" disabled={!current||source.status!=="VALID"} onClick={()=>chooseSource(source.source_id)}>查看来源原文</button></article>)}
        <details><summary>查看未纳入的对象与原因</summary>{view?.excluded_items.map(value=><p key={value.kind+value.id}>{value.kind} / {value.id} / v{value.version} · {morningReason(value.reason)}</p>)}</details></Panel>
      <Panel title="晨间原请求与恢复"><p>原晨间请求 {requestId||"尚未提交"}</p><p>晨间运行状态 {receipt?.request_state??(busy?"运行中":uncertain?"结果尚未确认":"尚未提交")} · 回执 {receipt?.receipt.outcome??"未知"}</p>{uncertain&&<p role="status">结果尚未确认，请查询同一原请求。</p>}
        <button className="boss-btn" disabled={!requestId||orderDirty||denied} onClick={()=>void recover()}>读取原晨间请求结果</button>
        <ul className="boss-morning-history">{history.requests.map(value=><li key={value.request_id}><button className="boss-btn" disabled={busy||orderDirty||uncertain||denied} onClick={()=>void recover(value.request_id,true)}>{value.date} · {value.timezone} · {value.created_at}</button></li>)}</ul></Panel>
    </div></div>
  </div>;
}
