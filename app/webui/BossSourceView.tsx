import {useEffect,useRef,useState} from "react";
import * as Dialog from "@radix-ui/react-dialog";
import {useClient} from "@/providers/ClientProvider";
import {V7Empty,V7Fact,V7Panel,V7ReadState} from "./BossV7UI";
import {BIRecordContent} from "./BIRecordContent";
import pageMeta from "./page-meta.json";

export type SourceAnchor={source_id:string;version:string;start:number;end:number};
type Source={source_id:string;source_type:string;version:string;content?:string|null;title?:string;published_at?:string;observed_at?:string;received_at?:string;read_at?:string;
  author_contact_id?:string;author_display_name?:string;author_kind?:string;generator_version?:string;business_basis?:string;allowed_use?:string;valid_from?:string;valid_until?:string|null;
  original_locator?:unknown;coverage?:unknown;validity_state?:string;missing_fields?:string[];namespace?:string;dataset_version?:string;historical?:boolean;
  available_versions?:{version:string;readable:boolean;reason?:string}[];
  origin_context?:{kind:string;id:string;version:string;title?:string;scope?:Record<string,unknown>};
  assertions?:{claim_id:string;text:string;kind:"FACT"|"OPINION"|"INFERENCE";support_state:string;source_version:string;start?:number;end?:number;limitation?:string}[]};
type Props={sourceId:string;anchor:SourceAnchor|null;originPage:string;refreshVersion:number;onReturn:()=>void};
export function savedSourceAnchor(sourceId:string):SourceAnchor|null{
  const query=new URLSearchParams(window.location.search),version=query.get("bossSourceVersion"),start=query.get("bossSourceStart"),end=query.get("bossSourceEnd");
  if(version===null&&start===null&&end===null)return null;
  if(!version||start===null||end===null||!Number.isInteger(Number(start))||!Number.isInteger(Number(end))||Number(start)<0||Number(end)<=Number(start))throw new Error("来源引用位置或版本无效。");
  return {source_id:sourceId,version,start:Number(start),end:Number(end)};
}
export function BossSourceView(props:Props){const {token}=useClient();return <SourceView key={token+":"+props.sourceId} {...props}/>;}
function SourceView({sourceId,anchor:providedAnchor,originPage,refreshVersion,onReturn}:Props){
  const {getToken}=useClient();
  const [anchor]=useState(()=>providedAnchor??savedSourceAnchor(sourceId));
  const [referenceVersion]=useState(()=>providedAnchor?.version??new URLSearchParams(window.location.search).get("bossSourceReferenceVersion")??anchor?.version??null);
  const [version,setVersion]=useState(""),[revision,setRevision]=useState(0),[data,setData]=useState<Source|null>(null),[loading,setLoading]=useState(true),[error,setError]=useState("");
  const [fullOpen,setFullOpen]=useState(false),[versions,setVersions]=useState<NonNullable<Source["available_versions"]>>([]);
  const supportRef=useRef<HTMLElement|null>(null);
  const query=new URLSearchParams(window.location.search);
  const originRefs=[["经营查询",query.get("biRequest")],["关联任务",query.get("bossTask")],["原运行",query.get("bossRun")],["原事项",query.get("bossEvent")],["经营专题",query.get("overviewTopic")]].filter((item):item is [string,string]=>Boolean(item[1]));
  useEffect(()=>{
    const abort=new AbortController();setData(null);setError("");setLoading(true);setFullOpen(false);
    const params=new URLSearchParams({source:sourceId});if(version)params.set("version",version);
    void fetch("/api/boss/ui/evidence?"+params,{headers:{Authorization:"Bearer "+getToken()},cache:"no-store",signal:abort.signal}).then(async response=>{
      if(abort.signal.aborted)return null;
      if(response.status===401)window.dispatchEvent(new Event("boss-auth-expired"));
      if(!response.ok)throw new Error(response.status===403?"当前身份无法读取这项来源，正文不可用。":response.status===404?"当前来源或所选版本不存在。":response.status===409||response.status===410?"当前来源已变化、到期或撤销，请返回原事项核查。":"来源读取失败，HTTP "+response.status);
      const result=await response.json() as Source;
      if(result.source_id!==sourceId||!result.version||version&&result.version!==version)throw new Error("来源返回的编号或版本与本次请求不符。");
      if(!["SIMULATED","PUBLIC_SOURCE","RUNTIME_RECORD"].includes(result.source_type))throw new Error("来源属性尚未通过核查。");
      return result;
    }).then(result=>{if(abort.signal.aborted||!result)return;setData(result);if(result.available_versions)setVersions(result.available_versions);setLoading(false);}).catch(failure=>{if(abort.signal.aborted)return;setData(null);setLoading(false);setError(failure instanceof Error?failure.message:String(failure));});
    return()=>abort.abort();
  },[sourceId,version,revision,refreshVersion,getToken]);
  const restricted=Boolean(data?.validity_state&&["FORBIDDEN","WITHDRAWN","MISSING","MISSING_OR_FORBIDDEN"].includes(data.validity_state));
  const content=restricted?null:data?.content;
  const matching=Boolean(anchor&&data&&anchor.source_id===data.source_id&&anchor.version===data.version&&typeof content==="string"&&anchor.start>=0&&anchor.end<=content.length&&anchor.start<anchor.end);
  const text=typeof content==="string"?matching&&anchor?<>{content.slice(0,anchor.start)}<mark id="boss-source-citation" className="boss-source-highlight">{content.slice(anchor.start,anchor.end)}</mark>{content.slice(anchor.end)}</>:content:null;
  return <div className="boss-source-workspace"><V7ReadState loading={loading} error={error} onReload={()=>setRevision(value=>value+1)}/>
    <div className="boss-source-columns"><div className="boss-column"><V7Panel title="当前经营查询上下文"><V7Fact label="返回页面">{(pageMeta as Record<string,{title:string}>)[originPage]?.title??"原工作页面"}</V7Fact><V7Fact label="所引用来源">{sourceId}</V7Fact><V7Fact label="引用版本">{referenceVersion??"原入口未提供固定引用版本"}</V7Fact>{originRefs.map(([label,value])=><V7Fact key={label} label={label}>{value}</V7Fact>)}{data?.origin_context&&<><V7Fact label="原对象">{data.origin_context.title??data.origin_context.id} · {data.origin_context.kind} · 版本 {data.origin_context.version}</V7Fact>{data.origin_context.scope&&<BIRecordContent value={data.origin_context.scope}/>}</>}
      {!data?.origin_context&&<p className="boss-helper">完整查询条件与断言正文尚未由来源服务提供。返回原页面可继续核查原查询。</p>}
      <section ref={supportRef} tabIndex={-1} className="boss-source-support"><h3>断言支持关系</h3>{!restricted&&data?.assertions?.length?data.assertions.map(item=><article className="boss-feedback" key={item.claim_id}><span className="boss-tag">{{FACT:"事实",OPINION:"作者意见",INFERENCE:"模型推断"}[item.kind]}</span><p>{item.text}</p><V7Fact label="支持状态">{item.support_state}</V7Fact><V7Fact label="依据版本">{item.source_version}</V7Fact><V7Fact label="引用位置">{item.start!==undefined&&item.end!==undefined?item.start+" 至 "+item.end:"尚未提供"}</V7Fact>{item.limitation&&<p>{item.limitation}</p>}</article>):<V7Empty title="尚无可核查的断言支持关系">来源原文与结论支持范围需要分别核查；资料缺少时不生成支持结论。</V7Empty>}</section>
      <div className="boss-actions"><button type="button" className="boss-btn boss-btn-primary" onClick={onReturn}>关闭并返回原引用</button><button type="button" className="boss-btn" onClick={()=>supportRef.current?.focus()}>查看支持范围</button></div>
    </V7Panel></div><aside className="boss-column"><V7Panel title={data?.title??"来源原文"} description="当前获准来源与版本"><div className="boss-actions"><span className="boss-tag boss-tag-blue">{data?.source_type??"来源属性待读取"}</span>{version&&<span className="boss-tag">指定版本只读</span>}</div>
      <V7Fact label="来源名称">{data?.title??data?.source_id??sourceId}</V7Fact><V7Fact label="作者">{data?.author_display_name??data?.author_contact_id??"尚未提供"}</V7Fact><V7Fact label="发布日期">{data?.published_at??"尚未提供"}</V7Fact><V7Fact label="观察时间">{data?.observed_at??"尚未提供"}</V7Fact><V7Fact label="接收时间">{data?.received_at??"尚未提供"}</V7Fact><V7Fact label="版本">{data?.version??"等待读取"}</V7Fact><V7Fact label="有效期间">{data?.valid_from??"起始时间未提供"} 至 {data?.valid_until??"结束时间未提供"}</V7Fact><V7Fact label="允许用途">{data?.allowed_use??"尚未提供"}</V7Fact>
      {data?.coverage!==undefined&&<div><h3>适用范围</h3><BIRecordContent value={data.coverage}/></div>}{data?.original_locator!==undefined&&<div><h3>原文位置</h3><BIRecordContent value={data.original_locator}/></div>}
      {restricted&&<p className="boss-status boss-status-warn" role="status">来源状态 {data?.validity_state}，当前不显示正文。</p>}
      {data?.validity_state==="EXPIRED"&&<p className="boss-status boss-status-warn" role="status">来源已经到期。当前获准历史内容仅用于核查，不能直接作为当前结论依据。</p>}
      {anchor&&data&&!matching&&<p className="boss-status boss-status-warn" role="status">当前原文的版本或位置与原引用不同。原引用保持独立，可查询当时版本；新内容不会自动替代原证据。</p>}
      {!anchor&&referenceVersion&&data&&data.version!==referenceVersion&&<p className="boss-status boss-status-warn" role="status">当前版本与会话引用版本 {referenceVersion} 不同，可以查询当时版本核查原依据。</p>}
      {text!==null?<blockquote className="boss-source-text">{text}</blockquote>:<V7Empty title="原文尚不可读">来源未提供、读取失败或权限受限时，正文保持不可用。</V7Empty>}
      <div className="boss-actions"><button type="button" className="boss-btn boss-btn-primary" disabled={loading||text===null} onClick={()=>setFullOpen(true)}>查看完整原文</button><button type="button" className="boss-btn" disabled={loading||!referenceVersion} onClick={()=>{if(referenceVersion){setVersion(referenceVersion);setRevision(value=>value+1);}}}>查看当时版本</button><button type="button" className="boss-btn" disabled={loading} onClick={()=>{setVersion("");setRevision(value=>value+1);}}>与当前版本比较</button></div>
      {versions.length>0&&<label className="boss-source-version">其他获准版本<select value={version} disabled={loading} onChange={event=>setVersion(event.target.value)}><option value="">当前版本</option>{versions.map(item=><option key={item.version} value={item.version} disabled={!item.readable}>{item.version}{item.reason?" · "+item.reason:""}</option>)}</select></label>}
      <details><summary>来源缺口与技术记录</summary>{data?.missing_fields?.length?<ul>{data.missing_fields.map(item=><li key={item}>{item}</li>)}</ul>:<p>完整来源缺口尚未提供。</p>}<V7Fact label="业务口径">{data?.business_basis??"尚未提供"}</V7Fact><V7Fact label="作者类型">{data?.author_kind??"尚未提供"}</V7Fact><V7Fact label="生成器版本">{data?.generator_version??"尚未提供"}</V7Fact><V7Fact label="执行空间">{data?.namespace??"尚未提供"}</V7Fact><V7Fact label="资料版本">{data?.dataset_version??"尚未提供"}</V7Fact><V7Fact label="读取时间">{data?.read_at??"尚未提供"}</V7Fact></details>
    </V7Panel></aside></div>
    <Dialog.Root open={fullOpen&&text!==null} onOpenChange={setFullOpen}><Dialog.Portal><Dialog.Overlay className="boss-v7-dialog-overlay"/><Dialog.Content className="boss-v7-dialog boss-source-full"><Dialog.Title>{data?.title??sourceId} · 版本 {data?.version}</Dialog.Title><Dialog.Description>当前已读取的获准完整原文；关闭后返回原引用位置。</Dialog.Description><blockquote className="boss-source-text">{content}</blockquote><Dialog.Close asChild><button type="button" className="boss-btn">返回来源详情</button></Dialog.Close></Dialog.Content></Dialog.Portal></Dialog.Root>
  </div>;
}
