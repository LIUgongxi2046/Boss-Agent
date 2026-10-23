import {useEffect, useState} from "react";
import {useClient} from "@/providers/ClientProvider";
import {BossSupplyQualityPanel, type SupplyQualityEditor, type SupplyQualityProjection, type SupplyQualityReceipt} from "./BossSupplyQualityPanel";

type Props={interfaceId:"SI09"|"SI10";onOpenSource:(sourceId:string)=>void;onOpenTask:(taskId:string)=>void;
  editor:SupplyQualityEditor;onEditorChange:(changes:Partial<SupplyQualityEditor>)=>void};

export function BossSupplyQualityView({interfaceId,onOpenSource,onOpenTask,editor,onEditorChange}:Props){
  const {client,getToken,token}=useClient();
  const [data,setData]=useState<SupplyQualityProjection|null>(null);
  const [loading,setLoading]=useState(false);
  const [error,setError]=useState("");
  const [revision,setRevision]=useState(0);
  const reload=()=>setRevision(current=>current+1);
  useEffect(()=>{
    const abort=new AbortController();
    const token=getToken();
    setData(null);setError("");
    if(!token){setError("当前身份令牌失效，请重新登录。");return;}
    setLoading(true);
    void fetch("/api/boss/ui/supply-quality?interface_id="+interfaceId,{headers:{Authorization:"Bearer "+token},cache:"no-store",signal:abort.signal}).then(async response=>{
      if(!response.ok)throw new Error("业务资料读取失败（HTTP "+response.status+"）");
      const result=await response.json() as SupplyQualityProjection;
      if(result.interface_id!==interfaceId||result.source_type!=="SIMULATED"||result.external_service_invoked!==false||result.purchase_executed!==false||result.quality_release_executed!==false)throw new Error("业务资料范围与当前页面不符。");
      return result;
    }).then(result=>{if(abort.signal.aborted)return;setData(result);setLoading(false);},(error:unknown)=>{
      if(abort.signal.aborted)return;setError(error instanceof Error?error.message:String(error));setLoading(false);
    });
    return ()=>abort.abort();
  },[interfaceId,getToken,revision,client,token]);
  async function command(action:string,payload:Record<string,unknown>){
    if(!client)throw new Error("当前认证通道尚未连接。");
    return client.requestMutation<unknown>(action,payload);
  }
  async function receipt(action:string,key:string){
    const token=getToken();
    if(!token)throw new Error("当前身份令牌失效，请重新登录。");
    const parameters=new URLSearchParams({action,client_request_id:key});
    const response=await fetch("/api/boss/ui/supply-quality-receipt?"+parameters.toString(),{headers:{Authorization:"Bearer "+token},cache:"no-store"});
    if(!response.ok)throw new Error("原请求回执读取失败（HTTP "+response.status+"）");
    return response.json() as Promise<SupplyQualityReceipt>;
  }
  return <BossSupplyQualityPanel key={interfaceId} data={data} loading={loading} error={error} onReload={reload} onOpenSource={onOpenSource} onOpenTask={onOpenTask} onCommand={command} onReceipt={receipt} editor={editor} onEditorChange={onEditorChange}/>;
}
