import {useEffect,useRef,useState} from "react";
import {SkillCandidatePublication} from "./SkillCandidatePublication";

type Role="BOSS"|"MAINTAINER";
type Preview={candidate_id:string;sop_id:string;content:string;content_sha256:string;base_content:string;
  base_method:{content_sha256:string;version:string};validation_status:string;
  decision_receipts:{client_request_id:string;candidate_id:string;decision:string;authorization_id:string}[]};
type Validation={candidate_id:string;content_sha256:string;validation_status:string;errors:unknown[];missing_tools:string[]};
type Candidate={candidate_id:string;sop_id:string;content_sha256:string;state:string;validation_status:string};
export type CandidateDetail=Candidate&{base_method:{content_sha256:string;version:string};current_active_sha256:string;draft_version:string;
  errors:unknown[];missing_tools:string[];tool_config_sha256:string|null;decisions:{authorization_id:string;decision:string;expired:boolean;revoked:boolean;content_sha256:string;base_sha256:string;tool_config_sha256:string|null;valid_until:string}[]};

export function SkillCandidateReview({role,getToken,identityKey}:{role:Role;getToken:()=>string|null;identityKey:string}){
  const [candidate,setCandidate]=useState("");
  const [digest,setDigest]=useState("");
  const [preview,setPreview]=useState<Preview|null>(null);
  const [validation,setValidation]=useState<Validation|null>(null);
  const [items,setItems]=useState<Candidate[]|null>(null);
  const [next,setNext]=useState<string|null>(null);
  const [detail,setDetail]=useState<CandidateDetail|null>(null);
  const [busy,setBusy]=useState(false);
  const [error,setError]=useState("");
  const [notice,setNotice]=useState("");
  const [pending,setPending]=useState<string|null>(null);
  const epoch=useRef(0);
  useEffect(()=>{epoch.current++;setCandidate(role==="BOSS"?sessionStorage.getItem("boss-skill-decision-candidate")??"":"");setDigest("");setPreview(null);setValidation(null);setItems(null);setNext(null);setDetail(null);setPending(role==="BOSS"?sessionStorage.getItem("boss-skill-decision-pending"):null);setError("");setNotice("");setBusy(false);return()=>{epoch.current++;};},[identityKey,role]);

  async function request(path:string,body?:object){
    const token=getToken();
    if(!token)throw new Error("当前身份已经失效，请重新认证");
    const response=await fetch(path,{method:body?"POST":"GET",headers:{Authorization:"Bearer "+token,...(body?{"Content-Type":"application/json"}:{})},
      body:body?JSON.stringify(body):undefined,credentials:"same-origin",cache:"no-store",redirect:"error"});
    if(!response.ok){
      const detail=await response.text();
      throw new Error("请求失败（HTTP "+response.status+"）"+(detail?"："+detail:"")+(response.status===401||response.status===403?"；请核查当前身份":response.status===409?"；请重新读取当前版本":""));
    }
    return await response.json() as unknown;
  }
  function path(id:string){return "/api/v2/skill-candidates/"+encodeURIComponent(id);}
  async function list(after=""){
    if(busy||pending)return;const current=epoch.current;setBusy(true);setError("");
    try{
      const value=await request("/api/v2/skill-candidates"+(after?"?"+new URLSearchParams({after}):"")) as {items:Candidate[];next_after:string|null};
      if(current!==epoch.current)return;
      if(!Array.isArray(value.items)||value.items.some(item=>typeof item.candidate_id!=="string"||typeof item.sop_id!=="string"||!/^[0-9a-f]{64}$/.test(item.content_sha256)||typeof item.state!=="string"||typeof item.validation_status!=="string")||value.next_after!==null&&typeof value.next_after!=="string")throw new Error("候选目录结果不完整");
      setItems(previous=>after?[...(previous??[]),...value.items]:value.items);setNext(value.next_after);
    }catch(failure){if(current===epoch.current)setItems(null);if(current===epoch.current)setError(failure instanceof Error?failure.message:String(failure));}
    finally{if(current===epoch.current)setBusy(false);}
  }
  async function selectCandidate(id:string){
    if(busy||pending)return;const current=epoch.current;setCandidate(id);setDigest("");setDetail(null);setPreview(null);setValidation(null);setError("");setNotice("");
    if(role!=="MAINTAINER")return;
    setBusy(true);
    try{
      const value=await request(path(id)+"/maintenance") as CandidateDetail;
      if(current!==epoch.current)return;
      if(value.candidate_id!==id||!/^[0-9a-f]{64}$/.test(value.content_sha256)||!value.base_method||!/^[0-9a-f]{64}$/.test(value.base_method.content_sha256)||!/^[0-9a-f]{64}$/.test(value.current_active_sha256)||!/^[0-9]+$/.test(value.draft_version)||!Array.isArray(value.decisions)||value.decisions.some(item=>!item||typeof item.authorization_id!=="string"||!item.authorization_id||!['APPROVE','REJECT'].includes(item.decision)||typeof item.expired!=="boolean"||typeof item.revoked!=="boolean"||typeof item.valid_until!=="string"||typeof item.content_sha256!=="string"||typeof item.base_sha256!=="string")||!Array.isArray(value.errors)||!Array.isArray(value.missing_tools))throw new Error("维护详情结果不完整");
      setDetail(value);setDigest(value.content_sha256);
    }catch(failure){if(current===epoch.current)setError(failure instanceof Error?failure.message:String(failure));}
    finally{if(current===epoch.current)setBusy(false);}
  }
  async function read(){
    const id=candidate.trim();if(!id||busy||pending)return;
    const current=epoch.current;setBusy(true);setPreview(null);setValidation(null);setError("");setNotice("");
    try{
      const value=await request(path(id)) as Preview;
      if(current!==epoch.current)return;
      if(value.candidate_id!==id||typeof value.content!=="string"||typeof value.base_content!=="string"||typeof value.sop_id!=="string"||!/^[0-9a-f]{64}$/.test(value.content_sha256)||!value.base_method||!/^[0-9a-f]{64}$/.test(value.base_method.content_sha256))throw new Error("候选读取结果不完整");
      setPreview(value);
    }catch(failure){if(current===epoch.current)setError(failure instanceof Error?failure.message:String(failure));}
    finally{if(current===epoch.current)setBusy(false);}
  }
  async function validate(){
    const id=candidate.trim(),sha=digest.trim();if(!id||!/^[0-9a-f]{64}$/.test(sha)||busy||pending)return;
    const current=epoch.current;setBusy(true);setValidation(null);setDetail(null);setError("");setNotice("");
    try{
      const value=await request(path(id)+"/validation",{expected_content_sha256:sha}) as Validation;
      if(current!==epoch.current)return;
      if(value.candidate_id!==id||value.content_sha256!==sha||typeof value.validation_status!=="string"||!Array.isArray(value.errors)||!Array.isArray(value.missing_tools))throw new Error("候选校验结果不完整");
      setValidation(value);
    }catch(failure){if(current===epoch.current)setError(failure instanceof Error?failure.message:String(failure));}
    finally{if(current===epoch.current)setBusy(false);}
  }
  async function decide(decision:"APPROVE"|"REJECT"){
    if(!preview||busy||pending)return;
    if(!getToken()){setError("当前身份已经失效，请重新认证");return;}
    const current=epoch.current,id=preview.candidate_id,requestId="skill-decision-"+crypto.randomUUID();
    sessionStorage.setItem("boss-skill-decision-pending",requestId);
    sessionStorage.setItem("boss-skill-decision-candidate",id);
    setBusy(true);setPending(requestId);setError("");setNotice("");
    try{
      const value=await request(path(id)+"/decision",{client_request_id:requestId,expected_content_sha256:preview.content_sha256,
        expected_base_sha256:preview.base_method.content_sha256,decision}) as {candidate_id?:string;decision?:string;authorization_id?:string};
      if(current!==epoch.current)return;
      if(value.candidate_id!==id||value.decision!==decision||typeof value.authorization_id!=="string"||!value.authorization_id)throw new Error("本人决定回执不完整");
      sessionStorage.removeItem("boss-skill-decision-pending");sessionStorage.removeItem("boss-skill-decision-candidate");setPending(null);setNotice("本人决定已经记录："+(decision==="APPROVE"?"批准":"拒绝")+"。授权编号："+value.authorization_id);setPreview(null);
    }catch(failure){if(current===epoch.current)setError((failure instanceof Error?failure.message:String(failure))+"。请保留原操作编号并核查原决定结果。");}
    finally{if(current===epoch.current)setBusy(false);}
  }
  async function reconcileDecision(){
    if(!pending||!candidate||busy)return;
    const current=epoch.current;setBusy(true);setError("");setNotice("");
    try{
      const value=await request(path(candidate)+"/decisions/"+encodeURIComponent(pending)) as {candidate_id:string;client_request_id:string;state:string;result:{candidate_id:string;decision:string;authorization_id:string}|null};
      if(current!==epoch.current)return;
      if(value.candidate_id!==candidate||value.client_request_id!==pending||!['RECORDED','NOT_FOUND'].includes(value.state))throw new Error("原决定回执读取结果不完整");
      if(value.state==="NOT_FOUND"){setError("当前未发现原决定回执，请保留操作编号并再次核查。");return;}
      const receipt=value.result;if(!receipt)throw new Error("原决定回执缺少");
      if(receipt.candidate_id!==candidate||!['APPROVE','REJECT'].includes(receipt.decision)||typeof receipt.authorization_id!=="string"||!receipt.authorization_id)throw new Error("原决定回执内容不一致");
      sessionStorage.removeItem("boss-skill-decision-pending");sessionStorage.removeItem("boss-skill-decision-candidate");setPending(null);setPreview(null);
      setNotice("已重读本人决定："+(receipt.decision==="APPROVE"?"批准":"拒绝")+"。授权编号："+receipt.authorization_id);
    }catch(failure){if(current===epoch.current)setError(failure instanceof Error?failure.message:String(failure));}
    finally{if(current===epoch.current)setBusy(false);}
  }
  return <section className="boss-panel" aria-label="方法候选">
    <div className="boss-panel-head"><h2>方法候选</h2></div>
    <div className="boss-actions"><button type="button" className="boss-btn" disabled={busy||!!pending} onClick={()=>void list()}>读取候选目录</button>{next&&<button type="button" className="boss-btn" disabled={busy||!!pending} onClick={()=>void list(next)}>读取更多候选</button>}</div>
    {items&&<>{items.length?<ul>{items.map(item=><li key={item.candidate_id}><button type="button" className="boss-btn" disabled={busy||!!pending} onClick={()=>void selectCandidate(item.candidate_id)}>{item.sop_id} · {item.candidate_id} · {item.state} · {item.validation_status}</button></li>)}</ul>:<p>当前没有候选。</p>}</>}
    <p>当前候选：{candidate||"尚未选择"}</p>
    {role==="BOSS"?<div className="boss-actions"><button className="boss-btn" type="button" disabled={!candidate.trim()||busy||!!pending} onClick={()=>void read()}>查看候选及来源方法</button></div>:
      <><p>候选内容摘要：{digest||"尚未读取"}</p>{detail&&<div><p>来源方法：{detail.sop_id} · v{detail.base_method.version}</p><p>来源摘要：{detail.base_method.content_sha256}</p><p>当前方法摘要：{detail.current_active_sha256}</p><p>当前草稿版本：{detail.draft_version}</p><p>静态校验：{detail.validation_status}</p><p>本人决定：{detail.decisions[0]?detail.decisions[0].decision+" · 有效期至 "+detail.decisions[0].valid_until+(detail.decisions[0].expired?" · 已过期":"")+(detail.decisions[0].revoked?" · 已撤销":""):"尚未取得"}</p></div>}
      <div className="boss-actions"><button className="boss-btn" type="button" disabled={!candidate.trim()||!/^[0-9a-f]{64}$/.test(digest.trim())||busy||!!pending} onClick={()=>void validate()}>校验候选</button></div>
      {candidate&&<button type="button" className="boss-btn" disabled={busy} onClick={()=>void selectCandidate(candidate)}>重新读取维护详情</button>}
      <SkillCandidatePublication detail={detail} getToken={getToken} identityKey={identityKey}/></>}
    {busy&&<p role="status">正在处理请求。</p>}{error&&<p role="alert">{error}</p>}{notice&&<p role="status">{notice}</p>}
    {pending&&<div role="status"><p>原决定编号：{pending}。结果尚未确认，请重读原决定。</p><button type="button" className="boss-btn" disabled={busy} onClick={()=>void reconcileDecision()}>查询原决定</button></div>}
    {validation&&<div><p>校验状态：{validation.validation_status}</p><p>缺少工具：{validation.missing_tools.join("、")||"没有"}</p>{validation.errors.length>0&&<pre>{JSON.stringify(validation.errors,null,2)}</pre>}<p>静态校验不代表实际任务已经采用。</p></div>}
    {preview&&<article><p>方法：{preview.sop_id} · 当前版本 {preview.base_method.version}</p><p>候选摘要：{preview.content_sha256}</p><p>来源摘要：{preview.base_method.content_sha256}</p><p>校验状态：{preview.validation_status}</p>
      <h3>当前方法</h3><pre style={{whiteSpace:"pre-wrap",overflowWrap:"anywhere"}}>{preview.base_content}</pre><h3>候选内容</h3><pre style={{whiteSpace:"pre-wrap",overflowWrap:"anywhere"}}>{preview.content}</pre>
      <div className="boss-actions"><button className="boss-btn" type="button" disabled={busy||!!pending||preview.validation_status!=="VALIDATED_STATIC_ONLY"} onClick={()=>void decide("APPROVE")}>批准此候选</button><button className="boss-btn" type="button" disabled={busy||!!pending||preview.validation_status!=="VALIDATED_STATIC_ONLY"} onClick={()=>void decide("REJECT")}>拒绝此候选</button></div>
      <p>决定仅对应当前显示的候选和来源摘要；授权有效期限由服务端核查。</p></article>}
  </section>;
}
