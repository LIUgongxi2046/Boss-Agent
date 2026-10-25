import { createRoot } from "react-dom/client";
import { MaintainerMemoryStatus } from "../../../app/webui/MaintainerMemoryStatus";
import { MaintainerRuntimeRecords } from "../../../app/webui/MaintainerRuntimeRecords";
import "../../../app/webui/boss-v6.css";

const root = document.getElementById("root");
if (!root) throw Error("缺少页面根元素");
const getToken = () => document.querySelector<HTMLMetaElement>('meta[name="maintainer-token"]')?.content ?? "";
const parameters = new URLSearchParams(window.location.search);
createRoot(root).render(parameters.get("page") === "A15" ?
  <MaintainerRuntimeRecords getToken={getToken} initialRunId={parameters.get("run_id") ?? undefined}/> :
  <MaintainerMemoryStatus getToken={getToken} onNavigate={(page, reference) => {
    const target = new URLSearchParams({page});
    if (reference) target.set("run_id", reference.run_id);
    window.location.assign("/?" + target.toString());
  }}/>);
