import {useEffect,useRef,useState} from "react";
import type {CandidateDetail} from "./SkillCandidateReview";

type Status={candidate_id:string;client_request_id:string;state:"NOT_FOUND"|"PREPARED"|"COMPLETED"|"CANCELED";sop_id?:string;result?:{state?:string}|null};
const key="boss-skill-publication-";
class RequestRejected extends Error {constructor(readonly status:number,message:string){super(message);}}

export function SkillCandidatePublication({detail,getToken,identityKey}:{detail:CandidateDetail|null;getToken:()=>string|null;identityKey:string}){
  const [note,setNote]=useState("");
  const [confirmed,setConfirmed]=useState(false);
  const [original,setOriginal]=useState("");
  const [originalCandidate,setOriginalCandidate]=useState("");
  const [status,setStatus]=useState<Status|null>(null);
  const [recoveryPending,setRecoveryPending]=useState("");
  const [publishRejected,setPublishRejected]=useState(false);
  const [recoveryRejected,setRecoveryRejected]=useState(false);
  const [busy,setBusy]=useState(false);
  const [error,setError]=useState("");
  const epoch=useRef(0);
  useEffect(()=>{epoch.current++;setNote("");setConfirmed(false);
    setOriginal(sessionStorage.getItem(key+"request")??"");setOriginalCandidate(sessionStorage.getItem(key+"candidate")??"");
    setRecoveryPending(sessionStorage.getItem(key+"recovery")??"");setPublishRejected(sessionStorage.getItem(key+"publish-rejected")==="yes");setRecoveryRejected(sessionStorage.getItem(key+"recovery-rejected")==="yes");setStatus(null);setBusy(false);setError("");return()=>{epoch.current++;};},[identityKey]);
  useEffect(()=>{setConfirmed(false);setNote("");},[detail?.candidate_id,detail?.content_sha256,detail?.draft_version,detail?.decisions[0]?.authorization_id]);
  const decision=detail?.decisions[0];
  const ready=!!detail&&detail.state==="DRAFT"&&detail.validation_status==="VALIDATED_STATIC_ONLY"&&!detail.errors.length&&!detail.missing_tools.length&&detail.current_active_sha256===detail.base_method.content_sha256&&!!decision&&decision.decision==="APPROVE"&&!decision.expired&&!decision.revoked&&decision.content_sha256===detail.content_sha256&&decision.base_sha256===detail.base_method.content_sha256&&decision.tool_config_sha256===detail.tool_config_sha256;
  async function call(path:string,body?:object){
    const token=getToken();if(!token)throw new Error("当前维护身份已经失效，请重新认证");
    const response=await fetch(path,{method:body?"POST":"GET",headers:{Authorization:"Bearer "+token,...(body?{"Content-Type":"application/json"}:{})},
      body:body?JSON.stringify(body):undefined,credentials:"same-origin",cache:"no-store",redirect:"error"});
    if(!response.ok)throw new RequestRejected(response.status,"请求失败（HTTP "+response.status+"）："+await response.text());
    return await response.json() as unknown;
  }
  async function publish(){
    if(busy||original||!confirmed||!ready||!detail||!decision||!note.trim())return;
    if(!getToken()){setError("当前维护身份已经失效，请重新认证");return;}
    const candidateId=detail.candidate_id;
    const current=epoch.current,id="skill-publish-"+crypto.randomUUID();
    sessionStorage.setItem(key+"request",id);sessionStorage.setItem(key+"candidate",candidateId);
    setOriginal(id);setOriginalCandidate(candidateId);setBusy(true);setError("");
    try{
      const result=await call("/api/v2/skill-candidates/"+encodeURIComponent(candidateId)+"/publish",{client_request_id:id,expected_content_sha256:detail.content_sha256,
        expected_base_sha256:detail.base_method.content_sha256,expected_draft_version:detail.draft_version,authorization_id:decision.authorization_id,change_note:note.trim()}) as {state?:string};
      if(current!==epoch.current)return;
      if(result.state!=="ACTIVE")throw new Error("发布回执状态不完整");
    }catch(failure){if(current===epoch.current){if(failure instanceof RequestRejected&&failure.status>=400&&failure.status<500){sessionStorage.setItem(key+"publish-rejected","yes");setPublishRejected(true);}setError((failure instanceof Error?failure.message:String(failure))+"；请查询原操作状态。");}}
    finally{if(current===epoch.current)setBusy(false);}
  }
  async function readStatus(){
    if(!original||!originalCandidate||busy)return;
    const current=epoch.current;setBusy(true);setError("");setStatus(null);
    try{
      const result=await call("/api/v2/skill-candidates/"+encodeURIComponent(originalCandidate)+"/publications/"+encodeURIComponent(original)) as Status;
      if(current!==epoch.current)return;
      if(result.candidate_id!==originalCandidate||result.client_request_id!==original||!(["NOT_FOUND","PREPARED","COMPLETED","CANCELED"] as string[]).includes(result.state)||result.state!=="NOT_FOUND"&&typeof result.sop_id!=="string")throw new Error("原操作状态不一致");
      if(result.state==="COMPLETED"&&result.result?.state!=="ACTIVE"||result.state==="CANCELED"&&result.result?.state!=="CANCELED")throw new Error("原操作回执状态不一致");
      setStatus(result);
    }catch(failure){if(current===epoch.current)setError(failure instanceof Error?failure.message:String(failure));}
    finally{if(current===epoch.current)setBusy(false);}
  }
  async function recover(action:"recover"|"cancel"){
    if(!status||status.state!=="PREPARED"||!status.sop_id||busy||recoveryPending)return;
    if(!getToken()){setError("当前维护身份已经失效，请重新认证");return;}
    const current=epoch.current,id="skill-"+action+"-"+crypto.randomUUID();
    sessionStorage.setItem(key+"recovery",id);setRecoveryPending(id);setBusy(true);setError("");setStatus(null);
    try{
      await call("/api/v2/skills/"+action,{client_request_id:id,sop_id:status.sop_id,activation_request_id:original});
      if(current===epoch.current)setError("操作已返回，请查询原发布状态。");
    }catch(failure){if(current===epoch.current){if(failure instanceof RequestRejected&&failure.status>=400&&failure.status<500){sessionStorage.setItem(key+"recovery-rejected","yes");setRecoveryRejected(true);}setError((failure instanceof Error?failure.message:String(failure))+"；请查询原发布状态。");}}
    finally{if(current===epoch.current)setBusy(false);}
  }
  function finish(){
    if(status?.state!=="COMPLETED"&&status?.state!=="CANCELED"&&!(status?.state==="NOT_FOUND"&&publishRejected))return;
    sessionStorage.removeItem(key+"request");sessionStorage.removeItem(key+"candidate");sessionStorage.removeItem(key+"recovery");
    sessionStorage.removeItem(key+"publish-rejected");sessionStorage.removeItem(key+"recovery-rejected");
    setOriginal("");setOriginalCandidate("");setRecoveryPending("");setPublishRejected(false);setRecoveryRejected(false);setStatus(null);setConfirmed(false);setNote("");
  }
  function clearRejectedRecovery(){
    if(status?.state!=="PREPARED"||!recoveryRejected)return;
    sessionStorage.removeItem(key+"recovery");sessionStorage.removeItem(key+"recovery-rejected");setRecoveryPending("");setRecoveryRejected(false);
  }
  return <div aria-label="候选发布">
    <h3>发布候选</h3>
    {!original&&<><p>来源摘要：{detail?.base_method.content_sha256??"尚未读取"}</p><p>草稿版本：{detail?.draft_version??"尚未读取"}</p><p>本人授权编号：{decision?.authorization_id??"尚未取得"}</p>
      <label className="boss-label">变更说明<textarea value={note} maxLength={360} onChange={event=>setNote(event.target.value)}/></label>
      <label><input type="checkbox" checked={confirmed} onChange={event=>setConfirmed(event.target.checked)}/>已核查候选、来源、校验结果和本人决定</label>
      <p>发布使用维护详情中的候选、版本与本人决定；版本、授权和工具条件由服务端重新核查。</p>
      {!ready&&<p>发布条件尚未满足，请重新读取维护详情并核查校验、来源与本人决定。</p>}
      <button className="boss-btn" type="button" disabled={busy||!confirmed||!ready||!note.trim()} onClick={()=>void publish()}>发布已核查候选</button></>}
    {original&&<><p>候选编号：{originalCandidate}</p><p>原发布编号：{original}</p><button className="boss-btn" type="button" disabled={busy} onClick={()=>void readStatus()}>查询原发布状态</button></>}
    {status&&<div role="status"><p>原发布状态：{status.state}</p>{status.state==="NOT_FOUND"&&<><p>当前未发现记录，请保留原编号并继续核查。</p>{publishRejected&&<button className="boss-btn" type="button" onClick={finish}>结束已拒绝的请求</button>}</>}
      {status.state==="PREPARED"&&<><p>方法启用尚待处理。继续时会重新检查本人授权；取消时恢复原方法。</p>
        {recoveryPending?<><p>原恢复操作编号：{recoveryPending}。请继续查询原发布状态。</p>{recoveryRejected&&<button className="boss-btn" type="button" onClick={clearRejectedRecovery}>结束已拒绝的恢复请求</button>}</>:<div className="boss-actions"><button className="boss-btn" type="button" disabled={busy} onClick={()=>void recover("recover")}>继续原启用</button><button className="boss-btn" type="button" disabled={busy} onClick={()=>void recover("cancel")}>取消原启用</button></div>}</>}
      {(status.state==="COMPLETED"||status.state==="CANCELED")&&<button className="boss-btn" type="button" disabled={busy} onClick={finish}>完成状态核查</button>}</div>}
    {error&&<p role="alert">{error}</p>}
  </div>;
}
