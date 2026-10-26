import {useEffect,useRef,useState} from "react";
import * as Dialog from "@radix-ui/react-dialog";
import {V7Empty,V7Fact,V7Panel,V7ReadState} from "./BossV7UI";
import {useTechnicalWorkspace} from "./useTechnicalWorkspace";

type Host={platform:string;architecture:string;versions:Record<string,string>;service_pid:number;service_startup_ms:number;microphone:string;notifications_supported:boolean;auto_start:boolean|null;auto_update:boolean;background_mode:string};
type Bridge={invoke:(request:{action:"status"})=>Promise<Host>};
type Projection={projection:"local-system";private_body_available_here:false;namespace:string;application_version:string;upstream_version:string;source_commit:string;read_at:string;
  service:{state:string;started_at:string|null;scheduler_state:string;scheduler_owner:string;active_runs:number};
  desktop:{background_mode:string;auto_start:boolean|null;auto_update:boolean|null;recording_state:string};
  recovery:{name:string;state:string;checked_at:string|null;details:string}[];
  instructions:{id:string;title:string;body:string;command:string|null;state:string}[];
  installations:{id:string;version:string;platform:string;state:string;checked_at:string}[];
  backups:{id:string;created_at:string;namespace:string;state:string;digest:string}[];
  contributions:{component:string;version:string;source:string;extension:string}[]};
export type {Projection as LocalSystemProjection};

export function MaintainerLocalSystem({onNavigate}:{onNavigate:(page:string)=>void}){
  const api=useTechnicalWorkspace<Projection>("local-system");
  const [host,setHost]=useState<Host|null>(null);
  const [hostError,setHostError]=useState("");
  const [hostLoading,setHostLoading]=useState(false),[hostReadAt,setHostReadAt]=useState("");
  const hostSequence=useRef(0);
  const [visibility,setVisibility]=useState(document.visibilityState);
  const [instruction,setInstruction]=useState("");
  const [records,setRecords]=useState<"installations"|"backups"|null>(null);
  const bridge=(window as Window&{bossDesktop?:Bridge}).bossDesktop;
  function readHost(){if(!bridge)return;const sequence=++hostSequence.current;setHostLoading(true);setHost(null);setHostError("");setHostReadAt("");void bridge.invoke({action:"status"}).then(value=>{if(sequence!==hostSequence.current)return;setHost(value);setHostReadAt(new Date().toISOString());setHostLoading(false);},error=>{if(sequence!==hostSequence.current)return;setHostError(error.message);setHostLoading(false);});}
  useEffect(()=>{readHost();return()=>{hostSequence.current++;};},[bridge]);
  useEffect(()=>{const update=()=>setVisibility(document.visibilityState);document.addEventListener("visibilitychange",update);return()=>document.removeEventListener("visibilitychange",update);},[]);
  const selected=api.data?.instructions.find(row=>row.id===instruction);
  return <div className="boss-local-workspace"><V7ReadState loading={api.loading||hostLoading} error={api.error||hostError} onReload={()=>{api.reload();readHost();}}/>
    <div className="boss-columns"><div className="boss-column">
      <V7Panel title="本地环境与版本"><div className="boss-form-grid"><label>目标 OS / 架构<input readOnly value={host?host.platform+" / "+host.architecture:bridge?"尚未读取":"当前为浏览器入口"}/></label><label>应用版本<input readOnly value={api.data?.application_version??"尚未读取"}/></label><label>上游组件版本<input readOnly value={api.data?.upstream_version??"尚未读取"}/></label><label>实际检查时间<input readOnly value={api.data?.read_at??"尚未读取"}/></label></div><V7Fact label="服务状态">{api.data?.service.state??"尚未读取"}</V7Fact><V7Fact label="服务进程">{host?.service_pid??"桌面宿主未提供"}</V7Fact><V7Fact label="宿主检查时间">{hostReadAt||"尚未读取"}</V7Fact><div className="boss-actions"><button className="boss-btn" disabled={api.loading||hostLoading} onClick={()=>{api.reload();readHost();}}>查询当前状态</button></div></V7Panel>
      <V7Panel title="窗口、后台与调度"><div className="boss-form-grid"><label>前台窗口状态<input readOnly value={visibility==="visible"?"当前窗口可见":"当前窗口不可见"}/></label><label>后台运行状态<input readOnly value={host?.background_mode??api.data?.desktop.background_mode??"尚未读取"}/></label><label>自启动<input readOnly value={host?.auto_start===true?"已启用":host?.auto_start===false?"未启用":"宿主尚未提供"}/></label><label>自动更新<input readOnly value={host?.auto_update===true?"已启用":host?.auto_update===false?"未启用":"宿主尚未提供"}/></label></div><V7Fact label="当前录音状态">{api.data?.desktop.recording_state??"尚未读取"}</V7Fact><V7Fact label="调度进程">{api.data?.service.scheduler_owner??"尚未读取"}</V7Fact><V7Fact label="调度状态">{api.data?.service.scheduler_state??"尚未读取"}</V7Fact><V7Fact label="在途运行">{api.data?.service.active_runs??"尚未读取"}</V7Fact><div className="boss-actions">{api.data?.instructions.filter(row=>["quit","restart"].includes(row.id)).map(row=><button key={row.id} className="boss-btn" onClick={()=>setInstruction(row.id)}>{row.id==="quit"?"完整退出影响":"重新启动说明"}</button>)}</div></V7Panel>
      <V7Panel title="恢复核查">{api.data?.recovery.length?api.data.recovery.map(row=><article key={row.name} className="boss-workspace-item"><strong>{row.name} · {row.state}</strong><p>{row.details}</p><small>{row.checked_at??"尚未检查"}</small></article>):<V7Empty title="尚无恢复核查记录"/>}<div className="boss-actions"><button className="boss-btn" onClick={()=>onNavigate("A15")}>查询执行结果</button><button className="boss-btn" onClick={()=>onNavigate("A13")}>重读计划版本</button></div></V7Panel>
    </div><aside className="boss-column">
      <V7Panel title="安装与数据备份"><article className="boss-workspace-item"><strong>安装与启动</strong><p>按当前实例的正式入口启动，查看对应版本及设备检查记录。</p></article><article className="boss-workspace-item"><strong>完整退出</strong><p>{api.data?.instructions.find(row=>row.id==="quit")?.body??"尚未读取当前退出说明"}</p></article><article className="boss-workspace-item"><strong>备份与恢复</strong><p>按执行空间、保存时间与校验摘要核查实际记录。</p></article><div className="boss-actions"><button className="boss-btn" aria-pressed={records==="installations"} onClick={()=>setRecords("installations")}>查看安装记录</button><button className="boss-btn" aria-pressed={records==="backups"} onClick={()=>setRecords("backups")}>查看备份记录</button></div>{records==="installations"&&(api.data?.installations.length?api.data.installations.map(row=><article className="boss-workspace-item" key={row.id}><strong>{row.version} · {row.platform}</strong><p>{row.state}</p><small>{row.checked_at}</small></article>):<V7Empty title="尚无安装检查记录"/>)}{records==="backups"&&(api.data?.backups.length?api.data.backups.map(row=><article className="boss-workspace-item" key={row.id}><strong>{row.id}</strong><p>{row.namespace} · {row.state}</p><small>{row.created_at}</small><details><summary>校验摘要</summary><code>{row.digest}</code></details></article>):<V7Empty title="尚无备份记录"/>)}</V7Panel>
    </aside></div>
    <details className="boss-panel"><summary>运行说明、复用来源与贡献</summary><div className="boss-actions">{api.data?.instructions.map(row=><button className="boss-btn" key={row.id} onClick={()=>setInstruction(row.id)}>{row.title}</button>)}</div>{api.data?.contributions.map(row=><article className="boss-workspace-item" key={row.component}><strong>{row.component} · {row.version}</strong><p>{row.source}</p><p>{row.extension}</p></article>)}<V7Fact label="源码版本">{api.data?.source_commit??"尚未读取"}</V7Fact></details>
    <Dialog.Root open={!!selected} onOpenChange={open=>{if(!open)setInstruction("");}}><Dialog.Portal><Dialog.Overlay className="boss-v7-dialog-overlay"/><Dialog.Content className="boss-v7-dialog"><Dialog.Title>{selected?.title??"运行说明"}</Dialog.Title><Dialog.Description>{selected?.body}</Dialog.Description>{selected?.command&&<pre className="boss-v7-code">{selected.command}</pre>}<p>当前验证状态：{selected?.state}</p><div className="boss-actions"><Dialog.Close asChild><button className="boss-btn">关闭说明</button></Dialog.Close></div></Dialog.Content></Dialog.Portal></Dialog.Root>
  </div>;
}
