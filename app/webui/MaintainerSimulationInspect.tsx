import { useEffect, useRef, useState, type FormEvent } from "react";
import { useClient } from "@/providers/ClientProvider";
import schema from "./simulation-query.schema.json";
import {V7Empty,V7Fact,V7Panel} from "./BossV7UI";

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
export type SimulationObservation={id:string;request:string;at:string;elapsed_ms:number;namespace:string;result:Result|null;error:string|null};
type InspectionContext={namespace:string;datasetId:string;version:string};

export function MaintainerSimulationInspect({onOpenTools,onObservation,expectedContext}: {onOpenTools: () => void;onObservation?:(value:SimulationObservation)=>void;expectedContext?:InspectionContext}) {
  const {client, getToken, token} = useClient();
  const [interfaceId, setInterfaceId] = useState("SI01");
  const [objectIds, setObjectIds] = useState("");
  const [filters, setFilters] = useState("{}");
  const [result, setResult] = useState<Result | null>(null);
  const [request, setRequest] = useState("");
  const [elapsed, setElapsed] = useState<number | null>(null);
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");
  const [loading, setLoading] = useState(false);
  const active = useRef<AbortController | null>(null);
  const epoch = useRef(0);
  const requestPanel=useRef<HTMLFormElement>(null),schemaPanel=useRef<HTMLDivElement>(null),responsePanel=useRef<HTMLElement>(null);
  const [section,setSection]=useState("interfaces");
  function focusSection(name:string){setSection(name);const target=name==="schema"?schemaPanel.current:name==="response"?responsePanel.current:requestPanel.current;target?.scrollIntoView({block:"start",behavior:"smooth"});target?.focus();}
  function clear() {
    epoch.current += 1; active.current?.abort();
    setResult(null); setRequest(""); setElapsed(null); setError(""); setNotice(""); setLoading(false);
  }
  useEffect(() => {
    clear(); setObjectIds(""); setFilters("{}"); setInterfaceId("SI01");
    return () => {epoch.current += 1; active.current?.abort();};
  }, [client, token]);

  async function inspect(event?: FormEvent) {
    event?.preventDefault(); clear();
    const identity = epoch.current;
    const abort = new AbortController(); active.current = abort;
    let started: number | null = null;
    let requestedRoute="";
    const observedAt=new Date().toISOString();
    setLoading(true);
    try {
      const parsed: unknown = JSON.parse(filters);
      if (parsed === null || typeof parsed !== "object" || Array.isArray(parsed)) throw Error("筛选参数必须是 JSON 对象");
      const parameters = new URLSearchParams({interface_id: interfaceId});
      for (const id of objectIds.split(/\r?\n/).map(value => value.trim()).filter(Boolean)) parameters.append("object_ids", id);
      for (const [name, value] of Object.entries(parsed)) {
        if (!Object.keys(schema.$defs.Query.properties.filters.properties).includes(name)) throw Error("当前 Schema 不支持此筛选字段");
        if (name === "product_ids") {
          if (!Array.isArray(value) || !value.length || !value.every(item => typeof item === "string"))
            throw Error("product_ids 必须是非空字符串数组");
          for (const item of value) parameters.append(name, item);
        } else if (typeof value === "string") parameters.append(name, value);
        else throw Error("当前筛选字段必须使用字符串");
      }
      const route = "/api/boss/ui/simulation-inspect?" + parameters.toString();
      requestedRoute=route;
      setRequest(route);
      started = performance.now();
      const response = await fetch(route, {headers: {Authorization: "Bearer " + getToken()}, cache: "no-store", signal: abort.signal});
      if (!response.ok) throw Error("HTTP " + response.status + " · " + await response.text());
      const actual = await response.json() as Result;
      if (actual.source_type !== "SIMULATED" || actual.access !== "TECHNICAL_METADATA" || actual.interface_id !== interfaceId ||
        actual.business_actions_performed !== false || actual.external_retrieval_performed !== false || actual.sources.length !== 0 ||
        actual.records.some(record => record.data !== null || record.content_state !== "METADATA_ONLY" ||
          record.business_authorization_granted !== false || record.source_refs.length !== 0)) throw Error("技术检查投影字段或范围无效");
      if (abort.signal.aborted || epoch.current !== identity) return;
      if(expectedContext&&(actual.execution_namespace!==expectedContext.namespace||actual.dataset_id!==expectedContext.datasetId||actual.dataset_version!==expectedContext.version))throw new Error("当前数据集或执行空间已经变化，请重新读取模拟中心");
      const duration=performance.now()-started;
      setResult(actual);setElapsed(duration);
      onObservation?.({id:crypto.randomUUID(),request:route,at:observedAt,elapsed_ms:duration,namespace:actual.execution_namespace,result:actual,error:null});
    } catch (failure) {
      if (abort.signal.aborted || epoch.current !== identity) return;
      setResult(null); setElapsed(started === null ? null : performance.now() - started);
      setError(failure instanceof Error ? failure.message : String(failure));
      if(started!==null&&expectedContext)onObservation?.({id:crypto.randomUUID(),request:requestedRoute,at:observedAt,elapsed_ms:performance.now()-started,namespace:expectedContext.namespace,result:null,error:failure instanceof Error?failure.message:String(failure)});
    } finally {if (epoch.current === identity && !abort.signal.aborted) setLoading(false);}
  }
  function cancel() {clear(); setNotice("已取消本次人工检查，业务状态保持当前内容。");}
  return <div className="boss-maintainer-records boss-simulation-inspect">
    <div className="boss-interface-columns">
    <aside className="boss-column"><V7Panel title="工具 / 接口目录"><nav className="boss-interface-directory" aria-label="接口目录区域">
      <button className="boss-btn" aria-current={section==="interfaces"?"location":undefined} onClick={()=>focusSection("interfaces")}>SI01—SI14 接口目录</button>
      <button className="boss-btn" aria-current={section==="request"?"location":undefined} onClick={()=>focusSection("request")}>请求定义</button>
      <button className="boss-btn" aria-current={section==="response"?"location":undefined} onClick={()=>focusSection("response")}>实际响应</button>
      <button className="boss-btn" onClick={onOpenTools}>工具映射</button>
      <button className="boss-btn" aria-current={section==="schema"?"location":undefined} onClick={()=>focusSection("schema")}>Schema 与映射</button>
    </nav><V7Fact label="当前接口">{interfaceId}</V7Fact><p>{NAMES[interfaceId]}</p><span className="boss-tag boss-tag-amber">SIMULATED</span></V7Panel></aside>
    <div className="boss-column">
      <section className="boss-panel" aria-label="模拟接口人工检查">
        <div className="boss-panel-head"><h2>Schema 与映射</h2><small>A02 · SIMULATED</small></div>
        <p>当前技术维护身份只检查对象标识、类别、版本和状态。本人正文、业务决定及外部调用不在此入口执行。</p>
        <div ref={schemaPanel} tabIndex={-1} className="boss-interface-schemas"><details open><summary>Input Schema</summary><pre>{JSON.stringify(schema.$defs.Query,null,2)}</pre></details><details open><summary>Output Schema</summary><pre>{JSON.stringify(schema.$defs.Result,null,2)}</pre></details></div>
        <details><summary>查看完整 Schema 与引用定义</summary><pre>{JSON.stringify(schema,null,2)}</pre></details>
        <form ref={requestPanel} tabIndex={-1} className="boss-runtime-fields" onSubmit={event => {void inspect(event);}}>
          <label>接口编号<select aria-label="接口编号" value={interfaceId} onChange={event => {clear(); setInterfaceId(event.target.value); setObjectIds(""); setFilters("{}");}}>
            {schema.$defs.Interface.enum.map(id => <option key={id} value={id}>{id} · {NAMES[id]}</option>)}
          </select></label>
          <label>对象编号（每行一个，可留空）<textarea aria-label="对象编号（每行一个，可留空）" rows={3} value={objectIds} onChange={event => {clear(); setObjectIds(event.target.value);}}/></label>
          <label>筛选参数（JSON）<textarea aria-label="筛选参数（JSON）" rows={5} value={filters} onChange={event => {clear(); setFilters(event.target.value);}}/></label>
          <V7Fact label="接口方法">GET /api/boss/ui/simulation-inspect</V7Fact><V7Fact label="权限范围">MAINTAINER · TECHNICAL_METADATA</V7Fact>
          <p>SI07/SI08支持完整期间、region_id、product_ids、legal_entity_id、customer_id、currency及source_version；SI13支持source_version。其他接口使用对象编号选择。</p>
          <div className="boss-actions"><button type="submit" className="boss-btn boss-btn-primary" disabled={loading}>人工检查</button>
            <button type="button" className="boss-btn" disabled={loading || !request} onClick={() => {void inspect();}}>重新查询</button>
            <button type="button" className="boss-btn" disabled={!loading} onClick={cancel}>取消检查</button>
            <button type="button" className="boss-btn" onClick={onOpenTools}>查看工具映射</button></div>
        </form>
      </section>
    </div>
    <aside className="boss-column" aria-label="模拟接口实际响应">
      <section ref={responsePanel} tabIndex={-1} className="boss-panel">
        <div className="boss-panel-head"><h2>实际请求与结果</h2></div>
        {loading && <div role="status" className="boss-status">正在读取当前模拟资料的技术元信息</div>}
        {!loading && !result && !error && !notice && <V7Empty title="尚未调用">没有实际请求记录，调用后显示接口的真实响应。</V7Empty>}
        {error && <div role="alert" className="boss-status boss-status-error">{error}</div>}
        {notice && <div role="status" className="boss-status">{notice}</div>}
        {request && <div className="boss-kv"><span>实际请求</span><strong>{request}</strong></div>}
        {result && <>
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
      <V7Panel title="来源与依据"><V7Fact label="资料属性">SIMULATED</V7Fact><V7Fact label="实际请求与响应">{loading?"请求处理中":result?"已收到实际响应":error?"请求失败":"尚未调用"}</V7Fact><V7Fact label="错误详情">{error||"没有已记录错误"}</V7Fact><V7Fact label="保存对象">此入口仅查询技术元信息</V7Fact><V7Fact label="响应对象">{result?`${result.records.length} 项`:"尚未取得响应"}</V7Fact><V7Fact label="请求耗时">{elapsed===null?"尚未取得实际耗时":`${elapsed.toFixed(1)} ms`}</V7Fact><V7Fact label="业务授权">没有授予业务授权</V7Fact><V7Fact label="当前 Schema">{schema.$id}</V7Fact></V7Panel>
    </aside>
    </div>
    <footer className="boss-maintainer-actions"><span>{interfaceId} · {NAMES[interfaceId]}</span><button className="boss-btn boss-btn-primary" disabled={loading} onClick={()=>void inspect()}>人工调用</button><button className="boss-btn" disabled={loading||!request} onClick={()=>void inspect()}>重新查询</button><button className="boss-btn" disabled={!loading} onClick={cancel}>取消检查</button><button className="boss-btn" onClick={onOpenTools}>查看映射</button></footer>
  </div>;
}
