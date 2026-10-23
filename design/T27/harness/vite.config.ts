import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";
import path from "node:path";
import tailwindcss from "tailwindcss";
import autoprefixer from "autoprefixer";

const upstream = process.env.BOSS_UPSTREAM_WEBUI;
if (!upstream) throw new Error("需要指定已核查的上游前端源码路径");
const project = path.resolve("../../..");
const theme = await import(path.join(upstream, "tailwind.config.js"));
export default defineConfig({ plugins: [
  { name: "boss-login-source", enforce: "pre", resolveId(source) {
    if (source === "./boss-agent/BossLogin") return path.join(project, "app/webui/BossLogin.tsx");
  } }, react()], css: { postcss: { plugins: [tailwindcss({ ...theme.default,
    content: [path.join(upstream, "src/**/*.{ts,tsx}"), path.join(upstream, "../nanobot/channels/*/webui/**/*.{ts,tsx}"), path.join(project, "app/webui/**/*.{ts,tsx}")],
  }), autoprefixer()] } }, resolve: { alias: {
  "@upstream": path.join(upstream, "src"),
  "@": path.join(upstream, "src"),
  react: path.resolve("node_modules/react"),
  "react-dom": path.resolve("node_modules/react-dom"),
  "lucide-react": path.resolve("node_modules/lucide-react"),
}, dedupe: ["react", "react-dom", "react-i18next", "lucide-react"] } });
