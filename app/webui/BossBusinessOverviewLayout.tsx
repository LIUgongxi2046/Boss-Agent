import type {ReactNode} from "react";
import "./boss-n03.css";

type Props={scope:ReactNode;topics:ReactNode;details:ReactNode};

export function BossBusinessOverviewLayout({scope,topics,details}:Props){
  return <div className="boss-n03 boss-n03-grid" aria-label="经营关注内容">
    <div className="boss-n03-main">
      <section className="boss-panel" aria-labelledby="business-overview-scope-heading">
        <header className="boss-panel-head"><h2 id="business-overview-scope-heading">查询经营情况</h2></header>
        {scope}
      </section>
      <section className="boss-panel" aria-labelledby="business-overview-topics-heading">
        <header className="boss-panel-head"><h2 id="business-overview-topics-heading">经营数据</h2></header>
        {topics}
      </section>
    </div>
    <aside className="boss-n03-aside" aria-label="Boss Agent 提醒">
      <section className="boss-panel" aria-labelledby="business-overview-details-heading">
        <header className="boss-panel-head"><h2 id="business-overview-details-heading">Boss Agent 提醒</h2></header>
        {details}
      </section>
    </aside>
  </div>;
}
