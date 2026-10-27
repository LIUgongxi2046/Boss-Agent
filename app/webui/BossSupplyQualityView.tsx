import {useEffect,useRef,useState,type FormEvent} from "react";
import {useClient} from "@/providers/ClientProvider";
import {BossSupplyQualityPanel,type SupplyQualityEditor,type SupplyQualityProjection,type SupplyQualityReceipt} from "./BossSupplyQualityPanel";
import {BusinessOverviewReference,readOverviewReference,verifyOverviewReference} from "./BusinessOverviewReference";
import type {OverviewSelection} from "./business-overview-types";

type Props={interfaceId:"SI09"|"SI10";onOpenSource:(sourceId:string)=>void;onOpenTask:(taskId:string)=>void;editor:SupplyQualityEditor;onEditorChange:(changes:Partial<SupplyQualityEditor>)=>void;refreshVersion?:number;onDirtyChange?:(dirty:boolean)=>void};
const SUPPLY_FIELDS=[["material_id","原料编号"],["product_ids","产品编号"],["legal_entity_id","法人编号"],["period_start","期间开始"],["period_end","期间结束"],["currency","币种"]] as const;
const QUALITY_FIELDS=[["complaint_id","客诉编号"],["input_batch_id","原料批次"],["output_batch_id","加工产出批次"],["trace_state","关系范围"]] as const;
const FIELD_LABELS:Record<string,string>=Object.fromEntries([...SUPPLY_FIELDS,...QUALITY_FIELDS].map(([key,label])=>[key,label] as const));
const QUERY_LABELS={SI09:"查询原料与成本",SI10:"查询品质追溯"} as const;
export function BossSupplyQualityView(props:Props){const {token}=useClient(),identity=useRef({token,version:0});if(identity.current.token!==token)identity.current={token,version:identity.current.version+1};return <SupplyQualityView key={identity.current.version} {...props}/>;}
function SupplyQualityView({interfaceId,onOpenSource,onOpenTask,editor,onEditorChange,refreshVersion,onDirtyChange}:Props){
  const {client,getToken}=useClient();
  const [overviewReference]=useState(()=>readOverviewReference(interfaceId==="SI09"?"F14":"F21"));
  const [fields,setFields]=useState<Record<string,string>>({}),[applied,setApplied]=useState<Record<string,string>>({});
  const [data,setData]=useState<SupplyQualityProjection|null>(null),[loading,setLoading]=useState(true),[error,setError]=useState(""),[revision,setRevision]=useState(0);
  const dirty=JSON.stringify(fields)!==JSON.stringify(applied),locked=Boolean(editor.pending||editor.pendingPreparation);
  const reload=()=>setRevision(value=>value+1);
  useEffect(()=>{onDirtyChange?.(dirty);return()=>onDirtyChange?.(false);},[dirty,onDirtyChange]);
  useEffect(()=>{
    const abort=new AbortController(),token=getToken();setData(null);setError("");setLoading(true);if(!token){setError("当前身份已失效");setLoading(false);return;}
    const query=new URLSearchParams({interface_id:interfaceId});if(Object.keys(applied).length)query.set("filters",JSON.stringify(applied));
    if(overviewReference)query.set("overview_reference",JSON.stringify(overviewReference));
    void fetch("/api/boss/ui/supply-quality?"+query,{headers:{Authorization:"Bearer "+token},cache:"no-store",signal:abort.signal}).then(async response=>{
      if(abort.signal.aborted)return null;if(response.status===401)window.dispatchEvent(new Event("boss-auth-expired"));if(!response.ok)throw new Error("业务资料查询失败（HTTP "+response.status+"），当前条件尚未取得计算结果");
      const value=await response.json() as SupplyQualityProjection&{overview_reference?:OverviewSelection};
      verifyOverviewReference(overviewReference,value.overview_reference);
      if(value.interface_id!==interfaceId||value.source_type!=="SIMULATED"||value.external_service_invoked!==false||value.purchase_executed!==false||value.quality_release_executed!==false)throw new Error("业务资料与当前页面范围不符");
      if(Object.keys(applied).length&&(!value.applied_filters||JSON.stringify(Object.entries(value.applied_filters).sort())!==JSON.stringify(Object.entries(applied).sort())))throw new Error("返回的计算范围与当前查询条件不符");return value;
    }).then(value=>{if(abort.signal.aborted||!value)return;setData(value);setLoading(false);}).catch(reason=>{if(abort.signal.aborted)return;setError(reason instanceof Error?reason.message:String(reason));setLoading(false);});return()=>abort.abort();
  },[interfaceId,getToken,revision,applied,refreshVersion,overviewReference]);
  function query(event:FormEvent){event.preventDefault();if(locked)return;if(Boolean(fields.period_start)!==Boolean(fields.period_end)||fields.period_start&&fields.period_end&&fields.period_start>fields.period_end){setError("期间需要完整起止日期，结束日期应晚于或等于开始日期");return;}setApplied(Object.fromEntries(Object.entries(fields).filter(([,value])=>value.trim()).map(([key,value])=>[key,value.trim()])));setFields(Object.fromEntries(Object.entries(fields).filter(([,value])=>value.trim()).map(([key,value])=>[key,value.trim()])));reload();}
  async function command(action:string,payload:Record<string,unknown>){return client.requestMutation<unknown>(action,payload);}
  async function receipt(action:string,key:string){const token=getToken();if(!token)throw new Error("当前身份已失效");const response=await fetch("/api/boss/ui/supply-quality-receipt?"+new URLSearchParams({action,client_request_id:key}),{headers:{Authorization:"Bearer "+token},cache:"no-store"});if(response.status===401)window.dispatchEvent(new Event("boss-auth-expired"));if(!response.ok)throw new Error("原请求回执读取失败（HTTP "+response.status+"）");return response.json() as Promise<SupplyQualityReceipt>;}
  return <div className="boss-supply-quality"><form className="boss-supply-filters" onSubmit={query}><fieldset disabled={locked||loading}>{(interfaceId==="SI09"?SUPPLY_FIELDS:QUALITY_FIELDS).map(([key,label])=><label key={key}>{label}{key==="trace_state"?<select value={fields[key]??""} onChange={event=>setFields(value=>({...value,[key]:event.target.value}))}><option value="">全部有权关系</option><option value="CONFIRMED">已确认范围</option><option value="POSSIBLE">可能关联</option><option value="MISSING">关系缺少</option><option value="CONFLICTED">存在冲突</option></select>:<input type={key.startsWith("period_")?"date":"text"} maxLength={128} value={fields[key]??""} onChange={event=>setFields(value=>({...value,[key]:event.target.value}))}/>}</label>)}<button type="submit" className="boss-btn boss-btn-primary">{QUERY_LABELS[interfaceId]}</button></fieldset></form>
    <BusinessOverviewReference reference={overviewReference}/>
    <p className="boss-helper">{Object.keys(applied).length?"当前采用范围："+Object.entries(applied).map(([key,value])=>(FIELD_LABELS[key]??key)+"="+value).join("；"):overviewReference?"采用经营关注原范围，尚未添加其他查询条件。":"当前读取全部有权导入资料。填写条件后，计算与明细共同按所选范围查询。"}{dirty&&"查询条件尚未应用。"}</p>
    <BossSupplyQualityPanel key={interfaceId} interfaceId={interfaceId} data={dirty?null:data} loading={loading} error={error} onReload={reload} onOpenSource={onOpenSource} onOpenTask={onOpenTask} onCommand={command} onReceipt={receipt} editor={editor} onEditorChange={onEditorChange}/>
  </div>;
}
