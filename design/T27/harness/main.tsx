import { createRoot } from "react-dom/client";
import App from "@upstream/App";
import "@upstream/globals.css";
import { initializeI18n } from "@upstream/i18n";
import { initializeLoopbackRuntimeHost } from "@upstream/lib/runtime";

initializeLoopbackRuntimeHost();
async function main() {
  await initializeI18n();
  const root = document.getElementById("root");
  if (!root) throw new Error("缺少应用根容器");
  createRoot(root).render(<App/>);
}
void main();
