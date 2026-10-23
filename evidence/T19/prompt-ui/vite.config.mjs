import path from "node:path";
import { fileURLToPath } from "node:url";

const taskProject = fileURLToPath(new URL("../../../", import.meta.url));
const taskModules = path.join(taskProject, ".work/w2-checks/runtime-ui/node_modules");
export default {
  root: fileURLToPath(new URL("./", import.meta.url)),
  esbuild: {jsx: "automatic"},
  resolve: {alias: {
    "@": "/Users/liuhaoxian/.codex/worktrees/boss-integration/Boss-Agent/.work/product/nanobot/webui/src",
    react: path.join(taskModules, "react"), "react-dom": path.join(taskModules, "react-dom"),
    "lucide-react": path.join(taskModules, "lucide-react"),
  }},
  build: {outDir: path.join(taskProject, ".work/w2-checks/prompt-ui/dist"), emptyOutDir: true},
};
