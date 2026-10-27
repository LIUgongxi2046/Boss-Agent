import {useCallback,useEffect,useRef,useState,type ReactNode} from "react";
import {ArrowRight,X} from "lucide-react";
import {useClient} from "@/providers/ClientProvider";
import {Dialog,DialogContent,DialogTitle,DialogDescription,DialogClose} from "@/components/ui/dialog";
import {BossBusinessOverviewLayout} from "./BossBusinessOverviewLayout";
import type {Overview,OverviewScope,OverviewDimensions,OverviewDetail,OverviewSelection,OverviewAssociation} from "./business-overview-types";
import type {BusinessAlert} from "./BossBusinessAlerts";

type Props={visible:boolean;refreshVersion:number;discardVersion:number;onDirtyChange:(dirty:boolean)=>void;onQuery:(view:Overview)=>void;onReminder:(alert:BusinessAlert)=>void;onTask:(task:OverviewAssociation)=>void;onDiscuss:(selection:OverviewSelection)=>Promise<void>;onPrepare:(detail:OverviewDetail,use:OverviewSelection["use"])=>void;conversationStatus:ReactNode;onTopic:(selection:OverviewSelection)=>void;onViewSource:(id:string)=>void};
type SourceText={source_id:string;version:string;source_type:string;content:string;author_contact_id?:string;author_display_name?:string;published_at?:string;read_at:string};
const scopeKeys=["legal_entity_id","region_id","period_start","period_end","timezone","attention"] as const;
const sameScope=(first:OverviewScope,second:OverviewScope)=>scopeKeys.every(key=>first[key]===second[key]);
const metricLabels:Record<string,string>={sales_quantity:"销量",revenue:"营业收入",cost:"成本",gross_profit:"毛利",gross_margin:"毛利率",gross_profit_per_tonne:"单吨毛利"};
const attentionLabels:Record<OverviewScope["attention"],string>={ALL:"全部当前范围",OWNER_INVOLVEMENT:"需要本人参与",SOURCE_REVIEW:"来源需要复核"};
const stateLabels:Record<string,string>={PARTIAL:"部分资料可读",NEEDS_REVIEW:"需要重新核查",SOURCE_NOT_AVAILABLE:"尚无本专题有效资料",FILTER_EMPTY:"当前关注条件没有匹配资料",CURRENT:"当前可采用",VALID:"当前有效",WITHDRAWN:"来源已撤销",EXPIRED:"来源已到期",MISSING_OR_FORBIDDEN:"来源无法访问",SCOPED_AVAILABLE:"所选范围已有资料",UNAVAILABLE:"当前无法采用"};
const topicRequirements:Record<string,string>={F14:"仍需补充完整行情、合同、入库、领用成本及有效配方和排产范围。",F15:"需要同品种、阶段和周期的订单、预测、客户收益及观察覆盖。",F16:"需要苗种交付与养殖批次关系、样本数量和覆盖分母。",F17:"需要专业作者、适用范围、确认意见、执行与后续复查资料。",F18:"需要合作归属、费用、数量平衡及结算期间资料。",F19:"需要分别核查肉禽、蛋禽、奶畜、肉用牛羊的用途、阶段、单位与观察期。",F20:"需要自营单元、设备、批次和观察时间的明确关系。",F21:"仍需补充完整客诉追溯范围及当前专业复核资料。",F22:"需要国别、法人、本地与集团期间、币种、汇率来源及工段能力。",F23:"需要试验、对照、样本、观察期、评审作者及适用范围。"};
const useLabels={BROILER:"肉禽",EGG:"蛋禽",MILK:"奶畜",BEEF:"肉用牛羊"};
const factLabels:Record<string,string>={ownership_type:"归属类型",asset_owner_id:"资产归属",cost_owner_id:"成本归属",quantity_unit:"数量单位",currency:"币种",trace_state:"追溯状态",inspection_state:"检验状态",professional_state:"专业状态",period_start:"报告期间开始",period_end:"报告期间结束"};
const topicDirectory=[
  ["F14","原料与饲料"],["F15","水产季节"],["F16","苗种批次"],["F17","动保与技服"],["F18","生猪合作"],
  ["F19","禽类与反刍"],["F20","公司水产养殖"],["F21","食品与品质"],["F22","海外业务"],["F23","研发应用"],
] as const;
const state=(value:string)=>stateLabels[value]??value;
function remember(values:Record<string,string|null>){const address=new URL(window.location.href);for(const [key,value] of Object.entries(values)){if(value===null)address.searchParams.delete(key);else address.searchParams.set(key,value);}window.history.replaceState(window.history.state,"",address);}
function saveScope(scope:OverviewScope){remember({overviewEntity:scope.legal_entity_id,overviewRegion:scope.region_id??"ALL",overviewStart:scope.period_start,overviewEnd:scope.period_end,overviewTimezone:scope.timezone,overviewAttention:scope.attention});}
export function savedOverviewScope():OverviewScope|null{const query=new URLSearchParams(window.location.search),values=["overviewEntity","overviewRegion","overviewStart","overviewEnd","overviewTimezone","overviewAttention"].map(key=>query.get(key));if(values.every(value=>value===null))return null;if(values.some(value=>!value))throw new Error("保存的经营范围引用不完整");return {legal_entity_id:values[0]!,region_id:values[1]==="ALL"?null:values[1]!,period_start:values[2]!,period_end:values[3]!,timezone:values[4]!,attention:values[5] as OverviewScope["attention"]};}

export function BossBusinessOverview({visible,refreshVersion,discardVersion,onDirtyChange,onQuery,onReminder,onTask,onDiscuss,onPrepare,conversationStatus,onTopic,onViewSource}:Props){
  const {client,getToken,token}=useClient();
  const [dimensions,setDimensions]=useState<OverviewDimensions|null>(null),[draft,setDraft]=useState<OverviewScope|null>(null),[view,setView]=useState<Overview|null>(null);
  const [dirty,setDirty]=useState(false),[loading,setLoading]=useState(false),[error,setError]=useState(""),[denied,setDenied]=useState(false),[stale,setStale]=useState(false),[selected,setSelected]=useState("");
  const [detail,setDetail]=useState<OverviewDetail|null>(null),[detailLoading,setDetailLoading]=useState(false),[dialogOpen,setDialogOpen]=useState(false),[source,setSource]=useState<SourceText|null>(null);
  const [selectedUse,setSelectedUse]=useState<OverviewSelection["use"]>(null);
  const root=useRef<HTMLDivElement>(null),epoch=useRef(0),generation=useRef(0),detailGeneration=useRef(0),viewRef=useRef<Overview|null>(null),visibleRef=useRef(visible),trigger=useRef<HTMLElement|null>(null);
  const returnPoint=useRef<{scroll:number;focus:string}|null>(null),previousVisible=useRef(visible),initial=useRef<OverviewScope|null>(null);
  const dirtyRef=useRef(dirty);dirtyRef.current=dirty;
  viewRef.current=view;visibleRef.current=visible;
  const failure=useCallback((reason:unknown)=>{
    const status=reason instanceof Error&&"status" in reason?Number(reason.status):null;
    if(status===409)setStale(true);
    if(status===401||status===403){++epoch.current;++generation.current;++detailGeneration.current;setDenied(true);setDimensions(null);setDraft(null);setDirty(false);setSelected("");setSelectedUse(null);setView(null);viewRef.current=null;initial.current=null;returnPoint.current=null;setDetail(null);setSource(null);setDialogOpen(false);if(status===401)window.dispatchEvent(new Event("boss-auth-expired"));}
    const detail=reason instanceof Error?reason.message:String(reason);
    setError(status===409?"当前范围、对象或来源已经变化，请重新查询专题范围。":status===400?"当前法人、区域、期间、时区或关注条件不受支持，请核查后重新查询。":status===401||status===403?"当前身份无法读取经营关注资料。":status===504?"当前读取已经超时，请保留原范围并重新核查。":status===502?"上游读取失败："+detail:status===503?"当前连接或业务服务不可用："+detail:"当前读取未完成："+detail+"。请保留原范围并核查连接后重新读取。");
  },[]);
  const apply=useCallback((scope:OverviewScope,explicit=false,preserveDraft=false)=>{
    const current=epoch.current,sequence=++generation.current;++detailGeneration.current;
    setLoading(true);setError("");setDetail(null);setSource(null);setDialogOpen(false);
    const cleared=explicit?client.requestMutation("boss.conversation.business.clear",{}):Promise.resolve();
    void cleared.then(()=>client.requestMutation<Overview>("boss.business_overview.read",scope)).then(result=>{
      if(epoch.current!==current||generation.current!==sequence)return;
      if(result.projection!=="business-overview"||!sameScope(result.applied_scope,scope)||result.business_mutation_performed!==false||result.business_authorization_granted!==false||result.topics.length!==10||result.topics.some((row,index)=>row.page_id!=="F"+(index+14)))throw new Error("经营总览没有采用当前正式范围和完整专题");
      setView(result);viewRef.current=result;if(!preserveDraft||!dirtyRef.current){setDraft(result.applied_scope);setDirty(false);}setStale(false);setLoading(false);saveScope(result.applied_scope);
    }).catch(reason=>{if(epoch.current===current&&generation.current===sequence){setLoading(false);failure(reason);}});
  },[client,failure]);
  useEffect(()=>{
    const current=++epoch.current,abort=new AbortController();++generation.current;++detailGeneration.current;
    setDimensions(null);setDraft(null);setView(null);viewRef.current=null;setDirty(false);dirtyRef.current=false;setDenied(false);setStale(false);setError("");setSelected(new URLSearchParams(window.location.search).get("overviewTopic")??"");
    const saved=new URLSearchParams(window.location.search),scroll=saved.get("overviewScroll"),focus=saved.get("overviewFocus");
    const savedUse=saved.get("overviewUse");
    if(savedUse!==null&&!Object.hasOwn(useLabels,savedUse))throw new Error("保存的禽类与反刍用途无效");
    setSelectedUse(saved.get("overviewTopic")==="F19"?savedUse as OverviewSelection["use"]:null);
    returnPoint.current=scroll!==null&&focus!==null?{scroll:Number(scroll),focus}:null;
    if(returnPoint.current&&(!Number.isFinite(returnPoint.current.scroll)||returnPoint.current.scroll<0))throw new Error("保存的经营关注滚动位置无效");
    setDetail(null);setSource(null);setDialogOpen(false);setLoading(true);
    void fetch("/api/boss/ui/business-overview/dimensions",{headers:{Authorization:"Bearer "+getToken()},cache:"no-store",signal:abort.signal}).then(async response=>{
      if(!response.ok)throw Object.assign(new Error("经营范围选项读取失败"),{status:response.status});
      return response.json() as Promise<OverviewDimensions>;
    }).then(result=>{
      if(epoch.current!==current||abort.signal.aborted)return;
      const period=result.periods.find(value=>value.id==="CURRENT");
      if(!period||!result.legal_entity_ids.length||!result.timezones.length)throw new Error("正式经营范围缺少当前期间、法人或时区");
      const restored=savedOverviewScope(),first:OverviewScope=restored??{legal_entity_id:result.legal_entity_ids[0],region_id:null,period_start:period.period_start,period_end:period.period_end,timezone:result.timezones[0],attention:"ALL"};
      initial.current=first;setDimensions(result);setDraft(first);setLoading(false);apply(restored??first);
    }).catch(reason=>{if(epoch.current===current&&!abort.signal.aborted){setLoading(false);failure(reason);}});
    return()=>{++epoch.current;++generation.current;++detailGeneration.current;abort.abort();};
  },[client,token,getToken,apply,failure]);
  useEffect(()=>{onDirtyChange(dirty);},[dirty,onDirtyChange]);
  useEffect(()=>{
    if(discardVersion===0)return;
    const next=viewRef.current?.applied_scope??initial.current;
    if(next)setDraft(next);setDirty(false);setError("");
  },[discardVersion]);
  useEffect(()=>{if(refreshVersion>0&&visibleRef.current&&viewRef.current)apply(viewRef.current.applied_scope,false,true);},[refreshVersion,apply]);
  useEffect(()=>{
    const wasVisible=previousVisible.current;previousVisible.current=visible;
    if(!visible){++generation.current;++detailGeneration.current;setLoading(false);setDetailLoading(false);setDialogOpen(false);return;}
    if(!wasVisible&&viewRef.current)apply(viewRef.current.applied_scope,false,true);
  },[visible,apply]);
  useEffect(()=>{
    if(!visible||loading||!view)return;
    const point=returnPoint.current;
    if(!point)return;
    const area=root.current?.closest<HTMLElement>(".boss-content"),focus=window.document.getElementById(point.focus);
    if(!area||!focus||!root.current?.contains(focus))throw new Error("经营关注缺少原返回区域或控件");
    focus.focus({preventScroll:true});area.scrollTop=point.scroll;returnPoint.current=null;
  },[visible,loading,view]);
  function capture(active:HTMLElement|null=window.document.activeElement instanceof HTMLElement?window.document.activeElement:null){const area=root.current?.closest<HTMLElement>(".boss-content");if(!area||!active?.id||!root.current?.contains(active))throw new Error("经营关注返回需要明确控件与滚动区域");returnPoint.current={scroll:area.scrollTop,focus:active.id};remember({overviewScroll:String(area.scrollTop),overviewFocus:active.id});}
  function edit(changes:Partial<OverviewScope>){++generation.current;setLoading(false);setDraft(current=>current?{...current,...changes}:current);setDirty(true);setError("");}
  function currentAction(action:(current:Overview)=>void){const before=viewRef.current;if(!before||dirty||loading||denied||stale)return;capture();const current=epoch.current,sequence=++generation.current;setLoading(true);setError("");void client.requestMutation<Overview>("boss.business_overview.read",before.applied_scope).then(result=>{if(current!==epoch.current||sequence!==generation.current)return;setLoading(false);if(result.snapshot_sha256!==before.snapshot_sha256){setView(result);setDetail(null);setSource(null);setDialogOpen(false);setError("资料已经变化，当前内容已重新核查；请核对后再次选择操作。");return;}action(result);}).catch(reason=>{if(current===epoch.current&&sequence===generation.current){setLoading(false);failure(reason);}});}
  function openTopic(pageId:string){
    if(!view||dirty||loading||denied||stale)return;
    const current=epoch.current,sequence=++detailGeneration.current;setSelected(pageId);remember({overviewTopic:pageId});trigger.current=window.document.activeElement instanceof HTMLElement?window.document.activeElement:null;
    if(pageId!=="F19"){setSelectedUse(null);remember({overviewUse:null});}
    setDetail(null);setSource(null);setDetailLoading(true);setDialogOpen(true);setError("");
    void client.requestMutation<OverviewDetail>("boss.business_overview.detail",{scope:view.applied_scope,page_id:pageId,snapshot_sha256:view.snapshot_sha256}).then(result=>{if(current!==epoch.current||sequence!==detailGeneration.current)return;if(result.topic.page_id!==pageId||!sameScope(result.applied_scope,view.applied_scope)||result.snapshot_sha256!==view.snapshot_sha256||result.business_mutation_performed!==false||result.business_authorization_granted!==false)throw new Error("经营专题详情与当前范围及版本不符");setDetail(result);setDetailLoading(false);}).catch(reason=>{if(current===epoch.current&&sequence===detailGeneration.current){setDetailLoading(false);failure(reason);}});
  }
  function openSector(pageId:string){currentAction(current=>{if(!current.topics.some(topic=>topic.page_id===pageId))throw new Error("当前范围没有所选经营专题");setSelected(pageId);remember({overviewTopic:pageId,overviewUse:pageId==="F19"?selectedUse:null});onTopic({scope:current.applied_scope,page_id:pageId,use:pageId==="F19"?selectedUse:null,snapshot_sha256:current.snapshot_sha256});});}
  function openSource(sourceId:string){
    if(!view||!detail||stale)return;
    const expected=detail.sources.find(row=>row.source_id===sourceId);
    if(!expected||expected.status!=="VALID"||!expected.version)throw new Error("当前专题没有可采用的来源引用");
    const current=epoch.current,sequence=++detailGeneration.current,payload={scope:view.applied_scope,page_id:detail.topic.page_id,snapshot_sha256:view.snapshot_sha256};
    setDetailLoading(true);setError("");
    const reject=(reason:unknown)=>{if(current===epoch.current&&sequence===detailGeneration.current){setDetailLoading(false);failure(reason);}};
    void fetch("/api/boss/ui/evidence?"+new URLSearchParams({source:sourceId}),{headers:{Authorization:"Bearer "+getToken()},cache:"no-store"}).then(async response=>{if(!response.ok)throw Object.assign(new Error("来源原文读取失败"),{status:response.status});return response.json() as Promise<SourceText>;}).then(result=>client.requestMutation<OverviewDetail>("boss.business_overview.detail",payload).then(checked=>{
      if(current!==epoch.current||sequence!==detailGeneration.current)return;
      if(result.source_id!==expected.source_id||result.version!==expected.version||checked.snapshot_sha256!==payload.snapshot_sha256)throw new Error("来源原文与当前固定版本不符");
      setSource(result);setDetailLoading(false);
    })).catch(reject);
  }
  const selectedTopic=view?.topics.find(row=>row.page_id===selected),disabled=!view||dirty||loading||denied||stale;
  const period=dimensions?.periods.find(row=>row.period_start===draft?.period_start&&row.period_end===draft?.period_end);
  const detailSourceIds=detail?new Set([...detail.topic.records.flatMap(row=>row.source_refs),...detail.topic.related_sales_source_refs].map(row=>row.source_id)):new Set<string>();
  const sourceMetadata=source?detail?.sources.find(row=>row.source_id===source.source_id)?.metadata:null;
  return <div ref={root}>
    <BossBusinessOverviewLayout scope={<>
      {error&&<p role="alert" className="boss-n03-note">{error}</p>}
      {loading&&<p role="status">正在读取当前经营范围。</p>}
      {dimensions&&draft&&<form onSubmit={event=>{event.preventDefault();apply(draft,true);}}>
        <div className="boss-n03-fields">
          <label className="boss-n03-field"><span>法人范围</span><select id="overview-entity" value={draft.legal_entity_id} disabled={denied} onChange={event=>edit({legal_entity_id:event.target.value})}>{dimensions.legal_entity_ids.map(value=><option key={value} value={value}>{value}</option>)}</select></label>
          <label className="boss-n03-field"><span>区域</span><select id="overview-region" value={draft.region_id??"ALL"} disabled={denied} onChange={event=>edit({region_id:event.target.value==="ALL"?null:event.target.value})}><option value="ALL">全部获准区域</option>{dimensions.region_ids.map(value=><option key={value} value={value}>{value}</option>)}</select></label>
          <label className="boss-n03-field"><span>期间</span><select id="overview-period" value={period?.id??""} disabled={denied} onChange={event=>{const next=dimensions.periods.find(row=>row.id===event.target.value);if(!next)throw new Error("当前经营期间不属于正式选项");edit({period_start:next.period_start,period_end:next.period_end});}}>{dimensions.periods.map(value=><option key={value.id} value={value.id}>{value.period_start} 至 {value.period_end}</option>)}</select></label>
          <label className="boss-n03-field"><span>关注条件</span><select id="overview-attention" value={draft.attention} disabled={denied} onChange={event=>edit({attention:event.target.value as OverviewScope["attention"]})}>{dimensions.attention_values.map(value=><option key={value} value={value}>{attentionLabels[value]}</option>)}</select></label>
        </div>
        <div className="boss-n03-actions"><button id="overview-apply" className="boss-btn boss-btn-primary" disabled={loading||denied}>{loading?"查询中…":"查询"}</button>{loading&&<button className="boss-btn" type="button" onClick={()=>{++generation.current;setLoading(false);}}>停止查询</button>}</div>
      </form>}
      <p className="boss-n03-note">{dirty?"范围已编辑，尚未应用。后续操作使用本人明确查询后的范围。":view?"当前已应用范围；指标采用所选期间，专题显示业务时钟下的当前状态。":"请选择范围并查询。尚未读取经营结果。"} {draft&&"业务时区："+draft.timezone}。关注条件仅支持当前正式选项。</p>
      {view&&<details><summary>指标查询与资料范围</summary><p>当前数值限定水产饲料外销经营范围，不代表完整农业专题结果。</p><dl className="boss-n03-kv">{view.metrics.map(metric=><div key={metric.metric_id}><dt>{metricLabels[metric.metric_id]??metric.metric_id}</dt><dd>{metric.value??"未知"} {metric.unit}</dd></div>)}</dl><p>覆盖状态：{state(view.metric_coverage.state)}；资料截至 {view.business_at}；读取时间 {view.read_at}。</p><div className="boss-n03-actions"><button id="overview-query" className="boss-btn" disabled={disabled||!view.query_handoff} onClick={()=>currentAction(onQuery)}>查看查询明细</button></div>{!view.query_handoff&&<p>当前没有完整可比期间、区域覆盖或有效经营来源，请核查范围及资料。</p>}</details>}
    </>} topics={<>
      {!view&&<p role="status">{denied?"当前身份无法读取专题。":"当前范围尚未取得正式专题记录。"}</p>}
      {!view&&!denied&&<div className="boss-n03-topics">{topicDirectory.map(([pageId,title],index)=><button key={pageId} type="button" className="boss-n03-topic" disabled><span className="boss-n03-topic-icon" aria-hidden="true">{String(index+1).padStart(2,"0")}</span><span className="boss-n03-topic-copy"><strong>{title}</strong><p>尚未读取当前专题。请明确查询经营关注范围。<br/>{topicRequirements[pageId]}</p></span></button>)}</div>}
      {view&&<div className="boss-n03-topics">{view.topics.map((topic,index)=><button key={topic.page_id} id={"overview-topic-"+topic.page_id} type="button" className="boss-n03-topic" aria-pressed={selected===topic.page_id} disabled={disabled} onClick={()=>openSector(topic.page_id)}><span className="boss-n03-topic-icon" aria-hidden="true">{String(index+1).padStart(2,"0")}</span><span className="boss-n03-topic-copy"><strong>{topic.title}</strong><p>{state(topic.availability)} · 资料截至：{topic.data_as_of??"未知"}<br/>覆盖缺口：{topic.missing_fields.length?topic.missing_fields.join("；"):"当前未报告额外缺口"} · 关联资料：{topic.records.length}项</p></span><ArrowRight size={18} aria-hidden="true"/></button>)}</div>}
      <p className="boss-n03-note">专题资料、通知及交办分别核查。禽类与反刍包含肉禽、蛋禽、奶畜、肉用牛羊，各自使用适用阶段与单位。</p>
    </>} details={<>
      <dl className="boss-n03-kv"><div><dt>最新资料时间</dt><dd>{selectedTopic?.data_as_of??"当前专题尚无已核查时间"}</dd></div><div><dt>当前覆盖缺口</dt><dd>{selectedTopic?topicRequirements[selectedTopic.page_id]:"选择专题后查看具体资料要求"}</dd></div></dl>
      <div className="boss-n03-actions">{selectedTopic&&<button id="overview-selected" className="boss-btn" disabled={disabled} onClick={()=>openTopic(selected)}>查看资料范围</button>}<button id="overview-right-query" className="boss-btn" disabled={disabled||!view?.query_handoff} onClick={()=>currentAction(onQuery)}>查看查询明细</button><button id="overview-discuss" className="boss-btn boss-btn-primary" disabled={disabled} onClick={()=>currentAction(current=>void onDiscuss({scope:current.applied_scope,page_id:selectedTopic?.page_id??null,use:selectedTopic?.page_id==="F19"?selectedUse:null,snapshot_sha256:current.snapshot_sha256}))}>让大鹏分析</button></div>
      {view&&<details><summary>来源原文 · {view.sources.length}项</summary>{view.sources.map(source=><div key={source.source_id}><p>{source.source_id} · 版本 {source.version??"待核查"} · {state(source.status)}</p><button id={"overview-source-"+source.source_id} type="button" className="boss-btn" disabled={disabled||source.status!=="VALID"} onClick={()=>currentAction(current=>{const found=current.sources.find(row=>row.source_id===source.source_id&&row.version===source.version&&row.status==="VALID");if(!found)throw new Error("当前来源版本需要重新核查");onViewSource(found.source_id);})}>查看依据</button></div>)}</details>}
      {conversationStatus}
      {view&&<>
        <details><summary>本人参与提醒 · {view.alerts.length} 项</summary>{view.alerts.length===0?<p>当前已应用范围没有匹配的经营提醒。</p>:view.alerts.map(alert=><article key={alert.event_id}><p>事项 {alert.event_id} · 事件版本 {alert.event_version} · {state(alert.adoption_state)}</p><p>{alert.facts?.participation_reason??"当前来源需要重新核查，原参与依据不可采用。"}</p><p>提醒 {alert.reminder?.state??"尚无提醒"}；源事件 {alert.state}；规则 {alert.business_rule?.version??"未知"}；通知 {String(alert.notification?.state??"当前没有通知记录")}。</p><p>处理人 {alert.facts?.handler_id??"未知"}；已有措施 {alert.existing_measures.length?alert.existing_measures.map(row=>String(row.kind)+" / "+String(row.task_id??row.plan_id??"当前对象")+" / "+String(row.status??row.state??"未知")).join("；"):"当前没有已记录措施"}。</p><p>缺少条件 {alert.missing_fields.join("；")||"当前没有额外缺少条件"}；关联任务 {alert.assignment_references.length?alert.assignment_references.map(row=>String(row.task_id)+" v"+String(row.task_version)).join("；"):"当前没有正式关联任务"}。</p><button id={"overview-alert-"+alert.event_id} className="boss-btn" disabled={disabled} onClick={()=>currentAction(current=>{const found=current.alerts.find(row=>row.event_id===alert.event_id);if(!found)throw new Error("当前范围没有所选经营提醒");onReminder(found);})}>查看提醒</button></article>)}</details>
        <details><summary>关联事项 · {view.associations.length} 项</summary>{view.associations.length===0?<p>当前没有按正式来源关系匹配的交办事项。</p>:view.associations.map(task=><article key={task.id}><p>{task.id} · v{task.version} · {task.state} · {state(task.adoption_state)}</p><button id={"overview-task-"+task.id} className="boss-btn" disabled={disabled} onClick={()=>currentAction(current=>{const found=current.associations.find(row=>row.id===task.id);if(!found)throw new Error("当前范围没有所选关联事项");onTask(found);})}>查看关联交办</button></article>)}</details>
        <p>业务时钟 {view.business_at}<br/>本次读取 {view.read_at}</p>
      </>}
    </>}/>
    <Dialog open={dialogOpen} onOpenChange={open=>{if(!open)++detailGeneration.current;setDialogOpen(open);}}>
      <DialogContent className="boss-v6 boss-n03-dialog" overlayClassName="boss-n03-overlay" onCloseAutoFocus={event=>{event.preventDefault();if(trigger.current?.isConnected)trigger.current.focus({preventScroll:true});}}>
        <div className="boss-n03-dialog-head"><DialogTitle>{source?"来源原文":detail?.topic.title??selectedTopic?.title??"经营专题"}</DialogTitle><DialogClose asChild><button className="boss-btn" aria-label="关闭专题详情"><X size={18}/></button></DialogClose></div>
        <DialogDescription>当前已应用范围及固定资料版本；专业结论、提醒和交办分别核查。</DialogDescription>
        {detailLoading&&<p role="status">正在核查当前专题与来源。</p>}
        {error&&<p role="alert">{error}</p>}
        {source?<><p>{source.source_id} · v{source.version} · {source.source_type} · {source.author_display_name??source.author_contact_id??"作者尚未提供"}</p><p>发布时间 {source.published_at??"未知"}；观察时间 {sourceMetadata?.observed_at??"未知"}；读取时间 {source.read_at}。</p><p>适用范围：{typeof sourceMetadata?.coverage==="string"?sourceMetadata.coverage:sourceMetadata?.coverage?JSON.stringify(sourceMetadata.coverage):"当前来源没有提供完整范围"}。</p><p>有效期间：{sourceMetadata?.valid_from??"未知"} 至 {sourceMetadata?.valid_until??"未知"}。</p>{sourceMetadata?.original_locator!==null&&sourceMetadata?.original_locator!==undefined&&<p>原文位置：{typeof sourceMetadata.original_locator==="string"?sourceMetadata.original_locator:JSON.stringify(sourceMetadata.original_locator)}</p>}<blockquote className="boss-n03-source">{source.content}</blockquote><button className="boss-btn" onClick={()=>setSource(null)}>返回当前专题</button></>:detail&&<>
          <p>{state(detail.topic.availability)}；资料截至 {detail.topic.data_as_of??"未知"}；来源发布时间 {detail.topic.latest_source_published_at??"未知"}。</p>
          <p>用途：{detail.topic.purpose.filters.join("、")}；核查内容：{detail.topic.purpose.indicators.join("、")}。</p><p>{topicRequirements[detail.topic.page_id]}</p>
          {detail.topic.uses.length>0&&<><div className="boss-n03-actions" aria-label="禽类与反刍用途">{detail.topic.uses.map(value=><button type="button" className="boss-btn" key={value} aria-pressed={selectedUse===value} onClick={()=>{setSelectedUse(value);remember({overviewUse:value});}}>{useLabels[value]}</button>)}</div><p>当前用途：{selectedUse?useLabels[selectedUse]:"尚未选择"}。当前缺少完整专业资料，切换用途不会合并不相容指标。</p></>}
          {detail.topic.records.length===0?<p>当前没有符合范围及关注条件的本专题正式对象。</p>:detail.topic.records.map(record=><article key={record.kind+":"+record.id}><p>{record.kind} · {record.id} · v{record.version??"未知"} · {state(record.adoption_state)}</p><p>当前状态 {record.state??"未知"}</p>{record.facts&&<dl className="boss-n03-kv">{Object.entries(record.facts).map(([key,value])=><div key={key}><dt>{factLabels[key]??key}</dt><dd>{value===null?"未知":String(value)}</dd></div>)}</dl>}</article>)}
          {detail.sources.filter(row=>detailSourceIds.has(row.source_id)).map(row=><article key={row.source_id}><p>{row.source_id} · v{row.version??"未知"} · {state(row.status)} · {row.metadata?.author_display_name??row.metadata?.author_contact_id??"当前作者不可采用"}</p><button className="boss-btn" disabled={stale||row.status!=="VALID"||detailLoading} onClick={()=>openSource(row.source_id)}>来源原文</button></article>)}
          <div className="boss-n03-actions"><button className="boss-btn" disabled={disabled||detailLoading} onClick={()=>{capture(trigger.current);setDialogOpen(false);void onDiscuss({scope:detail.applied_scope,page_id:detail.topic.page_id,use:detail.topic.page_id==="F19"?selectedUse:null,snapshot_sha256:detail.snapshot_sha256});}}>继续讨论</button><button className="boss-btn" disabled={disabled||detailLoading} onClick={()=>{capture(trigger.current);setDialogOpen(false);requestAnimationFrame(()=>onPrepare(detail,detail.topic.page_id==="F19"?selectedUse:null));}}>准备会议或交办</button></div>
          {!detail.topic.records.some(row=>row.adoption_state==="CURRENT")&&<p>准备会议或交办需要当前有效对象及来源；现有资料尚不足。</p>}
        </>}
      </DialogContent>
    </Dialog>
  </div>;
}
