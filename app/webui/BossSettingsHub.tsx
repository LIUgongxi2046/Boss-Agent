import {useEffect,useState, type ReactNode} from "react";
import {
  BellRing, CalendarDays, ChevronRight, ClipboardCheck,
  FolderLock, History, Loader2, LogOut, RefreshCw, ShieldCheck,
  Target, UserRound,
} from "lucide-react";
import { useClient } from "@/providers/ClientProvider";

type Snapshot={
  source_type:"SIMULATED";projection:string;
  active:{version:string;state:string;content:Record<string,unknown>}|null;
  active_is_effective:boolean;
};
type Props={onNavigate:(page:string)=>void;onLogout:()=>void};
function Tile({title,detail,status,onClick,icon}:{
  title:string;detail:string;status:string;onClick:()=>void;icon:ReactNode;
}){
  return <button type="button" className="boss-task-row"
    onClick={onClick}>
    <span style={{display:"flex",alignItems:"center",gap:12}}>
      {icon}<span style={{display:"grid",gap:4}}>
        <strong>{title}</strong><small>{detail}</small>
        <small>{status}</small>
      </span><ChevronRight size={17}/>
    </span>
  </button>;
}
export function BossSettingsHub({onNavigate,onLogout}:Props){
  const {getToken}=useClient();
  const [goals,setGoals]=useState<Snapshot|null>(null);
  const [notice,setNotice]=useState<Snapshot|null>(null);
  const [loading,setLoading]=useState(false);
  const [error,setError]=useState("");
  const [revision,setRevision]=useState(0);
  useEffect(()=>{
    const token=getToken();
    if(!token){setError("当前会话已失效");return;}
    const controller=new AbortController();
    setLoading(true);setError("");
    const headers={Authorization:"Bearer "+token};
    void Promise.all(["owner-goals","owner-notice"].map(async key=>{
      const response=await fetch("/api/boss/ui/workspace/"+key,{
        headers,cache:"no-store",signal:controller.signal,
      });
      if(!response.ok)throw new Error("设置读取失败 HTTP "+response.status);
      const row=await response.json() as Snapshot;
      if(row.source_type!=="SIMULATED"||row.projection!==key)
        throw new Error("本次读取的业务空间或页面类型不符合预期");
      return row;
    })).then(([a,b])=>{
      if(controller.signal.aborted)return;
      setGoals(a);setNotice(b);setLoading(false);
    }).catch(e=>{
      if(controller.signal.aborted)return;
      setError(e instanceof Error?e.message:String(e));setLoading(false);
    });
    return ()=>controller.abort();
  },[revision,getToken]);
  return <>
    <div className="boss-workspace-toolbar">
      <span className="boss-workspace-note">
        <span className="boss-tag boss-tag-amber">SIMULATED · BOSS_ONLY</span>
        F26 · 应用入口与本人设置
      </span>
      <button className="boss-btn" type="button" disabled={loading}
        onClick={()=>setRevision(v=>v+1)}>
        {loading?<Loader2 size={15} className="boss-spin"/>:
          <RefreshCw size={15}/>} 核对最新有效配置
      </button>
    </div>
    {error&&<div className="boss-status boss-status-error" role="alert">{error}</div>}
    <div className="boss-columns">
      <div className="boss-column">
        <section className="boss-panel">
          <div className="boss-panel-head"><h2>本人目标、通知和记忆</h2>
            <small>Desktop v6 · 一位老板的独立设置入口</small></div>
          <Tile title="本人目标与关注要求" detail="目标、阅读偏好、适用范围和后续采纳"
            status={goals?.active_is_effective?
              "有效版本 v"+goals.active?.version:"目前没有有效的本人确认配置"}
            icon={<Target size={19}/>} onClick={()=>onNavigate("N07")}/>
          <Tile title="通知要求与可见范围" detail="免打扰、通知限制、个人内容分享边界"
            status={notice?.active_is_effective?
              "有效版本 v"+notice.active?.version:"本人通知偏好尚未正式确认"}
            icon={<BellRing size={19}/>} onClick={()=>onNavigate("N08")}/>
          <Tile title="个人长期记忆" detail="由本人确认或删除、停止后续任务采用"
            status="独立管理，不能由技术维护代改"
            icon={<History size={19}/>} onClick={()=>onNavigate("F13")}/>
          <Tile title="本人计划" detail="晨间安排、事项复查及技术计划的执行引用"
            status="计划配置和运行结果分别核对"
            icon={<CalendarDays size={19}/>} onClick={()=>onNavigate("N09")}/>
        </section>
        <section className="boss-panel">
          <div className="boss-panel-head"><h2>权限和隐私</h2>
            <small>每个操作都按独立对象和当前版本校验</small></div>
          <Tile title="本人授权记录" detail="确认动作、授权有效期及撤销边界"
            status="只查看当前获准业务范围"
            icon={<ShieldCheck size={19}/>} onClick={()=>onNavigate("N10")}/>
          <Tile title="私人安排" detail="私人正文本人可见；分享仅有 busy 信息"
            status="分享和撤销需要逐对象单独授权"
            icon={<FolderLock size={19}/>} onClick={()=>onNavigate("F12")}/>
          <Tile title="历史决定" detail="原始操作审计及当前有效事项"
            status="历史版本保持只读"
            icon={<ClipboardCheck size={19}/>} onClick={()=>onNavigate("N11")}/>
        </section>
      </div>
      <div className="boss-column">
        <section className="boss-panel">
          <div className="boss-panel-head"><h2>本人账户与工作区</h2>
            <small>与技术维护身份隔离</small></div>
          <div className="boss-kv"><span>当前角色</span><strong>BOSS · 唯一本人</strong></div>
          <div className="boss-kv"><span>目标状态</span>
            <strong>{goals?.active_is_effective?"本人已确认":"未确认新目标"}</strong></div>
          <div className="boss-kv"><span>通知要求</span>
            <strong>{notice?.active_is_effective?"本人已确认":"尚未确认"}</strong></div>
          <div className="boss-kv"><span>技术后台</span>
            <strong>单独的 MAINTAINER 角色</strong></div>
          <p className="boss-helper">本页面仅提供本人当前设置和对应入口。
            保存草稿不等于启用，模型运行时读取上下文也不证明模型已经正确遵循。
            技术维护无权读取或修改私人正文。</p>
          <div className="boss-actions">
            <button className="boss-btn boss-btn-primary" type="button"
              onClick={()=>onNavigate("F01")}>
              <UserRound size={16}/> 返回今日工作
            </button>
            <button className="boss-btn" type="button" onClick={onLogout}>
              <LogOut size={15}/> 退出当前会话
            </button>
          </div>
        </section>
      </div>
    </div>
  </>;
}
