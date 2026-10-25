"""Rebuild the reviewed Boss-Agent native nanobot integrations from pinned source.

The checked-in .patch files record real native WebUI changes accumulated over
F01/N02/UI02. Apply their ordered changes to an *isolated* pinned nanobot tree;
never mutate the upstream repository or silently drop a failed hunk.
"""
from __future__ import annotations

import hashlib
import json
import re
import subprocess
from pathlib import Path

PATCHES = (
    "nanobot-one-shot.patch",
    "nanobot-today-order.patch",
    "nanobot-mvp-request.patch",
    "nanobot-fc07-request.patch",
    "nanobot-fc04-request.patch",
    "nanobot-ui02-shell.patch",
    "nanobot-menu-f01.patch",
    "nanobot-menu-n02.patch",
    "nanobot-all-menus-routing.patch",
    "nanobot-menu-n03.patch",
)


def sha(content: str) -> str:
    return hashlib.sha256(content.encode("utf-8")).hexdigest()


def pristine(source: Path, path: str) -> str:
    return subprocess.run(
        ["git", "show", "HEAD:" + path], cwd=source,
        capture_output=True, text=True, check=True,
    ).stdout


def patch_blocks(text: str):
    """Parse the repository's context-based *** Update File format."""
    current = None
    hunk = None
    blocks = []

    def flush():
        nonlocal hunk
        if current is not None and hunk is not None:
            current["hunks"].append(hunk)
        hunk = None

    for line in text.split("\n"):
        if line.startswith("*** Update File: "):
            flush()
            path = line[len("*** Update File: "):].strip()
            path = path.removeprefix(".work/product/nanobot/")
            if not path.startswith("webui/"):
                raise RuntimeError("补丁试图修改非固定WebUI路径：" + path)
            current = {"path": path, "hunks": []}
            blocks.append(current)
        elif line.startswith("*** End Patch"):
            flush()
            current = None
        elif line.startswith("@@"):
            flush()
            hunk = {"before": [], "after": []}
        elif current is not None and hunk is not None:
            if line.startswith("+"):
                hunk["after"].append(line[1:])
            elif line.startswith("-"):
                hunk["before"].append(line[1:])
            elif line.startswith(" "):
                hunk["before"].append(line[1:])
                hunk["after"].append(line[1:])
    flush()
    return blocks


def normalize_native_threads(content: str) -> str:
    """Resolve duplicated historic hunks for both *real* native thread panes.

    The historical patches included a pair of ambiguous 'transcriptionEnabled'
    hunks; context-only matching can insert both callbacks on the first pane.
    Assign the callbacks to the actual existing session of each ThreadShell.
    """
    pattern = re.compile(r"(?m)^(?P<prefix>\\s*<ThreadShell\\n)(?P<body>[\\s\\S]*?)^(?P<close>\\s*/>)")
    found = []

    def repair(match):
        body = match.group("body")
        if "session={activeSession}" in body:
            key = 'activeKey??"new-conversation"'
        elif "session={paneSession}" in body:
            key = "paneSession.key"
        else:
            raise RuntimeError("原生会话面板缺少合法session对象")
        lines = body.split("\\n")
        attributes = (
            "persistQueuedPrompts", "composerInputLabel", "composerSubmitLabel",
            "composerAttachmentLabel", "composerPlaceholder", "onDraftController",
            "onReadingController",
        )
        lines = [line for line in lines if not re.match(
            r"^\\s*(?:" + "|".join(attributes) + r")=", line
        )]
        anchor = next((i for i, line in enumerate(lines) if "transcriptionEnabled={false}" in line), None)
        if anchor is None:
            raise RuntimeError("原生页面没有继承暂停语音的声明")
        indent = re.match(r"^\\s*", lines[anchor]).group()
        props = [
            "persistQueuedPrompts={false}",
            'composerInputLabel={role==="BOSS"?"本次消息":undefined}',
            'composerSubmitLabel={role==="BOSS"?"提交需求":undefined}',
            'composerAttachmentLabel={role==="BOSS"?"添加附件":undefined}',
            'composerPlaceholder={role==="BOSS"?"输入问题、补充信息或待执行任务":undefined}',
            f"onDraftController={{controller=>registerNativeDraft({key},controller)}}",
            f"onReadingController={{controller=>registerNativeReading({key},controller)}}",
        ]
        lines[anchor+1:anchor+1] = [indent + value for value in props]
        found.append(key)
        return match.group("prefix") + "\\n".join(lines) + match.group("close")

    result = pattern.sub(repair, content)
    if found != ['activeKey??"new-conversation"', "paneSession.key"]:
        raise RuntimeError("原生会话非预期布局，拒绝修剪历史补丁：" + str(found))
    return result


def normalize_native_composers(content: str) -> str:
    """Both existing ThreadComposer instances require accessible field labels."""
    pattern = re.compile(r"(?m)^(?P<prefix>\\s*<ThreadComposer\\n)(?P<body>[\\s\\S]*?)^(?P<close>\\s*/>)")
    found = []

    def repair(match):
        lines = match.group("body").split("\\n")
        props = ("inputLabel", "submitLabel", "attachmentLabel")
        lines = [line for line in lines if not re.match(
            r"^\\s*(?:" + "|".join(props) + r")=", line
        )]
        anchor = next((i for i, line in enumerate(lines) if "inputAriaLabel={composerInputAriaLabel}" in line), None)
        if anchor is None:
            raise RuntimeError("原生编辑器缺少输入可访问名称的正式来源")
        indent = re.match(r"^\\s*", lines[anchor]).group()
        lines[anchor+1:anchor+1] = [
            indent + "inputLabel={composerInputLabel}",
            indent + "submitLabel={composerSubmitLabel}",
            indent + "attachmentLabel={composerAttachmentLabel}",
        ]
        found.append("session" if "onSend={handleThreadSend}" in match.group("body") else "new")
        return match.group("prefix") + "\\n".join(lines) + match.group("close")

    result = pattern.sub(repair, content)
    if found != ["session", "new"]:
        raise RuntimeError("原生输入框数量与实际流程不符：" + str(found))
    return result


def apply_native_overlay(root: Path, checkout: Path, app_overlay: str, upstream_app: str) -> dict:
    """Validate every source/patch first, then write only reproducible candidates."""
    patch_root = root / "app" / "webui"
    manifest_path = root / ".work" / "product" / "boss-native-patches.json"
    previous = json.loads(manifest_path.read_text(encoding="utf-8")) if manifest_path.is_file() else None

    original: dict[str, str] = {"webui/src/App.tsx": upstream_app}
    candidate: dict[str, str] = {"webui/src/App.tsx": app_overlay}
    patch_hashes = {}
    count = 0
    already_applied = 0
    skipped_copied = 0
    for name in PATCHES:
        source_file = patch_root / name
        source_bytes = source_file.read_bytes()
        patch_hashes[name] = hashlib.sha256(source_bytes).hexdigest()
        for block in patch_blocks(source_bytes.decode("utf-8")):
            path = block["path"]
            if path.startswith("webui/src/boss-agent/"):
                # Those modules are copied in full from app/webui rather than
                # being imported as relative links into a developer worktree.
                copied = checkout / path
                if not copied.is_file():
                    raise FileNotFoundError("缺少已交付第一方模块：" + str(copied))
                skipped_copied += 1
                continue
            if path not in original:
                original[path] = pristine(checkout, path)
                candidate[path] = original[path]
            working = candidate[path]
            for index, hunk in enumerate(block["hunks"]):
                before = "\n".join(hunk["before"])
                after = "\n".join(hunk["after"])
                if not before:
                    raise RuntimeError(f"空旧版本补丁拒绝应用：{name} {path} #{index}")
                offset = working.find(before)
                if offset < 0:
                    if after and after in working:
                        already_applied += 1
                        continue
                    raise RuntimeError(
                        f"缺少固定上游或前置补丁：{name} {path} #{index}: "
                        + before[:100].replace("\n", " / ")
                    )
                working = working[:offset] + after + working[offset + len(before):]
                count += 1
            candidate[path] = working

    candidate["webui/src/App.tsx"] = normalize_native_threads(candidate["webui/src/App.tsx"])
    candidate["webui/src/components/thread/ThreadShell.tsx"] = normalize_native_composers(
        candidate["webui/src/components/thread/ThreadShell.tsx"]
    )

    required = {
        "webui/src/App.tsx": (
            "onStartMorningChat", "BossConversationWorkspace",
            "onCreateTaskConversation", "onReadingController",
            "onRegisterCloseGuard",
        ),
        "webui/src/components/thread/ThreadViewport.tsx": (
            "ThreadReadingPosition", "restoreReadingPosition",
            "captureReadingPosition",
        ),
        "webui/src/components/thread/ThreadShell.tsx": (
            "onReadingController", "onDraftController",
        ),
        "webui/src/lib/nanobot-client.ts": (
            "boss.morning.bind", "boss.conversation.task.prepare",
            "boss.conversation.business.prepare",
        ),
    }
    for path, markers in required.items():
        if path not in candidate or any(marker not in candidate[path] for marker in markers):
            raise RuntimeError("原生功能接收缺少关键消费者：" + path)

    # Fail closed if any independently modified file is present. Previously
    # managed files can only be replaced when the installed SHA still equals
    # the last manifest. This protects local work and repeatable builds.
    for path, rendered in candidate.items():
        target = checkout / path
        current = target.read_text(encoding="utf-8")
        allowed = {original[path], rendered}
        if path == "webui/src/App.tsx":
            allowed.add(app_overlay)
        if previous and previous.get("source_commit") == "1bb712d3488915ca4ed9ccc1a93067ff722f5ab9":
            prior_hash = previous.get("output_sha256", {}).get(path)
            if prior_hash and sha(current) == prior_hash:
                allowed.add(current)
        if current not in allowed:
            raise RuntimeError("已修改原生源码，不能覆盖其它开发内容：" + path)

    for path, rendered in candidate.items():
        target = checkout / path
        target.write_text(rendered, encoding="utf-8")

    manifest = {
        "source_commit": "1bb712d3488915ca4ed9ccc1a93067ff722f5ab9",
        "patches": patch_hashes,
        "output_sha256": {path: sha(value) for path, value in candidate.items()},
        "hunks_applied": count,
        "hunks_already_applied": already_applied,
        "first_party_modules_supplied_by_copy": skipped_copied,
    }
    manifest_path.parent.mkdir(parents=True, exist_ok=True)
    manifest_path.write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    return manifest
