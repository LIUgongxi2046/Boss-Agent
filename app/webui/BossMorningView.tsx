import {useCallback,useEffect,useRef,useState,type ReactNode} from "react";
import {useClient} from "@/providers/ClientProvider";
import {BossToday,morningReason,morningState,type TodayItem,type TodayOrderReceipt,type TodayProjection} from "./BossToday";
import {Dialog,DialogContent,DialogTitle,DialogDescription,DialogClose} from "@/components/ui/dialog";
import {CheckCircle2,ClipboardList,Info,Send,X} from "lucide-react";
import {isSafeMorningFocusId,readMorningReturnPoint} from "./morning-return";
import {currentMorningDetailScope,shouldClearMorningSelectionOnFilter} from "./morning-detail-scope";
import {validateMorningBindingReceipt,canAcknowledgeMissingMorningBinding,type MorningBinding,type MorningBindingReceipt} from "./morning-binding-recovery";
export type {MorningBinding,MorningBindingReceipt} from "./morning-binding-recovery";
import "./boss-morning.css";
import "./boss-f01-shell.css";

type Day={date:string;timezone:string};
export type MorningConversationRequest=Day&{client_request_id:string;question:string;list_id?:string;item_id?:string;binding_id?:string};
export type MorningReference={list_id:string;list_version:string;item_id:string;snapshot_sha256:string};
type Document={source_id:string;version:string;content?:string;published_at?:string;observed_at?:string;valid_from?:string;valid_until?:string;author_contact_id?:string;author_display_name?:string;author_kind?:string;allowed_use?:string;original_locator?:unknown};
type Source={source_id:string;version:string|null;status:string;author_contact_id:string|null;published_at:string|null;observed_at:string|null;data_as_of?:string|null;locator:unknown};
type Item=TodayItem&{kind:string;starts_at:string|null;ends_at:string|null;timezone?:string|null;location?:string|null;related_meetings?:{kind:string;id:string;version:string}[];
  risk_evaluations?:{event_id:string;event_version:string;rule_state:string;rule_version:string;phase:string;reason:string;duration_seconds:number|null;condition_since:string|null}[];
  goal_matches:string[];existing_measures:{kind:string;id:string;version:string;state:string}[]};
type View=Omit<TodayProjection,"items">&{items:Item[];list_id:string|null;list_version:string|null;business_clock:string;read_at:string;data_as_of:string|null;day_start:string;day_end:string;
  profile:{owner_confirmation?:string;goals?:string[];topics?:string[];reading_requirement?:string|null};
  source_statuses:Source[];source_coverage:{region_id:string;state:string;as_of?:string|null}[];
  conflicts:{item_ids:string[];starts_at:string;ends_at:string;scope:string}[];excluded_items:{kind:string;id:string;version:string;reason:string}[];
  preparation_materials:{item_id:string;documents:Source[];requirements:string[];preparation_due_at:string|null}[];
  category_counts?:Record<TodayItem["category"],number>|null;order_state?:string;
  input_coverage?:{kind:string;state:string;provided_count:number;included_count:number;excluded_count:number;reported_total:number|null;scope:string}[]};
type Read={adoption_state:string;result:View;current_order:{version:string;item_ids:string[];state?:string}|null};
type Receipt={client_request_id:string;request_state:string;run_id:string|null;receipt:{outcome:string;result:{list_id:string;list_version:string;date:string;timezone:string}|null};write_performed_by_lookup:false};
type History={requests:{request_id:string;date:string;timezone:string;created_at:string;run_id:string|null}[]};
type Detail={list_id:string;list_version:string;snapshot_sha256:string;item:Item;documents:Document[];objects:{reference:{kind:string;id:string;version:string};data:Record<string,unknown>}[]};
function Panel({title,children}:{title:string;children:ReactNode}){return <section className="boss-panel"><header className="boss-panel-head"><h2>{title}</h2></header>{children}</section>;}
function remember(values:Record<string,string|null>){const address=new URL(window.location.href);for(const [key,value] of Object.entries(values)){if(value===null)address.searchParams.delete(key);else address.searchParams.set(key,value);}window.history.replaceState(window.history.state,"",address);}
const statusLabels:Record<string,string>={CURRENT:"当前可采用",HISTORICAL_REQUIRES_REQUERY:"历史内容需要重新查询",PARTIAL:"部分覆盖",UNAVAILABLE:"资料不足",NOT_UPDATED:"尚未更新",UNSYNCHRONIZED:"尚未同步",VALID:"当前有效",FORBIDDEN:"无权访问",MISSING:"资料缺少",WITHDRAWN:"已经撤销",EXPIRED:"已经到期",INSUFFICIENT_EVIDENCE:"证据不足",CONFLICTS_FOUND:"存在时间冲突",NO_CONFLICT_IN_PROVIDED_RANGES:"所提供时段没有冲突"};
const label=(value:string)=>statusLabels[value]??({SAVED:"已经保存",REVOKED:"本人确认已经撤销",NOT_SET:"尚未设置",NEEDS_REIMPORT:"需要重新载入"} as Record<string,string>)[value]??morningState(value);
const inputLabels:Record<string,string>={owner_goals:"本人目标",task:"交办与历史承诺",self_commitment:"本人承诺",application:"申请",meeting:"会议",event:"经营事件",private_calendar:"私人安排",travel_plan:"出行安排"};
const coverageLabels:Record<string,string>={CONFIRMED:"已经确认",NOT_SET:"尚未设置",NO_RECORDS_IN_PROVIDED_SCOPE:"所提供范围没有记录",NEEDS_REVIEW:"需要复核",PARTIAL:"部分覆盖"};

export function BossMorningView({onNavigate,onDirtyChange,onPrepare,onStartConversation,onOpenConversation,refreshVersion,visible=true}:{onNavigate:(page:string,id:string)=>void;onDirtyChange:(value:boolean)=>void;onPrepare:(item:TodayItem,reference:MorningReference)=>void;onStartConversation:(value:MorningConversationRequest,signal:AbortSignal)=>Promise<MorningBindingReceipt>;onOpenConversation:(chatId:string)=>void;refreshVersion:number;visible?:boolean}){
  const {client,getToken,token}=useClient();
  const [day,setDay]=useState<Day|null>(null),[view,setView]=useState<View|null>(null),[list,setList]=useState<Read|null>(null);
  const [question,setQuestion]=useState(""),[questionDirty,setQuestionDirty]=useState(false),[receipt,setReceipt]=useState<Receipt|null>(null),[history,setHistory]=useState<History>({requests:[]});
  const [dayDraft,setDayDraft]=useState<Day|null>(null),[category,setCategory]=useState<TodayItem["category"]|"ALL">("ALL"),[meetingOpen,setMeetingOpen]=useState(false);
  const [requestId,setRequestId]=useState(""),[selected,setSelected]=useState(""),[sourceId,setSourceId]=useState("");
  const [bindingId,setBindingId]=useState(""),[nativeBinding,setNativeBinding]=useState<MorningBinding|null>(null),[missingBindingReceipt,setMissingBindingReceipt]=useState<MorningBindingReceipt|null>(null);
  const handoff=useRef<AbortController|null>(null),[handoffCanceled,setHandoffCanceled]=useState(false);
  const [detail,setDetail]=useState<Detail|null>(null),[document,setDocument]=useState<Document|null>(null);
  const [detailLoading,setDetailLoading]=useState(false),[detailError,setDetailError]=useState(""),[detailRevision,setDetailRevision]=useState(0);
  const [sourceError,setSourceError]=useState(""),[sourceRevision,setSourceRevision]=useState(0);
  const [error,setError]=useState(""),[loading,setLoading]=useState(false),[busy,setBusy]=useState(false),[uncertain,setUncertain]=useState(false),[orderDirty,setOrderDirty]=useState(false),[denied,setDenied]=useState(false),[revision,setRevision]=useState(0);
  const epoch=useRef(0),generation=useRef(0),receiptSequence=useRef(0),deniedRef=useRef(false),bound=useRef<Read|null>(null);
  const surface=useRef<HTMLDivElement>(null),returnPoint=useRef<{scroll:number;focus:string}|null>(null),returnPending=useRef(false),overlayFocus=useRef<HTMLElement|null>(null),visibility=useRef(visible);
  visibility.current=visible;
  const clearDetailForRead=useCallback(()=>{
    if(visibility.current&&returnPoint.current?.focus===window.document.activeElement?.id)returnPending.current=true;
    setDetail(null);setDetailLoading(false);setDetailError("");
  },[]);
  bound.current=list;
  const clear=useCallback(()=>{setView(null);setList(null);bound.current=null;setDetail(null);setDocument(null);setHistory({requests:[]});setReceipt(null);setSelected("");setSourceId("");setDetailLoading(false);setDetailError("");setSourceError("");setMissingBindingReceipt(null);},[]);
  const read=useCallback(async<T,>(path:string,signal?:AbortSignal):Promise<T>=>{
    const response=await fetch(path,{headers:{Authorization:"Bearer "+getToken()},cache:"no-store",signal});
    if(response.status===401||response.status===403){deniedRef.current=true;setDenied(true);generation.current++;clear();if(response.status===401)window.dispatchEvent(new Event("boss-auth-expired"));throw new Error("当前身份无法读取晨间资料");}
    const body=await response.json();if(!response.ok){
      if(response.status===400&&path.startsWith("/api/boss/ui/morning/preview?"))throw new Error("业务日期或 IANA 时区无效，请核查当前条件。");
      throw new Error("HTTP "+response.status+" · "+body.error);
    }return body as T;
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
      if(adoptDay){setDay({date:result.date,timezone:result.timezone});setDayDraft({date:result.date,timezone:result.timezone});remember({morningDate:result.date,morningTimezone:result.timezone});}
      setList(value);setView(value.result);bound.current=value;
    }
  },[read]);
  const restoreBinding=useCallback(async(key:string,signal?:AbortSignal)=>{
    const current=epoch.current,version=generation.current;
    const value=validateMorningBindingReceipt(await read<unknown>("/api/boss/ui/morning/binding?"+new URLSearchParams({client_request_id:key}),signal),key);
    if(current!==epoch.current||version!==generation.current||signal?.aborted)return;
    setBindingId(key);setNativeBinding(value.result);setUncertain(value.outcome!=="RECORDED");
    setMissingBindingReceipt(value.outcome==="NOT_FOUND_IN_CURRENT_STORE"?value:null);
    if(value.outcome==="NOT_FOUND_IN_CURRENT_STORE"){
      setError("当前库没有原会话绑定记录，未知网络状态已通过原编号核查。不会自动重发问题；可以再次读取原编号或由本人明确结束核查。");
      return;
    }
    if(value.result?.last_request_id){remember({morningRequest:value.result.last_request_id});await restore(value.result.last_request_id,signal,true);}
    else if(value.result)setError("会话范围已绑定，问题尚未进入晨间运行。保留当前文字，可明确提交或打开该会话。");
  },[read,restore]);
  useEffect(()=>{
    const current=++epoch.current,abort=new AbortController();generation.current++;deniedRef.current=false;setDenied(false);clear();setDay(null);setDayDraft(null);setQuestion("");setQuestionDirty(false);setCategory("ALL");setMeetingOpen(false);returnPoint.current=null;setBusy(false);setOrderDirty(false);setLoading(true);setError("");setUncertain(false);
    const parameters=new URLSearchParams(window.location.search),key=parameters.get("morningRequest")??"",binding=parameters.get("morningBinding")??"";
    const savedCategory=parameters.get("morningCategory");
    if(savedCategory==="DECIDE"||savedCategory==="COORDINATE"||savedCategory==="INFORM")setCategory(savedCategory);
    const restored=readMorningReturnPoint(parameters.get("morningFocus"),parameters.get("morningScroll"));
    if(restored){returnPoint.current=restored;returnPending.current=true;}
    setBindingId(binding);setNativeBinding(null);
    setRequestId(key);setSelected(parameters.get("morningItem")??"");setSourceId(parameters.get("morningSource")??"");
    const active=()=>current===epoch.current&&!abort.signal.aborted&&!deniedRef.current;
    void read<Day>("/api/boss/ui/today",abort.signal).then(async value=>{
      if(!active())return;
      const date=parameters.get("morningDate")??value.date,timezone=parameters.get("morningTimezone")??value.timezone;
      setDay({date,timezone});setDayDraft({date,timezone});
      if(binding)await restoreBinding(binding,abort.signal);else if(key){setUncertain(true);await restore(key,abort.signal,true);}
    }).catch(failure=>{if(active())setError(failure.message);}).finally(()=>{if(active())setLoading(false);});
    void read<History>("/api/boss/ui/morning/history",abort.signal).then(value=>{if(active())setHistory(value);},failure=>{if(active())setError(failure.message);});
    return()=>{epoch.current++;generation.current++;receiptSequence.current++;abort.abort();handoff.current?.abort();};
  },[client,token,read,restore,restoreBinding,clear]);
  const dateDirty=Boolean(day&&dayDraft&&(day.date!==dayDraft.date||day.timezone!==dayDraft.timezone));
  useEffect(()=>{if(visible)onDirtyChange(orderDirty||busy||uncertain||questionDirty||dateDirty);},[onDirtyChange,orderDirty,busy,uncertain,questionDirty,dateDirty,visible]);
  useEffect(()=>{
    if(!visible)return;
    setRevision(value=>value+1);
    if(bindingId)void restoreBinding(bindingId).catch(failure=>setError(failure.message));
    const point=returnPoint.current;if(!point)return;
    returnPending.current=true;
    const frame=requestAnimationFrame(()=>{surface.current?.closest(".boss-content")?.scrollTo({top:point.scroll});});
    return()=>cancelAnimationFrame(frame);
  },[visible,restoreBinding]);
  useEffect(()=>{
    if(!day||deniedRef.current)return;
    const abort=new AbortController(),current=epoch.current,version=generation.current;
    const active=()=>current===epoch.current&&version===generation.current&&!abort.signal.aborted&&!deniedRef.current;
    setLoading(true);setError("");clearDetailForRead();setDocument(null);
    const currentList=bound.current;
    const path=currentList?"/api/boss/ui/morning/list?"+new URLSearchParams({list_id:currentList.result.list_id!,historical:"true"}):"/api/boss/ui/morning/preview?"+new URLSearchParams(day);
    void read<Read|View>(path,abort.signal).then(value=>{if(!active()||!currentList&&bound.current)return;if("result" in value){setList(value);setView(value.result);}else setView(value);},failure=>{if(active()){setView(null);setList(null);setError(failure.message);}}).finally(()=>{if(active())setLoading(false);});
    return()=>abort.abort();
  },[day,revision,refreshVersion,read,clearDetailForRead]);
  useEffect(()=>{
    if(!selected||!currentMorningDetailScope(list,view)){
      setDetail(null);setDetailLoading(false);setDetailError("");
      return;
    }
    const abort=new AbortController(),current=epoch.current,version=generation.current,listId=view!.list_id!;
    const active=()=>current===epoch.current&&version===generation.current&&!abort.signal.aborted;
    clearDetailForRead();setDocument(null);setDetailLoading(true);
    void read<Detail>("/api/boss/ui/morning/detail?"+new URLSearchParams({list_id:listId,item_id:selected}),abort.signal).then(value=>{
      if(!active())return;
      if(bound.current?.result.list_id!==listId||value.list_id!==listId||value.item.item_id!==selected||
        value.list_version!==bound.current.result.list_version||value.snapshot_sha256!==bound.current.result.snapshot_sha256)
        throw new Error("当前事项与清单版本不符，请重新查询");
      setDetail(value);setDetailError("");setDetailLoading(false);
    }).catch(failure=>{if(active()){setDetailLoading(false);setDetailError(failure instanceof Error?failure.message:String(failure));}});
    return()=>abort.abort();
  },[selected,list,view?.list_id,read,clearDetailForRead,detailRevision]);
  useEffect(()=>{
    if(!sourceId||!currentMorningDetailScope(list,view)){setDocument(null);setSourceError("");return;}
    const abort=new AbortController(),current=epoch.current,version=generation.current;
    setDocument(null);setSourceError("");
    void read<{list_id:string;list_version:string;document:Document}>("/api/boss/ui/morning/source?"+new URLSearchParams({list_id:view.list_id,source_id:sourceId}),abort.signal).then(value=>{
      if(current===epoch.current&&version===generation.current&&!abort.signal.aborted){
        if(value.list_id!==bound.current?.result.list_id||value.list_version!==bound.current.result.list_version||value.document.source_id!==sourceId)throw new Error("当前来源与清单引用不符");
        setDocument(value.document);setSourceError("");
      }
    }).catch(failure=>{if(current===epoch.current&&!abort.signal.aborted)setSourceError(failure instanceof Error?failure.message:String(failure));});
    return()=>abort.abort();
  },[sourceId,list,view?.list_id,read,sourceRevision]);
  function changeDay(next:Day){
    generation.current++;receiptSequence.current++;setView(null);setList(null);bound.current=null;setReceipt(null);setRequestId("");setSelected("");setSourceId("");setDetail(null);setDocument(null);setUncertain(false);setDay(next);setDayDraft(next);setCategory("ALL");
    returnPoint.current=null;returnPending.current=false;
    setBindingId("");setNativeBinding(null);setMissingBindingReceipt(null);remember({morningDate:next.date,morningTimezone:next.timezone,morningRequest:null,morningItem:null,morningSource:null,morningBinding:null,morningChat:null,todayOrderRequest:null,morningCategory:null,morningScroll:null,morningFocus:null});
  }
  async function submit(discuss=false){
    if(!day||busy||orderDirty||uncertain||!view||deniedRef.current||!question.trim())return;
    if(discuss&&!detail)return;
    const current=epoch.current,version=++generation.current,key="morning-bind-"+crypto.randomUUID(),listId=detail?.list_id,itemId=detail?.item.item_id;
    const reusable=nativeBinding&&nativeBinding.date===day.date&&nativeBinding.timezone===day.timezone&&nativeBinding.item_id===(itemId??null)&&nativeBinding.snapshot_sha256===view.snapshot_sha256&&nativeBinding.order_version===(list?.current_order?.version??view.order_version)?nativeBinding:null;
    const controller=new AbortController();handoff.current=controller;setHandoffCanceled(false);setMissingBindingReceipt(null);
    captureReturn();receiptSequence.current++;setBusy(true);setUncertain(true);setError("");setDocument(null);setSourceId("");
    setBindingId(reusable?.binding_id??key);remember({morningBinding:reusable?.binding_id??key,morningDate:day.date,morningTimezone:day.timezone,morningItem:selected||null,morningSource:null,todayOrderRequest:null});
    await onStartConversation({client_request_id:key,...day,question,...(listId&&itemId?{list_id:listId,item_id:itemId}:{}),...(reusable?{binding_id:reusable.binding_id}:{})},controller.signal).then(saved=>{
      if(current!==epoch.current||version!==generation.current)return;
      if(saved.outcome!=="RECORDED"||!saved.result)throw new Error("原生晨间会话绑定尚未确认");
      setNativeBinding(saved.result);setBindingId(saved.result.binding_id);setUncertain(false);setQuestionDirty(controller.signal.aborted);remember({morningBinding:saved.result.binding_id,morningChat:saved.result.chat_id});
      if(controller.signal.aborted)setError("会话交接已取消；原绑定已保存，问题未发送。可核查后明确提交。");
    }).catch(failure=>{
      if(current!==epoch.current||version!==generation.current)return;
      setError(failure.message+"；请读取原会话绑定 "+(reusable?.binding_id??key));
      if(failure.handoffNotSubmitted){setUncertain(false);setBindingId("");setNativeBinding(null);remember({morningBinding:null,morningChat:null});setError("会话交接已取消；问题未发送，原有查询保持。");}
      if([400,401,403,404,409,410,413].includes(failure.status))setUncertain(false);
      if([401,403].includes(failure.status)){deniedRef.current=true;setDenied(true);clear();}
    });
    if(handoff.current===controller)handoff.current=null;
    if(current===epoch.current&&version===generation.current)setBusy(false);
  }
  async function recover(key=requestId,adoptDay=false){if(!key||orderDirty||deniedRef.current)return;const current=epoch.current;generation.current++;setError("");setDetail(null);setDocument(null);setSelected("");setSourceId("");remember({morningRequest:key,morningItem:null,morningSource:null});await restore(key,undefined,adoptDay).then(()=>{if(current===epoch.current&&!deniedRef.current)setRevision(value=>value+1);},failure=>{if(current===epoch.current)setError(failure.message);});}
  function cancelHandoff(){handoff.current?.abort();setHandoffCanceled(true);setError("会话交接取消已请求；等待原绑定结果，当前问题不会自动发送。");}
  function acknowledgeMissingBinding(){
    if(busy||deniedRef.current||!canAcknowledgeMissingMorningBinding(missingBindingReceipt,bindingId))return;
    setBindingId("");setNativeBinding(null);setMissingBindingReceipt(null);setUncertain(false);
    remember({morningBinding:null,morningChat:null});
    setError("已由本人结束当前库中未记录的原会话绑定核查；问题不会自动重发。请重新确认本次需求后再明确提交。");
  }
  const current=currentMorningDetailScope(list,view),order=current?list?.current_order:null;
  useEffect(()=>{
    if(!visible||!returnPending.current||loading||(Boolean(selected)&&!detail&&!detailError))return;
    const point=returnPoint.current;if(!point)return;
    const frame=requestAnimationFrame(()=>{const target=window.document.getElementById(point.focus);if(!target||target.matches(":disabled"))return;surface.current?.closest(".boss-content")?.scrollTo({top:point.scroll});target.focus({preventScroll:true});returnPending.current=false;});
    return()=>cancelAnimationFrame(frame);
  },[visible,detail,detailError,current,loading,selected]);
  useEffect(()=>{
    let frame=0;
    const restoreFocus=()=>{if(!visibility.current||!returnPoint.current)return;frame=requestAnimationFrame(()=>{
      const point=returnPoint.current;if(!point)return;
      const target=window.document.getElementById(point.focus);if(!target||target.matches(":disabled"))return;
      surface.current?.closest(".boss-content")?.scrollTo({top:point.scroll});target.focus({preventScroll:true});returnPending.current=false;
    });};
    window.addEventListener("boss-navigation-focus-ready",restoreFocus);
    return()=>{window.removeEventListener("boss-navigation-focus-ready",restoreFocus);cancelAnimationFrame(frame);};
  },[]);
  const ordered=view&&order?{...view,order_version:order.version,items:order.item_ids.map(id=>view.items.find(item=>item.item_id===id)).filter((item):item is Item=>Boolean(item))}:view;
  const disabled=busy||uncertain||orderDirty||denied;
  const actualCounts={DECIDE:0,COORDINATE:0,INFORM:0};for(const item of view?.items??[])actualCounts[item.category]++;
  const counts=view?.category_counts??actualCounts;
  const chooseItem=(item:TodayItem)=>{if(selected===item.item_id)setDetailRevision(value=>value+1);setSelected(item.item_id);setDetail(null);setDetailError("");setDetailLoading(currentMorningDetailScope(list,view));setSourceId("");setDocument(null);remember({morningItem:item.item_id,morningSource:null});};
  const chooseSource=(id:string)=>{overlayFocus.current=window.document.activeElement as HTMLElement;setError("");setSourceError("");setSourceId(id);setDocument(null);remember({morningSource:id});};
  const readOrder=useCallback((key:string,signal?:AbortSignal)=>read<TodayOrderReceipt>("/api/boss/ui/morning/receipt?"+new URLSearchParams({action:"boss.today.reorder",client_request_id:key}),signal),[read]);
  const categories=[{id:"DECIDE" as const,title:"待决定",Icon:ClipboardList},{id:"COORDINATE" as const,title:"待协调",Icon:CheckCircle2},{id:"INFORM" as const,title:"需要知晓",Icon:Info}];
  const meetings=detail?.objects.filter(object=>object.reference.kind==="meeting"&&detail.item.related_meetings?.some(ref=>ref.id===object.reference.id&&ref.version===object.reference.version))??[];
  const captureReturn=()=>{const active=window.document.activeElement,focus=active instanceof HTMLElement&&surface.current?.contains(active)&&isSafeMorningFocusId(active.id)?active.id:"morning-question";returnPoint.current={scroll:surface.current?.closest(".boss-content")?.scrollTop??0,focus};remember({morningScroll:String(returnPoint.current.scroll),morningFocus:focus,morningCategory:category});};
  const discuss=()=>{if(question.trim())void submit(true);else{const input=window.document.getElementById("morning-question");input?.focus();input?.scrollIntoView({block:"center"});}};
  const openRelated=(item:TodayItem)=>{captureReturn();onNavigate(item.page_id,item.object_id);};
  return <div ref={surface} className="boss-morning-view boss-f01" aria-busy={loading||busy}>
    {error&&<p role="alert" className="boss-status boss-status-error">{error}</p>}{loading&&<p role="status">正在读取当前日期资料</p>}
    {list&&list.adoption_state!=="CURRENT"&&<p className="boss-status" role="status">{label(list.adoption_state)}，当前依据需重新查询，历史结果不用于本次操作。</p>}
    <div className="boss-f01-grid"><main className="boss-f01-main">
    <Panel title="日期"><form className="boss-f01-scope" onSubmit={event=>{event.preventDefault();if(dayDraft&&!disabled){if(dateDirty)changeDay(dayDraft);else setRevision(value=>value+1);}}}>
      <label>日期<input aria-label="日期" type="date" required value={dayDraft?.date??""} disabled={disabled||!dayDraft} onChange={event=>dayDraft&&setDayDraft({...dayDraft,date:event.target.value})}/></label>
      <div className="boss-f01-scope-actions"><button type="submit" className="boss-btn boss-btn-primary" disabled={disabled||loading||!dayDraft}>切换日期</button></div>
    </form><p>当前查看 {day?.date??"今天"}</p></Panel>
      <BossToday key={view?.list_id??day?.date??""} data={ordered} loading={loading} error="" onReload={()=>setRevision(value=>value+1)} onNavigate={onNavigate}
        presentation="compact" category={category} selectedItemId={selected} onDirtyChange={setOrderDirty} orderEnabled={Boolean(current)&&!busy&&!uncertain&&!dateDirty} onSelectItem={chooseItem} onDiscuss={discuss} discussEnabled={Boolean(detail&&current)&&!disabled&&!dateDirty}
        orderScope={current&&view?.list_id?{list_id:view.list_id,date:view.date,timezone:view.timezone}:undefined} onReadOrder={readOrder} onReorder={payload=>client.requestMutation("boss.today.reorder",payload).then(()=>undefined)}>
        <div className="boss-f01-categories" role="group" aria-label="事项分类">{categories.map(({id,title})=><button className={"boss-f01-category "+(category===id?"selected":"")} key={id} type="button" aria-pressed={category===id} onClick={()=>{const next=category===id?"ALL":id;setCategory(next);if(shouldClearMorningSelectionOnFilter(next,selected,view?.items??[])){setSelected("");setDetail(null);setDetailLoading(false);setDetailError("");setSourceId("");setDocument(null);setSourceError("");remember({morningCategory:next,morningItem:null,morningSource:null});}else remember({morningCategory:next});}}>{title}<span>{view?counts[id]+" 项":"数量待读取"}</span></button>)}</div>
      </BossToday>
      <section className="boss-panel boss-f01-entry"><header className="boss-panel-head"><div><h2>问问今天的事</h2></div></header>
        <form onSubmit={event=>{event.preventDefault();void submit();}}><label className="boss-f01-entry-label" htmlFor="morning-question">想处理什么</label>
          <textarea id="morning-question" placeholder="比如：今天有哪些事需要我处理？" required maxLength={4000} value={question} disabled={busy||uncertain||denied} onChange={event=>{setQuestion(event.target.value);setQuestionDirty(true);}}/>
          <div className="boss-f01-entry-actions">{busy&&<button className="boss-btn" type="button" disabled={handoffCanceled} onClick={cancelHandoff}>取消</button>}<button className="boss-btn boss-btn-primary" type="submit" disabled={disabled||dateDirty||loading||!view||!question.trim()}><Send size={16}/>发送</button></div>
        </form>
      </section>
    </main><aside className="boss-f01-aside" aria-label="今日工作相关信息">
      <Panel title="事项详情">{detail&&current?<>
        <dl className="boss-f01-detail-fields"><div><dt>事项</dt><dd>{detail.item.title}</dd></div><div><dt>相关资料</dt><dd>{detail.documents.length} 项</dd></div><div><dt>相关会议</dt><dd>{meetings.length?meetings.length+" 场":"没有会议"}</dd></div><div><dt>相关交办</dt><dd>{detail.item.existing_measures.filter(value=>value.kind==="task").length||"没有"}</dd></div></dl>
        <div className="boss-actions"><button id="morning-prepare" className="boss-btn" disabled={disabled} onClick={()=>{captureReturn();onPrepare(detail.item,{list_id:detail.list_id,list_version:detail.list_version,item_id:detail.item.item_id,snapshot_sha256:detail.snapshot_sha256});}}>安排交办</button>
          {meetings.length>0&&<button id="morning-meeting" className="boss-btn" disabled={disabled} onClick={()=>{overlayFocus.current=window.document.activeElement as HTMLElement;setMeetingOpen(true);}}>查看会议</button>}
          {["F06","N05","F02"].includes(detail.item.page_id)&&<button id="morning-related" className="boss-btn" disabled={disabled} onClick={()=>openRelated(detail.item)}>查看事项</button>}</div>
        <div className="boss-actions">{detail.documents.map(value=><button id={"morning-source-"+value.source_id} className="boss-btn" key={value.source_id} disabled={busy||uncertain} onClick={()=>chooseSource(value.source_id)}>查看资料{value.source_id}</button>)}</div>
        <details><summary>查看完整内容</summary>
        <h3>{detail.item.title}</h3><p>{detail.item.reason}</p><p>处理人 {detail.item.coordinator_id??"尚未提供"} · 有效期限 {detail.item.due_at??"尚未提供"} · 当前状态 {morningState(detail.item.state??"尚未提供")}</p>
        <p>时间 {detail.item.starts_at??"尚未提供"} 至 {detail.item.ends_at??"尚未提供"} · 对象时区 {detail.item.timezone??"尚未提供"}</p><p>地点 {detail.item.location??"尚未提供"}</p>
        {detail.item.sorting_reasons?.map(reason=><p key={reason}>{morningReason(reason)}</p>)}{detail.item.goal_matches.map(goal=><p key={goal}>关联本人目标：{goal}</p>)}
        {detail.item.risk_evaluations?.map(risk=><p key={risk.event_id}>风险 {risk.event_id} · 事件v{risk.event_version} · 规则v{risk.rule_version} · {risk.rule_state} / {risk.phase} · {risk.reason} · 持续时间 {risk.duration_seconds??"未知"} 秒</p>)}
        {detail.item.existing_measures.map(measure=><p key={measure.kind+measure.id}>已有措施 {measure.id} · v{measure.version} · {measure.state}</p>)}
        <p>清单 {detail.list_id} · 版本 {detail.list_version}</p>
        {detail.documents.length===0&&<p>当前事项尚未提供原文材料。</p>}
        {view?.preparation_materials.filter(value=>value.item_id===selected).map(value=><div key={value.item_id}><p>准备期限 {value.preparation_due_at??"尚未提供"}</p>{value.requirements.map(text=><p key={text}>{text}</p>)}</div>)}
        </details>
      </>:<><dl className="boss-f01-detail-fields">{["对象与当前版本","关联来源","关联会议","交办记录"].map(field=><div key={field}><dt>{field}</dt><dd>{selected?detailLoading?"正在核查":detailError?"当前读取失败":current?"尚未取得详情":list?"需重新查询清单":"仅为日期预览":"尚未选择事项"}</dd></div>)}</dl>
        <p>{selected?detailLoading?"正在核查当前事项与来源版本。":detailError?"详情读取失败，原有清单仍在；请重新核查该事项。":current?"当前事项尚未取得可采用详情，请核查来源。":list?"当前清单需要重新查询，历史内容不可直接操作。":"此项仅为日期预览，尚不能读取正式详情或绑定交办。请先通过“本次需求”提交晨间问题，取得正式清单后核查事项。":current?"选择列表中的事项，查看同一版本的资料和操作。":"提交晨间问题取得有效清单后，可以查看详情、保存次序和准备交办。"}</p>
        {detailError&&current&&selected&&<div className="boss-status boss-status-error" role="alert"><span>{detailError}</span><button id="morning-detail-retry" type="button" className="boss-btn" disabled={busy||denied} onClick={()=>setDetailRevision(value=>value+1)}>重新核查当前事项</button></div>}</>}</Panel>
      <details className="boss-panel boss-f01-more"><summary>状态与更多信息</summary><dl className="boss-f01-detail-fields"><div><dt>排序保存状态</dt><dd>{orderDirty?"尚未保存":label(order?.state??view?.order_state??"NOT_SET")}</dd></div><div><dt>资料完整性</dt><dd>{view?label(view.coverage_state):"尚待读取"}</dd></div></dl>
      <div className="boss-actions"><button id="morning-tasks" className="boss-btn" disabled={disabled} onClick={()=>{captureReturn();onNavigate("N05","");}}>任务与承诺</button><button id="morning-notifications" className="boss-btn" disabled={disabled} onClick={()=>{captureReturn();onNavigate("N06","");}}>通知中心</button></div>
      <details><summary>查看资料与业务记录</summary>
      <details><summary>当前进展与查询记录</summary><p>{list?label(list.adoption_state):"当前日期预览"} · 清单版本 {view?.list_version??"尚未生成"}</p><p>业务日 {view?.day_start??"等待读取"} 至 {view?.day_end??"等待读取"}</p>
        <p>当前本人次序设置：{label(order?.state??view?.order_state??"NOT_SET")} · 当前次序版本 {order?.version??view?.order_version??"等待读取"}。事项排序理由保留清单查询时的依据。</p>
        {bindingId&&<><p>原生会话绑定 {bindingId}</p><button className="boss-btn" disabled={busy||orderDirty||denied} onClick={()=>void restoreBinding(bindingId).catch(failure=>setError(failure.message))}>读取原会话绑定与结果</button>
          {canAcknowledgeMissingMorningBinding(missingBindingReceipt,bindingId)&&<button className="boss-btn" type="button" disabled={busy||orderDirty||denied} onClick={acknowledgeMissingBinding}>确认原绑定未记录，结束核查</button>}</>}
        {nativeBinding&&<button className="boss-btn" disabled={busy||orderDirty||denied} onClick={()=>{captureReturn();onOpenConversation(nativeBinding.chat_id);}}>打开当前晨间会话</button>}
        {nativeBinding&&receipt&&["PREPARED","RUNNING"].includes(receipt.request_state)&&<p>可打开当前晨间会话，使用原生停止操作取消尚未执行的步骤。</p>}
        <p>原晨间请求 {requestId||"尚未提交"}</p><p>晨间运行状态 {receipt?.request_state??(busy?"运行中":uncertain?"结果尚未确认":"尚未提交")} · 回执 {receipt?.receipt.outcome??"未知"}</p>{receipt?.run_id&&<p>运行 {receipt.run_id}</p>}
        {uncertain&&<p role="status">结果尚未确认，请查询同一原请求。</p>}<button className="boss-btn" disabled={!requestId||orderDirty||denied} onClick={()=>void recover()}>读取原晨间请求结果</button>
        <details><summary>查看历史查询</summary><ul className="boss-morning-history">{history.requests.map(value=><li key={value.request_id}><button className="boss-btn" disabled={busy||orderDirty||uncertain||denied||questionDirty||dateDirty} onClick={()=>void recover(value.request_id,true)}>{value.date} · {value.timezone} · {value.created_at}</button></li>)}</ul></details>
      </details>
      <details><summary>当前需我关注</summary><div className="boss-f01-attention"><div><ClipboardList size={20}/><span>需要本人决定<strong>{view?counts.DECIDE+" 项":"等待读取"}</strong></span></div>
        <div><CheckCircle2 size={20}/><span>会议与承诺<strong>{view?view.items.filter(item=>["meeting","self_commitment","historical_task"].includes(item.kind)).length+" 项":"等待读取"}</strong></span></div>
        <div><Info size={20}/><span>可能的时间冲突<strong>{view?label(view.conflict_state):"等待读取"}</strong></span></div></div></details>
      <details><summary>会议与承诺</summary>{view?.items.filter(item=>["meeting","self_commitment","historical_task","private_calendar","travel_plan"].includes(item.kind)).map(item=><article className="boss-f01-related" key={item.item_id}>
        <button type="button" className="boss-f01-item-link" disabled={!current||busy||uncertain} onClick={()=>chooseItem(item)}>{item.title}</button><p>{item.starts_at??item.due_at??"时间尚未提供"} 至 {item.ends_at??"结束时间尚未提供"}</p><p>{inputLabels[item.kind]??item.kind} · {item.timezone??"对象时区尚未提供"}</p></article>)}
        {view&&!view.items.some(item=>["meeting","self_commitment","historical_task","private_calendar","travel_plan"].includes(item.kind))&&<p>当前所提供资料没有适用的会议或承诺；覆盖范围见来源区域。</p>}
        {!view&&<p>资料尚待读取。</p>}</details>
      <details><summary>时间冲突</summary><p>{view?label(view.conflict_state):"资料尚待读取"}</p>{view?.conflicts.map((conflict,index)=><article className="boss-f01-related" key={index}><p>{conflict.starts_at} 至 {conflict.ends_at}</p>{conflict.item_ids.map(id=><p key={id}>{view.items.find(item=>item.item_id===id)?.title??id}</p>)}<p>检查范围：当前所提供时段</p></article>)}<p>完整外部日历覆盖尚未验证。</p></details>
      <details><summary>来源与依据</summary><p>资料覆盖范围 · {view?label(view.coverage_state):"数据尚待读取"}</p><p>资料截至 {view?.data_as_of??"来源更新时间不完整"}</p>
        {view?.source_coverage.map(region=><p key={region.region_id}>{region.region_id} · {label(region.state)} · 截至 {region.as_of??"未知"}</p>)}
        {view?.input_coverage?.map(input=><p className="boss-f01-input-coverage" key={input.kind}>{inputLabels[input.kind]??input.kind} · {coverageLabels[input.state]??input.state} · 已提供 {input.provided_count} / 纳入 {input.included_count} / 未纳入 {input.excluded_count} · 完整范围数量 {input.reported_total??"未知"}</p>)}
        {view?.missing_sources.map(value=><p className="boss-helper" key={value}>{morningReason(value)}</p>)}
        {view?.source_statuses.map(source=><article className="boss-f01-related" key={source.source_id}><p>{source.source_id} · v{source.version??"未知"} · {label(source.status)}</p><p>资料截至 {source.data_as_of??"未知"} · 作者 {source.author_contact_id??"未知"} · 更新 {source.observed_at??"未知"}</p><button className="boss-btn" disabled={!current||source.status!=="VALID"||busy||uncertain} onClick={()=>chooseSource(source.source_id)}>查看来源原文</button></article>)}
        <details><summary>查看未纳入的对象与原因</summary>{view?.excluded_items.map(value=><p key={value.kind+value.id}>{value.kind} / {value.id} / v{value.version} · {morningReason(value.reason)}</p>)}</details></details>
      <details><summary>本人目标与阅读要求</summary><p>{view?.profile.owner_confirmation==="CONFIRMED"?"当前有效本人确认目标":"本人目标尚未设置或当前确认不适用"}</p>{view?.profile.goals?.map(goal=><p key={goal}>{goal}</p>)}{view?.profile.topics?.map(topic=><p key={topic}>关注 {topic}</p>)}<p>{view?.profile.reading_requirement??"阅读要求尚未提供"}</p></details></details></details>
    </aside></div>
    <Dialog open={Boolean(sourceId)&&visible} onOpenChange={open=>{if(!open){setSourceId("");setDocument(null);setSourceError("");remember({morningSource:null});}}}><DialogContent showCloseButton={false} onCloseAutoFocus={event=>{event.preventDefault();overlayFocus.current?.focus({preventScroll:true});}} overlayClassName="boss-f01-overlay" className="boss-f01-dialog boss-v6" aria-describedby="morning-source-description"><DialogTitle>当前来源原文</DialogTitle><DialogDescription id="morning-source-description">当前清单与来源版本经服务端重新核查。关闭后返回当前事项。</DialogDescription>
      <DialogClose className="boss-icon-button boss-f01-close" aria-label="返回当前事项"><X size={20}/></DialogClose>
      {document&&current?<article id="morning-source"><h3>{document.source_id} · v{document.version}</h3><p>作者 {document.author_display_name??document.author_contact_id??document.author_kind??"尚未提供"} · 用途 {document.allowed_use??"以当前资料权限为准"}</p><p>发布 {document.published_at??"未知"} · 更新 {document.observed_at??"未知"}</p><p>有效时间 {document.valid_from??"未知"} 至 {document.valid_until??"未知"}</p><p>引用位置 {document.original_locator===undefined?"尚未提供":JSON.stringify(document.original_locator)}</p><blockquote>{document.content??"原文未提供"}</blockquote></article>:<div><p role={sourceError&&current?"alert":"status"}>{!current?"当前清单为预览或已失效，暂不能读取原文，请重新查询正式清单。":sourceError||"正在读取当前来源"}</p>{current&&sourceError&&<button id="morning-source-retry" type="button" className="boss-btn" disabled={busy||denied} onClick={()=>setSourceRevision(value=>value+1)}>重新核查当前来源</button>}</div>}
    </DialogContent></Dialog>
    <Dialog open={meetingOpen&&visible} onOpenChange={setMeetingOpen}><DialogContent showCloseButton={false} onCloseAutoFocus={event=>{event.preventDefault();overlayFocus.current?.focus({preventScroll:true});}} overlayClassName="boss-f01-overlay" className="boss-f01-dialog boss-v6" aria-describedby="morning-meeting-description"><DialogTitle>关联会议与准备材料</DialogTitle><DialogDescription id="morning-meeting-description">当前事项所引用的会议，只读展示当前清单绑定的版本。</DialogDescription><DialogClose className="boss-icon-button boss-f01-close" aria-label="返回当前事项"><X size={20}/></DialogClose>
      {current&&detail?meetings.map(object=><article key={object.reference.id}><h3>{String(object.data.title??"会议与会前材料")}</h3><p>会议 {object.reference.id} · v{object.reference.version}</p><p>{String(object.data.starts_at??"开始时间尚未提供")} 至 {String(object.data.ends_at??"结束时间尚未提供")} · {String(object.data.timezone??view?.timezone??"时区尚未提供")}</p><p>地点 {String(object.data.location??"尚未提供")}</p><p>材料 {Array.isArray(object.data.material_ids)?object.data.material_ids.join("、"):"尚未提供"}</p></article>):<p>当前依据需要重新核查。</p>}
    </DialogContent></Dialog>
  </div>;
}
