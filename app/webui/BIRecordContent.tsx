const LABELS:Record<string,string>={record_id:"记录标识",source_id:"来源标识",version:"版本",product_id:"产品",region_id:"区域",legal_entity_id:"法人",period_start:"期间开始",period_end:"期间结束",currency:"币种",quantity_unit:"数量单位",quantity:"数量",revenue:"营业收入",cost:"成本",gross_profit:"毛利",business_basis:"业务口径",settlement_state:"结算状态",trade_scope:"交易范围",author_display_name:"作者",author_contact_id:"作者标识",author_kind:"作者类型",allowed_use:"允许用途",valid_from:"有效开始时间",valid_until:"有效结束时间",content:"原文内容",original_locator:"原始位置",quality_state:"资料质量",business_as_of:"业务截至时间",source_updated_at:"来源更新时间"};

export function BIRecordContent({value}:{value:unknown}){
  if(value===null||value===undefined)return <span>未知</span>;
  if(Array.isArray(value))return value.length?<ol className="boss-bi-record-array">{value.map((item,index)=><li key={index}><BIRecordContent value={item}/></li>)}</ol>:<span>当前记录为空</span>;
  if(typeof value==="object")return <dl className="boss-bi-record-fields">{Object.entries(value).map(([field,item])=><div key={field}><dt>{LABELS[field]??field}</dt><dd><BIRecordContent value={item}/></dd></div>)}</dl>;
  return <span className="boss-bi-record-text">{typeof value==="boolean"?(value?"符合":"未符合"):String(value)}</span>;
}
