import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";
import path from "node:path";
import tailwindcss from "tailwindcss";
import autoprefixer from "autoprefixer";
import fs from "node:fs";
import { createHash } from "node:crypto";

const upstream = process.env.BOSS_UPSTREAM_WEBUI;
if (!upstream) throw new Error("需要指定已核查的上游前端源码路径");
const project = path.resolve("../../..");
const variant = process.env.BOSS_T27_BUILD_VARIANT ?? "default";
if (!["default", "native-zoom", "review", "review-flight", "review-natural"].includes(variant)) throw new Error("构建目标无效");
const isolatedBuild = variant !== "default";
const zoomDirectory = path.join(project, `.work/t27-${variant}`);
const inputs = [path.join(project, "app/webui/BossLogin.tsx"), path.join(project, "app/webui/boss-login.css"),
  path.resolve("main.tsx"), path.join(upstream, "src/App.tsx"), path.join(upstream, "src/boss-agent/BossDesktop.tsx")];
const digest = (file: string) => createHash("sha256").update(fs.readFileSync(file)).digest("hex");
let buildSources: Record<string, string> = {};
const theme = await import(path.join(upstream, "tailwind.config.js"));
export default defineConfig({ build: { outDir: isolatedBuild ? path.join(zoomDirectory, "dist") : "dist", emptyOutDir: true }, plugins: [
  { name: "boss-zoom-build-identity", apply: "build", buildStart() {
    if (isolatedBuild) buildSources = Object.fromEntries(inputs.map(file => [file, digest(file)]));
  }, closeBundle() {
    if (!isolatedBuild) return;
    for (const [file, sha256] of Object.entries(buildSources)) if (digest(file) !== sha256) throw new Error("构建期间来源文件发生变化");
    fs.mkdirSync(zoomDirectory, { recursive: true });
    fs.writeFileSync(path.join(zoomDirectory, "build-source.json"), JSON.stringify(buildSources, null, 2));
  } },
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
