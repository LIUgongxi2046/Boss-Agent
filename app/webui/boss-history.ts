type BrowserWindow=Window&typeof globalThis;
const POSITION="bossHistoryPosition";
const PUSH="boss-history-push";
const controllers=new WeakMap<Window,{suppressed:boolean}>();

function position(target:BrowserWindow):number{
  const value=target.history.state?.[POSITION];
  if(!Number.isSafeInteger(value)||value<0)throw new Error("页面历史记录缺少有效位置");
  return value;
}
export function ensureBossHistory(target:BrowserWindow=window):void{
  if(target.history.state?.[POSITION]===undefined)target.history.replaceState({...target.history.state,[POSITION]:0},"",target.location.href);
  position(target);
}
export function pushBossHistory(url:URL|string,target:BrowserWindow=window):void{
  ensureBossHistory(target);
  target.history.pushState({[POSITION]:position(target)+1},"",url);
  target.dispatchEvent(new target.Event(PUSH));
}
export function replaceBossHistory(url:URL|string,target:BrowserWindow=window):void{
  ensureBossHistory(target);
  target.history.replaceState(target.history.state,"",url);
}
export function bossHistorySuppressed(target:Window=window):boolean{return controllers.get(target)?.suppressed===true;}

// 页面离开需要确认时，沿原历史记录往返；批准后继续原次移动。
export function bindBossHistory(target:BrowserWindow,beforeTravel:(url:URL,proceed:()=>void)=>void,apply:(url:URL)=>void){
  ensureBossHistory(target);
  let current=position(target),sequence=0;
  type Movement={delta:number;destination:number;url:URL;sequence:number;approved:boolean;phase:"RESTORING"|"WAITING"|"REPLAYING"};
  let pending:Movement|null=null;
  const controller={suppressed:false};controllers.set(target,controller);
  const pushed=()=>{current=position(target);sequence++;pending=null;controller.suppressed=false;};
  const popped=()=>{
    const destination=position(target),url=new URL(target.location.href);
    if(pending?.phase==="RESTORING"){
      const movement=pending;
      if(destination!==current)throw new Error("页面历史没有返回确认来源");
      controller.suppressed=true;
      movement.phase="WAITING";
      if(movement.approved){movement.phase="REPLAYING";target.history.go(movement.delta);}
      return;
    }
    if(pending?.phase==="REPLAYING"){
      if(destination!==pending.destination)throw new Error("页面历史没有进入批准的目的位置");
      pending=null;current=destination;controller.suppressed=false;apply(url);return;
    }
    pending=null;
    const delta=destination-current;
    if(delta===0){controller.suppressed=false;apply(url);return;}
    const movement:Movement={delta,destination,url,sequence:++sequence,approved:false,phase:"RESTORING"};
    let immediate=true,committed=false;
    beforeTravel(url,()=>{
      if(sequence!==movement.sequence)return;
      if(immediate){committed=true;current=destination;controller.suppressed=false;apply(url);}
      else{movement.approved=true;if(movement.phase==="WAITING"){movement.phase="REPLAYING";target.history.go(delta);}}
    });
    immediate=false;
    if(committed)return;
    controller.suppressed=true;
    pending=movement;
    target.history.go(-delta);
  };
  target.addEventListener(PUSH,pushed);
  target.addEventListener("popstate",popped,true);
  return()=>{sequence++;target.removeEventListener(PUSH,pushed);target.removeEventListener("popstate",popped,true);controllers.delete(target);};
}
