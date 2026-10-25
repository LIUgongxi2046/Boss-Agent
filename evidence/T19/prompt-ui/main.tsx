import { useMemo, useState } from "react";
import { createRoot } from "react-dom/client";
import { ClientProvider } from "@/providers/ClientProvider";
import { NanobotClient } from "@/lib/nanobot-client";
import { MaintainerPromptVersion } from "../../../app/webui/MaintainerPromptVersion";
import "../../../app/webui/boss-v6.css";

function Check() {
  const [token, setToken] = useState(() => document.querySelector<HTMLMetaElement>('meta[name="maintainer-token"]')?.content ?? "");
  const [error, setError] = useState("");
  const client = useMemo(() => new NanobotClient({url: location.origin.replace("http", "ws"), reconnect: false}), []);
  function revoke() {
    void fetch("/component/session/revoke", {method: "POST", headers: {Authorization: "Bearer " + token}})
      .then(response => {
        if (!response.ok) throw Error("本机验证会话撤销失败");
        setToken("");
      }).catch(failure => setError(failure instanceof Error ? failure.message : String(failure)));
  }
  return <ClientProvider client={client} token={token}>
    <section aria-label="验证会话控制"><button type="button" onClick={revoke}>撤销本次维护会话</button>
      <p role="status">{token ? "Provider token 已提供" : "Provider token 已清除"}</p>{error && <p role="alert">{error}</p>}
    </section>
    <MaintainerPromptVersion onNavigate={page => {document.title = page;}}/>
  </ClientProvider>;
}
const root = document.getElementById("root");
if (!root) throw Error("缺少页面根元素");
createRoot(root).render(<Check/>);
