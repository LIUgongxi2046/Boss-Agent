import { useCallback, useEffect, useRef, useState } from "react";
import { AlertCircle, Loader2, RefreshCw } from "lucide-react";
import { useClient } from "@/providers/ClientProvider";

type Method = {
  sop_id: string; name: string; requirement_id: string; version: string; content_sha256: string;
  enabled: boolean; native_available: boolean; missing_tools: string[]; context_eligible: boolean;
  missing_projections:string[];projection_references_resolved:boolean;
  read_operations: string[]; command_operations: string[]; human_only_operations: string[];
};
type Projection = {
  projection: "sop-technical-status"; items: Method[]; native_configuration_sha256: string;
  runtime_admission_ready: boolean; private_body_available_here: false; business_authorization_granted: false;
  pending_activations: {sop_id: string; client_request_id: string}[];
};

export function MaintainerSkills() {
  const {client, getToken, token} = useClient();
  const [data, setData] = useState<Projection | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");
  const active = useRef<AbortController | null>(null);
  const epoch = useRef(0);
  const read = useCallback(async () => {
    active.current?.abort();
    const abort = new AbortController(); active.current = abort;
    const identity = epoch.current;
    setData(null); setLoading(true); setError("");
    await fetch("/api/boss/ui/admin/skills", {
      headers: {Authorization: "Bearer " + getToken()}, cache: "no-store", signal: abort.signal,
    }).then(async response => {
      if (!response.ok) throw Error("方法技术状态读取失败（HTTP " + response.status + "）");
      const result = await response.json() as Projection;
      if (result.projection !== "sop-technical-status" || result.items.length !== 13 ||
        result.private_body_available_here !== false || result.business_authorization_granted !== false)
        throw Error("方法技术投影范围无效");
      return result;
    }).then(result => {
      if (abort.signal.aborted || epoch.current !== identity) return;
      setData(result); setLoading(false);
    }).then(undefined, failure => {
      if (abort.signal.aborted || epoch.current !== identity) return;
      setData(null); setLoading(false);
      setError(failure instanceof Error ? failure.message : String(failure));
    });
  }, [getToken]);
  useEffect(() => {
    epoch.current += 1;
    setData(null); setError("");
    void read();
    return () => {epoch.current += 1; active.current?.abort();};
  }, [client, token, read]);
  function unavailableReasons(item: Method) {
    const reasons: string[] = [];
    if (data?.pending_activations.length) reasons.push("存在待恢复的方法启用操作，当前全部新上下文暂停采用。");
    if (item.missing_tools.length) reasons.push("缺少尚未注册的工具：" + item.missing_tools.join("、"));
    if (item.missing_projections.length) reasons.push("缺少尚未获准的工作投影：" + item.missing_projections.join("、"));
    if (!item.native_available) reasons.push("当前原生方法文件不可用。");
    return reasons;
  }
  return <div>
    <section className="boss-panel" aria-label="秘书方法技术维护">
      <div className="boss-panel-head"><h2>方法技术状态</h2><small>A06 · 十三项原生方法的只读状态</small></div>
      <p>读取当前方法文件、版本、工具引用与工作投影。启用、停用和草稿操作在方法版本区完成，本区域只显示实际状态与缺少条件。</p>
      <button type="button" className="boss-btn" disabled={loading} onClick={() => {void read();}}>
        {loading ? <Loader2 size={15} className="boss-spin"/> : <RefreshCw size={15}/>} {loading ? "刷新中…" : "刷新方法技术状态"}
      </button>
      <div className="boss-kv"><span>当前 Runtime 可接收任务</span><strong>{data ? data.runtime_admission_ready ? "可以接收" : "需要检查当前运行配置" : "尚未读取"}</strong></div>
      {data && !data.runtime_admission_ready && <p className="boss-helper">Runtime 当前不能接收任务：服务未返回具体原因，需要到运行状态页核查运行配置。</p>}
      <p>方法正文编辑、草稿及历史恢复由方法版本区负责。当前状态读取和本地上下文检查没有验证模型质量。</p>
      {!!data?.pending_activations.length && <p role="status" className="boss-helper">存在待恢复的方法启用操作，请在方法版本区明确继续或取消。</p>}
    </section>
    {loading && <div role="status" className="boss-status">正在读取当前方法</div>}
    {error && <div role="alert" className="boss-status boss-status-error"><AlertCircle size={16}/>{error}</div>}
    {data && <div className="boss-columns"><div className="boss-column">
      {data.items.map(item => {
        const reasons = unavailableReasons(item);
        return <section key={item.sop_id} className="boss-panel" aria-label={"方法 " + item.sop_id}>
          <div className="boss-panel-head"><h2>{item.sop_id} · {item.name}</h2><small>{item.requirement_id} · v{item.version}</small></div>
          <div className="boss-kv"><span>当前状态</span><strong>{item.enabled ? "已经启用" : "已经停用"}</strong></div>
          <div className="boss-kv"><span>后续上下文采用条件</span><strong>{item.context_eligible ? "符合当前条件" : "当前不能采用"}</strong></div>
          <div className="boss-kv"><span>当前缺少条件</span><strong>{reasons.length ? reasons.join("；") : "没有缺少条件"}</strong></div>
          <div className="boss-kv"><span>内容 SHA256</span><strong>{item.content_sha256}</strong></div>
          <div className="boss-kv"><span>读取工具</span><strong>{item.read_operations.join("、") || "没有读取工具"}</strong></div>
          <div className="boss-kv"><span>动作工具</span><strong>{item.command_operations.join("、") || "没有动作工具"}</strong></div>
          <div className="boss-kv"><span>需要本人独立确认</span><strong>{item.human_only_operations.join("、") || "根据对应业务动作核查"}</strong></div>
          <div className="boss-kv"><span>尚未注册的工具</span><strong>{item.missing_tools.join("、") || "当前引用已经注册"}</strong></div>
          <div className="boss-kv"><span>尚未获准的工作投影</span><strong>{item.missing_projections.join("、") || "当前投影引用完整"}</strong></div>
          {!item.enabled && reasons.length > 0 && <p className="boss-helper">当前停用且存在缺少条件：需要先在方法版本区补齐依赖，才能启用此方法版本。</p>}
          {item.enabled && <p className="boss-helper">当前已启用；如需变更版本或停用，请到方法版本区操作。</p>}
        </section>;
      })}
    </div></div>}
  </div>;
}
