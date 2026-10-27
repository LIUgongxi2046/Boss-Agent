import {useEffect, useRef, useState, type ReactNode} from "react";
import * as Dialog from "@radix-ui/react-dialog";
import {CheckCircle2, FileCode2, RefreshCw, Save, ShieldCheck} from "lucide-react";
import {V7Empty,V7Fact,V7Panel,V7ReadState,V7Tabs} from "./BossV7UI";
import {useTechnicalWorkspace} from "./useTechnicalWorkspace";
import {BossBusinessAlertRules} from "./BossBusinessAlerts";

type Domain="access"|"tools"|"metrics";
type Scalar=string|number|boolean|string[]|null;
type Values=Record<string,Scalar>;
type Version={version:string;values:Values;content_sha256:string;state:string;created_at:string;validation?:{state:string;checks:{name:string;state:string;message:string}[]}};
type Item={id:string;title:string;current:Version|null;draft:Version|null;history:Version[];effective_version?:string;activation_state?:string};
type Projection={projection:Domain;private_body_available_here:false;items:Item[];options:Record<string,{id:string;label:string}[]>;
  uses:{id:string;object_id:string;version:string;run_id:string;state:string;at:string;details?:Record<string,unknown>}[];
  access:{owner_id:string;maintainer_id:string;owner_confirmation_state:string;business_authority_granted:false};
  namespace:string;read_at:string};
type Field={key:string;label:string;type?:"number"|"textarea"|"json"|"select"|"multiselect"|"checkbox"|"datetime-local";options?:string;required?:boolean;min?:number;max?:number;help?:string;readonly?:boolean;identity?:boolean};
type Section={title:string;description:string;fields:Field[];matrix?:boolean};
type Diff={label:string;before:string;after:string};
const SCOPE_PURPOSE:Record<string,string>={
  relationships:"联系人、会议与历史事项等关联对象",
  audit:"运行、调用与核查记录",
  knowledge:"资料来源、摄取与检索索引",
  models:"模型连接、验证结果与用量",
  datasets:"模拟数据版本、载入与重置",
  evaluation:"评测任务与结果",
  "simulation-events":"模拟事件、模拟回复与业务时钟",
  "local-system":"本机运行、启动与系统检查",
  tools:"工具定义、接口映射与启用版本",
  metrics:"指标定义、独立复算与提醒规则",
  scheduler:"技术调度计划与触发记录",
  prompts:"Prompt 版本与采用记录",
  skills:"SOP 方法与 Skills 版本",
  simulation:"模拟中心查询与人工接口检查",
  "memory-status":"记忆状态与确认记录",
};
const SIDE_EFFECT_LABEL:Record<string,string>={
  QUERY_RECORD:"只记录本次查询",AUDIT_ONLY:"只写入核查记录",TASK_WRITE:"写入交办任务",OUTBOX_WRITE:"写入待发送消息",
};
const PERMISSION_LABEL:Record<string,string>={
  BOSS_CURRENT_AUTHORIZATION:"需要老板本人当时的授权决定",BOSS_CURRENT_SCOPE:"按老板当前获准范围执行",
};
function editableValues(values:Values):Values{
  const result={...values};
  for(const key of ["valid_from","valid_until","effective_at"]){
    if(typeof result[key]==="string"&&result[key])result[key]=new Intl.DateTimeFormat("sv-SE",{timeZone:"Asia/Shanghai",year:"numeric",month:"2-digit",day:"2-digit",hour:"2-digit",minute:"2-digit",hourCycle:"h23"}).format(new Date(result[key] as string)).replace(" ","T");
  }
  return result;
}
function formValues(domain:Domain,values:Values|undefined):Values{
  const result=editableValues(values??{});
  if(domain==="access"){
    const permissions=Array.isArray(result.permissions)?result.permissions:[];
    result.permissions=permissions.includes("READ")?permissions:[...permissions,"READ"];
  }
  return result;
}
function instant(value:Scalar|undefined):Date|null{
  if(typeof value!=="string"||!value)return null;
  if(/[zZ]$|[+-]\d{2}:\d{2}$/.test(value))return new Date(value);
  return new Date((/^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}$/.test(value)?value+":00":value)+"+08:00");
}
function effectiveState(from:Scalar|undefined,until:Scalar|undefined):string{
  const start=instant(from),end=instant(until);
  if(!start||!end)return "尚未读取";
  const now=Date.now();
  if(now<start.getTime())return "尚未生效";
  return now>=end.getTime()?"已到期":"已生效";
}
const DEFINITIONS:Record<Domain,{title:string;sections:Section[]}>={
  access:{title:"技术访问配置",sections:[
    {title:"基本信息",description:"配置名称与维护身份；身份由当前登录的技术维护账号决定。",fields:[
      {key:"name",label:"配置名称",required:true},
      {key:"subject_id",label:"维护身份",type:"select",options:"maintainers",required:true,help:"只能选择当前管理员获准维护的身份；不能通过填写其他身份获得权限。"}]},
    {title:"访问范围与权限",description:"逐项选择资料范围，并决定整份配置是否包含写入；配置权限不授予老板业务确认权。",fields:[],matrix:true},
    {title:"生效范围",description:"使用 Asia/Shanghai 时区；结束时间需要晚于开始时间，过期配置不能启用。",fields:[
      {key:"valid_from",label:"开始时间（Asia/Shanghai）",type:"datetime-local",required:true},
      {key:"valid_until",label:"结束时间（Asia/Shanghai）",type:"datetime-local",required:true},
      {key:"change_note",label:"变更说明",type:"textarea",required:true,help:"变更说明必填，并随该版本保存。"}]}]},
  tools:{title:"工具定义与连接",sections:[
    {title:"基本定义",description:"工具名称保留英文标识，与所选业务接口一致。",fields:[
      {key:"name",label:"工具名称",readonly:true,required:true,help:"tool name 保持英文标识，与业务接口相同。"},
      {key:"description",label:"用途与调用条件",type:"textarea",required:true,help:"说明适用意图、前置条件和结果，不能只重复工具名称。"}]},
    {title:"参数与返回结构",description:"结构由正式 Schema 校验；默认显示字段列表，完整 JSON 在折叠区编辑。",fields:[
      {key:"input_schema",label:"输入 Schema",type:"json",required:true,help:"根引用需要保留当前业务接口的输入定义。"},
      {key:"output_schema",label:"输出 Schema",type:"json",required:true,help:"根引用需要保留当前业务接口的输出定义。"},
      {key:"error_schema",label:"错误响应 Schema",type:"json",required:true}]},
    {title:"执行规则",description:"业务接口、连接引用、副作用、调用身份与幂等字段由所选接口决定；写入工具执行时需要老板本人当时的授权决定。",fields:[
      {key:"operation_id",label:"业务接口",type:"select",options:"operations",required:true,identity:true},
      {key:"connection_id",label:"服务端连接引用",type:"select",options:"connections",required:true,readonly:true},
      {key:"side_effect",label:"副作用",type:"select",options:"side_effects",required:true,readonly:true},
      {key:"permission",label:"调用身份与授权规则",type:"select",options:"tool_permissions",required:true,readonly:true},
      {key:"timeout_seconds",label:"超时（秒）",type:"number",min:1,max:300,required:true},
      {key:"idempotency_field",label:"幂等字段",required:true,readonly:true},
      {key:"change_note",label:"变更说明",type:"textarea",required:true}]}]},
  metrics:{title:"指标定义与计算",sections:[
    {title:"指标定义",description:"公式和单位由当前指标的业务定义决定；统计范围与维度决定参与计算的明细。",fields:[
      {key:"name",label:"指标名称",required:true},
      {key:"metric_id",label:"指标标识",type:"select",options:"metric_ids",required:true,identity:true},
      {key:"formula",label:"计算公式",type:"select",options:"formulas",required:true,readonly:true},
      {key:"unit",label:"单位",type:"select",options:"units",required:true,readonly:true},
      {key:"dimensions",label:"维度",type:"multiselect",options:"dimensions",required:true,help:"当前服务把维度作为整体选择，需要至少保留一项；必须维度与可选维度尚未由服务区分。"},
      {key:"scope",label:"统计范围",type:"select",options:"metric_scopes",required:true},
      {key:"precision",label:"显示精度",type:"number",min:0,max:8,required:true},
      {key:"refresh_seconds",label:"刷新间隔（秒）",type:"number",min:1,max:86400,required:true,help:"再次查询时，达到刷新间隔或明细版本改变即重新计算。"}]},
    {title:"版本生效",description:"使用 Asia/Shanghai 时区；换版保留历史计算依据。",fields:[
      {key:"effective_at",label:"生效时间（Asia/Shanghai）",type:"datetime-local",required:true},
      {key:"change_note",label:"变更说明",type:"textarea",required:true}]}]},
};
const FIELDS=(()=>{
  const all={} as Record<Domain,Record<string,Field>>;
  const labels={} as Record<Domain,Record<string,string>>;
  for(const domain of Object.keys(DEFINITIONS) as Domain[]){
    const fields:Record<string,Field>={};const names:Record<string,string>={};
    for(const section of DEFINITIONS[domain].sections)for(const field of section.fields){fields[field.key]=field;names[field.key]=field.label;}
    names.object_scopes="资料范围";names.permissions="技术权限";all[domain]=fields;labels[domain]=names;
  }
  return {fields:all,labels};
})();
type JsonSummary={state:"invalid";message:string}|{state:"valid";root:string;digest:string;fields:{name:string;type:string;detail:string;required:boolean}[]};
function resolveLocal(document:Record<string,unknown>,reference:string):Record<string,unknown>|null{
  if(!reference.startsWith("#/"))return null;
  let current:unknown=document;
  for(const key of reference.slice(2).split("/")){
    if(current===null||typeof current!=="object")return null;
    current=(current as Record<string,unknown>)[key];
  }
  return current!==null&&typeof current==="object"?current as Record<string,unknown>:null;
}
function schemaType(node:Record<string,unknown>):string{
  if(typeof node.$ref==="string")return "引用 "+node.$ref.replace("#/$defs/","");
  if(Array.isArray(node.enum))return "枚举";
  const type=node.type;
  if(Array.isArray(type))return type.map(String).join("／");
  if(typeof type==="string")return type;
  return "未声明类型";
}
function schemaDetail(node:Record<string,unknown>):string{
  if(Array.isArray(node.enum))return node.enum.map(String).join("、");
  if(node.const!==undefined)return "固定值 "+String(node.const);
  if(typeof node.pattern==="string")return "格式 "+node.pattern;
  if(typeof node.format==="string")return "格式 "+node.format;
  if(String(node.type)==="array"&&typeof node.maxItems==="number")return "最多 "+String(node.maxItems)+" 项";
  return "";
}
function schemaSummary(text:string):JsonSummary{
  let document:unknown;
  try{document=JSON.parse(text)}catch(failure){return {state:"invalid",message:failure instanceof Error?failure.message:"JSON 格式无效"};}
  if(document===null||typeof document!=="object"||Array.isArray(document))return {state:"invalid",message:"Schema 需要是 JSON 对象"};
  const root=document as Record<string,unknown>;
  const reference=typeof root.$ref==="string"?root.$ref:"";
  const resolved=reference?resolveLocal(root,reference):root;
  if(resolved===null)return {state:"invalid",message:"根引用 "+reference+" 不在当前定义中"};
  const properties=resolved.properties!==null&&typeof resolved.properties==="object"?resolved.properties as Record<string,Record<string,unknown>>:{};
  const required=Array.isArray(resolved.required)?resolved.required.filter((item):item is string=>typeof item==="string"):[];
  const fields=Object.entries(properties).map(([name,node])=>({name,type:schemaType(node),detail:schemaDetail(node),required:required.includes(name)}));
  return {state:"valid",root:reference,digest:(reference||"没有根引用")+"；字段 "+(fields.map(row=>row.name+(row.required?"（必要）":"")).join("、")||"无"),fields};
}
function valueText(domain:Domain,key:string,value:Scalar|undefined,options:Projection["options"]):string{
  if(value===undefined||value===null||value==="")return "未设置";
  if(["input_schema","output_schema","error_schema"].includes(key)){
    const summary=schemaSummary(String(value));
    return summary.state==="valid"?summary.digest:"无法解析的 Schema";
  }
  const field=FIELDS.fields[domain][key];
  const lookup=(id:string)=>options[field?.options??""]?.find(item=>item.id===id)?.label??id;
  if(Array.isArray(value))return value.length?value.map(lookup).join("、"):"未选择";
  if(key==="side_effect")return value+" · "+(SIDE_EFFECT_LABEL[String(value)]??"尚未提供说明");
  if(key==="permission")return value+" · "+(PERMISSION_LABEL[String(value)]??"尚未提供说明");
  if(field?.type==="select")return lookup(String(value));
  return String(value);
}
function diffRows(domain:Domain,beforeValues:Values,afterValues:Values,options:Projection["options"]):Diff[]{
  const rows:Diff[]=[];
  if(domain==="access"){
    const beforeScopes=Array.isArray(beforeValues.object_scopes)?beforeValues.object_scopes:[];
    const afterScopes=Array.isArray(afterValues.object_scopes)?afterValues.object_scopes:[];
    const added=afterScopes.filter(id=>!beforeScopes.includes(id));
    const removed=beforeScopes.filter(id=>!afterScopes.includes(id));
    if(added.length)rows.push({label:"新增资料范围",before:"未包含",after:added.join("、")});
    if(removed.length)rows.push({label:"移除资料范围",before:removed.join("、"),after:"未包含"});
    const beforePermissions=Array.isArray(beforeValues.permissions)?beforeValues.permissions:[];
    const afterPermissions=Array.isArray(afterValues.permissions)?afterValues.permissions:[];
    if(beforePermissions.join("、")!==afterPermissions.join("、"))
      rows.push({label:"技术权限",before:beforePermissions.join("、")||"未设置",after:afterPermissions.join("、")||"未设置"});
  }
  for(const key of [...new Set([...Object.keys(beforeValues),...Object.keys(afterValues)])]){
    if(["object_scopes","permissions"].includes(key))continue;
    if(JSON.stringify(beforeValues[key]??null)===JSON.stringify(afterValues[key]??null))continue;
    rows.push({label:FIELDS.labels[domain][key]??key,before:valueText(domain,key,beforeValues[key],options),after:valueText(domain,key,afterValues[key],options)});
  }
  return rows;
}
function itemState(row:Item):string{
  if(row.draft)return `草稿 v${row.draft.version}`;
  if(row.current)return row.current.state==="BUILTIN"?"内置定义":"已启用 v"+row.current.version;
  return "尚未保存";
}
function itemStatus(row:Item|null):string{
  if(!row)return "尚未保存";
  const state=row.draft?.state==="DRAFT"?"待校验":row.draft?.state==="VALIDATED"?"已校验":row.draft?.state==="ACTIVE"?"已启用":"已停止";
  const draft=row.draft?`草稿 v${row.draft.version}（${state}）`:"没有草稿";
  const current=row.current?(row.current.state==="BUILTIN"?"当前业务定义":`已启用 v${row.current.version}`):"尚未启用";
  return draft+" · "+current;
}
function DiffList({rows}:{rows:Diff[]}){
  if(!rows.length)return <p className="boss-helper">没有字段或范围变化。</p>;
  return <div>{rows.map(row=><p key={row.label} className="boss-helper"><strong>{row.label}</strong>：{row.before} → {row.after}</p>)}</div>;
}
function JsonField({field,value,onChange}:{field:Field;value:Scalar|undefined;onChange:(value:Scalar)=>void}){
  const [expanded,setExpanded]=useState(false);
  const summary=schemaSummary(String(value??""));
  return <div className="boss-field boss-v7-full-field">
    <span>{field.label}{field.required&&" *"}</span>
    {summary.state==="invalid"
      ?<p role="alert" className="boss-status boss-status-error">JSON 无法解析：{summary.message}</p>
      :<>
        <p className="boss-helper">根引用：{summary.root||"没有根引用"}；共 {summary.fields.length} 个字段。</p>
        <div>{summary.fields.map(row=><p key={row.name}>{row.name}{row.required?"（必要）":""} · {row.type}{row.detail?" · "+row.detail:""}</p>)}</div>
      </>}
    <button type="button" className="boss-btn" aria-expanded={expanded} onClick={()=>setExpanded(!expanded)}>{expanded?"收起完整 JSON":"编辑完整 JSON"}</button>
    {(expanded||summary.state==="invalid")&&<textarea id={"technical-"+field.key} aria-label={field.label+" 完整 JSON"} className="boss-v7-code" rows={10} spellCheck={false} value={String(value??"")} onChange={event=>onChange(event.target.value)}/>}
    {field.help&&<small>{field.help}</small>}
  </div>;
}
function PermissionMatrix({options,scopes,permissions,onChange}:{options:Projection["options"];scopes:string[];permissions:string[];onChange:(next:{scopes:string[];permissions:string[]})=>void}){
  const read=permissions.includes("READ"),write=permissions.includes("WRITE");
  return <>
    <div className="boss-v7-table-scroll"><table className="boss-v7-table" aria-label="资料范围与读取写入权限">
      <thead><tr><th scope="col">资料范围</th><th scope="col">用途</th>
        <th scope="col"><label className="boss-confirm-check"><input type="checkbox" checked={read} disabled readOnly/>读取</label></th>
        <th scope="col"><label className="boss-confirm-check"><input type="checkbox" checked={write} onChange={()=>onChange({scopes,permissions:write?permissions.filter(item=>item!=="WRITE"):[...permissions.filter(item=>item!=="WRITE"),"WRITE"]})}/>写入</label></th></tr></thead>
      <tbody>{(options.object_scopes??[]).map(row=>{
        const included=scopes.includes(row.id);
        return <tr key={row.id} aria-selected={included}>
          <td><label className="boss-confirm-check"><input type="checkbox" checked={included} onChange={()=>onChange({scopes:included?scopes.filter(item=>item!==row.id):[...scopes,row.id],permissions})}/>{row.id}</label></td>
          <td>{SCOPE_PURPOSE[row.id]??"当前版本尚未提供用途说明"}</td>
          <td>{included&&read?<span className="boss-tag boss-tag-green">可读取</span>:<span className="boss-tag boss-tag-muted">范围未选</span>}</td>
          <td>{included?write?<span className="boss-tag boss-tag-green">可写入</span>:<span className="boss-tag boss-tag-muted">只读</span>:<span className="boss-tag boss-tag-muted">范围未选</span>}</td>
        </tr>;
      })}</tbody>
    </table></div>
    <p className="boss-helper">读取为必选权限：技术访问至少要保留所选资料范围的读取权限，不能取消。写入权限按整份配置统一授予全部所选资料范围，服务当前不保存逐范围的写入权限。各资料范围影响的接口与字段尚未由服务返回，需要按实际页面与工具核对。</p>
    <p className="boss-helper">写入包含配置保存、校验与启用，以及资料摄取、修订和关联对象保存；配置权限不授予老板本人的业务确认权。</p>
  </>;
}
function EditorField({field,value,options,onChange,locked}:{field:Field;value:Scalar|undefined;options:Projection["options"];onChange:(value:Scalar)=>void;locked:boolean}){
  const id="technical-"+field.key;
  const choices=options[field.options||""]||[];
  const current=String(value??"");
  if(field.readonly||(field.identity&&locked)){
    const explanation=SIDE_EFFECT_LABEL[current]??PERMISSION_LABEL[current];
    const shown=explanation?current+" · "+explanation:field.type==="select"?choices.find(item=>item.id===current)?.label??current:current;
    return <div className="boss-field"><span>{field.label}（只读）</span><p>{shown||"尚未读取"}</p>
      {field.identity&&<small>标识与当前对象一致；切换对象请使用上方选择。</small>}{field.help&&<small>{field.help}</small>}</div>;
  }
  if(field.type==="multiselect")return <fieldset className="boss-v7-check-list"><legend>{field.label}</legend>{choices.map(item=><label key={item.id}><input type="checkbox" checked={Array.isArray(value)&&value.includes(item.id)} onChange={event=>onChange(event.target.checked?[...(Array.isArray(value)?value:[]),item.id]:(Array.isArray(value)?value:[]).filter(id=>id!==item.id))}/>{item.label}</label>)}{!choices.length&&<p>当前没有可选范围</p>}{field.help&&<p className="boss-helper">{field.help}</p>}</fieldset>;
  if(field.type==="json")return <JsonField field={field} value={value} onChange={onChange}/>;
  return <label className={"boss-field "+(["textarea","json"].includes(field.type||"")?"boss-v7-full-field":"")} htmlFor={id}><span>{field.label}{field.required&&" *"}</span>
    {field.type==="select"?<select id={id} required={field.required} value={current} onChange={event=>onChange(event.target.value)}><option value="">请选择</option>{choices.map(item=><option key={item.id} value={item.id}>{item.label}</option>)}</select>:
      field.type==="textarea"?<textarea id={id} rows={3} required={field.required} value={current} onChange={event=>onChange(event.target.value)}/>:
      <input id={id} type={field.type||"text"} required={field.required} min={field.min} max={field.max} value={typeof value==="string"||typeof value==="number"?value:""} onChange={event=>onChange(field.type==="number"&&event.target.value!==""?event.target.valueAsNumber:event.target.value)}/>}
    {field.help&&<small>{field.help}</small>}
  </label>;
}

export function MaintainerMetricsConfiguration({onDirtyChange,onNavigate}:{onDirtyChange:(dirty:boolean)=>void;onNavigate:(page:string)=>void}){
  const [metricsDirty,setMetricsDirty]=useState(false),[rulesDirty,setRulesDirty]=useState(false);
  useEffect(()=>onDirtyChange(metricsDirty||rulesDirty),[metricsDirty,rulesDirty,onDirtyChange]);
  return <MaintainerConfiguration domain="metrics" onDirtyChange={setMetricsDirty} onNavigate={onNavigate} relatedContent={<BossBusinessAlertRules role="MAINTAINER" title="经营提醒规则" onDirtyChange={setRulesDirty}/>}/>;
}

export function MaintainerConfiguration({domain,onDirtyChange,onNavigate,relatedContent}:{domain:Domain;onDirtyChange:(dirty:boolean)=>void;onNavigate:(page:string)=>void;relatedContent?:ReactNode}){
  const api=useTechnicalWorkspace<Projection>(domain);
  const [selected,setSelected]=useState("");
  const [values,setValues]=useState<Values>({});
  const [dirty,setDirty]=useState(false);
  const [tab,setTab]=useState<"edit"|"history"|"uses">("edit");
  const [confirm,setConfirm]=useState(false);
  const [query,setQuery]=useState("");
  const [localError,setLocalError]=useState("");
  const editVersion=useRef("0");
  const selectedExplicitly=useRef(false);
  const usesRef=useRef<HTMLDivElement>(null);
  const editorRef=useRef<HTMLFormElement>(null);
  const definition=DEFINITIONS[domain];
  const selectorLabel=domain==="access"?"配置选择":domain==="tools"?"工具目录":"指标配置";
  const refreshLabel=domain==="access"?"刷新此配置":domain==="tools"?"刷新工具目录":"刷新指标配置";
  const saveLabel=domain==="tools"?"保存工具草稿":domain==="metrics"?"保存指标草稿":"保存草稿";
  const item=api.data?.items.find(row=>row.id===selected)??null;
  useEffect(()=>{
    if(!api.data||dirty)return;
    const current=api.data.items.find(row=>row.id===selected)??(selectedExplicitly.current?undefined:api.data.items[0]);
    setSelected(current?.id??"");setValues(formValues(domain,current?.draft?.values??current?.current?.values));editVersion.current=current?.draft?.version??"0";
  },[api.data,dirty]);
  const unavailable=api.loading||api.busy||!!api.pending;
  const uses=(api.data?.uses.filter(row=>row.object_id===selected)??[]).sort((left,right)=>left.at.localeCompare(right.at));
  const checks=item?.draft?.validation?.checks??[];
  const versionPayload={object_id:selected,expected_version:item?.draft?.version,expected_content_sha256:item?.draft?.content_sha256,expected_active_version:item?.current?.version??"0"};
  const validated=Boolean(item?.draft&&item.draft.state==="VALIDATED"&&item.draft.validation?.state==="PASSED");
  const expired=Boolean(domain==="access"&&typeof values.valid_until==="string"&&values.valid_until&&(instant(values.valid_until)?.getTime()??0)<=Date.now());
  const activationBlocker=unavailable?"正在读取服务状态或等待回执":dirty?"存在未保存编辑":item?.draft?.state==="ACTIVE"?"当前草稿版本已经启用":!item?.draft?"尚未保存草稿":!validated?`草稿 v${item.draft.version} 尚未通过校验`:expired?"访问配置已经到期，不能启用":"";
  const options=api.data?.options??{};
  const diff=item?.draft?diffRows(domain,item.current?.values??{},item.draft.values,options):[];
  function choose(id:string){
    if(dirty||api.pending)return;
    selectedExplicitly.current=true;
    const current=api.data?.items.find(row=>row.id===id)??null;
    setSelected(id);setValues(formValues(domain,current?.draft?.values??current?.current?.values));editVersion.current=current?.draft?.version??"0";setLocalError("");
  }
  function definitionValues(id:string):Values{
    const row=api.data?.items.find(entry=>entry.id===id);
    return row?.current?.values??row?.draft?.values??{};
  }
  function edit(key:string,value:Scalar){
    if((domain==="tools"&&key==="operation_id")||(domain==="metrics"&&key==="metric_id")){
      if(item)return;
      const base=definitionValues(String(value));
      setValues({...formValues(domain,base),[key]:value,name:base.name??String(value)});
    }else setValues(current=>({...current,[key]:value}));
    setDirty(true);onDirtyChange(true);setLocalError("");
  }
  function editMatrix(next:{scopes:string[];permissions:string[]}){
    setValues(current=>({...current,object_scopes:next.scopes,permissions:next.permissions}));
    setDirty(true);onDirtyChange(true);setLocalError("");
  }
  function schemaProblem(key:"input_schema"|"output_schema"|"error_schema"):string{
    const label=key==="input_schema"?"输入 Schema":key==="output_schema"?"输出 Schema":"错误响应 Schema";
    const summary=schemaSummary(String(values[key]??""));
    if(summary.state==="invalid")return label+" 无法解析："+summary.message;
    if(key==="error_schema")return "";
    const base=schemaSummary(String(definitionValues(String(values.operation_id??""))[key]??""));
    if(base.state==="valid"&&base.root&&summary.root!==base.root)return label+" 需要保留当前业务接口的根引用 "+base.root;
    return "";
  }
  function save(){
    if(unavailable)return;
    setLocalError("");
    for(const section of definition.sections)for(const field of section.fields){
      const value=values[field.key];
      if(field.required&&(value===undefined||value===""||Array.isArray(value)&&!value.length)){setLocalError("请填写"+field.label);return;}
    }
    if(domain==="access"){
      if(!Array.isArray(values.object_scopes)||!values.object_scopes.length){setLocalError("请选择至少一个资料范围");return;}
      if(!Array.isArray(values.permissions)||!values.permissions.includes("READ")){setLocalError("技术访问必须包含读取权限");return;}
      const from=instant(values.valid_from),until=instant(values.valid_until);
      if(from&&until&&from.getTime()>=until.getTime()){setLocalError("结束时间需要晚于开始时间");return;}
    }
    if(domain==="tools"){
      if(String(values.name??"")!==String(values.operation_id??"")){setLocalError("工具名称需要与所选业务接口一致");return;}
      if(String(values.description??"").trim()===String(values.name??"")){setLocalError("用途与调用条件不能只重复工具名称");return;}
      for(const key of ["input_schema","output_schema","error_schema"] as const){
        const problem=schemaProblem(key);
        if(problem){setLocalError(problem);return;}
      }
    }
    const submitted={...values};
    for(const section of definition.sections)for(const field of section.fields)if(field.type==="datetime-local"&&submitted[field.key])submitted[field.key]=instant(submitted[field.key])?.toISOString()??"";
    void api.execute("save",{object_id:selected||null,expected_version:editVersion.current,values:submitted}).then(saved=>{if(saved){selectedExplicitly.current=true;setSelected(domain==="access"?"maintainer-access":String(submitted[domain==="metrics"?"metric_id":"operation_id"]));setDirty(false);onDirtyChange(false);}});
  }
  function showUses(){setTab("uses");requestAnimationFrame(()=>{usesRef.current?.scrollIntoView({block:"start",behavior:"smooth"});usesRef.current?.focus({preventScroll:true});});}
  function showEditor(){setTab("edit");requestAnimationFrame(()=>{editorRef.current?.scrollIntoView({block:"start",behavior:"smooth"});editorRef.current?.focus({preventScroll:true});});}
  function hint(){
    if(unavailable)return "正在读取服务状态或等待回执，操作暂不可用。";
    if(dirty)return "存在未保存编辑：保存草稿后才能校验或启用；放弃本次编辑可恢复已保存版本。";
    if(!item?.draft)return "尚未保存草稿：保存后产生新版本，不影响当前启用范围。";
    if(item.draft.state==="ACTIVE")return "当前草稿版本已经启用；修改后保存会产生新版本，历史运行保留原采用版本。";
    if(!validated)return `草稿 v${item.draft.version} 尚未通过校验：校验结果绑定草稿内容，校验通过后才能启用。`;
    if(expired)return "访问配置已经到期：不能启用，请修改结束时间后重新保存并校验。";
    return "校验结果绑定草稿内容；修改并保存后需要重新校验。启用不会扩大老板的业务权限。";
  }
  const validation=<>{checks.map(check=><div key={check.name} className="boss-workspace-item"><strong>{check.name} · {check.state}</strong><p className="boss-config-check-message">{check.message}</p></div>)}{!checks.length&&<p className="boss-helper">当前版本尚无已保存的校验结果。</p>}</>;
  return <div className={"boss-v7-configuration boss-config-"+domain}>
    <V7ReadState loading={api.loading} error={api.error||localError} onReload={api.reload}/>
    {api.pending&&<div className="boss-status boss-status-warn" role="status">请求 {api.pending.request_id} 等待核查。<button className="boss-btn" disabled={api.busy} onClick={()=>void api.reconcile()}>核查原请求</button></div>}
    {api.receipt&&<div className="boss-status boss-status-ok" role="status"><CheckCircle2 size={17}/>操作已记录 · {api.receipt.request_id}</div>}
    <div className="boss-config-toolbar" aria-label={definition.title}>
      <div className="boss-v7-filter-bar"><label>查找配置<input type="search" value={query} onChange={event=>setQuery(event.target.value)} placeholder="名称或标识"/></label><label>{selectorLabel}<select disabled={dirty||unavailable} value={selected} onChange={event=>choose(event.target.value)}><option value="">新建配置</option>{api.data?.items.filter(row=>row.id===selected||(row.title+row.id).toLowerCase().includes(query.toLowerCase())).map(row=><option key={row.id} value={row.id}>{domain==="tools"?row.id+" · "+itemState(row):row.title+" · "+row.id+" · "+itemState(row)}</option>)}</select></label></div>
      <button className="boss-btn" disabled={unavailable} onClick={api.reload}><RefreshCw size={16} className={api.loading?"boss-spin":""}/>{api.loading?"刷新中…":refreshLabel}</button>
      <V7Tabs label="配置视图" value={tab} onChange={setTab} items={[{id:"edit",title:"编辑配置"},{id:"history",title:"版本记录"},{id:"uses",title:"实际采用"}]}/>
    </div>
    <p className="boss-helper">{item?`${selectorLabel}：${domain==="tools"?item.id:item.title+" · "+item.id} · ${itemStatus(item)}。`:"当前为新建配置：保存后才产生独立草稿版本。"}{dirty?"存在未保存编辑：切换对象前需要保存或放弃本次编辑；刷新只读取服务版本，不覆盖当前编辑。":""}</p>
    <div className={domain==="access"?"boss-config-access-columns":"boss-columns"}><div className="boss-column">
      {tab==="edit"&&<form ref={editorRef} tabIndex={-1} onSubmit={event=>{event.preventDefault();save();}}>
        <fieldset className="boss-v7-form-fieldset" disabled={unavailable||!api.data}>
          {definition.sections.map(section=><V7Panel key={section.title} title={section.title} description={section.description}>
            {section.matrix
              ?<PermissionMatrix options={options} scopes={Array.isArray(values.object_scopes)?values.object_scopes:[]} permissions={Array.isArray(values.permissions)?values.permissions:[]} onChange={editMatrix}/>
              :<div className="boss-form-grid">{section.fields.map(field=><EditorField key={field.key} field={field} value={values[field.key]} options={options} locked={Boolean(item)} onChange={value=>edit(field.key,value)}/>)}</div>}
          </V7Panel>)}
          <div className="boss-actions">
            <button className="boss-btn" type="submit" disabled={!dirty||unavailable}><Save size={16}/>{saveLabel}</button>
            <button className="boss-btn" type="button" disabled={dirty||!item?.draft||item.draft.state!=="DRAFT"||unavailable} onClick={()=>void api.execute("validate",versionPayload)}><FileCode2 size={16}/>{domain==="access"?(item?.draft?`校验草稿版本 v${item.draft.version}`:"校验草稿版本"):domain==="metrics"?"校验公式":"校验工具定义"}</button>
            <button className="boss-btn boss-btn-primary" type="button" disabled={Boolean(activationBlocker)} onClick={()=>setConfirm(true)}><ShieldCheck size={16}/>{domain==="access"?"启用此版本":domain==="tools"?"启用此工具版本":"启用版本"}</button>
            {dirty&&<button className="boss-btn" type="button" disabled={unavailable} onClick={()=>{setValues(formValues(domain,item?.draft?.values??item?.current?.values));setDirty(false);onDirtyChange(false);setLocalError("");}}>放弃本次编辑</button>}
          </div>
          <p className="boss-helper">{hint()}</p>
        </fieldset>
      </form>}
      {relatedContent}
      {tab==="history"&&<V7Panel title="配置版本记录">{item?.history.length?<div className="boss-v7-table-scroll"><table className="boss-v7-table"><thead><tr><th>版本</th><th>状态</th><th>时间</th><th>变更说明与差异</th></tr></thead><tbody>{item.history.map(row=><tr key={row.version}><td>{row.version}</td><td>{row.state}</td><td>{row.created_at}</td><td>{row.values.change_note}{item.current&&<details><summary>查看与当前启用版本的差异</summary><DiffList rows={diffRows(domain,row.values,item.current.values,options)}/></details>}</td></tr>)}</tbody></table></div>:<V7Empty title="尚无历史版本"/>}</V7Panel>}
      {tab==="uses"&&<div ref={usesRef} tabIndex={-1}><V7Panel title="实际采用记录">{uses.length?<div className="boss-v7-table-scroll"><table className="boss-v7-table"><thead><tr><th>运行</th><th>采用版本</th><th>结果</th><th>时间</th></tr></thead><tbody>{uses.map(row=><tr key={row.id}><td>{row.run_id}</td><td>{row.version}</td><td>{row.state}{row.details&&<details><summary>计算与维度依据</summary><pre className="boss-v7-code">{JSON.stringify(row.details,null,2)}</pre></details>}</td><td>{row.at}</td></tr>)}</tbody></table></div>:<V7Empty title="尚无该配置的实际采用记录">启用版本后，后续请求的采用情况在此显示。</V7Empty>}</V7Panel></div>}
    </div><aside className="boss-column">
      <V7Panel title={domain==="tools"?"验证和实际调用":domain==="metrics"?"公式验证":"来源与依据"}>
        <V7Fact label="草稿版本">{dirty?`存在未保存编辑${item?.draft?`（基于 v${item.draft.version}）`:""}`:item?.draft?"v"+item.draft.version:"尚未保存"}</V7Fact>
        <V7Fact label="校验状态">{item?.draft?.validation?.state??"尚未校验"}</V7Fact>
        <V7Fact label="启用版本">{item?.current?"v"+item.current.version:"尚未启用"}</V7Fact>
        {domain==="metrics"&&<><V7Fact label="当前输入范围">{values.scope?options.metric_scopes?.find(choice=>choice.id===String(values.scope))?.label??String(values.scope):"尚未选择"}</V7Fact><V7Fact label="公式版本">{item?.effective_version??"尚未读取"}</V7Fact><V7Fact label="生效状态">{item?.activation_state==="SCHEDULED"?"等待生效时间":item?.activation_state==="EFFECTIVE"?"已生效":item?.activation_state==="BUILTIN"?"当前业务定义":"尚未读取"}</V7Fact></>}
        {validation}
        {domain==="metrics"&&<><button className="boss-btn boss-btn-primary" disabled={dirty||unavailable||item?.draft?.state!=="DRAFT"} onClick={()=>void api.execute("validate",versionPayload)}>使用当前明细复算</button><p className="boss-helper">{dirty?"存在未保存编辑：先保存指标草稿再复算。":item?.draft?.state!=="DRAFT"?"只有已保存且尚未校验的草稿可以复算；已校验的草稿需要修改并重新保存后再复算。":"复算使用当前执行空间明细、所选统计范围与公式版本，逐组显示输入与差异；缺少明细时服务拒绝复算，不补零。"}</p></>}
        {domain==="tools"&&<><V7Fact label="实际采用记录">{uses.length}</V7Fact><V7Fact label="最近采用版本">{uses.at(-1)?.version??"尚无采用记录"}</V7Fact><p>配置校验与实际请求结果分别记录；工具启用不扩大业务权限。</p><p className="boss-helper">启用后是否进入聊天的实际工具集由运行侧报告；当前接口尚未返回该字段，页面不作已接入结论。</p><div className="boss-actions"><button className="boss-btn" onClick={showUses}>查看实际调用</button><button className="boss-btn" onClick={()=>onNavigate("A02")}>接口参数与实际响应</button></div></>}
        {domain==="access"&&<><V7Fact label="维护身份">{api.data?.access.maintainer_id??"尚未读取"}</V7Fact><V7Fact label="可见范围">{Array.isArray(values.object_scopes)?values.object_scopes.join("、"):"尚未选择"}</V7Fact><V7Fact label="当前启用版本生效状态">{item?.current?effectiveState(item.current.values.valid_from,item.current.values.valid_until):"尚未启用"}</V7Fact><V7Fact label="老板档案">{api.data?.access.owner_id??"尚未读取"}</V7Fact><V7Fact label="本人确认状态">{api.data?.access.owner_confirmation_state??"尚未读取"}</V7Fact><V7Fact label="私人正文">无访问权限</V7Fact><p>技术访问配置不授予老板业务决定权限。</p><button className="boss-btn" onClick={()=>onNavigate("A14")}>查看访问结果</button></>}
      </V7Panel>
      {domain!=="tools"&&<V7Panel title={domain==="metrics"?"规则运行记录":"状态与核查"}>
        <V7Fact label="执行空间">{api.data?.namespace??"尚未读取"}</V7Fact><V7Fact label="读取时间">{api.data?.read_at??"尚未读取"}</V7Fact>
        <V7Fact label={domain==="metrics"?"指标采用记录":"访问采用记录"}>{uses.length}</V7Fact>
        {domain==="metrics"?<><p>提醒触发、恢复与抑制需要读取获准的运行记录；指标采用次数单独记录。</p><div className="boss-actions"><button className="boss-btn" onClick={showUses}>查看指标采用记录</button><button className="boss-btn" onClick={()=>onNavigate("A15")}>打开运行记录</button><button className="boss-btn" onClick={()=>onNavigate("A13")}>查看调度计划</button></div></>:<><p className="boss-helper">{uses.length?"已记录访问采用；逐条结果在“实际采用”页签，按实际请求核对允许与拒绝。":"尚未发生访问检查：当前没有可核查的访问结果，页面不预测通过。"}</p><button className="boss-btn" onClick={showUses}>查看访问检查状态</button></>}
      </V7Panel>}
    </aside></div>
    {domain==="tools"&&<V7Panel title="参数验证与接口调用全量记录" className="boss-config-full-records"><div className="boss-v7-table-scroll"><table className="boss-v7-table"><thead><tr><th>检查环节</th><th>版本</th><th>状态</th><th>结果与字段</th><th>下一步</th></tr></thead><tbody>
      {checks.map(check=><tr key={"check:"+check.name}><td>{check.name}</td><td>{item?.draft?.version}</td><td>{check.state}</td><td>{check.message}</td><td><button className="boss-btn" onClick={showEditor}>查看配置</button></td></tr>)}
      {uses.map(use=><tr key={use.id}><td>实际采用 · {use.run_id}</td><td>{use.version}</td><td>{use.state}</td><td>{use.details?<pre className="boss-v7-code">{JSON.stringify(use.details,null,2)}</pre>:"没有额外请求或响应正文"}</td><td><button className="boss-btn" onClick={showUses}>查看采用记录</button></td></tr>)}
    </tbody></table></div>{!checks.length&&!uses.length&&<V7Empty title="尚无参数验证与实际调用记录"/>}</V7Panel>}
    <Dialog.Root open={confirm} onOpenChange={setConfirm}><Dialog.Portal><Dialog.Overlay className="boss-v7-dialog-overlay"/><Dialog.Content className="boss-v7-dialog"><Dialog.Title>启用此版本</Dialog.Title><Dialog.Description>{item?.title}（{selected}）· v{item?.draft?.version}。先核对增加与移除的范围，再确认启用。</Dialog.Description>
      {diff.length?<div className="boss-v7-table-scroll"><table className="boss-v7-table"><thead><tr><th>项目</th><th>当前启用版本</th><th>待启用版本</th></tr></thead><tbody>{diff.map(row=><tr key={row.label}><td>{row.label}</td><td>{row.before}</td><td>{row.after}</td></tr>)}</tbody></table></div>:<p className="boss-helper">与当前启用版本相比没有字段或范围变化。</p>}
      {domain==="metrics"&&<p className="boss-helper">独立复算：{checks.length} 组明细通过；公式 {String(values.formula??"尚未读取")}；单位 {String(values.unit??"尚未读取")}；统计范围 {String(values.scope??"尚未选择")}。</p>}
      <p className="boss-helper">启用后，后续请求采用此版本，已开始的运行保留原版本；存在进行中的运行时服务会拒绝启用。回执后重新读取，核对实际采用记录。</p>
      <div className="boss-actions"><Dialog.Close asChild><button className="boss-btn">取消</button></Dialog.Close><button className="boss-btn boss-btn-primary" disabled={unavailable} onClick={()=>{setConfirm(false);void api.execute("activate",versionPayload);}}>确认启用此版本</button></div></Dialog.Content></Dialog.Portal></Dialog.Root>
  </div>;
}
