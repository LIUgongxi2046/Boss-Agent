import hashlib
import json
import zipfile
from datetime import datetime
from pathlib import Path
from uuid import UUID

from hermes_bridge import validate_engine_inventory, verify_engine_archive


REQUIRED_ARTIFACTS = ("engine-source", "guest-runtime", "adapter", "isolation-profile")
EXPECTED_ENGINE_SHA256 = "2902bae7c50d1a93b10cc7a42042dc0c54a40f8b665de91b54e88553f20cff7b"


def _read_json(path):
    if not path.is_absolute() or path.is_symlink() or not path.is_file():
        return None
    info = path.stat()
    if info.st_mode & 0o022:
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


def _verify_artifact(entry, blockers):
    name = entry.get("name") if isinstance(entry, dict) else None
    path = entry.get("path") if isinstance(entry, dict) else None
    digest = entry.get("sha256") if isinstance(entry, dict) else None
    if not isinstance(name, str) or not isinstance(path, str) or not isinstance(digest, str) or len(digest) != 64:
        blockers.append("DEPLOYMENT_MANIFEST_ENTRY_INVALID")
        return None
    artifact = Path(path)
    if not artifact.is_absolute() or artifact.is_symlink() or not artifact.is_file():
        blockers.append("DEPLOYMENT_ARTIFACT_MISSING:" + name)
        return None
    if artifact.stat().st_mode & 0o022:
        blockers.append("DEPLOYMENT_ARTIFACT_PERMISSION:" + name)
        return None
    try:
        if hashlib.sha256(artifact.read_bytes()).hexdigest() != digest:
            blockers.append("DEPLOYMENT_ARTIFACT_DIGEST:" + name)
            return None
    except OSError:
        blockers.append("DEPLOYMENT_ARTIFACT_MISSING:" + name)
        return None
    return artifact.resolve()


def _wheel_module_digests(artifact):
    with zipfile.ZipFile(artifact) as archive:
        names = archive.namelist()
        if len(names) != len(set(names)):
            raise ValueError("运行包包含重复文件")
        return {name: hashlib.sha256(archive.read(name)).hexdigest() for name in names if name.endswith(".py") and "/" not in name}


def _expected_install_modules(verified):
    modules = _wheel_module_digests(verified["guest-runtime"])
    adapter = _wheel_module_digests(verified["adapter"])
    if set(modules).intersection(adapter):
        raise ValueError("运行包与适配器模块重名")
    return {**modules, **adapter}


def verify_guest_install_evidence(evidence_path, manifest_path, verified):
    if evidence_path is None:
        return ["RUNTIME_INSTALL_ASSOCIATION_UNVERIFIED"]
    document = _read_json(Path(evidence_path))
    if not isinstance(document, dict) or set(document) != {"boot_id", "captured_at", "console_log", "console_log_sha256", "manifest_sha256", "modules", "wheels"}:
        return ["GUEST_INSTALL_EVIDENCE_INVALID"]
    try:
        boot_id = str(UUID(document["boot_id"]))
        datetime.fromisoformat(document["captured_at"])
    except (TypeError, ValueError):
        return ["GUEST_INSTALL_EVIDENCE_INVALID"]
    if boot_id != document["boot_id"]:
        return ["GUEST_INSTALL_EVIDENCE_INVALID"]
    try:
        manifest_digest = hashlib.sha256(Path(manifest_path).read_bytes()).hexdigest()
    except OSError:
        return ["GUEST_INSTALL_EVIDENCE_MANIFEST_MISMATCH"]
    if not isinstance(document["manifest_sha256"], str) or manifest_digest != document["manifest_sha256"]:
        return ["GUEST_INSTALL_EVIDENCE_MANIFEST_MISMATCH"]
    wheels = document["wheels"]
    if not isinstance(wheels, dict) or set(wheels) != {"guest-runtime", "adapter"}:
        return ["GUEST_INSTALL_EVIDENCE_INVALID"]
    for name in wheels:
        if hashlib.sha256(verified[name].read_bytes()).hexdigest() != wheels[name]:
            return ["GUEST_INSTALL_EVIDENCE_WHEEL_MISMATCH:" + name]
    try:
        expected = _expected_install_modules(verified)
    except (OSError, ValueError):
        return ["GUEST_INSTALL_EVIDENCE_INVALID"]
    if not isinstance(document["modules"], dict) or document["modules"] != expected:
        return ["GUEST_INSTALL_EVIDENCE_MODULE_MISMATCH"]
    if not isinstance(document["console_log"], str):
        return ["GUEST_INSTALL_EVIDENCE_INVALID"]
    console = Path(document["console_log"])
    if not console.is_absolute() or console.is_symlink() or not console.is_file() or console.stat().st_mode & 0o022:
        return ["GUEST_INSTALL_EVIDENCE_CONSOLE_MISSING"]
    try:
        transcript = console.read_text(encoding="utf-8", errors="replace")
        console_digest = hashlib.sha256(console.read_bytes()).hexdigest()
    except OSError:
        return ["GUEST_INSTALL_EVIDENCE_CONSOLE_MISSING"]
    if console_digest != document["console_log_sha256"] or "GUEST_INSTALL_EVIDENCE_OK" not in transcript or "GUEST_BOOT_ID " + document["boot_id"] not in transcript:
        return ["GUEST_INSTALL_EVIDENCE_CONSOLE_MISMATCH"]
    for name, digest in expected.items():
        if "GUEST_MODULE_SHA256 " + name + " " + digest not in transcript:
            return ["GUEST_INSTALL_EVIDENCE_CONSOLE_MISMATCH"]
    return []


def _linux_isolation_properties():
    return {
        "NoNewPrivileges": "yes",
        "ProtectSystem": "strict",
        "ProtectHome": "yes",
        "ProtectControlGroups": "yes",
        "PrivateUsers": "yes",
        "PrivateDevices": "yes",
        "PrivateIPC": "yes",
        "PrivateNetwork": "yes",
        "RestrictSUIDSGID": "yes",
        "Delegate": "no",
        "ExitType": "cgroup",
        "KillMode": "control",
        "ProtectProc": "invisible",
        "ProcSubset": "pid",
    }


def verify_linux_isolation_evidence(profile_path, evidence_path, verified):
    profile = _read_json(Path(profile_path))
    if not isinstance(profile, dict) or set(profile) != {"profile_id", "platform", "mechanism", "guest_systemd_sha256", "properties"}:
        return ["LINUX_ISOLATION_PROFILE_INVALID"]
    expected = _linux_isolation_properties()
    if profile["platform"] != "linux" or profile["mechanism"] != "SYSTEMD_SERVICE_AND_CGROUP" or profile["properties"] != expected:
        return ["LINUX_ISOLATION_PROFILE_INVALID"]
    try:
        guest_digest = _wheel_module_digests(verified["guest-runtime"])["hermes_guest_systemd.py"]
    except (KeyError, OSError, ValueError):
        return ["LINUX_ISOLATION_PROFILE_INVALID"]
    if profile["guest_systemd_sha256"] != guest_digest:
        return ["LINUX_ISOLATION_PROFILE_INVALID"]
    document = _read_json(Path(evidence_path))
    if not isinstance(document, dict) or set(document) != {"profile_id", "boot_id", "unit", "captured_at", "properties", "network"}:
        return ["LINUX_ISOLATION_EVIDENCE_INVALID"]
    try:
        boot_id = str(UUID(document["boot_id"]))
        datetime.fromisoformat(document["captured_at"])
    except (TypeError, ValueError):
        return ["LINUX_ISOLATION_EVIDENCE_INVALID"]
    if boot_id != document["boot_id"] or document["profile_id"] != profile["profile_id"] or not isinstance(document["unit"], str) or not document["unit"].startswith("isolation-probe-"):
        return ["LINUX_ISOLATION_EVIDENCE_INVALID"]
    if document["properties"] != expected:
        return ["LINUX_ISOLATION_EVIDENCE_MISMATCH"]
    network = document["network"]
    if not isinstance(network, dict) or set(network) != {"addresses", "routes", "non_loopback_interfaces"}:
        return ["LINUX_ISOLATION_EVIDENCE_INVALID"]
    if network["routes"] or network["non_loopback_interfaces"] or not isinstance(network["addresses"], list) or not network["addresses"] or any(" lo:" not in item for item in network["addresses"]):
        return ["LINUX_ISOLATION_EVIDENCE_EGRESS"]
    return []


def verify_deployment_authorization(authorization_path, manifest_path, deployment):
    if authorization_path is None:
        return ["DEPLOYMENT_AUTHORIZATION_UNVERIFIED", "MODEL_EXECUTION_AUTHORIZED_UNVERIFIED", "EXTERNAL_NETWORK_EGRESS_UNVERIFIED", "DESCENDANT_EXIT_UNVERIFIED"]
    document = _read_json(Path(authorization_path))
    if not isinstance(document, dict) or set(document) != {"authorization_id", "authorized_by", "granted_at", "statement", "scope", "model", "engine_archive_sha256", "manifest_sha256"}:
        return ["DEPLOYMENT_AUTHORIZATION_INVALID"]
    try:
        datetime.fromisoformat(document["granted_at"])
    except (TypeError, ValueError):
        return ["DEPLOYMENT_AUTHORIZATION_INVALID"]
    if document["authorized_by"] != "BOSS_USER" or not isinstance(document["authorization_id"], str) or not document["authorization_id"].strip() or not isinstance(document["statement"], str) or not document["statement"].strip():
        return ["DEPLOYMENT_AUTHORIZATION_INVALID"]
    blockers = []
    scope = document["scope"]
    required = {"formal_deployment": True, "model_execution": True, "linux_isolation": "SYSTEMD_SERVICE_AND_CGROUP",
                "network_egress": "NO_VM_NETWORK_AND_PRIVATE_NETNS", "descendant_exit": "SYSTEMD_CGROUP_EXIT"}
    if not isinstance(scope, dict) or set(scope) != set(required):
        return ["DEPLOYMENT_AUTHORIZATION_INVALID"]
    if scope.get("formal_deployment") is not True:
        blockers.append("DEPLOYMENT_AUTHORIZATION_UNVERIFIED")
    if scope.get("model_execution") is not True:
        blockers.append("MODEL_EXECUTION_AUTHORIZED_UNVERIFIED")
    if scope.get("linux_isolation") != required["linux_isolation"]:
        blockers.append("ISOLATION_PROFILE_PLATFORM_UNVERIFIED")
    if scope.get("network_egress") != required["network_egress"]:
        blockers.append("EXTERNAL_NETWORK_EGRESS_UNVERIFIED")
    if scope.get("descendant_exit") != required["descendant_exit"]:
        blockers.append("DESCENDANT_EXIT_UNVERIFIED")
    model = document["model"]
    if not isinstance(model, dict) or set(model) != {"provider", "model_id", "base_url", "max_requests_per_run", "max_output_tokens"}:
        blockers.append("MODEL_EXECUTION_AUTHORIZED_UNVERIFIED")
    else:
        if (model["provider"], model["model_id"], model["base_url"]) != ("deepseek", "deepseek-flash", "https://api.deepseek.com"):
            blockers.append("MODEL_EXECUTION_AUTHORIZED_UNVERIFIED")
        if type(model["max_requests_per_run"]) is not int or model["max_requests_per_run"] <= 0 or type(model["max_output_tokens"]) is not int or model["max_output_tokens"] <= 0:
            blockers.append("MODEL_EXECUTION_AUTHORIZED_UNVERIFIED")
    if document["engine_archive_sha256"] != EXPECTED_ENGINE_SHA256:
        blockers.append("DEPLOYMENT_AUTHORIZATION_ENGINE_MISMATCH")
    try:
        manifest_digest = hashlib.sha256(Path(manifest_path).read_bytes()).hexdigest()
    except OSError:
        manifest_digest = None
    if document["manifest_sha256"] != manifest_digest:
        blockers.append("DEPLOYMENT_AUTHORIZATION_MANIFEST_MISMATCH")
    if deployment.offline is False and not isinstance(deployment.provider_key, str):
        blockers.append("MODEL_EXECUTION_AUTHORIZED_UNVERIFIED")
    return blockers


def verify_model_execution_authorization(authorization_path, manifest_path, deployment):
    if deployment.offline or not isinstance(deployment.provider_key, str) or not deployment.provider_key.strip():
        return False
    return not verify_deployment_authorization(authorization_path, manifest_path, deployment)


def verify_deployment_manifest(manifest_path, deployment):
    blockers = []
    if manifest_path is None:
        return ["DEPLOYMENT_ARTIFACT_MANIFEST_MISSING"]
    path = Path(manifest_path)
    document = _read_json(path)
    if not isinstance(document, dict) or set(document) != {"artifacts"} or not isinstance(document["artifacts"], list):
        return ["DEPLOYMENT_ARTIFACT_MANIFEST_INVALID"]
    entries = document["artifacts"]
    names = [entry.get("name") for entry in entries if isinstance(entry, dict)]
    if any(not isinstance(name, str) or name not in REQUIRED_ARTIFACTS for name in names) or len(set(names)) != len(names) or set(names) != set(REQUIRED_ARTIFACTS):
        return ["DEPLOYMENT_ARTIFACT_MANIFEST_INVALID"]
    verified = {}
    for entry in entries:
        artifact = _verify_artifact(entry, blockers)
        if artifact is not None:
            verified[entry["name"]] = artifact
    if blockers:
        return blockers
    if verified["engine-source"] != Path(deployment.source_archive).resolve():
        blockers.append("DEPLOYMENT_ENGINE_SOURCE_MISMATCH")
    if verified["isolation-profile"] != Path(deployment.isolation_profile).resolve():
        blockers.append("DEPLOYMENT_ISOLATION_PROFILE_MISMATCH")
    try:
        with verified["engine-source"].open("rb") as archive_file:
            expected_files, expected_dirs = verify_engine_archive(archive_file, Path(deployment.engine_dir), EXPECTED_ENGINE_SHA256)
        validate_engine_inventory(Path(deployment.engine_dir), expected_files, expected_dirs)
    except (OSError, ValueError):
        blockers.append("DEPLOYMENT_ENGINE_ARCHIVE_UNVERIFIED")
    blockers.extend(verify_guest_install_evidence(deployment.guest_install_evidence, path, verified))
    if deployment.isolation_evidence is None:
        blockers.append("ISOLATION_PROFILE_PLATFORM_UNVERIFIED")
    else:
        blockers.extend(verify_linux_isolation_evidence(verified["isolation-profile"], deployment.isolation_evidence, verified))
    return blockers
