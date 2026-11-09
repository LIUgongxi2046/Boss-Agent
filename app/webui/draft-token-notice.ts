import {useEffect, useRef, useState} from "react";

export function useTokenChangeDraftNotice(token: string, dirty: boolean) {
  const previous = useRef({token, dirty: false});
  const [notice, setNotice] = useState("");
  const changed = previous.current.token !== token;
  useEffect(() => {
    const before = previous.current;
    if (changed && before.dirty) setNotice("认证令牌已更新。上一条未保存的纪要或申请内容已随页面重建清除；服务目前不能证明同一认证会话，未自动恢复。");
    previous.current = {token, dirty};
  }, [token, dirty, changed]);
  return {notice, dismiss: () => setNotice("")};
}
