import path from "node:path";
import {mergeConfig} from "../../.work/product/nanobot/webui/node_modules/vite/dist/node/index.js";
import base from "../../.work/upgrade2-u2-07/vite-full-source.config.mts";

export default mergeConfig(base, {
  build: {
    outDir: path.resolve(__dirname, "../../.work/upgrade2-u2-07/vite-chat-budget-export"),
    rollupOptions: {preserveEntrySignatures: "strict"},
  },
});
