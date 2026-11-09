import {useEffect,useState} from "react";
import {resumeStatusSchemaError,Upgrade2RunClient,type ResumeStatus,type RunSnapshot} from "./upgrade2-run-client";

const reasons:Record<string,string>={
  ENGINE_BOUNDARY_UNVERIFIED:"引擎启动条件尚未核查。",
  PROCESS_RECOVERY_UNVERIFIED:"原进程的完整回收尚未核查。",
  BUDGET_REVALIDATION_REQUIRED:"本人预算需要重新核查。",
  RUN_STATE_UNAVAILABLE:"当前运行状态不允许恢复。",
  REQUIRED_OUTPUTS_UNCONFIRMED:"当前目标的必要成果尚未确认。",
  ORIGINAL_LEASE_ACTIVE:"原运行租约仍然有效。",
  ADDITIONAL_INPUT_REQUIRED:"等待本人补充当前目标。",
  CHILD_RUN_RECOVERY_UNAVAILABLE:"子运行的恢复条件尚未具备。",
  PROCESS_RECORDS_UNAVAILABLE:"进程记录尚不可核查。",
  PROCESS_CAPACITY_UNRESOLVED:"原进程占用的运行额度尚未核查。",
  PRIOR_PROCESS_SCOPE_UNVERIFIED:"原进程范围尚未核查。",
};

type View={scope:string;status:ResumeStatus|null;message:string};

export function Upgrade2ResumeStatus({client,snapshot,token,getToken,onAccessDenied,timeoutMs=15000}:{client:Upgrade2RunClient;snapshot:RunSnapshot;token:string;getToken:()=>string;onAccessDenied:(status:number)=>void;timeoutMs?:number}) {
  const scope=JSON.stringify([snapshot.run_id,snapshot.revision,snapshot.goal_revision,token]);
  const [view,setView]=useState<View|null>(null);
  const [attempt,setAttempt]=useState(0);
  useEffect(()=>{
    let active=true;
    const xhr=new XMLHttpRequest();
    xhr.open("GET",client.resumeStatusPath(snapshot.run_id));
    xhr.responseType="json";
    xhr.timeout=timeoutMs;
    if(token)xhr.setRequestHeader("Authorization","Bearer "+token);
    const same=()=>active&&getToken()===token;
    const timer=window.setTimeout(()=>{
      if(!same())return;
      active=false;
      xhr.abort();
      setView({scope,status:null,message:"恢复条件读取超时，请检查网络后重新读取。"});
    },timeoutMs);
    const finish=()=>{active=false;window.clearTimeout(timer);};
    xhr.onload=()=>{
      if(!same())return;
      finish();
      if(xhr.status<200||xhr.status>=300){
        if(xhr.status===401)window.dispatchEvent(new Event("boss-auth-expired"));
        if([401,403,410].includes(xhr.status))onAccessDenied(xhr.status);
        setView({scope,status:null,message:"恢复条件读取失败，HTTP "+xhr.status+"。"});
        return;
      }
      const value:unknown=xhr.response;
      const schemaError=resumeStatusSchemaError(value);
      if(schemaError){setView({scope,status:null,message:schemaError});return;}
      const status=value as ResumeStatus;
      if(status.run_id!==snapshot.run_id){setView({scope,status:null,message:"运行恢复状态与当前运行不一致，请重新读取运行。"});return;}
      if(status.revision!==snapshot.revision||status.goal_revision!==snapshot.goal_revision||status.status!==snapshot.status){
        setView({scope,status:null,message:"运行状态已经变化，请重新读取。"});
        return;
      }
      setView({scope,status,message:""});
    };
    xhr.onerror=()=>{if(!same())return;finish();setView({scope,status:null,message:"恢复条件读取失败：无法连接服务，请检查网络后重新读取。"});};
    xhr.ontimeout=()=>{if(!same())return;finish();setView({scope,status:null,message:"恢复条件读取超时，请检查网络后重新读取。"});};
    xhr.send();
    return()=>{active=false;window.clearTimeout(timer);xhr.abort();};
  },[attempt,client,getToken,onAccessDenied,scope,snapshot.run_id,snapshot.revision,snapshot.goal_revision,snapshot.status,token,timeoutMs]);
  const current=view?.scope===scope?view:null;
  return <section className="upgrade2-run-card" aria-label="继续运行条件"><h3>继续运行条件</h3>
    {!current?<p role="status">正在读取继续运行条件。</p>:current.message?<><p role="alert">{current.message}</p><button type="button" className="boss-btn" onClick={()=>setAttempt(value=>value+1)}>重新读取继续运行条件</button></>:<><p>当前没有获准的继续运行操作。</p><ul>{current.status!.waiting_reasons.map(reason=><li key={reason}>{reasons[reason]}</li>)}</ul><button type="button" className="boss-btn" onClick={()=>setAttempt(value=>value+1)}>重新读取继续运行条件</button></>}
  </section>;
}
