import {useEffect,useId,useRef,useState,type ClipboardEvent} from "react";
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
type Props={pageId:"N07"|"N08";refreshVersion?:number;onNavigate:(page:string)=>void;onDirtyChange:(dirty:boolean)=>void};
type Editor={goals:string[];topics:string[];reading:string;scope:GoalSettings["scope"]|"";until:string;timezone:string;quietStart:string;quietEnd:string;enabled:""|"true"|"false";important:""|"true"|"false";format:NoticeSettings["reading_format"]|""};
type ItemKey="goals"|"topics";
const SCOPES={OWNER_WORKSPACE:"本人全部工作区",DAILY_BRIEF:"晨间简报",MEETING_PREP:"会议准备"};
const FORMATS={ACTIONS_FIRST:"待行动事项优先",SUMMARY:"简要汇总",DETAIL:"详细模式"};
const MAX_GOALS=8,MAX_TOPICS=10,GOAL_LIMIT=160,TOPIC_LIMIT=120,READING_LIMIT=800;
const TIME_ZONES=Intl.supportedValuesOf("timeZone");
const HOURS=Array.from({length:24},(_,hour)=>String(hour));
function emptyEditor():Editor{return {goals:[],topics:[],reading:"",scope:"",until:"",timezone:"",quietStart:"",quietEnd:"",enabled:"",important:"",format:""};}
function localTime(value:string|null){return value?new Intl.DateTimeFormat("sv-SE",{timeZone:"Asia/Shanghai",year:"numeric",month:"2-digit",day:"2-digit",hour:"2-digit",minute:"2-digit",hourCycle:"h23"}).format(new Date(value)).replace(" ","T"):"";}
function isGoals(value:GoalSettings|NoticeSettings):value is GoalSettings{return "goals" in value;}
function goalRecord(record:RecordState|null|undefined){return record&&isGoals(record.content)?record.content:null;}
function noticeRecord(record:RecordState|null|undefined){return record&&!isGoals(record.content)?record.content:null;}
function zoneNow(zone:string){return TIME_ZONES.includes(zone)?new Intl.DateTimeFormat("en-GB",{timeZone:zone,hour:"2-digit",minute:"2-digit",hourCycle:"h23"}).format(new Date()):"";}
function zoneClock(zone:string){return TIME_ZONES.includes(zone)?new Intl.DateTimeFormat("zh-CN",{timeZone:zone,dateStyle:"short",timeStyle:"short",hourCycle:"h23"}).format(new Date()):"";}
function quietSummary(start:string,end:string){
  if(start===""||end==="")return "免打扰时段尚未完整设置。";
  const begin=Number(start),finish=Number(end);
  if(begin===finish)return "免打扰开始与结束均为 "+begin+":00，该时段不会抑制通知。";
  return begin>finish?"免打扰时段："+begin+":00 至次日 "+finish+":00，跨日时段包含开始小时至午夜以及午夜至结束小时。":"免打扰时段："+begin+":00 至 "+finish+":00。";
}
function goalDiff(draft:GoalSettings,active:GoalSettings|null){
  if(!active)return ["当前没有已确认版本，核对生效会建立第一份有效要求。"];
  const lines:string[]=[];
  if(draft.goals.join("\n")!==active.goals.join("\n"))lines.push("目标：由 "+active.goals.length+" 项改为 "+draft.goals.length+" 项。");
  if(draft.topics.join("\n")!==active.topics.join("\n"))lines.push("关注主题：由 "+active.topics.length+" 项改为 "+draft.topics.length+" 项。");
  if(draft.scope!==active.scope)lines.push("适用范围："+SCOPES[active.scope]+" 改为 "+SCOPES[draft.scope]+"。");
  if(draft.reading_requirement!==active.reading_requirement)lines.push("阅读与表达要求已经修改。");
  if((draft.valid_until??"")!==(active.valid_until??""))lines.push("有效期："+(active.valid_until??"未设置期限")+" 改为 "+(draft.valid_until??"未设置期限")+"。");
  return lines.length?lines:["草稿与当前有效版本内容一致。"];
}
function noticeDiff(draft:NoticeSettings,active:NoticeSettings|null){
  if(!active)return ["当前没有已确认版本，核对生效会建立第一份有效要求。"];
  const lines:string[]=[];
  if(draft.notifications_enabled!==active.notifications_enabled)lines.push("应用内通知："+(active.notifications_enabled?"允许按有效规则提醒":"暂停")+" 改为 "+(draft.notifications_enabled?"允许按有效规则提醒":"暂停")+"。");
  if(draft.timezone!==active.timezone)lines.push("通知时区："+active.timezone+" 改为 "+draft.timezone+"。");
  if(draft.quiet_start!==active.quiet_start||draft.quiet_end!==active.quiet_end)lines.push("免打扰时段："+active.quiet_start+":00 — "+active.quiet_end+":00 改为 "+draft.quiet_start+":00 — "+draft.quiet_end+":00。");
  if(draft.important_during_quiet!==active.important_during_quiet)lines.push("重要事件在免打扰期间提醒："+(active.important_during_quiet?"允许，仍受技术规则限制":"不允许")+" 改为 "+(draft.important_during_quiet?"允许，仍受技术规则限制":"不允许")+"。");
  if(draft.reading_format!==active.reading_format)lines.push("阅读格式："+FORMATS[active.reading_format]+" 改为 "+FORMATS[draft.reading_format]+"。");
  if((draft.valid_until??"")!==(active.valid_until??""))lines.push("有效期："+(active.valid_until??"未设置期限")+" 改为 "+(draft.valid_until??"未设置期限")+"。");
  return lines.length?lines:["草稿与当前有效版本内容一致。"];
}
function noticePreview(editor:Editor,at:string){
  if(!TIME_ZONES.includes(editor.timezone))return ["先选择通知时区，才能按本地时间预览。"];
  if(editor.enabled===""||editor.quietStart===""||editor.quietEnd===""||editor.important===""||editor.format==="")return ["先填写应用内通知要求、免打扰时段、重要事件升级和阅读格式，才能预览。"];
  if(at==="")return ["填写预览时刻后显示本人规则的允许或抑制结果。"];
  const lines=["预览时刻："+at+"（"+editor.timezone+"）","阅读格式："+FORMATS[editor.format],quietSummary(editor.quietStart,editor.quietEnd)];
  if(editor.enabled==="false")return [...lines,"结果：本人通知已经暂停，本次提醒被抑制。"];
  const hour=Number(at.slice(0,2)),begin=Number(editor.quietStart),finish=Number(editor.quietEnd);
  const quiet=begin>finish?(hour>=begin||hour<finish):begin<finish?(begin<=hour&&hour<finish):false;
  if(!quiet)return [...lines,"结果：该时刻不在免打扰时段，按阅读格式生成提醒。"];
  if(editor.important==="true")return [...lines,"结果：该时刻处于免打扰时段。普通事项被抑制；重要事项在技术规则允许时可以提醒。"];
  return [...lines,"结果：该时刻处于免打扰时段，本次提醒按本人设置抑制。"];
}

export function BossOwnerPreferences(props:Props){
  const {token}=useClient();
  const identity=useRef({token,sequence:0});
  if(identity.current.token!==token)identity.current={token,sequence:identity.current.sequence+1};
  return <OwnerPreferences key={props.pageId+identity.current.sequence} {...props}/>;
}

function OwnerPreferences({pageId,refreshVersion,onNavigate,onDirtyChange}:Props){
  const {getToken}=useClient();
  const zoneListId=useId();
  const isGoal=pageId==="N07",route=isGoal?"owner-goals":"owner-notice";
  const [data,setData]=useState<Projection|null>(null),[revision,setRevision]=useState(0);
  const [loading,setLoading]=useState(true),[readError,setReadError]=useState(""),[formError,setFormError]=useState("");
  const [editor,setEditor]=useState<Editor>(emptyEditor),[basis,setBasis]=useState({draft:"0",active:"0"});
  const [dirty,setDirty]=useState(false),dirtyRef=useRef(false);
  const [recordView,setRecordView]=useState<"history"|"usage"|null>(null);
  const [discardOpen,setDiscardOpen]=useState(false);
  const [previewOpen,setPreviewOpen]=useState(false),[previewAt,setPreviewAt]=useState("");
  const pendingChain=useRef(false),chainAfterSave=useRef(false);
  const reload=()=>setRevision(value=>value+1);
  const transaction=useTransaction(recorded=>{
    if(recorded){dirtyRef.current=false;setDirty(false);onDirtyChange(false);chainAfterSave.current=pendingChain.current;}
    else chainAfterSave.current=false;
    pendingChain.current=false;
    reload();
  },undefined,undefined,isGoal?"ownerGoals":"ownerNotice");
  const stale=Boolean(data&&(basis.draft!==(data.draft?.version??"0")||basis.active!==(data.active?.version??"0")));
  const disabled=loading||transaction.busy||!data||Boolean(readError)||stale;
  const active=data?.active,selected=data?.draft??active;
  const usage=data?.runtime_context_observation;
  const actualUsage=usage&&usage.active_version===active?.version?usage:null;
  const effectiveState=data?data.active_is_effective?"已确认且在有效期内":"当前未生效":"尚未读取";
  const actionHint=loading?"正在读取当前版本，读取完成后才能保存或确认。":transaction.busy?"正在提交本次操作，请等待结果。":readError?"读取失败，请先重新读取当前版本。":!data?"尚未读取本人当前设置。":stale?"已保存版本发生变化，请先核对最新保存内容，再继续编辑或确认。":"";
  const goalDraft=goalRecord(data?.draft??null),goalActive=goalRecord(active);
  const noticeDraft=noticeRecord(data?.draft??null),noticeActive=noticeRecord(active);
  const diffLines=data?.draft?isGoal?(goalDraft?goalDiff(goalDraft,goalActive):[]):(noticeDraft?noticeDiff(noticeDraft,noticeActive):[]):[];
  const restoreLabel=data?.draft?"草稿 v"+data.draft.version:active?"已确认版本 v"+active.version:"空白内容";
  useEffect(()=>{onDirtyChange(dirty||transaction.busy);},[dirty,transaction.busy,onDirtyChange]);
  useEffect(()=>{const prevent=(event:BeforeUnloadEvent)=>{if(dirtyRef.current||transaction.busy){event.preventDefault();event.returnValue="";}};window.addEventListener("beforeunload",prevent);return()=>window.removeEventListener("beforeunload",prevent);},[transaction.busy]);
  function markDirty(){dirtyRef.current=true;setDirty(true);setFormError("");}
  function hydrate(value:Projection){
    const content=(value.draft??value.active)?.content;
    setBasis({draft:value.draft?.version??"0",active:value.active?.version??"0"});
    setEditor(!content?emptyEditor():isGoals(content)?{...emptyEditor(),goals:[...content.goals],topics:[...content.topics],reading:content.reading_requirement,scope:content.scope,until:localTime(content.valid_until)}:{...emptyEditor(),timezone:content.timezone,quietStart:String(content.quiet_start),quietEnd:String(content.quiet_end),enabled:content.notifications_enabled?"true":"false",important:content.important_during_quiet?"true":"false",format:content.reading_format,until:localTime(content.valid_until)});
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
      if(chainAfterSave.current){
        chainAfterSave.current=false;
        if(!dirtyRef.current&&result.draft)confirmRecord(result);
      }
    }).catch(error=>{if(controller.signal.aborted)return;chainAfterSave.current=false;setReadError(error.message);setLoading(false);});
    return()=>controller.abort();
  },[route,revision,refreshVersion,getToken]);
  function change<K extends keyof Editor>(key:K,value:Editor[K]){setEditor(current=>({...current,[key]:value}));markDirty();}
  function updateItem(key:ItemKey,index:number,value:string){setEditor(current=>({...current,[key]:current[key].map((item,position)=>position===index?value:item)}));markDirty();}
  function addItem(key:ItemKey){const limit=key==="goals"?MAX_GOALS:MAX_TOPICS;setEditor(current=>current[key].length>=limit?current:{...current,[key]:[...current[key],""]});markDirty();}
  function removeItem(key:ItemKey,index:number){setEditor(current=>({...current,[key]:current[key].filter((_,position)=>position!==index)}));markDirty();}
  function pasteItems(event:ClipboardEvent<HTMLTextAreaElement>,key:ItemKey,index:number){
    const lines=event.clipboardData.getData("text").split(/\r?\n/).map(line=>line.trim()).filter(Boolean);
    if(lines.length<2)return;
    event.preventDefault();
    const limit=key==="goals"?MAX_GOALS:MAX_TOPICS,perItem=key==="goals"?GOAL_LIMIT:TOPIC_LIMIT;
    const merged=[...editor[key].slice(0,index),...lines,...editor[key].slice(index+1)].map(item=>item.slice(0,perItem));
    change(key,merged.slice(0,limit));
    if(merged.length>limit)setFormError((key==="goals"?"目标最多8项":"关注主题最多10项")+"，粘贴内容已保留前 "+limit+" 项，请检查。");
  }
  function save(chain=false){
    pendingChain.current=false;
    if(disabled||!data)return;
    if(editor.until&&!/^\d{4}-\d\d-\d\dT\d\d:\d\d$/.test(editor.until)){setFormError("请填写完整有效期日期与时间。");return;}
    const common={expected_version:basis.draft,valid_until:editor.until?editor.until+":00+08:00":null};
    if(isGoal){
      const goals=editor.goals.map(item=>item.trim()),topics=editor.topics.map(item=>item.trim());
      if(!goals.length||goals.length>MAX_GOALS||goals.some(item=>!item||item.length>GOAL_LIMIT)||new Set(goals).size!==goals.length){setFormError("请填写1—8项不同目标，每项不超过160字，不能留空或重复。");return;}
      if(topics.length>MAX_TOPICS||topics.some(item=>!item||item.length>TOPIC_LIMIT)||new Set(topics).size!==topics.length){setFormError("关注主题最多10项，每项不超过120字，不能留空或重复。");return;}
      if(!editor.scope||!editor.reading.trim()||editor.reading.trim().length>READING_LIMIT){setFormError("请选择适用范围，并填写1—800字的阅读要求。");return;}
      pendingChain.current=chain;
      transaction.propose("boss.owner.goals.save",{...common,goals,topics,reading_requirement:editor.reading.trim(),scope:editor.scope},"保存本人目标与关注要求草稿",["原草稿版本："+basis.draft,"适用范围："+SCOPES[editor.scope],"目标："+goals.join("；"),"关注主题："+(topics.join("；")||"未指定"),"阅读要求："+editor.reading.trim(),"有效期："+(common.valid_until??"未设置期限"),"保存后为草稿，本人确认后才能在有效范围内采用。"]);
    }else{
      if(!editor.timezone.trim()||editor.quietStart===""||editor.quietEnd===""||editor.enabled===""||editor.important===""||editor.format===""){setFormError("请完整选择通知要求、时区、免打扰时段、事件升级及阅读格式。");return;}
      pendingChain.current=chain;
      transaction.propose("boss.owner.notice.save",{...common,timezone:editor.timezone.trim(),quiet_start:Number(editor.quietStart),quiet_end:Number(editor.quietEnd),notifications_enabled:editor.enabled==="true",important_during_quiet:editor.important==="true",reading_format:editor.format,visibility:"BOSS_ONLY",calendar_share_limit:"BUSY_ONLY"},"保存本人通知要求草稿",["原草稿版本："+basis.draft,"通知时区："+editor.timezone.trim(),quietSummary(editor.quietStart,editor.quietEnd),"本人通知："+(editor.enabled==="true"?"允许按有效规则提醒":"暂停"),"重要事件在免打扰期间提醒："+(editor.important==="true"?"允许，仍受技术规则限制":"不允许"),"阅读格式："+FORMATS[editor.format],"有效期："+(common.valid_until??"未设置期限"),"私人正文仅本人可见；占用时间分享继续逐对象授权。"]);
    }
  }
  function confirmRecord(target:Projection){
    const draft=target.draft;
    if(!draft)return;
    const lines=["待确认草稿：v"+draft.version,"当前有效版本："+(target.active?.version??"尚未确认"),"内容摘要："+draft.content_sha256];
    if(isGoals(draft.content))lines.push("目标："+draft.content.goals.length+" 项","关注主题："+draft.content.topics.length+" 项","适用范围："+SCOPES[draft.content.scope],...goalDiff(draft.content,goalRecord(target.active)));
    else lines.push("通知时区："+draft.content.timezone,quietSummary(String(draft.content.quiet_start),String(draft.content.quiet_end)),"本人通知："+(draft.content.notifications_enabled?"允许按有效规则提醒":"暂停"),"重要事件在免打扰期间提醒："+(draft.content.important_during_quiet?"允许，仍受技术规则限制":"不允许"),"阅读格式："+FORMATS[draft.content.reading_format],...noticeDiff(draft.content,noticeRecord(target.active)));
    lines.push("有效期："+(draft.content.valid_until??"未设置期限"),"确认后仅在有效期和本人授权范围内采用。");
    transaction.propose(isGoal?"boss.owner.goals.confirm":"boss.owner.notice.confirm",{expected_draft_version:draft.version,expected_active_version:target.active?.version??"0",content_sha256:draft.content_sha256},isGoal?"核对并生效本人目标与关注要求":"核对并生效本人通知要求",lines);
  }
  function confirm(){
    if(disabled||dirty||!data?.draft)return;
    confirmRecord(data);
  }
  function confirmEffective(){
    if(disabled)return;
    if(dirty)save(true);
    else confirm();
  }
  const saveControls=<div className="boss-actions"><button className="boss-btn" disabled={disabled||!dirty} onClick={()=>save(false)}>保存草稿</button><button className="boss-btn boss-btn-primary" disabled={disabled||(!dirty&&!data?.draft)} onClick={confirmEffective}>核对并生效</button>{dirty&&<button className="boss-btn" disabled={loading||transaction.busy} onClick={()=>setDiscardOpen(true)}>放弃本次修改</button>}{!isGoal&&<button className="boss-btn" onClick={()=>{if(previewOpen){setPreviewOpen(false);return;}setPreviewAt(zoneNow(editor.timezone));setPreviewOpen(true);}}>{previewOpen?"收起通知效果预览":"预览通知效果"}</button>}</div>;
  const versionState=<><V7Fact label="草稿版本">{data?data.draft?.version??"尚未保存":"尚未读取"}</V7Fact><V7Fact label="草稿状态">{data?data.draft?.state??"未设置":"尚未读取"}</V7Fact><V7Fact label="本人已确认版本">{data?active?.version??"尚未确认":"尚未读取"}</V7Fact><V7Fact label="有效状态">{effectiveState}</V7Fact><V7Fact label="确认时间">{data?active?.confirmed_at??"尚未确认":"尚未读取"}</V7Fact><V7Fact label="有效期限">{active?active.content.valid_until??"未设置期限":"尚未取得有效内容"}</V7Fact></>;
  const goalItems=(key:ItemKey,limit:number,perItem:number,title:string,placeholder:string)=><>
    <h3>{title}（{key==="goals"?"1—8":"0—10"}项）</h3>
    {editor[key].map((value,index)=><div className="boss-field" key={key+index}>
      <span>{title} {index+1}</span>
      <textarea rows={2} maxLength={perItem} value={value} placeholder={placeholder} onChange={event=>updateItem(key,index,event.target.value)} onPaste={event=>pasteItems(event,key,index)}/>
      <div className="boss-actions"><button type="button" className="boss-v7-text-button" onClick={()=>removeItem(key,index)}>删除这项</button></div>
    </div>)}
    {!editor[key].length&&<p className="boss-v7-note">{key==="goals"?"尚未填写目标。至少需要一项才能保存草稿。":"尚未填写关注主题，可以留空。"}</p>}
    <div className="boss-actions"><button type="button" className="boss-btn" disabled={editor[key].length>=limit} onClick={()=>addItem(key)}>添加{key==="goals"?"目标":"关注主题"}</button>{editor[key].length>=limit&&<span className="boss-v7-note">{title}已达上限 {limit} 项。</span>}</div>
  </>;
  return <div className={"boss-owner-preferences "+(isGoal?"boss-goals-view":"boss-notice-view")}>
    <V7ReadState loading={loading} error={readError} onReload={reload}/>
    {formError&&<p className="boss-status boss-status-error" role="alert">{formError}</p>}
    {dirty&&<p className="boss-status boss-status-warn" role="status">当前内容尚未保存。</p>}
    {stale&&<p className="boss-status boss-status-warn" role="status">已保存版本发生变化。当前编辑保留，采用最新保存内容后才能继续操作。</p>}
    <div className="boss-workspace-toolbar"><span>{data?.source_type??"本人设置待读取"}</span></div>
    <div className="boss-preference-columns"><div className="boss-column">
      <V7Panel title={isGoal?"内容与配置":"应用内与系统通知"}>
        <fieldset className="boss-preference-fields" disabled={disabled}>
          {isGoal?<>
            {goalItems("goals",MAX_GOALS,GOAL_LIMIT,"目标","填写本人明确的工作目标")}
            {goalItems("topics",MAX_TOPICS,TOPIC_LIMIT,"关注主题","填写本人关注的主题")}
            <div className="boss-form-grid"><label>适用范围<select value={editor.scope} onChange={event=>change("scope",event.target.value as Editor["scope"])}><option value="">请选择范围</option>{Object.entries(SCOPES).map(([value,title])=><option key={value} value={value}>{title}</option>)}</select></label><label>目标期限（Asia/Shanghai，可留空）<input type="datetime-local" value={editor.until} onChange={event=>change("until",event.target.value)}/></label></div>
            <p className="boss-v7-note">当前服务按一份要求保存适用范围与期限，所有目标共用这两项。</p>
            <h3>阅读与表达要求</h3>
            <label className="boss-field">阅读与表达要求<textarea rows={5} value={editor.reading} maxLength={READING_LIMIT} onChange={event=>change("reading",event.target.value)} placeholder="填写希望持续采用的阅读与表达要求"/></label>
          </>:<>
            <div className="boss-form-grid"><label>应用内通知要求<select value={editor.enabled} onChange={event=>change("enabled",event.target.value as Editor["enabled"])}><option value="">待设置</option><option value="true">按有效规则提醒</option><option value="false">暂停本人通知</option></select></label><label>IANA 通知时区<input list={zoneListId} value={editor.timezone} maxLength={80} onChange={event=>change("timezone",event.target.value)} placeholder="输入或选择时区"/><datalist id={zoneListId}>{TIME_ZONES.map(zone=><option key={zone} value={zone}/>)}</datalist></label><label>免打扰开始（整点）<select value={editor.quietStart} onChange={event=>change("quietStart",event.target.value)}><option value="">待设置</option>{HOURS.map(hour=><option key={hour} value={hour}>{hour}:00</option>)}</select></label><label>免打扰结束（整点）<select value={editor.quietEnd} onChange={event=>change("quietEnd",event.target.value)}><option value="">待设置</option>{HOURS.map(hour=><option key={hour} value={hour}>{hour}:00</option>)}</select></label><label>重要事件升级<select value={editor.important} onChange={event=>change("important",event.target.value as Editor["important"])}><option value="">待设置</option><option value="false">遵守本人免打扰</option><option value="true">技术规则允许时可在免打扰期间提醒</option></select></label><label>阅读格式<select value={editor.format} onChange={event=>change("format",event.target.value as Editor["format"])}><option value="">待设置</option>{Object.entries(FORMATS).map(([value,title])=><option key={value} value={value}>{title}</option>)}</select></label><label>要求有效期（Asia/Shanghai，可留空）<input type="datetime-local" value={editor.until} onChange={event=>change("until",event.target.value)}/></label></div>
            <p className="boss-v7-note">{quietSummary(editor.quietStart,editor.quietEnd)}当前服务按整点保存免打扰时段。</p>
            <p className="boss-v7-note">{TIME_ZONES.includes(editor.timezone)?"通知时区当前本地时间："+zoneClock(editor.timezone)+"。免打扰按该时区判断。":"尚未选择有效时区名称，无法判断当前本地时间与免打扰结果。"}</p>
            <p className="boss-v7-note">可见范围：私人正文仅本人可见（BOSS_ONLY）；占用时间分享继续按 BUSY_ONLY 逐对象授权，不随通知要求扩大。</p>
          </>}
        </fieldset>
        {!isGoal&&previewOpen&&<>
          <h3>通知效果预览</h3>
          <label className="boss-field">预览时刻（按通知时区）<input type="time" value={previewAt} onChange={event=>setPreviewAt(event.target.value)}/></label>
          <div className="boss-v7-note">{noticePreview(editor,previewAt).map(line=><p key={line}>{line}</p>)}</div>
          <p className="boss-v7-note">预览只使用编辑区当前值与本人规则，不保存规则、不发送通知；技术冷却、事项影响级别和系统许可需要在实际触发时核查。</p>
        </>}
        <h3>与当前有效版本的差异</h3>
        <div className="boss-v7-note">{data?.draft?diffLines.map(line=><p key={line}>{line}</p>):<p>尚未保存草稿，保存后显示草稿与有效版本的差异。</p>}</div>
        {actionHint&&<p className="boss-v7-note" role="status">{actionHint}</p>}
        {!actionHint&&!dirty&&<p className="boss-v7-note">当前没有修改，保存草稿不可用。{!data?.draft?"尚未保存草稿，核对并生效需要先填写并保存内容。":""}</p>}
        {saveControls}
      </V7Panel>
      {isGoal?<V7Panel title="关联内容与处理边界"><div className="boss-preference-facts"><V7Fact label="当前要求">{active&&isGoals(active.content)?active.content.goals.join("；"):"尚未取得本人确认的目标"}</V7Fact><V7Fact label="本人确认">{effectiveState}</V7Fact><V7Fact label="适用范围">{active&&isGoals(active.content)?SCOPES[active.content.scope]:"尚未确认"}</V7Fact></div><p className="boss-v7-note">保存的候选要求尚未生效。实际采用需要对应任务记录和有效版本。</p><details><summary>关联功能</summary><div className="boss-actions"><button className="boss-btn" onClick={()=>onNavigate("F01")}>查看今日工作</button><button className="boss-btn" onClick={()=>onNavigate("F04")}>查看会前材料</button><button className="boss-btn" onClick={()=>onNavigate("F13")}>个人记忆</button></div><p className="boss-v7-note">离开本页时，有未保存内容会先进入离开确认。</p></details></V7Panel>:<V7Panel title="隐私预览"><V7Fact label="系统预览应用名">Boss-Agent</V7Fact><V7Fact label="事项类别">经营提醒</V7Fact><V7Fact label="显示内容">请打开应用核查当前事项。</V7Fact><V7Fact label="返回入口">打开后核查当前授权与原通知对象</V7Fact><V7Fact label="私人标题与正文">不展示</V7Fact><V7Fact label="附件或摘要">不展示</V7Fact><p className="boss-v7-note">系统许可被拒绝时，可通过应用内通知中心读取获准内容。</p><details><summary>分享字段与私人安排</summary><V7Fact label="默认许可字段">仅占用时间 BUSY_ONLY</V7Fact><p>接收对象、用途、到期时间及撤销状态在私人安排中逐项核查。这里保存通知要求不创建分享授权。</p><div className="boss-actions"><button className="boss-btn" onClick={()=>onNavigate("F12")}>进入私人安排</button><button className="boss-btn" onClick={()=>onNavigate("N10")}>查看授权</button><button className="boss-btn" onClick={()=>onNavigate("F13")}>个人记忆</button></div></details></V7Panel>}
    </div><aside className="boss-column">
      {isGoal?<><V7Panel title="来源与依据"><V7Fact label="内容来源">{selected?.content.source??"尚未填写"}</V7Fact><V7Fact label="对象标识">{selected?.id??"尚未保存"}</V7Fact><V7Fact label="编辑依据版本">{basis.draft==="0"?"尚无保存草稿":basis.draft}</V7Fact><V7Fact label="最近保存时间">{data?.draft?.saved_at??"尚未保存"}</V7Fact><p className="boss-v7-note">本人目标与阅读要求仅由本人保存和确认。</p></V7Panel><V7Panel title="状态与核查">{versionState}<V7Fact label="当前版本采用">{actualUsage?.observation??(data?"尚无当前版本采用记录":"尚未读取")}</V7Fact><div className="boss-actions"><button className="boss-btn" onClick={()=>setRecordView("history")}>版本历史</button><button className="boss-btn" onClick={()=>setRecordView("usage")}>采用记录</button></div></V7Panel></>:<V7Panel title="权限与返回"><BossNotificationPermissions/><V7Fact label="系统许可拒绝或撤销">在系统设置中管理当前应用的通知许可，页面文字不能改变许可结果</V7Fact><V7Fact label="会话过期">重新认证后核查当前通知对象</V7Fact><h3>关联功能</h3><div className="boss-actions"><button className="boss-btn" onClick={()=>onNavigate("N06")}>通知记录</button><button className="boss-btn" onClick={()=>onNavigate("N09")}>本人计划</button></div><p className="boss-v7-note">历史通知需要先在通知中心选择具体记录，再打开该记录的详情。</p><h3>当前有效要求</h3>{versionState}<div className="boss-actions"><button className="boss-btn" onClick={()=>setRecordView("history")}>版本历史</button><button className="boss-btn" onClick={()=>setRecordView("usage")}>采用记录</button></div></V7Panel>}
    </aside></div>
    {isGoal&&<footer className="boss-owner-actions">{saveControls}</footer>}
    {transaction.notice&&<p className="boss-status boss-status-ok" role="status">{transaction.notice}</p>}{transaction.dialog}{transaction.recovery}
    <Dialog.Root open={discardOpen} onOpenChange={setDiscardOpen}><Dialog.Portal><Dialog.Overlay className="boss-v7-dialog-overlay"/><Dialog.Content className="boss-v7-dialog"><Dialog.Title>放弃本次修改</Dialog.Title><Dialog.Description>放弃后恢复到{restoreLabel}，已经确认的有效版本不会被修改。</Dialog.Description><div className="boss-actions"><Dialog.Close asChild><button className="boss-btn">继续编辑</button></Dialog.Close><button className="boss-btn boss-btn-primary" onClick={()=>{if(data)hydrate(data);setDiscardOpen(false);}}>放弃修改</button></div></Dialog.Content></Dialog.Portal></Dialog.Root>
    <Dialog.Root open={recordView!==null} onOpenChange={open=>{if(!open)setRecordView(null);}}><Dialog.Portal><Dialog.Overlay className="boss-v7-dialog-overlay"/><Dialog.Content className="boss-v7-dialog"><Dialog.Title>{recordView==="history"?"历史已确认版本":"实际采用与当前要求"}</Dialog.Title><Dialog.Description>记录来自当前本人获准范围，保存、确认和后续采用分别核查。</Dialog.Description>
      {recordView==="history"?<><div className="boss-v7-table-scroll"><table className="boss-v7-table"><thead><tr><th>历史版本</th><th>状态</th><th>本人确认时间</th></tr></thead><tbody>{data?.history.map(row=><tr key={row.version}><td>{row.version}</td><td>{row.state}</td><td>{row.confirmed_at??"尚未提供"}</td></tr>)}</tbody></table></div>{!data?.history.length&&<V7Empty title={data?"没有已读取的历史版本":"历史版本待读取"}/>}</>:<>{versionState}{isGoal?<><V7Fact label="当前采用版本">{actualUsage?.active_version??"尚未记录"}</V7Fact><V7Fact label="上下文加载次数">{actualUsage?.context_load_count??"尚无当前版本记录"}</V7Fact><V7Fact label="最近加载时间">{actualUsage?.last_loaded_at??"尚未记录"}</V7Fact><V7Fact label="采用观测">{actualUsage?.observation??"尚未取得"}</V7Fact><p>上下文加载记录仅证明要求已经提供给相应任务，模型执行质量仍需独立核查。</p></>:<><V7Fact label="技术规则版本">{data?.technical_rules?.version??"尚未读取"}</V7Fact><V7Fact label="技术调度版本">{data?.technical_schedule?.version??"尚未读取"}</V7Fact><V7Fact label="技术调度状态">{data?.technical_schedule?.canceled?"已取消":data?.technical_schedule?.enabled===true?"启用":data?.technical_schedule?.enabled===false?"暂停":"尚未读取"}</V7Fact><p>查看通知记录中的实际采用规则、抑制原因和送达结果。</p><button className="boss-btn" onClick={()=>onNavigate("N06")}>打开通知中心</button></>}</>}
      <div className="boss-actions"><Dialog.Close asChild><button className="boss-btn">关闭</button></Dialog.Close></div>
    </Dialog.Content></Dialog.Portal></Dialog.Root>
  </div>;
}
