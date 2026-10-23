import { useEffect, useState } from "react";
import { createRoot } from "react-dom/client";
import { BossLogin, bossFetchBootstrap, bossClearSavedSecret } from "../../../app/webui/BossLogin";

function App() {
  const [role, setRole] = useState("");
  const [expired, setExpired] = useState(false);
  const [token, setToken] = useState("");
  const [socket, setSocket] = useState<WebSocket | null>(null);
  const [error, setError] = useState("");
  async function authenticate(value: string) {
    const boot = await bossFetchBootstrap("", value);
    const result = await fetch("/api/boss/identity", { headers: { Authorization: "Bearer " + boot.api_token } });
    if (!result.ok) throw new Error("认证身份不可用");
    setRole((await result.json()).role);
    setToken(boot.api_token!);
    sessionStorage.setItem("t27-session", boot.api_token!);
    const ws = new WebSocket(`ws://${location.host}${boot.ws_path}?token=${encodeURIComponent(boot.token!)}`);
    setSocket(ws);
    ws.addEventListener("message", event => {
      const value = JSON.parse(event.data);
      if (value.request_id === "t27-ui-logout" && value.ok) {
        sessionStorage.removeItem("t27-session"); bossClearSavedSecret(); setRole(""); setToken(""); ws.close();
      }
    });
    ws.addEventListener("error", () => setError("会话连接失败"));
  }
  useEffect(() => {
    const value = sessionStorage.getItem("t27-session");
    if (value) void authenticate(value).then(undefined, () => {
      sessionStorage.removeItem("t27-session"); bossClearSavedSecret(); setExpired(true);
    });
  }, []);
  return role ? <main data-role={role}><h1>已认证身份：{role}</h1><p role="status">真实 nanobot 认证连接</p>
    <button onClick={() => {
      if (socket?.readyState !== WebSocket.OPEN || !token) throw new Error("会话尚未准备完成");
      socket.send(JSON.stringify({ type: "webui_request", action: "boss.auth.logout", request_id: "t27-ui-logout", payload: {} }));
    }}>退出登录</button>{error && <p role="alert">{error}</p>}</main>
    : <BossLogin expired={expired} onSecret={value => { void authenticate(value); }}/>;
}

createRoot(document.getElementById("root")!).render(<App/>);
