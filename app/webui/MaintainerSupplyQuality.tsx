import {useState} from "react";
import {useClient} from "@/providers/ClientProvider";
import definition from "./supply-quality-v1.json";
import type {SupplyQualityReceipt} from "./BossSupplyQualityPanel";

const IMPORT="boss.simulation.supply_quality.import";
const WITHDRAW="boss.simulation.supply_quality.withdraw";
type Choice="initial_request"|"empty_request"|"failed_request"|"timeout_request"|"withdraw";
export type SupplyImportEditor={choice:Choice;text:string;approvedText:string|null;pending:{action:string;payload:Record<string,unknown>}|null};
export const EMPTY_IMPORT_EDITOR:SupplyImportEditor={choice:"initial_request",text:"",approvedText:null,pending:null};
type Props={editor:SupplyImportEditor;onEditorChange:(changes:Partial<SupplyImportEditor>)=>void};

export function MaintainerSupplyQuality({editor,onEditorChange}:Props){
  const {client,getToken}=useClient();
  const [busy,setBusy]=useState(false);
  const [error,setError]=useState("");
  const [result,setResult]=useState<unknown>(null);
  const {choice,text,approvedText,pending}=editor;
  function load(){
    const payload:Record<string,unknown>=choice==="withdraw"?{client_request_id:"supply-withdraw-"+crypto.randomUUID(),entity_type:"inventory_lot",record_id:"",expected_version:"",reason:""}:
      {...definition[choice],client_request_id:"supply-import-"+crypto.randomUUID()};
    onEditorChange({text:JSON.stringify(payload,null,2),approvedText:null});setResult(null);setError("");
  }
  function record(action:string,value:unknown){
    const receipt=value as {state?:unknown;record_state?:unknown;external_service_invoked?:unknown};
    if(action===IMPORT&&(!["SUCCESS","EMPTY","FAILED","TIMED_OUT"].includes(String(receipt?.state))||receipt.external_service_invoked!==false))
      throw Error("导入回执内容与模拟范围不符，请保留原请求继续核查。");
    if(action===WITHDRAW&&receipt?.record_state!=="WITHDRAWN")throw Error("撤销回执状态不符，请保留原请求继续核查。");
    setResult(value);onEditorChange({text:"",approvedText:null,pending:null});
  }
  async function original(request:NonNullable<SupplyImportEditor["pending"]>){
    const token=getToken();
    if(!token)throw Error("当前身份令牌失效，请重新登录。");
    const response=await fetch("/api/boss/ui/supply-quality-receipt?"+new URLSearchParams({action:request.action,client_request_id:String(request.payload.client_request_id)}),
      {headers:{Authorization:"Bearer "+token},cache:"no-store"});
    if(!response.ok)throw Error("原请求读取失败（HTTP "+response.status+"）");
    const receipt=await response.json() as SupplyQualityReceipt;
    if(receipt.action!==request.action||receipt.client_request_id!==request.payload.client_request_id)throw Error("回执与原请求编号不符。");
    if(receipt.outcome!=="RECORDED")throw Error("当前没有查到原请求回执，请保留原请求继续核查或使用原编号提交。");
    record(request.action,receipt.result);
  }
  async function submit(){
    if(busy||(!pending&&(!text||approvedText!==text)))return;
    setBusy(true);setError("");setResult(null);
    try{
      const payload=pending?.payload??JSON.parse(text) as unknown;
      if(!payload||typeof payload!=="object"||Array.isArray(payload)||typeof (payload as Record<string,unknown>).client_request_id!=="string")throw Error("输入必须为包含client_request_id的JSON对象。");
      const request=pending??{action:choice==="withdraw"?WITHDRAW:IMPORT,payload:payload as Record<string,unknown>};
      onEditorChange({pending:request});
      await client.requestMutation<unknown>(request.action,request.payload).then(value=>record(request.action,value),async(failure:unknown)=>{
        if(failure instanceof Error&&failure.name==="WebUIMutationError"&&"status" in failure&&typeof failure.status==="number"){
          if([502,504].includes(failure.status)){await original(request);return;}
          if([400,401,403,404,409,410,413,422].includes(failure.status))onEditorChange({pending:null,approvedText:null});
        }
        throw failure;
      });
    }catch(failure){setError(failure instanceof Error?failure.message:String(failure));}
    finally{setBusy(false);}
  }
  async function reconcile(){
    if(!pending||busy)return;
    setBusy(true);setError("");
    await original(pending).then(undefined,failure=>setError(failure instanceof Error?failure.message:String(failure)));
    setBusy(false);
  }
  const outcome=result as {state?:string;record_state?:string}|null;
  return <section className="boss-panel" aria-label="采购与品质模拟资料维护">
    <div className="boss-panel-head"><h2>采购与品质模拟资料</h2><small>A03 · 显式SIMULATED输入</small></div>
    <p>{definition.purpose}</p><p className="boss-helper">定义 {definition.definition_id} · 版本 {definition.version}。资料只在当前本机空间保存；初始selection保持，所有外部服务调用均为false。</p>
    <fieldset disabled={busy||Boolean(pending)}>
      <label className="boss-field">输入种类<select aria-label="输入种类" value={choice} onChange={event=>onEditorChange({choice:event.target.value as Choice,text:"",approvedText:null})}>
        <option value="initial_request">导入21项模拟业务记录</option><option value="empty_request">模拟空结果</option><option value="failed_request">模拟失败</option><option value="timeout_request">模拟超时</option><option value="withdraw">撤销当前模拟记录</option>
      </select></label>
      <button type="button" className="boss-btn" onClick={load}>载入待检查输入</button>
      <label className="boss-field">完整输入JSON<textarea aria-label="完整输入JSON" rows={18} value={text} onChange={event=>onEditorChange({text:event.target.value,approvedText:null})}/></label>
      <p className="boss-helper">更新需要当前expected_version，重新导入需要明确当前引用。重复提交使用原client_request_id。撤销保留历史回执并停止当前正文采用。</p>
      <label className="boss-confirm-check"><input type="checkbox" checked={Boolean(text)&&approvedText===text} disabled={!text} onChange={event=>onEditorChange({approvedText:event.target.checked?text:null})}/>确认当前输入及模拟状态，仅保存当前资料操作</label>
    </fieldset>
    <div className="boss-actions"><button type="button" className="boss-btn boss-btn-primary" disabled={busy||(!pending&&(!text||approvedText!==text))} onClick={()=>void submit()}>{busy?"正在核查":pending?"使用原请求编号继续提交":"确认保存模拟资料操作"}</button>
      {pending&&<button type="button" className="boss-btn" disabled={busy} onClick={()=>void reconcile()}>核查原资料请求回执</button>}</div>
    {pending&&<p role="status">待核查请求 {String(pending.payload.client_request_id)}。离开页面保留原请求，返回后继续核查。</p>}
    {error&&<p className="boss-status boss-status-error" role="alert">{error}</p>}
    {outcome&&<div role={outcome.state==="FAILED"||outcome.state==="TIMED_OUT"?"alert":"status"} className="boss-status"><p>已保存的原请求状态：{outcome.state??outcome.record_state}</p><pre>{JSON.stringify(result,null,2)}</pre></div>}
  </section>;
}
