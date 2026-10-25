import {useEffect,useRef,useState} from "react";
import {useClient} from "@/providers/ClientProvider";

export function BossOriginalReceipt({scope,actions,onRecorded}:{scope:string;actions:readonly string[];onRecorded:()=>void}){
  const {getToken,token}=useClient();
  const [busy,setBusy]=useState(false),[error,setError]=useState("");
  const epoch=useRef(0);
  useEffect(()=>{epoch.current++;setBusy(false);setError("");return()=>{epoch.current++;};},[token]);
  const values=new URLSearchParams(window.location.search),id=values.get(scope+"Request"),action=values.get(scope+"Action"),target=values.get(scope+"Target");
  if(!id||!action||!actions.includes(action))return null;
  async function read(){
    if(busy||!id||!action)return;const current=epoch.current;setBusy(true);setError("");
    await fetch("/api/boss/ui/operation-status?"+new URLSearchParams({action,client_request_id:id}),{headers:{Authorization:"Bearer "+getToken()},cache:"no-store"}).then(async response=>{
      if(current!==epoch.current)return;
      if(response.status===401)window.dispatchEvent(new Event("boss-auth-expired"));
      if(!response.ok)throw new Error("当前身份无法核查原回执，HTTP "+response.status);
      const receipt=await response.json();if(current!==epoch.current)return;
      if(receipt.action!==action||receipt.client_request_id!==id||receipt.write_performed_by_lookup!==false)throw new Error("原回执标识或只读属性不符");
      if(receipt.outcome!=="RECORDED"||!receipt.result)throw new Error("原请求结果仍未确定，请继续查询同一编号。");
      const object=action.startsWith("boss.alert.")?receipt.result.event_id:receipt.result.task_id??receipt.result.task?.task_id??receipt.result.commitment_id??receipt.result.event_id??receipt.result.plan_id;
      if(target&&object!==target)throw new Error("原回执不属于当前记录的对象");
      const url=new URL(window.location.href);if(url.searchParams.get(scope+"Request")!==id||url.searchParams.get(scope+"Action")!==action)throw new Error("当前原请求编号已经变化，请重新核查。");for(const suffix of ["Request","Action","Target"])url.searchParams.delete(scope+suffix);window.history.replaceState(window.history.state,"",url);onRecorded();
    }).catch(failure=>{if(current===epoch.current)setError(failure.message);});
    if(current===epoch.current)setBusy(false);
  }
  return <section className="boss-panel" aria-label="当前身份只读核查原回执"><h2>查询原操作回执</h2><p>当前身份只能读取原编号的正式结果。此处没有提交、恢复授权或继续执行的操作。</p><p>原编号 {id} · 动作 {action}{target&&" · 对象 "+target}</p><button className="boss-btn" type="button" disabled={busy} onClick={()=>void read()}>使用当前身份查询原回执（只读）</button>{error&&<p role="alert" className="boss-status boss-status-error">{error}</p>}</section>;
}
