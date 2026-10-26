import os
import json

from aiohttp import web


def validate_namespace(value):
    if not isinstance(value, str) or not 1 <= len(value) <= 160 or not value.isascii():
        raise ValueError("执行空间标识无效")
    if not all(character.isalnum() or character in "-_:." for character in value):
        raise ValueError("执行空间标识包含无效字符")
    if value in {".", "..", "dataset-catalog"} or value.startswith("dataset-candidate:"):
        raise ValueError("当前服务不能绑定资料目录或候选空间")
    return value


NAMESPACE = validate_namespace(os.environ.get("BOSS_EXECUTION_NAMESPACE", "ui-check"))


def require_dataset_scope(db, namespace, initial):
    from business import checksum, require
    require(initial["owner_id"] == "boss-1" and initial["source_type"] == "SIMULATED",
            "当前资料不属于获准本人及模拟范围", web.HTTPForbidden)
    if initial["dataset_id"] == "selection":
        require(initial["dataset_version"] == "1", "初始资料版本不符", web.HTTPForbidden)
        return
    record = db.execute("SELECT body FROM objects WHERE namespace='dataset-catalog' AND kind='dataset_definition' AND id=?",
                        (initial["dataset_id"],)).fetchone()
    manifest = db.execute("SELECT body FROM objects WHERE namespace=? AND kind='execution_space' AND id='current'",
                          (namespace,)).fetchone()
    require(record is not None and manifest is not None, "数据集缺少生成来源或执行空间登记", web.HTTPForbidden)
    definition, binding = json.loads(record[0]), json.loads(manifest[0])
    require(definition["version"] == initial["dataset_version"] and definition["facts_sha256"] == checksum(definition["facts"])
            and binding["namespace"] == namespace and binding["dataset_id"] == initial["dataset_id"]
            and binding["dataset_version"] == initial["dataset_version"] and binding["facts_sha256"] == definition["facts_sha256"],
            "数据集来源、版本或空间登记不一致", web.HTTPForbidden)
