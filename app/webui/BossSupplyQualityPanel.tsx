import {useEffect,useId,useRef,useState,type ReactNode} from "react";
import * as Dialog from "@radix-ui/react-dialog";

export type SupplyQualityRecord={record_id:string;entity_type:string;version:string;state:string;source_id:string;source_version:string;
  source_type:"SIMULATED";observed_at:string;valid_from:string;valid_until:string|null;author_contact_id:string;data:Record<string,unknown>};
type Supply={material_id:string;legal_entity_id:string;asset_owner_id:string;ownership_type:string;customer_id:string|null;quantity_unit:string;currency:string;
  available_quantity:string|null;daily_quantity:string|null;coverage_days:string|null;quote_price_difference:string|null;contract_unit_prices:(string|null)[];
  actual_cost_change:null;required_quantity:string|null;quantity_gap:string|null;hypothetical_plan_quote_difference:string|null;calculation_basis:string;
  consumption_assumptions:string[];excluded_inventory:{inventory_id:string;reason:string}[];cost_reports:CostReport[]};
type CostReportSummary={report_id:string;source_id:string;source_version:string;period_start:string;period_end:string;quantity:string|null;total_cost:string|null;unit_cost:string|null};
type CostReport={cost_type:"INBOUND_RECEIPT"|"ACTUAL_CONSUMPTION";cost_owner_id:string|null;report_scope_id:string;cost_basis_id:string;scope_description:string;currency:string;quantity_unit:string;
  current:CostReportSummary;baseline:CostReportSummary|null;comparison_state:string;unit_cost_change:string|null;total_cost_change:string|null;formula:string;missing_fields:string[]};
type Trace={processing_totals:{processing_id:string;input_quantity:string|null;output_quantity:string|null;loss_quantity:string|null;quantity_unit:string}[];
  confirmed_inventory:{inventory_id:string;batch_id:string;quantity:string|null;quantity_unit:string}[];
  confirmed_customers:{customer_id:string;quantity:string|null;quantity_unit:string}[];
  unconfirmed_relationships:Record<string,unknown>[];relationships_by_state:Record<string,Record<string,unknown>[]>;causal_conclusion:null};
export type SupplyQualityProjection={source_type:"SIMULATED";interface_id:"SI09"|"SI10";execution_namespace:string;dataset_version:string;
  applied_filters?:Record<string,string>;coordinators?:{contact_id:string;name:string;organization:string;responsibility:string}[];
  records:SupplyQualityRecord[];source_statuses:{record_id:string;content_state:string;data:unknown;source_refs:{source_id:string;version:string|null;status:string}[]}[];
  availability:"PARTIAL"|"UNAVAILABLE";last_import:{state:string;record_count:number;received_at:string}|null;missing_fields:string[];
  supply:Supply[];trace:Trace|null;events:SupplyQualityRecord[];coordination_links:{task_id:string;origin_record_id:string;origin_version:string}[];
  review_sha256:string;business_at:string;read_at:string;external_service_invoked:false;purchase_executed:false;quality_release_executed:false};
export type SupplyQualityReceipt={action:string;client_request_id:string;outcome:"RECORDED"|"NOT_FOUND_IN_CURRENT_STORE";result:unknown};
type Prepared={source_type:"SIMULATED";run_id:string;client_request_id:string;preparation_sha256:string;owner_decision_required:true;business_authority_granted:false;coordinate_input:Record<string,unknown>};
export type SupplyQualityEditor={originId:string;purpose:string;due:string;evidence:string;coordinatorId?:string;timezone?:string;basis?:string;approvedFor:string|null;pending:Record<string,unknown>|null;pendingPreparation?:Record<string,unknown>|null;prepared?:Prepared|null};
export const EMPTY_SUPPLY_EDITOR:SupplyQualityEditor={originId:"",purpose:"",due:"",evidence:"",coordinatorId:"",timezone:"",basis:"",approvedFor:null,pending:null,pendingPreparation:null,prepared:null};
type Props={interfaceId:"SI09"|"SI10";data:SupplyQualityProjection|null;loading:boolean;error:string;onReload:()=>void;onOpenSource:(sourceId:string)=>void;
  onOpenTask:(taskId:string)=>void;onCommand:(action:string,payload:Record<string,unknown>)=>Promise<unknown>;
  onReceipt:(action:string,key:string)=>Promise<SupplyQualityReceipt>;editor:SupplyQualityEditor;onEditorChange:(changes:Partial<SupplyQualityEditor>)=>void};
const ACTION="boss.supply_quality.coordinate";
const value=(quantity:string|null,unit="")=>quantity===null?"未知":quantity+(unit?" "+unit:"");
function Card({title,children}:{title:string;children:ReactNode}){return <section className="boss-panel"><div className="boss-panel-head"><h2>{title}</h2></div>{children}</section>;}
const FIELD_LABELS:Record<string,string>={material_id:"原料编号",product_id:"产品编号",legal_entity_id:"法人编号",asset_owner_id:"资产归属",cost_owner_id:"成本归属",quantity:"数量",quantity_unit:"数量单位",currency:"币种",price:"行情价格",price_unit:"价格单位",origin:"产地",quoted_at:"报价时间",contract_id:"合同编号",unit_price:"合同单价",quality_state:"库存质量",quality_requirements:"质量要求",quality_requirement:"质量要求",formula_id:"配方编号",professional_state:"专业状态",composition_complete:"配方完整性",ingredients:"配方组成",ratio:"配方比例",ratio_unit:"比例单位",valid_from:"有效起始",valid_until:"有效截至",batch_id:"批次编号",input_batch_id:"原料批次",output_batch_id:"产出批次",processing_id:"加工编号",inventory_id:"库存编号",customer_id:"客户编号",complaint_id:"客诉编号",trace_id:"关系编号",trace_state:"关系状态",inspection_state:"检验状态",input_quantity:"投入数量",output_quantity:"产出数量",loss_quantity:"损耗数量",destination_quantity:"流向数量",professional_record_id:"专业意见编号",author_contact_id:"专业作者",applicability:"适用范围",content:"专业内容",conclusion:"专业结论",followup_at:"后续检查时间",coverage:"资料覆盖",description:"说明",event_id:"原事件编号",state:"当前状态",order_id:"订单编号",status:"业务状态",delivery_window:"交付时间",starts_at:"开始时间",ends_at:"结束时间",report_scope_id:"报告范围",cost_basis_id:"成本口径",period_start:"期间开始",period_end:"期间结束",total_cost:"报告总成本",unit_cost:"报告单位成本",purpose:"用途",species:"品类",stage:"阶段"};
const REVIEW_STATE_LABELS:Record<string,string>={PENDING_REVIEW:"待专业复核",PROFESSIONALLY_CONFIRMED:"专业已确认",REVIEW_RESULT_REPORTED:"复核结果已报告"};
function RecordValue({item}:{item:unknown}):ReactNode{if(item===null||item===undefined)return "未知";if(Array.isArray(item))return item.length?item.map((value,index)=><div key={index}><RecordValue item={value}/></div>):"当前没有记录";if(typeof item==="object")return <RecordFields data={item as Record<string,unknown>}/>;return String(item);}
function RecordFields({data}:{data:Record<string,unknown>}){return <dl className="boss-supply-record-fields">{Object.entries(data).map(([key,item])=><div key={key}><dt>{FIELD_LABELS[key]??key}</dt><dd><RecordValue item={item}/></dd></div>)}</dl>;}

export function BossSupplyQualityPanel({interfaceId,data,loading,error,onReload,onOpenSource,onOpenTask,onCommand,onReceipt,editor,onEditorChange}:Props){
  const heading=useId();
  const [search,setSearch]=useState("");
  const [showCoordination,setShowCoordination]=useState(false),detailsRef=useRef<HTMLElement|null>(null),linksRef=useRef<HTMLDivElement|null>(null),costRef=useRef<HTMLDivElement|null>(null),reviewRef=useRef<HTMLDivElement|null>(null),affectedRef=useRef<HTMLDivElement|null>(null);
  const {originId,purpose,due,evidence,approvedFor,pending}=editor;
  const coordinatorId=editor.coordinatorId??"",timezone=editor.timezone??"";
  const setOriginId=(originId:string)=>onEditorChange({originId});
  const setPurpose=(purpose:string)=>onEditorChange({purpose});
  const setDue=(due:string)=>onEditorChange({due});
  const setEvidence=(evidence:string)=>onEditorChange({evidence});
  const setApprovedFor=(approvedFor:string|null)=>onEditorChange({approvedFor});
  const setPending=(pending:Record<string,unknown>|null)=>onEditorChange({pending});
  const [busy,setBusy]=useState(false);
  const [failure,setFailure]=useState("");
  const [notice,setNotice]=useState("");
  const selected=data?.records.find(record=>record.entity_type+":"+record.record_id===originId);
  const stale=Boolean(data&&editor.basis&&editor.basis!==data.review_sha256);
  const approvalKey=JSON.stringify([data?.review_sha256,selected?.version,purpose,due,evidence,coordinatorId,timezone]);
  const ready=Boolean(data&&selected&&!loading&&!stale&&purpose.trim()&&coordinatorId.trim()&&timezone.trim()&&Number.isFinite(Date.parse(due))&&evidence.trim()&&evidence.split("\n").filter(row=>row.trim()).length<=8);
  const changed=()=>onEditorChange({approvedFor:null,prepared:null,basis:editor.basis||data?.review_sha256||""});
  function remember(kind:"Coordinate"|"Preparation",payload:Record<string,unknown>|null){const url=new URL(window.location.href),prefix="supply"+interfaceId+kind;for(const suffix of ["Request","Origin"]){if(payload)url.searchParams.set(prefix+suffix,String(suffix==="Request"?payload.client_request_id:payload.origin_record_id??""));else url.searchParams.delete(prefix+suffix);}window.history.replaceState(window.history.state,"",url);}
  useEffect(()=>{const query=new URLSearchParams(window.location.search),coordinate=query.get("supply"+interfaceId+"CoordinateRequest"),preparation=query.get("supply"+interfaceId+"PreparationRequest");if(coordinate&&!pending)onEditorChange({pending:{client_request_id:coordinate,origin_record_id:query.get("supply"+interfaceId+"CoordinateOrigin"),restored:true}});if(preparation&&!editor.pendingPreparation)onEditorChange({pendingPreparation:{client_request_id:preparation,restored:true}});},[interfaceId]);
  const preparationInput=()=>({interface_id:data!.interface_id,origin_entity_type:selected!.entity_type,origin_record_id:selected!.record_id,
    origin_version:selected!.version,review_sha256:data!.review_sha256,purpose:purpose.trim(),coordinator_id:coordinatorId.trim(),due_at:due,timezone:timezone.trim(),evidence_requirements:evidence.split("\n").map(text=>text.trim()).filter(Boolean)});
  async function prepare(reconcile=false){
    if(busy||pending||(!editor.pendingPreparation&&!ready)||editor.pendingPreparation&&!reconcile)return;
    const payload=editor.pendingPreparation||{client_request_id:"fc01-prepare-"+crypto.randomUUID(),coordinate_input:preparationInput()};
    remember("Preparation",payload);
    onEditorChange({pendingPreparation:payload,prepared:null,approvedFor:null});setBusy(true);setFailure("");
    await onCommand(reconcile?"boss.fc01.status":"boss.fc01.prepare",reconcile?{client_request_id:payload.client_request_id}:payload).then(result=>{
      const state=result as {status?:string;run_id?:string;client_request_id?:string;source_type?:string};
      if(state.source_type==="SIMULATED"&&state.client_request_id===payload.client_request_id&&state.status&&["FAILED","CANCELED","TIMED_OUT"].includes(state.status)){
        remember("Preparation",null);onEditorChange({pendingPreparation:null,prepared:null,approvedFor:null});setBusy(false);setFailure("原准备请求 "+String(payload.client_request_id)+" 的运行状态为 "+state.status+"。可以核查运行记录后重新准备。");return;
      }
      const prepared=result as Prepared;
      const expected=payload.coordinate_input as Record<string,unknown>;
      if(prepared.source_type!=="SIMULATED"||typeof prepared.run_id!=="string"||prepared.client_request_id!==payload.client_request_id||prepared.owner_decision_required!==true||prepared.business_authority_granted!==false||!prepared.coordinate_input||expected&&(Object.keys(prepared.coordinate_input).length!==Object.keys(expected).length||Object.keys(expected).some(key=>JSON.stringify(prepared.coordinate_input[key])!==JSON.stringify(expected[key])))){
        setBusy(false);setFailure("准备结果尚未确定，请保留原请求编号核查。");return;
      }
      remember("Preparation",null);onEditorChange({prepared:expected?prepared:null,pendingPreparation:null,approvedFor:null});setBusy(false);setNotice(expected?"当前模拟助手已读取实际来源并准备材料，请本人核查当前内容后决定。":"原准备请求已经完成。当前页面未保留原输入，请重新核查当前来源后准备协调材料。");
    },(reason:unknown)=>{setBusy(false);setFailure(reason instanceof Error?reason.message:String(reason));
      if(!reconcile&&reason instanceof Error&&"status" in reason&&typeof reason.status==="number"&&[400,401,403,404,409,410,422].includes(reason.status)){remember("Preparation",null);onEditorChange({pendingPreparation:null});}});
  }
  function saved(){remember("Coordinate",null);onEditorChange({...EMPTY_SUPPLY_EDITOR});setBusy(false);setShowCoordination(false);setNotice("交办任务已经保存，请打开交办查看发送与后续状态。");onReload();}
  async function submit(){
    if(busy||pending||editor.pendingPreparation||!ready||approvedFor!==approvalKey)return;
    const payload={client_request_id:"supply-coordinate-"+crypto.randomUUID(),interface_id:data!.interface_id,
      origin_entity_type:selected!.entity_type,origin_record_id:selected!.record_id,origin_version:selected!.version,
      review_sha256:data!.review_sha256,purpose:purpose.trim(),coordinator_id:coordinatorId.trim(),due_at:due,timezone:timezone.trim(),
      evidence_requirements:evidence.split("\n").map(text=>text.trim()).filter(Boolean)};
    remember("Coordinate",payload);setPending(payload);setBusy(true);setFailure("");setNotice("");
    const {client_request_id,...coordinate_input}=payload;
    await onCommand(editor.prepared?"boss.fc01.coordinate":ACTION,editor.prepared?{client_request_id,coordinate_input,preparation_request_id:editor.prepared.client_request_id}:payload).then(result=>{
      const savedResult=result as {task_id?:unknown;coordination_link?:{origin_record_id?:unknown};external_service_invoked?:unknown;quality_release_executed?:unknown;purchase_executed?:unknown};
      if(typeof savedResult?.task_id!=="string"||savedResult.coordination_link?.origin_record_id!==payload.origin_record_id||savedResult.external_service_invoked!==false||savedResult.quality_release_executed!==false||savedResult.purchase_executed!==false){setBusy(false);setFailure("协调回执与当前请求不符，请核查原请求。");return;}
      saved();
    },(error:unknown)=>{
      setBusy(false);setFailure(error instanceof Error?error.message:String(error));
      if(error instanceof Error&&error.name==="WebUIMutationError"&&"status" in error&&typeof error.status==="number"&&[400,401,403,404,409,410,413,422].includes(error.status)){
        remember("Coordinate",null);setPending(null);setApprovedFor(null);onReload();
      }
    });
  }
  async function reconcile(){
    if(!pending||busy)return;
    setBusy(true);setFailure("");
    await onReceipt(ACTION,String(pending.client_request_id)).then(receipt=>{
      setBusy(false);
      if(receipt.action!==ACTION||receipt.client_request_id!==pending.client_request_id){setFailure("回执与当前请求编号不符，需要继续核查。");return;}
      if(receipt.outcome==="RECORDED"){
        const result=receipt.result as {task_id?:unknown;coordination_link?:{origin_record_id?:unknown}};
        if(typeof result?.task_id!=="string"||result.coordination_link?.origin_record_id!==pending.origin_record_id){setFailure("协调原回执内容不符，需要继续核查。");return;}
        saved();return;
      }
      setFailure("当前没有查到原请求回执，执行结果仍未确定。请保留原请求编号继续核查。");onReload();
    },(error:unknown)=>{setBusy(false);setFailure(error instanceof Error?error.message:String(error));});
  }
  const reviewRecords=data?.records.filter(record=>record.entity_type==="professional_record"&&(typeof record.data.event_id==="string"||typeof record.data.batch_id==="string"))??[];
  return <div className="boss-supply-workspace" aria-labelledby={heading}>
    <div className="boss-workspace-toolbar"><strong id={heading}>{interfaceId==="SI10"?"批次追溯与品质核查":"原料与库存协调"}</strong></div>
    <p className="boss-helper">SIMULATED · 当前外部资料仅用于程序行为检查；专业结论、采购执行与质量放行分别由原业务系统负责。</p>
    {loading&&<p role="status">正在读取当前来源与业务资料</p>}
    {(error||failure)&&<p className="boss-status boss-status-error" role="alert">{error||failure}</p>}
    {notice&&<p className="boss-status" role="status">{notice}</p>}
    {editor.prepared&&<p className="boss-helper">SIMULATED · 准备运行 {editor.prepared.run_id} · 当前内容仍需本人决定</p>}
    {editor.pendingPreparation&&<section aria-label="准备原请求核查"><p>准备请求编号：{String(editor.pendingPreparation.client_request_id)}</p><button type="button" className="boss-btn" disabled={busy} onClick={()=>void prepare(true)}>核查原准备请求</button></section>}
    {pending&&<section aria-label="协调原请求核查"><p className="boss-helper" role="status">请求编号：{String(pending.client_request_id)}；执行结果通过原请求核查。</p>
      <div className="boss-actions"><button type="button" className="boss-btn" disabled={busy} onClick={()=>void reconcile()}>核查原请求回执</button></div></section>}
    {stale&&<p className="boss-status boss-status-warn">当前资料或协调状态已经变化，编辑内容需要重新核查。<button type="button" className="boss-btn" disabled={busy||Boolean(pending)||Boolean(editor.pendingPreparation)} onClick={()=>onEditorChange({basis:data?.review_sha256,approvedFor:null,prepared:null})}>采用当前依据重新核查</button></p>}
    <div className="boss-supply-columns"><main className="boss-column"><div ref={costRef} tabIndex={-1}><Card title={interfaceId==="SI09"?"经营指标与趋势":"关系与来源核查"}>
    {data&&<>
      <p>资料版本 {data.dataset_version} · 业务时间 {data.business_at} · 读取时间 {data.read_at}</p>
      <p>最近导入：{data.last_import?data.last_import.state+" · "+data.last_import.record_count+" 条记录 · "+data.last_import.received_at:"尚无导入记录"}</p>
      {data.availability==="UNAVAILABLE"&&<p role="status">当前没有可采用的业务资料，请核查导入状态和来源。</p>}
      {interfaceId==="SI09"&&<div className="boss-supply-prices">{data.records.filter(record=>record.entity_type==="material_quote").map(record=><article className="boss-workspace-item" key={record.record_id}><h3>行情报价 · {record.record_id}</h3><RecordFields data={record.data}/><p>来源：{record.source_id} / v{record.source_version}</p></article>)}</div>}
      {data.supply.map((row,index)=><article className="boss-workspace-item" key={index}>
        <h3>{row.material_id} · {row.legal_entity_id}</h3>
        <p>资产归属 {row.asset_owner_id} · {row.ownership_type} · 客户 {row.customer_id??"没有关联客户"}</p>
        <dl><dt>可用库存</dt><dd>{value(row.available_quantity,row.quantity_unit)}</dd><dt>假设日耗用</dt><dd>{value(row.daily_quantity,row.quantity_unit+"/日")}</dd>
          <dt>覆盖天数</dt><dd>{value(row.coverage_days,"日")}</dd><dt>同产地报价变化</dt><dd>{value(row.quote_price_difference,row.currency+"/"+row.quantity_unit)}</dd>
          <dt>合同单价</dt><dd>{row.contract_unit_prices.length?row.contract_unit_prices.map(price=>value(price,row.currency+"/"+row.quantity_unit)).join("；"):"未知"}</dd>
          <dt>完整原料成本变化</dt><dd>{value(row.actual_cost_change)}</dd><dt>计划原料需要量</dt><dd>{value(row.required_quantity,row.quantity_unit)}</dd>
          <dt>计划供应缺口</dt><dd>{value(row.quantity_gap,row.quantity_unit)}</dd><dt>计划数量对应的报价变化假设</dt><dd>{value(row.hypothetical_plan_quote_difference,row.currency)}</dd></dl>
        <p className="boss-helper">{row.calculation_basis}</p>{row.consumption_assumptions.map(text=><p className="boss-helper" key={text}>{text}</p>)}
        {row.cost_reports.length===0&&<p>入库成本与实际领用成本：尚未提供当前报告。</p>}
        {row.cost_reports.map(report=><section key={JSON.stringify([report.cost_type,report.report_scope_id,report.cost_basis_id,report.cost_owner_id])} aria-label={report.cost_type==="INBOUND_RECEIPT"?"已报告入库成本":"已报告实际领用成本"}>
          <h4>{report.cost_type==="INBOUND_RECEIPT"?"已报告入库成本":"已报告实际领用成本"}</h4>
          <p>报告范围 {report.report_scope_id} · 成本口径 {report.cost_basis_id} · 成本归属 {report.cost_owner_id??"未知"}</p><p>{report.scope_description}</p>
          <p>当前期间 {report.current.period_start} 至 {report.current.period_end} · 数量 {value(report.current.quantity,report.quantity_unit)} · 金额 {value(report.current.total_cost,report.currency)} · 单位成本 {value(report.current.unit_cost,report.currency+"/"+report.quantity_unit)}</p>
          {report.baseline&&<p>基期 {report.baseline.period_start} 至 {report.baseline.period_end} · 数量 {value(report.baseline.quantity,report.quantity_unit)} · 金额 {value(report.baseline.total_cost,report.currency)} · 单位成本 {value(report.baseline.unit_cost,report.currency+"/"+report.quantity_unit)}</p>}
          <p>报告单位成本变化 {value(report.unit_cost_change,report.currency+"/"+report.quantity_unit)} · 报告总成本变化 {value(report.total_cost_change,report.currency)} · 比较状态 {report.comparison_state}</p>
          <p className="boss-helper">{report.formula}</p>{report.missing_fields.map(field=><p className="boss-helper" key={field}>{field}</p>)}
          <button type="button" className="boss-btn" disabled={busy} onClick={()=>onOpenSource(report.current.source_id)}>查看依据</button>
        </section>)}
        {row.excluded_inventory.length>0&&<p>排除库存：{row.excluded_inventory.map(item=>item.inventory_id+"（"+item.reason+"）").join("、")}</p>}
      </article>)}
      {data.trace&&<section aria-label="批次关系与数量">
        <div className="boss-workspace-toolbar"><h3>加工投入与产出</h3><button type="button" className="boss-btn" onClick={()=>{affectedRef.current?.scrollIntoView({block:"start",behavior:"smooth"});affectedRef.current?.focus();}}>查看受影响库存／客户</button></div>{data.trace.processing_totals.map(row=><p key={row.processing_id}>{row.processing_id}：投入 {value(row.input_quantity,row.quantity_unit)}；产出 {value(row.output_quantity,row.quantity_unit)}；损耗 {value(row.loss_quantity,row.quantity_unit)}</p>)}
        <div ref={affectedRef} tabIndex={-1} aria-label="受影响库存与客户">
          <h3>已确认库存关系</h3>{data.trace.confirmed_inventory.map((row,index)=><p key={index}>{row.inventory_id} · 产出批次 {row.batch_id} · {value(row.quantity,row.quantity_unit)}</p>)}
          <h3>已确认客户关系</h3>{data.trace.confirmed_customers.map((row,index)=><p key={index}>{row.customer_id} · {value(row.quantity,row.quantity_unit)}</p>)}
          {!data.trace.confirmed_inventory.length&&!data.trace.confirmed_customers.length&&<p className="boss-helper">尚无关系证据支持的库存或客户，影响数量未知。</p>}
        </div>
        {Object.entries(data.trace.relationships_by_state).map(([state,rows])=><details key={state} open={state==="CONFIRMED"}><summary>{state} · {rows.length} 条关系</summary>{rows.map((row,index)=><article className="boss-workspace-item" key={index}><RecordFields data={row}/></article>)}</details>)}
        <p className="boss-helper">关系确认、专业意见和原质量事件分别保存；当前关系不构成质量原因确认。</p>
      </section>}
      {interfaceId==="SI09"&&<p className="boss-helper">趋势依据当前与基期成本报告展示；报价变化、合同价格与实际成本各自采用对应资料。</p>}
    </>}{!data&&!loading&&<p className="boss-helper">等待取得与当前查询条件一致的计算及关系结果。</p>}</Card></div>
      <section className="boss-panel" ref={detailsRef} tabIndex={-1} aria-label="业务原始记录"><div className="boss-panel-head"><h2>{interfaceId==="SI09"?"数据明细与资料覆盖":"关联记录"}</h2></div>
        <label className="boss-field">查找当前记录编号<input value={search} onChange={event=>setSearch(event.target.value)}/></label>
        <p className="boss-helper">展开一条记录后可查看原始记录，或将其采用为交办依据；页面底部准备交办时需要选择一条依据。</p>
        {data?.records.filter(record=>!search.trim()||record.record_id.includes(search.trim())).map(record=><details key={record.entity_type+":"+record.record_id}>
          <summary>{record.entity_type} · {record.record_id} · v{record.version} · {record.state}</summary>
          <p>作者 {record.author_contact_id} · 观察 {record.observed_at} · 生效 {record.valid_from} · 到期 {record.valid_until??"尚未提供"}</p>
          <RecordFields data={record.data}/><div className="boss-actions"><button type="button" className="boss-btn" disabled={busy} onClick={()=>onOpenSource(record.source_id)}>查看原始记录</button><button type="button" className="boss-btn" disabled={busy||Boolean(pending)||Boolean(editor.pendingPreparation)} onClick={()=>{if(originId&&originId!==record.entity_type+":"+record.record_id&&(purpose||due||evidence)){setFailure("交办表单已有编辑内容，请在表单中明确选择依据");setShowCoordination(true);return;}onEditorChange({originId:record.entity_type+":"+record.record_id,basis:data.review_sha256,approvedFor:null,prepared:null});setShowCoordination(true);}}>采用为交办依据</button></div>
        </details>)}
        {data?.source_statuses.filter(record=>record.data===null).map(record=><p key={record.record_id} role="status">{record.record_id}：需要核查当前来源；{record.source_refs.filter(reference=>reference.status!=="VALID").map(reference=>reference.source_id+" · "+reference.status).join("；")}</p>)}
        {data&&!data.records.length&&<p className="boss-helper">当前范围没有可采用的原始记录。</p>}
      </section>
    </main><aside className="boss-column"><Card title="来源与依据">
      <div className="boss-kv"><span>执行空间</span><strong>{data?.execution_namespace??"尚未提供"}</strong></div><div className="boss-kv"><span>资料版本</span><strong>{data?.dataset_version??"尚未提供"}</strong></div><div className="boss-kv"><span>业务时间</span><strong>{data?.business_at??"尚未提供"}</strong></div><div className="boss-kv"><span>核查摘要</span><strong>{data?.review_sha256??"尚未提供"}</strong></div>
      {data?.records.filter(record=>["feed_formula","professional_record"].includes(record.entity_type)||record.entity_type+":"+record.record_id===originId).map(record=><article className="boss-workspace-item" key={record.entity_type+":"+record.record_id}><strong>{record.entity_type} · {record.record_id}</strong><p>作者：{record.author_contact_id}</p><p>版本：{record.version} · 来源：{record.source_id} / v{record.source_version}</p><p>观察时间：{record.observed_at}</p><p>有效期：{record.valid_from} — {record.valid_until??"尚未提供"}</p><p>专业状态：{record.state}</p><RecordFields data={record.data}/><button type="button" className="boss-btn" onClick={()=>onOpenSource(record.source_id)}>查看依据</button></article>)}
      <p className="boss-helper">有效配方、专业意见和检验记录按正式来源及时间范围采用。未知关系和缺少成本依据继续保留。</p>
    </Card><Card title="状态与核查"><div className="boss-kv"><span>资料可用性</span><strong>{data?.availability??"尚未查询"}</strong></div><div className="boss-kv"><span>读取时间</span><strong>{data?.read_at??"尚未提供"}</strong></div><h3>资料缺少范围</h3>{data?.missing_fields.map(field=><p className="boss-helper" key={field}>{field}</p>)}<h3>原质量事件</h3>{data?.events.map(event=><article className="boss-workspace-item" key={event.record_id}><strong>{event.record_id}</strong><p>原事件版本：{event.version}</p><p>专业处理状态：{event.state}</p><button type="button" className="boss-btn" onClick={()=>onOpenSource(event.source_id)}>查看依据</button></article>)}{data&&!data.events.length&&<p className="boss-helper">当前范围没有原质量事件。</p>}
      {interfaceId==="SI10"&&<div ref={reviewRef} tabIndex={-1}><h3>复核记录</h3>{reviewRecords.length?reviewRecords.map(record=><article className="boss-workspace-item" key={record.entity_type+":"+record.record_id}><strong>{record.record_id}</strong><p>记录作者：{record.author_contact_id} · 版本：{record.version}</p><p>复核状态：{REVIEW_STATE_LABELS[record.state]??record.state}</p><RecordFields data={record.data}/><button type="button" className="boss-btn" onClick={()=>onOpenSource(record.source_id)}>查看依据</button></article>):<p className="boss-helper">尚未复核：当前资料没有复核记录。</p>}</div>}
      <div ref={linksRef} tabIndex={-1}><h3>协调交办与后续检查</h3>{data?.coordination_links.map(link=><article className="boss-workspace-item" key={link.task_id}><strong>{link.task_id}</strong><p>依据：{link.origin_record_id} / v{link.origin_version}</p><button type="button" className="boss-btn" disabled={busy||Boolean(pending)} onClick={()=>onOpenTask(link.task_id)}>打开协调任务</button></article>)}{data&&!data.coordination_links.length&&<p className="boss-helper">当前没有协调交办记录。</p>}</div><p className="boss-helper">协调完成与供应恢复、原事件状态、质量放行分别核查。</p>
    </Card></aside></div>
    {data?<footer className="boss-supply-footer boss-actions">
      {interfaceId==="SI09"?<>
        <button type="button" className="boss-btn" onClick={()=>{costRef.current?.scrollIntoView({block:"start",behavior:"smooth"});costRef.current?.focus();}}>查看成本明细与计算条件</button>
        <button type="button" className="boss-btn" disabled aria-describedby={heading+"-meeting"}>准备成本分析会议</button>
        <span className="boss-helper" id={heading+"-meeting"}>准备成本分析会议需要会议时间、参会人与材料服务；当前服务尚未接入。</span>
        <button type="button" className="boss-btn boss-btn-primary" disabled={busy||data.records.length===0} onClick={()=>setShowCoordination(true)}>准备协调交办</button>
      </>:<>
        <button type="button" className="boss-btn" onClick={()=>{reviewRef.current?.scrollIntoView({block:"start",behavior:"smooth"});reviewRef.current?.focus();}}>复核记录</button>
        <button type="button" className="boss-btn boss-btn-primary" disabled={busy||data.records.length===0} onClick={()=>setShowCoordination(true)}>准备品质核查交办</button>
      </>}
      {data.records.length===0&&<span className="boss-helper">当前范围没有可交办的记录，请核查导入状态与资料范围。</span>}
    </footer>:<p className="boss-helper">查询后显示当前范围可用的后续操作；未选择对象时不显示业务操作。</p>}
    <Dialog.Root open={showCoordination} onOpenChange={open=>{if(!busy)setShowCoordination(open);}}><Dialog.Portal><Dialog.Overlay className="boss-v7-dialog-overlay"/><Dialog.Content className="boss-v7-dialog boss-supply-dialog"><Dialog.Title>{interfaceId==="SI09"?"准备协调交办":"准备品质核查交办"}</Dialog.Title><Dialog.Description>核查当前来源、负责人、期限和证据要求。交办任务需要独立发送与完成确认。</Dialog.Description><section aria-label="本人交办表单">
        <fieldset disabled={busy||loading||!data||stale||Boolean(pending)||Boolean(editor.pendingPreparation)||data.records.length===0}>
          <label className="boss-field">交办依据<select aria-label="交办依据" value={originId} onChange={event=>{setOriginId(event.target.value);changed();}}><option value="">请选择当前记录</option>{data?.records.map(record=><option key={record.entity_type+":"+record.record_id} value={record.entity_type+":"+record.record_id}>{record.entity_type} · {record.record_id} · v{record.version}</option>)}</select></label>
          <label className="boss-field">交办目的<textarea aria-label="交办目的" maxLength={2000} value={purpose} onChange={event=>{setPurpose(event.target.value);changed();}}/></label>
          <label className="boss-field">统筹负责人{data?.coordinators?<select value={coordinatorId} onChange={event=>{onEditorChange({coordinatorId:event.target.value});changed();}}><option value="">请选择负责人</option>{data.coordinators.map(contact=><option key={contact.contact_id} value={contact.contact_id}>{contact.name} · {contact.organization} · {contact.responsibility} [{contact.contact_id}]</option>)}</select>:<input value={coordinatorId} placeholder="填写完整负责人编号，当前职责由服务核查" onChange={event=>{onEditorChange({coordinatorId:event.target.value});changed();}}/>}</label>
          <label className="boss-field">截止时间（包含UTC时差）<input value={due} placeholder="ISO 8601完整时间" onChange={event=>{setDue(event.target.value);changed();}}/></label><label className="boss-field">IANA时区<input value={timezone} onChange={event=>{onEditorChange({timezone:event.target.value});changed();}}/></label>
          <label className="boss-field">证据要求（每行一项，最多八项）<textarea aria-label="证据要求（每行一项，最多八项）" value={evidence} onChange={event=>{setEvidence(event.target.value);changed();}}/></label>
          <label className="boss-confirm-check"><input type="checkbox" checked={ready&&approvedFor===approvalKey} disabled={!ready} onChange={event=>setApprovedFor(event.target.checked?approvalKey:null)}/>本人确认当前依据、负责人、期限与证据要求</label>
        </fieldset>
        {!pending&&!editor.pendingPreparation&&<button type="button" className="boss-btn" disabled={busy||!ready} onClick={()=>void prepare()}>通过模拟助手准备当前交办材料</button>}
        {!pending&&<div className="boss-actions"><button type="button" className="boss-btn boss-btn-primary" disabled={busy||!ready||approvedFor!==approvalKey||Boolean(editor.pendingPreparation)} onClick={()=>void submit()}>{busy?"正在核查":"核对并创建交办"}</button></div>}
        {failure&&<p role="alert" className="boss-status boss-status-error">{failure}</p>}{stale&&<p className="boss-helper">当前依据已经变化，请关闭表单并重新核查当前资料。</p>}{(pending||editor.pendingPreparation)&&<p className="boss-helper">原请求结果尚待核查，请关闭表单后使用原请求查询入口。</p>}<Dialog.Close asChild><button type="button" className="boss-btn" disabled={busy}>返回资料页面</button></Dialog.Close>
      </section>
    </Dialog.Content></Dialog.Portal></Dialog.Root>
  </div>;
}
