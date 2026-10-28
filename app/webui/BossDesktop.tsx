import {
  useCallback, useEffect, useRef, useState,
  type ReactNode,
} from "react";
import * as DialogPrimitive from "@radix-ui/react-dialog";
import {
  AlertCircle, ArrowLeft, Bell,
  CheckCircle2,
  Clock3, Loader2,
  Menu, MessageCircle, RefreshCw, Search, Settings,
  X,
} from "lucide-react";
import pageMeta from "./page-meta.json";
import {brandMessages} from "./boss-branding";
import {deliveredPage} from "./delivered-navigation";
import {BossPrimaryNavigation,BossMenuDirectory} from "./BossMenuNavigation";
import {bindBossHistory,pushBossHistory,replaceBossHistory} from "./boss-history";
import {bossPageId,menuPageUrl,readBossLocation} from "./boss-route";
import { BossAssignmentFlow, MaintainerFeedback, type TaskListResponse, type MaintenanceTaskRef } from "./BossAssignmentFlow";
import { BossWorkspaceView, WORKSPACE_PAGE_ROUTES } from "./BossWorkspaceView";
import {BossNotificationReturn} from "./BossDesktopNotifications";
import {BossSourceView} from "./BossSourceView";
import {BossRestrictedView,BossUnsavedWorkspace} from "./BossAccessStates";
import type {DraftLeaveHandle} from "./draft-leave";
import { BossSectorView, SECTOR_PAGE_IDS } from "./BossSectorView";
import { BossSupplyQualityView } from "./BossSupplyQualityView";
import { EMPTY_SUPPLY_EDITOR, type SupplyQualityEditor } from "./BossSupplyQualityPanel";
import { MaintainerSupplyQuality, EMPTY_IMPORT_EDITOR, type SupplyImportEditor } from "./MaintainerSupplyQuality";
import { BossAssignmentPicker, DEFAULT_ASSIGNMENT_DRAFT, type AssignmentDraft } from "./BossAssignmentPicker";
import { BossMeetingApprovalView, MaintainerApplicationSeed } from "./BossMeetingApproval";
import { BossMeetingBrief } from "./BossMeetingBrief";
import type { MeetingArrangementProjection } from "./BossMeetingArrangement";
import { MaintainerRuntimeRecords } from "./MaintainerRuntimeRecords";
import { RuntimeTaskTechnicalView } from "./RuntimeTaskTechnicalView";
import {MaintainerModelWorkspace} from "./MaintainerModelConnections";
import {BossRunDetails} from "./BossRunDetails";
import { MaintainerMemoryStatus } from "./MaintainerMemoryStatus";
import { MaintainerSkills } from "./MaintainerSkills";
import { MaintainerSkillVersions } from "./MaintainerSkillVersions";
import { MaintainerSimulationInspect } from "./MaintainerSimulationInspect";
import { BossAssignmentSourceReview, type AssignmentSourceReviewProjection } from "./BossAssignmentSourceReview";
import { BossTravelView } from "./BossTravelView";
import { BossPeopleMeeting } from "./BossPeopleMeeting";
import { BossOwnerPreferences } from "./BossOwnerPreferences";
import { BossSettingsHub } from "./BossSettingsHub";
import { BossTaskCenter } from "./BossTaskCenter";
import { BossMeetingLibrary } from "./BossMeetingLibrary";
import { BossRuntimeOverview } from "./BossRuntimeOverview";
import { BossVoicePaused } from "./BossVoicePaused";
import {BossExecutionRecovery} from "./BossExecutionRecovery";
import {BossTaskExceptions} from "./BossTaskExceptions";
import {BossPersonalMemory} from "./BossPersonalMemory";
import {BossOwnerRecords} from "./BossOwnerRecords";
import {MaintainerAudit} from "./MaintainerAudit";
import {MaintainerConfiguration,MaintainerMetricsConfiguration} from "./MaintainerConfiguration";
import {MaintainerDatasets} from "./MaintainerDatasets";
import {MaintainerSimulationCenter} from "./MaintainerSimulationCenter";
import {MaintainerEvaluation} from "./MaintainerEvaluation";
import {MaintainerContactsWorkspace} from "./MaintainerSecretary";
import {MaintainerLocalSystem} from "./MaintainerLocalSystem";
import { MaintainerPromptVersion } from "./MaintainerPromptVersion";
import { BossResearchView } from "./BossResearchView";
import { BossCommunicationCalendar } from "./BossCommunicationCalendar";
import { BossPrivateCalendar } from "./BossPrivateCalendar";
import { MaintainerMessageReply } from "./MaintainerMessageReply";
import {MaintainerKnowledgeWorkspace} from "./MaintainerKnowledgeWorkspace";
import { MaintainerScheduler } from "./MaintainerScheduler";
import { BossMorningView, type MorningReference,type MorningConversationRequest,type MorningBindingReceipt } from "./BossMorningView";
import type {ConversationActions} from "./BossConversationWorkspace";
import {BossTaskConversationEntry} from "./BossTaskConversationEntry";
import { BossMorningPreparation,type MorningPreparationContext } from "./BossMorningPreparation";
import { BossMVPView } from "./BossMVPView";
import { BossBIView } from "./BossBIView";
import {BossBusinessOverview} from "./BossBusinessOverview";
import {useBusinessConversationEntry} from "./BusinessConversationEntry";
import {BusinessOverviewQuery} from "./BusinessOverviewQuery";
import {BusinessOverviewAlert} from "./BusinessOverviewAlert";
import {BossReminderWorkspace} from "./BossReminderWorkspace";
import {BusinessOverviewPreparation,savedOverviewPreparation} from "./BusinessOverviewPreparation";
import type {OverviewSelection} from "./business-overview-types";
import { MaintainerBIScenarios } from "./MaintainerBIScenarios";
import {MaintainerSimulationEvents} from "./MaintainerSimulationEvents";
import { MaintainerMorningCoverage } from "./MaintainerMorningCoverage";
import { BossOwnerPlans, type OwnerPlanProjection } from "./BossOwnerPlans";
import { useClient } from "@/providers/ClientProvider";
import "./boss-v6.css";
import "./boss-v7.css";

type Role = "BOSS" | "MAINTAINER";
const navigationGraphics:Record<string,ReactNode>={
  F01:<path d="m3 10 9-7 9 7v10a1 1 0 0 1-1 1h-5v-7H9v7H4a1 1 0 0 1-1-1z"/>,
  N02:<path d="M21 11.5a8.4 8.4 0 0 1-9 8.5 9.5 9.5 0 0 1-4-.8L3 21l1.8-5A8.5 8.5 0 1 1 21 11.5Z"/>,
  N03:<path d="M4 20V10m5 10V4m6 16v-7m5 7V7"/>,
  N04:<><rect x="3" y="5" width="18" height="16" rx="2"/><path d="M7 3v4m10-4v4M3 10h18"/></>,
  N05:<><rect x="5" y="4" width="14" height="17" rx="2"/><path d="M9 4.5h6m-6 7 2 2 4-4m-6 8h6"/></>,
  N06:<path d="M18 8a6 6 0 0 0-12 0c0 7-3 7-3 9h18c0-2-3-2-3-9ZM10 21h4"/>,
};
function ReferenceNavigationIcon({id}:{id:string}){const graphic=navigationGraphics[id];if(!graphic)throw new Error("当前聊天导航缺少原稿图形");return <svg viewBox="0 0 24 24" width={18} height={18} fill="none" stroke="currentColor" strokeWidth={1.75} strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">{graphic}</svg>;}
function ReferenceHeaderIcon({kind}:{kind:"search"|"notification"}){return <svg viewBox="0 0 24 24" width={20} height={20} fill="none" stroke="currentColor" strokeWidth={1.75} strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">{kind==="search"?<><circle cx="11" cy="11" r="7"/><path d="m16.4 16.4 5 5"/></>:navigationGraphics.N06}</svg>;}
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
  profile: { timezone: string; goals: string[]; reading_requirement: string|null;
    topics?: string[]; owner_confirmation?: string; active_version?: string|null;
    applicability?: string; };
  source_coverage: { region: string; trade_scope: string; periods: Record<string, string[]> };
  tasks: Task[]; historical_commitment: HistoricalTask | null;
  meeting: { meeting_id: string; starts_at: string; timezone: string; participant_ids: string[]; material_ids: string[] } | null;
  contacts: { contact_id: string; name: string; organization: string; responsibility: string }[];
  event?: { event_id: string; status: string };
  assignment_source_ids?: string[];
  notifications: { event_id: string; state: string }[];
};
type Tasks = TaskListResponse & { historical_commitment: HistoricalTask | null; source_type: string };
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
type Identity = { role: Role | null; owner_id: string | null; execution_scope?:string|null };
type Animation = "idle" | "thinking" | "complete" | "notice";

type Props = {
  getToken: () => string;
  onLogout: () => void;
  onStartChat: (content: string) => Promise<boolean | void>;
  onStartMorning:(value:MorningConversationRequest,signal:AbortSignal)=>Promise<MorningBindingReceipt>;
  onOpenMorning:(chatId:string)=>void;
  onNewConversation:()=>void;
  onCreateTaskConversation:()=>Promise<string>;
  onOpenTaskConversation:(chatId:string)=>void;
  children: (role: Role, visible: boolean, actions:ConversationActions) => ReactNode;
  onOpenNative: (role: Role) => void;
  onBeforeLeaveNative: (leave: () => void) => void;
  onRegisterCloseGuard: (guard: ((close: () => void) => void) | null) => void;
};

const pages = brandMessages(pageMeta) as Record<string, DesignPage>;
pages.N06={...pages.N05};
function unsupportedPage(page:string):never {throw new Error("页面没有对应的业务组件："+page);}
function allowed(page: string, role: Role, mvp=false, _priority=false) {
  return deliveredPage(page,role,mvp)!==undefined;
}
function initialPage(role: Role, mvp=false, priority=false): string {
  void mvp;void priority;
  return readBossLocation(new URL(window.location.href),role).page;
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
    if (response.status === 401) window.dispatchEvent(new Event("boss-auth-expired"));
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
function businessGreeting(clock?: string, timezone?: string) {
  if (!clock) return "今天想推进什么？";
  const at = new Date(clock);
  if (Number.isNaN(at.getTime())) return "今天想推进什么？";
  const zone = timezone || undefined;
  const hour = Number(new Intl.DateTimeFormat("zh-CN", { hour: "2-digit", hour12: false, timeZone: zone }).format(at));
  const date = new Intl.DateTimeFormat("zh-CN", { month: "long", day: "numeric", weekday: "long", timeZone: zone }).format(at);
  const part = hour < 6 ? "夜深了" : hour < 12 ? "早上好" : hour < 14 ? "中午好" : hour < 18 ? "下午好" : "晚上好";
  return part + " · " + date + "，今天想推进什么？";
}

export function BossDesktop({ getToken, onLogout, onStartChat, onStartMorning,onOpenMorning,onCreateTaskConversation,onOpenTaskConversation, children, onOpenNative, onBeforeLeaveNative,onRegisterCloseGuard }: Props) {
  const { client, token } = useClient();
  const [role, setRole] = useState<Role | null>(null);
  const [mvpScope,setMvpScope]=useState(false);
  const [priorityScope,setPriorityScope]=useState(false);
  const [authError, setAuthError] = useState("");
  const [authAttempt, setAuthAttempt] = useState(0);
  const [page, setPage] = useState("F01");
  const [previousPage, setPreviousPage] = useState(()=>new URLSearchParams(window.location.search).get("bossReturn")??"F01");
  const businessPage = useRef<string | null>(null);
  const conversationReturn=useRef(new URLSearchParams(window.location.search).get("bossConversationReturn")==="N02");
  useEffect(()=>{conversationReturn.current=new URLSearchParams(window.location.search).get("bossConversationReturn")==="N02";},[client]);
  const [sidebarOpen, setSidebarOpen] = useState(true);
  const [directoryOpen, setDirectoryOpen] = useState(false);
  const [accountOpen, setAccountOpen] = useState(false);
  const [pageFilter, setPageFilter] = useState("");
  const [assignmentDraft, setAssignmentDraft] = useState<AssignmentDraft>(DEFAULT_ASSIGNMENT_DRAFT);
  const [assignmentDirty, setAssignmentDirty] = useState(false);
  useEffect(()=>{setAssignmentDraft({...DEFAULT_ASSIGNMENT_DRAFT});setAssignmentDirty(false);},[client,token]);
  const [settingsDirty, setSettingsDirty] = useState(false);
  const [workDirty, setWorkDirty] = useState(false);
  const [overviewDirty,setOverviewDirty]=useState(false),[queryDirty,setQueryDirty]=useState(false);
  const [overviewDiscardVersion,setOverviewDiscardVersion]=useState(0);
  const [overviewPreparation,setOverviewPreparation]=useState<OverviewSelection|null>(savedOverviewPreparation);
  const [morningDiscardVersion,setMorningDiscardVersion]=useState(0);
  const [morningOrigin,setMorningOrigin]=useState<MorningReference|null>(null);
  const [morningReady,setMorningReady]=useState(false);
  const [morningContext,setMorningContext]=useState<MorningPreparationContext|null>(null);
  useEffect(()=>{setMorningOrigin(null);setMorningReady(false);setMorningContext(null);},[client]);
  const [supplyEditors, setSupplyEditors] = useState({client,token,SI09:{...EMPTY_SUPPLY_EDITOR},SI10:{...EMPTY_SUPPLY_EDITOR},import:{...EMPTY_IMPORT_EDITOR}});
  useEffect(()=>{
    setSupplyEditors({client,token,SI09:{...EMPTY_SUPPLY_EDITOR},SI10:{...EMPTY_SUPPLY_EDITOR},import:{...EMPTY_IMPORT_EDITOR}});
  },[client,token]);
  const updateSupplyEditor=useCallback((interfaceId:"SI09"|"SI10",changes:Partial<SupplyQualityEditor>)=>{
    setSupplyEditors(current=>current.client===client&&current.token===token?{...current,[interfaceId]:{...current[interfaceId],...changes}}:current);
  },[client,token]);
  const updateImportEditor=useCallback((changes:Partial<SupplyImportEditor>)=>{
    setSupplyEditors(current=>current.client===client&&current.token===token?{...current,import:{...current.import,...changes}}:current);
  },[client,token]);
  const currentSupply=supplyEditors.client===client&&supplyEditors.token===token?supplyEditors:null;
  const supplyInterface=page==="F14"?"SI09":"SI10";
  const supplyEditor=currentSupply?.[supplyInterface]??EMPTY_SUPPLY_EDITOR;
  const importEditor=currentSupply?.import??EMPTY_IMPORT_EDITOR;
  const supplyDirty=["F14","F21"].includes(page)&&Boolean(supplyEditor.pending||supplyEditor.pendingPreparation||supplyEditor.prepared||supplyEditor.originId||supplyEditor.purpose||supplyEditor.due||supplyEditor.evidence||supplyEditor.coordinatorId||supplyEditor.timezone||supplyEditor.approvedFor);
  const importDirty=page==="A03"&&Boolean(importEditor.text||importEditor.pending);
  const [pendingNavigation, setPendingNavigation] = useState<{id:string;focus:string;taskId?:string;sopId?:string;menu?:boolean}|null>(null);
  const [pendingLeaveAction,setPendingLeaveAction]=useState<(()=>void)|null>(null);
  const draftLeaveRef=useRef<DraftLeaveHandle|null>(null);
  const registerDraftLeave=useCallback((handle:DraftLeaveHandle|null)=>{draftLeaveRef.current=handle;},[]);
  const [sourceReviewDirty, setSourceReviewDirty] = useState(false);
  const updateAssignmentDraft = useCallback((field:keyof AssignmentDraft,value:string)=>{
    setAssignmentDraft(old=>({...old,[field]:value}));
    setAssignmentDirty(true);
  }, []);
  const [selectedTaskId, setSelectedTaskId] = useState(() => new URLSearchParams(window.location.search).get("bossTask") ?? "");
  const [draftToReview, setDraftToReview] = useState("");
  const [sourceId, setSourceId] = useState(()=>new URLSearchParams(window.location.search).get("bossSource")??"finance-note");
  const [sourceAnchor, setSourceAnchor] = useState<{
    source_id:string;version:string;start:number;end:number;
  }|null>(null);
  const [dashboard, setDashboard] = useState<Dashboard | null>(null);
  const [tasks, setTasks] = useState<Tasks | null>(null);
  const [maintenance, setMaintenance] = useState<Maintenance | null>(null);
  const [modelHealth, setModelHealth] = useState<ModelHealth | null>(null);
  const [ownerPlans, setOwnerPlans] = useState<OwnerPlanProjection | null>(null);
  const [meetingArrangement, setMeetingArrangement] = useState<MeetingArrangementProjection | null>(null);
  const [runtimeTask, setRuntimeTask] = useState<{taskId: string; runId: string} | null>(null);
  const [runtimeRunId, setRuntimeRunId] = useState("");
  const [selectedSop, setSelectedSop] = useState(() => {
    const value = new URLSearchParams(window.location.search).get("bossSop") ?? "";
    return /^SOP(?:0[1-9]|1[0-3])$/.test(value) ? value : "SOP03";
  });
  const [runtimeSopReference, setRuntimeSopReference] = useState(() => new URLSearchParams(window.location.search).get("bossSop") ?? "");
  const [sopStatusVersion, setSopStatusVersion] = useState(0);
  const mutateSop = useCallback(async (action: string, payload: Record<string, unknown>) => {
    const result = await client.requestMutation<Record<string, unknown>>("boss.sop." + action, payload);
    setSopStatusVersion(value => value + 1);
    return result;
  }, [client]);
  const [sourceReview, setSourceReview] = useState<AssignmentSourceReviewProjection | null>(null);
  const [sourceReviewLoading, setSourceReviewLoading] = useState(false);
  const [sourceReviewError, setSourceReviewError] = useState("");
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");
  const [, setAnimate] = useState<Animation>("idle");
  const nextRequest = useRef(0);
  const [requestVersion, setRequestVersion] = useState(0);
  const shellRef = useRef<HTMLDivElement | null>(null);
  const navigationFocus = useRef<HTMLElement | null>(null);
  const openDirectory = useCallback(() => {
    navigationFocus.current=document.activeElement instanceof HTMLElement?document.activeElement:null;
    setDirectoryOpen(true);
  }, []);
  useEffect(() => {
    if (!accountOpen) return;
    const close = (event: PointerEvent) => {
      const target = event.target;
      if (target instanceof Element && target.closest(".boss-user-area")) return;
      setAccountOpen(false);
    };
    const escape = (event: KeyboardEvent) => {
      if (event.key === "Escape") setAccountOpen(false);
    };
    window.addEventListener("pointerdown", close, true);
    window.addEventListener("keydown", escape);
    return () => {
      window.removeEventListener("pointerdown", close, true);
      window.removeEventListener("keydown", escape);
    };
  }, [accountOpen]);
  useEffect(() => {
    setAccountOpen(false);
  }, [page, role]);
  useEffect(() => {
    const shortcut = (event: KeyboardEvent) => {
      if (!role || event.repeat || event.isComposing || event.altKey || !(event.metaKey || event.ctrlKey) || event.key.toLowerCase() !== "k") return;
      if (document.querySelector('[role="dialog"][aria-modal="true"]')) return;
      event.preventDefault();openDirectory();
    };
    window.addEventListener("keydown",shortcut,true);
    return () => window.removeEventListener("keydown",shortcut,true);
  }, [role,openDirectory]);
  useEffect(() => {
    if (!(assignmentDirty || sourceReviewDirty || settingsDirty || workDirty || overviewDirty || queryDirty || supplyDirty || importDirty)) return;
    const protect = (event: BeforeUnloadEvent) => {event.preventDefault();event.returnValue="";};
    window.addEventListener("beforeunload",protect);
    return () => window.removeEventListener("beforeunload",protect);
  }, [assignmentDirty,sourceReviewDirty,settingsDirty,workDirty,overviewDirty,queryDirty,supplyDirty,importDirty]);

  useEffect(() => {
    const abort = new AbortController();
    jsonRequest<Identity>("/api/boss/identity", getToken, abort.signal)
      .then((identity) => {
        if (abort.signal.aborted) return;
        if (identity.role !== "BOSS" && identity.role !== "MAINTAINER") throw new Error("当前身份无法进入工作区");
        setRole(identity.role);
        setMvpScope(identity.execution_scope==="BOSS-MVP-1");
        setPriorityScope(identity.execution_scope==="BOSS-PRIORITY-ITERATION");
        setPage(initialPage(identity.role,identity.execution_scope==="BOSS-MVP-1",identity.execution_scope==="BOSS-PRIORITY-ITERATION"));
        setAuthError("");
      })
      .catch((err: unknown) => { if (!abort.signal.aborted) setAuthError(String(err instanceof Error ? err.message : err)); });
    return () => abort.abort();
  }, [getToken, authAttempt]);

  const navigate = useCallback((id: string, focus = "", bypassDirty = false, taskId?: string, sopId?: string,menu=false) => {
    if(role)id=bossPageId(id,role);
    if (!role || !allowed(id, role,mvpScope,priorityScope)) return;
    if (["NATIVE","N02"].includes(page) && id !== page && !bypassDirty) {
      onBeforeLeaveNative(() => navigate(id, focus, true, taskId, sopId,menu));
      return;
    }
    const changingTask = taskId !== undefined && taskId !== selectedTaskId;
    if (!bypassDirty && ((page === "F06" && sourceReviewDirty && (id !== page || changingTask)) || (page==="F06"&&changingTask&&(assignmentDirty||workDirty))||
        (id !== page && ((page === "F06" && assignmentDirty && !["D04","D05","D01"].includes(id)) ||
          (["N07","N08"].includes(page) && settingsDirty) ||
          workDirty||(page==="N03"&&overviewDirty)||(page==="F03"&&queryDirty)||supplyDirty||importDirty)))) {
      navigationFocus.current = document.activeElement instanceof HTMLElement ? document.activeElement : null;
      if(directoryOpen){
        const trigger=shellRef.current?.querySelector<HTMLButtonElement>('button.boss-search');
        if(!trigger)throw new Error("页面目录缺少返回焦点入口");
        navigationFocus.current=trigger;
      }
      setDirectoryOpen(false);
      setPendingNavigation({id,focus,taskId,sopId,menu});
      return;
    }
    if (id !== page) setPreviousPage(page);
    if(id!==page)setOverviewPreparation(null);
    if(id==="F01"&&!mvpScope)setSidebarOpen(true);
    if (["NATIVE","N02"].includes(id) && !["NATIVE","N02"].includes(page)) {
      businessPage.current = page;
      onOpenNative(role);
    }
    if (id !== page && ["N07","N08"].includes(page)) setSettingsDirty(false);
    if (id !== page) setWorkDirty(false);
    const url = menu?menuPageUrl(window.location.href,id,role):new URL(window.location.href);
    url.searchParams.set("bossPage", id);
    if(menu){conversationReturn.current=false;setSourceAnchor(null);if(id==="D01")setSourceId(readBossLocation(url,role).sourceId);}
    if(conversationReturn.current)url.searchParams.set("bossConversationReturn","N02");
    if (["NATIVE","N02"].includes(id)) url.searchParams.set("bossReturn", page);
    if(!menu&&(taskId ?? selectedTaskId))url.searchParams.set("bossTask",taskId ?? selectedTaskId);
    if(taskId==="")url.searchParams.delete("bossTask");
    if(id==="D01")url.searchParams.set("bossReturn",page);
    const sopReference = id === "A06" ? selectedSop : id === "A15" ? sopId ?? "" : "";
    if (sopReference) url.searchParams.set("bossSop", sopReference);
    else url.searchParams.delete("bossSop");
    setRuntimeSopReference(id === "A15" ? sopReference : "");
    pushBossHistory(url);
    if (taskId !== undefined) setSelectedTaskId(taskId);
    if (id !== page || changingTask) setSourceReviewDirty(false);
    setPage(id);
    setError("");
    setDirectoryOpen(false);
  }, [page, role, assignmentDirty, sourceReviewDirty, selectedTaskId, selectedSop, settingsDirty, workDirty,overviewDirty,queryDirty,supplyDirty,importDirty,directoryOpen,mvpScope,priorityScope,onOpenNative,onBeforeLeaveNative]);

  const openMenu=(id:string)=>navigate(id,"",false,id==="F06"?"":undefined,undefined,true);

  const guardLeave=useCallback((leave:()=>void)=>{
    if(["NATIVE","N02"].includes(page)){onBeforeLeaveNative(leave);return;}
    if(assignmentDirty||sourceReviewDirty||settingsDirty||workDirty||overviewDirty||queryDirty||supplyDirty||importDirty){
      navigationFocus.current=document.activeElement instanceof HTMLElement?document.activeElement:null;
      setPendingLeaveAction(()=>leave);
    }else leave();
  },[page,assignmentDirty,sourceReviewDirty,settingsDirty,workDirty,overviewDirty,queryDirty,supplyDirty,importDirty,onBeforeLeaveNative]);
  const businessConversation=useBusinessConversationEntry({role,getToken,onCreateChat:onCreateTaskConversation,
    onOpenChat:chatId=>{onOpenTaskConversation(chatId);navigate("N02","N03",true);},onBeforeStart:guardLeave});
  const requestLogout=useCallback(()=>guardLeave(onLogout),[guardLeave,onLogout]);
  const historyCallbacks=useRef({guardLeave,page});
  historyCallbacks.current={guardLeave,page};
  useEffect(()=>{
    onRegisterCloseGuard(guardLeave);
    return()=>onRegisterCloseGuard(null);
  },[guardLeave,onRegisterCloseGuard]);

  const sopChanged = useCallback((sopId: string) => {
    setSelectedSop(sopId);
    if (page === "A06") {
      const url = new URL(window.location.href); url.searchParams.set("bossSop", sopId);
      replaceBossHistory(url);
    }
  }, [page]);

  useEffect(() => {
    if(!role)return;
    return bindBossHistory(window,(url,proceed)=>{
      const current=historyCallbacks.current;
      if(readBossLocation(url,role).page!==current.page)current.guardLeave(proceed);else proceed();
    },url=>{
      const location=readBossLocation(url,role);
      setSelectedTaskId(location.taskId);setSourceId(location.sourceId);setSourceAnchor(null);
      setPreviousPage(location.returnPage);
      conversationReturn.current=url.searchParams.get("bossConversationReturn")==="N02";
      if(["NATIVE","N02"].includes(location.page))businessPage.current=location.returnPage;
      if(location.page==="A06"&&/^SOP(?:0[1-9]|1[0-3])$/.test(location.sopId))setSelectedSop(location.sopId);
      setRuntimeSopReference(location.page==="A15"?location.sopId:"");
      setOverviewPreparation(null);setPage(location.page);setError("");
    });
  },[role]);

  useEffect(() => {
    if (!role || ["NATIVE","N02"].includes(page)) return;
    const id = ++nextRequest.current;
    const abort = new AbortController();
    const tasksToRead: Promise<void>[] = [];
    const read = <T,>(url: string, set: (v: T) => void) => {
      tasksToRead.push(jsonRequest<T>(url, getToken, abort.signal).then((value) => {
        if (id === nextRequest.current) set(value);
      }));
    };
    if (role === "BOSS") {
      if (page === "N09") read<OwnerPlanProjection>("/api/boss/ui/owner-plans", setOwnerPlans);
      if (page === "F04") read<MeetingArrangementProjection>("/api/boss/ui/meeting-arrangement", setMeetingArrangement);
      if (["F01", "MVP01", "N05", "F06", "D04", "D05", "N07", "N09"].includes(page)) read<Dashboard>("/api/boss/ui/dashboard", setDashboard);
      if (["N05", "N06", "F06"].includes(page)) read<Tasks>("/api/boss/ui/tasks", setTasks);
    } else if (["A04", "A08", "A01", "A15", "F30"].includes(page)) {
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
    setSourceReview(null); setSourceReviewError("");
    if (role !== "BOSS" || page !== "F06" || !selectedTaskId) {setSourceReviewLoading(false); return;}
    const abort = new AbortController();
    setSourceReviewLoading(true);
    void jsonRequest<AssignmentSourceReviewProjection>("/api/boss/ui/assignment-source-review?task_id=" +
      encodeURIComponent(selectedTaskId), getToken, abort.signal).then(result => {
      if (abort.signal.aborted) return;
      if (result.source_type !== "SIMULATED" || result.task.task_id !== selectedTaskId)
        throw new Error("交办来源返回范围无效");
      setSourceReview(result); setSourceReviewLoading(false);
    }).catch((failure: unknown) => {
      if (abort.signal.aborted) return;
      setSourceReview(null); setSourceReviewLoading(false);
      setSourceReviewError(failure instanceof Error ? failure.message : String(failure));
    });
    return () => abort.abort();
  }, [getToken, page, role, selectedTaskId, requestVersion]);

  const referenceMenu = role==="BOSS"&&!mvpScope;
  const fromOverview=new URLSearchParams(window.location.search).get("overviewReturn")==="N03";
  const currentEntry=role?deliveredPage(page,role,mvpScope):undefined;
  const metadata = currentEntry?.state==="AUTHENTICATION"?{...pages[page],title:"当前登录状态",summary:"查看当前身份，需要切换账号时可以退出并返回登录表单。"}:page === "NATIVE" ? {
    ...pages.N01,
    title: role === "BOSS" ? "Boss Agent 会话" : "应用设置",
    module: role === "BOSS" ? "会话" : "应用设置",
    summary: role === "BOSS" ? "继续当前会话，核查回复与工具结果。" : "使用当前维护身份管理应用设置。",
    initial_state: "当前身份与原生连接保持",
  } : page==="F27"?{...pages.F27,summary:"语音服务当前暂停；录音、上传与转写不会启动，可以使用文字交办。",initial_state:"语音服务已暂停"} : page==="F11"?{...pages.F11,initial_state:"按当前行程读取状态"}:page==="F32"?{...pages.F32,initial_state:"运行条件按当前实例检查结果核查"}:page==="MVP01"?{...pages.F01,title:"采购成本协调",module:"采购成本协调",summary:"核查当前采购报告的成本变化、原文与本人协调记录。"}:pages[page];
  const refreshLabel:Record<string,string>={F04:"刷新会议材料",F05:"刷新版本",F07:"刷新申请",N04:"刷新目录",N05:"刷新任务",N06:"刷新通知",F02:"刷新这条提醒",F08:"刷新消息记录",F13:"刷新记忆",F24:"刷新状态",F29:"刷新状态",A03:"刷新数据集",A07:"刷新资料",F14:"刷新资料",F15:"刷新资料",F16:"刷新资料",F17:"刷新资料",F21:"刷新品质资料"};
  const currentRefreshLabel=refreshLabel[page]??"刷新";
  const isNative = ["NATIVE","N02"].includes(page);
  const refresh = () => setRequestVersion((v) => v + 1);
  const scopedCommand = async (action: string, payload: Record<string, unknown>): Promise<void> => {
    if (typeof payload.client_request_id !== "string") throw new Error("业务请求缺少原请求编号");
    const receipt = await jsonRequest<{outcome: string}>(
      "/api/boss/ui/operation-status?action=" + encodeURIComponent(action) + "&client_request_id=" + encodeURIComponent(payload.client_request_id), getToken);
    if (receipt.outcome === "RECORDED") return;
    if (receipt.outcome !== "NOT_FOUND_IN_CURRENT_STORE") throw new Error("原请求结果尚未确定");
    await client.requestMutation(action, payload);
  };
  const goSource = (id = "finance-note", anchor?:{
    version:string;start:number;end:number;
  },referenceVersion?:string) => {
    guardLeave(()=>{
      setSourceId(id);
      const url=new URL(window.location.href);url.searchParams.set("bossSource",id);
      for(const key of ["bossSourceVersion","bossSourceStart","bossSourceEnd","bossSourceReferenceVersion"])url.searchParams.delete(key);
      if(anchor){url.searchParams.set("bossSourceVersion",anchor.version);url.searchParams.set("bossSourceStart",String(anchor.start));url.searchParams.set("bossSourceEnd",String(anchor.end));}
      if(referenceVersion)url.searchParams.set("bossSourceReferenceVersion",referenceVersion);
      replaceBossHistory(url);
      setSourceAnchor(anchor?{source_id:id,...anchor}:null);
      navigate("D01", page,true);
    });
  };
  const selectTask = (id: string,bypassDirty=false) => navigate("F06", page, bypassDirty, id);
  const markOverviewReturn=()=>{const address=new URL(window.location.href);address.searchParams.set("overviewReturn","N03");replaceBossHistory(address);};
  const returnOverview=()=>guardLeave(()=>{const address=new URL(window.location.href);address.searchParams.delete("overviewReturn");replaceBossHistory(address);navigate("N03","",true);});

  if (!role) return <div className="boss-gate">
    <img src="/boss-brand/dapeng-front.png" alt="" />
    <h1>Boss Agent</h1>
    <p>{authError || "正在验证账号…"}</p>
    {authError ? <div className="boss-actions">
      <GlassButton onClick={() => { setAuthError(""); setAuthAttempt((v) => v + 1); }}>重新核验</GlassButton>
      <GlassButton onClick={requestLogout}>返回登录</GlassButton>
    </div> : <Loader2 size={22} className="boss-spin" aria-hidden="true" />}
  </div>;

  if(page==="UNAVAILABLE")return <div className="boss-v6" data-role={role}><section className="boss-panel boss-unavailable" aria-label="当前入口不可用"><h1>当前身份无法打开此页面</h1><p>页面编号未知或不属于当前身份的菜单范围。请返回相应工作区。</p><div className="boss-actions"><button className="boss-btn" onClick={()=>navigate(role==="BOSS"?"F01":"A08")}>返回工作区</button><button className="boss-btn" onClick={requestLogout}>退出当前身份</button></div></section></div>;
  return <div className="boss-v6" data-design="v7" data-role={role} data-page={page} ref={shellRef}>
    <a className="boss-skip-link" href="#boss-main">跳转至当前工作内容</a>
    <BossNotificationReturn role={role} onOpen={target=>{const url=new URL(window.location.href);if(target.page_id==="D09"&&target.record_id){url.searchParams.set("bossHistoryRecord",target.record_id);}else{url.searchParams.delete("bossHistoryRecord");url.searchParams.set("bossEvent",target.event_id);url.searchParams.set("bossEventVersion",target.event_version);}replaceBossHistory(url);navigate(target.page_id);window.dispatchEvent(new Event("boss-notification-target-changed"));}}/>
    <div className="boss-frame">
      <div className={"boss-layout " + (!sidebarOpen ? "boss-layout-slim" : "")}>
        <aside className="boss-sidebar" aria-label={role === "BOSS" ? "老板工作区" : "技术维护工作区"}>
          <div className="boss-brand">
            <img src="/boss-brand/boss-logo-from-reference.png" alt="Boss Agent 标识" />
            {sidebarOpen && <strong>Boss Agent</strong>}
          </div>
          {sidebarOpen && <p className="boss-brand-caption">让重要的事，推进得更确定</p>}
          <div className="boss-sidebar-label">{sidebarOpen ? (role === "BOSS" ? "老板工作区" : "技术维护工作区") : "◈"}</div>
          <BossPrimaryNavigation role={role} page={page} expanded={sidebarOpen} onNavigate={openMenu} referenceIcon={referenceMenu?id=><ReferenceNavigationIcon id={id}/>:undefined}/>
          <div className="boss-sidebar-bottom">
            {(page!=="F01"||mvpScope)&&<button type="button" onClick={() => setSidebarOpen(!sidebarOpen)} title={sidebarOpen ? "收起导航" : "展开导航"}>
              <Menu size={17} aria-hidden="true" />{sidebarOpen && "收起导航"}
            </button>}
          </div>
        </aside>
        <main className="boss-main" id="boss-main">
          <header className="boss-topbar">
            <button className="boss-mobile-menu" type="button" onClick={openDirectory}
              aria-label="打开页面目录"><Menu size={19}/></button>
            <button className="boss-search" type="button" onClick={openDirectory}>
              {["F01","N03"].includes(page)&&referenceMenu?<ReferenceHeaderIcon kind="search"/>:<Search size={17}/>}<span>搜索功能或事项</span><kbd>⌘ K</kbd>
            </button>
            <div className="boss-topright">
              <button type="button" className="boss-icon-button" title="全局刷新" aria-label="全局刷新" onClick={()=>guardLeave(()=>window.location.reload())}><RefreshCw size={18}/></button>
              {role==="MAINTAINER"&&<Tag tone="amber">模拟业务资料</Tag>}
              {role==="BOSS"&&<button type="button" className="boss-icon-button" title="任务通知" aria-label="任务通知"
                onClick={() => {const url=new URL(window.location.href);url.searchParams.set("taskTab","通知");replaceBossHistory(url);navigate("N06");}}>{["F01","N03"].includes(page)&&referenceMenu?<ReferenceHeaderIcon kind="notification"/>:<Bell size={18}/>}</button>}
              <div className="boss-user-area">
                <button type="button" className="boss-user" aria-expanded={accountOpen} aria-haspopup="menu"
                  onClick={()=>setAccountOpen(value=>!value)}>
                  <span className="boss-user-avatar">{role === "BOSS" ? "本人" : "维护"}</span>
                  <span>{role === "BOSS" ? "老板本人" : "技术管理员"}<small>{role === "BOSS" ? "已认证" : "维护身份"}</small></span>
                </button>
                {accountOpen&&<div className="boss-account-menu" role="menu" aria-label="账号与设置">
                  {role==="BOSS"&&<button type="button" role="menuitem" onClick={()=>{setAccountOpen(false);navigate("N08");}}>通知设置</button>}
                  <button type="button" role="menuitem" onClick={()=>{setAccountOpen(false);navigate(role==="BOSS"?"F26":"N12");}}><Settings size={16}/>{role==="BOSS"?"账号与设置":"实例与访问"}</button>
                  <button type="button" role="menuitem" onClick={()=>{setAccountOpen(false);requestLogout();}}>退出登录</button>
                </div>}
              </div>
            </div>
          </header>
          <section className="boss-stage">
            <div className={"boss-hero " + (["F01","N02","N03"].includes(page) ? "" : "boss-hero-compact")}>
              <div className="boss-hero-copy">
                <div className="boss-eyebrow" aria-label="当前位置">{role === "BOSS" ? "老板工作台" : "技术维护"} / {metadata?.module || "工作区"}</div>
                <h1>{page === "F01" ? mvpScope?"今日采购成本事项":businessGreeting(dashboard?.business_clock,dashboard?.profile.timezone) : metadata?.title || "工作页面"}</h1>
                <p>{mvpScope&&page==="F01"?"核查同一采购报告的成本变化、原文与本人协调记录。":metadata?.summary || "按照 PRD 查看当前执行过程和资料来源。"}</p>
              </div>
              <img src={page==="N02"?"/boss-brand/dapeng-side.png":["F05","F13","F24","F29"].includes(page) ? "/boss-brand/dapeng-think.png" : ["F06","F07","F14","F15","F16","F17","F18","F19","F20","F21","F22","F23"].includes(page) ? "/boss-brand/dapeng-execute.png" : "/boss-brand/dapeng-front.png"} className="boss-hero-mascot" alt="Boss Agent 吉祥物" />
            </div>
            <section className="boss-native-surface" hidden={!isNative} aria-label={role === "BOSS" ? "聊天交办内容" : "应用设置内容"}>
              {role==="MAINTAINER"&&<div className="boss-native-context"><button className="boss-btn" type="button" onClick={() => navigate(businessPage.current??"A08")}><ArrowLeft size={16}/>返回业务页面</button><span>当前身份：技术维护</span></div>}
              {children(role,isNative,{onOpenTask:id=>{conversationReturn.current=true;setMorningOrigin(null);setMorningContext(null);setMorningReady(false);if(!id){setAssignmentDraft({...DEFAULT_ASSIGNMENT_DRAFT});setAssignmentDirty(false);}selectTask(id);},onOpenSource:(id,version)=>{conversationReturn.current=true;goSource(id,undefined,version);},onOpenMessages:()=>{conversationReturn.current=true;navigate("F08",page);},onOpenPage:(target,runId)=>guardLeave(()=>{
                conversationReturn.current=true;
                const address=new URL(window.location.href);
                if(runId)address.searchParams.set("bossRun",runId);else address.searchParams.delete("bossRun");
                for(const key of ["bossIssue","bossOwnerRecord","bossTask","overviewReturn","overviewQuerySnapshot"])address.searchParams.delete(key);
                const state={...window.history.state};delete state.bossRunView;delete state.bossIssueView;delete state.bossOwnerRecords;
                window.history.replaceState(state,"",address);
                navigate(target,page,true,"");
              }),onReturn:()=>navigate(businessPage.current??(previousPage!=="NATIVE"&&previousPage!=="N02"&&allowed(previousPage,role,mvpScope,priorityScope)?previousPage:role==="BOSS"?"F01":"A08"))})}
            </section>
            {role==="BOSS"&&!mvpScope&&<div className="boss-content boss-morning-content" hidden={page!=="F01"}>
              <BossMorningView key={morningDiscardVersion} refreshVersion={requestVersion} visible={page==="F01"} onDirtyChange={setWorkDirty} contacts={dashboard?.contacts??[]}
                onStartConversation={async(value,signal)=>{const result=await onStartMorning(value,signal);if(!signal.aborted)navigate("NATIVE","",true);return result;}}
                onOpenConversation={chatId=>{onOpenMorning(chatId);navigate("NATIVE","",true);}}
                onNavigate={(target,objectId)=>target==="F06"?selectTask(objectId):navigate(target,objectId)}
                onPrepare={(item,reference)=>{setMorningOrigin(reference);setMorningReady(false);if(item.page_id==="F06")selectTask(item.object_id);else{updateAssignmentDraft("purpose",item.title);navigate("F06",item.object_id,false,"");}}}/>
            </div>}
            {role==="BOSS"&&!mvpScope&&<div className="boss-content boss-overview-content" hidden={page!=="N03"}>
              <BossBusinessOverview visible={page==="N03"} refreshVersion={requestVersion} discardVersion={overviewDiscardVersion} onDirtyChange={setOverviewDirty}
                onTopic={selection=>{if(!selection.page_id)throw new Error("经营专题入口缺少页面编号");markOverviewReturn();const address=new URL(window.location.href);address.searchParams.set("overviewSectorReference",JSON.stringify(selection));replaceBossHistory(address);navigate(selection.page_id==="F19"&&selection.use&&selection.use!=="BROILER"?"V19-"+selection.use:selection.page_id);}}
                onViewSource={id=>{markOverviewReturn();goSource(id);}}
                onQuery={view=>{markOverviewReturn();const address=new URL(window.location.href);address.searchParams.set("overviewQuerySnapshot",view.snapshot_sha256);address.searchParams.delete("biRequest");address.searchParams.delete("biScenario");replaceBossHistory(address);navigate("F03");}}
                onReminder={alert=>{markOverviewReturn();const address=new URL(window.location.href);address.searchParams.set("bossEvent",alert.event_id);address.searchParams.set("bossEventVersion",alert.event_version);replaceBossHistory(address);navigate("F02");window.dispatchEvent(new Event("boss-notification-target-changed"));}}
                onTask={task=>{markOverviewReturn();selectTask(task.id);}} onDiscuss={businessConversation.start} conversationStatus={<>{businessConversation.status}{savedOverviewPreparation()&&<button className="boss-btn" onClick={()=>setOverviewPreparation(savedOverviewPreparation())}>核查原经营准备</button>}</>} onPrepare={(detail,use)=>setOverviewPreparation({scope:detail.applied_scope,page_id:detail.topic.page_id,use,snapshot_sha256:detail.snapshot_sha256})}/>
              {page==="N03"&&overviewPreparation&&<BusinessOverviewPreparation selection={overviewPreparation} onClose={()=>setOverviewPreparation(null)} onOpenTask={id=>{markOverviewReturn();selectTask(id);}}/>}
            </div>}
            {!isNative && !(role==="BOSS"&&!mvpScope&&["F01","N03"].includes(page)) && <div className="boss-content" key={page}>
              {!["N04","N05","N06"].includes(page)&&<div className="boss-meta-strip">
                <div className="boss-state-line">
                  <span>{currentEntry?.state==="AUTHENTICATION"?"当前身份已经认证":metadata?.initial_state || "业务状态待读取"}</span>
                </div>
                <div className="boss-meta-actions">
                  {role==="BOSS"&&conversationReturn.current&&<button className="boss-btn" type="button" onClick={()=>navigate("N02")}><ArrowLeft size={15}/>返回原会话</button>}
                  {role==="BOSS"&&!conversationReturn.current&&page!=="F01"&&previousPage==="F01"&&<button className="boss-btn" type="button" onClick={()=>navigate("F01")}><ArrowLeft size={15}/>返回今日工作</button>}
                  {role==="BOSS"&&!conversationReturn.current&&page==="F04"&&<button className="boss-btn" type="button" onClick={()=>navigate("N04")}><ArrowLeft size={15}/>返回会议与资料</button>}
                  {role==="BOSS"&&fromOverview&&<button className="boss-btn" type="button" onClick={returnOverview}><ArrowLeft size={15}/>返回经营关注</button>}
                  {role==="BOSS"&&!(currentEntry?.state==="AUTHENTICATION"||["A13","A14","A15","F30","N10","N11","F28","D02","D09"].includes(page))&&<button type="button" onClick={refresh} disabled={loading} aria-label="刷新当前页面的业务数据" aria-busy={loading}>
                    <RefreshCw size={15} className={loading ? "boss-spin" : ""}/> {loading ? "刷新中…" : currentRefreshLabel}
                  </button>}
                </div>
              </div>}
              {error && <StatusLine variant="error" text={"业务读取失败：" + error + "。已保留先前可见结果，不会自动执行写入。"} />}
              {loading && <StatusLine text="正在读取当前数据与状态…" />}
              {currentEntry?.state==="AUTHENTICATION"?<div className="boss-columns"><div className="boss-column"><Panel title="当前认证状态"><Value label="当前身份" value={role==="BOSS"?"本人":"技术维护"}/><p>当前账号已经登录。切换身份需要退出当前账号，然后使用登录表单。</p><GlassButton onClick={requestLogout}>退出登录</GlassButton></Panel></div></div>:
                currentEntry?.state==="PAUSED"?<BossVoicePaused onNavigate={id=>navigate(id)}/>:
                page==="D06"?<BossUnsavedWorkspace role={role} onNavigate={id=>navigate(id)}/>:
                page==="D07"?<BossRestrictedView role={role} onNavigate={id=>navigate(id)}/>:
                role === "BOSS" ? (
                (page === "MVP01"||page==="F01"&&mvpScope) ? <BossMVPView contacts={dashboard?.contacts??[]} refreshVersion={requestVersion} onDirtyChange={setWorkDirty} onOpenTask={priorityScope?selectTask:undefined}/> :
                page==="F03" ? fromOverview?<BusinessOverviewQuery getToken={getToken} onSource={goSource} onReturn={returnOverview} onDirtyChange={setQueryDirty} refreshVersion={requestVersion}/>:<BossBIView getToken={getToken} onSource={goSource} onDirtyChange={setQueryDirty} refreshVersion={requestVersion}/> :
                page === "F06" ? <>{morningOrigin&&<BossMorningPreparation reference={morningOrigin} onReady={setMorningReady} onContext={setMorningContext} onReturn={()=>navigate("F01")} refreshVersion={requestVersion}/>}<BossAssignmentFlow
                  morningReference={morningOrigin??undefined} morningReady={morningReady} morningContext={morningContext}
                  messagesEnabled={!priorityScope}
                  tasks={tasks} selectedTaskId={selectedTaskId}
                  onSelectTask={selectTask} onReload={refresh}
                  onViewSource={id => goSource(id??"finance-note")} context={dashboard}
                  draft={assignmentDraft} onDraftChange={updateAssignmentDraft}
                  onDraftSaved={()=>{setAssignmentDraft({...DEFAULT_ASSIGNMENT_DRAFT});setAssignmentDirty(false);}}
                  loading={loading} onDirtyChange={setWorkDirty} onNavigate={id=>navigate(id)}
                  onDiscard={()=>{setAssignmentDraft({...DEFAULT_ASSIGNMENT_DRAFT});setAssignmentDirty(false);}}
                  onNew={origin=>guardLeave(()=>{setAssignmentDraft({...DEFAULT_ASSIGNMENT_DRAFT,relatedTask:origin?.task_id??"",relatedTaskVersion:origin?.version??""});setAssignmentDirty(Boolean(origin));selectTask("",true);})}
                  onOpenCoordinatorPicker={()=>navigate("D04")}
                  onOpenDuePicker={()=>navigate("D05")}
                  onViewMessages={()=>navigate("F08")}
                  onMessageDraftCreated={setDraftToReview}
                  conversation={<BossTaskConversationEntry task={tasks?.tasks.find(task=>task.task_id===selectedTaskId)??null} getToken={getToken}
                  onBeforeStart={start=>{
                    if(assignmentDirty||sourceReviewDirty||workDirty){navigationFocus.current=document.activeElement instanceof HTMLElement?document.activeElement:null;setPendingLeaveAction(()=>start);}
                    else start();
                  }} onCreateChat={onCreateTaskConversation}
                  onOpenChat={chatId=>{onOpenTaskConversation(chatId);navigate("N02","F06",true);}}
                  onReturnTask={id=>selectTask(id)}/>}
                  sourceReview={selectedTaskId && <BossAssignmentSourceReview key={selectedTaskId} data={sourceReview}
                  loading={sourceReviewLoading} error={sourceReviewError} onReload={refresh} onCommand={scopedCommand}
                  onReceipt={(action, clientRequestId) => jsonRequest("/api/boss/ui/operation-status?action=" +
                    encodeURIComponent(action) + "&client_request_id=" + encodeURIComponent(clientRequestId), getToken)}
                  onOpenSource={id => goSource(id)} onDirtyChange={setSourceReviewDirty}/>}
                /></> :
                (page==="D04"||page==="D05") ? <BossAssignmentPicker
                  key={page} pageId={page} contacts={dashboard?.contacts||[]}
                  timezone={dashboard?.profile.timezone}
                  businessClock={dashboard?.business_clock} draft={assignmentDraft}
                  taskId={selectedTaskId} taskVersion={tasks?.tasks.find(task=>task.task_id===selectedTaskId)?.version} loading={loading}
                  onChange={updateAssignmentDraft} onDirtyChange={setWorkDirty} onReturn={()=>navigate("F06","",true)}
                /> :
                (page === "N05"||page === "N06") ? <BossTaskCenter key={page}
                  data={tasks} selectedTaskId={selectedTaskId} contacts={dashboard?.contacts??[]} refreshVersion={requestVersion} notifications={page==="N06"}
                  onSelectTask={id=>{setSelectedTaskId(id);const url=new URL(window.location.href);url.searchParams.set("bossTask",id);replaceBossHistory(url);}}
                  onOpenTask={selectTask}
                  onCreateTask={()=>guardLeave(()=>{setAssignmentDraft({...DEFAULT_ASSIGNMENT_DRAFT});setAssignmentDirty(false);selectTask("",true);})}
                  onNavigate={id=>navigate(id)} onReload={refresh} onDirtyChange={setWorkDirty}
                /> :
                page === "N04" ? <BossMeetingLibrary refreshVersion={requestVersion} onViewSource={goSource} onOpen={(action,reference)=>{const url=new URL(window.location.href);url.searchParams.set("bossLibraryContext",JSON.stringify(reference));url.searchParams.set("bossLibraryAction",action.id);replaceBossHistory(url);navigate(action.page);}}/> :
                page==="D03" ? <BossExecutionRecovery taskId={selectedTaskId} onOpenTask={selectTask} onNavigate={id=>navigate(id)}/> :
                page==="F29" ? <BossTaskExceptions taskId={selectedTaskId} onOpenTask={selectTask} onNavigate={id=>navigate(id)} onViewSource={goSource} refreshVersion={requestVersion}/> :
                page==="F13" ? <BossPersonalMemory onNavigate={id=>navigate(id)} onViewSource={goSource} onDirtyChange={setWorkDirty} refreshVersion={requestVersion}/> :
                ["N10","N11","F28","D02","D09"].includes(page) ? <BossOwnerRecords key={page} pageId={page} onNavigate={id=>navigate(id)} onOpenTask={selectTask} onViewSource={goSource}/> :
                page==="F24" ? <BossRunDetails taskId={selectedTaskId} onNavigate={id=>navigate(id)} onOpenTask={selectTask} onViewSource={goSource} refreshVersion={requestVersion}/> :
                page === "D01" ? <BossSourceView key={sourceId} sourceId={sourceId} anchor={sourceAnchor} originPage={previousPage} refreshVersion={requestVersion} onReturn={()=>navigate(allowed(previousPage,role,mvpScope,priorityScope)?previousPage:"F01")}/> :
                (page==="F14"||page==="F21") ? <BossSupplyQualityView key={page} interfaceId={supplyInterface}
                  editor={supplyEditor} onEditorChange={changes=>updateSupplyEditor(supplyInterface,changes)}
                  refreshVersion={requestVersion} onDirtyChange={setWorkDirty}
                  onOpenSource={goSource} onOpenTask={taskId=>navigate("F06","",false,taskId)}/> :
                (SECTOR_PAGE_IDS as readonly string[]).includes(page) ? <BossSectorView
                  key={page} pageId={page} onNavigate={id=>navigate(id,"",true)} onBeforeLeave={guardLeave}
                  onViewSource={goSource} onStartChat={onStartChat}
                  onDirtyChange={setWorkDirty} onOpenTask={selectTask} refreshVersion={requestVersion}
                /> :
                page === "F12" ? <BossPrivateCalendar key={page} onNavigate={id=>navigate(id)} onViewSource={goSource} onDirtyChange={setWorkDirty} refreshVersion={requestVersion}/> :
                page === "F08" ? <BossCommunicationCalendar
                  key={page} pageId={page} onViewSource={goSource}
                  onNavigate={id=>navigate(id)} focusDraftId={draftToReview}
                  onDirtyChange={setWorkDirty} onOpenTask={selectTask} refreshVersion={requestVersion} onDraftLeaveChange={registerDraftLeave}
                  onFocusDraftConsumed={()=>setDraftToReview("")}
                /> :
                page === "F26" ? <BossSettingsHub
                  key={page} onNavigate={id=>navigate(id)} onLogout={requestLogout} refreshVersion={requestVersion}
                /> :
                (page === "N07" || page === "N08") ? <BossOwnerPreferences
                  key={page} pageId={page} onNavigate={id=>navigate(id)}
                  onDirtyChange={setSettingsDirty} refreshVersion={requestVersion}
                /> :
                page === "F09" ? <BossResearchView
                  key={page} onNavigate={id=>navigate(id)}
                  onViewSource={goSource} onStartChat={onStartChat}
                  onDirtyChange={setWorkDirty} refreshVersion={requestVersion}
                /> :
                page === "F10" ? <BossPeopleMeeting
                  key={page} onNavigate={id=>navigate(id)} onViewSource={goSource}
                  onOpenTask={selectTask} onDirtyChange={setWorkDirty} refreshVersion={requestVersion}
                /> :
                page === "F11" ? <BossTravelView
                  key={page} onNavigate={id=>navigate(id)} onViewSource={goSource} onOpenTask={selectTask}
                  onDirtyChange={setWorkDirty} refreshVersion={requestVersion}
                /> :
                page === "F04" ? <BossMeetingBrief
                  key={page} onNavigate={id=>navigate(id)} onViewSource={goSource}
                  onMessageDraftCreated={setDraftToReview}
                  refreshVersion={requestVersion} onOpenTask={selectTask} onDirtyChange={setWorkDirty}
                  arrangement={meetingArrangement} arrangementLoading={loading} arrangementError={error} onReloadArrangement={refresh}
                /> :
                (page === "F05" || page === "F07") ? <BossMeetingApprovalView
                  key={page} pageId={page}
                  onViewSource={goSource}
                  onNavigate={id=>navigate(id)}
                  onTaskCreated={id=>{setSelectedTaskId(id);refresh();}}
                  onDirtyChange={setWorkDirty} refreshVersion={requestVersion} onDraftLeaveChange={registerDraftLeave}
                /> :
                page === "N09" ? <BossOwnerPlans data={ownerPlans} loading={loading} error={error}
                  onReload={refresh} onDirtyChange={setWorkDirty}/> :
                page==="F02"&&fromOverview?<BusinessOverviewAlert refreshVersion={requestVersion} onNavigate={id=>navigate(id)} onOpenTask={selectTask} onDirtyChange={setWorkDirty}/>:
                page==="F02"?<BossReminderWorkspace refreshVersion={requestVersion} onNavigate={id=>navigate(id)} onOpenTask={selectTask} onViewSource={goSource} onDirtyChange={setWorkDirty}/>:
                WORKSPACE_PAGE_ROUTES[page] ? <BossWorkspaceView
                  key={page} role={role} pageId={page} refreshVersion={requestVersion}
                onOpenTask={selectTask} onDirtyChange={setWorkDirty}
                  onNavigate={id=>navigate(id)} onViewSource={goSource}
                /> :
                unsupportedPage(page)
              ) : page === "N12" ? <BossRuntimeOverview getToken={getToken} identityKey={token??""} onNavigate={id=>navigate(id)} onOpenRun={id=>{setRuntimeRunId(id);navigate("A15");}}/>
              : page==="A01"||page==="A09" ? <MaintainerConfiguration key={page} domain={page==="A01"?"access":"tools"} onNavigate={id=>navigate(id)} onDirtyChange={setWorkDirty}/>
              : page==="A10" ? <MaintainerMetricsConfiguration onNavigate={id=>navigate(id)} onDirtyChange={setWorkDirty}/>
              : page==="A11" ? <MaintainerContactsWorkspace onNavigate={id=>navigate(id)} onDirtyChange={setWorkDirty} onViewSource={goSource}/>
              : page==="A14" ? <MaintainerAudit onNavigate={id=>navigate(id)} onOpenRun={id=>{setRuntimeRunId(id);navigate("A15");}}/>
              : ["A16","F31"].includes(page) ? <MaintainerEvaluation key={page} pageId={page==="A16"?"A16":"F31"} onNavigate={id=>navigate(id)} onDirtyChange={setWorkDirty} onOpenRun={id=>{setRuntimeRunId(id);navigate("A15");}}/>
              : page==="F32" ? <MaintainerLocalSystem onNavigate={id=>navigate(id)}/>
              : page==="F25" ? <MaintainerSimulationCenter onNavigate={id=>navigate(id)} onOpenRun={id=>{setRuntimeRunId(id);navigate("A15");}}/>
              : page === "A06" ? <>
                <MaintainerSkillVersions getToken={getToken} identityKey={token ?? ""} mutate={mutateSop}
                  initialSopId={selectedSop} onSopChange={sopChanged} onDirtyChange={setWorkDirty}
                  onNavigate={(id, reference) => navigate(id, "", false, undefined, reference?.sop_id)}/>
                <details><summary>查看全部方法技术状态</summary><MaintainerSkills key={sopStatusVersion}/></details>
              </> : ["A15","F30"].includes(page) ? <>
                {page === "A15" && runtimeSopReference && <StatusLine text={"方法上下文：" + runtimeSopReference + "。当前正式记录没有方法编号筛选，请按实际 run_id 核查；当前未验证本方法与记录的关联。"}/>}
                <MaintainerRuntimeRecords getToken={getToken} identityKey={token??""} pageId={page==="F30"?"F30":"A15"}
                  key={runtimeRunId} initialRunId={runtimeRunId}
                  onOpenRunDetails={id=>{setRuntimeRunId(id);navigate("F30");}}
                  onBackToList={()=>window.history.back()}
                  onOpenTask={(taskId, runId) => setRuntimeTask({taskId, runId})}/>
                {runtimeTask && <RuntimeTaskTechnicalView getToken={getToken}
                  taskId={runtimeTask.taskId} runId={runtimeTask.runId} onClose={() => setRuntimeTask(null)}/>}
                <details className="boss-runtime-extra"><summary>查看本机 Provider 审计汇总</summary><div className="boss-columns">
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
              </div></details></>
              : page === "A04" ? <MaintainerSimulationEvents onNavigate={id=>navigate(id)} onDirtyChange={setWorkDirty} onOpenRun={id=>{setRuntimeRunId(id);navigate("A15");}}>
              <MaintainerBIScenarios/>
              {!mvpScope&&<MaintainerMorningCoverage/>}
              <div className="boss-columns">
                <div className="boss-column">
                  <MaintainerFeedback tasks={maintenance?.task_refs || []} onReload={refresh}/>
                  {allowed("F08","BOSS")&&<MaintainerMessageReply/>}
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
              </MaintainerSimulationEvents> : page === "A13" ? <MaintainerScheduler
                key="A13" onNavigate={id=>navigate(id)} onDirtyChange={setWorkDirty}
              /> : page === "A05" ?
                <MaintainerPromptVersion key="A05" onNavigate={id=>navigate(id)} onDirtyChange={setWorkDirty}/>
              :
                page === "A02" ? <>
                  <MaintainerSimulationInspect onOpenTools={() => navigate("A09")}/>
                  <details className="boss-interface-business-tools"><summary>查看已发布业务工具目录</summary><BossWorkspaceView key="A02" role={role} pageId="A02" onNavigate={id => navigate(id)} onViewSource={goSource}/></details>
                </> : page === "A07" ? <MaintainerKnowledgeWorkspace onNavigate={id=>navigate(id)} onDirtyChange={setWorkDirty}/> :
                page === "A12" ? <>
                  <MaintainerMemoryStatus getToken={getToken} identityKey={token??""} onNavigate={(id, reference) => {
                    setRuntimeRunId(reference?.run_id ?? ""); navigate(id);
                  }}/>
                  <details className="boss-memory-extra"><summary>查看其他获准技术记录</summary><BossWorkspaceView key="A12" role={role} pageId="A12" onNavigate={id=>navigate(id)} onViewSource={goSource}/></details>
                </> :
                page === "A03" ? <>
                <MaintainerDatasets onNavigate={id=>navigate(id)} onDirtyChange={setWorkDirty}/>
                <div className="boss-workspace-extra">
                  <MaintainerSupplyQuality editor={importEditor} onEditorChange={updateImportEditor}/>
                  {allowed("F10","BOSS")&&<MaintainerApplicationSeed/>}
                </div>
              </> : page==="A08" ? <MaintainerModelWorkspace onNavigate={id=>navigate(id)} getToken={getToken} onCommand={scopedCommand} onDirtyChange={setWorkDirty} onReload={refresh}/>
              : WORKSPACE_PAGE_ROUTES[page] ? <BossWorkspaceView
                key={page} role={role} pageId={page}
                onNavigate={id=>navigate(id)} onViewSource={goSource}
              /> : unsupportedPage(page)}
            </div>}
          </section>
        </main>
      </div>
    </div>
    <DialogPrimitive.Root open={pendingNavigation !== null||pendingLeaveAction!==null} onOpenChange={(open) => {if (!open){setPendingNavigation(null);setPendingLeaveAction(null);}}}>
      <DialogPrimitive.Portal container={shellRef.current}>
        <DialogPrimitive.Overlay className="boss-confirm-backdrop"/>
        <DialogPrimitive.Content className="boss-confirm boss-navigation-confirm" onCloseAutoFocus={(event) => {
          event.preventDefault();
          requestAnimationFrame(()=>{
            const confirmation=shellRef.current?.querySelector<HTMLElement>(".boss-fc07-confirm");
            if(confirmation)confirmation.focus();else if(navigationFocus.current?.isConnected)navigationFocus.current.focus();
            window.dispatchEvent(new Event("boss-navigation-focus-ready"));
          });
        }}>
        <DialogPrimitive.Title asChild><h3><AlertCircle size={19}/> 本次修改尚未保存</h3></DialogPrimitive.Title>
        <DialogPrimitive.Description asChild><p>{["F14","F21","A03"].includes(page)?"当前模拟资料或协调表单存在编辑内容。离开将放弃尚未提交的编辑；已经提交但结果未确定的原请求会保留，返回后继续核查。":page === "A08" ? "当前运行配置有未保存内容。离开不会修改已经启用的配置。" : ["N07","N08"].includes(page)?
          "当前本人设置有未保存内容。离开将放弃当前编辑，但不会删除先前保存的草稿或已确认版本。":
          page === "A06" ? "当前方法有未保存内容。离开不会修改已经保存的草稿或当前原生方法。" :
          page === "F04" ? "当前会议草稿有未保存内容。离开不会修改已经保存的会议安排。" :
          page === "F08" ? "当前消息正文、收件人或附件有未保存内容。请选择继续编辑或明确放弃；已保存草稿与模拟发送记录继续保留。" :
          page==="N03"?"当前经营范围有尚未应用的修改。离开将放弃这些修改，已经应用的范围、查询和会话记录继续保留。":page==="F03"?"当前经营查询有尚未提交的条件。离开将放弃当前编辑，已经提交的原请求和保存结果继续保留。":
          ["F01","N09"].includes(page) ? "当前本人事项次序或计划有未保存内容。离开不会修改先前保存的正式记录。" :
          "当前表单有未保存内容。离开前请明确选择继续编辑、保存草稿或放弃本次编辑。"}</p></DialogPrimitive.Description>
        {draftLeaveRef.current&&<div className="boss-draft-leave-facts"><Value label="当前对象" value={draftLeaveRef.current.object}/><Value label="已有内容版本" value={draftLeaveRef.current.version}/><Value label="未保存范围" value={draftLeaveRef.current.changedFields.join("；")||"当前操作需要核查"}/><p className="boss-helper">保存草稿不会发送消息、批准申请或创建交办。只有正式保存回执确认后才继续离开。</p>{!draftLeaveRef.current.canSave&&<p role="status">{draftLeaveRef.current.unavailableReason}</p>}</div>}
        <div className="boss-actions">
          <DialogPrimitive.Close asChild><button type="button" className="boss-btn boss-btn-primary">继续编辑</button></DialogPrimitive.Close>
          {draftLeaveRef.current&&<button type="button" className="boss-btn" disabled={!draftLeaveRef.current.canSave} onClick={()=>{
            const handle=draftLeaveRef.current,destination=pendingNavigation,action=pendingLeaveAction;
            if(!handle?.canSave||!destination&&!action)return;
            handle.beginSave(()=>{setWorkDirty(false);if(action)action();else if(destination)navigate(destination.id,destination.focus,true,destination.taskId,destination.sopId,destination.menu);});
            setPendingNavigation(null);setPendingLeaveAction(null);
          }}>保存草稿并离开</button>}
          <button type="button" className="boss-btn" onClick={()=>{
            const destination=pendingNavigation;
            const action=pendingLeaveAction;
            if (!destination&&!action) throw new Error("离开页面缺少目标");
            setAssignmentDraft({...DEFAULT_ASSIGNMENT_DRAFT});
            setAssignmentDirty(false);
            setSourceReviewDirty(false);
            setSettingsDirty(false);
            setWorkDirty(false);
            setOverviewDirty(false);setQueryDirty(false);
            if(page==="N03")setOverviewDiscardVersion(value=>value+1);
            if(page==="F01")setMorningDiscardVersion(value=>value+1);
            if(["F14","F21"].includes(page)&&!supplyEditor.pending&&!supplyEditor.pendingPreparation)updateSupplyEditor(supplyInterface,{...EMPTY_SUPPLY_EDITOR});
            if(page==="A03"&&!importEditor.pending)updateImportEditor({...EMPTY_IMPORT_EDITOR});
            setPendingNavigation(null);
            setPendingLeaveAction(null);
            if(action)action();else if(destination)navigate(destination.id,destination.focus,true,destination.taskId,destination.sopId,destination.menu);
          }}>放弃本次编辑</button>
        </div>
        </DialogPrimitive.Content>
      </DialogPrimitive.Portal>
    </DialogPrimitive.Root>
    <DialogPrimitive.Root open={directoryOpen} onOpenChange={setDirectoryOpen}><DialogPrimitive.Portal container={shellRef.current}>
      <DialogPrimitive.Overlay className="boss-directory-backdrop">
      <DialogPrimitive.Content className="boss-directory" aria-label="全部页面导航" aria-labelledby={undefined} aria-describedby={undefined} onCloseAutoFocus={event=>{event.preventDefault();if(navigationFocus.current?.isConnected)navigationFocus.current.focus();}}>
        <header><DialogPrimitive.Title asChild><strong>全部工作页面</strong></DialogPrimitive.Title>
          <button type="button" onClick={() => setDirectoryOpen(false)} aria-label="关闭目录"><X size={19}/></button></header>
        <label className="boss-directory-search"><Search size={17}/><input autoFocus value={pageFilter}
          onChange={(e) => setPageFilter(e.target.value)} placeholder="搜索页面编号或名称"/></label>
        <BossMenuDirectory role={role} page={page} search={pageFilter} onNavigate={openMenu}/>
        {allowed("NATIVE",role,mvpScope,priorityScope)&&<footer><button type="button" onClick={() => navigate("NATIVE")}>
          <MessageCircle size={16}/>{role === "BOSS" ? "Boss Agent 会话" : "应用设置"}
        </button></footer>}
      </DialogPrimitive.Content></DialogPrimitive.Overlay>
    </DialogPrimitive.Portal></DialogPrimitive.Root>
  </div>;
}
