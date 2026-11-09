import type {ReactNode} from "react";

export function MemoryContentGate({loading,busy,pending,error,ready,children}:{loading:boolean;busy:boolean;pending:boolean;error:string;ready:boolean;children:ReactNode}) {
  if(loading||busy)return <p role="status">正在核查个人记忆和传播状态，正文暂不可见。</p>;
  if(pending)return <p role="status">原请求尚未核查，个人记忆正文暂不可见。</p>;
  if(error||!ready)return <p role="status">当前个人记忆尚未核查，正文暂不可见。</p>;
  return <>{children}</>;
}
