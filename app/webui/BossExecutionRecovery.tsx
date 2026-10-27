import {useEffect,useRef,useState} from "react";
import {useClient} from "@/providers/ClientProvider";
import {V7Empty,V7Fact,V7Panel,V7ReadState,V7Steps} from "./BossV7UI";

type Receipt={action:string;client_request_id:string;outcome:"RECORDED"|"NOT_FOUND_IN_CURRENT_STORE";result?:Record<string,unknown>};
function initial(){const params=new URLSearchParams(window.location.search);for(const scope of ["bossRecovery","assignment","feedback","commitment","reminder","ownerNotice","ownerGoalsReadonly","plan","scheduler","alerts","alertRules","alertInput"]){const request=params.get(scope+"Request"),action=params.get(scope+"Action");if(request&&action)return{request,action};}return{request:"",action:""};}

export function BossExecutionRecovery({taskId,onOpenTask,onNavigate}:{taskId?:string;onOpenTask:(id:string)=>void;onNavigate:(page:string)=>void}){
  const {getToken}=useClient();
  const [values,setValues]=useState(initial);
  const [receipt,setReceipt]=useState<Receipt|null>(null);
  const [loading,setLoading]=useState(false);
  const [error,setError]=useState("");
  const controller=useRef<AbortController|null>(null);
  useEffect(()=>()=>controller.current?.abort(),[]);
  function read(){
    if(!values.action.trim()||!values.request.trim()){setError("请提供原动作与原请求编号");return;}
    controller.current?.abort();const abort=new AbortController();controller.current=abort;setLoading(true);setError("");setReceipt(null);
    const request=values.request.trim(),action=values.action.trim();
    const url=new URL(window.location.href);url.searchParams.set("bossRecoveryRequest",request);url.searchParams.set("bossRecoveryAction",action);window.history.replaceState(window.history.state,"",url);
    void fetch("/api/boss/ui/operation-status?"+new URLSearchParams({action,client_request_id:request}),{headers:{Authorization:"Bearer "+getToken()},signal:abort.signal,cache:"no-store"}).then(async response=>{
      if(response.status===401)window.dispatchEvent(new Event("boss-auth-expired"));
      if(!response.ok)throw new Error("执行结果查询失败（HTTP "+response.status+"）");
      const next=await response.json() as Receipt;
      if(next.action!==action||next.client_request_id!==request||!["RECORDED","NOT_FOUND_IN_CURRENT_STORE"].includes(next.outcome))throw new Error("回执与原请求不一致");
      if(abort.signal.aborted)return;setReceipt(next);setLoading(false);
    }).then(undefined,reason=>{if(!abort.signal.aborted){setLoading(false);setError(reason.message);}});
  }
  const resultTask=typeof receipt?.result?.task_id==="string"?receipt.result.task_id:taskId;
  return <><V7ReadState loading={loading} error={error}/><div className="boss-columns"><div className="boss-column">
    <V7Panel title="执行结果核查" description="通过原请求编号读取服务端回执，不会再次执行原业务动作。"><details><summary>按编号查询</summary><form onSubmit={event=>{event.preventDefault();read();}}><div className="boss-form-grid"><label>原动作<input required value={values.action} onChange={event=>{setValues(current=>({...current,action:event.target.value}));setReceipt(null);}} placeholder="原请求中的 action"/></label><label>原请求编号<input required value={values.request} onChange={event=>{setValues(current=>({...current,request:event.target.value}));setReceipt(null);}} placeholder="client_request_id"/></label></div></form></details><div className="boss-actions"><button className="boss-btn boss-btn-primary" disabled={loading||!values.action.trim()||!values.request.trim()} onClick={read}>查询原请求结果</button><button className="boss-btn" type="button" disabled={!loading} onClick={()=>{controller.current?.abort();setLoading(false);}}>{loading?"停止本次查询":"取消本次查询"}</button></div></V7Panel>
    <V7Panel title="当前正式状态">{receipt?<><V7Fact label="查询结论">{receipt.outcome==="RECORDED"?"已找到执行回执":"执行结果仍未确定"}</V7Fact><V7Fact label="原请求编号">{receipt.client_request_id}</V7Fact><V7Fact label="动作">{receipt.action}</V7Fact>{receipt.result?<pre className="boss-v7-code">{JSON.stringify(receipt.result,null,2)}</pre>:<p>当前没有找到该请求记录。继续使用原编号核查，读取业务对象的当前状态。</p>}</>:<V7Empty title="尚未查询原执行结果">网络中断、超时或页面关闭后，使用原请求信息继续核查。</V7Empty>}</V7Panel>
  </div><aside className="boss-column"><V7Panel title="恢复步骤"><V7Steps steps={[
    {title:"定位原请求",description:values.request?values.request:"提供原请求编号",state:values.request?"complete":"current"},
    {title:"查询正式回执",description:receipt?.outcome==="RECORDED"?"已取得回执":receipt?"仍需核查":"尚未查询",state:receipt?.outcome==="RECORDED"?"complete":receipt?"current":"waiting"},
    {title:"核查业务对象",description:"读取当前任务、消息和有效授权",state:"waiting"},
  ]}/><div className="boss-actions"><button className="boss-btn" disabled={!resultTask} onClick={()=>{if(resultTask)onOpenTask(resultTask);}}>打开当前任务</button><button className="boss-btn" onClick={()=>onNavigate("N10")}>查看本次授权</button><button className="boss-btn" onClick={()=>onNavigate("F08")}>查看消息记录</button>{taskId&&<button className="boss-btn" onClick={()=>onNavigate("F29")}>返回原任务异常</button>}</div></V7Panel><V7Panel title="已执行与未执行"><p>操作结果以正式回执和业务对象为依据。取消查询只终止本次读取。</p></V7Panel></aside></div></>;
}
