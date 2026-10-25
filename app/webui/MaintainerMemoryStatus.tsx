import { useEffect, useRef, useState, type ReactNode } from "react";
import { AlertCircle, FileSearch, Loader2, ShieldCheck, Square } from "lucide-react";

type Selection = {
  run_id: string; memory_version: string; eligible: boolean; selected_at: string;
  run_status: string; model_completion_observed: boolean; matches_current_memory_version: boolean;
  observation: "CONTEXT_SELECTION_RECORDED";
};
type MemoryStatus = {
  projection: "memory-technical-status"; source_type: "RUNTIME_RECORD"; namespace: string; checked_at: string;
  owner_scope: {owner_id: string; dataset_id: string; dataset_version: string}; memory_source_type: string;
  memory: {memory_id: string; version: string; confirmation_state: string; valid_until: string | null};
  future_context_eligible: boolean; confirmation_authority_checked: true; next_context_memory_version: string | null;
  latest_context_selection: Selection | null; context_selection_count: number;
  future_turn_policy: "CURRENT_CONFIRMATION_REQUIRED"; deletion_propagation: string; derived_memory_index: "NOT_USED";
  deletion_scopes: {current_memory_content: string; initial_approved_source: string; loaded_sessions: string; backups: string; physical_erasure: string};
  model_adoption_verified: false; physical_secure_erasure_verified: false;
  private_body_available_here: false; owner_content_mutation_allowed: false;
};
type Props = {
  getToken: () => string;
  onNavigate: (page: "A14" | "A15", reference?: {run_id: string}) => void;
};
function Detail({label, children}: {label: string; children?: ReactNode}) {
  return <div className="boss-kv"><span>{label}</span><strong>{children ?? "尚未检查"}</strong></div>;
}

export function MaintainerMemoryStatus({getToken, onNavigate}: Props) {
  const [data, setData] = useState<MemoryStatus | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");
  const [diagnostics, setDiagnostics] = useState(false);
  const active = useRef<AbortController | null>(null);
  useEffect(() => {
    setData(null); setError(""); setNotice(""); setLoading(false); setDiagnostics(false);
    return () => active.current?.abort();
  }, [getToken]);

  function read() {
    active.current?.abort();
    const abort = new AbortController(); active.current = abort;
    setData(null); setLoading(true); setError(""); setNotice("");
    const token = getToken();
    if (!token) {setLoading(false); setError("技术维护身份已失效，请重新登录"); return;}
    void fetch("/api/boss/ui/admin/memory-status", {
      headers: {Authorization: "Bearer " + token}, signal: abort.signal, cache: "no-store",
    }).then(async response => {
      if (!response.ok) throw Error("记忆技术状态读取失败（HTTP " + response.status + "）");
      const result = await response.json() as MemoryStatus;
      if (result.projection !== "memory-technical-status" || result.source_type !== "RUNTIME_RECORD" ||
        result.private_body_available_here !== false || result.owner_content_mutation_allowed !== false ||
        result.confirmation_authority_checked !== true || !result.owner_scope || !result.deletion_scopes ||
        !Number.isInteger(result.context_selection_count)) throw Error("记忆技术投影字段或访问范围无效");
      return result;
    }).then(result => {
      if (abort.signal.aborted) return;
      setData(result); setLoading(false);
    }).then(undefined, failure => {
      if (abort.signal.aborted) return;
      setData(null); setLoading(false); setDiagnostics(true);
      setError(failure instanceof Error ? failure.message : String(failure));
    });
  }
  function cancel() {
    active.current?.abort(); setLoading(false); setNotice("已取消本次技术状态读取，记忆内容保持当前状态");
  }
  const selection = data?.latest_context_selection;
  return <>
    <section className="boss-panel" aria-label="记忆技术状态查询">
      <div className="boss-panel-head"><h2>记忆技术维护</h2><small>RUNTIME_RECORD · 只读技术状态</small></div>
      <div className="boss-actions">
        <button type="button" className="boss-btn boss-btn-primary" disabled={loading} onClick={read}>
          <FileSearch size={16}/>检查技术状态</button>
        <button type="button" className="boss-btn" disabled={!loading} onClick={cancel}><Square size={16}/>取消查询</button>
        <button type="button" className="boss-btn" onClick={() => onNavigate("A14")}>查看获准记录</button>
        <button type="button" className="boss-btn" onClick={() => setDiagnostics(true)}>定位保存或索引失败</button>
      </div>
    </section>
    {loading && <div className="boss-status" role="status"><Loader2 size={16} className="boss-spin"/>正在读取当前确认与删除传播状态</div>}
    {error && <div className="boss-status boss-status-error" role="alert"><AlertCircle size={16}/>{error}</div>}
    {notice && <div className="boss-status" role="status">{notice}</div>}
    {!data && !loading && !error && <div className="boss-status" role="status">技术状态待查询</div>}
    <div className="boss-columns">
      <div className="boss-column">
        <section className="boss-panel" aria-label="当前记忆确认">
          <div className="boss-panel-head"><h2>当前记忆与确认</h2><small>本人范围与当前版本</small></div>
          <Detail label="老板范围">{data?.owner_scope.owner_id}</Detail>
          <Detail label="执行空间">{data?.namespace}</Detail>
          <Detail label="数据集及版本">{data ? `${data.owner_scope.dataset_id} · v${data.owner_scope.dataset_version}` : null}</Detail>
          <Detail label="记忆来源类型">{data?.memory_source_type}</Detail>
          <Detail label="记忆标识">{data?.memory.memory_id}</Detail>
          <Detail label="当前记忆版本">{data?.memory.version}</Detail>
          <Detail label="本人确认状态">{data?.memory.confirmation_state}</Detail>
          <Detail label="有效期限">{data ? data.memory.valid_until ?? "未知" : null}</Detail>
          <Detail label="当前确认权限检查">{data ? "已经检查" : null}</Detail>
          <Detail label="当前采用条件">{data ? data.future_context_eligible ? "符合当前确认条件" : "停止采用" : null}</Detail>
          <Detail label="新任务可采用版本">{data ? data.next_context_memory_version ?? "没有可采用版本" : null}</Detail>
          <Detail label="最近检查时间">{data?.checked_at}</Detail>
          <div className="boss-status"><ShieldCheck size={16}/>本人内容的确认、修改和删除在老板入口完成。当前页面只读取技术元信息。</div>
        </section>
        <section className="boss-panel" aria-label="删除传播范围">
          <div className="boss-panel-head"><h2>删除传播与索引</h2><small>各项范围独立核查</small></div>
          <Detail label="当前删除传播状态">{data?.deletion_propagation}</Detail>
          <Detail label="当前记忆内容">{data?.deletion_scopes.current_memory_content}</Detail>
          <Detail label="派生记忆索引">{data ? "未使用派生索引" : null}</Detail>
          <Detail label="原始获准来源">{data?.deletion_scopes.initial_approved_source}</Detail>
          <Detail label="已载入历史会话">{data ? "尚未验证清理" : null}</Detail>
          <Detail label="备份传播">{data ? "尚未验证清理" : null}</Detail>
          <Detail label="物理安全擦除">{data ? "尚未验证" : null}</Detail>
          <Detail label="正文访问">不提供正文</Detail>
          <Detail label="维护修改能力">不允许修改本人内容</Detail>
        </section>
      </div>
      <aside className="boss-column" aria-label="新会话与技术核查">
        <section className="boss-panel">
          <div className="boss-panel-head"><h2>新会话与实际选择记录</h2><small>当前条件及历史观察分别显示</small></div>
          <Detail label="当前选择规则">{data?.future_turn_policy}</Detail>
          <Detail label="已记录选择次数">{data?.context_selection_count}</Detail>
          {data && !selection && <p>没有已经记录的上下文选择，模型采用状态尚未验证。</p>}
          {selection && <>
            <Detail label="最近 run_id">{selection.run_id}</Detail>
            <Detail label="该次记忆版本">{selection.memory_version}</Detail>
            <Detail label="该次选择结果">{selection.eligible ? "该次符合选择条件" : "该次停止采用"}</Detail>
            <Detail label="该次选择时间">{selection.selected_at}</Detail>
            <Detail label="该次运行状态">{selection.run_status}</Detail>
            <Detail label="与当前记忆版本一致">{selection.matches_current_memory_version ? "版本一致" : "版本已经变化"}</Detail>
            <Detail label="该次模型完成观察">{selection.model_completion_observed ? "已经观察" : "尚未观察"}</Detail>
            <button type="button" className="boss-btn" onClick={() => onNavigate("A15", {run_id: selection.run_id})}>查看关联运行记录</button>
          </>}
          <Detail label="当前模型遵从验证">{data ? "本次技术读取没有执行模型验证" : null}</Detail>
          {data && !data.future_context_eligible && selection?.eligible && <div className="boss-status boss-status-warn">
            <AlertCircle size={16}/>当前确认条件已经停止后续采用；上方记录保留当次上下文选择结果。</div>}
        </section>
        {diagnostics && <section className="boss-panel" aria-label="保存或索引失败定位">
          <div className="boss-panel-head"><h2>保存或索引失败定位</h2><small>获准技术信息</small></div>
          <Detail label="当前状态读取">{error ? "读取失败" : loading ? "正在读取" : data ? "读取成功" : "尚未检查"}</Detail>
          <Detail label="实际读取错误">{error || "没有本次读取错误记录"}</Detail>
          <Detail label="独立保存故障记录">未知</Detail>
          <Detail label="派生索引故障">{data ? "当前未使用派生记忆索引" : null}</Detail>
          <p>保存及历史索引故障需要查询获准动作记录和运行记录。当前读取没有修改记忆或执行索引任务。</p>
          <div className="boss-actions"><button type="button" className="boss-btn" onClick={() => onNavigate("A14")}>查看获准动作记录</button>
            <button type="button" className="boss-btn" onClick={() => onNavigate("A15")}>查看运行记录</button></div>
        </section>}
      </aside>
    </div>
  </>;
}
