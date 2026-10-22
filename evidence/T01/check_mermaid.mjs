import { readFile } from "node:fs/promises";
import assert from "node:assert/strict";
import { JSDOM } from "../../.planning-checks/node_modules/jsdom/lib/api.js";
import MarkdownIt from "../../.planning-checks/node_modules/markdown-it/index.mjs";

// 仅解析 Markdown 与 Mermaid 语法，不生成或查看图像。
const dom = new JSDOM("");
globalThis.window = dom.window;
globalThis.document = dom.window.document;
const { default: mermaid } = await import("../../.planning-checks/node_modules/mermaid/dist/mermaid.esm.mjs");
mermaid.initialize({ startOnLoad: false, securityLevel: "strict" });
const source = await readFile("docs/PRD.md", "utf8");
const diagrams = new MarkdownIt().parse(source, {}).filter(token => token.type === "fence" && token.info === "mermaid");
assert.equal(diagrams.length, 52);
for (const diagram of diagrams) {
  assert.ok(await mermaid.parse(diagram.content), `Mermaid 语法错误，Markdown 行号 ${diagram.map[0] + 1}`);
}
console.log(JSON.stringify({ parsed_diagrams: diagrams.length, rendered: false, visual: "NOT_RUN" }));
