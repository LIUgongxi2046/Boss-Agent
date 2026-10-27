import { useEffect, useRef, useState, type FormEvent } from "react";
import { useClient } from "@/providers/ClientProvider";
import schema from "./simulation-query.schema.json";
import {V7Empty,V7Fact,V7Panel,V7Tabs} from "./BossV7UI";

type Result = {
  source_type: "SIMULATED"; dataset_id: string; dataset_version: string; execution_namespace: string;
  interface_id: string; availability: "PARTIAL" | "UNAVAILABLE"; access: "TECHNICAL_METADATA";
  records: {record_id: string; object_id: string; storage_id: string; entity_type: string; version: string | null;
    state: string | null; content_state: "METADATA_ONLY"; data: null; source_refs: never[]; business_authorization_granted: false}[];
  missing_fields: string[]; sources: never[]; business_as_of: string | null; read_at: string;
  business_actions_performed: false; external_retrieval_performed: false;
};
const NAMES: Record<string, string> = {
  SI01: "个人档案与组织", SI02: "联系人与关系", SI03: "日历与出行", SI04: "消息与邮件",
  SI05: "会议与资料", SI06: "任务与承诺", SI07: "销售与经营 BI", SI08: "财务与应收",
  SI09: "采购与库存", SI10: "生产、质量与客诉", SI11: "审批", SI12: "行业与外部信息",
  SI13: "知识资料", SI14: "通知中心",
};
const DETAIL_FILTERS = ["period_start", "period_end", "region_id", "product_ids", "legal_entity_id", "customer_id", "currency", "source_version"];
const SUPPLY_FILTERS = ["material_id", "asset_owner_id", "cost_owner_id", "ownership_type", "product_ids", "legal_entity_id", "customer_id", "batch_id", "currency", "source_version", "period_start", "period_end"];
const FILTER_LABELS: Record<string, string> = {
  period_start: "开始日期", period_end: "结束日期", region_id: "区域编号", product_ids: "产品编号列表",
  legal_entity_id: "法人编号", customer_id: "客户编号", material_id: "物料编号", asset_owner_id: "资产归属编号",
  cost_owner_id: "成本归属编号", ownership_type: "归属类型", batch_id: "批次编号", currency: "币种",
  source_version: "来源资料版本", purpose: "用途", stage: "阶段",
};
const SUPPORTED: Record<string, string[]> = Object.fromEntries(schema.$defs.Interface.enum.map(identifier => [identifier,
  ["SI07", "SI08"].includes(identifier) ? DETAIL_FILTERS : ["SI09", "SI10"].includes(identifier) ? SUPPLY_FILTERS : identifier === "SI13" ? ["source_version"] : []]));
const QUERY_FIELDS = [
  {name: "interface_id", type: "枚举 SI01—SI14", required: true},
  {name: "object_ids", type: "对象编号数组，最多 100 项且不能重复；页面留空表示不限制对象", required: false},
  {name: "filters", type: "筛选对象，字段按当前接口适用；未列出的字段会被服务拒绝", required: false},
];
const RESULT_FIELDS = [
  {name: "source_type", type: "固定 SIMULATED", required: true},
  {name: "dataset_id · dataset_version", type: "当前模拟数据集与版本", required: true},
  {name: "execution_namespace", type: "实际执行空间", required: true},
  {name: "interface_id", type: "接口编号", required: true},
  {name: "availability", type: "PARTIAL 或 UNAVAILABLE", required: true},
  {name: "records", type: "对象标识、类别、版本与状态；不含正文", required: true},
  {name: "missing_fields", type: "当前缺少的资料来源范围", required: true},
  {name: "business_as_of · read_at", type: "业务资料时间与实际读取时间", required: true},
  {name: "business_actions_performed · external_retrieval_performed", type: "固定 false", required: true},
];
export type SimulationObservation={id:string;request:string;at:string;elapsed_ms:number;namespace:string;result:Result|null;error:string|null};
type InspectionContext={namespace:string;datasetId:string;version:string};

export function MaintainerSimulationInspect({onOpenTools,onObservation,expectedContext}: {onOpenTools: () => void;onObservation?:(value:SimulationObservation)=>void;expectedContext?:InspectionContext}) {
  const {client, getToken, token} = useClient();
  const [interfaceId, setInterfaceId] = useState("SI01");
  const [objectIds, setObjectIds] = useState("");
  const [filters, setFilters] = useState("{}");
  const [advanced, setAdvanced] = useState(false);
  const [result, setResult] = useState<Result | null>(null);
  const [request, setRequest] = useState("");
  const [requestedAt, setRequestedAt] = useState("");
  const [elapsed, setElapsed] = useState<number | null>(null);
  const [error, setError] = useState("");
  const [fieldError, setFieldError] = useState("");
  const [notice, setNotice] = useState("");
  const [loading, setLoading] = useState(false);
  const active = useRef<AbortController | null>(null);
  const epoch = useRef(0);
  const requestPanel=useRef<HTMLFormElement>(null),schemaPanel=useRef<HTMLElement>(null),responsePanel=useRef<HTMLElement>(null);
  const [section,setSection]=useState("request");
  function focusSection(name:string){setSection(name);const target=name==="schema"?schemaPanel.current:name==="response"?responsePanel.current:requestPanel.current;target?.scrollIntoView({block:"start",behavior:"smooth"});target?.focus();}
  function clear() {
    epoch.current += 1; active.current?.abort();
    setResult(null); setRequest(""); setRequestedAt(""); setElapsed(null); setError(""); setFieldError(""); setNotice(""); setLoading(false);
  }
  useEffect(() => {
    clear(); setObjectIds(""); setFilters("{}"); setInterfaceId("SI01"); setAdvanced(false); setSection("request");
    return () => {epoch.current += 1; active.current?.abort();};
  }, [client, token]);

  function selectInterface(identifier:string){
    if(identifier===interfaceId)return;
    clear(); setInterfaceId(identifier); setObjectIds(""); setFilters("{}"); setAdvanced(false);
  }
  function buildRoute():{route:string}|{error:string} {
    let parsed:unknown;
    try { parsed = JSON.parse(filters.trim()||"{}"); }
    catch (failure) { return {error:"高级参数不是有效 JSON：" + (failure instanceof Error ? failure.message : "格式无效")}; }
    if (parsed === null || typeof parsed !== "object" || Array.isArray(parsed)) return {error:"高级参数需要是 JSON 对象，例如 {\"region_id\":\"region-1\"}"};
    const ids = objectIds.split(/\r?\n/).map(value => value.trim()).filter(Boolean);
    if (ids.length > 100) return {error:"对象编号最多 100 个，当前填写 " + ids.length + " 个"};
    const repeated = ids.filter((value, index) => ids.indexOf(value) !== index);
    if (repeated.length) return {error:"对象编号「" + repeated[0] + "」重复，请去掉重复项"};
    const parameters = new URLSearchParams({interface_id: interfaceId});
    for (const id of ids) parameters.append("object_ids", id);
    const known = Object.keys(schema.$defs.Query.properties.filters.properties);
    const supported = SUPPORTED[interfaceId] ?? [];
    for (const [name, value] of Object.entries(parsed as Record<string, unknown>)) {
      if (!known.includes(name)) return {error:"筛选字段「" + name + "」不在正式 Schema 定义中"};
      if (!supported.includes(name)) return {error:"接口 " + interfaceId + " 不接受筛选字段「" + name + "」；" + (supported.length ? "该接口可用字段：" + supported.join("、") : "该接口只按对象编号查询")};
      if (name === "product_ids") {
        if (!Array.isArray(value) || !value.length || !value.every(item => typeof item === "string" && item.trim()))
          return {error:"筛选字段「product_ids」需要是非空的字符串数组"};
        for (const item of value) parameters.append(name, item);
        continue;
      }
      if (typeof value !== "string" || !value.trim()) return {error:"筛选字段「" + name + "」需要是非空字符串"};
      if (["period_start", "period_end"].includes(name) && !/^\d{4}-\d{2}-\d{2}$/.test(value))
        return {error:"筛选字段「" + name + "」需要使用 YYYY-MM-DD 日期"};
      if (name === "currency" && !/^[A-Z]{3}$/.test(value)) return {error:"筛选字段「currency」需要使用三位大写币种代码"};
      if (name === "currency" && ["SI07", "SI08"].includes(interfaceId) && value !== "CNY")
        return {error:"筛选字段「currency」当前资料只有 CNY，不能换算其他币种"};
      if (name === "source_version" && !/^[0-9]+$/.test(value)) return {error:"筛选字段「source_version」需要使用数字版本号"};
      if (name === "ownership_type" && !["COMPANY", "CUSTOMER", "COOPERATION"].includes(value))
        return {error:"筛选字段「ownership_type」只能使用 COMPANY、CUSTOMER 或 COOPERATION"};
      if (value.length > 128) return {error:"筛选字段「" + name + "」长度超过 128"};
      parameters.append(name, value);
    }
    if (parameters.has("period_start") !== parameters.has("period_end")) return {error:"筛选字段「period_start」与「period_end」需要同时填写"};
    if (parameters.has("period_start") && String(parameters.get("period_start")) > String(parameters.get("period_end")))
      return {error:"筛选字段「period_end」需要不早于「period_start」"};
    return {route:"/api/boss/ui/simulation-inspect?" + parameters.toString()};
  }
  async function execute(route:string, at:string, expectedInterface:string) {
    const identity = epoch.current;
    const abort = new AbortController(); active.current = abort;
    setLoading(true); setError(""); setNotice("");
    let started: number | null = null;
    try {
      started = performance.now();
      const response = await fetch(route, {headers: {Authorization: "Bearer " + getToken()}, cache: "no-store", signal: abort.signal});
      if (!response.ok) throw Error("HTTP " + response.status + " · " + await response.text());
      const actual = await response.json() as Result;
      if (actual.source_type !== "SIMULATED" || actual.access !== "TECHNICAL_METADATA" || actual.interface_id !== expectedInterface ||
        actual.business_actions_performed !== false || actual.external_retrieval_performed !== false || actual.sources.length !== 0 ||
        actual.records.some(record => record.data !== null || record.content_state !== "METADATA_ONLY" ||
          record.business_authorization_granted !== false || record.source_refs.length !== 0)) throw Error("技术检查投影字段或范围无效");
      if (abort.signal.aborted || epoch.current !== identity) return;
      if(expectedContext&&(actual.execution_namespace!==expectedContext.namespace||actual.dataset_id!==expectedContext.datasetId||actual.dataset_version!==expectedContext.version))throw new Error("当前数据集或执行空间已经变化，请回到模拟中心刷新当前数据集与执行空间");
      const duration=performance.now()-started;
      setResult(actual);setElapsed(duration);
      onObservation?.({id:crypto.randomUUID(),request:route,at,elapsed_ms:duration,namespace:actual.execution_namespace,result:actual,error:null});
    } catch (failure) {
      if (abort.signal.aborted || epoch.current !== identity) return;
      const message = failure instanceof Error ? failure.message : String(failure);
      setResult(null); setElapsed(started === null ? null : performance.now() - started); setError(message);
      if(started!==null&&expectedContext)onObservation?.({id:crypto.randomUUID(),request:route,at,elapsed_ms:performance.now()-started,namespace:expectedContext.namespace,result:null,error:message});
    } finally {if (epoch.current === identity && !abort.signal.aborted) setLoading(false);}
  }
  function executeCheck(event?:FormEvent) {
    event?.preventDefault();
    if (loading) return;
    const built = buildRoute();
    if ("error" in built) { setFieldError(built.error); return; }
    setFieldError(""); setResult(null); setError(""); setNotice(""); setElapsed(null);
    const at = new Date().toISOString();
    setRequest(built.route); setRequestedAt(at);
    void execute(built.route, at, interfaceId);
  }
  function queryResult() {
    if (!request || loading) return;
    void execute(request, requestedAt || new Date().toISOString(), interfaceId);
  }
  function stopWaiting() {
    active.current?.abort();
    setLoading(false);
    setNotice("已停止等待本次结果；服务端读取可能已经完成，原请求地址保留，可以用“查询本次请求结果”再次读取。");
  }
  const supportedFields = SUPPORTED[interfaceId] ?? [];
  return <div className="boss-maintainer-records boss-simulation-inspect">
    <div className="boss-interface-columns">
    <aside className="boss-column">
      <V7Panel title="接口目录"><nav className="boss-interface-directory" aria-label="接口目录">
        {schema.$defs.Interface.enum.map(identifier=><button key={identifier} type="button" className="boss-btn" aria-current={interfaceId===identifier?"location":undefined} onClick={()=>selectInterface(identifier)}>{identifier} · {NAMES[identifier]}</button>)}
      </nav></V7Panel>
      <V7Panel title="接口摘要">
        <V7Fact label="当前接口">{interfaceId} · {NAMES[interfaceId]}</V7Fact>
        <V7Fact label="数据属性">SIMULATED · 技术元信息</V7Fact>
        <V7Fact label="权限范围">MAINTAINER · TECHNICAL_METADATA</V7Fact>
        <V7Fact label="接口方法">GET · 只读技术检查</V7Fact>
        <p className="boss-helper">切换接口只同步请求定义、实际响应与 Schema，不会执行接口。</p>
        <button type="button" className="boss-btn" onClick={onOpenTools}>查看关联工具</button>
        <p className="boss-helper">接口对应的工具版本与消费者在 A09 工具目录与版本详情中维护；本页只核对接口技术元信息。</p>
      </V7Panel>
    </aside>
    <div className="boss-column">
      <V7Tabs label="接口详情" value={section} onChange={focusSection} items={[{id:"request",title:"请求定义"},{id:"response",title:"实际响应"},{id:"schema",title:"Schema与映射"}]}/>
      <section className="boss-panel" aria-label="模拟接口请求定义">
        <div className="boss-panel-head"><h2>请求定义</h2><small>A02 · SIMULATED</small></div>
        <p>当前技术维护身份只检查对象标识、类别、版本和状态。本人正文、业务决定及外部调用不在此入口执行。</p>
        <V7Fact label="接口编号">{interfaceId} · {NAMES[interfaceId]}</V7Fact>
        <V7Fact label="目标执行空间">{expectedContext?expectedContext.namespace:"服务端当前执行空间（调用前不能预先确认）"}</V7Fact>
        <V7Fact label="检查属性">只读技术检查；不执行业务写入，也不替代任何写入接口的决定</V7Fact>
        <form ref={requestPanel} tabIndex={-1} className="boss-runtime-fields" onSubmit={executeCheck}>
          <label>对象编号（每行一个，可留空）<textarea aria-label="对象编号（每行一个，可留空）" rows={3} value={objectIds} onChange={event => {clear(); setObjectIds(event.target.value);}}/></label>
          <p className="boss-helper">对象编号在目标执行空间内解释；本入口不提供对象列表，需要填写该空间内的对象编号，留空表示不限制对象。</p>
          <button type="button" className="boss-btn" aria-expanded={advanced} onClick={()=>setAdvanced(!advanced)}>{advanced?"收起高级参数":"高级参数（筛选 JSON）"}</button>
          {advanced
            ?<label>筛选参数（JSON）<textarea aria-label="筛选参数（JSON）" rows={5} value={filters} onChange={event => {clear(); setFilters(event.target.value);}}/></label>
            :<p className="boss-helper">当前筛选：{filters.trim()==="{}"?"没有筛选条件":filters}</p>}
          <p className="boss-helper">接口 {interfaceId} 可用字段：{supportedFields.length?supportedFields.map(field=>field+"（"+(FILTER_LABELS[field]??"技术参数")+"）").join("、"):"没有筛选字段，只按对象编号查询"}。</p>
          {fieldError&&<p role="alert" className="boss-status boss-status-error">{fieldError}</p>}
          <div className="boss-actions"><button type="submit" className="boss-btn boss-btn-primary" disabled={loading}>{loading?"检查中…":"执行接口检查"}</button></div>
        </form>
      </section>
      <section ref={schemaPanel} tabIndex={-1} className="boss-panel" aria-label="Schema 与映射">
        <div className="boss-panel-head"><h2>Schema 与映射</h2><small>{schema.$id}</small></div>
        <p>请求与响应使用正式 Schema。输入只允许接口编号、对象编号与当前接口支持的筛选字段，输出只包含技术元信息。</p>
        <div className="boss-interface-schemas">
          <details><summary>Input Schema（请求字段）</summary>
            <div>{QUERY_FIELDS.map(row=><p key={row.name} className="boss-helper">{row.name}{row.required?"（必要）":""}：{row.type}</p>)}</div>
            <pre>{JSON.stringify(schema.$defs.Query,null,2)}</pre>
          </details>
          <details><summary>Output Schema（响应字段）</summary>
            <div>{RESULT_FIELDS.map(row=><p key={row.name} className="boss-helper">{row.name}{row.required?"（必要）":""}：{row.type}</p>)}</div>
            <pre>{JSON.stringify(schema.$defs.Result,null,2)}</pre>
          </details>
        </div>
        <details><summary>查看完整 Schema 与引用定义</summary><pre className="boss-v7-code">{JSON.stringify(schema,null,2)}</pre></details>
      </section>
    </div>
    <aside className="boss-column" aria-label="模拟接口实际响应">
      <section ref={responsePanel} tabIndex={-1} className="boss-panel">
        <div className="boss-panel-head"><h2>实际请求与结果</h2><small>实际响应</small></div>
        {loading && <div role="status" className="boss-status">正在读取当前模拟资料的技术元信息<button type="button" className="boss-btn" onClick={stopWaiting}>停止等待结果</button></div>}
        {!loading && !result && !error && !notice && <V7Empty title="尚未调用">没有已提交的请求记录；执行接口检查后显示真实响应。</V7Empty>}
        {error && <div role="alert" className="boss-status boss-status-error">{error}</div>}
        {notice && <div role="status" className="boss-status">{notice}</div>}
        {request && <><div className="boss-kv"><span>本次请求地址</span><strong>{request}</strong></div><div className="boss-kv"><span>请求发起时间</span><strong>{requestedAt}</strong></div></>}
        <div className="boss-actions"><button type="button" className="boss-btn" disabled={!request||loading} onClick={queryResult}>查询本次请求结果</button>{!request&&<span className="boss-helper">还没有已提交的请求：先执行接口检查。</span>}</div>
        {result && <>
          <p className="boss-helper">本次响应 {result.records.length} 项记录；缺少范围 {result.missing_fields.join("、")||"没有记录"}。</p>
          <div className="boss-kv"><span>当前数据集</span><strong>{result.dataset_id} · v{result.dataset_version}</strong></div>
          <div className="boss-kv"><span>实际执行空间</span><strong>{result.execution_namespace}</strong></div>
          <div className="boss-kv"><span>当前资料覆盖</span><strong>{result.availability}</strong></div>
          <div className="boss-kv"><span>业务资料时间</span><strong>{result.business_as_of ?? "当前没有可用时间"}</strong></div>
          <div className="boss-kv"><span>实际读取时间</span><strong>{result.read_at}</strong></div>
          {!result.records.length && <p>当前范围没有对象记录。</p>}
          {result.records.map(record => <div className="boss-panel" key={record.record_id}>
            <strong>{record.record_id}</strong><div className="boss-kv"><span>对象类别</span><strong>{record.entity_type}</strong></div>
            <div className="boss-kv"><span>当前版本</span><strong>{record.version ?? "没有版本记录"}</strong></div>
            <div className="boss-kv"><span>当前状态</span><strong>{record.state ?? "没有状态记录"}</strong></div>
            <div className="boss-kv"><span>正文</span><strong>不提供正文</strong></div>
          </div>)}
          <h3>当前缺少范围</h3><ul>{result.missing_fields.map(field => <li key={field}>{field}</li>)}</ul>
          <details><summary>查看实际响应 JSON</summary><pre>{JSON.stringify(result, null, 2)}</pre></details>
        </>}
      </section>
      <V7Panel title="来源与依据"><V7Fact label="资料属性">SIMULATED</V7Fact><V7Fact label="请求与响应">{loading?"请求处理中":result?"已收到实际响应":error?"请求失败":"尚未调用"}</V7Fact><V7Fact label="错误详情">{error||"没有已记录错误"}</V7Fact><V7Fact label="保存对象">此入口仅查询技术元信息</V7Fact><V7Fact label="响应对象">{result?`${result.records.length} 项`:"尚未取得响应"}</V7Fact><V7Fact label="请求耗时">{elapsed===null?"尚未取得实际耗时":`${elapsed.toFixed(1)} ms`}</V7Fact><V7Fact label="业务授权">没有授予业务授权</V7Fact><V7Fact label="当前 Schema">{schema.$id}</V7Fact></V7Panel>
    </aside>
    </div>
  </div>;
}
