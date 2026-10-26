import {useState, type ReactNode} from "react";
import {Activity,Bell,CalendarDays,ChartNoAxesCombined,ChevronDown,ClipboardCheck,Database,House,MessageCircle,Settings,ShieldCheck} from "lucide-react";
import {deliveredPage,navigationGroups,primaryNavigation,type Role} from "./delivered-navigation";

const icons={F01:House,N02:MessageCircle,N03:ChartNoAxesCombined,N04:CalendarDays,N05:ClipboardCheck,N06:Bell,A01:ShieldCheck,F25:Database,A08:Settings,A15:Activity};
type NavigationProps={role:Role;page:string;expanded:boolean;onNavigate:(page:string)=>void;referenceIcon?:(id:string)=>ReactNode};

export function BossPrimaryNavigation({role,page,expanded,onNavigate,referenceIcon}:NavigationProps){
  const selected=deliveredPage(page,role);
  const groups=navigationGroups(role);
  const [openGroups,setOpenGroups]=useState<string[]>([]);
  return <nav className="boss-sidebar-nav" aria-label={role==="BOSS"?"本人全部菜单分组":"维护全部菜单分组"}>
    {primaryNavigation(role).map(({id,title})=>{
      const Icon=icons[id as keyof typeof icons];
      if(!Icon)throw new Error("当前菜单分组缺少图标");
      const active=selected?.group===title;
      const open=openGroups.includes(id);
      const pages=groups.find(group=>group.title===title)?.pages??[];
      const single=pages.length<=1;
      const target=single&&pages[0]?pages[0].id:id;
      return <section className="boss-nav-group" key={id} aria-label={title}><div className="boss-nav-group-heading"><button type="button" data-menu-group={id} className={"boss-nav-item "+(active?"active":"")} onClick={()=>onNavigate(target)} title={title} aria-current={active?"page":undefined}>
        {referenceIcon?referenceIcon(id):<Icon size={18} strokeWidth={1.8} aria-hidden="true"/>}{expanded&&<span>{title}</span>}
      </button>{expanded&&!single&&<button type="button" className="boss-nav-disclosure" aria-label={(open?"收起":"展开")+title+"页面"} aria-expanded={open} aria-controls={"boss-navigation-"+id} onClick={()=>setOpenGroups(current=>open?current.filter(value=>value!==id):[...current,id])}><ChevronDown size={14}/></button>}</div>{expanded&&!single&&<div id={"boss-navigation-"+id} className="boss-nav-pages" hidden={!open}>{pages.map(entry=><MenuPage key={entry.id} entry={entry} page={page} onNavigate={onNavigate}/>)}</div>}</section>;
    })}
  </nav>;
}

function MenuPage({entry,page,onNavigate}:{entry:NonNullable<ReturnType<typeof deliveredPage>>;page:string;onNavigate:(id:string)=>void}){
  return <button type="button" data-menu-page={entry.id} data-menu-state={entry.state} className={"boss-nav-page "+(page===entry.id?"selected":"")} onClick={()=>onNavigate(entry.id)} title={entry.title} aria-current={page===entry.id?"location":undefined}><span>{entry.title}{entry.variantLabel&&" · "+entry.variantLabel}</span>{entry.state==="PAUSED"&&<small>语音服务暂停</small>}</button>;
}

export function BossMenuDirectory({role,page,search,onNavigate}:{role:Role;page:string;search:string;onNavigate:(page:string)=>void}){
  const groups=navigationGroups(role,search),count=groups.reduce((total,group)=>total+group.pages.length,0),total=navigationGroups(role).reduce((sum,group)=>sum+group.pages.length,0);
  return <><p>当前身份共有 {total} 个入口，找到 {count} 个匹配页面。</p>
    <div className="boss-directory-list">{groups.map(group=><section className="boss-directory-group" key={group.title} aria-label={group.title}>
      <h3>{group.title} · {group.pages.length}</h3><div className="boss-directory-list">{group.pages.map(entry=><button type="button" key={entry.id} data-menu-page={entry.id} data-menu-state={entry.state} onClick={()=>onNavigate(entry.id)} className={page===entry.id?"selected":""}>
        <span>{entry.title}{entry.variantLabel&&" · "+entry.variantLabel}</span><small className="boss-tag boss-tag-muted">{entry.state==="PAUSED"?"语音服务暂停":entry.id}</small>
      </button>)}</div>
    </section>)}</div>{count===0&&<p role="status">当前身份下无匹配页面。</p>}
  </>;
}
