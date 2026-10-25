import type {ReactNode} from "react";
import {Activity,Bell,CalendarDays,ChartNoAxesCombined,ClipboardCheck,Database,House,MessageCircle,Settings,ShieldCheck} from "lucide-react";
import {deliveredPage,navigationGroups,primaryNavigation,type Role} from "./delivered-navigation";

const icons={F01:House,N02:MessageCircle,N03:ChartNoAxesCombined,N04:CalendarDays,N05:ClipboardCheck,N06:Bell,A01:ShieldCheck,F25:Database,A08:Settings,A15:Activity};
type NavigationProps={role:Role;page:string;expanded:boolean;onNavigate:(page:string)=>void;referenceIcon?:(id:string)=>ReactNode};

export function BossPrimaryNavigation({role,page,expanded,onNavigate,referenceIcon}:NavigationProps){
  const selected=deliveredPage(page,role);
  return <nav className="boss-sidebar-nav" aria-label={role==="BOSS"?"本人全部菜单分组":"维护全部菜单分组"}>
    {primaryNavigation(role).map(({id,title})=>{
      const Icon=icons[id as keyof typeof icons];
      if(!Icon)throw new Error("当前菜单分组缺少图标");
      const active=selected?.group===title;
      return <button type="button" key={id} data-menu-group={id} className={"boss-nav-item "+(active?"active":"")} onClick={()=>onNavigate(id)} title={title} aria-current={active?"page":undefined}>
        {referenceIcon?referenceIcon(id):<Icon size={18} strokeWidth={1.8} aria-hidden="true"/>}{expanded&&<span>{title}</span>}
      </button>;
    })}
  </nav>;
}

export function BossMenuDirectory({role,page,search,onNavigate}:{role:Role;page:string;search:string;onNavigate:(page:string)=>void}){
  const groups=navigationGroups(role,search),count=groups.reduce((total,group)=>total+group.pages.length,0),total=navigationGroups(role).reduce((sum,group)=>sum+group.pages.length,0);
  return <><p>当前身份全部 {total} 个入口，匹配 {count} 个。页面显示当前实现状态，菜单可见不代表完整功能或验收通过。</p>
    <div className="boss-directory-list">{groups.map(group=><section className="boss-directory-group" key={group.title} aria-label={group.title}>
      <h3>{group.title} · {group.pages.length}</h3><div className="boss-directory-list">{group.pages.map(entry=><button type="button" key={entry.id} data-menu-page={entry.id} data-menu-state={entry.state} onClick={()=>onNavigate(entry.id)} className={page===entry.id?"selected":""}>
        <span>{entry.id} · {entry.title}{entry.variantLabel&&" · "+entry.variantLabel}</span><small className={"boss-tag boss-tag-"+(entry.state==="DEVELOPED"?"green":"amber")}>{entry.stateLabel}</small>
      </button>)}</div>
    </section>)}</div>{count===0&&<p role="status">当前身份下无匹配页面。</p>}
  </>;
}
