import {ArrowLeft,LockKeyhole,ScrollText} from "lucide-react";
import {V7Fact,V7Panel} from "./BossV7UI";

type Props={role:"BOSS"|"MAINTAINER";onNavigate:(page:string)=>void};

export function BossRestrictedView({role,onNavigate}:Props){
  return <section className="boss-panel boss-access-restricted" aria-labelledby="boss-access-title">
    <span className="boss-access-icon"><LockKeyhole size={30} aria-hidden="true"/></span>
    <h2 id="boss-access-title">无法访问此内容</h2>
    <p>当前身份没有该对象的读取或操作权限。</p>
    <span className="boss-tag">当前身份：{role==="MAINTAINER"?"技术维护":"本人"}</span>
    <p className="boss-helper">受限对象的标题、正文、附件、录音及派生摘要均不可见。访问记录只显示当前身份获准查询的内容。</p>
    <div className="boss-actions">
      <button type="button" className="boss-btn boss-btn-primary" onClick={()=>onNavigate(role==="MAINTAINER"?"A01":"F01")}><ArrowLeft size={16}/>返回获准页面</button>
      <button type="button" className="boss-btn" onClick={()=>onNavigate(role==="MAINTAINER"?"A14":"N11")}><ScrollText size={16}/>查询访问记录</button>
    </div>
  </section>;
}

export function BossUnsavedWorkspace({role,onNavigate}:Props){
  return <div className="boss-unsaved-columns">
    <div className="boss-column">
      <V7Panel title="未保存的编辑内容" description="编辑页面离开前会显示当前对象、版本及未保存范围。">
        <V7Fact label="当前对象">当前入口没有正在编辑的对象</V7Fact>
        <V7Fact label="本次编辑范围">请进入相应编辑页面查看</V7Fact>
        <V7Fact label="当前版本">按原对象读取</V7Fact>
        <p className="boss-helper">继续编辑会保留表单内容；保存草稿成功后才会离开。放弃本次编辑需要明确选择，已经保存的记录继续保留。</p>
        <div className="boss-actions">{role==="BOSS"?<><button type="button" className="boss-btn boss-btn-primary" onClick={()=>onNavigate("F05")}>打开会议纪要</button><button type="button" className="boss-btn" onClick={()=>onNavigate("F08")}>打开消息草稿</button></>:<button type="button" className="boss-btn boss-btn-primary" onClick={()=>onNavigate("A08")}>打开维护配置</button>}</div>
      </V7Panel>
      <V7Panel title="完整退出的独立影响">
        <V7Fact label="本地调度">完整退出后停止</V7Fact><V7Fact label="录音采集">完整退出后停止；当前语音服务暂停</V7Fact><V7Fact label="未执行步骤">完整退出后停止</V7Fact><V7Fact label="已保存记录">继续保留</V7Fact><V7Fact label="未知结果">重新认证后按原请求查询</V7Fact>
        <div className="boss-actions"><button type="button" className="boss-btn" onClick={()=>onNavigate(role==="BOSS"?"F26":"F32")}>查看应用退出与运行状态</button></div>
      </V7Panel>
    </div>
    <aside className="boss-column"><V7Panel title="编辑保护"><V7Fact label="当前处理结果">尚未选择</V7Fact><p className="boss-helper">保存草稿不会发送消息、批准申请或创建交办。保存失败与结果未知时保留原表单，取消离开后恢复原编辑位置。</p></V7Panel></aside>
  </div>;
}
