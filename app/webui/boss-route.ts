import {deliveredPage,type Role} from "./delivered-navigation";

export function bossPageId(value:string,role:Role):string{return role==="BOSS"&&value==="NATIVE"?"N02":value;}
export function readBossLocation(url:URL,role:Role){
  const selected=bossPageId(url.searchParams.get("bossPage")??(role==="BOSS"?"F01":"A08"),role);
  const returned=bossPageId(url.searchParams.get("bossReturn")??(role==="BOSS"?"F01":"A08"),role);
  return{page:deliveredPage(selected,role)?selected:"UNAVAILABLE",returnPage:deliveredPage(returned,role)?returned:role==="BOSS"?"F01":"A08",
    taskId:url.searchParams.get("bossTask")??"",sourceId:url.searchParams.get("bossSource")??"finance-note",sopId:url.searchParams.get("bossSop")??""};
}
export function menuPageUrl(address:string,id:string,role:Role):URL{
  const page=bossPageId(id,role);
  if(!deliveredPage(page,role))throw new Error("当前身份没有此菜单入口");
  const url=new URL(address);
  for(const key of ["bossReturn","bossConversationReturn","bossSource","bossTask","bossSop","bossEvent","bossEventVersion","overviewReturn","overviewQuerySnapshot"])url.searchParams.delete(key);
  url.searchParams.set("bossPage",page);
  return url;
}
