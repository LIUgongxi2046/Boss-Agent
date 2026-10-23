import {
  useCallback, useEffect, useMemo, useRef, useState,
  type FormEvent, type ReactNode,
} from "react";
import {
  Activity, AlertCircle, ArrowLeft, ArrowRight, Bell, CalendarDays,
  ChartNoAxesCombined, CheckCircle2, ChevronRight, ClipboardCheck,
  Clock3, Database, FileSearch, FolderOpen, LayoutDashboard, Loader2,
  Menu, MessageCircle, RefreshCw, Search, Send, Settings,
  ShieldCheck, X,
} from "lucide-react";
import pageMeta from "./page-meta.json";
import { BossAssignmentFlow, MaintainerFeedback, type TaskListResponse, type MaintenanceTaskRef } from "./BossAssignmentFlow";
import { BossWorkspaceView, WORKSPACE_PAGE_ROUTES } from "./BossWorkspaceView";
import { BossSectorView, SECTOR_PAGE_IDS } from "./BossSectorView";
import { BossAssignmentPicker, DEFAULT_ASSIGNMENT_DRAFT, type AssignmentDraft } from "./BossAssignmentPicker";
import { BossVoiceAssignment } from "./BossVoiceAssignment";
import { BossMeetingApprovalView, MaintainerApplicationSeed } from "./BossMeetingApproval";
import { BossMeetingBrief } from "./BossMeetingBrief";
import { MaintainerPromptVersion } from "./MaintainerPromptVersion";
import { BossResearchView } from "./BossResearchView";
import { BossCommunicationCalendar } from "./BossCommunicationCalendar";
import { MaintainerMessageReply } from "./MaintainerMessageReply";
import { MaintainerKnowledgeEditor } from "./MaintainerKnowledgeEditor";
import "./boss-v6.css";

type Role = "BOSS" | "MAINTAINER";
type DesignPage = {
  title: string; summary: string; technical: boolean; module: string;
  filters: string[]; fields: string[]; sections: string[];
  actions: string[]; right: string[]; initial_state: string; kind: string;
};
type Task = {
  task_id: string; status: string; version?: string; purpose?: string;
  coordinator_id?: string; due_at?: string; evidence_requirements?: string[];
  source_refs?: string[];
};
type HistoricalTask = { task_id: string; status: string; due_at?: string; evidence_requirements?: string[] };
type Dashboard = {
  source_type: "SIMULATED"; namespace: string; dataset_version: string;
  business_clock: string; refreshed_at: string;
  profile: { timezone: string; goals: string[]; reading_requirement: string };
  source_coverage: { region: string; trade_scope: string; periods: Record<string, string[]> };
  tasks: Task[]; historical_commitment: HistoricalTask | null;
  meeting: { meeting_id: string; starts_at: string; timezone: string; participant_ids: string[]; material_ids: string[] } | null;
  contacts: { contact_id: string; name: string; organization: string; responsibility: string }[];
  event?: { event_id: string; status: string };
  assignment_source_ids?: string[];
  notifications: { event_id: string; state: string }[];
};
type Metrics = {
  source_type: "SIMULATED";
  result: {
    query_id: string;
    values: { metric_id: string; period_scope: string; value: string | null; unit: string; formula: string; definition_version: string }[];
    sources: { source_id: string; source_type: string; coverage?: string; business_as_of?: string }[];
    missing_fields: string[]; unexplained_causes: string[];
  };
};
type Tasks = TaskListResponse & { historical_commitment: HistoricalTask | null; source_type: string };
type Meetings = {
  source_type: string;
  meeting: Dashboard["meeting"];
  documents: { source_id: string; version: string; published_at: string; source_type: string }[];
};
type Evidence = { source_id: string; source_type: string; version: string; content: string; published_at?: string; author_contact_id?: string };
type Maintenance = { configured_provider: string; configured_model: string; configuration_version: string; source_type: string; status: string; counts: Record<string, number>; task_refs?: MaintenanceTaskRef[] };
type ModelHealth = {
  source_type: string; provider: string; data_source: string;
  observed_request_count: number; observed_response_count: number;
  runtime_response_observed: boolean;
  latest_response: {
    response_id: string; at: string | null;
    model: string | null; finish_reasons: string[];
  } | null;
  reported_usage: {
    prompt_tokens: number | null;
    completion_tokens: number | null;
    total_tokens: number | null;
  } | null;
  cost_total: null;
  business_task_completed: false;
  tool_event_count?: number;
  observed_error_count?: number;
};
type Identity = { role: Role | null; owner_id: string | null };
type Animation = "idle" | "thinking" | "complete" | "notice";

type Props = {
  getToken: () => string;
  onLogout: () => void;
  onStartChat: (content: string) => Promise<boolean | void>;
  children: ReactNode;
};

const pages = pageMeta as Record<string, DesignPage>;
const BOSS_NAV = [
  ["F01", "今日工作", LayoutDashboard],
  ["N02", "聊天交办", MessageCircle],
  ["N03", "经营关注", ChartNoAxesCombined],
  ["N04", "会议与资料", CalendarDays],
  ["N05", "任务与承诺", ClipboardCheck],
  ["N06", "通知与设置", Bell],
] as const;
const MAINT_NAV = [
  ["A01", "档案与访问", ShieldCheck],
  ["A02", "接口目录", Database],
  ["A03", "数据集", FolderOpen],
  ["A04", "场景与事件", Activity],
  ["A05", "Prompt 版本", FileSearch],
  ["A06", "SOP 与 Skills", ClipboardCheck],
  ["A07", "Knowledge Base", FolderOpen],
  ["A08", "模型连接", Settings],
  ["A09", "Tools 与连接", Settings],
  ["A10", "指标与规则", ChartNoAxesCombined],
  ["A11", "关联对象", ClipboardCheck],
  ["A12", "记忆技术维护", Database],
  ["A13", "调度计划", Clock3],
  ["A14", "动作授权记录", ShieldCheck],
  ["A15", "运行记录", Activity],
  ["A16", "评测管理", ClipboardCheck],
] as const;
const PRODUCT_PAGES = new Set<string>([
  "F01", "N02", "N03", "F03", "N04", "N05", "F05", "F06", "F07", "F08", "F12", "D01", "F24", "D03", "A04", "A05", "A06", "A08", "A15", "F30", "N12",
  ...Object.keys(WORKSPACE_PAGE_ROUTES), ...SECTOR_PAGE_IDS,
]);
const ANIMATIONS: Record<Animation, string> = {
  idle: "/boss-brand/01-待机悬浮.webp",
  thinking: "/boss-brand/03-思考分析.webp",
  complete: "/boss-brand/05-完成确认.webp",
  notice: "/boss-brand/06-通知提醒.webp",
};
const LABELS: Record<string, string> = {
  sales_quantity: "外销数量", revenue: "营业收入", cost: "经营成本",
  gross_profit: "毛利", gross_margin: "毛利率", gross_profit_per_tonne: "单吨毛利",
};
function allowed(page: string, role: Role) {
  if (page === "NATIVE") return true;
  if (!pages[page]) return false;
  if (["N01", "D08"].includes(page)) return false; // handled by original nanobot AuthForm
  if (["D06", "D07"].includes(page)) return true;
  return pages[page].technical ? role === "MAINTAINER" : role === "BOSS";
}
function initialPage(role: Role): string {
  const selected = new URLSearchParams(window.location.search).get("bossPage") || "";
  return allowed(selected, role) ? selected : role === "BOSS" ? "F01" : "A08";
}
async function jsonRequest<T>(path: string, getToken: () => string, signal?: AbortSignal): Promise<T> {
  const token = getToken();
  if (!token) throw new Error("身份令牌未就绪，请重新认证");
  const response = await fetch(path, {
    method: "GET",
    headers: { Authorization: "Bearer " + token },
    cache: "no-store",
    signal,
  });
  const raw = await response.text();
  let payload: unknown;
  try { payload = JSON.parse(raw); } catch { payload = null; }
  if (!response.ok) {
    const body = payload as { error?: string } | null;
    throw new Error((body && body.error ? body.error : "请求失败") + "（HTTP " + response.status + "）");
  }
  if (payload === null) throw new Error("业务接口返回格式错误");
  return payload as T;
}
function Value({ label, value }: { label: string; value?: ReactNode }) {
  return <div className="boss-kv"><span>{label}</span><strong>{value ?? "尚未读取"}</strong></div>;
}
function Panel({ title, note, children, className = "" }: {
  title: string; note?: string; children: ReactNode; className?: string;
}) {
  return <section className={"boss-panel " + className}>
    <div className="boss-panel-head"><h2>{title}</h2>{note ? <small>{note}</small> : null}</div>
    {children}
  </section>;
}
function Tag({ children, tone = "blue" }: { children: ReactNode; tone?: "blue" | "green" | "amber" | "muted" }) {
  return <span className={"boss-tag boss-tag-" + tone}>{children}</span>;
}
function Quiet({ message }: { message: string }) {
  return <div className="boss-empty"><FolderOpen size={22} aria-hidden="true" />
    <div><strong>暂无可核查记录</strong><p>{message}</p></div>
  </div>;
}
function waitText(value?: string | null) { return value === undefined || value === null || value === "" ? "待核查" : value; }
function localTime(value?: string) {
  if (!value) return "待核查";
  // Keep the original business-local timezone/offset visible. Never silently use host time.
  return value.replace("T", " ").replace(/\+08:00$/, "（北京时间）");
}
function GlassButton({ children, onClick, primary = false, disabled = false }: {
  children: ReactNode; onClick: () => void; primary?: boolean; disabled?: boolean;
}) {
  return <button type="button" onClick={onClick} disabled={disabled}
    className={"boss-btn " + (primary ? "boss-btn-primary" : "")}>{children}</button>;
}
function StatusLine({ text, variant = "info" }: { text: string; variant?: "info" | "error" | "warn" | "ok" }) {
  return <div className={"boss-status boss-status-" + variant} role="status">
    {variant === "error" ? <AlertCircle size={16} /> : variant === "ok" ? <CheckCircle2 size={16} /> : <Clock3 size={16} />}
    <span>{text}</span>
  </div>;
}

export function BossDesktop({ getToken, onLogout, onStartChat, children }: Props) {
  const [role, setRole] = useState<Role | null>(null);
  const [authError, setAuthError] = useState("");
  const [authAttempt, setAuthAttempt] = useState(0);
  const [page, setPage] = useState("F01");
  const [previousPage, setPreviousPage] = useState("F01");
  const [sidebarOpen, setSidebarOpen] = useState(true);
  const [directoryOpen, setDirectoryOpen] = useState(false);
  const [pageFilter, setPageFilter] = useState("");
  const [dateFilter, setDateFilter] = useState("");
  const [question, setQuestion] = useState("");
  const [assignmentDraft, setAssignmentDraft] = useState<AssignmentDraft>(DEFAULT_ASSIGNMENT_DRAFT);
  const [assignmentDirty, setAssignmentDirty] = useState(false);
  const [pendingNavigation, setPendingNavigation] = useState<{id:string;focus:string}|null>(null);
  const updateAssignmentDraft = useCallback((field:keyof AssignmentDraft,value:string)=>{
    setAssignmentDraft(old=>({...old,[field]:value}));
    setAssignmentDirty(true);
  }, []);
  const [productScope, setProductScope] = useState("product-1,product-2");
  const [selectedTaskId, setSelectedTaskId] = useState("");
  const [draftToReview, setDraftToReview] = useState("");
  const [sourceId, setSourceId] = useState("finance-note");
  const [sourceAnchor, setSourceAnchor] = useState<{
    source_id:string;version:string;start:number;end:number;
  }|null>(null);
  const [dashboard, setDashboard] = useState<Dashboard | null>(null);
  const [metrics, setMetrics] = useState<Metrics | null>(null);
  const [tasks, setTasks] = useState<Tasks | null>(null);
  const [meetings, setMeetings] = useState<Meetings | null>(null);
  const [evidence, setEvidence] = useState<Evidence | null>(null);
  const [maintenance, setMaintenance] = useState<Maintenance | null>(null);
  const [modelHealth, setModelHealth] = useState<ModelHealth | null>(null);
  const [loading, setLoading] = useState(false);
  const [querying, setQuerying] = useState(false);
  const [error, setError] = useState("");
  const [inputError, setInputError] = useState("");
  const [animate, setAnimate] = useState<Animation>("idle");
  const nextRequest = useRef(0);
  const [requestVersion, setRequestVersion] = useState(0);
  const [metricsRequest, setMetricsRequest] = useState(0);
  const draftRef = useRef<HTMLTextAreaElement | null>(null);
  const [originFocus, setOriginFocus] = useState("");

  useEffect(() => {
    const abort = new AbortController();
    jsonRequest<Identity>("/api/boss/identity", getToken, abort.signal)
      .then((identity) => {
        if (abort.signal.aborted) return;
        if (identity.role !== "BOSS" && identity.role !== "MAINTAINER") throw new Error("当前身份无法进入工作区");
        setRole(identity.role);
        setPage(initialPage(identity.role));
        setAuthError("");
      })
      .catch((err: unknown) => { if (!abort.signal.aborted) setAuthError(String(err instanceof Error ? err.message : err)); });
    return () => abort.abort();
  }, [getToken, authAttempt]);

  const navigate = useCallback((id: string, focus = "", bypassDirty = false) => {
    if (!role || !allowed(id, role)) return;
    if (!bypassDirty && page === "F06" && assignmentDirty &&
        id !== page && !["D04","D05","D01"].includes(id)) {
      setPendingNavigation({id,focus});
      return;
    }
    if (id !== page) setPreviousPage(page);
    if (focus) setOriginFocus(focus);
    const url = new URL(window.location.href);
    url.searchParams.set("bossPage", id);
    window.history.pushState({}, "", url);
    setPage(id);
    setError("");
    setDirectoryOpen(false);
  }, [page, role, assignmentDirty]);

  useEffect(() => {
    if (!pendingNavigation) return;
    const onEscape = (event: KeyboardEvent) => {
      if (event.key === "Escape") setPendingNavigation(null);
    };
    window.addEventListener("keydown", onEscape);
    return () => window.removeEventListener("keydown", onEscape);
  }, [pendingNavigation]);

  useEffect(() => {
    const onBack = () => {
      if (!role) return;
      const selected = initialPage(role);
      setPage(selected);
    };
    window.addEventListener("popstate", onBack);
    return () => window.removeEventListener("popstate", onBack);
  }, [role]);

  useEffect(() => {
    if (!role || page === "NATIVE") return;
    const id = ++nextRequest.current;
    const abort = new AbortController();
    const tasksToRead: Promise<void>[] = [];
    const read = <T,>(url: string, set: (v: T) => void) => {
      tasksToRead.push(jsonRequest<T>(url, getToken, abort.signal).then((value) => {
        if (id === nextRequest.current) set(value);
      }));
    };
    if (role === "BOSS") {
      if (["F01", "F06", "D04", "D05", "N03", "N06", "N07", "N09"].includes(page)) read<Dashboard>("/api/boss/ui/dashboard", setDashboard);
      if (["N05", "F06"].includes(page)) read<Tasks>("/api/boss/ui/tasks", setTasks);
      if (["N04", "F04"].includes(page)) read<Meetings>("/api/boss/ui/meetings", setMeetings);
      if (["F24", "D03"].includes(page)) read<ModelHealth>("/api/boss/ui/model-health", setModelHealth);
      if (page === "D01") read<Evidence>("/api/boss/ui/evidence?source=" + encodeURIComponent(sourceId), setEvidence);
    } else if (["A04", "A08", "N12", "A01", "A15", "F30"].includes(page)) {
      read<Maintenance>("/api/boss/ui/maintenance", setMaintenance);
      if (["A15", "F30"].includes(page)) read<ModelHealth>("/api/boss/ui/model-usage", setModelHealth);
    }
    if (tasksToRead.length === 0) { setLoading(false); return () => abort.abort(); }
    setLoading(true);
    setError("");
    setAnimate("thinking");
    void Promise.all(tasksToRead).then(() => {
      if (id !== nextRequest.current) return;
      setLoading(false);
      setAnimate("complete");
    }).catch((err: unknown) => {
      if (abort.signal.aborted || id !== nextRequest.current) return;
      setLoading(false); setError(String(err instanceof Error ? err.message : err)); setAnimate("notice");
    });
    return () => abort.abort();
  }, [role, page, sourceId, requestVersion, getToken]);

  useEffect(() => {
    if (role !== "BOSS" || !["F03", "N03"].includes(page)) return;
    if (metricsRequest === 0) return;
    const abort = new AbortController();
    setQuerying(true);
    setError("");
    const url = "/api/boss/ui/metrics?products=" + encodeURIComponent(productScope);
    void jsonRequest<Metrics>(url, getToken, abort.signal).then((value) => {
      if (abort.signal.aborted) return;
      setMetrics(value); setQuerying(false); setAnimate("complete");
    }).catch((err: unknown) => {
      if (abort.signal.aborted) return;
      setQuerying(false); setError(String(err instanceof Error ? err.message : err));
    });
    return () => abort.abort();
  }, [role, page, metricsRequest, getToken]);

  const userNav = role === "MAINTAINER" ? MAINT_NAV : BOSS_NAV;
  const metadata = pages[page];
  const isNative = page === "NATIVE";
  const searchablePages = useMemo(() => {
    return Object.entries(pages).filter(([id, p]) => role && allowed(id, role) &&
      (id.toLowerCase().includes(pageFilter.toLowerCase()) ||
       p.title.includes(pageFilter) || p.module.includes(pageFilter)));
  }, [pageFilter, role]);
  const refresh = () => setRequestVersion((v) => v + 1);
  const goSource = (id = "finance-note", anchor?:{
    version:string;start:number;end:number;
  }) => {
    setSourceId(id);
    setSourceAnchor(anchor?{source_id:id,...anchor}:null);
    navigate("D01", page);
  };
  const selectTask = (id: string) => { setSelectedTaskId(id); navigate("F06", page); };
  const sendQuestion = async (event: FormEvent) => {
    event.preventDefault();
    if (!question.trim()) {
      setInputError("请填写要交给大鹏的具体需求。");
      draftRef.current?.focus();
      return;
    }
    setInputError("");
    setAnimate("thinking");
    try {
      const accepted = await onStartChat(question.trim());
      if (accepted === false) throw new Error("原生会话未能创建，请重试。");
      setQuestion("");
      navigate("NATIVE");
    } catch (err) {
      setInputError(err instanceof Error ? err.message : "提交失败，请重试");
      setAnimate("notice");
    }
  };

  if (!role) return <div className="boss-gate">
    <img src="/boss-brand/dapeng-front.png" alt="" />
    <h1>Boss Agent · 大鹏</h1>
    <p>{authError || "正在通过 nanobot 校验当前身份与访问范围…"}</p>
    {authError ? <div className="boss-actions">
      <GlassButton onClick={() => { setAuthError(""); setAuthAttempt((v) => v + 1); }}>重新核验</GlassButton>
      <GlassButton onClick={onLogout}>返回登录</GlassButton>
    </div> : <Loader2 size={22} className="boss-spin" aria-hidden="true" />}
  </div>;

  if (isNative) return <div className="boss-native-view">
    <div className="boss-native-return">
      <button type="button" onClick={() => navigate(role === "BOSS" ? "F01" : "A08")}>
        <ArrowLeft size={16} /> 返回 Boss-Agent 工作台
      </button>
      <span>nanobot 原生会话 / Settings · 实际模型与配置操作</span>
    </div>
    <div className="boss-native-content">{children}</div>
  </div>;

  return <div className="boss-v6" data-role={role}>
    <div className="boss-frame">
      <div className={"boss-layout " + (!sidebarOpen ? "boss-layout-slim" : "")}>
        <aside className="boss-sidebar" aria-label={role === "BOSS" ? "老板工作区" : "技术维护工作区"}>
          <div className="boss-brand">
            <img src="/boss-brand/boss-logo-from-reference.png" alt="Boss Agent 标识" />
            {sidebarOpen && <strong>Boss Agent</strong>}
          </div>
          {sidebarOpen && <p className="boss-brand-caption">让重要的事，推进得更确定</p>}
          <div className="boss-sidebar-label">{sidebarOpen ? (role === "BOSS" ? "老板工作区" : "技术维护工作区") : "◈"}</div>
          <nav className="boss-sidebar-nav">
            {userNav.map(([id, label, Icon]) =>
              <button type="button" key={id} className={"boss-nav-item " + (page === id ? "active" : "")}
                onClick={() => navigate(id)} title={label} aria-current={page === id ? "page" : undefined}>
                <Icon size={18} strokeWidth={1.8} aria-hidden="true" />
                {sidebarOpen && <span>{label}</span>}
              </button>
            )}
          </nav>
          <div className="boss-sidebar-bottom">
            <button type="button" onClick={() => setDirectoryOpen(true)} title="全部设计页面">
              <FolderOpen size={17} aria-hidden="true" />{sidebarOpen && "全部页面"}
            </button>
            <button type="button" onClick={() => setSidebarOpen(!sidebarOpen)} title={sidebarOpen ? "收起导航" : "展开导航"}>
              <Menu size={17} aria-hidden="true" />{sidebarOpen && "收起导航"}
            </button>
          </div>
        </aside>
        <main className="boss-main" id="boss-main">
          <header className="boss-topbar">
            <button className="boss-mobile-menu" type="button" onClick={() => setDirectoryOpen(true)}
              aria-label="打开页面目录"><Menu size={19}/></button>
            <button className="boss-search" type="button" onClick={() => setDirectoryOpen(true)}>
              <Search size={17}/><span>搜索页面、经营专题、任务入口…</span><kbd>⌘ K</kbd>
            </button>
            <div className="boss-topright">
              <Tag tone="blue">本地桌面开发版</Tag>
              <Tag tone="amber">模拟业务资料</Tag>
              <button type="button" className="boss-icon-button" title="通知中心"
                onClick={() => navigate(role === "BOSS" ? "N06" : "N12")}><Bell size={18}/></button>
              <button type="button" className="boss-user" onClick={onLogout} title="退出当前身份">
                <span className="boss-user-avatar">{role === "BOSS" ? "张" : "技"}</span>
                <span>{role === "BOSS" ? "张总" : "技术维护"}<small>{role === "BOSS" ? "演示老板身份" : "维护身份"}</small></span>
              </button>
            </div>
          </header>
          <section className="boss-stage">
            <div className={"boss-hero " + (page === "F01" ? "" : "boss-hero-compact")}>
              <div className="boss-hero-copy">
                <div className="boss-eyebrow">{role === "BOSS" ? "老板工作台" : "技术维护"} / {metadata?.module || "工作区"} · {page}</div>
                <h1>{page === "F01" ? "早上好，张总 · 今天想推进什么？" : metadata?.title || "工作页面"}</h1>
                <p>{metadata?.summary || "按照 PRD 查看真实执行过程和资料来源。"}</p>
              </div>
              <img src={["F05","F13","F24","F29"].includes(page) ? "/boss-brand/dapeng-think.png" : ["F06","F07","F14","F15","F16","F17","F18","F19","F20","F21","F22","F23"].includes(page) ? "/boss-brand/dapeng-execute.png" : "/boss-brand/dapeng-front.png"} className="boss-hero-mascot" alt="大鹏吉祥物" />
            </div>
            <div className="boss-content" key={page}>
              <div className="boss-meta-strip">
                <div className="boss-state-line">
                  <Tag tone={PRODUCT_PAGES.has(page) ? "green" : "muted"}>
                    {PRODUCT_PAGES.has(page) ? "部分功能已接入 · 待验收" : "已映射 · 未实现"}
                  </Tag>
                  <span>{metadata?.initial_state || "业务状态待读取"}</span>
                </div>
                <div className="boss-meta-actions">
                  <span>来源：Desktop v6 · {page}</span>
                  <button type="button" onClick={refresh} disabled={loading} aria-label="重新读取业务数据">
                    <RefreshCw size={15} className={loading ? "boss-spin" : ""}/> 重新读取
                  </button>
                </div>
              </div>
              {error && <StatusLine variant="error" text={"业务读取失败：" + error + "。已保留先前可见结果，不会自动执行写入。"} />}
              {loading && <StatusLine text="正在从本机业务服务读取有权数据和当前状态…" />}
              {role === "BOSS" ? (
                page === "F01" ? <div className="boss-columns">
                  <div className="boss-column">
                    <Panel title="业务日期与资料范围" note="F01 · 今日工作">
                      <div className="boss-form-grid boss-grid-3">
                        <label>业务日期<input type="date" value={dateFilter || (dashboard?.business_clock.slice(0,10) || "")}
                          onChange={(e) => setDateFilter(e.target.value)} /></label>
                        <label>IANA 时区<input readOnly value={dashboard?.profile.timezone || "等待读取"} /></label>
                        <label>资料截至时间<input readOnly value={dashboard?.source_coverage.periods.CURRENT?.[1] || "等待读取"} /></label>
                      </div>
                      <div className="boss-actions"><GlassButton primary onClick={refresh}><RefreshCw size={15}/> 更新当前事项</GlassButton></div>
                      <StatusLine variant="warn" text="目前仅连接 T02 模拟数据集；业务日期筛选尚未接入正式逐日聚合。资料覆盖和时效以服务返回为准。" />
                    </Panel>
                    <Panel title="今天需要我参与的事" note="待决定 · 待协调 · 需要知晓">
                      <div className="boss-tabs"><button className="active">待决定</button><button onClick={() => navigate("N05")}>待协调</button><button onClick={() => navigate("N06")}>需要知晓</button></div>
                      {dashboard?.tasks.length ? dashboard.tasks.map((t) =>
                        <button type="button" className="boss-task-row" key={t.task_id} onClick={() => selectTask(t.task_id)}>
                          <span className="boss-task-icon"><ClipboardCheck size={18}/></span>
                          <span><strong>{waitText(t.purpose)}</strong>
                            <small>当前处理人：{waitText(t.coordinator_id)} · 期限：{localTime(t.due_at)} · 状态：{t.status}</small>
                            <small>排序理由与本人参与原因：需结合正式业务资料确认</small>
                          </span><ChevronRight size={17}/>
                        </button>
                      ) : <Quiet message="当前没有已创建的模拟交办任务。不会将设计稿中的示例事项作为正式任务。" />}
                      {dashboard?.historical_commitment && <div className="boss-history-card">
                        <Tag tone="amber">已有历史承诺（模拟）</Tag>
                        <strong>{dashboard.historical_commitment.task_id}</strong>
                        <span>状态：{dashboard.historical_commitment.status} · 期限：{localTime(dashboard.historical_commitment.due_at)}</span>
                      </div>}
                      <div className="boss-actions"><GlassButton onClick={() => navigate("N05")}>查看全部任务 <ArrowRight size={15}/></GlassButton></div>
                    </Panel>
                    <Panel title="现在就交给大鹏" note="真实 DeepSeek 会话与 Tool 执行">
                      <form onSubmit={(event) => void sendQuestion(event)}>
                        <label className="boss-label" htmlFor="boss-question">输入本次工作需求</label>
                        <textarea id="boss-question" ref={draftRef} value={question} onChange={(e) => setQuestion(e.target.value)}
                          placeholder="例如：查看当前区域饲料外销毛利变化，读取依据，再帮我准备给负责人的交办。" rows={3}/>
                        {inputError && <p className="boss-validation-error">{inputError}</p>}
                        <div className="boss-actions">
                          <GlassButton onClick={() => navigate("N02")}><MessageCircle size={15}/> 聊天交办</GlassButton>
                          <button type="submit" className="boss-btn boss-btn-primary"><Send size={15}/> 提交需求</button>
                        </div>
                      </form>
                    </Panel>
                  </div>
                  <div className="boss-column">
                    <Panel title="会议与本人承诺">
                      {dashboard?.meeting ? <>
                        <Value label="关联会议" value={dashboard.meeting.meeting_id}/>
                        <Value label="会议时间" value={localTime(dashboard.meeting.starts_at)}/>
                        <Value label="参会人数" value={dashboard.meeting.participant_ids.length.toString()}/>
                        <div className="boss-actions"><GlassButton onClick={() => navigate("N04")}>查看会议资料</GlassButton></div>
                      </> : <Quiet message="会议资料未连接或当前范围为空。" />}
                    </Panel>
                    <Panel title="数据与来源状态">
                      <Value label="来源类型" value={dashboard?.source_type}/>
                      <Value label="执行空间" value={dashboard?.namespace}/>
                      <Value label="数据集版本" value={dashboard?.dataset_version}/>
                      <Value label="业务时钟" value={localTime(dashboard?.business_clock)}/>
                      <Value label="当前资料覆盖" value={dashboard ? (dashboard.source_coverage.region + " / " + dashboard.source_coverage.trade_scope) : undefined}/>
                      <div className="boss-actions"><GlassButton onClick={() => goSource("finance-note")}>查看原始依据</GlassButton></div>
                    </Panel>
                    <Panel title="大鹏的工作状态">
                      <div className="boss-mascot-work">
                        <img src={ANIMATIONS[loading || animate === "thinking" ? "thinking" : animate]} alt="" />
                        <div><strong>{loading ? "正在读取资料" : "待命 · 随时开始"}</strong>
                          <p>只有真实模型和业务接口返回后才显示执行结果；动画不会代替任务状态。</p>
                        </div>
                      </div>
                    </Panel>
                  </div>
                </div> :
                page === "N02" ? <div className="boss-columns">
                  <div className="boss-column">
                    <Panel title="大鹏 · 连续对话" note="连接 nanobot 原生 WebSocket 会话">
                      <StatusLine text="首次开发版本将已确认需求交给原生纳管会话；模型调用、Tools、流式事件与持久化由 nanobot 负责。" />
                      <form onSubmit={(event) => void sendQuestion(event)}>
                        <label className="boss-label" htmlFor="boss-chat-input">向大鹏提出需求</label>
                        <textarea id="boss-chat-input" ref={draftRef} rows={5} placeholder="输入你的需求，按提交进入真实 Agent 会话。"
                          value={question} onChange={(e) => setQuestion(e.target.value)} />
                        {inputError && <p className="boss-validation-error">{inputError}</p>}
                        <div className="boss-actions"><button className="boss-btn boss-btn-primary" type="submit"><Send size={15}/> 提交并进入 Agent 会话</button>
                          <GlassButton onClick={() => navigate("NATIVE")}>打开现有会话</GlassButton></div>
                      </form>
                    </Panel>
                  </div>
                  <div className="boss-column"><Panel title="授权与执行原则">
                    <Value label="模型" value="DeepSeek（固定 T02 选型）"/>
                    <Value label="工具权限" value="由服务端当前授权决定"/>
                    <Value label="任务结果" value="已执行与待反馈须分别读取"/>
                    <StatusLine variant="warn" text="未获准动作不得发送，缺少依据不能生成成功结果。" />
                  </Panel></div>
                </div> :
                ["N03", "F03"].includes(page) ? <div className="boss-columns">
                  <div className="boss-column">
                    <Panel title="经营指标查询" note="F03 · 实际复用 query_metrics Tool">
                      <div className="boss-form-grid">
                        <label>业务范围<input readOnly value="region-1 · EXTERNAL_SALES"/></label>
                        <label>产品范围<select value={productScope} onChange={(e) => setProductScope(e.target.value)}>
                          <option value="product-1,product-2">产品 1 + 产品 2</option>
                          <option value="product-1">产品 1</option>
                          <option value="product-2">产品 2</option>
                        </select></label>
                        <label>指标口径<input readOnly value="definition_version=1"/></label>
                        <label>当前/基准期间<input readOnly value="由获准业务数据集定义"/></label>
                      </div>
                      <div className="boss-actions">
                        <GlassButton primary onClick={() => {setAnimate("thinking"); setMetricsRequest((n) => n+1);}} disabled={querying}>
                          {querying && <Loader2 size={15} className="boss-spin"/>} 提交查询
                        </GlassButton>
                        <GlassButton onClick={() => navigate("F03")}>查看明细与追问</GlassButton>
                      </div>
                    </Panel>
                    <Panel title="经营对比" note="数值来自真实业务 Tool；保留 Decimal 原始字符串">
                      {metrics ? <div className="boss-table-scroll"><table className="boss-table">
                        <thead><tr><th>指标</th><th>基准期</th><th>当前期</th><th>单位</th></tr></thead>
                        <tbody>{Object.keys(LABELS).map((key) => {
                          const base = metrics.result.values.find((v) => v.metric_id === key && v.period_scope === "BASE");
                          const current = metrics.result.values.find((v) => v.metric_id === key && v.period_scope === "CURRENT");
                          return <tr key={key}><th scope="row">{LABELS[key]}</th>
                            <td>{base?.value ?? "未定义"}</td><td>{current?.value ?? "未定义"}</td>
                            <td>{current?.unit ?? base?.unit ?? "—"}</td></tr>;
                        })}</tbody></table></div> : <Quiet message="尚未执行该页查询。点击“提交查询”调用经过 Schema 校验的实际业务工具。" />}
                    </Panel>
                    <Panel title="继续追问">
                      <div className="boss-actions"><GlassButton onClick={() => navigate("N02")}><MessageCircle size={15}/> 进入 DeepSeek 会话</GlassButton>
                        <GlassButton onClick={() => goSource("finance-note")}>查看原始凭据与明细来源</GlassButton></div>
                    </Panel>
                  </div>
                  <div className="boss-column">
                    <Panel title="指标来源与覆盖">
                      <Value label="业务范围" value={metrics?.result.sources[0]?.coverage || "待查询"}/>
                      <Value label="资料截至" value={metrics?.result.sources[0]?.business_as_of || "待查询"}/>
                      <Value label="资料来源" value={metrics?.result.sources[0]?.source_id}/>
                      <Value label="本次查询 ID" value={metrics?.result.query_id}/>
                      <Value label="数据属性" value={metrics?.source_type}/>
                    </Panel>
                    <Panel title="可解释性与缺口">
                      {metrics ? <>
                        {(metrics.result.unexplained_causes || []).map((v,i) => <StatusLine key={i} variant="warn" text={v}/>)}
                        {(metrics.result.missing_fields || []).map((v,i) => <StatusLine key={"missing-"+i} variant="warn" text={"缺少：" + v}/>)}
                      </> : <p className="boss-helper">指标公式、定义版本、缺失原因需等实际查询完成后展示。</p>}
                    </Panel>
                  </div>
                </div> :
                page === "F27" ? <BossVoiceAssignment
                  getToken={getToken}
                  onSubmit={onStartChat}
                  onOpenConversation={() => navigate("NATIVE")}
                /> :
                page === "F06" ? <BossAssignmentFlow
                  tasks={tasks} selectedTaskId={selectedTaskId}
                  onSelectTask={setSelectedTaskId} onReload={refresh}
                  onViewSource={() => goSource("finance-note")} context={dashboard}
                  draft={assignmentDraft} onDraftChange={updateAssignmentDraft}
                  onDraftSaved={()=>setAssignmentDirty(false)}
                  onOpenCoordinatorPicker={()=>navigate("D04")}
                  onOpenDuePicker={()=>navigate("D05")}
                  onViewMessages={()=>navigate("F08")}
                  onMessageDraftCreated={setDraftToReview}
                /> :
                (page==="D04"||page==="D05") ? <BossAssignmentPicker
                  key={page} pageId={page} contacts={dashboard?.contacts||[]}
                  timezone={dashboard?.profile.timezone||"Asia/Shanghai"}
                  businessClock={dashboard?.business_clock} draft={assignmentDraft}
                  onChange={updateAssignmentDraft} onReturn={()=>navigate("F06")}
                /> :
                page==="D06" ? <div className="boss-columns">
                  <div className="boss-column">
                    <Panel title="未保存修改提醒" note="D06 · 草稿保护">
                      <StatusLine text="当前草稿不自动保存或发送；离开F06前会显示真实确认弹窗。"/>
                      <GlassButton onClick={()=>navigate("F06")}>返回交办草稿</GlassButton>
                    </Panel>
                  </div>
                </div> :
                page==="D07" ? <div className="boss-columns">
                  <div className="boss-column">
                    <Panel title="访问权限限制" note="D07 · 服务端权限制约">
                      <StatusLine variant="warn" text="角色权限由Gateway与业务服务同时核查，前端页面不能提升或绕过授权。"/>
                      <Value label="当前身份" value={role}/>
                      <GlassButton onClick={()=>navigate("F01")}>返回本人工作台</GlassButton>
                    </Panel>
                  </div>
                </div> :
                page === "N05" ? <div className="boss-columns">
                  <div className="boss-column">
                    <Panel title="任务与承诺" note="从 SQLite 正式业务对象读取，不根据设计图生成任务">
                      {tasks?.tasks.length ? tasks.tasks.map((t) =>
                        <button key={t.task_id} type="button" className={"boss-task-row " + (selectedTaskId === t.task_id ? "selected" : "")}
                          onClick={() => selectTask(t.task_id)}>
                          <span className="boss-task-icon"><ClipboardCheck size={18}/></span>
                          <span><strong>{waitText(t.purpose)}</strong>
                          <small>状态：{t.status} · 唯一负责人：{waitText(t.coordinator_id)}</small>
                          <small>版本 {waitText(t.version)} · 期限 {localTime(t.due_at)}</small></span><ChevronRight size={17}/>
                        </button>
                      ) : <Quiet message="还没有从 Agent 工具创建的交办；首次执行时不会伪造已有任务。" />}
                    </Panel>
                    <Panel title="历史承诺 · 仅供背景参考">
                      {tasks?.historical_commitment ? <>
                        <Value label="历史任务" value={tasks.historical_commitment.task_id}/>
                        <Value label="背景状态" value={tasks.historical_commitment.status}/>
                        <Value label="原定期限" value={localTime(tasks.historical_commitment.due_at)}/>
                      </> : <Quiet message="历史材料尚未载入。" />}
                    </Panel>
                  </div>
                  <div className="boss-column">
                    <Panel title="选中任务">
                      {(() => {
                        const t = tasks?.tasks.find((row) => row.task_id === selectedTaskId) || tasks?.tasks[0];
                        return t ? <>
                          <Value label="对象 ID" value={t.task_id}/>
                          <Value label="当前状态" value={t.status}/>
                          <Value label="证据要求" value={t.evidence_requirements?.join("、")}/>
                          <Value label="有效期限" value={localTime(t.due_at)}/>
                          <Value label="来源资料" value={t.source_refs?.join("、")}/>
                          <StatusLine variant="warn" text="确认完成、延期和催办属于 PRD 的授权写入流程；本批次只开放实际查询，不提供伪确认按钮。" />
                        </> : <Quiet message="请选择一个已存在的交办对象。" />;
                      })()}
                    </Panel>
                    <Panel title="下一步"><div className="boss-actions">
                      <GlassButton onClick={() => navigate("N02")}>与 Agent 讨论交办</GlassButton>
                      <GlassButton onClick={() => navigate("F01")}>返回今日工作</GlassButton>
                    </div></Panel>
                  </div>
                </div> :
                page === "N04" ? <div className="boss-columns">
                  <div className="boss-column">
                    <Panel title="会议与资料" note="来源与作者均为模拟数据标注">
                      {meetings?.meeting ? <>
                        <Value label="会议 ID" value={meetings.meeting.meeting_id}/>
                        <Value label="会议时间" value={localTime(meetings.meeting.starts_at)}/>
                        <Value label="时区" value={meetings.meeting.timezone}/>
                        <Value label="参会联系人" value={meetings.meeting.participant_ids.join("、")}/>
                      </> : <Quiet message="暂无可读取的会议资料。" />}
                    </Panel>
                    <Panel title="关联来源">
                      {meetings?.documents.map((d) => <button type="button" className="boss-task-row" key={d.source_id} onClick={() => goSource(d.source_id)}>
                        <span className="boss-task-icon"><FileSearch size={18}/></span>
                        <span><strong>{d.source_id}</strong><small>版本 {d.version} · {d.source_type} · {localTime(d.published_at)}</small></span>
                        <ChevronRight size={17}/>
                      </button>)}{!meetings?.documents.length && <Quiet message="尚无获准资料索引。" />}
                    </Panel>
                  </div>
                  <div className="boss-column">
                    <Panel title="业务连续性">
                      <StatusLine text="纪要核查、意见/决定分类与分项交办属于后续开发任务；已连接会议与原文读取，未接入写入 API。" />
                      <div className="boss-actions"><GlassButton onClick={() => navigate("N02")}>让 Agent 准备会议</GlassButton>
                      <GlassButton onClick={() => navigate("F05")}>纪要分类核查</GlassButton>
                      <GlassButton onClick={() => navigate("F07")}>查看申请审阅</GlassButton></div>
                    </Panel>
                  </div>
                </div> :
                ["F24","D03"].includes(page) ? <div className="boss-columns">
                  <div className="boss-column">
                    <Panel title="DeepSeek 实际运行详情" note={page+" · 源自本机脱敏 Provider 回执"}>
                      {modelHealth?.runtime_response_observed ?
                        <StatusLine variant="ok" text="本机服务收到过实际 DeepSeek 模型响应。此状态不代表当前业务已完成。" /> :
                        <StatusLine variant="warn" text="本次本机运行尚无真实模型响应回执。仅有配置不等于服务已验证可用。" />}
                      <Value label="Provider 观察" value={modelHealth?.provider}/>
                      <Value label="当前模型" value={modelHealth?.latest_response?.model ?? "尚未观察"}/>
                      <Value label="响应标识" value={modelHealth?.latest_response?.response_id}/>
                      <Value label="响应时间" value={modelHealth?.latest_response?.at}/>
                      <Value label="结束原因" value={modelHealth?.latest_response?.finish_reasons.join("、") || "待观察"}/>
                      <div className="boss-actions">
                        <GlassButton primary onClick={() => navigate("NATIVE")}>进入原生会话</GlassButton>
                        <GlassButton onClick={refresh}>重新读取运行结果</GlassButton>
                      </div>
                    </Panel>
                  </div>
                  <div className="boss-column">
                    <Panel title="Token 用量及费用覆盖">
                      <Value label="实际请求数" value={modelHealth?.observed_request_count.toString()}/>
                      <Value label="有回执的响应数" value={modelHealth?.observed_response_count.toString()}/>
                      <Value label="Prompt Token" value={modelHealth?.reported_usage?.prompt_tokens?.toString()}/>
                      <Value label="Completion Token" value={modelHealth?.reported_usage?.completion_tokens?.toString()}/>
                      <Value label="Total Token" value={modelHealth?.reported_usage?.total_tokens?.toString()}/>
                      <Value label="总费用" value="未知（用量缺口与计价尚待核对）"/>
                      <StatusLine text="界面只显示真实响应元信息，不读取 Prompt、消息正文、服务端密钥或内部推理。" />
                    </Panel>
                  </div>
                </div> :
                page === "D01" ? <div className="boss-columns">
                  <div className="boss-column">
                    <Panel title="来源原文与支持关系">
                      <Value label="来源 ID" value={evidence?.source_id}/>
                      <Value label="版本" value={evidence?.version}/>
                      <Value label="来源属性" value={evidence?.source_type}/>
                      <Value label="作者" value={evidence?.author_contact_id}/>
                      {evidence?.content ? <blockquote className="boss-source">{
                        sourceAnchor &&
                        evidence.source_id===sourceAnchor.source_id &&
                        evidence.version===sourceAnchor.version &&
                        Number.isInteger(sourceAnchor.start) &&
                        Number.isInteger(sourceAnchor.end) &&
                        sourceAnchor.start>=0 &&
                        sourceAnchor.end<=evidence.content.length &&
                        sourceAnchor.start<sourceAnchor.end ? <>
                          {evidence.content.slice(0,sourceAnchor.start)}
                          <mark className="boss-source-highlight" id="boss-source-citation">
                            {evidence.content.slice(sourceAnchor.start,sourceAnchor.end)}
                          </mark>
                          {evidence.content.slice(sourceAnchor.end)}
                        </> : evidence.content
                      }</blockquote> :
                        <Quiet message="尚未读取原文；无效、超范围和已撤销文件不会显示正文。" />}
                      {sourceAnchor && evidence &&
                        (evidence.source_id!==sourceAnchor.source_id ||
                         evidence.version!==sourceAnchor.version) &&
                        <StatusLine variant="warn" text="研究引用的原始版本已发生变化。本页不会把新版本原文错误标记为旧版本的证据。" />}
                    </Panel>
                  </div>
                  <div className="boss-column">
                    <Panel title="返回当前工作">
                      <div className="boss-actions"><GlassButton primary onClick={() => navigate(allowed(previousPage, role) ? previousPage : "F01")}><ArrowLeft size={15}/> 返回原页面</GlassButton>
                        <GlassButton onClick={refresh}>重读来源</GlassButton></div>
                      {originFocus && <p className="boss-helper">关联入口：{originFocus}。原有筛选和滚动恢复由后续 T08 进一步接入。</p>}
                    </Panel>
                  </div>
                </div> :
                (SECTOR_PAGE_IDS as readonly string[]).includes(page) ? <BossSectorView
                  key={page} pageId={page} onNavigate={id=>navigate(id)}
                  onViewSource={goSource} onStartChat={onStartChat}
                /> :
                (page === "F08" || page === "F12") ? <BossCommunicationCalendar
                  key={page} pageId={page} onViewSource={goSource}
                  onNavigate={id=>navigate(id)} focusDraftId={draftToReview}
                  onFocusDraftConsumed={()=>setDraftToReview("")}
                /> :
                page === "F09" ? <BossResearchView
                  key={page} onNavigate={id=>navigate(id)}
                  onViewSource={goSource} onStartChat={onStartChat}
                /> :
                page === "F04" ? <BossMeetingBrief
                  key={page} onNavigate={id=>navigate(id)} onViewSource={goSource}
                  onMessageDraftCreated={setDraftToReview}
                /> :
                (page === "F05" || page === "F07") ? <BossMeetingApprovalView
                  key={page} pageId={page}
                  onViewSource={goSource}
                  onNavigate={id=>navigate(id)}
                  onTaskCreated={id=>{setSelectedTaskId(id);refresh();}}
                /> :
                WORKSPACE_PAGE_ROUTES[page] ? <BossWorkspaceView
                  key={page} role={role} pageId={page}
                  onNavigate={id=>navigate(id)} onViewSource={goSource}
                /> :
                <div className="boss-columns">
                  <div className="boss-column"><Panel title={metadata?.title || "页面"} note="v6 设计源已固定">
                    <StatusLine variant="warn" text="此页面已纳入 72 页实现映射，但业务组件及接口尚未接入。以下只展示来自真实设计元数据的字段要求。" />
                    <div className="boss-field-grid">{(metadata?.sections || []).map((v,i)=>
                      <div className="boss-field-line" key={v+i}><span>{v}</span><strong>待实现 · 无运行结果</strong></div>)}</div>
                  </Panel></div>
                  <div className="boss-column"><Panel title="待绑定字段与动作">
                    <p className="boss-helper">字段：{metadata?.fields?.join("、") || "以 PRD 为准"}</p>
                    <p className="boss-helper">动作：{metadata?.actions?.join("、") || "以 PRD 为准"}</p>
                    <StatusLine text="未连接写入动作，不会显示模拟保存/发送成功。" />
                  </Panel></div>
                </div>
              ) : page === "D07" ? <div className="boss-columns">
                <div className="boss-column">
                  <Panel title="当前角色访问限制" note="D07 · 无敏感信息">
                    <StatusLine variant="warn" text="老板业务信息仅BOSS角色可访问；维护者不能代替老板批准、读取个人记忆或私人日历。"/>
                    <Value label="当前身份" value={role}/>
                    <GlassButton onClick={()=>navigate("A08")}>返回技术工作台</GlassButton>
                  </Panel>
                </div>
              </div> : page === "A06" ? <div className="boss-columns">
                <div className="boss-column">
                  <Panel title="SOP 与 Skills" note="A06 · 复用 nanobot 原生目录及工具注册表">
                    <StatusLine text="SOP 与 Skills 的安装、校验和正式采用由已有 nanobot Settings/Skills 承载；本页不再造一个未经验证的配置引擎。" />
                    <Value label="已固定的 Agent 核心" value="nanobot v0.3.5"/>
                    <Value label="业务角色" value="技术维护，不具备老板业务授权"/>
                    <Value label="本页状态" value="原生设置承接 · 自定义流程版本管理待开发"/>
                    <div className="boss-actions">
                      <GlassButton primary onClick={() => {
                        window.location.hash="#/skills";
                        navigate("NATIVE");
                      }}>打开原生 Skills 目录 <ArrowRight size={15}/></GlassButton>
                    </div>
                  </Panel>
                </div>
                <div className="boss-column">
                  <Panel title="启用和验证边界">
                    <StatusLine variant="warn" text="可以进入已认证的开源原生目录；这不表示 PRD 规定的业务 SOP 版本、校验、启用和下一任务采用全部实现。" />
                  </Panel>
                </div>
              </div> : ["A15","F30"].includes(page) ? <div className="boss-columns">
                <div className="boss-column">
                  <Panel title="模型及工具实际运行记录" note={page+" · 只读技术元信息"}>
                    {modelHealth?.runtime_response_observed ?
                      <StatusLine variant="ok" text="已观察到本机实际 Provider 响应；请求内容已脱敏。" /> :
                      <StatusLine variant="warn" text="当前还没有实际模型响应记录；不能将已配置视为运行成功。" />}
                    <Value label="模型" value={modelHealth?.latest_response?.model ?? "待观察"}/>
                    <Value label="实际模型请求" value={modelHealth?.observed_request_count.toString()}/>
                    <Value label="实际响应" value={modelHealth?.observed_response_count.toString()}/>
                    <Value label="工具事件数" value={modelHealth?.tool_event_count?.toString()}/>
                    <Value label="错误事件数" value={modelHealth?.observed_error_count?.toString()}/>
                    <div className="boss-actions">
                      <GlassButton onClick={refresh}>重新读取脱敏审计</GlassButton>
                    </div>
                  </Panel>
                </div>
                <div className="boss-column">
                  <Panel title="费用与使用范围">
                    <Value label="Total Token" value={modelHealth?.reported_usage?.total_tokens?.toString()}/>
                    <Value label="统计覆盖" value="仅本机实际已记录请求"/>
                    <Value label="合计模型费用" value="未知"/>
                    <Value label="提示词与原文" value="禁止维护角色直接查看"/>
                    <StatusLine text="部分取消、超时或服务错误可能没有 Token 回执，不能因此计为零费用。" />
                  </Panel>
                </div>
              </div>
              : page === "A04" ? <>
              <div className="boss-columns">
                <div className="boss-column">
                  <MaintainerFeedback tasks={maintenance?.task_refs || []} onReload={refresh}/>
                  <MaintainerMessageReply/>
                </div>
                <div className="boss-column">
                  <Panel title="当前模拟资料与角色">
                    <Value label="身份" value="MAINTAINER"/>
                    <Value label="可注入的任务对象" value={String(maintenance?.task_refs?.length ?? 0)}/>
                    <StatusLine text="模拟负责人反馈由维护者注入；老板需另行确认延期、完成或取消。"/>
                    <GlassButton onClick={refresh}>重读任务元数据</GlassButton>
                  </Panel>
                </div>
              </div>
              <div className="boss-workspace-extra">
                <BossWorkspaceView key="A04" role={role} pageId="A04"
                  onNavigate={id=>navigate(id)} onViewSource={goSource}/>
              </div>
              </> : page === "A05" ? <MaintainerPromptVersion key="A05" onNavigate={id=>navigate(id)}/> :
                page === "A07" ? <MaintainerKnowledgeEditor key="A07"/> :
                page === "A03" ? <>
                <BossWorkspaceView key="A03" role={role} pageId="A03"
                  onNavigate={id=>navigate(id)} onViewSource={goSource}/>
                <div className="boss-workspace-extra">
                  <MaintainerApplicationSeed/>
                </div>
              </> : WORKSPACE_PAGE_ROUTES[page] ? <BossWorkspaceView
                key={page} role={role} pageId={page}
                onNavigate={id=>navigate(id)} onViewSource={goSource}
              /> : <div className="boss-columns">
                <div className="boss-column">
                  <Panel title={metadata?.title || "维护工作"} note="独立维护身份 · 仅获准元信息">
                    {maintenance ? <>
                      <Value label="当前模拟配置的 Provider" value={maintenance.configured_provider}/>
                      <Value label="当前模拟配置的 Model" value={maintenance.configured_model}/>
                      <Value label="配置版本" value={maintenance.configuration_version}/>
                      <Value label="元数据来源" value={maintenance.status}/>
                      <StatusLine variant="warn" text="上述为验证服务中的模拟配置元信息，不是实时启用模型的证明；请从原生 nanobot Settings 核查实际配置采用。" />
                    </> : <Quiet message="请在原生 nanobot Settings 中查看真实模型和维护配置。" />}
                    <div className="boss-actions">
                      <GlassButton primary onClick={() => navigate("NATIVE")}>打开原生 Settings <ArrowRight size={15}/></GlassButton>
                      <GlassButton onClick={refresh}>重新读取维护元信息</GlassButton>
                    </div>
                  </Panel>
                  {page !== "A08" && <Panel title="页面工作项">
                    <StatusLine variant="warn" text="当前仅接入受权限控制的维护元信息；正式配置保存、启用、重载及下一任务采用需按 PRD 逐项实现。" />
                    {(metadata?.sections || []).map((v) => <Value key={v} label={v} value="待实现"/>)}
                  </Panel>}
                </div>
                <div className="boss-column">
                  <Panel title="维护范围">
                    <Value label="访问角色" value="MAINTAINER"/>
                    <Value label="当前业务权限" value="不能代老板审批、发送或更改个人记忆"/>
                    <Value label="功能状态" value="T02 开源能力已验证；业务页仍需 T19 开发"/>
                    <StatusLine text="原生 Settings 及纳管模型配置由固定 nanobot WebUI 负责，未来将在 v6 主题下统一重构。" />
                  </Panel>
                </div>
              </div>}
              <div className="boss-footer-line">
                Boss Agent × 大鹏 · Desktop v6 视觉基线 · {page} ·
                所有模拟资料均标注来源，页面导航不代表功能或验收通过。
              </div>
            </div>
          </section>
        </main>
      </div>
    </div>
    {pendingNavigation && <div className="boss-confirm-backdrop">
      <section className="boss-confirm" role="dialog" aria-modal="true" aria-labelledby="boss-unsaved-title">
        <h3 id="boss-unsaved-title"><AlertCircle size={19}/> 未保存修改（D06）</h3>
        <p>当前交办表单有未保存内容。离开前请本人明确选择：继续编辑，或放弃这些修改。此提示不会提交业务写入。</p>
        <div className="boss-actions">
          <button type="button" className="boss-btn" onClick={()=>setPendingNavigation(null)}>返回继续编辑</button>
          <button type="button" className="boss-btn boss-btn-primary" onClick={()=>{
            const destination=pendingNavigation;
            setAssignmentDraft({...DEFAULT_ASSIGNMENT_DRAFT});
            setAssignmentDirty(false);
            setPendingNavigation(null);
            navigate(destination.id,destination.focus,true);
          }}>放弃草稿并离开</button>
        </div>
      </section>
    </div>}
    {directoryOpen && <div className="boss-directory-backdrop" role="presentation" onMouseDown={(e) => {
      if(e.target === e.currentTarget) setDirectoryOpen(false);
    }}>
      <section className="boss-directory" role="dialog" aria-modal="true" aria-label="全部页面导航">
        <header><strong>页面目录 · Desktop v6</strong>
          <button type="button" onClick={() => setDirectoryOpen(false)} aria-label="关闭目录"><X size={19}/></button></header>
        <label className="boss-directory-search"><Search size={17}/><input autoFocus value={pageFilter}
          onChange={(e) => setPageFilter(e.target.value)} placeholder="搜索页面编号或名称"/></label>
        <p>仅列出当前身份可见页面，开发中页面不会执行伪写入。</p>
        <div className="boss-directory-list">
          {searchablePages.map(([id,p])=>
            <button type="button" key={id} onClick={() => navigate(id)} className={page===id?"selected":""}>
              <span>{id} · {p.title}</span>
              <Tag tone={PRODUCT_PAGES.has(id)?"green":"muted"}>{PRODUCT_PAGES.has(id)?"部分开发":"待实现"}</Tag>
            </button>)}
          {searchablePages.length === 0 && <Quiet message="当前身份下无匹配页面。"/>}
        </div>
        <footer><button type="button" onClick={() => navigate("NATIVE")}>
          <MessageCircle size={16}/> 进入 nanobot 原生工作区
        </button></footer>
      </section>
    </div>}
  </div>;
}
