type Role="BOSS"|"MAINTAINER";
type Entry={title:string;feature:string;directory:boolean};
export const DELIVERED_NAVIGATION:Record<Role,Record<string,Entry>>={
  BOSS:{
    NATIVE:{title:"大鹏会话",feature:"UI02",directory:true},
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
    N03:{title:"经营查询与追问",feature:"FC02",directory:false},
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
export function deliveredPage(page:string,role:Role,mvp=false):Entry|undefined{
  if(mvp&&!(role==="BOSS"?["F01"]:["A03","A08","A15"]).includes(page))return undefined;
  return DELIVERED_NAVIGATION[role][page];
}
