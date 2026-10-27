import {Keyboard,ShieldCheck} from "lucide-react";
import {V7Panel,V7Fact,V7Steps} from "./BossV7UI";

export function BossVoicePaused({onNavigate}:{onNavigate:(id:string)=>void}){
  const phases=[{title:"等待许可",description:"系统许可与本次同意"},{title:"录音中",description:"显示时长及停止操作"},{title:"上传中",description:"可取消尚未完成的上传"},{title:"转写中",description:"显示实际服务返回"},{title:"文本核查",description:"本人核对人名、金额、时间和动作"},{title:"提交成功",description:"确认文本进入聊天交办"},{title:"失败 / 已取消",description:"保留已有结果并提供文字入口"}];
  return <><div className="boss-status boss-status-warn" role="status"><ShieldCheck size={19}/><span>语音服务当前暂停，可以继续使用文字交办。</span></div><div className="boss-columns"><div className="boss-column">
    <V7Panel title="语音状态"><p>语音暂停期间不申请麦克风许可，不接受音频上传，也不调用转写服务。</p><V7Fact label="暂停范围">录音、上传、转写与语音提交</V7Fact><V7Fact label="当前可用方式">文字交办</V7Fact><V7Fact label="设备许可">本页面不请求任何设备权限</V7Fact></V7Panel>
    <details className="boss-panel"><summary>恢复后的录音与转写说明</summary><p>恢复后需要先取得系统麦克风许可和本人本次同意，再显示录音时长、停止、上传、转写原文与校对版本。确认文本只进入文字交办流程，不会自动创建或发送任务。</p><p>原始音频的保留期限和删除规则需要在恢复前单独确定。</p></details>
  </div><aside className="boss-column"><V7Panel title="提交与业务动作"><V7Fact label="文本提交状态">未确认</V7Fact><V7Fact label="业务动作状态">尚未发起</V7Fact><V7Fact label="实际服务用量">未知</V7Fact><V7Fact label="录音与转写费用">未知</V7Fact><p>确认后的文本进入聊天交办，发信与业务写入继续核查本人授权。</p></V7Panel><V7Panel title="失败与继续"><p>语音暂停期间可以通过文字完整描述当前事项。</p><button className="boss-btn boss-btn-primary" onClick={()=>onNavigate("N02")}><Keyboard size={17}/>使用文字交办</button><button className="boss-btn" onClick={()=>onNavigate("F26")}>查看设备权限状态</button></V7Panel></aside></div>
    <div className="boss-v7-addendum"><V7Panel title="语音交办完整状态流程"><p className="boss-helper">以下为恢复后的完整流程，当前全部处于等待状态，不会执行。</p><V7Steps steps={phases.map(phase=>({...phase,state:"waiting" as const}))}/></V7Panel><V7Panel title="录音、转写与业务动作边界"><div className="boss-v7-table"><table><thead><tr><th>当前阶段</th><th>取消范围</th><th>失败继续入口</th><th>结果保存</th></tr></thead><tbody>{[["录音","停止本次采集","使用文字","未产生确认文本"],["上传","停止未完成的上传","重新选择获准音频","不创建交办"],["转写","按实际服务状态取消","使用文字","保留原始资料"],["文本核查","不提交未确认文本","继续编辑","只提交确认版本"]].map(row=><tr key={row[0]}>{row.map(value=><td key={value}>{value}</td>)}</tr>)}</tbody></table></div></V7Panel></div>
  </>;
}
