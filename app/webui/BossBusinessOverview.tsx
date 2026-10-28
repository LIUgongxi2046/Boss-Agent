import {useCallback,useEffect,useRef,useState,type ReactNode} from "react";
import {ArrowRight,X} from "lucide-react";
import {useClient} from "@/providers/ClientProvider";
import {Dialog,DialogContent,DialogTitle,DialogDescription,DialogClose} from "@/components/ui/dialog";
import {BossBusinessOverviewLayout} from "./BossBusinessOverviewLayout";
import type {Overview,OverviewScope,OverviewDimensions,OverviewDetail,OverviewSelection,OverviewAssociation} from "./business-overview-types";
import type {BusinessAlert} from "./BossBusinessAlerts";
import {BossInsightList} from "./BossInsightList";

type Props={visible:boolean;refreshVersion:number;discardVersion:number;onDirtyChange:(dirty:boolean)=>void;onQuery:(view:Overview)=>void;onReminder:(alert:BusinessAlert)=>void;onTask:(task:OverviewAssociation)=>void;onDiscuss:(selection:OverviewSelection)=>Promise<void>;onPrepare:(detail:OverviewDetail,use:OverviewSelection["use"])=>void;conversationStatus:ReactNode;onTopic:(selection:OverviewSelection)=>void;onViewSource:(id:string)=>void};
type SourceText={source_id:string;version:string;source_type:string;content:string;author_contact_id?:string;author_display_name?:string;published_at?:string;read_at:string};
const scopeKeys=["legal_entity_id","region_id","period_start","period_end","timezone","attention"] as const;
const sameScope=(first:OverviewScope,second:OverviewScope)=>scopeKeys.every(key=>first[key]===second[key]);
const metricLabels:Record<string,string>={sales_quantity:"销量",revenue:"营业收入",cost:"成本",gross_profit:"毛利",gross_margin:"毛利率",gross_profit_per_tonne:"单吨毛利"};
const numberFormat=new Intl.NumberFormat("zh-CN",{maximumFractionDigits:2});
function metricValue(value:string){return numberFormat.format(Number(value));}
function trendTone(label:string,change:number){const lower=["入库成本","领用成本","交付缺口"].includes(label),higher=["订单","回款范围"].includes(label);return change===0||!lower&&!higher?"neutral":(lower?change<0:change>0)?"improved":"risk";}
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

export function BossBusinessOverview({visible,refreshVersion,discardVersion,onDirtyChange,onQuery,onReminder,onDiscuss,onPrepare,conversationStatus}:Props){
  const {client,getToken,token}=useClient();
  const [business,setBusiness]=useState(()=>new URLSearchParams(window.location.search).get("overviewBusiness")??"ALL");
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
      const period=result.periods.find(value=>value.id==="SECTOR_CURRENT")??result.periods.find(value=>value.id==="CURRENT");
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
  const priorities:Record<string,string[]>={F14:["领用成本","合同价格"],F15:["订单"],F22:["订单","回款范围","交付缺口"]};
  const featured=view?.topics.filter(topic=>business==="ALL"||topic.page_id===business).flatMap(topic=>(topic.metrics??[]).filter(metric=>priorities[topic.page_id]?.includes(metric.label)).map(metric=>({...metric,topic:topic.title})))??[];
  const detailSourceIds=detail?new Set([...detail.topic.records.flatMap(row=>row.source_refs),...detail.topic.related_sales_source_refs].map(row=>row.source_id)):new Set<string>();
  return <div ref={root}>
    <BossBusinessOverviewLayout scope={<>
      {error&&<p role="alert" className="boss-n03-note">{error}</p>}
      {loading&&<p role="status">正在读取当前经营范围。</p>}
      {dimensions&&draft&&<form className="boss-compact-query" onSubmit={event=>{event.preventDefault();apply(draft,true);}}>
        <div className="boss-n03-fields">
          <label className="boss-n03-field"><span>业务</span><select value={business} onChange={event=>{setBusiness(event.target.value);remember({overviewBusiness:event.target.value});}}><option value="ALL">全部业务</option>{topicDirectory.map(([id,title])=><option key={id} value={id}>{title}</option>)}</select></label>
          <label className="boss-n03-field"><span>期间</span><select id="overview-period" value={period?.id??""} disabled={denied} onChange={event=>{const next=dimensions.periods.find(row=>row.id===event.target.value);if(!next)throw new Error("当前经营期间不属于正式选项");edit({period_start:next.period_start,period_end:next.period_end});}}>{dimensions.periods.map(value=><option key={value.id} value={value.id}>{value.period_start} 至 {value.period_end}</option>)}</select></label>
        </div>
        <details><summary>高级查询</summary><div className="boss-n03-fields">
          <label className="boss-n03-field"><span>法人范围</span><select id="overview-entity" value={draft.legal_entity_id} disabled={denied} onChange={event=>edit({legal_entity_id:event.target.value})}>{dimensions.legal_entity_ids.map((value,index)=><option key={value} value={value}>经营主体 {index+1}</option>)}</select></label>
          <label className="boss-n03-field"><span>区域</span><select id="overview-region" value={draft.region_id??"ALL"} disabled={denied} onChange={event=>edit({region_id:event.target.value==="ALL"?null:event.target.value})}><option value="ALL">全部区域</option>{dimensions.region_ids.map((value,index)=><option key={value} value={value}>经营区域 {index+1}</option>)}</select></label>
          <label className="boss-n03-field"><span>关注条件</span><select id="overview-attention" value={draft.attention} disabled={denied} onChange={event=>edit({attention:event.target.value as OverviewScope["attention"]})}>{dimensions.attention_values.map(value=><option key={value} value={value}>{attentionLabels[value]}</option>)}</select></label>
        </div></details>
        <div className="boss-n03-actions"><button id="overview-apply" className="boss-btn boss-btn-primary" disabled={loading||denied}>{loading?"查询中…":"查询"}</button>{loading&&<button className="boss-btn" type="button" onClick={()=>{++generation.current;setLoading(false);}}>停止查询</button>}</div>
      </form>}
    </>} topics={<>
      {!view&&<p role="status">{denied?"当前身份无法读取专题。":"当前范围尚未取得正式专题记录。"}</p>}
      {featured.length>0&&<section aria-label="老板关注指标"><h3>老板关注</h3><div className="boss-kpi-grid">{featured.map(metric=><div className="boss-kpi" key={metric.topic+metric.label}><span>{metric.topic} · {metric.label==="交付缺口"?"待补交付量":metric.label==="回款范围"?"回款金额":metric.label}</span><strong>{metricValue(metric.value)}</strong><small>{metric.unit.replace("CNY","元")} · {metric.period}</small>{metric.change_percent!==null&&<small className={"boss-metric-trend boss-metric-"+trendTone(metric.label,Number(metric.change_percent))}>{Number(metric.change_percent)===0?"— 持平":`${Number(metric.change_percent)>0?"↑":"↓"} ${Math.abs(Number(metric.change_percent))}%`} · 较上一报告期</small>}</div>)}</div></section>}
      {!view&&!denied&&<div className="boss-n03-topics">{topicDirectory.map(([pageId,title],index)=><button key={pageId} type="button" className="boss-n03-topic" disabled><span className="boss-n03-topic-icon" aria-hidden="true">{String(index+1).padStart(2,"0")}</span><span className="boss-n03-topic-copy"><strong>{title}</strong><p>尚未读取当前专题。请明确查询经营关注范围。<br/>{topicRequirements[pageId]}</p></span></button>)}</div>}
      {view&&business==="ALL"&&view.metrics.some(metric=>metric.value!==null)&&<section><h3>水产饲料 · 经营重点</h3><p className="boss-metric-legend">所选期间的对外销售数据</p><div className="boss-kpi-grid">{[...view.metrics].filter(metric=>metric.value!==null).sort((a,b)=>["revenue","gross_profit","gross_margin","sales_quantity","gross_profit_per_tonne","cost"].indexOf(a.metric_id)-["revenue","gross_profit","gross_margin","sales_quantity","gross_profit_per_tonne","cost"].indexOf(b.metric_id)).map(metric=><div className="boss-kpi" key={metric.metric_id}><span>{metricLabels[metric.metric_id]}</span><strong>{metricValue(metric.value!)}</strong><small>{metric.unit.replace("CNY","元").replace("tonne","吨")}</small></div>)}</div><button id="overview-query" className="boss-btn" disabled={disabled||!view.query_handoff} onClick={()=>currentAction(onQuery)}>查看经营分析</button></section>}
      <p className="boss-metric-legend"><span className="boss-metric-improved">绿色：改善</span> · <span className="boss-metric-risk">红色：需要关注</span> · 箭头表示升降；其他变化保留中性色</p>
      {view&&<div className="boss-n03-topics">{view.topics.filter(topic=>business==="ALL"||topic.page_id===business).map((topic,index)=><button key={topic.page_id} id={"overview-topic-"+topic.page_id} type="button" className="boss-n03-topic" aria-pressed={selected===topic.page_id} disabled={disabled} onClick={()=>openTopic(topic.page_id)}><span className="boss-n03-topic-icon" aria-hidden="true">{String(index+1).padStart(2,"0")}</span><span className="boss-n03-topic-copy"><strong>{topic.title}</strong>{topic.metrics?.length?topic.metrics.map(metric=><span className="boss-business-metric" key={metric.label}><span>{metric.label}</span><strong>{metricValue(metric.value)} <small>{metric.unit.replace("CNY","元")}</small></strong>{metric.change_percent!==null?<small className={"boss-metric-trend boss-metric-"+trendTone(metric.label,Number(metric.change_percent))}>{Number(metric.change_percent)===0?"— 持平":`${Number(metric.change_percent)>0?"↑":"↓"} ${Math.abs(Number(metric.change_percent))}%`} · 较上一报告期</small>:<small>暂无可比期间</small>}</span>):<p>所选期间没有经营报表。</p>}</span><ArrowRight size={18} aria-hidden="true"/></button>)}</div>}
    </>} details={<>
      {conversationStatus}
      {view?.alerts.filter(alert=>alert.adoption_state==="CURRENT"&&alert.facts).map(alert=><article className="boss-workspace-item" key={alert.event_id}><h3>经营情况需要关注</h3><p>{alert.facts!.participation_reason}</p><p>{alert.facts!.impact}</p><button id={"overview-alert-"+alert.event_id} className="boss-btn" disabled={disabled} onClick={()=>currentAction(current=>{const found=current.alerts.find(row=>row.event_id===alert.event_id);if(!found)throw new Error("当前提醒已经变化");onReminder(found);})}>处理提醒</button></article>)}
      {view&&<BossInsightList items={view.insights.filter(item=>business==="ALL"||item.target_id===business)} buttonId={item=>"overview-insight-"+item.target_id} disabled={disabled} label="在聊天中追查" onOpen={item=>currentAction(current=>void onDiscuss({scope:current.applied_scope,page_id:item.target_id,use:null,snapshot_sha256:current.snapshot_sha256}))}/>}
      <button id="overview-discuss" className="boss-btn boss-btn-primary" disabled={disabled} onClick={()=>currentAction(current=>void onDiscuss({scope:current.applied_scope,page_id:business==="ALL"?null:business,use:null,snapshot_sha256:current.snapshot_sha256}))}>请 Boss Agent 分析</button>
    </>}/>
    <Dialog open={dialogOpen} onOpenChange={open=>{if(!open)++detailGeneration.current;setDialogOpen(open);}}>
      <DialogContent showCloseButton={false} className="boss-v6 boss-n03-dialog" overlayClassName="boss-n03-overlay" onCloseAutoFocus={event=>{event.preventDefault();if(trigger.current?.isConnected)trigger.current.focus({preventScroll:true});}}>
        <div className="boss-n03-dialog-head"><DialogTitle>{source?"来源原文":detail?.topic.title??selectedTopic?.title??"经营专题"}</DialogTitle><DialogClose asChild><button className="boss-btn" aria-label="关闭专题详情"><X size={18}/></button></DialogClose></div>
        <DialogDescription>查看所选期间的经营指标与相关材料。</DialogDescription>
        {detailLoading&&<p role="status">正在核查当前专题与来源。</p>}
        {error&&<p role="alert">{error}</p>}
        {source?<>{source.author_display_name&&<p>作者：{source.author_display_name}</p>}<blockquote className="boss-n03-source">{source.content}</blockquote><button className="boss-btn" onClick={()=>setSource(null)}>返回当前专题</button></>:detail&&<>
          <p>{detail.applied_scope.period_start} 至 {detail.applied_scope.period_end}</p>
          <dl className="boss-n03-kv">{(detail.topic.metrics??[]).map(metric=><div key={metric.label}><dt>{metric.label}</dt><dd>{metric.value} {metric.unit.replace("CNY","元")}{metric.change_percent!==null&&<small> · {Number(metric.change_percent)===0?"与上月持平":`较上月${Number(metric.change_percent)>0?"增加":"减少"} ${Math.abs(Number(metric.change_percent))}%`}</small>}</dd></div>)}</dl>
          {detail.topic.uses.length>0&&<><div className="boss-n03-actions" aria-label="禽类与反刍用途">{detail.topic.uses.map(value=><button type="button" className="boss-btn" key={value} aria-pressed={selectedUse===value} onClick={()=>{setSelectedUse(value);remember({overviewUse:value});}}>{useLabels[value]}</button>)}</div><p>当前用途：{selectedUse?useLabels[selectedUse]:"尚未选择"}。当前缺少完整专业资料，切换用途不会合并不相容指标。</p></>}
          {detail.topic.records.length===0?<p>当前没有符合查询条件的经营资料。</p>:detail.topic.records.map(record=><article key={record.kind+":"+record.id}>{record.facts&&<dl className="boss-n03-kv">{Object.entries(record.facts).filter(([key,value])=>factLabels[key]&&typeof value==="string"&&!/[A-Za-z_]/.test(value)).map(([key,value])=><div key={key}><dt>{factLabels[key]}</dt><dd>{String(value)}</dd></div>)}</dl>}</article>)}
          {detail.sources.filter(row=>detailSourceIds.has(row.source_id)).map((row,index)=><article key={row.source_id}><button className="boss-btn" disabled={stale||row.status!=="VALID"||detailLoading} onClick={()=>openSource(row.source_id)}>阅读相关材料 {index+1}</button>{row.status!=="VALID"&&<p>{state(row.status)}</p>}</article>)}
          <div className="boss-n03-actions"><button className="boss-btn" disabled={disabled||detailLoading} onClick={()=>{capture(trigger.current);setDialogOpen(false);void onDiscuss({scope:detail.applied_scope,page_id:detail.topic.page_id,use:detail.topic.page_id==="F19"?selectedUse:null,snapshot_sha256:detail.snapshot_sha256});}}>继续讨论</button><button className="boss-btn" disabled={disabled||detailLoading} onClick={()=>{capture(trigger.current);setDialogOpen(false);requestAnimationFrame(()=>onPrepare(detail,detail.topic.page_id==="F19"?selectedUse:null));}}>准备会议或交办</button></div>
          {!detail.topic.records.some(row=>row.adoption_state==="CURRENT")&&<p>准备会议或交办需要当前有效对象及来源；现有资料尚不足。</p>}
        </>}
      </DialogContent>
    </Dialog>
  </div>;
}
