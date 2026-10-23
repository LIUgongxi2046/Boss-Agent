import {useId, useState} from "react";

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
  records:SupplyQualityRecord[];source_statuses:{record_id:string;content_state:string;data:unknown;source_refs:{source_id:string;version:string|null;status:string}[]}[];
  availability:"PARTIAL"|"UNAVAILABLE";last_import:{state:string;record_count:number;received_at:string}|null;missing_fields:string[];
  supply:Supply[];trace:Trace|null;events:SupplyQualityRecord[];coordination_links:{task_id:string;origin_record_id:string;origin_version:string}[];
  review_sha256:string;business_at:string;read_at:string;external_service_invoked:false;purchase_executed:false;quality_release_executed:false};
export type SupplyQualityReceipt={action:string;client_request_id:string;outcome:"RECORDED"|"NOT_FOUND_IN_CURRENT_STORE";result:unknown};
export type SupplyQualityEditor={originId:string;purpose:string;due:string;evidence:string;approvedFor:string|null;pending:Record<string,unknown>|null};
export const EMPTY_SUPPLY_EDITOR:SupplyQualityEditor={originId:"",purpose:"",due:"",evidence:"",approvedFor:null,pending:null};
type Props={data:SupplyQualityProjection|null;loading:boolean;error:string;onReload:()=>void;onOpenSource:(sourceId:string)=>void;
  onOpenTask:(taskId:string)=>void;onCommand:(action:string,payload:Record<string,unknown>)=>Promise<unknown>;
  onReceipt:(action:string,key:string)=>Promise<SupplyQualityReceipt>;editor:SupplyQualityEditor;onEditorChange:(changes:Partial<SupplyQualityEditor>)=>void};
const ACTION="boss.supply_quality.coordinate";
const value=(quantity:string|null,unit="")=>quantity===null?"未知":quantity+(unit?" "+unit:"");

export function BossSupplyQualityPanel({data,loading,error,onReload,onOpenSource,onOpenTask,onCommand,onReceipt,editor,onEditorChange}:Props){
  const heading=useId();
  const [search,setSearch]=useState("");
  const {originId,purpose,due,evidence,approvedFor,pending}=editor;
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
  const changed=()=>setApprovedFor(null);
  function saved(){onEditorChange({...EMPTY_SUPPLY_EDITOR});setBusy(false);setNotice("协调任务已经保存，请打开交办查看发送与后续状态。");onReload();}
  async function submit(){
    if(busy||(!pending&&(loading||!data||!selected||approvedFor!==data.review_sha256||!purpose.trim()||!due||!evidence.trim())))return;
    const payload=pending||{client_request_id:"supply-coordinate-"+crypto.randomUUID(),interface_id:data!.interface_id,
      origin_entity_type:selected!.entity_type,origin_record_id:selected!.record_id,origin_version:selected!.version,
      review_sha256:data!.review_sha256,purpose:purpose.trim(),coordinator_id:"coordinator-1",due_at:due+":00+08:00",timezone:"Asia/Shanghai",
      evidence_requirements:evidence.split("\n").map(text=>text.trim()).filter(Boolean)};
    setPending(payload);setBusy(true);setFailure("");setNotice("");
    await onCommand(ACTION,payload).then(result=>{
      const savedResult=result as {task_id?:unknown;coordination_link?:{origin_record_id?:unknown};external_service_invoked?:unknown;quality_release_executed?:unknown;purchase_executed?:unknown};
      if(typeof savedResult?.task_id!=="string"||savedResult.coordination_link?.origin_record_id!==payload.origin_record_id||savedResult.external_service_invoked!==false||savedResult.quality_release_executed!==false||savedResult.purchase_executed!==false){setBusy(false);setFailure("协调回执与当前请求不符，请核查原请求。");return;}
      saved();
    },(error:unknown)=>{
      setBusy(false);setFailure(error instanceof Error?error.message:String(error));
      if(error instanceof Error&&error.name==="WebUIMutationError"&&"status" in error&&typeof error.status==="number"&&[400,401,403,404,409,410,413,422].includes(error.status)){
        setPending(null);setApprovedFor(null);onReload();
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
  return <section className="boss-panel" aria-labelledby={heading}>
    <div className="boss-panel-head"><h2 id={heading}>{data?.interface_id==="SI10"?"批次追溯与品质核查":"原料与库存协调"}</h2>
      <button type="button" className="boss-btn" disabled={loading||busy} onClick={onReload}>重新读取当前资料</button></div>
    <p className="boss-helper">SIMULATED · 当前外部资料仅用于程序行为检查；专业结论、采购执行与质量放行分别由原业务系统负责。</p>
    {loading&&<p role="status">正在读取当前来源与业务资料</p>}
    {(error||failure)&&<p className="boss-status boss-status-error" role="alert">{error||failure}</p>}
    {notice&&<p className="boss-status" role="status">{notice}</p>}
    {pending&&<section aria-label="协调原请求核查"><p className="boss-helper" role="status">请求编号：{String(pending.client_request_id)}；执行结果通过原请求核查。</p>
      <div className="boss-actions"><button type="button" className="boss-btn" disabled={busy} onClick={()=>void reconcile()}>核查原请求回执</button>
        <button type="button" className="boss-btn" disabled={busy} onClick={()=>void submit()}>使用原请求编号继续提交</button></div></section>}
    {data&&<>
      <p>资料版本 {data.dataset_version} · 业务时间 {data.business_at} · 读取时间 {data.read_at}</p>
      <p>最近导入：{data.last_import?data.last_import.state+" · "+data.last_import.record_count+" 条记录 · "+data.last_import.received_at:"尚无导入记录"}</p>
      {data.availability==="UNAVAILABLE"&&<p role="status">当前没有可采用的业务资料，请核查导入状态和来源。</p>}
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
          <button type="button" className="boss-btn" disabled={busy} onClick={()=>onOpenSource(report.current.source_id)}>打开当前成本报告</button>
        </section>)}
        {row.excluded_inventory.length>0&&<p>排除库存：{row.excluded_inventory.map(item=>item.inventory_id+"（"+item.reason+"）").join("、")}</p>}
      </article>)}
      {data.trace&&<section aria-label="批次关系与数量">
        <h3>加工投入与产出</h3>{data.trace.processing_totals.map(row=><p key={row.processing_id}>{row.processing_id}：投入 {value(row.input_quantity,row.quantity_unit)}；产出 {value(row.output_quantity,row.quantity_unit)}；损耗 {value(row.loss_quantity,row.quantity_unit)}</p>)}
        <h3>已确认库存关系</h3>{data.trace.confirmed_inventory.map((row,index)=><p key={index}>{row.inventory_id} · 产出批次 {row.batch_id} · {value(row.quantity,row.quantity_unit)}</p>)}
        <h3>已确认客户关系</h3>{data.trace.confirmed_customers.map((row,index)=><p key={index}>{row.customer_id} · {value(row.quantity,row.quantity_unit)}</p>)}
        {Object.entries(data.trace.relationships_by_state).filter(([state])=>state!=="CONFIRMED").map(([state,rows])=><details key={state}><summary>{state} · {rows.length} 条关系</summary>{rows.map((row,index)=><pre key={index}>{JSON.stringify(row,null,2)}</pre>)}</details>)}
        <p className="boss-helper">关系确认、专业意见和原质量事件分别保存；当前关系不构成质量原因确认。</p>
      </section>}
      {data.events.map(event=><p key={event.record_id}>原质量事件 {event.record_id} · 专业处理状态 {event.state}</p>)}
      <section aria-label="业务原始记录"><h3>原始记录、专业作者与有效范围</h3>
        <label className="boss-field">查找当前记录编号<input value={search} onChange={event=>setSearch(event.target.value)}/></label>
        {data.records.filter(record=>!search.trim()||record.record_id.includes(search.trim())).map(record=><details key={record.entity_type+":"+record.record_id}>
          <summary>{record.entity_type} · {record.record_id} · v{record.version} · {record.state}</summary>
          <p>作者 {record.author_contact_id} · 观察 {record.observed_at} · 生效 {record.valid_from} · 到期 {record.valid_until??"尚未提供"}</p>
          <pre>{JSON.stringify(record.data,null,2)}</pre><button type="button" className="boss-btn" disabled={busy} onClick={()=>onOpenSource(record.source_id)}>打开当前原始记录</button>
        </details>)}
        {data.source_statuses.filter(record=>record.data===null).map(record=><p key={record.record_id} role="status">{record.record_id}：需要核查当前来源；{record.source_refs.filter(reference=>reference.status!=="VALID").map(reference=>reference.source_id+" · "+reference.status).join("；")}</p>)}
      </section>
      <details><summary>资料缺少范围（{data.missing_fields.length}）</summary>{data.missing_fields.map(field=><p key={field}>{field}</p>)}</details>
      <section aria-label="本人协调交办"><h3>授权统筹交办</h3>
        <fieldset disabled={busy||loading||Boolean(pending)||data.records.length===0}>
          <label className="boss-field">协调依据<select aria-label="协调依据" value={originId} onChange={event=>{setOriginId(event.target.value);changed();}}><option value="">请选择当前记录</option>{data.records.map(record=><option key={record.entity_type+":"+record.record_id} value={record.entity_type+":"+record.record_id}>{record.entity_type} · {record.record_id} · v{record.version}</option>)}</select></label>
          <label className="boss-field">协调目的<textarea aria-label="协调目的" maxLength={2000} value={purpose} onChange={event=>{setPurpose(event.target.value);changed();}}/></label>
          <p>统筹负责人：coordinator-1 · 由服务核查当前职责</p>
          <label className="boss-field">截止时间（Asia/Shanghai）<input aria-label="截止时间（Asia/Shanghai）" type="datetime-local" value={due} onChange={event=>{setDue(event.target.value);changed();}}/></label>
          <label className="boss-field">证据要求（每行一项，最多八项）<textarea aria-label="证据要求（每行一项，最多八项）" value={evidence} onChange={event=>{setEvidence(event.target.value);changed();}}/></label>
          <label className="boss-confirm-check"><input type="checkbox" checked={approvedFor===data.review_sha256} onChange={event=>setApprovedFor(event.target.checked?data.review_sha256:null)}/>本人确认当前依据、负责人、期限与证据要求</label>
        </fieldset>
        {!pending&&<div className="boss-actions"><button type="button" className="boss-btn boss-btn-primary" disabled={busy||loading||!selected||approvedFor!==data.review_sha256||!purpose.trim()||!due||!evidence.trim()} onClick={()=>void submit()}>{busy?"正在核查":"本人确认创建协调任务"}</button></div>}
        {data.coordination_links.map(link=><p key={link.task_id}>{link.origin_record_id} v{link.origin_version} · 交办 {link.task_id} · <button type="button" className="boss-btn" disabled={busy||Boolean(pending)} onClick={()=>onOpenTask(link.task_id)}>查看交办列表</button></p>)}
      </section>
    </>}
  </section>;
}
