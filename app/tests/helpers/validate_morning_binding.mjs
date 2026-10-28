import {readFileSync} from "node:fs";
import assert from "node:assert/strict";
import {validateMorningBindingReceipt} from "../../webui/morning-binding-recovery.ts";

const receipt=JSON.parse(readFileSync(0,"utf8"));
assert.equal(validateMorningBindingReceipt(receipt,receipt.client_request_id),receipt);
