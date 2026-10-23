import { useCallback, useEffect, useRef, useState } from "react";
import { AlertCircle, ArrowRight, ChartNoAxesCombined, Clock3,
  FileSearch, FolderOpen, Loader2, RefreshCw, Search, Sparkles } from "lucide-react";
import { useClient } from "@/providers/ClientProvider";

export const SECTOR_PAGE_IDS = [
  "F14","F15","F16","F17","F18","F19","F20","F21","F22","F23",
  "V19-BEEF","V19-EGG","V19-MILK",
] as const;
type Sector = {
  page_id: string; title: string; design_filters: string[]; kpi_labels: string[];
  metrics: {label:string;value:null;unit:null;data_status:string}[];
  related_source_refs: {
    source_id:string;source_type:string;version:string;
    published_at?:string;related_scope:string;not_evidence_for:string;
  }[];
  sector_specific_dataset_available:boolean;
  sector_kpi_calculations_supported:boolean;
  data_gap:string;
  business_scope:string;source_type:"SIMULATED";
  namespace:string;dataset_version:string;read_at:string;
};
type Props = {
  pageId:string;
  onNavigate:(page:string)=>void;
  onViewSource:(source:string)=>void;
  onStartChat:(content:string)=>Promise<boolean|void>;
};

export function BossSectorView({pageId,onNavigate,onViewSource,onStartChat}:Props) {
  const {client,getToken,token}=useClient();
  const [loadedData,setData]=useState<Sector|null>(null);
  const [fieldValues,setFields]=useState<Record<string,string>>({});
  const [appliedValues,setApplied]=useState<Record<string,string>>({});
  const [revision,setRevision]=useState(0);
  const [errorText,setError]=useState("");
  const [noticeText,setNotice]=useState("");
  const [loadingState,setLoading]=useState(false);
  const [sendingState,setSending]=useState(false);
  const identity=useRef({client,token,pageId});
  const displayed=useRef(identity.current);
  if(identity.current.client!==client||identity.current.token!==token||identity.current.pageId!==pageId)
    identity.current={client,token,pageId};
  const sameScope=displayed.current===identity.current;
  const data=sameScope?loadedData:null;
  const fields=sameScope?fieldValues:{};
  const applied=sameScope?appliedValues:{};
  const error=sameScope?errorText:"";
  const notice=sameScope?noticeText:"";
  const loading=sameScope&&loadingState;
  const sending=sameScope&&sendingState;
  const clearScope=useCallback(()=>{
    identity.current={...identity.current};displayed.current=identity.current;
    setData(null);setFields({});setApplied({});setError("");setNotice("");setSending(false);setLoading(false);
  },[]);

  useEffect(()=>{
    clearScope();
    return()=>{identity.current={...identity.current};};
  },[client,token,pageId,clearScope]);

  useEffect(()=>{
    if(!(SECTOR_PAGE_IDS as readonly string[]).includes(pageId))return;
    const abort=new AbortController();
    const current=identity.current;
    const currentToken=getToken();
    if(!currentToken){setError("身份令牌失效");return;}
    setLoading(true);setError("");setData(null);
    void fetch("/api/boss/ui/sector?page="+encodeURIComponent(pageId),{
      headers:{"Authorization":"Bearer "+currentToken},
      cache:"no-store",signal:abort.signal,
    }).then(async res=>{
      if(abort.signal.aborted||current!==identity.current)return null;
      if(res.status===401||res.status===403){
        clearScope();setError("当前专题范围校验失败（HTTP "+res.status+"）");return null;
      }
      if(!res.ok)throw new Error("当前专题范围校验失败（HTTP "+res.status+"）");
      const value=await res.json() as Sector;
      if(value.page_id!==pageId||value.source_type!=="SIMULATED"||
         value.sector_kpi_calculations_supported!==false)
        throw new Error("当前专题资料状态与接口预期不一致");
      return value;
    }).then(value=>{
      if(abort.signal.aborted||current!==identity.current||value===null)return;
      setData(value);setLoading(false);
    }).catch(e=>{
      if(abort.signal.aborted||current!==identity.current)return;
      setError(e instanceof Error?e.message:String(e));setLoading(false);
    });
    return ()=>abort.abort();
  },[pageId,revision,getToken,client,token,clearScope]);

  function checkScope(){
    if(!data||data.page_id!==pageId){setError("专题来源尚未载入");return;}
    setApplied({...fields});
    setNotice("已记录当前页面的查询条件；后端尚无可计算本专题指标的授权明细，所有数值继续保持未知。");
  }
  async function askAgent(){
    if(!data||data.page_id!==pageId||!getToken()||sending)return;
    const current=identity.current;
    setError("");setSending(true);
    try{
      const conditions=Object.entries(applied).filter(([,value])=>value.trim()).map(
        ([key,value])=>key+"="+value.trim()).join("；");
      const prompt=[
        "当前是 Boss-Agent 的获准农业专题阅读任务，不得创建或发送交办。",
        "专题："+data.title+"（"+pageId+"）。",
        "用户填写的范围："+(conditions||"尚未提供具体筛选条件")+"。",
        "已验证的资料覆盖："+data.data_gap,
        "关联资料："+data.related_source_refs.map(x=>x.source_id+" v"+x.version).join("、"),
        "请先梳理完成本专题实际经营判断所需要补充的明细、专业责任人、时间、统计口径和来源。",
        "只引用当前已有的有权材料；缺少资料时明确待提供，不猜测或生成虚构的经营数字。",
      ].join("\n");
      const result=await onStartChat(prompt);
      if(current!==identity.current)return;
      if(result===false)throw new Error("原生 Agent 会话创建失败，未提交业务请求");
      onNavigate("NATIVE");
    }catch(e){if(current===identity.current)setError(e instanceof Error?e.message:String(e));}
    finally{if(current===identity.current)setSending(false);}
  }
  return <>
    <div className="boss-workspace-toolbar">
      <div className="boss-workspace-note">
        <span className="boss-tag boss-tag-amber">模拟业务 · 尚无完整专题数据</span>
        <span>{pageId} · {data?.dataset_version?"资料版本 "+data.dataset_version:"等待读取"}</span>
      </div>
      <button type="button" className="boss-btn" disabled={loading}
        onClick={()=>setRevision(x=>x+1)}>
        {loading?<Loader2 size={15} className="boss-spin"/>:<RefreshCw size={15}/>} 重新核对
      </button>
    </div>
    {error&&<div className="boss-status boss-status-error" role="alert"><AlertCircle size={17}/>{error}</div>}
    {notice&&<div className="boss-status" role="status"><Clock3 size={17}/>{notice}</div>}
    {loading&&<div className="boss-status"><Loader2 className="boss-spin" size={17}/> 正在核对已授权的行业资料范围…</div>}
    {data&&<>
      <section className="boss-panel boss-sector-filters">
        <div className="boss-panel-head"><h2>经营筛选范围</h2>
          <small>原 Desktop v6 页面字段 · 未提供值不自动推断</small></div>
        {["F19","V19-BEEF","V19-EGG","V19-MILK"].includes(pageId)&&<div className="boss-sector-tabs">
          {[
            ["F19","肉禽"],["V19-EGG","蛋禽"],["V19-MILK","奶畜"],["V19-BEEF","肉用牛羊"],
          ].map(([id,label])=><button key={id} type="button" onClick={()=>onNavigate(id)}
            className={pageId===id?"selected":""}>{label}</button>)}
        </div>}
        <div className="boss-sector-filter-row">
          {data.design_filters.map(label=><label key={label}>
            <span>{label}</span>
            <input value={fields[label]||""}
              onChange={e=>setFields(old=>({...old,[label]:e.target.value}))}
              placeholder="待选择 / 待提供"/>
          </label>)}
          <button type="button" className="boss-btn boss-btn-primary" onClick={checkScope}>
            <Search size={16}/> 核对资料范围
          </button>
        </div>
        <p className="boss-helper">输入值只作为本次分析条件保存于页面，不会被虚构成已查询的数据记录。</p>
      </section>
      <div className="boss-columns">
        <div className="boss-column">
          <section className="boss-panel">
            <div className="boss-panel-head"><h2><ChartNoAxesCombined size={17}/> 经营指标与趋势</h2>
              <small>与 v6 原稿的指标顺序一致</small></div>
            <div className="boss-sector-stat-grid">
              {data.metrics.map(item=><div className="boss-sector-stat" key={item.label}>
                <span>{item.label}</span><strong>待查询</strong>
                <small>单位、期间、可追溯数据来源未提供</small>
              </div>)}
            </div>
            <div className="boss-sector-chart-empty">
              <ChartNoAxesCombined size={27} aria-hidden="true"/>
              <strong>缺少能够绘制本专题经营趋势的明细</strong>
              <p>当前没有可验证的期间、统计粒度和分子分母。图表不绘制虚构趋势或零值。</p>
            </div>
          </section>
          <section className="boss-panel">
            <div className="boss-panel-head"><h2>已有依据与可补充材料</h2>
              <small>来源版本、覆盖范围、缺口</small></div>
            {data.related_source_refs.length?data.related_source_refs.map(source=>
              <div className="boss-workspace-item" key={source.source_id}>
                <div className="boss-workspace-item-top"><strong>{source.source_id}</strong>
                  <span className="boss-tag boss-tag-green">{source.source_type}</span></div>
                <div className="boss-kv"><span>有效版本</span><strong>{source.version}</strong></div>
                <div className="boss-kv"><span>实际范围</span><strong>{source.related_scope}</strong></div>
                <p>不能支持：{source.not_evidence_for}</p>
                <button className="boss-btn" type="button" onClick={()=>onViewSource(source.source_id)}>
                  <FileSearch size={15}/> 核对原始资料 <ArrowRight size={15}/>
                </button>
              </div>)
              :<div className="boss-empty"><FolderOpen size={20}/>
                <div><strong>没有适用于本专题的已核验明细</strong>
                  <p>无法从其他专题借用数值或未经确认的业务口径。</p></div></div>}
            <div className="boss-status boss-status-warn"><AlertCircle size={16}/>{data.data_gap}</div>
          </section>
        </div>
        <div className="boss-column">
          <section className="boss-panel">
            <div className="boss-panel-head"><h2>业务范围与统计口径</h2><small>{pageId}</small></div>
            <div className="boss-kv"><span>专题</span><strong>{data.title}</strong></div>
            <div className="boss-kv"><span>数据集</span><strong>{data.namespace} / {data.dataset_version}</strong></div>
            <div className="boss-kv"><span>资料属性</span><strong>{data.source_type}</strong></div>
            <div className="boss-kv"><span>完整业务明细</span><strong>缺少</strong></div>
            <div className="boss-kv"><span>可计算专题指标</span><strong>否</strong></div>
            <div className="boss-kv"><span>最近核对时间</span><strong>{data.read_at.replace("T"," ")}</strong></div>
            <div className="boss-sector-next">
              <button type="button" className="boss-btn boss-btn-primary" disabled={sending}
                onClick={()=>void askAgent()}>
                {sending?<Loader2 size={15} className="boss-spin"/>:<Sparkles size={15}/>}
                与大鹏讨论需要补充的资料
              </button>
              {pageId==="F14"&&<button className="boss-btn" type="button" onClick={()=>onNavigate("F03")}>
                查看已授权外销经营指标</button>}
              <button className="boss-btn" type="button" onClick={()=>onNavigate("N03")}>
                返回经营关注</button>
            </div>
          </section>
          <section className="boss-panel">
            <div className="boss-panel-head"><h2>当前判断限制</h2></div>
            <p className="boss-helper">可以整理项目问题、识别需要的业务资料并与 Agent 连续沟通，但只有取得有效原始资料、完成定义校验后才能展示经营指标或建议结论。</p>
            <div className="boss-status"><Clock3 size={16}/> 没有数据时不生成图表、不估算金额、不将计划或专业反馈标记为已完成。</div>
          </section>
        </div>
      </div>
    </>}
  </>;
}
