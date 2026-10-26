import {useEffect,useRef,useState} from "react";
import * as Dialog from "@radix-ui/react-dialog";
import {useClient} from "@/providers/ClientProvider";
import {useTransaction} from "./BossAssignmentFlow";
import {V7Empty,V7Fact,V7Panel,V7ReadState} from "./BossV7UI";
import {BossNotificationPermissions} from "./BossDesktopNotifications";

type GoalSettings={goals:string[];topics:string[];reading_requirement:string;scope:"OWNER_WORKSPACE"|"DAILY_BRIEF"|"MEETING_PREP";valid_until:string|null;source:string};
type NoticeSettings={timezone:string;quiet_start:number;quiet_end:number;notifications_enabled:boolean;important_during_quiet:boolean;reading_format:"ACTIONS_FIRST"|"SUMMARY"|"DETAIL";visibility:"BOSS_ONLY";calendar_share_limit:"BUSY_ONLY";valid_until:string|null;source:string};
type RecordState={id:string;version:string;state:string;content:GoalSettings|NoticeSettings;content_sha256:string;confirmed_at?:string;saved_at?:string};
type Projection={source_type:"SIMULATED";projection:"owner-goals"|"owner-notice";draft:RecordState|null;active:RecordState|null;active_is_effective:boolean;
  runtime_context_observation?:{active_version?:string;context_load_count:number;last_loaded_at?:string;observation:string;actual_model_compliance_verified:boolean};
  technical_rules?:{version?:string;timezone?:string;quiet_start?:number;quiet_end?:number};technical_schedule?:{version?:string;enabled?:boolean;canceled?:boolean};
  history:{version:string;state:string;confirmed_at?:string}[]};
type Props={pageId:"N07"|"N08";onNavigate:(page:string)=>void;onDirtyChange:(dirty:boolean)=>void};
type Editor={goals:string;topics:string;reading:string;scope:GoalSettings["scope"]|"";until:string;timezone:string;quietStart:string;quietEnd:string;enabled:""|"true"|"false";important:""|"true"|"false";format:NoticeSettings["reading_format"]|""};
const EMPTY:Editor={goals:"",topics:"",reading:"",scope:"",until:"",timezone:"",quietStart:"",quietEnd:"",enabled:"",important:"",format:""};
const SCOPES={OWNER_WORKSPACE:"本人全部工作区",DAILY_BRIEF:"晨间简报",MEETING_PREP:"会议准备"};
const FORMATS={ACTIONS_FIRST:"待行动事项优先",SUMMARY:"简要汇总",DETAIL:"详细模式"};
function localTime(value:string|null){return value?new Intl.DateTimeFormat("sv-SE",{timeZone:"Asia/Shanghai",year:"numeric",month:"2-digit",day:"2-digit",hour:"2-digit",minute:"2-digit",hourCycle:"h23"}).format(new Date(value)).replace(" ","T"):"";}
function isGoals(value:GoalSettings|NoticeSettings):value is GoalSettings{return "goals" in value;}
function rows(value:string){return value.split("\n").map(row=>row.trim()).filter(Boolean);}

export function BossOwnerPreferences(props:Props){
  const {token}=useClient();
  const identity=useRef({token,sequence:0});
  if(identity.current.token!==token)identity.current={token,sequence:identity.current.sequence+1};
  return <OwnerPreferences key={props.pageId+identity.current.sequence} {...props}/>;
}

function OwnerPreferences({pageId,onNavigate,onDirtyChange}:Props){
  const {getToken}=useClient();
  const isGoal=pageId==="N07",route=isGoal?"owner-goals":"owner-notice";
  const [data,setData]=useState<Projection|null>(null),[revision,setRevision]=useState(0);
  const [loading,setLoading]=useState(true),[readError,setReadError]=useState(""),[formError,setFormError]=useState("");
  const [editor,setEditor]=useState<Editor>(EMPTY),[basis,setBasis]=useState({draft:"0",active:"0"});
  const [dirty,setDirty]=useState(false),dirtyRef=useRef(false);
  const [recordView,setRecordView]=useState<"history"|"usage"|null>(null);
  const reload=()=>setRevision(value=>value+1);
  const transaction=useTransaction(recorded=>{if(recorded){dirtyRef.current=false;setDirty(false);onDirtyChange(false);}reload();},undefined,undefined,isGoal?"ownerGoals":"ownerNotice");
  const stale=Boolean(data&&(basis.draft!==(data.draft?.version??"0")||basis.active!==(data.active?.version??"0")));
  const disabled=loading||transaction.busy||!data||Boolean(readError)||stale;
  const active=data?.active,selected=data?.draft??active;
  const usage=data?.runtime_context_observation;
  const actualUsage=usage&&usage.active_version===active?.version?usage:null;
  const effectiveState=data?data.active_is_effective?"已确认且在有效期内":"当前未生效":"尚未读取";
  useEffect(()=>{onDirtyChange(dirty||transaction.busy);},[dirty,transaction.busy,onDirtyChange]);
  useEffect(()=>{const prevent=(event:BeforeUnloadEvent)=>{if(dirtyRef.current||transaction.busy){event.preventDefault();event.returnValue="";}};window.addEventListener("beforeunload",prevent);return()=>window.removeEventListener("beforeunload",prevent);},[transaction.busy]);
  function hydrate(value:Projection){
    const content=(value.draft??value.active)?.content;
    setBasis({draft:value.draft?.version??"0",active:value.active?.version??"0"});
    setEditor(!content?EMPTY:isGoals(content)?{...EMPTY,goals:content.goals.join("\n"),topics:content.topics.join("\n"),reading:content.reading_requirement,scope:content.scope,until:localTime(content.valid_until)}:{...EMPTY,timezone:content.timezone,quietStart:String(content.quiet_start),quietEnd:String(content.quiet_end),enabled:content.notifications_enabled?"true":"false",important:content.important_during_quiet?"true":"false",format:content.reading_format,until:localTime(content.valid_until)});
    dirtyRef.current=false;setDirty(false);setFormError("");onDirtyChange(false);
  }
  useEffect(()=>{
    const controller=new AbortController();setLoading(true);setReadError("");
    void fetch("/api/boss/ui/workspace/"+route,{headers:{Authorization:"Bearer "+getToken()},cache:"no-store",signal:controller.signal}).then(async response=>{
      if(response.status===401)window.dispatchEvent(new Event("boss-auth-expired"));
      if(!response.ok)throw new Error("读取本人设置失败，HTTP "+response.status);
      const result=await response.json() as Projection;
      if(result.source_type!=="SIMULATED"||result.projection!==route)throw new Error("设置来源或页面范围不匹配");
      for(const record of [result.draft,result.active])if(record&&isGoals(record.content)!==isGoal)throw new Error("本人设置内容与当前页面不匹配");
      if(controller.signal.aborted)return;
      setData(result);setLoading(false);if(!dirtyRef.current)hydrate(result);
    }).catch(error=>{if(controller.signal.aborted)return;setReadError(error.message);setLoading(false);});
    return()=>controller.abort();
  },[route,revision,getToken]);
  function change<K extends keyof Editor>(key:K,value:Editor[K]){setEditor(current=>({...current,[key]:value}));dirtyRef.current=true;setDirty(true);setFormError("");}
  function save(){
    if(disabled||!data)return;
    if(editor.until&&!/^\d{4}-\d\d-\d\dT\d\d:\d\d$/.test(editor.until)){setFormError("请填写完整有效期日期与时间。");return;}
    const common={expected_version:basis.draft,valid_until:editor.until?editor.until+":00+08:00":null};
    if(isGoal){
      const goals=rows(editor.goals),topics=rows(editor.topics);
      if(!goals.length||goals.length>8||goals.some(value=>value.length>160)||new Set(goals).size!==goals.length){setFormError("请填写1—8项不同目标，每项不超过160字。");return;}
      if(topics.length>10||topics.some(value=>value.length>120)||new Set(topics).size!==topics.length){setFormError("关注主题最多10项，每项不超过120字且不能重复。");return;}
      if(!editor.scope||!editor.reading.trim()||editor.reading.trim().length>800){setFormError("请选择适用范围，并填写1—800字的阅读要求。");return;}
      transaction.propose("boss.owner.goals.save",{...common,goals,topics,reading_requirement:editor.reading.trim(),scope:editor.scope},"保存本人目标与关注要求",["原草稿版本："+basis.draft,"适用范围："+SCOPES[editor.scope],"目标："+goals.join("；"),"关注主题："+(topics.join("；")||"未指定"),"阅读要求："+editor.reading.trim(),"有效期："+(common.valid_until??"未设置期限"),"保存后为草稿，本人确认后才能在有效范围内采用。"]);
    }else{
      if(!editor.timezone.trim()||editor.quietStart===""||editor.quietEnd===""||editor.enabled===""||editor.important===""||editor.format===""){setFormError("请完整选择通知要求、时区、免打扰时段、事件升级及阅读格式。");return;}
      transaction.propose("boss.owner.notice.save",{...common,timezone:editor.timezone.trim(),quiet_start:Number(editor.quietStart),quiet_end:Number(editor.quietEnd),notifications_enabled:editor.enabled==="true",important_during_quiet:editor.important==="true",reading_format:editor.format,visibility:"BOSS_ONLY",calendar_share_limit:"BUSY_ONLY"},"保存本人通知要求",["原草稿版本："+basis.draft,"通知时区："+editor.timezone.trim(),"免打扰："+editor.quietStart+":00 — "+editor.quietEnd+":00","本人通知："+(editor.enabled==="true"?"允许按有效规则提醒":"暂停"),"重要事件在免打扰期间提醒："+(editor.important==="true"?"允许，仍受技术规则限制":"不允许"),"阅读格式："+FORMATS[editor.format],"有效期："+(common.valid_until??"未设置期限"),"私人正文仅本人可见；占用时间分享继续逐对象授权。"]);
    }
  }
  function confirm(){
    if(disabled||dirty||!data?.draft)return;
    transaction.propose(isGoal?"boss.owner.goals.confirm":"boss.owner.notice.confirm",{expected_draft_version:data.draft.version,expected_active_version:data.active?.version??"0",content_sha256:data.draft.content_sha256},isGoal?"确认当前本人要求":"确认当前通知要求",["待确认草稿：v"+data.draft.version,"当前有效版本："+(data.active?.version??"尚未确认"),"内容摘要："+data.draft.content_sha256,"有效期："+(data.draft.content.valid_until??"未设置期限"),"确认后仅在有效期和本人授权范围内采用当前内容。"]);
  }
  const saveControls=<div className="boss-actions"><button className="boss-btn boss-btn-primary" disabled={disabled} onClick={save}>{isGoal?"保存":"保存本人通知要求"}</button><button className="boss-btn" disabled={disabled||dirty||!data?.draft} onClick={confirm}>确认当前要求</button><button className="boss-btn" disabled={loading||transaction.busy||!data} onClick={()=>{if(data)hydrate(data);}}>恢复最近保存内容</button>{!isGoal&&<button className="boss-btn" onClick={()=>onNavigate("N06")}>应用内通知中心</button>}</div>;
  const versionState=<><V7Fact label="草稿版本">{data?data.draft?.version??"尚未保存":"尚未读取"}</V7Fact><V7Fact label="草稿状态">{data?data.draft?.state??"未设置":"尚未读取"}</V7Fact><V7Fact label="本人已确认版本">{data?active?.version??"尚未确认":"尚未读取"}</V7Fact><V7Fact label="有效状态">{effectiveState}</V7Fact><V7Fact label="确认时间">{data?active?.confirmed_at??"尚未确认":"尚未读取"}</V7Fact><V7Fact label="有效期限">{active?active.content.valid_until??"未设置期限":"尚未取得有效内容"}</V7Fact></>;
  return <div className={"boss-owner-preferences "+(isGoal?"boss-goals-view":"boss-notice-view")}>
    <V7ReadState loading={loading} error={readError} onReload={reload}/>
    {formError&&<p className="boss-status boss-status-error" role="alert">{formError}</p>}
    {dirty&&<p className="boss-status boss-status-warn" role="status">当前内容尚未保存。</p>}
    {stale&&<p className="boss-status boss-status-warn" role="status">已保存版本发生变化。当前编辑保留，采用最新保存内容后才能继续操作。</p>}
    <div className="boss-workspace-toolbar"><span>{data?.source_type??"本人设置待读取"}</span><button className="boss-btn" disabled={loading||transaction.busy} onClick={reload}>重新读取当前版本</button></div>
    <div className="boss-preference-columns"><div className="boss-column">
      <V7Panel title={isGoal?"内容与配置":"应用内与系统通知"}>
        <fieldset className="boss-preference-fields" disabled={disabled}>
          {isGoal?<><div className="boss-form-grid"><label>目标内容（每行一项）<textarea rows={5} value={editor.goals} maxLength={1600} onChange={event=>change("goals",event.target.value)} placeholder="填写本人明确的工作目标"/></label><label>关注主题（每行一项）<textarea rows={5} value={editor.topics} maxLength={1300} onChange={event=>change("topics",event.target.value)} placeholder="填写本人关注的主题"/></label><label>适用范围<select value={editor.scope} onChange={event=>change("scope",event.target.value as Editor["scope"])}><option value="">请选择范围</option>{Object.entries(SCOPES).map(([value,title])=><option key={value} value={value}>{title}</option>)}</select></label><label>目标期限（Asia/Shanghai，可留空）<input type="datetime-local" value={editor.until} onChange={event=>change("until",event.target.value)}/></label></div><h3>编辑内容与说明</h3><label className="boss-field">阅读与表达要求<textarea rows={5} value={editor.reading} maxLength={800} onChange={event=>change("reading",event.target.value)} placeholder="填写希望持续采用的阅读与表达要求"/></label></>:<>
            <div className="boss-form-grid"><label>应用内通知要求<select value={editor.enabled} onChange={event=>change("enabled",event.target.value as Editor["enabled"])}><option value="">待设置</option><option value="true">按有效规则提醒</option><option value="false">暂停本人通知</option></select></label><label>系统通知许可<input readOnly value="由系统提供，尚未取得全局许可结果"/></label><label>IANA 通知时区<input value={editor.timezone} maxLength={80} onChange={event=>change("timezone",event.target.value)} placeholder="请选择实际采用的时区"/></label><label>可见范围<input readOnly value="私人正文仅本人可见；系统预览采用最少信息"/></label><label>免打扰开始（整点）<select value={editor.quietStart} onChange={event=>change("quietStart",event.target.value)}><option value="">待设置</option>{Array.from({length:24},(_,index)=><option key={index} value={String(index)}>{index}:00</option>)}</select></label><label>免打扰结束（整点）<select value={editor.quietEnd} onChange={event=>change("quietEnd",event.target.value)}><option value="">待设置</option>{Array.from({length:24},(_,index)=><option key={index} value={String(index)}>{index}:00</option>)}</select></label><label>重要事件升级<select value={editor.important} onChange={event=>change("important",event.target.value as Editor["important"])}><option value="">待设置</option><option value="false">遵守本人免打扰</option><option value="true">技术规则允许时可在免打扰期间提醒</option></select></label><label>阅读格式<select value={editor.format} onChange={event=>change("format",event.target.value as Editor["format"])}><option value="">待设置</option>{Object.entries(FORMATS).map(([value,title])=><option key={value} value={value}>{title}</option>)}</select></label><label>要求有效期（Asia/Shanghai，可留空）<input type="datetime-local" value={editor.until} onChange={event=>change("until",event.target.value)}/></label></div>
          </>}
        </fieldset>{!isGoal&&saveControls}
      </V7Panel>
      {isGoal?<V7Panel title="关联内容与处理边界"><div className="boss-preference-facts"><V7Fact label="当前要求">{active&&isGoals(active.content)?active.content.goals.join("；"):"尚未取得本人确认的目标"}</V7Fact><V7Fact label="本人确认">{effectiveState}</V7Fact><V7Fact label="适用范围">{active&&isGoals(active.content)?SCOPES[active.content.scope]:"尚未确认"}</V7Fact></div><p className="boss-v7-note">保存的候选要求尚未生效。实际采用需要对应任务记录和有效版本。</p><div className="boss-actions"><button className="boss-btn" onClick={()=>onNavigate("F01")}>查看今日工作</button><button className="boss-btn" onClick={()=>onNavigate("F04")}>查看会前材料</button><button className="boss-btn" onClick={()=>onNavigate("F13")}>个人记忆</button></div></V7Panel>:<V7Panel title="隐私预览"><V7Fact label="系统预览应用名">Boss-Agent</V7Fact><V7Fact label="事项类别">经营提醒</V7Fact><V7Fact label="显示内容">请打开应用核查当前事项。</V7Fact><V7Fact label="返回入口">打开后核查当前授权与原通知对象</V7Fact><V7Fact label="私人标题与正文">不展示</V7Fact><V7Fact label="附件或摘要">不展示</V7Fact><p className="boss-v7-note">系统许可被拒绝时，可通过应用内通知中心读取获准内容。</p><details><summary>分享字段与私人安排</summary><V7Fact label="默认许可字段">仅占用时间 BUSY_ONLY</V7Fact><p>接收对象、用途、到期时间及撤销状态在私人安排中逐项核查。这里保存通知要求不创建分享授权。</p><div className="boss-actions"><button className="boss-btn" onClick={()=>onNavigate("F12")}>进入私人安排</button><button className="boss-btn" onClick={()=>onNavigate("N10")}>查看授权</button><button className="boss-btn" onClick={()=>onNavigate("F13")}>个人记忆</button></div></details></V7Panel>}
    </div><aside className="boss-column">
      {isGoal?<><V7Panel title="来源与依据"><V7Fact label="内容来源">{selected?.content.source??"尚未填写"}</V7Fact><V7Fact label="对象标识">{selected?.id??"尚未保存"}</V7Fact><V7Fact label="编辑依据版本">{basis.draft==="0"?"尚无保存草稿":basis.draft}</V7Fact><V7Fact label="最近保存时间">{data?.draft?.saved_at??"尚未保存"}</V7Fact><p className="boss-v7-note">本人目标与阅读要求仅由本人保存和确认。</p></V7Panel><V7Panel title="状态与核查">{versionState}<V7Fact label="当前版本采用">{actualUsage?.observation??(data?"尚无当前版本采用记录":"尚未读取")}</V7Fact></V7Panel></>:<V7Panel title="权限与返回"><BossNotificationPermissions/><V7Fact label="系统许可拒绝或撤销">在系统设置中管理当前应用的通知许可</V7Fact><V7Fact label="会话过期">重新认证后核查当前通知对象</V7Fact><div className="boss-actions"><button className="boss-btn" onClick={()=>onNavigate("D09")}>历史通知详情</button><button className="boss-btn" onClick={()=>onNavigate("N09")}>查看或暂停本人计划</button></div><h3>当前有效要求</h3>{versionState}<div className="boss-actions"><button className="boss-btn" onClick={()=>setRecordView("history")}>查看历史版本</button><button className="boss-btn" onClick={()=>setRecordView("usage")}>查看实际采用</button></div></V7Panel>}
    </aside></div>
    {isGoal&&<footer className="boss-owner-actions">{saveControls}<button className="boss-btn" onClick={()=>setRecordView("history")}>查看历史</button><button className="boss-btn" onClick={()=>setRecordView("usage")}>查看实际采用</button></footer>}
    {transaction.notice&&<p className="boss-status boss-status-ok" role="status">{transaction.notice}</p>}{transaction.dialog}{transaction.recovery}
    <Dialog.Root open={recordView!==null} onOpenChange={open=>{if(!open)setRecordView(null);}}><Dialog.Portal><Dialog.Overlay className="boss-v7-dialog-overlay"/><Dialog.Content className="boss-v7-dialog"><Dialog.Title>{recordView==="history"?"历史已确认版本":"实际采用与当前要求"}</Dialog.Title><Dialog.Description>记录来自当前本人获准范围，保存、确认和后续采用分别核查。</Dialog.Description>
      {recordView==="history"?<><div className="boss-v7-table-scroll"><table className="boss-v7-table"><thead><tr><th>历史版本</th><th>状态</th><th>本人确认时间</th></tr></thead><tbody>{data?.history.map(row=><tr key={row.version}><td>{row.version}</td><td>{row.state}</td><td>{row.confirmed_at??"尚未提供"}</td></tr>)}</tbody></table></div>{!data?.history.length&&<V7Empty title={data?"没有已读取的历史版本":"历史版本待读取"}/>}</>:<>{versionState}{isGoal?<><V7Fact label="当前采用版本">{actualUsage?.active_version??"尚未记录"}</V7Fact><V7Fact label="上下文加载次数">{actualUsage?.context_load_count??"尚无当前版本记录"}</V7Fact><V7Fact label="最近加载时间">{actualUsage?.last_loaded_at??"尚未记录"}</V7Fact><V7Fact label="采用观测">{actualUsage?.observation??"尚未取得"}</V7Fact><p>上下文加载记录仅证明要求已经提供给相应任务，模型执行质量仍需独立核查。</p></>:<><V7Fact label="技术规则版本">{data?.technical_rules?.version??"尚未读取"}</V7Fact><V7Fact label="技术调度版本">{data?.technical_schedule?.version??"尚未读取"}</V7Fact><V7Fact label="技术调度状态">{data?.technical_schedule?.canceled?"已取消":data?.technical_schedule?.enabled===true?"启用":data?.technical_schedule?.enabled===false?"暂停":"尚未读取"}</V7Fact><p>查看通知记录中的实际采用规则、抑制原因和送达结果。</p><button className="boss-btn" onClick={()=>onNavigate("N06")}>打开通知中心</button></>}</>}
      <div className="boss-actions"><Dialog.Close asChild><button className="boss-btn">关闭</button></Dialog.Close></div>
    </Dialog.Content></Dialog.Portal></Dialog.Root>
  </div>;
}
