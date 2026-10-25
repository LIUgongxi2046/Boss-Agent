import {createElement} from "react";
import {createRoot} from "react-dom/client";
import {BossPrimaryNavigation,BossMenuDirectory} from "../webui/BossMenuNavigation";
import {menuPageUrl} from "../webui/boss-route";
import {pushBossHistory} from "../webui/boss-history";
import type {Role} from "../webui/delivered-navigation";
export * from "../webui/boss-history";
export * from "../webui/boss-route";
export * from "../webui/delivered-navigation";

export function mountMenu(role:Role,directory=false,search=""){
  const host=document.createElement("main");document.body.replaceChildren(host);
  const root=createRoot(host);
  root.render(createElement(directory?BossMenuDirectory:BossPrimaryNavigation,{role,page:role==="BOSS"?"F01":"A08",expanded:true,search,
    onNavigate:(id:string)=>pushBossHistory(menuPageUrl(window.location.href,id,role))}));
  return()=>root.unmount();
}
