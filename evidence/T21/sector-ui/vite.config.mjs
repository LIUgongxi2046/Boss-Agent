import path from "node:path";
import { fileURLToPath } from "node:url";
const project=fileURLToPath(new URL("../../../",import.meta.url));
const modules=path.join(project,".work/w2-checks/runtime-ui/node_modules");
export default {
  root:fileURLToPath(new URL("./",import.meta.url)),esbuild:{jsx:"automatic"},
  resolve:{alias:{"@":"/Users/liuhaoxian/.codex/worktrees/boss-integration/Boss-Agent/.work/product/nanobot/webui/src",
    react:path.join(modules,"react"),"react-dom":path.join(modules,"react-dom"),"lucide-react":path.join(modules,"lucide-react")}},
  build:{outDir:path.join(project,".work/w2-checks/sector-ui/dist"),emptyOutDir:true},
};
