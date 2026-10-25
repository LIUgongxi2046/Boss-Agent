import { createRoot } from "react-dom/client";
import { MaintainerRuntimeRecords } from "../../../app/webui/MaintainerRuntimeRecords";
import "../../../app/webui/boss-v6.css";

const root = document.getElementById("root");
if (!root) throw Error("缺少页面根元素");
const getToken = () => document.querySelector<HTMLMetaElement>('meta[name="maintainer-token"]')?.content ?? "";
createRoot(root).render(<MaintainerRuntimeRecords getToken={getToken}/>);
