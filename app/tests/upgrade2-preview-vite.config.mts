import path from "node:path";
import { fileURLToPath } from "node:url";
import { defineConfig, mergeConfig } from "../../.work/product/nanobot/webui/node_modules/vite/dist/node/index.js";
import upstream from "../../.work/product/nanobot/webui/vite.config.ts";

const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "../..");
const product = path.join(root, "app/webui");

export default defineConfig(async (environment) => {
  const configuration = typeof upstream === "function" ? await upstream(environment) : upstream;
  return mergeConfig(configuration, {
    resolve: {
      alias: [
        { find: /^@\/boss-agent\//, replacement: `${product}/` },
        { find: /^\.\/boss-agent\//, replacement: `${product}/` },
        { find: /^yaml$/, replacement: path.join(root, "app/frontend/node_modules/yaml/browser/index.js") },
        { find: /^diff$/, replacement: path.join(root, "app/frontend/node_modules/diff/libesm/index.js") },
        { find: /^ajv\//, replacement: path.join(root, "app/frontend/node_modules/ajv/") },
        { find: /^ajv-formats$/, replacement: path.join(root, "app/frontend/node_modules/ajv-formats/dist/index.js") },
        { find: /^luxon$/, replacement: path.join(root, "app/frontend/node_modules/luxon/src/luxon.js") },
      ],
    },
    build: { outDir: path.join(root, ".work/upgrade2/u2-01/preview-dist-001"), emptyOutDir: false },
  });
});
