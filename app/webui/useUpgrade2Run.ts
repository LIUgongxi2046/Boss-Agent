import {useCallback, useEffect, useRef, useState} from "react";
import {RunApiError, RunHttpError, Upgrade2RunClient, validateResultAgainstEvents, validateRunReadFence, snapshotWaitingInput, type RunSnapshot, type OriginalRequestReceipt, type IntentPreview, type DecisionReceipt} from "./upgrade2-run-client";
import {orderRunEvents, type RunEvent} from "./upgrade2-run-events";
import type {Upgrade2RunPanelProps, Upgrade2RunView} from "./Upgrade2RunPanel";
import type {RequiredOutput,RunResult,DomainDecisionExpectation,MethodSelection,MethodReceipt,MethodCatalog} from "./upgrade2-run-client";
import {upgrade2RunScopeKey} from "./upgrade2-run-scope";

export type Upgrade2Projection = Pick<Upgrade2RunView, "run_id" | "revision" | "allowed_actions" | "waiting_inputs" | "intent" | "artifacts"> & {identity_key: string};
type Pending = {request_key: string; action: "inputs" | "cancel"} | {request_key:string;action:"method";goal_revision:number;method:MethodSelection};
type DecisionPending = {request_key: string; intent_id: string; decision: "CONFIRM" | "REJECT"; revision: number;domain?:DomainDecisionExpectation};
type State = {scope: string; client: Upgrade2RunClient; snapshot: RunSnapshot | null; events: RunEvent[]; result:RunResult|null; intent: IntentPreview | null; decisionPending: DecisionPending | null; lastDecision: DecisionPending | null; decisionReceipt: DecisionReceipt | null; methodReceipt:MethodReceipt|null;methodCatalog:MethodCatalog|null; readEpoch: number; loading: boolean; busy: boolean; error: string | null; supplement: string; pending: Pending | null; receipt: OriginalRequestReceipt | null; ready: boolean};
type Options = {client: Upgrade2RunClient; identityKey: string; pendingScopeKey: string; runId: string | null; conversationId: string; authToken: string; connected: boolean; projection: Upgrade2Projection | null};

function scopeRevoked(reason: unknown): boolean {
  return (reason instanceof RunApiError || reason instanceof RunHttpError) && (reason.status === 401 || reason.status === 403 || reason.status === 410 ||
    reason instanceof RunApiError && (reason.detail.code === "EXECUTION_SPACE_CHANGED" || reason.detail.code === "SCOPE_CHANGED" || reason.detail.code === "REVISION_CONFLICT"));
}

function readPending(key: string): Pending | null {
  const raw = sessionStorage.getItem(key);
  if (raw === null) return null;
  const value: unknown = JSON.parse(raw);
  if (!value || typeof value !== "object" || !("request_key" in value) || typeof value.request_key !== "string" ||
      !value.request_key || !("action" in value) || (value.action !== "inputs" && value.action !== "cancel" && value.action !== "method")) throw new Error("原请求记录无效");
  if(value.action==="method"){
    if(!("goal_revision" in value)||typeof value.goal_revision!=="number"||!Number.isSafeInteger(value.goal_revision)||value.goal_revision<2||!("method" in value)||!value.method||typeof value.method!=="object"||!("sop_id" in value.method)||typeof value.method.sop_id!=="string"||!value.method.sop_id.trim()||!("version" in value.method)||typeof value.method.version!=="string"||!value.method.version.trim()||!("content_sha256" in value.method)||typeof value.method.content_sha256!=="string"||!/^[a-f0-9]{64}$/.test(value.method.content_sha256))throw new Error("原方法选择请求记录无效");
    return {request_key:value.request_key,action:"method",goal_revision:value.goal_revision,method:{sop_id:value.method.sop_id,version:value.method.version,content_sha256:value.method.content_sha256}};
  }
  return {request_key: value.request_key, action: value.action};
}

function empty(scope: string, client: Upgrade2RunClient): State {
  return {scope, client, snapshot: null, events: [], result:null, intent: null, decisionPending: null, lastDecision: null, decisionReceipt: null,methodReceipt:null,methodCatalog:null, readEpoch: -1, loading: false, busy: false, error: null, supplement: "", pending: null, receipt: null, ready: false};
}

function readDecisionPending(key: string): DecisionPending | null {
  const raw = localStorage.getItem(key);
  if (raw === null) return null;
  const value: unknown = JSON.parse(raw);
  if (!value || typeof value !== "object" || !("request_key" in value) || typeof value.request_key !== "string" || !/^[A-Za-z0-9_.-]{8,128}$/.test(value.request_key) ||
      !("intent_id" in value) || typeof value.intent_id !== "string" || !value.intent_id.trim() ||
      !("decision" in value) || value.decision !== "CONFIRM" && value.decision !== "REJECT" ||
      !("revision" in value) || typeof value.revision !== "number" || !Number.isSafeInteger(value.revision) || value.revision < 0) throw new Error("原本人决定记录无效");
  if("domain" in value){
    const domain=value.domain;
    if(!domain||typeof domain!=="object"||!("action" in domain)||typeof domain.action!=="string"||!["boss.meeting.confirm","boss.meeting.cancel","boss.meeting.held","boss.minutes.confirm","boss.minutes.assignment.create","boss.assignment.create"].includes(domain.action)||!("goal_revision" in domain)||typeof domain.goal_revision!=="number"||!Number.isSafeInteger(domain.goal_revision)||domain.goal_revision<1||!("object_id" in domain)||typeof domain.object_id!=="string"||!domain.object_id.trim()||!("source_refs" in domain)||!Array.isArray(domain.source_refs)||!domain.source_refs.length||domain.source_refs.some((ref:unknown)=>!ref||typeof ref!=="object"||!("source_id" in ref)||typeof ref.source_id!=="string"||!("version" in ref)||typeof ref.version!=="string"||!("source_sha256" in ref)||typeof ref.source_sha256!=="string"||!/^[a-f0-9]{64}$/.test(ref.source_sha256)))throw new Error("原本人决定范围无效");
    return {request_key:value.request_key,intent_id:value.intent_id,decision:value.decision,revision:value.revision,domain:domain as DomainDecisionExpectation};
  }
  return {request_key: value.request_key, intent_id: value.intent_id, decision: value.decision, revision: value.revision};
}

export function useUpgrade2Run({client, identityKey, pendingScopeKey, runId, conversationId, authToken, connected, projection}: Options) {
  if (!identityKey.trim() || !pendingScopeKey.trim() || !conversationId.trim()) throw new Error("身份或会话范围标识无效");
  const scope = upgrade2RunScopeKey({identityKey, pendingScopeKey, conversationId, runId, authToken});
  const storageKey = "boss:upgrade2:pending:" + JSON.stringify([pendingScopeKey, runId]);
  const decisionKey = "boss:upgrade2:decision:" + JSON.stringify([pendingScopeKey, conversationId, runId]);
  const decisionResultKey = "boss:upgrade2:decision-result:" + JSON.stringify([pendingScopeKey, conversationId, runId]);
  const [state, setState] = useState<State>(() => empty(scope, client));
  const [outputSelection,setOutputSelection]=useState<{scope:string;revision:number;outputs:RequiredOutput[]}|null>(null);
  const current = useRef({scope, client, connected});
  current.current = {scope, client, connected};
  const connection = useRef({connected, epoch: 0});
  if (connection.current.connected !== connected) connection.current = {connected, epoch: connection.current.epoch + 1};
  const lifetime = useRef(0);
  const readController = useRef<AbortController | null>(null);
  const generation = useRef(0);
  const mutations = useRef(new Set<string>());
  const scoped = state.scope === scope && state.client === client ? state : empty(scope, client);
  const visible = connected && scoped.readEpoch === connection.current.epoch ? scoped : {...scoped, snapshot: null, events: [], result:null, intent: null, receipt: null, decisionReceipt: null,methodReceipt:null,methodCatalog:null};
  const update = useCallback((change: (state: State) => State) => {
    setState(previous => previous.scope === scope && previous.client === client && current.current.scope === scope && current.current.client === client ? change(previous) : previous);
  }, [scope, client]);
  const invalidateAccess = useCallback((status:number) => {
    ++generation.current;
    readController.current?.abort();
    update(value => ({...value,snapshot:null,events:[],result:null,intent:null,receipt:null,decisionReceipt:null,methodReceipt:null,methodCatalog:null,readEpoch:-1,loading:false,error:"运行权限或来源范围需要重新核查，HTTP "+status+"。"}));
  }, [update]);

  const refresh = useCallback(async () => {
    if (!runId || !current.current.connected || current.current.scope !== scope || current.current.client !== client) return;
    const seq = ++generation.current;
    const epoch = connection.current.epoch;
    readController.current?.abort();
    const controller = new AbortController();
    readController.current = controller;
    update(value => ({...value, loading: true, result:null, error: null}));
    let completedSnapshot: RunSnapshot | null = null;
    let completedEvents: RunEvent[] = [];
    try {
      const snapshot = await client.read(runId, controller.signal);
      if (snapshot.conversation_id !== conversationId) throw new Error("运行与当前会话不一致");
      if (!snapshot.allowed_actions.includes("READ_EVENTS")) throw new Error("当前运行不允许读取事件");
      let cursor = 0;
      let events: RunEvent[] = [];
      let more: boolean;
      do {
        const page = await client.events(runId, cursor, controller.signal);
        const ordered = orderRunEvents(runId, 0, [...events, ...page.events]);
        if (ordered.missing_seq !== null) throw new Error("运行事件缺少序号 " + ordered.missing_seq + "，需要重新读取。");
        if (page.has_more && ordered.after_seq <= cursor) throw new Error("事件分页没有继续推进");
        events = ordered.events;
        cursor = ordered.after_seq;
        more = page.has_more;
      } while (more);
      if (cursor !== snapshot.last_event_seq) throw new Error("运行事件与读取快照不一致，请重新读取。");
      snapshotWaitingInput(snapshot,events);
      const result = await client.result(runId, controller.signal);
      validateResultAgainstEvents(snapshot, events, result);
      const methodCatalog=snapshot.allowed_actions.includes("SELECT_METHOD")?await client.availableMethods(runId,snapshot.goal_revision,controller.signal):null;
      if(methodCatalog&&!methodCatalog.selection_allowed)throw new Error("方法选择条件已经变化，请重新读取运行。");
      const intent = snapshot.status === "WAITING_CONFIRMATION" ? await client.intent(runId, controller.signal) : null;
      if(intent&&"action" in intent.preview&&intent.preview.goal_revision!==snapshot.goal_revision)throw new Error("本人决定与当前目标版本不一致");
      if(intent&&(new Set(intent.preview.source_refs.map(source=>source.source_id)).size!==intent.preview.source_refs.length||intent.preview.source_refs.some(source=>!snapshot.selected_refs.includes(source.source_id))))throw new Error("本人决定的来源不属于当前运行范围");
      const latest=await client.read(runId,controller.signal);
      validateRunReadFence(snapshot,latest,events);
      completedSnapshot = snapshot;
      completedEvents = events;
      if (controller.signal.aborted || seq !== generation.current || !current.current.connected || connection.current.epoch !== epoch) return;
      update(value => ({...value, snapshot, events, result, intent,methodCatalog, readEpoch: epoch, loading: false, error: null}));
    } catch (reason) {
      if (!controller.signal.aborted && seq === generation.current) {
        const revoked = scopeRevoked(reason);
        update(value => ({...value, snapshot: revoked ? null : completedSnapshot, events: revoked ? [] : completedEvents, result:null, intent: null,methodCatalog:null,
          ...(revoked ? {receipt: null, decisionReceipt: null, readEpoch: -1} : completedSnapshot ? {readEpoch: epoch} : {}),
          loading: false, error: reason instanceof Error ? reason.message : String(reason)}));
      }
    }
  }, [client, runId, conversationId, scope, update]);

  useEffect(() => {
    ++lifetime.current;
    setState({...empty(scope, client), pending: readPending(storageKey), decisionPending: readDecisionPending(decisionKey), lastDecision: readDecisionPending(decisionResultKey), ready: true});
    return () => { ++lifetime.current; ++generation.current; readController.current?.abort(); };
  }, [scope, storageKey, decisionKey, decisionResultKey, client]);

  useEffect(() => {
    if (state.scope !== scope || state.client !== client || !state.ready) return;
    if (!connected) {
      ++generation.current;
      readController.current?.abort();
      update(value => ({...value, snapshot: null, events: [], result:null, intent: null, receipt: null, decisionReceipt: null, readEpoch: -1, loading: false, busy: false}));
      return;
    }
    void refresh();
  }, [scope, client, connected, state.scope, state.client, state.ready, refresh, update]);

  useEffect(() => {
    if (!connected || !visible.snapshot || visible.loading || visible.busy || visible.pending || visible.decisionPending || visible.error ||
        !["QUEUED", "RUNNING", "WAITING_INPUT", "WAITING_CONFIRMATION", "CANCEL_REQUESTED", "RECONCILING"].includes(visible.snapshot.status)) return;
    const timer = window.setTimeout(() => void refresh(), 3000);
    return () => window.clearTimeout(timer);
  }, [connected, visible.snapshot, visible.loading, visible.busy, visible.pending, visible.decisionPending, visible.error, refresh]);

  const perform = useCallback(async (action: Pending["action"], value: string, version: number, outputs:RequiredOutput[] = [],method?:MethodSelection) => {
    if (!runId || !visible.ready || !visible.snapshot || visible.pending || visible.decisionPending || visible.busy || visible.loading || visible.error || !connected || mutations.current.has(scope) ||
        !visible.snapshot.allowed_actions.includes(action === "inputs" ? "ADD_INPUT" : action === "method" ? "SELECT_METHOD" : "CANCEL")) return;
    if (action === "inputs" && (!value.trim() || [...value].length > 65536)) {
      update(previous => ({...previous, error: "补充内容无效"}));
      return;
    }
    if (version !== (action === "inputs" || action === "method" ? visible.snapshot.goal_revision : visible.snapshot.revision)) return;
    if(action==="method"&&(version<2||!method||!method.sop_id.trim()||[...method.sop_id].length>128||!method.version.trim()||[...method.version].length>128||!/^[a-f0-9]{64}$/.test(method.content_sha256)))return;
    if(action==="method"&&(!visible.methodCatalog?.selection_allowed||visible.methodCatalog.goal_revision!==version||!visible.methodCatalog.methods.some(item=>item.status==="AVAILABLE"&&item.sop_id===method!.sop_id&&item.version===method!.version&&item.content_sha256===method!.content_sha256)))return;
    const started = lifetime.current, epoch = connection.current.epoch;
    const active = () => lifetime.current === started && connection.current.epoch === epoch && current.current.scope === scope && current.current.client === client && current.current.connected;
    const pending: Pending = action==="method"?{action,request_key:crypto.randomUUID(),goal_revision:version,method:method!}:{action, request_key: crypto.randomUUID()};
    sessionStorage.setItem(storageKey, JSON.stringify(pending));
    mutations.current.add(scope);
    ++generation.current;
    readController.current?.abort();
    update(previous => ({...previous, pending, busy: true, loading: false, result:null, error: null, receipt: null}));
    try {
      const methodReceipt=action==="method"?await client.selectMethod(runId,version,pending.request_key,method!):null;
      const inputReceipt=action === "inputs" ? await client.supplement(runId, value, version, pending.request_key,undefined,outputs.length?outputs:undefined) : null;
      if(action==="cancel")await client.cancel(runId, version, pending.request_key);
      if (!active()) return;
      sessionStorage.removeItem(storageKey);
      update(previous => ({...previous, pending: null, busy: false,methodReceipt, receipt:inputReceipt?{request_key:pending.request_key,run_id:runId,operation:"inputs",outcome:"RECORDED",receipt:inputReceipt}:null, supplement: action === "inputs" && previous.supplement === value ? "" : previous.supplement}));
      await refresh();
    } catch (reason) {
      if (!active()) return;
      const rejected = reason instanceof RunApiError && reason.detail.code !== "REQUEST_KEY_CONFLICT" && ([400, 401, 403, 404, 409, 413, 422].includes(reason.status) || action === "inputs" && reason.detail.code === "SERVICE_NOT_READY" && reason.detail.message === "成果要求服务尚未安装");
      const cleared = rejected;
      if (cleared) sessionStorage.removeItem(storageKey);
      const revoked = scopeRevoked(reason);
      update(previous => ({...previous, ...(revoked ? {snapshot: null, events: [], result:null, intent: null, receipt: null, decisionReceipt: null, readEpoch: -1} : {}), pending: cleared ? null : pending, busy: false, error: reason instanceof Error ? reason.message : String(reason)}));
    } finally {
      mutations.current.delete(scope);
    }
  }, [client, connected, refresh, runId, scope, storageKey, update, visible]);

  const reconcile = useCallback(async () => {
    if (!runId || !visible.pending || visible.busy || !connected || mutations.current.has(scope)) return;
    const started = lifetime.current, epoch = connection.current.epoch;
    const active = () => lifetime.current === started && connection.current.epoch === epoch && current.current.scope === scope && current.current.client === client && current.current.connected;
    const pending = visible.pending;
    mutations.current.add(scope);
    update(previous => ({...previous, busy: true, error: null}));
    try {
      const methodReceipt=pending.action==="method"?await client.methodReceipt(runId,pending.request_key,pending.goal_revision,pending.method):null;
      const receipt=pending.action==="method"?null:await client.requestReceipt(pending.request_key, runId, pending.action);
      if (!active()) return;
      sessionStorage.removeItem(storageKey);
      update(previous => ({...previous, pending: null, receipt,methodReceipt, busy: false, error: null}));
      await refresh();
    } catch (reason) {
      if (!active()) return;
      const revoked = scopeRevoked(reason);
      update(previous => ({...previous, ...(revoked ? {snapshot: null, events: [], result:null, intent: null, receipt: null, decisionReceipt: null, readEpoch: -1} : {}), busy: false, error: reason instanceof Error ? reason.message : String(reason)}));
    } finally {
      mutations.current.delete(scope);
    }
  }, [client, connected, refresh, runId, scope, storageKey, update, visible.pending, visible.busy]);

  const decide = useCallback(async (choice: "CONFIRM" | "REJECT" | null,acknowledgeConflict?:boolean) => {
    if (!runId || !connected || visible.busy || mutations.current.has(scope) || !visible.ready) return;
    const started = lifetime.current, epoch = connection.current.epoch;
    const active = () => lifetime.current === started && connection.current.epoch === epoch && current.current.scope === scope && current.current.client === client && current.current.connected;
    mutations.current.add(scope);
    update(previous => ({...previous, busy: true, error: null}));
    try {
      if (!navigator.locks) throw new Error("当前环境不支持跨窗口请求保护");
      await navigator.locks.request(decisionKey, async () => {
        if (!active()) return;
        let pending = readDecisionPending(decisionKey);
        if (choice === null && !pending) pending = readDecisionPending(decisionResultKey);
        if (choice !== null) {
          if (pending) { update(previous => ({...previous, decisionPending: pending})); throw new Error("原本人决定结果尚未核查"); }
          const intent = visible.intent;
          if (!intent || !visible.snapshot || visible.snapshot.status !== "WAITING_CONFIRMATION" || visible.pending || visible.error || visible.loading || !intent.allowed_actions.includes(choice)) throw new Error("当前决定尚不可用");
          const latest = await client.intent(runId);
          if (!active()) return;
          if (latest.intent_id !== intent.intent_id || latest.revision !== intent.revision || latest.payload_digest !== intent.payload_digest || !latest.allowed_actions.includes(choice)) throw new Error("本人决定内容已经变化，请重新读取");
          if("action" in latest.preview&&latest.preview.goal_revision!==visible.snapshot.goal_revision)throw new Error("本人决定与当前目标版本不一致");
          const domain="action" in latest.preview?{action:latest.preview.action,goal_revision:latest.preview.goal_revision,object_id:latest.preview.object_id,source_refs:latest.preview.source_refs}:undefined;
          if(choice==="CONFIRM"&&"action" in latest.preview&&latest.preview.action==="boss.meeting.confirm"&&latest.preview.impact?.requires_owner_acknowledgement===true&&acknowledgeConflict!==true)throw new Error("请先核查并确认会议安排冲突");
          pending = {request_key: crypto.randomUUID(), intent_id: intent.intent_id, decision: choice, revision: intent.revision,...(domain?{domain}:{})};
          localStorage.setItem(decisionKey, JSON.stringify(pending));
          update(previous => ({...previous, decisionPending: pending, decisionReceipt: null}));
        }
        if (!pending) throw new Error("没有待核查的本人决定请求");
        let result: DecisionReceipt;
        try {
          result = choice === null ? await client.decisionReceipt(pending.request_key, pending.intent_id, pending.decision, pending.revision,pending.domain)
            : await client.decision(pending.intent_id, pending.decision, pending.revision, visible.intent!.payload_digest, pending.request_key,acknowledgeConflict,pending.domain);
        } catch (reason) {
          if (choice !== null && active() && reason instanceof RunApiError && reason.detail.code === "SERVICE_NOT_READY") {
            localStorage.removeItem(decisionKey);
            update(previous => ({...previous, decisionPending: null}));
          }
          throw reason;
        }
        if (!active()) return;
        localStorage.setItem(decisionResultKey, JSON.stringify(pending));
        localStorage.removeItem(decisionKey);
        update(previous => ({...previous, decisionPending: null, lastDecision: pending, decisionReceipt: result, busy: false, intent: null}));
        await refresh();
      });
    } catch (reason) {
      if (active()) {
        const revoked = scopeRevoked(reason);
        update(previous => ({...previous, intent: null, ...(revoked ? {snapshot: null, events: [], result:null, receipt: null, decisionReceipt: null, readEpoch: -1} : {}), busy: false, error: reason instanceof Error ? reason.message : String(reason)}));
      }
    } finally { mutations.current.delete(scope); }
  }, [client, connected, decisionKey, decisionResultKey, refresh, runId, scope, update, visible]);

  const snapshot = visible.snapshot;
  const acceptedProjection = projection && snapshot && projection.identity_key === identityKey && projection.run_id === snapshot.run_id && projection.revision === snapshot.revision ? projection : null;
  const intent = visible.intent;
  const domain=intent&&"action" in intent.preview?intent.preview:null;
  const params = intent&&"coordinate_input" in intent.preview?intent.preview.coordinate_input:null;
  const run: Upgrade2RunView | null = snapshot ? {
    run_id: snapshot.run_id, goal: snapshot.goal, revision: snapshot.revision, goal_revision: snapshot.goal_revision, status: snapshot.status,
    cancel_requested_at: snapshot.cancel_requested_at,
    requirements:snapshot.requirements,method_selection:snapshot.method_selection,
    allowed_actions: [...(snapshot.allowed_actions.includes("ADD_INPUT") ? ["SUPPLY_INPUT" as const] : []), ...(snapshot.allowed_actions.includes("CANCEL") ? ["CANCEL" as const] : []), ...(intent?.allowed_actions ?? [])], waiting_inputs: snapshotWaitingInput(snapshot,visible.events),
    intent: intent && domain ? {intent_id:intent.intent_id,revision:intent.revision,payload_digest:intent.payload_digest,status:intent.status,action:domain.action,object_label:domain.object_id,content:"",assignee:"",deadline:"",impact:"",source_refs:domain.source_refs.map(source=>({source_id:source.source_id,revision:source.version,locator:"",sha256:source.source_sha256})),simulation_label:"",interface_id:"",review_sha256:"",preparation_sha256:"",evidence_requirements:[],owner_page:"",domain} : intent && params && "coordinate_input" in intent.preview ? {intent_id: intent.intent_id, revision: intent.revision, payload_digest: intent.payload_digest, status: intent.status,
      action: intent.preview.next_operation, object_label: params.origin_entity_type + " · " + params.origin_record_id + " · 版本 " + params.origin_version,
      content: params.purpose, assignee: params.coordinator_id, deadline: params.due_at + " · " + params.timezone,
      impact: "当前尚未签发业务授权，尚未调用外部服务", source_refs: intent.preview.source_refs.map(source => ({source_id: source.source_id, revision: source.version, locator: "定位未提供", sha256: source.source_sha256})),
      simulation_label: intent.preview.source_type, interface_id: params.interface_id, review_sha256: params.review_sha256,
      preparation_sha256: intent.preview.preparation_sha256, evidence_requirements: params.evidence_requirements, owner_page: intent.preview.owner_page} : null,
    artifacts: acceptedProjection?.artifacts ?? [], projection_ready: acceptedProjection !== null,
  } : null;
  const panelProps: Upgrade2RunPanelProps = {
    run, events: visible.events, result:visible.result?.result??null,citationChecks:visible.result?.citation_checks??null, event_base_seq: 0, connection: connected ? (visible.loading || !visible.ready ? "RECONNECTING" : "CONNECTED") : "DISCONNECTED",
    loading: visible.loading || !visible.ready || connected && visible.readEpoch !== connection.current.epoch && !visible.error, busy: visible.busy || visible.pending !== null || visible.decisionPending !== null,
    error: visible.decisionPending ? "本人决定结果尚未核查，请查询原请求编号：" + visible.decisionPending.request_key + (visible.error ? "。" + visible.error : "") : visible.pending ? "原请求结果尚未核查，请查询原请求编号：" + visible.pending.request_key + (visible.error ? "。" + visible.error : "") : visible.error,
    supplement: visible.supplement,
    onSupplementChange: value => update(previous => ({...previous, supplement: value})),
    supplementOutputs:outputSelection?.scope===scope&&outputSelection.revision===snapshot?.goal_revision?outputSelection.outputs:[],
    onSupplementOutputsChange:outputs=>{if(snapshot)setOutputSelection({scope,revision:snapshot.goal_revision,outputs});},
    onSupplement: (_runId, input, version,outputs) => { void perform("inputs", input, version,outputs); },
    onCancel: (_runId, version) => { void perform("cancel", "", version); },
    onDecision: (intentId, choice, revision, digest,acknowledgeConflict) => {
      if (visible.intent && visible.intent.intent_id === intentId && visible.intent.revision === revision && visible.intent.payload_digest === digest) void decide(choice,acknowledgeConflict);
    },
  };
  return {panelProps, snapshot, pending: visible.pending, receipt: visible.receipt,methodReceipt:visible.methodReceipt,methodCatalog:visible.methodCatalog,selectMethod:(method:MethodSelection)=>{if(snapshot)void perform("method","",snapshot.goal_revision,[],method);}, decisionPending: visible.decisionPending, lastDecision: visible.lastDecision, decisionReceipt: visible.decisionReceipt, requestBusy: visible.busy, refresh, reconcile, reconcileDecision: () => decide(null),invalidateAccess};
}
