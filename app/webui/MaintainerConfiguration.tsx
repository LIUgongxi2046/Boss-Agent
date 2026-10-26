import {useEffect, useRef, useState,type ReactNode} from "react";
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
type Field={key:string;label:string;type?:"number"|"textarea"|"json"|"select"|"multiselect"|"checkbox"|"datetime-local";options?:string;required?:boolean;min?:number;max?:number;help?:string};
type Section={title:string;description:string;fields:Field[]};
function editableValues(values:Values):Values{
  const result={...values};
  for(const key of ["valid_from","valid_until","effective_at"]){
    if(typeof result[key]==="string"&&result[key])result[key]=new Intl.DateTimeFormat("sv-SE",{timeZone:"Asia/Shanghai",year:"numeric",month:"2-digit",day:"2-digit",hour:"2-digit",minute:"2-digit",hourCycle:"h23"}).format(new Date(result[key] as string)).replace(" ","T");
  }
  return result;
}
const DEFINITIONS:Record<Domain,{title:string;sections:Section[];side:string}>={
  access:{title:"技术访问配置",side:"本人档案与访问范围",sections:[
    {title:"内容与配置",description:"维护身份只获得所选技术资料范围。",fields:[
      {key:"name",label:"配置名称",required:true},{key:"subject_id",label:"维护身份",type:"select",options:"maintainers",required:true},
      {key:"object_scopes",label:"允许访问的对象范围",type:"multiselect",options:"object_scopes",required:true},
      {key:"permissions",label:"技术权限",type:"multiselect",options:"technical_permissions",required:true}]},
    {title:"关联内容与处理范围",description:"老板本人决定及私人正文继续由本人权限控制。",fields:[
      {key:"valid_from",label:"开始时间（Asia/Shanghai）",type:"datetime-local",required:true},
      {key:"valid_until",label:"结束时间（Asia/Shanghai）",type:"datetime-local",required:true},
      {key:"change_note",label:"变更说明",type:"textarea",required:true}]}]},
  tools:{title:"工具定义与连接",side:"接口与实际调用",sections:[
    {title:"工具目录与版本",description:"每次运行引用已启用的工具版本。",fields:[
      {key:"name",label:"工具名称",required:true},
      {key:"description",label:"用途与调用条件",type:"textarea",required:true}]},
    {title:"输入输出 Schema",description:"使用 JSON Schema 检查请求和响应。",fields:[
      {key:"input_schema",label:"输入 Schema JSON",type:"json",required:true},{key:"output_schema",label:"输出 Schema JSON",type:"json",required:true}]},
    {title:"接口、安全与执行规则",description:"写入操作需要当前有效的本人动作授权。",fields:[
      {key:"operation_id",label:"业务接口",type:"select",options:"operations",required:true},
      {key:"connection_id",label:"服务端连接引用",type:"select",options:"connections",required:true},
      {key:"side_effect",label:"副作用",type:"select",options:"side_effects",required:true},
      {key:"permission",label:"调用身份与授权规则",type:"select",options:"tool_permissions",required:true},
      {key:"timeout_seconds",label:"超时（秒）",type:"number",min:1,max:300,required:true},
      {key:"idempotency_field",label:"幂等字段",required:true},
      {key:"error_schema",label:"错误响应 Schema",type:"json",required:true},
      {key:"change_note",label:"变更说明",type:"textarea",required:true}]}]},
  metrics:{title:"指标定义与计算",side:"计算版本与采用记录",sections:[
    {title:"指标定义与生效",description:"计算采用原始明细和明确的统计范围；达到生效时间后，后续查询采用对应版本。",fields:[
      {key:"name",label:"指标名称",required:true},{key:"metric_id",label:"指标标识",type:"select",options:"metric_ids",required:true},
      {key:"formula",label:"计算公式",type:"select",options:"formulas",required:true},
      {key:"dimensions",label:"维度",type:"multiselect",options:"dimensions",required:true},
      {key:"unit",label:"单位",type:"select",options:"units",required:true},
      {key:"precision",label:"显示精度",type:"number",min:0,max:8,required:true},
      {key:"scope",label:"统计范围",type:"select",options:"metric_scopes",required:true},
      {key:"effective_at",label:"生效时间（Asia/Shanghai）",type:"datetime-local",required:true},
      {key:"refresh_seconds",label:"刷新间隔（秒）",type:"number",min:1,max:86400,required:true,help:"再次查询时，达到刷新间隔或明细版本改变即重新计算。"},
      {key:"change_note",label:"变更说明",type:"textarea",required:true}]}]},
};

export function MaintainerMetricsConfiguration({onDirtyChange,onNavigate}:{onDirtyChange:(dirty:boolean)=>void;onNavigate:(page:string)=>void}){
  const [metricsDirty,setMetricsDirty]=useState(false),[rulesDirty,setRulesDirty]=useState(false);
  useEffect(()=>onDirtyChange(metricsDirty||rulesDirty),[metricsDirty,rulesDirty,onDirtyChange]);
  return <MaintainerConfiguration domain="metrics" onDirtyChange={setMetricsDirty} onNavigate={onNavigate} relatedContent={<BossBusinessAlertRules role="MAINTAINER" title="经营提醒与规则" onDirtyChange={setRulesDirty}/>}/>;
}

function EditorField({field,value,options,onChange}:{field:Field;value:Scalar|undefined;options:Projection["options"];onChange:(value:Scalar)=>void}){
  const id="technical-"+field.key;
  const choices=options[field.options||""]||[];
  if(field.type==="multiselect")return <fieldset className="boss-v7-check-list"><legend>{field.label}</legend>{choices.map(item=><label key={item.id}><input type="checkbox" checked={Array.isArray(value)&&value.includes(item.id)} onChange={event=>onChange(event.target.checked?[...(Array.isArray(value)?value:[]),item.id]:(Array.isArray(value)?value:[]).filter(id=>id!==item.id))}/>{item.label}</label>)}{!choices.length&&<p>当前没有可选范围</p>}</fieldset>;
  return <label className={"boss-field "+(["textarea","json"].includes(field.type||"")?"boss-v7-full-field":"")} htmlFor={id}><span>{field.label}{field.required&&" *"}</span>
    {field.type==="select"?<select id={id} required={field.required} value={String(value??"")} onChange={event=>onChange(event.target.value)}><option value="">请选择</option>{choices.map(item=><option key={item.id} value={item.id}>{item.label}</option>)}</select>:
      field.type==="textarea"||field.type==="json"?<textarea id={id} className={field.type==="json"?"boss-v7-code":""} rows={field.type==="json"?9:3} required={field.required} value={String(value??"")} spellCheck={field.type!=="json"} onChange={event=>onChange(event.target.value)}/>:
      <input id={id} type={field.type||"text"} required={field.required} min={field.min} max={field.max} value={typeof value==="string"||typeof value==="number"?value:""} onChange={event=>onChange(field.type==="number"&&event.target.value!==""?event.target.valueAsNumber:event.target.value)}/>}
    {field.help&&<small>{field.help}</small>}
  </label>;
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
  const item=api.data?.items.find(row=>row.id===selected)??null;
  useEffect(()=>{
    if(!api.data||dirty)return;
    const current=api.data.items.find(row=>row.id===selected)??(selectedExplicitly.current?undefined:api.data.items[0]);
    setSelected(current?.id??"");setValues(editableValues(current?.draft?.values??current?.current?.values??{}));editVersion.current=current?.draft?.version??"0";
  },[api.data,dirty]);
  function choose(id:string){
    if(dirty||api.pending)return;
    selectedExplicitly.current=true;
    const current=api.data?.items.find(row=>row.id===id);setSelected(id);setValues(editableValues(current?.draft?.values??current?.current?.values??{}));editVersion.current=current?.draft?.version??"0";setLocalError("");
  }
  function edit(key:string,value:Scalar){setValues(current=>({...current,[key]:value}));setDirty(true);onDirtyChange(true);setLocalError("");}
  function save(){
    for(const section of definition.sections)for(const field of section.fields){
      const value=values[field.key];
      if(field.required&&(value===undefined||value===""||Array.isArray(value)&&!value.length)){setLocalError("请填写"+field.label);return;}
    }
    const submitted={...values};
    for(const section of definition.sections)for(const field of section.fields)if(field.type==="datetime-local"&&submitted[field.key])submitted[field.key]=new Date(String(submitted[field.key])+":00+08:00").toISOString();
    void api.execute("save",{object_id:selected||null,expected_version:editVersion.current,values:submitted}).then(saved=>{if(saved){selectedExplicitly.current=true;setSelected(domain==="access"?"maintainer-access":String(submitted[domain==="metrics"?"metric_id":"operation_id"]));setDirty(false);onDirtyChange(false);}});
  }
  const versionPayload={object_id:selected,expected_version:item?.draft?.version,expected_content_sha256:item?.draft?.content_sha256,expected_active_version:item?.current?.version??"0"};
  const unavailable=api.loading||api.busy||!!api.pending;
  const uses=(api.data?.uses.filter(row=>row.object_id===selected)??[]).sort((left,right)=>left.at.localeCompare(right.at));
  const checks=item?.draft?.validation?.checks??[];
  function showUses(){setTab("uses");requestAnimationFrame(()=>{usesRef.current?.scrollIntoView({block:"start",behavior:"smooth"});usesRef.current?.focus({preventScroll:true});});}
  function showEditor(){setTab("edit");requestAnimationFrame(()=>{editorRef.current?.scrollIntoView({block:"start",behavior:"smooth"});editorRef.current?.focus({preventScroll:true});});}
  function actions(mode:"all"|"schema"|"execute"="all"){
    return <div className="boss-actions">
      {mode!=="execute"&&<button className="boss-btn" type="submit" disabled={!dirty||unavailable}><Save size={16}/>{domain==="tools"?"保存工具草稿":domain==="metrics"?"保存指标草稿":"保存草稿"}</button>}
      <button className="boss-btn" type="button" disabled={dirty||!item?.draft||item.draft.state!=="DRAFT"||unavailable} onClick={()=>void api.execute("validate",versionPayload)}><FileCode2 size={16}/>{domain==="metrics"?"校验公式":mode==="schema"?"校验 Schema":domain==="tools"?"验证参数与连接":"校验配置"}</button>
      {mode!=="schema"&&<button className="boss-btn boss-btn-primary" type="button" disabled={dirty||item?.draft?.state!=="VALIDATED"||item.draft.validation?.state!=="PASSED"||unavailable} onClick={()=>setConfirm(true)}><ShieldCheck size={16}/>{domain==="tools"?"启用工具":"启用版本"}</button>}
      {mode!=="execute"&&dirty&&<button className="boss-btn" type="button" disabled={unavailable} onClick={()=>{setValues(editableValues(item?.draft?.values??item?.current?.values??{}));setDirty(false);onDirtyChange(false);setLocalError("");}}>取消本次编辑</button>}
    </div>;
  }
  const validation=<>{checks.map(check=><div key={check.name} className="boss-workspace-item"><strong>{check.name} · {check.state}</strong><p className="boss-config-check-message">{check.message}</p></div>)}{!checks.length&&<p className="boss-helper">当前版本尚无已保存的校验结果。</p>}</>;
  return <div className={"boss-v7-configuration boss-config-"+domain}>
    <V7ReadState loading={api.loading} error={api.error||localError} onReload={api.reload}/>
    {api.pending&&<div className="boss-status boss-status-warn" role="status">请求 {api.pending.request_id} 等待核查。<button className="boss-btn" disabled={api.busy} onClick={()=>void api.reconcile()}>核查原请求</button></div>}
    {api.receipt&&<div className="boss-status boss-status-ok" role="status"><CheckCircle2 size={17}/>操作已记录 · {api.receipt.request_id}</div>}
      <div className="boss-config-toolbar" aria-label={definition.title}>
        <div className="boss-v7-filter-bar"><label>查找配置<input type="search" value={query} onChange={event=>setQuery(event.target.value)} placeholder="名称或标识"/></label><label>当前配置<select disabled={dirty||unavailable} value={selected} onChange={event=>choose(event.target.value)}><option value="">新建配置</option>{api.data?.items.filter(row=>row.id===selected||(row.title+row.id).toLowerCase().includes(query.toLowerCase())).map(row=><option key={row.id} value={row.id}>{row.title} · {row.id}</option>)}</select></label></div>
        <button className="boss-btn" disabled={dirty||unavailable} onClick={api.reload}><RefreshCw size={16}/>重新读取</button>
        <V7Tabs label="配置视图" value={tab} onChange={setTab} items={[{id:"edit",title:"编辑配置"},{id:"history",title:"版本记录"},{id:"uses",title:"实际采用"}]}/>
      </div>
    <div className={domain==="access"?"boss-config-access-columns":"boss-columns"}><div className="boss-column">
      {tab==="edit"&&<form ref={editorRef} tabIndex={-1} onSubmit={event=>{event.preventDefault();save();}}>
        <fieldset className="boss-v7-form-fieldset" disabled={unavailable||!api.data}>
          {definition.sections.map((section,index)=><V7Panel key={section.title} title={section.title} description={section.description}>
            <div className={domain==="tools"&&index===1?"boss-config-schema-pair":"boss-form-grid"}>{section.fields.map(field=>domain==="tools"&&index===1?<V7Panel key={field.key} title={field.key==="input_schema"?"Input Schema":"Output Schema"}><EditorField field={field} value={values[field.key]} options={api.data?.options??{}} onChange={value=>edit(field.key,value)}/></V7Panel>:<EditorField key={field.key} field={field} value={values[field.key]} options={api.data?.options??{}} onChange={value=>edit(field.key,value)}/>)}</div>
            {domain==="tools"&&index===0&&<><V7Fact label="当前编辑版本">{item?.draft?.version??"尚未保存"}</V7Fact><V7Fact label="连接状态">{uses.length?"已有实际采用记录，请核查具体请求结果":"尚无实际连接记录"}</V7Fact></>}
            {domain==="access"&&index===0&&<><V7Fact label="老板档案">{api.data?.access.owner_id??"尚未读取"}</V7Fact><V7Fact label="本人确认状态（只读）">{api.data?.access.owner_confirmation_state??"尚未读取"}</V7Fact><V7Fact label="私人正文">无访问权限</V7Fact></>}
            {domain==="tools"?(index>0&&actions(index===1?"schema":"execute")):index===definition.sections.length-1&&actions()}
          </V7Panel>)}
        </fieldset>
      </form>}
      {relatedContent}
      {tab==="history"&&<V7Panel title="配置版本记录">{item?.history.length?<div className="boss-v7-table-scroll"><table className="boss-v7-table"><thead><tr><th>版本</th><th>状态</th><th>时间</th><th>变更说明</th></tr></thead><tbody>{item.history.map(row=><tr key={row.version}><td>{row.version}</td><td>{row.state}</td><td>{row.created_at}</td><td>{row.values.change_note}</td></tr>)}</tbody></table></div>:<V7Empty title="尚无历史版本"/>}</V7Panel>}
      {tab==="uses"&&<div ref={usesRef} tabIndex={-1}><V7Panel title="实际采用记录">{uses.length?<div className="boss-v7-table-scroll"><table className="boss-v7-table"><thead><tr><th>运行</th><th>采用版本</th><th>结果</th><th>时间</th></tr></thead><tbody>{uses.map(row=><tr key={row.id}><td>{row.run_id}</td><td>{row.version}</td><td>{row.state}{row.details&&<details><summary>计算与维度依据</summary><pre className="boss-v7-code">{JSON.stringify(row.details,null,2)}</pre></details>}</td><td>{row.at}</td></tr>)}</tbody></table></div>:<V7Empty title="尚无该配置的实际采用记录">启用版本后，后续请求的采用情况在此显示。</V7Empty>}</V7Panel></div>}
    </div><aside className="boss-column">
      <V7Panel title={domain==="tools"?"验证和实际调用":domain==="metrics"?"独立复算结果":"来源与依据"}>
        <V7Fact label="草稿版本">{item?.draft?"v"+item.draft.version:dirty?"存在未保存编辑":"尚未保存"}</V7Fact>
        <V7Fact label="校验状态">{item?.draft?.validation?.state??"尚未校验"}</V7Fact>
        <V7Fact label="启用版本">{item?.current?"v"+item.current.version:"尚未启用"}</V7Fact>
        {domain==="metrics"&&<><V7Fact label="当前输入范围">{String(values.scope??"尚未选择")}</V7Fact><V7Fact label="公式版本">{item?.effective_version??"尚未读取"}</V7Fact><V7Fact label="生效状态">{item?.activation_state==="SCHEDULED"?"等待生效时间":item?.activation_state==="EFFECTIVE"?"已生效":item?.activation_state==="BUILTIN"?"当前业务定义":"尚未读取"}</V7Fact></>}
        {validation}
        {domain==="metrics"&&<button className="boss-btn boss-btn-primary" disabled={dirty||unavailable||item?.draft?.state!=="DRAFT"} onClick={()=>void api.execute("validate",versionPayload)}>独立复算</button>}
        {domain==="tools"&&<><V7Fact label="实际采用记录">{uses.length}</V7Fact><V7Fact label="最近采用版本">{uses.at(-1)?.version??"尚无采用记录"}</V7Fact><p>配置校验与实际请求结果分别记录；工具启用不扩大业务权限。</p><div className="boss-actions"><button className="boss-btn" onClick={showUses}>查看实际调用</button><button className="boss-btn" onClick={()=>onNavigate("A02")}>接口参数与实际响应</button></div></>}
        {domain==="access"&&<><V7Fact label="维护身份">{api.data?.access.maintainer_id??"尚未读取"}</V7Fact><V7Fact label="可见范围">{Array.isArray(values.object_scopes)?values.object_scopes.join("、"):"尚未选择"}</V7Fact><p>技术访问配置不授予老板业务决定权限。</p><button className="boss-btn" onClick={()=>onNavigate("A14")}>查看合法与拒绝记录</button></>}
      </V7Panel>
      {domain!=="tools"&&<V7Panel title={domain==="metrics"?"规则运行记录":"状态与核查"}>
        <V7Fact label="执行空间">{api.data?.namespace??"尚未读取"}</V7Fact><V7Fact label="读取时间">{api.data?.read_at??"尚未读取"}</V7Fact>
        <V7Fact label={domain==="metrics"?"指标采用记录":"访问采用记录"}>{uses.length}</V7Fact>
        {domain==="metrics"?<><p>提醒触发、恢复与抑制需要读取获准的运行记录；指标采用次数单独记录。</p><div className="boss-actions"><button className="boss-btn" onClick={showUses}>查看指标采用记录</button><button className="boss-btn" onClick={()=>onNavigate("A15")}>打开运行记录</button><button className="boss-btn" onClick={()=>onNavigate("A13")}>查看调度计划</button></div></>:<button className="boss-btn" onClick={showUses}>查看下一次访问检查</button>}
      </V7Panel>}
    </aside></div>
    {domain==="tools"&&<V7Panel title="参数验证与接口调用全量记录" className="boss-config-full-records"><div className="boss-v7-table-scroll"><table className="boss-v7-table"><thead><tr><th>检查环节</th><th>版本</th><th>状态</th><th>结果与字段</th><th>下一步</th></tr></thead><tbody>
      {checks.map(check=><tr key={"check:"+check.name}><td>{check.name}</td><td>{item?.draft?.version}</td><td>{check.state}</td><td>{check.message}</td><td><button className="boss-btn" onClick={showEditor}>查看配置</button></td></tr>)}
      {uses.map(use=><tr key={use.id}><td>实际采用 · {use.run_id}</td><td>{use.version}</td><td>{use.state}</td><td>{use.details?<pre className="boss-v7-code">{JSON.stringify(use.details,null,2)}</pre>:"没有额外请求或响应正文"}</td><td><button className="boss-btn" onClick={showUses}>查看采用记录</button></td></tr>)}
    </tbody></table></div>{!checks.length&&!uses.length&&<V7Empty title="尚无参数验证与实际调用记录"/>}</V7Panel>}
    <Dialog.Root open={confirm} onOpenChange={setConfirm}><Dialog.Portal><Dialog.Overlay className="boss-v7-dialog-overlay"/><Dialog.Content className="boss-v7-dialog"><Dialog.Title>启用当前配置版本</Dialog.Title><Dialog.Description>配置 {selected} · v{item?.draft?.version}。后续请求将采用此版本，已开始的运行保留原版本。</Dialog.Description><div className="boss-actions"><Dialog.Close asChild><button className="boss-btn">取消</button></Dialog.Close><button className="boss-btn boss-btn-primary" disabled={unavailable} onClick={()=>{setConfirm(false);void api.execute("activate",versionPayload);}}>确认启用</button></div></Dialog.Content></Dialog.Portal></Dialog.Root>
  </div>;
}
