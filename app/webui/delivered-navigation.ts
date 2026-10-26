import designPages from "../../Boss-Agent-Desktop-Complete-v7/meta/页面配置.json";

export type Role="BOSS"|"MAINTAINER";
type FeatureReference={title:string;feature:string;directory:boolean};
export type NavigationEntry={id:string;title:string;group:string;feature:string;directory:boolean;state:"DEVELOPED"|"IN_PROGRESS"|"PARTIAL"|"PAUSED"|"AUTHENTICATION";stateLabel:string;accepted:false;variantLabel:string|null};
type PrimaryEntry={id:string;title:string};
const FEATURE_REFERENCES:Record<Role,Record<string,FeatureReference>>={
  BOSS:{
    NATIVE:{title:"聊天交办",feature:"MENU-N02",directory:false},
    N02:{title:"聊天交办",feature:"MENU-N02",directory:true},
    F08:{title:"消息编辑",feature:"MENU-N02_SHARED",directory:false},
    F01:{title:"今日工作",feature:"MENU-F01",directory:true},
    MVP01:{title:"采购成本协调",feature:"MVP01",directory:true},
    F03:{title:"经营查询与追问",feature:"FC02",directory:true},
    F14:{title:"原料与饲料报告",feature:"FC01",directory:true},
    F21:{title:"食品与品质报告",feature:"FC01",directory:true},
    F02:{title:"经营提醒",feature:"FC04",directory:true},
    F06:{title:"交办管理",feature:"FC07",directory:true},
    N05:{title:"任务与承诺",feature:"FC07",directory:true},
    N06:{title:"通知中心",feature:"FC04",directory:true},
    N08:{title:"本人通知设置",feature:"FC04",directory:true},
    N09:{title:"本人计划",feature:"FC04",directory:true},
    N03:{title:"经营关注",feature:"MENU-N03",directory:true},
    D01:{title:"来源原文",feature:"SHARED_DELIVERED",directory:false},
    D04:{title:"选择负责人",feature:"FC07",directory:false},
    D05:{title:"选择时间",feature:"FC07",directory:false},
    D06:{title:"未保存内容保护",feature:"SHARED_DELIVERED",directory:false},
    D07:{title:"访问权限",feature:"SHARED_DELIVERED",directory:false},
  },
  MAINTAINER:{
    NATIVE:{title:"应用设置",feature:"UI02",directory:true},
    A03:{title:"模拟业务资料",feature:"FC01_MVP01",directory:true},
    A04:{title:"查询场景与交办反馈",feature:"FC02_FC07_FC04",directory:true},
    A08:{title:"模型运行配置",feature:"SHARED_DELIVERED",directory:true},
    A13:{title:"调度与经营规则",feature:"FC04",directory:true},
    A15:{title:"运行记录",feature:"SHARED_DELIVERED",directory:true},
  },
};
const PRIMARY_NAVIGATION:Record<Role,PrimaryEntry[]>={
  BOSS:[{id:"F01",title:"今日工作"},{id:"N02",title:"聊天交办"},{id:"N03",title:"经营关注"},{id:"N04",title:"会议与资料"},{id:"N05",title:"任务与承诺"},{id:"N06",title:"通知与设置"}],
  MAINTAINER:[{id:"A01",title:"档案与访问"},{id:"F25",title:"模拟中心"},{id:"A08",title:"Agent配置"},{id:"A15",title:"运行与评测"}],
};
const PUBLIC_GROUP="公共状态与登录";
const SHARED_PAGES=new Set(["D06","D07"]);
const AUTHENTICATION_PAGES=new Set(["N01","D08"]);
const VARIANTS:Record<string,string>={"V19-EGG":"蛋禽","V19-MILK":"奶畜","V19-BEEF":"肉用牛羊"};
const STATE_LABELS:Record<NavigationEntry["state"],string>={DEVELOPED:"已开发，待用户验收",IN_PROGRESS:"开发中，完整菜单待验收",PARTIAL:"已有实现，完整功能待验收",PAUSED:"语音暂停",AUTHENTICATION:"认证状态入口"};

export const DELIVERED_NAVIGATION:Record<Role,Record<string,NavigationEntry>>={BOSS:{},MAINTAINER:{}};
for(const role of ["BOSS","MAINTAINER"] as const){
  for(const [id,metadata] of Object.entries(designPages)){
    const authentication=AUTHENTICATION_PAGES.has(id);
    if(!authentication&&!SHARED_PAGES.has(id)&&(metadata.technical?"MAINTAINER":"BOSS")!==role)continue;
    const group=PRIMARY_NAVIGATION[role].some(item=>item.title===metadata.module)?metadata.module:PUBLIC_GROUP;
    const state:NavigationEntry["state"]=authentication?"AUTHENTICATION":id==="F27"?"PAUSED":["F01","N02"].includes(id)?"DEVELOPED":id==="N03"?"IN_PROGRESS":"PARTIAL";
    DELIVERED_NAVIGATION[role][id]={id,title:metadata.title,group,feature:FEATURE_REFERENCES[role][id]?.feature??"PARTIAL_PAGE_BINDING",directory:true,state,stateLabel:STATE_LABELS[state],accepted:false,variantLabel:VARIANTS[id]??null};
  }
}
DELIVERED_NAVIGATION.BOSS.MVP01={id:"MVP01",title:"采购成本协调",group:"今日工作",feature:"MVP01",directory:false,state:"DEVELOPED",stateLabel:STATE_LABELS.DEVELOPED,accepted:false,variantLabel:null};
DELIVERED_NAVIGATION.BOSS.NATIVE={...DELIVERED_NAVIGATION.BOSS.N02,id:"NATIVE",directory:false};
const BOSS_DIRECTORY=new Set(["F01","N02","N03","F02","F03","F14","F21","N04","N05","N06","N08","N09"]);
for(const [id,entry] of Object.entries(DELIVERED_NAVIGATION.BOSS))entry.directory=BOSS_DIRECTORY.has(id);
DELIVERED_NAVIGATION.MAINTAINER.NATIVE={id:"NATIVE",title:"应用设置",group:"Agent配置",feature:"UI02",directory:true,state:"DEVELOPED",stateLabel:STATE_LABELS.DEVELOPED,accepted:false,variantLabel:null};

export function deliveredPage(page:string,role:Role,_mvp=false):NavigationEntry|undefined{
  if(role!=="BOSS"&&role!=="MAINTAINER")return undefined;
  return Object.hasOwn(DELIVERED_NAVIGATION[role],page)?DELIVERED_NAVIGATION[role][page]:undefined;
}
export function primaryNavigation(role:Role):readonly PrimaryEntry[]{return PRIMARY_NAVIGATION[role];}
export function navigationGroups(role:Role,search=""): {title:string;pages:NavigationEntry[]}[]{
  const filter=search.trim().toLocaleLowerCase(),entries=Object.values(DELIVERED_NAVIGATION[role]).filter(entry=>entry.directory);
  return [...PRIMARY_NAVIGATION[role].map(item=>item.title),PUBLIC_GROUP].map(title=>({title,pages:entries.filter(entry=>entry.group===title&&(!filter||[entry.id,entry.title,entry.group,entry.variantLabel??"",entry.stateLabel].some(value=>value.toLocaleLowerCase().includes(filter))))})).filter(group=>group.pages.length>0);
}
