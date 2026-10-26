import type {OverviewSelection} from "./business-overview-types";

export function readOverviewReference(page:string):OverviewSelection|null{
  const query=new URLSearchParams(window.location.search);
  if(query.get("overviewReturn")!=="N03")return null;
  const stored=query.get("overviewSectorReference");
  if(!stored)return null;
  const value=JSON.parse(stored) as OverviewSelection;
  const expected=page.startsWith("V19-")?"F19":page;
  if(!value||value.page_id!==expected||!value.scope||typeof value.scope.legal_entity_id!=="string"||!value.scope.legal_entity_id||
    !(value.scope.region_id===null||typeof value.scope.region_id==="string")||!value.scope.period_start||!value.scope.period_end||!value.scope.timezone||
    !["ALL","OWNER_INVOLVEMENT","SOURCE_REVIEW"].includes(value.scope.attention)||!(value.use===null||["BROILER","EGG","MILK","BEEF"].includes(value.use))||!/^[a-f0-9]{64}$/.test(value.snapshot_sha256))throw new Error("经营专题入口缺少完整原范围与版本。");
  return value;
}
export function verifyOverviewReference(expected:OverviewSelection|null,received:OverviewSelection|undefined){
  if(!expected)return;
  const keys=["legal_entity_id","region_id","period_start","period_end","timezone","attention"] as const;
  if(!received||received.page_id!==expected.page_id||received.use!==expected.use||received.snapshot_sha256!==expected.snapshot_sha256||!received.scope||keys.some(key=>received.scope[key]!==expected.scope[key]))throw new Error("专题服务尚未确认原经营范围与版本，请返回经营关注重新核查。");
}
export function BusinessOverviewReference({reference}:{reference:OverviewSelection|null}){
  if(!reference)return null;
  return <div className="boss-status" role="status"><div><strong>经营关注原范围</strong><p>{reference.scope.legal_entity_id} · {reference.scope.region_id??"全部获准区域"} · {reference.scope.period_start} 至 {reference.scope.period_end} · {reference.scope.timezone}</p><p className="boss-helper">专题查询与后续操作需要使用同一范围和当前有效资料。返回经营关注可恢复原专题与阅读位置。</p></div></div>;
}
