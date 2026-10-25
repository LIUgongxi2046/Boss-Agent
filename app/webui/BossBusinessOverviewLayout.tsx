import type {ReactNode} from "react";
import "./boss-n03.css";

type Props={scope:ReactNode;topics:ReactNode;details:ReactNode};

export function BossBusinessOverviewLayout({scope,topics,details}:Props){
  return <div className="boss-n03 boss-n03-grid" aria-label="经营关注内容">
    <div className="boss-n03-main">
      <section className="boss-panel" aria-labelledby="business-overview-scope-heading">
        <header className="boss-panel-head"><h2 id="business-overview-scope-heading">经营关注范围</h2></header>
        {scope}
      </section>
      <section className="boss-panel" aria-labelledby="business-overview-topics-heading">
        <header className="boss-panel-head"><h2 id="business-overview-topics-heading">十个经营专题</h2></header>
        {topics}
      </section>
    </div>
    <aside className="boss-n03-aside" aria-label="经营提醒与来源区域">
      <section className="boss-panel" aria-labelledby="business-overview-details-heading">
        <header className="boss-panel-head"><h2 id="business-overview-details-heading">经营提醒与来源</h2></header>
        {details}
      </section>
    </aside>
  </div>;
}
