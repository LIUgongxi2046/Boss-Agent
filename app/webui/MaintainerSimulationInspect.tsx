import { useEffect, useRef, useState, type FormEvent } from "react";
import { useClient } from "@/providers/ClientProvider";
import schema from "./simulation-query.schema.json";

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

export function MaintainerSimulationInspect({onOpenTools}: {onOpenTools: () => void}) {
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
      setResult(actual); setElapsed(performance.now() - started);
    } catch (failure) {
      if (abort.signal.aborted || epoch.current !== identity) return;
      setResult(null); setElapsed(started === null ? null : performance.now() - started);
      setError(failure instanceof Error ? failure.message : String(failure));
    } finally {if (epoch.current === identity && !abort.signal.aborted) setLoading(false);}
  }
  function cancel() {clear(); setNotice("已取消本次人工检查，业务状态保持当前内容。");}
  return <div className="boss-columns boss-simulation-inspect">
    <div className="boss-column">
      <section className="boss-panel" aria-label="模拟接口人工检查">
        <div className="boss-panel-head"><h2>SI01—SI14 接口目录</h2><small>A02 · SIMULATED</small></div>
        <p>当前技术维护身份只检查对象标识、类别、版本和状态。本人正文、业务决定及外部调用不在此入口执行。</p>
        <div className="boss-kv"><span>当前 Schema</span><strong>{schema.$id}</strong></div>
        <form className="boss-runtime-fields" onSubmit={event => {void inspect(event);}}>
          <label>接口编号<select aria-label="接口编号" value={interfaceId} onChange={event => {clear(); setInterfaceId(event.target.value); setObjectIds(""); setFilters("{}");}}>
            {schema.$defs.Interface.enum.map(id => <option key={id} value={id}>{id} · {NAMES[id]}</option>)}
          </select></label>
          <label>对象编号（每行一个，可留空）<textarea aria-label="对象编号（每行一个，可留空）" rows={3} value={objectIds} onChange={event => {clear(); setObjectIds(event.target.value);}}/></label>
          <label>筛选参数（JSON）<textarea aria-label="筛选参数（JSON）" rows={5} value={filters} onChange={event => {clear(); setFilters(event.target.value);}}/></label>
          <p>SI07/SI08支持完整期间、region_id、product_ids、legal_entity_id、customer_id、currency及source_version；SI13支持source_version。其他接口使用对象编号选择。</p>
          <div className="boss-actions"><button type="submit" className="boss-btn boss-btn-primary" disabled={loading}>人工检查</button>
            <button type="button" className="boss-btn" disabled={loading || !request} onClick={() => {void inspect();}}>重新查询</button>
            <button type="button" className="boss-btn" disabled={!loading} onClick={cancel}>取消检查</button>
            <button type="button" className="boss-btn" onClick={onOpenTools}>查看工具映射</button></div>
        </form>
        <details><summary>Input Schema</summary><pre>{JSON.stringify(schema.$defs.Query, null, 2)}</pre></details>
        <details><summary>Output Schema</summary><pre>{JSON.stringify(schema, null, 2)}</pre></details>
      </section>
    </div>
    <aside className="boss-column" aria-label="模拟接口实际响应">
      <section className="boss-panel">
        <div className="boss-panel-head"><h2>实际响应</h2><small>TECHNICAL_METADATA</small></div>
        {loading && <div role="status" className="boss-status">正在读取当前模拟资料的技术元信息</div>}
        {!loading && !result && !error && !notice && <div role="status" className="boss-status">接口未调用</div>}
        {error && <div role="alert" className="boss-status boss-status-error">{error}</div>}
        {notice && <div role="status" className="boss-status">{notice}</div>}
        {request && <div className="boss-kv"><span>实际请求</span><strong>{request}</strong></div>}
        {elapsed !== null && <div className="boss-kv"><span>请求耗时</span><strong>{elapsed.toFixed(1)} ms</strong></div>}
        {result && <>
          <div className="boss-kv"><span>资料来源</span><strong>{result.source_type}</strong></div>
          <div className="boss-kv"><span>当前数据集</span><strong>{result.dataset_id} · v{result.dataset_version}</strong></div>
          <div className="boss-kv"><span>实际执行空间</span><strong>{result.execution_namespace}</strong></div>
          <div className="boss-kv"><span>当前资料覆盖</span><strong>{result.availability}</strong></div>
          <div className="boss-kv"><span>业务资料时间</span><strong>{result.business_as_of ?? "当前没有可用时间"}</strong></div>
          <div className="boss-kv"><span>实际读取时间</span><strong>{result.read_at}</strong></div>
          <div className="boss-kv"><span>业务授权</span><strong>没有授予业务授权</strong></div>
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
    </aside>
  </div>;
}
