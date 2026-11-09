import {orderRunEvents, type RunEvent} from "./upgrade2-run-events";
import Ajv2020 from "ajv/dist/2020";
import addFormats from "ajv-formats";
import runSchema from "../../specs/agent-runs.schema.json";
import eventSchema from "../../specs/agent-events.schema.json";
import sourceSchema from "../../specs/conversation-sources.schema.json";
import intentSchema from "../../specs/agent-intents.schema.json";
import resumeSchema from "./agent_run_resume_schema.local.json";

export type RunStatus = "QUEUED" | "RUNNING" | "WAITING_INPUT" | "WAITING_CONFIRMATION" | "CANCEL_REQUESTED" | "RECONCILING" | "SUCCEEDED" | "FAILED" | "CANCELED" | "INTERRUPTED";
export type RequiredOutput = "TEXT" | "BRIEF" | "SOURCE_LIST" | "ACTION_DRAFT" | "MARKDOWN" | "PDF" | "DOCX" | "XLSX" | "PPTX" | "BUSINESS_RECEIPT";
export type RunRequirements = {goal_revision:number;state:"CONFIRMED"|"PENDING_CONFIRMATION"|"UNAVAILABLE";required_outputs:RequiredOutput[]|null};
export type MethodSelection={sop_id:string;version:string;content_sha256:string};
export type MethodReceipt={run_id:string;goal_revision:number;input_id:string;request_key:string;method_selection:MethodSelection&{name:string;goal_revision:number;state:"SELECTED"}};
export type MethodCatalog={run_id:string;goal_revision:number;selection_allowed:boolean;methods:(MethodSelection&{name:string;status:"AVAILABLE"|"UNAVAILABLE";reasons:string[];missing_native_tools:string[];missing_runtime_tools:string[];missing_projections:string[]})[]};
export type CreateMethodCatalog={conversation_id:string;selected_refs:string[];methods:MethodCatalog["methods"]};
export type ObjectReference={entity_type:"task"|"metric_detail"|"event"|"travel_plan"|"owner_goals_active"|"meeting_context";object_id:string;version:string;sha256:string};
export type ObjectSource={source_id:string;version:string;sha256:string};
export type ObjectCandidate=ObjectReference&{source_refs:ObjectSource[];data:Record<string,unknown>};
export type ObjectCandidates={run_id:string;goal_revision:number;selection_allowed:boolean;unavailable_reasons:("RUN_CANCELED"|"RUN_STATE_UNAVAILABLE"|"GOAL_ALREADY_SELECTED")[];objects:ObjectCandidate[]};
export type ObjectReceipt={run_id:string;goal_revision:number;request_key:string;objects:(ObjectReference&{source_refs:ObjectSource[]})[]};
export type ObjectResponse<T>={ok:true;value:T}|{ok:false;status:number;message:string};
export type RunSnapshot = {run_id: string; conversation_id: string; goal: string; selected_refs: string[]; status: RunStatus; revision: number; goal_revision: number; applied_goal_revision: number; last_event_seq: number; cancel_requested_at: string | null; allowed_actions: ("READ_EVENTS" | "ADD_INPUT" | "CANCEL" | "SELECT_METHOD")[];requirements:RunRequirements;waiting_input?:{event_id:string;goal_revision:number;question:string};method_selection?:{sop_id:string;name:string;version:string;content_sha256:string;goal_revision:number;state:"SELECTED"}};
export type RunReceipt = {run_id: string; status: RunStatus; revision: number};
export type DispatchReceipt = {run_id:string;request_key:string;expected_revision:number;lease_epoch:number;state:"ACCEPTED"|"COMPLETED"|"UNKNOWN";result:Record<string,unknown>|null};
export type DispatchInspection={run_id:string;request_key:string;receipt_state:"ACCEPTED"|"COMPLETED"|"UNKNOWN";run_status:RunStatus;lease_epoch:number;current_lease_epoch:number;lease_owner_matches:boolean;lease_expires_at:string|null;reservation_state:"ACTIVE"|"UNKNOWN"|"RELEASED";process_state:"STARTING"|"RUNNING"|"UNKNOWN"|"EXITED"|"NOT_RECORDED";exit_code:number|null;exit_scope:string|null;automatic_retry:false};
export type RunInputReceipt = {input_id: string; input_seq: number; goal_revision: number};
export type RunEventPage = {events: RunEvent[]; next_seq: number; has_more: boolean};
export type RunResultEvent = Omit<RunEvent, "type" | "payload"> & {type:"RESULT_RECORDED"; payload:{text:string; goal_revision:number; engine_commit:string; dataset_id:string; dataset_version:string; source_pins:{source_id:string;version:string;content_sha256:string}[]; citations:{source_id:string;locator:string}[]}};
export type CitationCheck = {source_id:string;locator:string;locator_verification:"NOT_VERIFIED"};
export type RunResult = {run_id:string; goal_revision:number; result:RunResultEvent|null;citation_checks:CitationCheck[]|null};
export type ResumeStatus = {run_id:string;status:RunStatus;revision:number;goal_revision:number;allowed_actions:[];waiting_reasons:string[];original_receipt:{run_id:string;status:"QUEUED";revision:number;goal_revision:number}|null};
export type CompletionInspection = {run_id:string;goal_revision:number;current_goal_revision:number;inspection_revision:number;run_revision:number;stale:boolean;result_event_id:string;finish_event_id:string;completion_state:"BLOCKED"|"UNVERIFIED"|"PASS";blockers:string[];output_checks:{type:"TEXT"|"BRIEF"|"SOURCE_LIST"|"ACTION_DRAFT"|"MARKDOWN"|"PDF"|"DOCX"|"XLSX"|"PPTX"|"BUSINESS_RECEIPT";state:"RECORD_PRESENT"|"FILE_VERIFIED"|"NOT_VERIFIED"|"MISSING"}[];requirements:RunRequirements;brief_section_audits:{artifact_id:string;version:number;section_audit:{completion_state:string;sections:{kind:string;status:string;reason:string}[];gaps:{kind:string;reason:string;source_id?:string}[];missing_categories:string[]}|null}[]};
export type RunApiErrorBody = {code: string; message: string; run_id: string | null; trace_id: string; failed_step: string; completed_refs: string[]; recovery_action: string};
export type OriginalRequestReceipt = {request_key: string; run_id: string; operation: "create" | "inputs" | "cancel"; outcome: "RECORDED"; receipt: RunReceipt | RunInputReceipt};
export type IntentSource = {source_id:string;version:string;source_sha256:string};
export type DomainIntentPreview = {action:"boss.meeting.confirm"|"boss.meeting.cancel"|"boss.meeting.held"|"boss.minutes.confirm"|"boss.minutes.assignment.create"|"boss.assignment.create";params:Record<string,unknown>;object_id:string;object_revision:string;goal_revision:number;source_refs:IntentSource[];context_digest:string;impact:Record<string,unknown>|null;details:Record<string,unknown>;owner_decision_required:true;business_authority_granted:false;plan_digest:string;budget_digest:string};
export type CoordinateIntentPreview = {source_type: "SIMULATED"; preparation_sha256: string; coordinate_input: {interface_id: string; origin_entity_type: string; origin_record_id: string; origin_version: string; review_sha256: string; purpose: string; coordinator_id: string; due_at: string; timezone: string; evidence_requirements: string[]}; source_refs: IntentSource[]; owner_decision_required: true; business_authority_granted: false; external_service_invoked: false; next_operation: string; owner_page: string};
export type IntentPreview = {schema_version: 1; intent_id: string; run_id: string; status: "WAITING_CONFIRMATION"; revision: number; payload_digest: string; allowed_actions: ("CONFIRM" | "REJECT")[]; preview: CoordinateIntentPreview|DomainIntentPreview};
export type DomainDecisionExpectation={action:DomainIntentPreview["action"];goal_revision:number;object_id:string;source_refs:IntentSource[]};
export type DecisionReceipt = {schema_version: 1; request_key: string; receipt: {intent_id: string; status: "REJECTED" | "SUCCEEDED"; revision: number; authorization_id?: string; result_ref?: string; task_id?: string;action?:string;goal_revision?:number;business_object_id?:string;business_object_version?:string;source_refs?:IntentSource[]}};
export type RunSchemaKind = "snapshot" | "input_receipt" | "receipt" | "request_receipt" | "page" | "result" | "error" | "intent_preview" | "decision_receipt" | "decision" | "method_reselection" | "method_reselection_receipt" | "method_catalog" | "object_scope_request" | "object_scope_receipt" | "object_scope_candidates";

const schemaValidator = new Ajv2020({strictTypes: false, allowUnionTypes: true});
addFormats(schemaValidator);
const validateDispatchReceipt=schemaValidator.compile({type:"object",additionalProperties:false,required:["run_id","request_key","expected_revision","lease_epoch","state","result"],properties:{run_id:{type:"string"},request_key:{type:"string"},expected_revision:{type:"integer",minimum:0},lease_epoch:{type:"integer",minimum:1},state:{enum:["ACCEPTED","COMPLETED","UNKNOWN"]},result:{anyOf:[{type:"object"},{type:"null"}]}},allOf:[{if:{properties:{state:{const:"ACCEPTED"}}},then:{properties:{result:{type:"null"}}}},{if:{properties:{state:{const:"COMPLETED"}}},then:{properties:{result:{type:"object"}}}}]});
const validateDispatchInspection=schemaValidator.compile({type:"object",additionalProperties:false,required:["run_id","request_key","receipt_state","run_status","lease_epoch","current_lease_epoch","lease_owner_matches","lease_expires_at","reservation_state","process_state","exit_code","exit_scope","automatic_retry"],properties:{run_id:{type:"string"},request_key:{type:"string"},receipt_state:{enum:["ACCEPTED","COMPLETED","UNKNOWN"]},run_status:{enum:["QUEUED","RUNNING","WAITING_INPUT","WAITING_CONFIRMATION","CANCEL_REQUESTED","RECONCILING","SUCCEEDED","FAILED","CANCELED","INTERRUPTED"]},lease_epoch:{type:"integer",minimum:1},current_lease_epoch:{type:"integer",minimum:0},lease_owner_matches:{type:"boolean"},lease_expires_at:{type:["string","null"]},reservation_state:{enum:["ACTIVE","UNKNOWN","RELEASED"]},process_state:{enum:["STARTING","RUNNING","UNKNOWN","EXITED","NOT_RECORDED"]},exit_code:{type:["integer","null"]},exit_scope:{enum:["LEADER_ONLY",null]},automatic_retry:{const:false}}});
const validateCreateMethodCatalog=schemaValidator.compile({type:"object",additionalProperties:false,required:["conversation_id","selected_refs","methods"],properties:{conversation_id:{type:"string",minLength:1},selected_refs:{type:"array",items:{type:"string",minLength:1},uniqueItems:true},methods:{type:"array",items:{type:"object",additionalProperties:false,required:["sop_id","name","version","content_sha256","status","reasons","missing_native_tools","missing_runtime_tools","missing_projections"],properties:{sop_id:{type:"string",minLength:1},name:{type:"string",minLength:1},version:{type:"string",minLength:1},content_sha256:{type:"string",pattern:"^[0-9a-f]{64}$"},status:{enum:["AVAILABLE","UNAVAILABLE"]},reasons:{type:"array",items:{type:"string"}},missing_native_tools:{type:"array",items:{type:"string"}},missing_runtime_tools:{type:"array",items:{type:"string"}},missing_projections:{type:"array",items:{type:"string"}}}}}}});
export function checkDispatchReceipt(value:unknown,runId:string,revision:number,requestKey:string):DispatchReceipt {
  if(!validateDispatchReceipt(value))throw new Error("派发回执格式无效");
  const receipt=value as DispatchReceipt;
  if(receipt.run_id!==runId||receipt.request_key!==requestKey||receipt.expected_revision!==revision)throw new Error("派发回执与原请求不一致");
  return receipt;
}
schemaValidator.addSchema(runSchema);
schemaValidator.addSchema(eventSchema);
schemaValidator.addSchema(sourceSchema);
schemaValidator.addSchema(intentSchema);
schemaValidator.addSchema(resumeSchema,"urn:boss-agent:run-resume:1");
const validateResumeStatus=schemaValidator.getSchema("urn:boss-agent:run-resume:1#/$defs/status");
if(!validateResumeStatus)throw new Error("运行恢复状态 Schema 未找到");
export function resumeStatusSchemaError(value:unknown):string|null {
  if(validateResumeStatus!(value))return null;
  return "运行恢复状态不符合 Schema：" + schemaValidator.errorsText(validateResumeStatus!.errors);
}
const validateCompletionInspection=schemaValidator.getSchema("urn:boss-agent:agent-runs:1#/$defs/completion_inspection");
if(!validateCompletionInspection)throw new Error("完成核查 Schema 未找到");
export function completionInspectionSchemaError(value:unknown):string|null {
  if(validateCompletionInspection!(value))return null;
  return "完成核查响应不符合 Schema：" + schemaValidator.errorsText(validateCompletionInspection!.errors);
}
const validateCatalogue = schemaValidator.getSchema("urn:boss-agent:conversation-sources:1.0.0#/$defs/Catalogue");
if (!validateCatalogue) throw new Error("会话来源Schema未找到");
export function validateRunCatalogue(value: unknown): void {
  if (!validateCatalogue!(value)) throw new Error("会话来源响应不符合Schema：" + schemaValidator.errorsText(validateCatalogue!.errors));
}
const schemaKinds: Record<RunSchemaKind, string> = {
  snapshot: "urn:boss-agent:agent-runs:1#/$defs/snapshot",
  input_receipt: "urn:boss-agent:agent-runs:1#/$defs/input_receipt",
  receipt: "urn:boss-agent:agent-runs:1#/$defs/receipt",
  request_receipt: "urn:boss-agent:agent-runs:1#/$defs/request_receipt",
  error: "urn:boss-agent:agent-runs:1#/$defs/error",
  page: "urn:boss-agent:agent-events:1#/$defs/page",
  result: "urn:boss-agent:agent-events:1#/$defs/result",
  intent_preview: "urn:boss-agent:agent-intents:1#/$defs/preview",
  decision_receipt: "urn:boss-agent:agent-intents:1#/$defs/decision_receipt",
  decision: "urn:boss-agent:agent-intents:1#/$defs/decision",
  method_reselection: "urn:boss-agent:agent-runs:1#/$defs/method_reselection",
  method_reselection_receipt: "urn:boss-agent:agent-runs:1#/$defs/method_reselection_receipt",
  method_catalog: "urn:boss-agent:agent-runs:1#/$defs/method_catalog",
  object_scope_request: "urn:boss-agent:agent-runs:1#/$defs/object_scope_request",
  object_scope_receipt: "urn:boss-agent:agent-runs:1#/$defs/object_scope_receipt",
  object_scope_candidates: "urn:boss-agent:agent-runs:1#/$defs/object_scope_candidates",
};
const validators = Object.fromEntries(Object.entries(schemaKinds).map(([kind, reference]) => {
  const validate = schemaValidator.getSchema(reference);
  if (!validate) throw new Error("运行Schema未找到：" + reference);
  return [kind, validate];
})) as Record<RunSchemaKind, NonNullable<ReturnType<typeof schemaValidator.getSchema>>>;

export function validateRunResponse(kind: RunSchemaKind, value: unknown): void {
  const validate = validators[kind];
  if (!validate(value)) throw new Error("运行接口响应不符合Schema：" + schemaValidator.errorsText(validate.errors));
}

export function snapshotWaitingInput(snapshot:RunSnapshot,events:RunEvent[]):string[] {
  const input=snapshot.waiting_input;
  if(!input)return [];
  const event=events.find(item=>item.event_id===input.event_id);
  if(snapshot.status!=="WAITING_INPUT"||input.goal_revision!==snapshot.goal_revision||!event||event.type!=="INPUT_REQUIRED"||event.run_id!==snapshot.run_id||!event.payload||typeof event.payload!=="object"||Array.isArray(event.payload)||event.payload.goal_revision!==input.goal_revision||event.payload.question!==input.question)throw new Error("补充问题与当前运行事件不一致，请重新读取。");
  return [input.question];
}

export function validateRunReadFence(snapshot:RunSnapshot,latest:RunSnapshot,events:RunEvent[]):void {
  const ordered=orderRunEvents(snapshot.run_id,0,events);
  if(ordered.missing_seq!==null||ordered.after_seq!==snapshot.last_event_seq)throw new Error("运行事件与读取快照不一致，请重新读取。");
  const signature=(value:RunSnapshot)=>JSON.stringify([value.run_id,value.conversation_id,value.goal,value.status,value.revision,value.goal_revision,value.applied_goal_revision,value.last_event_seq,value.cancel_requested_at,value.selected_refs,value.allowed_actions,
    value.requirements?.goal_revision,value.requirements?.state,value.requirements?.required_outputs,
    value.waiting_input?.event_id,value.waiting_input?.goal_revision,value.waiting_input?.question,
    value.method_selection?.sop_id,value.method_selection?.name,value.method_selection?.version,value.method_selection?.content_sha256,value.method_selection?.goal_revision,value.method_selection?.state]);
  if(signature(snapshot)!==signature(latest))throw new Error("运行状态或目标版本已经变化，请重新读取。");
}

export function validateResultAgainstEvents(snapshot:RunSnapshot, events:RunEvent[], result:RunResult):void {
  if (result.run_id !== snapshot.run_id || result.goal_revision !== snapshot.goal_revision) throw new Error("运行目标版本已经变化，请重新读取。");
  const currentResults = events.filter(event => event.type === "RESULT_RECORDED" && event.payload !== null && typeof event.payload === "object" && !Array.isArray(event.payload) && event.payload.goal_revision === snapshot.goal_revision);
  if (currentResults.length !== (result.result ? 1 : 0)) throw new Error("运行结果与事件记录不一致，请重新读取。");
  if (result.result) {
    if (result.result.run_id !== snapshot.run_id || result.result.payload.goal_revision !== result.goal_revision || !events.some(event => event.event_id === result.result!.event_id && event.seq === result.result!.seq))
      throw new Error("运行结果尚未包含在连续事件中，请重新读取。");
    orderRunEvents(snapshot.run_id, 0, [...events, result.result]);
    const pins = result.result.payload.source_pins.map(pin => pin.source_id);
    if (pins.length !== snapshot.selected_refs.length || snapshot.selected_refs.some(source => !pins.includes(source)))
      throw new Error("运行结果来源与当前选择不一致，请重新读取。");
  }
}

export class RunApiError extends Error {
  constructor(readonly status: number, readonly detail: RunApiErrorBody) {
    super(detail.message);
    this.name = "RunApiError";
  }
}

export class RunHttpError extends Error {
  constructor(readonly status: number, message: string) {
    super("HTTP " + status + (message ? "：" + message : ""));
    this.name = "RunHttpError";
  }
}

export type RunClientOptions = {
  getToken: () => string;
};

export class Upgrade2RunClient {
  constructor(private readonly options: RunClientOptions) {}

  private async request<T>(path: string, kind: RunSchemaKind, signal?: AbortSignal, body?: object): Promise<T> {
    const token = this.options.getToken();
    const headers = new Headers();
    if (token) headers.set("Authorization", "Bearer " + token);
    if (body) headers.set("Content-Type", "application/json");
    const response = await fetch(path, {method: body ? "POST" : "GET", headers, body: body ? JSON.stringify(body) : undefined,
      credentials: "same-origin", cache: "no-store", redirect: "error", signal});
    if (!response.ok && !response.headers.get("content-type")?.toLowerCase().includes("application/json")) {
      const message = await response.text();
      throw new RunHttpError(response.status, message);
    }
    const value: unknown = await response.json();
    if (!response.ok) {
      validateRunResponse("error", value);
      throw new RunApiError(response.status, value as RunApiErrorBody);
    }
    validateRunResponse(kind, value);
    return value as T;
  }

  private path(runId: string): string {
    if (!runId || !runId.trim() || [...runId].length > 128) throw new Error("运行编号无效");
    return "/api/v2/runs/" + encodeURIComponent(runId);
  }

  async dispatch(runId:string, revision:number, requestKey:string, signal?:AbortSignal):Promise<DispatchReceipt> {
    return this.dispatchRequest(runId,revision,requestKey,true,signal);
  }

  async dispatchReceipt(runId:string, revision:number, requestKey:string, signal?:AbortSignal):Promise<DispatchReceipt> {
    return this.dispatchRequest(runId,revision,requestKey,false,signal);
  }

  async dispatchInspection(runId:string,requestKey:string,signal?:AbortSignal):Promise<DispatchInspection>{
    this.validateMutation("查询",0,requestKey);
    const token=this.options.getToken();
    const response=await fetch(this.path(runId)+"/dispatch-requests/"+encodeURIComponent(requestKey)+"/inspection",{headers:token?{Authorization:"Bearer "+token}:{},credentials:"same-origin",cache:"no-store",redirect:"error",signal});
    if(!response.ok){
      if(response.headers.get("content-type")?.toLowerCase().includes("application/json")){const value:unknown=await response.json();validateRunResponse("error",value);throw new RunApiError(response.status,value as RunApiErrorBody);}
      throw new RunHttpError(response.status,await response.text());
    }
    const value:unknown=await response.json();
    if(!validateDispatchInspection(value))throw new Error("派发核查响应格式无效");
    const result=value as DispatchInspection;
    if(result.run_id!==runId||result.request_key!==requestKey)throw new Error("派发核查与原请求不一致");
    return result;
  }

  private async dispatchRequest(runId:string, revision:number, requestKey:string, submit:boolean, signal?:AbortSignal):Promise<DispatchReceipt> {
    this.validateMutation("查询", revision, requestKey);
    const token=this.options.getToken();
    const headers=new Headers();
    if(token)headers.set("Authorization","Bearer "+token);
    if(submit)headers.set("Content-Type","application/json");
    const response=await fetch(this.path(runId)+(submit?"/dispatch":"/dispatch-requests/"+encodeURIComponent(requestKey)),{
      method:submit?"POST":"GET",headers,body:submit?JSON.stringify({expected_revision:revision,request_key:requestKey}):undefined,
      credentials:"same-origin",cache:"no-store",redirect:"error",signal});
    if(!response.ok){
      if(response.headers.get("content-type")?.toLowerCase().includes("application/json")){
        const value:unknown=await response.json();validateRunResponse("error",value);throw new RunApiError(response.status,value as RunApiErrorBody);
      }
      throw new RunHttpError(response.status,await response.text());
    }
    const value:unknown=await response.json();
    return checkDispatchReceipt(value,runId,revision,requestKey);
  }

  async create(conversationId: string, goal: string, selectedRefs: string[], requestKey: string, signal?: AbortSignal, requiredOutputs?: RequiredOutput[], methodSelection?:MethodSelection): Promise<RunReceipt> {
    this.validateMutation(goal, 0, requestKey);
    if (!conversationId.trim() || [...conversationId].length > 128 || !Array.isArray(selectedRefs) || selectedRefs.length > 100 ||
        selectedRefs.some(ref => typeof ref !== "string" || !ref.trim() || [...ref].length > 128) ||
        new Set(selectedRefs).size !== selectedRefs.length) throw new Error("会话或来源选择无效");
    return this.request<RunReceipt>("/api/v2/runs", "receipt", signal,
      {conversation_id: conversationId, goal, selected_refs: selectedRefs, request_key: requestKey, ...(requiredOutputs ? {required_outputs:requiredOutputs} : {}),...(methodSelection?{method_selection:methodSelection}:{})});
  }

  async createMethodCatalog(conversationId:string,selectedRefs:string[],signal?:AbortSignal):Promise<CreateMethodCatalog>{
    if(!conversationId.trim()||!Array.isArray(selectedRefs)||new Set(selectedRefs).size!==selectedRefs.length||selectedRefs.some(value=>typeof value!=="string"||!value.trim()))throw new Error("会话或来源选择无效");
    const token=this.options.getToken();
    const headers=new Headers({"Content-Type":"application/json"});if(token)headers.set("Authorization","Bearer "+token);
    const response=await fetch("/api/v2/run-method-catalog",{method:"POST",headers,body:JSON.stringify({conversation_id:conversationId,selected_refs:selectedRefs}),credentials:"same-origin",cache:"no-store",redirect:"error",signal});
    if(!response.ok){if(response.headers.get("content-type")?.toLowerCase().includes("application/json")){const value:unknown=await response.json();validateRunResponse("error",value);throw new RunApiError(response.status,value as RunApiErrorBody);}throw new RunHttpError(response.status,await response.text());}
    const value:unknown=await response.json();
    if(!validateCreateMethodCatalog(value))throw new Error("创建方法目录格式无效");
    const result=value as CreateMethodCatalog;
    if(result.conversation_id!==conversationId||JSON.stringify(result.selected_refs)!==JSON.stringify(selectedRefs)||new Set(result.methods.map(item=>item.sop_id)).size!==result.methods.length)throw new Error("创建方法目录与会话来源不一致");
    return result;
  }

  async createReceipt(requestKey: string, signal?: AbortSignal): Promise<OriginalRequestReceipt> {
    this.validateMutation("查询", 0, requestKey);
    const receipt = await this.request<OriginalRequestReceipt>("/api/v2/requests/" + encodeURIComponent(requestKey), "request_receipt", signal);
    if (receipt.request_key !== requestKey || receipt.operation !== "create" || receipt.outcome !== "RECORDED" ||
        !("run_id" in receipt.receipt) || receipt.receipt.run_id !== receipt.run_id) throw new Error("原创建请求回执不一致");
    return receipt;
  }

  async read(runId: string, signal?: AbortSignal): Promise<RunSnapshot> {
    const snapshot = await this.request<RunSnapshot>(this.path(runId), "snapshot", signal);
    if (snapshot.run_id !== runId) throw new Error("运行读取结果与请求不一致");
    if(snapshot.requirements.goal_revision!==snapshot.goal_revision || (snapshot.requirements.state==="CONFIRMED")!==Array.isArray(snapshot.requirements.required_outputs)) throw new Error("成果要求与当前目标版本不一致");
    if(snapshot.method_selection&&snapshot.method_selection.goal_revision>snapshot.goal_revision)throw new Error("方法选择与当前目标版本不一致");
    return snapshot;
  }

  resumeStatusPath(runId:string):string {
    return this.path(runId) + "/resume-status";
  }

  completionInspectionPath(runId:string,finishEventId?:string):string {
    const base=this.path(runId) + "/completion-inspection";
    return finishEventId ? base + "?" + new URLSearchParams({finish_event_id:finishEventId}) : base;
  }

  async resumeStatus(runId:string,signal?:AbortSignal):Promise<{status:ResumeStatus}|{httpStatus:number}> {
    const token=this.options.getToken();
    const response=await fetch(this.path(runId)+"/resume-status",{headers:token?{Authorization:"Bearer "+token}:{},credentials:"same-origin",cache:"no-store",redirect:"error",signal});
    if(!response.ok)return {httpStatus:response.status};
    const value:unknown=await response.json();
    if(!validateResumeStatus!(value))throw new Error("运行恢复状态不符合 Schema："+schemaValidator.errorsText(validateResumeStatus!.errors));
    const status=value as ResumeStatus;
    if(status.run_id!==runId)throw new Error("运行恢复状态与请求不一致");
    return {status};
  }

  async intent(runId: string, signal?: AbortSignal): Promise<IntentPreview> {
    const result = await this.request<IntentPreview>(this.path(runId) + "/intent", "intent_preview", signal);
    if (result.run_id !== runId) throw new Error("意图与当前运行不一致");
    if("action" in result.preview&&result.preview.action==="boss.meeting.confirm"){
      const impact=result.preview.impact,calendar=impact?.private_calendar,travel=impact?.overlapping_travel_ids;
      if(!impact||typeof impact.requires_owner_acknowledgement!=="boolean"||!calendar||typeof calendar!=="object"||!("conflict" in calendar)||typeof calendar.conflict!=="boolean"||!Array.isArray(travel)||travel.some(item=>typeof item!=="string")||impact.requires_owner_acknowledgement!==(calendar.conflict||travel.length>0))throw new Error("会议冲突确认条件不可核查");
    }
    if("action" in result.preview&&["boss.meeting.cancel","boss.meeting.held"].includes(result.preview.action)){
      const preview=result.preview,params=preview.params,details=preview.details;
      if(params.meeting_id!==preview.object_id||params.expected_version!==preview.object_revision||details.meeting_id!==preview.object_id||details.version!==preview.object_revision||typeof params.reason!=="string"||!params.reason.trim()||details.reason!==params.reason||typeof details.state!=="string"||typeof details.starts_at!=="string"||!details.starts_at.trim()||(preview.action==="boss.meeting.held"&&details.state!=="SCHEDULED"))throw new Error("会议本人决定预览与对象或版本不一致");
    }
    return result;
  }

  async decision(intentId: string, decision: "CONFIRM" | "REJECT", revision: number, digest: string, requestKey: string, acknowledgeConflict?:boolean, expected?:DomainDecisionExpectation): Promise<DecisionReceipt> {
    const payload = {decision, expected_revision: revision, payload_digest: digest, request_key: requestKey, ...(acknowledgeConflict===true?{acknowledge_conflict:true}:{})};
    validateRunResponse("decision", payload);
    if (!intentId.trim() || [...intentId].length > 160) throw new Error("意图编号无效");
    const result = await this.request<DecisionReceipt>("/api/v2/intents/" + encodeURIComponent(intentId) + "/decision", "decision_receipt", undefined, payload);
    this.checkDecisionReceipt(result, requestKey, intentId, decision, revision,expected);
    return result;
  }

  async decisionReceipt(requestKey: string, intentId: string, decision: "CONFIRM" | "REJECT", revision: number,expected?:DomainDecisionExpectation): Promise<DecisionReceipt> {
    const result = await this.request<DecisionReceipt>("/api/v2/intent-decisions/" + encodeURIComponent(requestKey), "decision_receipt");
    this.checkDecisionReceipt(result, requestKey, intentId, decision, revision,expected);
    return result;
  }

  private checkDecisionReceipt(result: DecisionReceipt, requestKey: string, intentId: string, decision: "CONFIRM" | "REJECT", revision: number,expected?:DomainDecisionExpectation): void {
    if (result.request_key !== requestKey || result.receipt.intent_id !== intentId || result.receipt.revision !== revision + 1 ||
        result.receipt.status !== (decision === "CONFIRM" ? "SUCCEEDED" : "REJECTED")) throw new Error("本人决定回执与原请求不一致");
    if(expected&&decision==="CONFIRM"&&(result.receipt.action!==expected.action||result.receipt.goal_revision!==expected.goal_revision||!result.receipt.source_refs||result.receipt.source_refs.length!==expected.source_refs.length||result.receipt.source_refs.some((source,index)=>source.source_id!==expected.source_refs[index].source_id||source.version!==expected.source_refs[index].version||source.source_sha256!==expected.source_refs[index].source_sha256)))throw new Error("本人决定回执的目标或来源与原请求不一致");
    if(expected&&decision==="CONFIRM"&&["boss.meeting.confirm","boss.meeting.cancel","boss.meeting.held","boss.minutes.confirm"].includes(expected.action)&&result.receipt.business_object_id!==expected.object_id)throw new Error("本人决定回执的对象与原请求不一致");
  }

  async supplement(runId: string, input: string, expectedGoalRevision: number, requestKey: string, signal?: AbortSignal, requiredOutputs?: RequiredOutput[]): Promise<RunInputReceipt> {
    this.validateMutation(input, expectedGoalRevision, requestKey);
    const receipt=await this.request<RunInputReceipt>(this.path(runId) + "/inputs", "input_receipt", signal,
      {input, expected_goal_revision: expectedGoalRevision, request_key: requestKey, ...(requiredOutputs ? {required_outputs:requiredOutputs} : {})});
    if(receipt.goal_revision!==expectedGoalRevision+1)throw new Error("补充输入回执的目标版本不一致");
    return receipt;
  }

  async selectMethod(runId:string,goalRevision:number,requestKey:string,method:MethodSelection):Promise<MethodReceipt> {
    const body={expected_goal_revision:goalRevision,request_key:requestKey,method_selection:method};
    validateRunResponse("method_reselection",body);
    const receipt=await this.request<MethodReceipt>(this.path(runId)+"/method-selection","method_reselection_receipt",undefined,body);
    this.checkMethodReceipt(receipt,runId,requestKey,goalRevision,method);
    return receipt;
  }

  async availableMethods(runId:string,goalRevision:number,signal?:AbortSignal):Promise<MethodCatalog> {
    const result=await this.request<MethodCatalog>(this.path(runId)+"/available-methods","method_catalog",signal);
    if(result.run_id!==runId||result.goal_revision!==goalRevision||new Set(result.methods.map(item=>item.sop_id)).size!==result.methods.length)throw new Error("方法目录与当前运行或目标版本不一致");
    return result;
  }

  private async objectRequest<T>(path:string,kind:RunSchemaKind,signal?:AbortSignal,body?:object):Promise<ObjectResponse<T>> {
    const token=this.options.getToken();
    const headers=new Headers();
    if(token)headers.set("Authorization","Bearer "+token);
    if(body)headers.set("Content-Type","application/json");
    const response=await fetch(path,{method:body?"POST":"GET",headers,body:body?JSON.stringify(body):undefined,credentials:"same-origin",cache:"no-store",redirect:"error",signal});
    if(!response.ok)return {ok:false,status:response.status,message:await response.text()};
    const value:unknown=await response.json();
    validateRunResponse(kind,value);
    return {ok:true,value:value as T};
  }

  async objectCandidates(runId:string,goalRevision:number,signal?:AbortSignal):Promise<ObjectResponse<ObjectCandidates>> {
    const response=await this.objectRequest<ObjectCandidates>(this.path(runId)+"/object-scope/candidates","object_scope_candidates",signal);
    if(!response.ok)return response;
    const result=response.value;
    const keys=result.objects.map(item=>JSON.stringify([item.entity_type,item.object_id]));
    if(result.run_id!==runId||result.goal_revision!==goalRevision||new Set(keys).size!==keys.length||result.selection_allowed!==(result.unavailable_reasons.length===0))throw new Error("对象候选与当前运行、目标版本或选择状态不一致");
    return response;
  }

  async meetingCandidate(runId:string,goalRevision:number,meetingId:string,signal?:AbortSignal):Promise<ObjectResponse<ObjectCandidates>> {
    if(!meetingId.trim()||[...meetingId].length>128)throw new Error("会议编号无效");
    const response=await this.objectRequest<ObjectCandidates>(this.path(runId)+"/object-scope/meeting-candidates/"+encodeURIComponent(meetingId),"object_scope_candidates",signal);
    if(!response.ok)return response;
    const result=response.value;
    if(result.run_id!==runId||result.goal_revision!==goalRevision||result.selection_allowed!==(result.unavailable_reasons.length===0)||result.objects.length>1||result.objects.some(item=>item.entity_type!=="meeting_context"||item.object_id!==meetingId))throw new Error("会议候选与当前运行、目标版本或会议不一致");
    return response;
  }

  async bindObjects(runId:string,goalRevision:number,requestKey:string,objects:ObjectReference[]):Promise<ObjectResponse<ObjectReceipt>> {
    const body={expected_goal_revision:goalRevision,request_key:requestKey,objects};
    validateRunResponse("object_scope_request",body);
    const response=await this.objectRequest<ObjectReceipt>(this.path(runId)+"/object-scope","object_scope_receipt",undefined,body);
    if(response.ok)this.checkObjectReceipt(response.value,runId,goalRevision,requestKey,objects);
    return response;
  }

  async objectReceipt(runId:string,goalRevision:number,requestKey:string,objects:ObjectReference[]):Promise<ObjectResponse<ObjectReceipt>> {
    const response=await this.objectRequest<ObjectReceipt>(this.path(runId)+"/object-scope/requests/"+encodeURIComponent(requestKey),"object_scope_receipt");
    if(response.ok)this.checkObjectReceipt(response.value,runId,goalRevision,requestKey,objects);
    return response;
  }

  private checkObjectReceipt(receipt:ObjectReceipt,runId:string,goalRevision:number,requestKey:string,objects:ObjectReference[]):void {
    if(receipt.run_id!==runId||receipt.goal_revision!==goalRevision||receipt.request_key!==requestKey||receipt.objects.length!==objects.length||receipt.objects.some((item,index)=>{const expected=objects[index];return item.entity_type!==expected.entity_type||item.object_id!==expected.object_id||item.version!==expected.version||item.sha256!==expected.sha256;}))throw new Error("对象选择回执与原请求不一致");
  }

  async methodReceipt(runId:string,requestKey:string,goalRevision:number,method:MethodSelection):Promise<MethodReceipt> {
    const receipt=await this.request<MethodReceipt>(this.path(runId)+"/method-selection/requests/"+encodeURIComponent(requestKey),"method_reselection_receipt");
    this.checkMethodReceipt(receipt,runId,requestKey,goalRevision,method);
    return receipt;
  }

  private checkMethodReceipt(receipt:MethodReceipt,runId:string,requestKey:string,goalRevision:number,method:MethodSelection):void {
    const selected=receipt.method_selection;
    if(receipt.run_id!==runId||receipt.request_key!==requestKey||receipt.goal_revision!==goalRevision||selected.goal_revision!==goalRevision||selected.sop_id!==method.sop_id||selected.version!==method.version||selected.content_sha256!==method.content_sha256)throw new Error("方法选择回执与原请求不一致");
  }

  async cancel(runId: string, expectedRevision: number, requestKey: string, signal?: AbortSignal): Promise<RunReceipt> {
    this.validateMutation("取消", expectedRevision, requestKey);
    const receipt = await this.request<RunReceipt>(this.path(runId) + "/cancel", "receipt", signal,
      {expected_revision: expectedRevision, request_key: requestKey});
    if (receipt.run_id !== runId) throw new Error("取消回执与请求不一致");
    return receipt;
  }

  async events(runId: string, afterSeq: number, signal?: AbortSignal): Promise<RunEventPage> {
    if (!Number.isSafeInteger(afterSeq) || afterSeq < 0) throw new Error("事件游标无效");
    const page = await this.request<RunEventPage>(this.path(runId) + "/events?after_seq=" + afterSeq, "page", signal);
    const ordered = orderRunEvents(runId, afterSeq, page.events);
    if (ordered.events.length !== page.events.length || ordered.events.some((event, index) => event !== page.events[index]) ||
        page.events.some(event => event.seq <= afterSeq) || page.next_seq !== (page.events.length ? page.events[page.events.length - 1].seq : afterSeq) ||
        page.has_more && page.events.length === 0) throw new Error("事件分页与请求游标不一致");
    return page;
  }

  async result(runId: string, signal?: AbortSignal): Promise<RunResult> {
    const value = await this.request<RunResult>(this.path(runId) + "/result", "result", signal);
    if (value.run_id !== runId || value.result && (value.result.run_id !== runId || value.result.payload.goal_revision !== value.goal_revision))
      throw new Error("运行结果与请求或目标版本不一致");
    if (value.result) {
      const pins = value.result.payload.source_pins;
      if (new Set(pins.map(pin => pin.source_id)).size !== pins.length || value.result.payload.citations.some(citation => !pins.some(pin => pin.source_id === citation.source_id)))
        throw new Error("运行结果的来源引用不一致");
      if(value.citation_checks && (value.citation_checks.length!==value.result.payload.citations.length || value.citation_checks.some((check,index)=>check.source_id!==value.result!.payload.citations[index].source_id||check.locator!==value.result!.payload.citations[index].locator))) throw new Error("引用核查记录与结果不一致");
    }
    if(!value.result&&value.citation_checks!==null)throw new Error("缺少运行结果，无法核查引用");
    return value;
  }

  async requestReceipt(requestKey: string, runId: string, action: "inputs" | "cancel", signal?: AbortSignal): Promise<OriginalRequestReceipt> {
    this.validateMutation("查询", 0, requestKey);
    this.path(runId);
    const receipt = await this.request<OriginalRequestReceipt>("/api/v2/requests/" + encodeURIComponent(requestKey), "request_receipt", signal);
    if (receipt.request_key !== requestKey || receipt.run_id !== runId || receipt.operation !== action || receipt.outcome !== "RECORDED" ||
        (action === "cancel" && (!("run_id" in receipt.receipt) || receipt.receipt.run_id !== runId))) {
      throw new Error("原请求回执与当前运行不一致");
    }
    return receipt;
  }

  private validateMutation(input: string, revision: number, requestKey: string): void {
    if (!input.trim() || [...input].length > 65536 || !requestKey.trim() || [...requestKey].length > 128 ||
        !Number.isSafeInteger(revision) || revision < 0) throw new Error("请求字段无效");
  }
}
