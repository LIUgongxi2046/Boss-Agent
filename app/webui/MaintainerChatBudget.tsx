import {useEffect, useRef, useState} from "react";

const fields = [
  ["model_requests", "模型请求次数"], ["rounds", "运行轮数"], ["tools", "工具调用次数"],
  ["seconds", "运行时间（秒）"], ["concurrency", "并发额度"], ["context_tokens", "上下文 Token"],
  ["files", "文件数量"], ["file_bytes", "单个文件大小（字节）"], ["open_files", "文件描述符数量"],
  ["cpu_seconds", "CPU 时间（秒）"],
] as const;
type Field = typeof fields[number][0];
type Budget = Record<Field, number>;
type Draft = Record<Field, string>;
type Configuration = {version:number; budget:Budget|null};
type Pending = {request_key:string; expected_version:number; budget:Budget};
const storageKey = "boss-chat-run-budget-pending-v1";
const endpoint = "/api/v2/settings/chat-run-budget";

function emptyDraft():Draft {
  return Object.fromEntries(fields.map(([key])=>[key, ""])) as Draft;
}
function validBudget(value:unknown):value is Budget {
  if (!value || typeof value !== "object" || Array.isArray(value)) return false;
  const object = value as Record<string,unknown>;
  return Object.keys(object).length === fields.length && fields.every(([key])=>
    Number.isSafeInteger(object[key]) && (object[key] as number) >= (key === "open_files" ? 16 : 1));
}
function configuration(value:unknown):Configuration {
  if (!value || typeof value !== "object") throw new Error("预算响应格式无效");
  const result = value as Configuration;
  if (!Number.isSafeInteger(result.version) || result.version < 0 ||
      (result.version === 0 ? result.budget !== null : !validBudget(result.budget))) throw new Error("预算版本或内容无效");
  return result;
}
function readPending():Pending|null {
  const value = localStorage.getItem(storageKey);
  if (value === null) return null;
  const pending = JSON.parse(value) as Pending;
  if (!pending || typeof pending.request_key !== "string" || !pending.request_key ||
      !Number.isSafeInteger(pending.expected_version) || pending.expected_version < 0 || !validBudget(pending.budget))
    throw new Error("原请求记录无效，请保留记录并联系维护人员核查");
  return pending;
}
function draftFrom(budget:Budget|null):Draft {
  return budget ? Object.fromEntries(fields.map(([key])=>[key, String(budget[key])])) as Draft : emptyDraft();
}

export function MaintainerChatBudget({getToken, identityKey, onDirtyChange}:{getToken:()=>string; identityKey:string; onDirtyChange:(dirty:boolean)=>void}) {
  const [data,setData] = useState<Configuration|null>(null);
  const [draft,setDraft] = useState<Draft>(emptyDraft);
  const [dirty,setDirty] = useState(false);
  const [busy,setBusy] = useState(false);
  const [pending,setPending] = useState<Pending|null>(null);
  const [conflict,setConflict] = useState(false);
  const [error,setError] = useState("");
  const [notice,setNotice] = useState("");
  const epoch = useRef(0);
  useEffect(()=>{
    epoch.current++;
    setData(null);setDraft(emptyDraft());setDirty(false);setBusy(false);setConflict(false);setError("");setNotice("");
    try {setPending(readPending());} catch (failure) {setError(failure instanceof Error ? failure.message : String(failure));}
    const changed = (event:StorageEvent)=>{
      if (event.key === storageKey) {
        try {setPending(readPending());setConflict(false);} catch (failure) {setError(failure instanceof Error ? failure.message : String(failure));}
      }
    };
    window.addEventListener("storage", changed);
    return ()=>{epoch.current++;window.removeEventListener("storage",changed);};
  },[identityKey]);
  useEffect(()=>{onDirtyChange(dirty);},[dirty,onDirtyChange]);
  useEffect(()=>()=>onDirtyChange(false),[onDirtyChange]);

  async function request(method:"GET"|"PUT", body?:Pending):Promise<Configuration> {
    const token = getToken();
    if (!token || token !== identityKey) throw new Error("维护身份已经失效，请重新认证");
    const response = await fetch(endpoint,{method,headers:{Authorization:"Bearer "+token,...(body?{"Content-Type":"application/json"}:{})},
      body:body?JSON.stringify(body):undefined,credentials:"same-origin",cache:"no-store",redirect:"error"});
    if (!response.ok) {
      const text = await response.text();
      let code = "";
      if (response.headers.get("content-type")?.includes("application/json")) {
        const parsed:unknown = JSON.parse(text);
        if (parsed && typeof parsed === "object" && "code" in parsed && typeof parsed.code === "string") code = parsed.code;
      }
      throw new BudgetRequestError(response.status,code,`预算请求失败（HTTP ${response.status}）${text ? "："+text : ""}`);
    }
    return configuration(await response.json());
  }
  async function load(discard = false) {
    if (busy || pending || (dirty && !discard)) return;
    const current = epoch.current;
    setBusy(true);setError("");setNotice("");
    try {
      const value = await request("GET");
      if (current !== epoch.current || getToken() !== identityKey) return;
      setData(value);setDraft(draftFrom(value.budget));setDirty(false);
      setNotice(value.budget ? "已读取当前预算。" : "当前尚未配置预算，请填写全部项目。");
    } catch (failure) {if (current === epoch.current) setError(failure instanceof Error ? failure.message : String(failure));}
    finally {if (current === epoch.current) setBusy(false);}
  }
  async function submit(recover:boolean) {
    if (busy || !identityKey) return;
    if (!navigator.locks) {setError("当前环境不支持跨窗口请求保护，无法提交。");return;}
    const current = epoch.current;
    setBusy(true);setError("");setNotice("");setConflict(false);
    try {
      await navigator.locks.request(storageKey,async()=>{
        if (current !== epoch.current || getToken() !== identityKey) throw new Error("维护身份已经变化");
        let original = readPending();
        if (recover) {
          if (!original) throw new Error("原请求记录不存在，请重新读取当前预算");
        } else {
          if (original) {setPending(original);throw new Error("存在等待核查的原请求");}
          if (!data || !dirty) throw new Error("请先读取并编辑当前预算");
          const budget = Object.fromEntries(fields.map(([key])=>[key, Number(draft[key])])) as Budget;
          if (fields.some(([key])=>!/^\d+$/.test(draft[key])) || !validBudget(budget)) throw new Error("请填写全部正整数，文件描述符数量至少为 16");
          original = {request_key:"chat-budget-"+crypto.randomUUID(),expected_version:data.version,budget};
          localStorage.setItem(storageKey,JSON.stringify(original));
          setPending(original);
        }
        const value = await request("PUT",original);
        if (current !== epoch.current || getToken() !== identityKey) return;
        if (value.version !== original.expected_version + 1 || !value.budget ||
            fields.some(([key])=>value.budget![key] !== original!.budget[key])) throw new Error("原请求回执与提交内容不一致");
        if (JSON.stringify(readPending()) !== JSON.stringify(original)) throw new Error("原请求记录已经变化，请继续核查");
        localStorage.removeItem(storageKey);setPending(null);setData(value);setDraft(draftFrom(value.budget));setDirty(false);
        setNotice("原请求已确认，预算版本 "+value.version+" 已保存。请重新读取当前版本。");
      });
    } catch (failure) {
      if (current === epoch.current) {
        if (failure instanceof BudgetRequestError && failure.status === 409 && failure.code === "REVISION_CONFLICT") setConflict(true);
        setError((failure instanceof Error ? failure.message : String(failure))+"。原请求存在时，请继续使用原编号核查。");
      }
    } finally {if (current === epoch.current) setBusy(false);}
  }
  async function finishConflict() {
    if (busy || !conflict || !pending || !navigator.locks) return;
    const current = epoch.current;
    setBusy(true);
    try {
      await navigator.locks.request(storageKey,async()=>{
        if (current !== epoch.current || getToken() !== identityKey || JSON.stringify(readPending()) !== JSON.stringify(pending))
          throw new Error("身份或原请求已经变化，请重新核查");
        const latest = await request("GET");
        if (current !== epoch.current || getToken() !== identityKey || JSON.stringify(readPending()) !== JSON.stringify(pending))
          throw new Error("身份或原请求已经变化，请重新核查");
        localStorage.removeItem(storageKey);setPending(null);setConflict(false);setData(latest);setDraft(draftFrom(pending.budget));setDirty(true);
        setNotice("服务端已拒绝过期版本，已读取当前版本并保留编辑内容。请核查后保存。");
      });
    } catch (failure) {if (current === epoch.current) setError(failure instanceof Error ? failure.message : String(failure));}
    finally {if (current === epoch.current) setBusy(false);}
  }
  return <section aria-label="聊天运行预算">
    <h3>聊天运行预算</h3><p>维护者配置后续聊天运行的额度；已创建运行保留原预算版本。</p>
    {!identityKey && <p role="status">当前维护身份尚未就绪。</p>}
    <p>当前版本：{data ? data.version : "尚未读取"}</p>
    <div className="boss-actions"><button type="button" className="boss-btn" disabled={busy||dirty||!!pending||!identityKey} onClick={()=>void load()}>读取当前预算</button>
      {dirty&&!pending&&<button type="button" className="boss-btn" disabled={busy} onClick={()=>void load(true)}>放弃编辑并重新读取</button>}</div>
    {pending && <div role="status"><p>原请求编号：{pending.request_key}；原版本：{pending.expected_version}。</p>
      <p>原请求结果尚待核查。使用相同编号和内容重新提交，服务端会返回原结果或明确冲突。</p>
      <button type="button" className="boss-btn" disabled={busy||!identityKey} onClick={()=>void submit(true)}>核查原请求</button>
      {conflict&&<button type="button" className="boss-btn" disabled={busy} onClick={()=>void finishConflict()}>读取新版本并保留编辑</button>}</div>}
    <form onSubmit={event=>{event.preventDefault();void submit(false);}}>
      <fieldset className="boss-v7-form-fieldset" disabled={!data||busy||!!pending||!identityKey}>
        <div className="boss-form-grid">{fields.map(([key,label])=><label key={key}>{label}<input type="number" required min={key==="open_files"?16:1} step={1} value={draft[key]} onChange={event=>{setDraft(previous=>({...previous,[key]:event.target.value}));setDirty(true);setNotice("");}}/>{dirty&&<small>当前版本：{data?.budget ? data.budget[key] : "尚未配置"}</small>}</label>)}</div>
        <p className="boss-v7-note">文件大小、文件描述符和 CPU 时间按单个进程限制；所有额度由维护者填写。</p>
        <button type="submit" className="boss-btn boss-btn-primary" disabled={!dirty}>保存预算</button>
      </fieldset>
    </form>
    {error&&<p role="alert">{error}</p>}{notice&&<p role="status">{notice}</p>}
  </section>;
}

class BudgetRequestError extends Error {
  constructor(readonly status:number,readonly code:string,message:string){super(message);}
}
