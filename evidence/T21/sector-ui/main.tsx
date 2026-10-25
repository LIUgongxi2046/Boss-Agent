import { useMemo, useState } from "react";
import { createRoot } from "react-dom/client";
import { ClientProvider } from "@/providers/ClientProvider";
import { NanobotClient } from "@/lib/nanobot-client";
import { BossSectorView, SECTOR_PAGE_IDS } from "../../../app/webui/BossSectorView";
import "../../../app/webui/boss-v6.css";

function Check(){
  const [token,setToken]=useState(()=>document.querySelector<HTMLMetaElement>('meta[name="boss-token"]')?.content??"");
  const [page,setPage]=useState("F14");
  const [error,setError]=useState("");
  const client=useMemo(()=>new NanobotClient({url:location.origin.replace("http","ws"),reconnect:false}),[]);
  async function revoke(){
    const response=await fetch("/component/session/revoke",{method:"POST",headers:{Authorization:"Bearer "+token}});
    if(!response.ok)throw Error("当前老板会话撤销失败");
    setToken("");
  }
  function navigate(next:string){
    if((SECTOR_PAGE_IDS as readonly string[]).includes(next))setPage(next);
    else setError("当前独立入口仅验证专题读取与身份");
  }
  return <ClientProvider client={client} token={token}>
    <section aria-label="专题验证控制"><label>专题页面<select aria-label="专题页面" value={page} onChange={event=>setPage(event.target.value)}>
      {SECTOR_PAGE_IDS.map(id=><option key={id} value={id}>{id}</option>)}</select></label>
      <button type="button" onClick={()=>{void revoke().catch(failure=>setError(failure instanceof Error?failure.message:String(failure)));}}>撤销本次老板会话</button>
      <p role="status">外部依赖 SIMULATED；当前入口验证专题读取与身份。</p>{error&&<p role="alert">{error}</p>}
    </section>
    <BossSectorView pageId={page} onNavigate={navigate}
      onViewSource={()=>setError("当前独立入口未提供公共原文导航")}
      onStartChat={async()=>{throw Error("当前独立入口未配置模型会话服务");}}/>
  </ClientProvider>;
}
const root=document.getElementById("root");
if(!root)throw Error("缺少页面根元素");
createRoot(root).render(<Check/>);
