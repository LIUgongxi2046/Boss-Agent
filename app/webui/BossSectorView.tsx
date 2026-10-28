import {useCallback,useEffect,useRef,useState} from "react";
import {useClient} from "@/providers/ClientProvider";
import {ArrowUpRight,Search} from "lucide-react";
import metadata from "./page-meta.json";
import {V7Empty,V7Fact,V7Metric,V7Panel,V7Pagination,V7ReadState,V7Steps,V7Tabs} from "./BossV7UI";
import {BusinessOverviewReference,readOverviewReference,verifyOverviewReference} from "./BusinessOverviewReference";
import {BIRecordContent} from "./BIRecordContent";
import {BossSectorFollowUp} from "./BossSectorFollowUp";
import {BossMetricTrend as Trend} from "./BossMetricTrend";
import type {OverviewSelection} from "./business-overview-types";
import type {SectorAction,SectorActionKind,SectorMetric,SectorProjection,SectorSection} from "./sector-types";

export const SECTOR_PAGE_IDS=["F14","F15","F16","F17","F18","F19","F20","F21","F22","F23","V19-BEEF","V19-EGG","V19-MILK"] as const;
type Props={pageId:string;onNavigate:(page:string)=>void;onBeforeLeave:(leave:()=>void)=>void;onViewSource:(id:string)=>void;onStartChat:(content:string)=>Promise<boolean|void>;onDirtyChange:(value:boolean)=>void;onOpenTask:(id:string)=>void;refreshVersion?:number};
type PageAction={code:string;label:string;chat:boolean;kind?:SectorActionKind};
const VARIANTS=[{id:"F19",title:"肉禽"},{id:"V19-EGG",title:"蛋禽"},{id:"V19-MILK",title:"奶畜"},{id:"V19-BEEF",title:"肉用牛羊"}];
const ACTION_KINDS:Record<string,SectorActionKind>={"选择统筹负责人":"COORDINATE","交办":"COORDINATE","创建联合核查":"COORDINATE","授权资源协调":"COORDINATE","资源协调":"COORDINATE","授权核查任务":"COORDINATE","授权设备协调":"COORDINATE","安排复查":"REVIEW","安排后续查询":"REVIEW","继续验证":"REVIEW","准备经营复查":"REVIEW","准备会面":"MEETING","准备跨时区会议":"MEETING","记录资源决定":"DECISION","调整项目":"DECISION","记录安排":"DECISION"};
const QUERY_LABELS:Record<string,string>={F14:"查询原料与成本",F15:"查询季节经营情况",F16:"查询批次关系",F17:"查询服务记录",F18:"查询合作经营情况",F19:"查询肉禽表现",F21:"查询品质追溯",F20:"查询养殖观测",F22:"查询海外经营",F23:"查询试验结果","V19-EGG":"查询蛋禽表现","V19-MILK":"查询奶畜表现","V19-BEEF":"查询肉用牛羊表现"};
const ROW_VIEW_LABELS:Record<string,string>={F15:"查看明细",F16:"查看阶段记录",F17:"查看本次服务",F18:"查看数量与结算明细",F19:"查看供料与出栏明细",F20:"查看观测记录",F22:"查看订单与回款记录",F23:"查看本次试验","V19-EGG":"查看产蛋记录","V19-MILK":"查看产奶记录","V19-BEEF":"查看生长记录"};
const ACTION_LABELS:Record<string,Record<string,string>>={
  F15:{"核查原因":"让 Boss Agent 核查变化原因","交办":"准备供货协调交办"},
  F16:{"创建联合核查":"准备联合核查交办"},
  F17:{"打开专业资料":"查看检测与专业意见","授权资源协调":"准备技服协调交办","安排后续查询":"安排专业复查"},
  F18:{"查看明细":"查看数量与结算明细","准备经营复查":"安排经营复查","授权核查任务":"准备数量／费用核查交办"},
  F19:{"继续查询":"让 Boss Agent 分析肉禽表现","查看明细":"查看供料与出栏明细","准备会面":"准备客户会面材料","资源协调":"准备肉禽业务协调"},
  "V19-EGG":{"继续查询":"让 Boss Agent 分析蛋禽表现","查看明细":"查看产蛋记录与合格蛋重","准备会面":"准备蛋禽客户会面","资源协调":"准备蛋禽业务协调"},
  "V19-MILK":{"继续查询":"让 Boss Agent 分析产奶变化","查看明细":"查看供料与产奶记录","准备会面":"准备奶畜客户会面","资源协调":"准备奶畜业务协调"},
  "V19-BEEF":{"继续查询":"让 Boss Agent 分析生长与出栏","查看明细":"查看生长与出栏记录","准备会面":"准备客户会面材料","资源协调":"准备牛羊业务协调"},
  F20:{"授权设备协调":"准备设备处理交办"},
  F22:{"查看选项":"查看资源协调选项","记录资源决定":"核对并记录资源决定"},
  F23:{"继续验证":"准备补充验证任务","调整项目":"提出项目调整意见","记录安排":"核对并记录本次决定"},
};
const HIDDEN_ACTIONS:Record<string,string[]>={F15:["选择统筹负责人"],F23:["打开原文"]};
const CHAT_REQUESTS:Record<string,string>={F15:"核查变化原因",F19:"分析肉禽表现","V19-EGG":"分析蛋禽表现","V19-MILK":"分析产奶变化","V19-BEEF":"分析生长与出栏"};
const UNIT_META_LABELS=new Set(["适用单位","计量单位"]);
const PERIOD_META_LABELS=new Set(["观察期"]);
const QUANTITY_LABELS=new Set(["存栏","转群","出栏重量","数量平衡"]);
const MASS_LABELS=new Set(["体重","合格蛋重","出栏重量"]);
const COUNT_UNITS=/^(头|只|羽|枚)$/;
const MASS_UNITS=/^(公斤|千克|克|吨|kg|t|g)$/;
const CLAIM_LABELS={FACT:"事实",OPINION:"作者意见",INFERENCE:"推断"};
function queryKey(fields:Record<string,string>){return JSON.stringify(Object.entries(fields).filter(([,value])=>value!=="").sort(([a],[b])=>a.localeCompare(b)));}

export function BossSectorView(props:Props){
  const {token}=useClient();
  const identity=useRef({token,sequence:0});
  if(identity.current.token!==token)identity.current={token,sequence:identity.current.sequence+1};
  return <SectorWorkspace key={props.pageId+identity.current.sequence} {...props}/>;
}

function SectorWorkspace({pageId,onNavigate,onBeforeLeave,onViewSource,onStartChat,onDirtyChange,onOpenTask,refreshVersion}:Props){
  const design=(metadata as Record<string,{title:string;filters:string[];fields:string[];sections:string[];actions:string[];right:string[]}>)[pageId];
  if(!design||!(SECTOR_PAGE_IDS as readonly string[]).includes(pageId))throw new Error("专题页面没有对应设计定义");
  const {getToken,token}=useClient();
  const [overviewReference]=useState(()=>readOverviewReference(pageId));
  const [data,setData]=useState<SectorProjection|null>(null),[fields,setFields]=useState<Record<string,string>>({}),[applied,setApplied]=useState<Record<string,string>>({});
  const [revision,setRevision]=useState(0),[loading,setLoading]=useState(true),[error,setError]=useState(""),[sending,setSending]=useState(false);
  const [page,setPage]=useState(1),[selected,setSelected]=useState(""),[action,setAction]=useState<SectorAction|null>(null),[followupDirty,setFollowupDirty]=useState(false);
  const recordsRef=useRef<HTMLDivElement>(null),sourcesRef=useRef<HTMLElement>(null),optionsRef=useRef<HTMLDivElement>(null),professionalRef=useRef<HTMLDivElement>(null),actionRef=useRef<HTMLDivElement>(null);
  const epoch=useRef(0),current=!loading&&!error?data:null,queryDirty=queryKey(fields)!==queryKey(applied);
  const reload=useCallback(()=>setRevision(value=>value+1),[]);
  useEffect(()=>{onDirtyChange(queryDirty||followupDirty||sending);return()=>onDirtyChange(false);},[queryDirty,followupDirty,sending,onDirtyChange]);
  useEffect(()=>{
    const abort=new AbortController(),identity=++epoch.current;setLoading(true);setError("");setData(null);
    const query=new URLSearchParams({page:pageId,filters:JSON.stringify(applied)});
    if(overviewReference)query.set("overview_reference",JSON.stringify(overviewReference));
    void fetch("/api/boss/ui/sector?"+query,{headers:{Authorization:"Bearer "+getToken()},cache:"no-store",signal:abort.signal}).then(async response=>{
      if(response.status===401)window.dispatchEvent(new Event("boss-auth-expired"));
      if(!response.ok)throw new Error("专题资料读取失败（HTTP "+response.status+"）");
      const value=await response.json() as SectorProjection;
      if(value.projection!=="sector-workspace"||value.page_id!==pageId||value.source_type!=="SIMULATED"||!value.namespace||!value.dataset_version||queryKey(value.applied_filters)!==queryKey(applied))throw new Error("专题资料与当前查询范围不一致");
      verifyOverviewReference(overviewReference,value.overview_reference);
      if(abort.signal.aborted||identity!==epoch.current)return;
      setData(value);setLoading(false);
    }).then(undefined,reason=>{if(!abort.signal.aborted&&identity===epoch.current){setError(reason.message);setLoading(false);}});
    return()=>{abort.abort();epoch.current++;};
  },[pageId,applied,revision,getToken,token,overviewReference,refreshVersion]);
  function navigate(target:string){onBeforeLeave(()=>{
    if(overviewReference&&VARIANTS.some(item=>item.id===target)){
      const uses:Record<string,NonNullable<OverviewSelection["use"]>>={F19:"BROILER","V19-EGG":"EGG","V19-MILK":"MILK","V19-BEEF":"BEEF"};
      const address=new URL(window.location.href);address.searchParams.set("overviewSectorReference",JSON.stringify({...overviewReference,use:uses[target]}));address.searchParams.set("overviewUse",uses[target]);window.history.replaceState(window.history.state,"",address);
    }
    onNavigate(target);
  });}
  function applyQuery(){if(loading||followupDirty||sending)return;setApplied(Object.fromEntries(Object.entries(fields).map(([key,value])=>[key,value.trim()]).filter(([,value])=>value)));setFields(value=>Object.fromEntries(Object.entries(value).map(([key,text])=>[key,text.trim()])));setRevision(value=>value+1);setPage(1);setSelected("");setAction(null);}
  async function discuss(request:string){
    if(!current||sending||queryDirty||followupDirty)return;
    const identity=epoch.current;setSending(true);setError("");
    const prompt=["专题："+current.title,"本次请求："+request,"执行空间："+current.namespace,"查询编号："+(current.query_id??"未提供"),"数据版本："+current.dataset_version,"查询条件："+JSON.stringify(current.applied_filters),"经营范围："+JSON.stringify(overviewReference),"来源引用："+current.sources.map(source=>source.source_id+" v"+source.version).join("、"),"需要补充："+current.missing_fields.join("、"),"请读取相同范围内的当前有效资料，分别说明事实、作者意见、推断及所需条件。此请求仅查询资料，不授权创建或发送业务事项。"].join("\n");
    await onStartChat(prompt).then(result=>{if(identity!==epoch.current)return;if(result===false)throw new Error("会话未接受本次专题请求");setSending(false);onNavigate("N02");}).then(()=>{if(identity===epoch.current)setSending(false);},reason=>{if(identity===epoch.current){setError(reason.message);setSending(false);}});
  }
  const rows=current?.records??[],currentPage=Math.min(page,Math.max(1,Math.ceil(rows.length/10))),record=rows.find(row=>row.id===selected),variant=VARIANTS.some(item=>item.id===pageId);
  const filters=pageId==="F19"?["阶段","客户","观察期","日龄"]:pageId==="F15"?["区域","品种","阶段","当前周期","比较周期"]:pageId==="F17"?[...design.filters,"资料有效期"]:design.filters;
  const professionalTitles=pageId==="F15"?["客户反馈","原因假设","下次复查"]:pageId==="F16"?["共同批次","差异条件","观察资料","专业反馈"]:pageId==="F17"?["专业确认","服务反馈","资源缺口","下一复查时间"]:pageId==="F18"?["公司与农场归属","预计结果","未结算项目","负责人解释"]:pageId==="F20"?["专业确认","估计影响","复查资料","费用归属"]:pageId==="F22"?["国别资料有效期","决定期限","跨时区会议"]:pageId==="F23"?["专家评审","客户反馈","适用范围","未验证条件"]:["服务反馈","覆盖分母","阶段与单位可比性"];
  const mainTitles=pageId==="F15"?["季节比较","天气观察"]:pageId==="F18"?["批次与数量","投入成本"]:pageId==="F22"?["本币金额","折算金额"]:variant?["适用单位","阶段与单位可比性"]:design.sections;
  const pageActions:PageAction[]=(design.actions??[]).filter(code=>!(HIDDEN_ACTIONS[pageId]??[]).includes(code)).map(code=>({code,label:ACTION_LABELS[pageId]?.[code]??code,chat:code==="核查原因"||code==="继续查询",kind:ACTION_KINDS[code]}));
  function sourceButtons(ids:string[]){return <div className="boss-actions">{ids.map(id=><button key={id} className="boss-v7-text-button" aria-label={"查看依据："+id} onClick={()=>onViewSource(id)}>查看依据<ArrowUpRight size={14}/></button>)}</div>;}
  function section(title:string){const value=current?.sections.find(item=>item.title===title);return <article key={title} className="boss-sector-section"><strong>{title}</strong>{value?.claim_kind&&<span className="boss-tag">{CLAIM_LABELS[value.claim_kind]}</span>}<p>{value?.text??"尚未提供当前范围的资料"}</p>{value&&<><small>{value.state}{value.author?" · "+value.author:""}</small>{value.limitations?.length?<ul>{value.limitations.map(item=><li key={item}>{item}</li>)}</ul>:null}{sourceButtons(value.source_ids)}</>}</article>;}
  function metricCard(metric:SectorMetric){
    const unit=metric.unit??"";
    const unitConflict=(QUANTITY_LABELS.has(metric.label)&&Boolean(unit)&&!COUNT_UNITS.test(unit))||(MASS_LABELS.has(metric.label)&&Boolean(unit)&&!MASS_UNITS.test(unit));
    if(UNIT_META_LABELS.has(metric.label))return <div key={metric.id}><V7Fact label={metric.label}>元信息，不作为数值指标</V7Fact><small>{metric.state} · 计量单位显示在对应指标说明中</small>{sourceButtons(metric.source_ids)}</div>;
    if(PERIOD_META_LABELS.has(metric.label))return <div key={metric.id}><V7Fact label={metric.label}>起止日期尚未提供，无法计算实际观察时长</V7Fact><small>{metric.state}</small>{sourceButtons(metric.source_ids)}</div>;
    const percent=unit==="%";
    const note=unitConflict?"当前服务为该指标返回的单位与指标类型不一致（"+unit+"），数值按未知处理，不参与汇总。":(percent?"百分比":unit||"单位未提供")+" · "+(metric.period??"期间未提供");
    return <div key={metric.id}>
      <V7Metric label={metric.label} value={unitConflict?"未知":metric.value===null?"未知":metric.value+(percent?"%":"")} note={note}/>
      <small>{metric.state}{metric.definition_version?" · 定义 "+metric.definition_version:""}</small>
      {percent&&metric.value!==null&&<p className="boss-helper">比例分子：未知 · 比例分母：未知。当前资料未提供分子与分母，比例不可复算。</p>}
      {metric.coverage&&<p className="boss-helper">覆盖：{metric.coverage}</p>}
      {metric.comparability&&<p className="boss-helper">{metric.comparability}</p>}
      {sourceButtons(metric.source_ids)}
    </div>;
  }
  function scrollTo(target:HTMLElement|null){target?.scrollIntoView({behavior:"smooth",block:"start"});target?.focus();}
  function perform(item:PageAction){
    if(item.chat){void discuss(CHAT_REQUESTS[pageId]??item.label);return;}
    const code=item.code;
    if(code==="查看明细"){scrollTo(recordsRef.current);return;}
    if(["打开原文","查看依据","打开关系证据","打开专业资料"].includes(code)){scrollTo(sourcesRef.current);return;}
    if(["查看专业反馈","查看专业复查"].includes(code)){scrollTo(professionalRef.current);return;}
    if(code==="查看选项"){scrollTo(optionsRef.current);return;}
    if(!item.kind)throw new Error("专题操作尚未定义："+code);
    const capability=current?.followup_actions?.find(row=>row.code===code);
    setAction(capability?{...capability,label:item.label}:{code,label:item.label,kind:item.kind,allowed:false,reason:"当前服务尚未提供本项操作的有效条件，请重新读取。"});
  }
  const metrics:SectorMetric[]=current?.metrics??design.fields.map(label=>({id:label,label,value:null,unit:null,period:null,source_ids:[],state:"待查询"}));
  return <div className="boss-sector-workspace">
    <BusinessOverviewReference reference={overviewReference}/>
    <V7ReadState loading={loading} error={error} onReload={reload}/>
    {variant&&<V7Tabs label="禽类与反刍用途" value={pageId} items={VARIANTS} onChange={navigate}/>}
    <form className="boss-panel boss-sector-filterbar" aria-label="专题查询范围" onSubmit={event=>{event.preventDefault();applyQuery();}}>
      {filters.map(label=><label key={label}>{label}{data?.filter_options[label]?.length?<select disabled={loading||sending} value={fields[label]??""} onChange={event=>setFields(old=>({...old,[label]:event.target.value}))}><option value="">请选择</option>{data.filter_options[label].map(option=><option key={option.id} value={option.id}>{option.label}</option>)}</select>:<input disabled={loading||sending} value={fields[label]??""} onChange={event=>setFields(old=>({...old,[label]:event.target.value}))} placeholder="填写查询范围"/>}</label>)}
      <button className="boss-btn boss-btn-primary" disabled={loading||followupDirty||sending}><Search size={16}/>{QUERY_LABELS[pageId]??"查询"}</button>
    </form>
    {queryDirty&&<p className="boss-status" role="status">当前筛选有尚未应用的修改；下方资料仍对应上次查询范围。</p>}
    <div className="boss-sector-columns"><div className="boss-column">
      {["F16","F20"].includes(pageId)?<V7Panel title="关系与来源核查"><div className="boss-v7-relation-grid">{(pageId==="F16"?["繁育","检验","交付","运输","接收","放养","回访"]:["事件与观察","observed_at","received_at","测量方法","当前措施","批次关系"]).map(label=>{const values=current?.relations.filter(row=>row.label===label)??[];return <article key={label} className="boss-workspace-item"><strong>{label}</strong>{values.length?values.map(value=><div key={value.id}><span className="boss-tag">{value.state}</span><p>{value.description}</p>{sourceButtons(value.source_ids)}</div>):<><span className="boss-tag">待核查</span><p>尚无可确认的关联证据</p></>}</article>;})}</div></V7Panel>:
      pageId==="F17"?<V7Panel title="流程步骤与执行条件">{current?.workflow.length?<><V7Steps steps={current.workflow}/>{current.workflow.map((step,index)=><article key={index} className="boss-sector-section"><strong>{step.title}</strong><p>{step.author?"专业作者："+step.author:"专业作者尚未提供"}{step.confirmed_at?" · 确认时间："+step.confirmed_at:""}</p>{sourceButtons(step.source_ids??[])}</article>)}</>:<div className="boss-sector-professional-stages">{["观察","采样检测","专业确认","执行反馈","复查"].map(title=><article key={title}><strong>{title}</strong><p>尚未读取专业资料与确认程度</p></article>)}</div>}</V7Panel>:
      pageId==="F23"?<V7Panel title="事实、观点与推断分层"><div className="boss-form-grid">{design.fields.map(section)}</div>{["FACT","OPINION","INFERENCE"].map(kind=><section className="boss-sector-claim-group" key={kind}><h3>{CLAIM_LABELS[kind as keyof typeof CLAIM_LABELS]}</h3>{current?.sections.some(row=>row.claim_kind===kind)?current.sections.filter(row=>row.claim_kind===kind).map((row:SectorSection)=><article key={row.title} className="boss-workspace-item"><strong>{row.title}</strong><p>{row.text??"资料正文尚未提供"}</p><small>{row.author??"作者尚未提供"} · {row.state}</small>{sourceButtons(row.source_ids)}</article>):<p>当前没有已读取的对应内容。</p>}</section>)}</V7Panel>:
      <V7Panel title="经营指标与趋势"><div className="boss-sector-stat-grid">{metrics.map(metricCard)}</div><Trend data={current?.trend??null} onSource={onViewSource}/><div className="boss-form-grid">{mainTitles.map(section)}</div></V7Panel>}
      <div ref={recordsRef} tabIndex={-1}><V7Panel title={pageId==="F17"?"责任与质量约束":pageId==="F23"?"查询范围与研究要求":["F16","F20"].includes(pageId)?"关联记录":"数据明细与资料覆盖"}>
        {(pageId==="F17"||pageId==="F23")&&<div className="boss-form-grid">{design.sections.map(section)}</div>}
        <div className="boss-v7-table-scroll"><table className="boss-v7-table"><thead><tr>{design.fields.map(label=><th key={label}>{label}</th>)}<th>版本与状态</th><th>资料来源</th></tr></thead><tbody>{rows.slice((currentPage-1)*10,currentPage*10).map(row=><tr key={row.id} aria-selected={selected===row.id}>{design.fields.map((label,index)=><td key={label}>{index===0?<><button className="boss-v7-text-button" title={"记录编号 "+row.id} onClick={()=>setSelected(row.id)}>{ROW_VIEW_LABELS[pageId]??"查看明细"}</button><BIRecordContent value={row.values[label]}/></>:<BIRecordContent value={row.values[label]}/>}</td>)}<td>{row.version} · {row.state}</td><td>{sourceButtons(row.source_ids)}</td></tr>)}</tbody></table></div>
        {!rows.length&&<V7Empty title="当前条件下尚无已读取记录">查询后显示符合范围的记录和来源。</V7Empty>}<V7Pagination page={currentPage} total={rows.length} pageSize={10} onChange={setPage}/>
      </V7Panel></div>
      {(pageId==="F22"||Boolean(current?.resource_options?.length))&&<div ref={optionsRef} tabIndex={-1}><V7Panel title="资源选项">{current?.resource_options?.length?current.resource_options.map(option=><article key={option.option_id} className="boss-workspace-item"><strong>{option.title}</strong><p>{option.description}</p><small>{option.option_id} / v{option.version} · {option.state}</small>{sourceButtons(option.source_ids)}</article>):<V7Empty title="当前没有已读取的资源选项">需要有效资料、适用范围及决定期限。</V7Empty>}</V7Panel></div>}
      {current?<div ref={actionRef} className="boss-v7-actionbar">{pageActions.map((item,index)=>{const capability=item.kind?current.followup_actions?.find(row=>row.code===item.code):undefined;return <button key={item.code} className={"boss-btn "+(index===0?"boss-btn-primary":"")} disabled={sending||followupDirty||(item.chat?queryDirty:Boolean(item.kind&&(queryDirty||!capability?.allowed)))} onClick={()=>perform(item)}>{item.label}</button>;})}</div>:<div ref={actionRef} className="boss-v7-actionbar"><p className="boss-helper">查询后显示当前范围可用的后续操作；未取得查询结果时不提供业务操作。</p></div>}
      {current&&pageActions.filter(item=>item.kind&&!current.followup_actions?.find(row=>row.code===item.code&&row.allowed)).map(item=><p className="boss-helper" key={item.code}>{item.label}：{current.followup_actions?.find(row=>row.code===item.code)?.reason||"当前服务尚未提供本项操作的有效条件，请重新读取。"}</p>)}
      <BossSectorFollowUp data={current} action={action} onAction={setAction} onDirtyChange={setFollowupDirty} onReload={reload} onNavigate={navigate} onOpenTask={onOpenTask} onViewSource={onViewSource}/>
    </div><aside ref={sourcesRef} tabIndex={-1} className="boss-column"><V7Panel title="来源与依据">{design.right.map(label=><V7Fact key={label} label={label}>{current?.coverage.find(row=>row.label===label)?.value??"待核查"}</V7Fact>)}{current?.sources.length?current.sources.map(source=><article className="boss-workspace-item" key={source.source_id+source.version}><strong>{source.source_id} · v{source.version}</strong><p>{source.related_scope}</p><small>{source.author_display_name??"作者尚未提供"} · {source.published_at} · {source.validity_state}</small>{source.observed_at&&<V7Fact label="观察时间">{source.observed_at}</V7Fact>}{source.received_at&&<V7Fact label="接收时间">{source.received_at}</V7Fact>}<button className="boss-btn" aria-label={"查看依据："+source.source_id} onClick={()=>onViewSource(source.source_id)}>查看依据</button></article>):<V7Empty title="尚未读取获准来源"/>}</V7Panel>
      <div ref={professionalRef} tabIndex={-1}><V7Panel title="状态与核查"><V7Fact label="资料覆盖">{current?.availability??"尚未读取"}</V7Fact><V7Fact label="资料版本">{current?.dataset_version??"尚未读取"}</V7Fact><V7Fact label="当前执行空间">{current?.namespace??"尚未读取"}</V7Fact><V7Fact label="读取时间">{current?.read_at??"尚未读取"}</V7Fact>{current?.missing_fields.length?<ul>{current.missing_fields.map(field=><li key={field}>{field}</li>)}</ul>:null}{professionalTitles.map(section)}</V7Panel></div>
      {record&&<V7Panel title="选中记录"><V7Fact label="记录编号">{record.id}</V7Fact><V7Fact label="版本与状态">{record.version} · {record.state}</V7Fact><BIRecordContent value={record.values}/>{sourceButtons(record.source_ids)}</V7Panel>}
    </aside></div>
  </div>;
}
