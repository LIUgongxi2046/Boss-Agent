import {readFileSync} from "node:fs";
import {parse} from "../../.work/upgrade2-u2-07/yaml-dependency/node_modules/yaml/dist/index.js";

const source = new URL("../../data/simulation/supply-quality-v1.yaml", import.meta.url);
process.stdout.write(JSON.stringify(parse(readFileSync(source,"utf8"),{merge:true})));
