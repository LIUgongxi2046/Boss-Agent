import { useCallback, useState } from "react";
import { createRoot } from "react-dom/client";
import { MaintainerSkillVersions } from "../../../app/webui/MaintainerSkillVersions";
import "../../../app/webui/boss-v6.css";

function Check(){
  const [token,setToken]=useState(()=>document.querySelector<HTMLMetaElement>('meta[name="maintainer-token"]')?.content??"");
  const [error,setError]=useState("");
  const getToken=useCallback(()=>token,[token]);
  const mutate=useCallback(async(action:string,payload:Record<string,unknown>)=>{
    const response=await fetch("/component/sop-command",{method:"POST",headers:{Authorization:"Bearer "+token,"Content-Type":"application/json"},
      body:JSON.stringify({action,payload})});
    const result=await response.json() as Record<string,unknown>;
    if(!response.ok)throw Object.assign(Error("方法操作失败（HTTP "+response.status+"）："+String(result.error)),{status:response.status});
    return result;
  },[token]);
  async function revoke(){
    try{
      const response=await fetch("/component/session/revoke",{method:"POST",headers:{Authorization:"Bearer "+token}});
      if(!response.ok)throw Error("当前维护会话撤销失败");
      setToken("");
    }catch(failure){setError(failure instanceof Error?failure.message:String(failure));}
  }
  return <><section aria-label="本机验证会话"><button type="button" onClick={()=>void revoke()}>撤销本次维护会话</button>
    <p role="status">外部依赖 SIMULATED；本地鉴权与SQLite使用实际实现。</p>{error&&<p role="alert">{error}</p>}</section>
    <MaintainerSkillVersions identityKey={token} getToken={getToken} mutate={mutate}/></>;
}
const root=document.getElementById("root");
if(!root)throw Error("缺少页面根元素");
createRoot(root).render(<Check/>);
