import { existsSync, lstatSync, readFileSync, realpathSync, writeFileSync } from "node:fs";
import { createHash } from "node:crypto";
import { createRequire } from "node:module";
import path from "node:path";
import { fileURLToPath, pathToFileURL } from "node:url";
import { gzipSync } from "node:zlib";

const project = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "../..");
const requiredNode = readFileSync(path.join(project, "app/frontend/.node-version"), "utf8").trim();
if (process.versions.node !== requiredNode) {
  throw new Error(`Node 版本不符合构建要求：需要 ${requiredNode}，当前 ${process.versions.node}`);
}
if (!process.env.BOSS_FRONTEND_UPSTREAM || !process.env.BOSS_FRONTEND_DEPENDENCIES || !process.env.BOSS_FRONTEND_OUTPUT || !path.isAbsolute(process.env.BOSS_FRONTEND_OUTPUT)) {
  throw new Error("必须提供上游源码、依赖目录和绝对输出目录");
}
const upstream = realpathSync(process.env.BOSS_FRONTEND_UPSTREAM);
const dependencies = realpathSync(process.env.BOSS_FRONTEND_DEPENDENCIES);
const output = path.resolve(process.env.BOSS_FRONTEND_OUTPUT);
const outputParent = realpathSync(path.dirname(output));
const outputTarget = path.join(outputParent, path.basename(output));
const work = realpathSync(path.join(project, ".work"));
if (outputParent !== work && !outputParent.startsWith(`${work}${path.sep}`)) {
  throw new Error("构建输出必须位于项目独立目录");
}
if (realpathSync(process.cwd()) !== realpathSync(path.join(upstream, "webui"))) {
  throw new Error("构建必须从上游 webui 目录执行");
}
if (lstatSync(output, { throwIfNoEntry: false })) throw new Error("构建输出目录已存在");
if (!readFileSync(path.join(project, "app/frontend/package-lock.json")).equals(readFileSync(path.join(dependencies, "package-lock.json")))) {
  throw new Error("依赖目录的锁文件与产品锁文件不一致");
}
if (realpathSync(path.join(upstream, "webui/node_modules")) !== realpathSync(path.join(dependencies, "node_modules"))) {
  throw new Error("上游 Vite 依赖目录与锁定依赖不一致");
}
if (outputTarget === project || project.startsWith(`${outputTarget}${path.sep}`) || outputTarget === upstream || upstream.startsWith(`${outputTarget}${path.sep}`) || outputTarget.startsWith(`${upstream}${path.sep}`) || outputTarget === dependencies || dependencies.startsWith(`${outputTarget}${path.sep}`) || outputTarget.startsWith(`${dependencies}${path.sep}`)) {
  throw new Error("输出目录不能覆盖源码目录");
}
const requireDependency = createRequire(path.join(dependencies, "package.json"));
const vite = await import(pathToFileURL(path.join(path.dirname(requireDependency.resolve("vite/package.json")), "dist/node/index.js")).href);
const react = (await import(pathToFileURL(path.join(path.dirname(requireDependency.resolve("@vitejs/plugin-react")), "index.js")).href)).default;
const product = path.join(project, "app/webui");
const assets = ["boss-logo-from-reference.png", "dapeng-front.png", "dapeng-side.png", "dapeng-think.png", "dapeng-execute.png"];
const animations = ["01-待机悬浮.webp", "02-语音倾听.webp", "03-思考分析.webp", "04-执行推进.webp", "05-完成确认.webp", "06-通知提醒.webp"];

function manualChunk(id) {
  const locale = /\/webui\/locales\/([^/]+)\.json$/.exec(id)?.[1]
    ?? /\/src\/i18n\/locales\/([^/]+)\/common\.json$/.exec(id)?.[1];
  if (locale) return `locale-${locale}`;
  if (id.endsWith("/src/lib/clipboard.ts")) return "clipboard";
  if (id.endsWith("/src/lib/markdown-math.ts") || id.includes("node_modules/rehype-katex/") ||
      (id.includes("node_modules/micromark-extension-math/") && id.endsWith("/html.js"))) return "markdown-math";
  if (["node_modules/react/", "node_modules/react-dom/", "node_modules/scheduler/", "node_modules/clsx/", "vite/preload-helper"].some(value => id.includes(value))) return "react-vendor";
  if (id.includes("node_modules/refractor/lang/")) return;
  if (id.includes("node_modules/streamdown/dist/mermaid-")) return "markdown-diagrams";
  if (id.includes("node_modules/streamdown/dist/highlighted-body-")) return "markdown-code";
  if (["node_modules/react-syntax-highlighter", "node_modules/refractor/core", "node_modules/hast-util-parse-selector"].some(value => id.includes(value))) return "syntax-highlight";
  if (["node_modules/streamdown", "node_modules/remend", "node_modules/remark-", "node_modules/rehype-", "node_modules/unified", "node_modules/mdast-", "node_modules/hast-", "node_modules/micromark", "node_modules/unist-"].some(value => id.includes(value))) return "markdown-vendor";
  if (id.includes("node_modules/katex")) return "katex";
}

function guardEntryChunk() {
  return {
    name: "nanobot-guard-webui-entry-chunk", apply: "build",
    generateBundle(_options, bundle) {
      for (const item of Object.values(bundle)) {
        if (item.type !== "chunk" || !item.isEntry) continue;
        const unexpected = item.imports.filter(name => ["markdown-vendor-", "syntax-highlight-", "katex-"].some(prefix => path.basename(name).startsWith(prefix)));
        if (unexpected.length) throw new Error(`WebUI entry chunk statically imports lazy features: ${unexpected.join(", ")}`);
      }
    },
  };
}

function gzipAssets() {
  return {
    name: "nanobot-gzip-webui-assets", apply: "build",
    writeBundle(options, bundle) {
      const directory = options.dir ?? (options.file ? path.dirname(options.file) : undefined);
      if (!directory) throw new Error("WebUI gzip build requires a Rollup output directory");
      for (const name of Object.keys(bundle)) {
        if (!/\.(?:css|html|js|json|mjs|svg)$/i.test(name)) continue;
        const target = path.resolve(directory, name);
        const bytes = readFileSync(target);
        if (bytes.byteLength < 4096) continue;
        const compressed = gzipSync(bytes, { level: 9 });
        if (compressed.byteLength < bytes.byteLength) writeFileSync(`${target}.gz`, compressed);
      }
    },
  };
}

export default async (environment) => {
  const upstreamConfig = readFileSync(path.join(upstream, "webui/vite.config.ts"));
  if (createHash("sha256").update(upstreamConfig).digest("hex") !== "c207f5bcaa1cd988edd94db6a438c0a197ba17e44a54f5bf89c0b8ced5e437a6") {
    throw new Error("上游 Vite 配置与受控内容不一致");
  }
  for (const name of [".env", ".env.local", `.env.${environment.mode}`, `.env.${environment.mode}.local`]) {
    if (existsSync(path.join(upstream, "webui", name))) throw new Error("上游目录包含环境配置，拒绝读取");
  }
  const env = vite.loadEnv(environment.mode, process.cwd(), "");
  const tailwind = (await import(pathToFileURL(path.join(upstream, "webui/tailwind.config.js")).href)).default;
  if (!Array.isArray(tailwind.content)) throw new Error("固定上游 Tailwind 输入配置无效");
  return {
    root: path.join(upstream, "webui"),
    css: { postcss: { plugins: [
      requireDependency("tailwindcss")({ ...tailwind, content: [...tailwind.content, `${product}/**/*.{ts,tsx}`] }),
      requireDependency("autoprefixer")(),
    ] } },
    resolve: { alias: [
      { find: /^@\/boss-agent\//, replacement: `${product}/` },
      { find: /^\.\/boss-agent\//, replacement: `${product}/` },
      { find: "@", replacement: path.join(upstream, "webui/src") },
    ], dedupe: ["react", "react-dom", "lucide-react", "react-i18next", "qrcode", "@radix-ui/react-dialog"] },
    optimizeDeps: { include: ["@radix-ui/react-dialog"] },
    plugins: [react(), guardEntryChunk(), gzipAssets(), {
      name: "boss-independent-inputs",
      async resolveId(id, importer) {
        if (!importer || !importer.startsWith(`${product}${path.sep}`) || id.startsWith(".") || id.startsWith("/") || id.startsWith("@/")) return null;
        return this.resolve(id, path.join(dependencies, "package.json"), { skipSelf: true });
      },
      generateBundle() {
        for (const name of assets) this.emitFile({ type: "asset", fileName: `boss-brand/${name}`, source: readFileSync(path.join(project, "Boss-Agent-Desktop-Complete-v7/assets", name)) });
        for (const name of animations) this.emitFile({ type: "asset", fileName: `boss-brand/${name}`, source: readFileSync(path.join(project, "Boss-Agent-Desktop-Complete-v7/animation", name)) });
        this.emitFile({ type: "asset", fileName: "boss-brand/boss-flight-sprite.png", source: readFileSync(path.join(project, "design/T27/assets/boss-flight-sprite.png")) });
      },
    }],
    build: { outDir: output, emptyOutDir: false, manifest: "asset-manifest.json", sourcemap: false, commonjsOptions: { strictRequires: true }, rollupOptions: { output: { manualChunks: manualChunk } } },
    server: {
      host: "127.0.0.1", port: 5173, strictPort: true,
      fs: { allow: [upstream, product, dependencies] }, hmr: { host: "127.0.0.1", path: "/__nanobot_vite_hmr" },
      proxy: Object.fromEntries(["/webui", "/api", "/auth"].map(key => [key, { target: env.NANOBOT_API_URL ?? "http://127.0.0.1:8765", changeOrigin: true }])),
    },
    test: { environment: "happy-dom", globals: true, setupFiles: ["./src/tests/setup.ts"], coverage: { provider: "v8", include: ["src/**/*.{ts,tsx}"], exclude: ["src/tests/**", "src/**/*.d.ts"], reporter: ["text", "json-summary"], thresholds: { statements: 85, branches: 80, functions: 80, lines: 85 } } },
  };
};
