import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";
import path from "node:path";

const upstream = process.env.BOSS_UPSTREAM_WEBUI;
if (!upstream) throw new Error("需要指定已核查的上游前端源码路径");
export default defineConfig({ plugins: [react()], resolve: { alias: {
  "@": path.join(upstream, "src"),
  react: path.resolve("node_modules/react"),
  "react-dom": path.resolve("node_modules/react-dom"),
  "lucide-react": path.resolve("node_modules/lucide-react"),
} } });
