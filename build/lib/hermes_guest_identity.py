import grp
import hashlib
import json
import os
import pwd
import sqlite3
import stat
import subprocess
import sys
from pathlib import Path
from uuid import UUID


def identity_for_run(run_id):
    if not isinstance(run_id, str) or str(UUID(run_id)) != run_id:
        raise ValueError("客体运行编号无效")
    name = "ba" + run_id.replace("-", "")[:28]
    uid = 600000 + int.from_bytes(hashlib.sha256(run_id.encode("ascii")).digest()[:8], "big") % 1000000
    return name, uid


def require_persistent_guest_storage(directory):
    if sys.platform != "linux" or os.geteuid() != 0:
        raise ValueError("客体身份存储需要 Linux 系统管理权限")
    directory = Path(directory)
    if directory != Path("/var/lib/boss-vm/identities") or directory.resolve(strict=True) != directory:
        raise ValueError("客体身份存储路径不可核查")
    mounts = []
    for target in (directory, Path("/etc")):
        result = subprocess.run(["/usr/bin/findmnt", "--json", "--target", str(target), "--output", "SOURCE,FSTYPE,OPTIONS"],
                                check=True, capture_output=True, text=True, timeout=15)
        entries = json.loads(result.stdout)["filesystems"]
        if len(entries) != 1 or entries[0]["fstype"] != "ext4" or "rw" not in entries[0]["options"].split(","):
            raise ValueError("客体身份存储需要可写持久文件系统")
        mounts.append(entries[0]["source"])
    if mounts[0] != mounts[1]:
        raise ValueError("客体账号与登记存储不在同一文件系统")


class IdentityConnection(sqlite3.Connection):
    def __exit__(self, exc_type, exc, traceback):
        try:
            return super().__exit__(exc_type, exc, traceback)
        finally:
            self.close()


class HermesGuestIdentityRegistry:
    def __init__(self, directory):
        directory = Path(directory)
        if not directory.is_absolute() or directory.resolve(strict=True) != directory or not directory.is_dir():
            raise ValueError("客体身份目录不可核查")
        info = directory.stat()
        if info.st_uid != os.getuid() or info.st_mode & 0o077:
            raise ValueError("客体身份目录权限无效")
        self.path = directory / "identities.sqlite"
        descriptor = os.open(self.path, os.O_RDWR | os.O_CREAT | os.O_NOFOLLOW, 0o600)
        try:
            info = os.fstat(descriptor)
            if not stat.S_ISREG(info.st_mode) or info.st_uid != os.getuid() or info.st_mode & 0o077 or info.st_nlink != 1:
                raise ValueError("客体身份数据库权限无效")
        finally:
            os.close(descriptor)
        with self.connect() as db:
            version = db.execute("PRAGMA user_version").fetchone()[0]
            if version == 0:
                if db.execute("SELECT 1 FROM sqlite_master WHERE type IN ('table','trigger') LIMIT 1").fetchone() is not None:
                    raise ValueError("客体身份数据库未初始化")
                db.executescript("BEGIN IMMEDIATE; CREATE TABLE guest_identities (run_id TEXT PRIMARY KEY, account TEXT NOT NULL UNIQUE, uid INTEGER NOT NULL UNIQUE, state TEXT NOT NULL CHECK(state IN ('RESERVED','READY'))); CREATE TRIGGER guest_identities_no_delete BEFORE DELETE ON guest_identities BEGIN SELECT RAISE(ABORT,'guest identity is immutable'); END; CREATE TRIGGER guest_identities_guard BEFORE UPDATE ON guest_identities WHEN NEW.run_id IS NOT OLD.run_id OR NEW.account IS NOT OLD.account OR NEW.uid IS NOT OLD.uid OR OLD.state != 'RESERVED' OR NEW.state != 'READY' BEGIN SELECT RAISE(ABORT,'guest identity transition is invalid'); END; PRAGMA user_version=1; COMMIT;")
                version = 1
            if version == 1:
                db.executescript("BEGIN IMMEDIATE; CREATE TABLE guest_control (run_id TEXT NOT NULL, epoch INTEGER NOT NULL CHECK(epoch>0), boot_id TEXT NOT NULL, request_digest TEXT, unit TEXT NOT NULL, state TEXT NOT NULL CHECK(state IN ('RESERVED','STOPPED')), PRIMARY KEY(run_id,epoch), CHECK((state='RESERVED' AND request_digest IS NOT NULL) OR state='STOPPED')); CREATE TRIGGER guest_control_no_delete BEFORE DELETE ON guest_control BEGIN SELECT RAISE(ABORT,'guest control is immutable'); END; CREATE TRIGGER guest_control_guard BEFORE UPDATE ON guest_control WHEN NEW.run_id IS NOT OLD.run_id OR NEW.epoch IS NOT OLD.epoch OR NEW.boot_id IS NOT OLD.boot_id OR NEW.request_digest IS NOT OLD.request_digest OR NEW.unit IS NOT OLD.unit OR OLD.state != 'RESERVED' OR NEW.state != 'STOPPED' BEGIN SELECT RAISE(ABORT,'guest control transition is invalid'); END; PRAGMA user_version=2; COMMIT;")
                version = 2
            if version == 2:
                db.executescript("BEGIN IMMEDIATE; CREATE TABLE guest_exit_receipts (run_id TEXT NOT NULL, epoch INTEGER NOT NULL, boot_id TEXT NOT NULL, unit TEXT NOT NULL, state TEXT NOT NULL CHECK(state='UNKNOWN'), cpu_ns INTEGER CHECK(cpu_ns IS NULL), PRIMARY KEY(run_id,epoch), FOREIGN KEY(run_id,epoch) REFERENCES guest_control(run_id,epoch)); CREATE TRIGGER guest_exit_receipts_no_update BEFORE UPDATE ON guest_exit_receipts BEGIN SELECT RAISE(ABORT,'guest exit receipt is immutable'); END; CREATE TRIGGER guest_exit_receipts_no_delete BEFORE DELETE ON guest_exit_receipts BEGIN SELECT RAISE(ABORT,'guest exit receipt is immutable'); END; PRAGMA user_version=3; COMMIT;")
                version = 3
            if version == 3:
                db.executescript("BEGIN IMMEDIATE; CREATE TABLE guest_exit_observations (run_id TEXT NOT NULL, epoch INTEGER NOT NULL, boot_id TEXT NOT NULL, unit TEXT NOT NULL, invocation TEXT NOT NULL, unit_state TEXT NOT NULL, control_group TEXT NOT NULL, cpu_ns INTEGER NOT NULL CHECK(cpu_ns>=0), kill_mode TEXT NOT NULL, result TEXT NOT NULL, PRIMARY KEY(run_id,epoch), FOREIGN KEY(run_id,epoch) REFERENCES guest_exit_receipts(run_id,epoch)); CREATE TRIGGER guest_exit_observations_no_update BEFORE UPDATE ON guest_exit_observations BEGIN SELECT RAISE(ABORT,'guest exit observation is immutable'); END; CREATE TRIGGER guest_exit_observations_no_delete BEFORE DELETE ON guest_exit_observations BEGIN SELECT RAISE(ABORT,'guest exit observation is immutable'); END; PRAGMA user_version=4; COMMIT;")
                version = 4
            if version != 4:
                raise ValueError("客体身份数据库版本不可核查")

    def connect(self):
        db = sqlite3.connect(self.path.as_uri() + "?mode=rw", uri=True, timeout=15, factory=IdentityConnection)
        db.execute("PRAGMA foreign_keys=ON")
        return db

    def reserve(self, run_id):
        name, uid = identity_for_run(run_id)
        with self.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            row = db.execute("SELECT account,uid,state FROM guest_identities WHERE run_id=?", (run_id,)).fetchone()
            if row is not None:
                if row[:2] != (name, uid):
                    raise ValueError("客体账号映射已经变化")
                return row
            if any(item.pw_name == name or item.pw_uid == uid for item in pwd.getpwall()) or any(item.gr_name == name or item.gr_gid == uid for item in grp.getgrall()):
                raise ValueError("客体账号编号已经被占用")
            db.execute("INSERT INTO guest_identities VALUES (?,?,?,'RESERVED')", (run_id, name, uid))
            return name, uid, "RESERVED"

    @staticmethod
    def _control_identity(run_id, epoch, boot_id):
        identity_for_run(run_id)
        if type(epoch) is not int or epoch <= 0 or not isinstance(boot_id, str) or str(UUID(boot_id)) != boot_id:
            raise ValueError("客体控制身份无效")
        return "boss-" + run_id + "-" + str(epoch) + ".service"

    def reserve_start(self, run_id, epoch, boot_id, request_digest):
        unit = self._control_identity(run_id, epoch, boot_id)
        if not isinstance(request_digest, str) or len(request_digest) != 64 or any(character not in "0123456789abcdef" for character in request_digest):
            raise ValueError("客体请求摘要无效")
        with self.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            row = db.execute("SELECT boot_id,request_digest,unit,state FROM guest_control WHERE run_id=? AND epoch=?", (run_id, epoch)).fetchone()
            if row is not None:
                if row != (boot_id, request_digest, unit, "RESERVED"):
                    raise ValueError("客体启动请求已经变化或停止")
                return unit, False
            db.execute("INSERT INTO guest_control VALUES (?,?,?,?,?,'RESERVED')", (run_id, epoch, boot_id, request_digest, unit))
            return unit, True

    def mark_stopped(self, run_id, epoch, boot_id):
        unit = self._control_identity(run_id, epoch, boot_id)
        with self.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            row = db.execute("SELECT boot_id,unit,state FROM guest_control WHERE run_id=? AND epoch=?", (run_id, epoch)).fetchone()
            if row is None:
                db.execute("INSERT INTO guest_control VALUES (?,?,?,NULL,?,'STOPPED')", (run_id, epoch, boot_id, unit))
                return unit, False
            if row[:2] != (boot_id, unit):
                raise ValueError("客体停止身份已经变化")
            if row[2] == "RESERVED":
                db.execute("UPDATE guest_control SET state='STOPPED' WHERE run_id=? AND epoch=?", (run_id, epoch))
            return unit, True

    def read_control(self, run_id, epoch, boot_id):
        unit = self._control_identity(run_id, epoch, boot_id)
        with self.connect() as db:
            row = db.execute("SELECT boot_id,unit,state FROM guest_control WHERE run_id=? AND epoch=?", (run_id, epoch)).fetchone()
            if row is None or row[:2] != (boot_id, unit):
                raise ValueError("客体运行身份不可核查")
            return row[2]

    def record_unknown_exit(self, run_id, epoch, boot_id):
        unit = self._control_identity(run_id, epoch, boot_id)
        with self.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            row = db.execute("SELECT boot_id,unit,state FROM guest_control WHERE run_id=? AND epoch=?", (run_id, epoch)).fetchone()
            if row != (boot_id, unit, "STOPPED"):
                raise ValueError("客体退出身份不可核查")
            db.execute("INSERT INTO guest_exit_receipts VALUES (?,?,?,?,'UNKNOWN',NULL) ON CONFLICT(run_id,epoch) DO NOTHING", (run_id, epoch, boot_id, unit))
            saved = db.execute("SELECT boot_id,unit,state,cpu_ns FROM guest_exit_receipts WHERE run_id=? AND epoch=?", (run_id, epoch)).fetchone()
            if saved != (boot_id, unit, "UNKNOWN", None):
                raise ValueError("客体退出记录已经变化")
            return {"run_id": run_id, "epoch": epoch, "boot_id": boot_id, "unit": unit, "state": "UNKNOWN", "cpu_ns": None}

    def read_exit(self, run_id, epoch, boot_id):
        unit = self._control_identity(run_id, epoch, boot_id)
        with self.connect() as db:
            row = db.execute("SELECT boot_id,unit,state,cpu_ns FROM guest_exit_receipts WHERE run_id=? AND epoch=?", (run_id, epoch)).fetchone()
            if row != (boot_id, unit, "UNKNOWN", None):
                raise ValueError("客体退出记录不可核查")
            return {"run_id": run_id, "epoch": epoch, "boot_id": boot_id, "unit": unit, "state": "UNKNOWN", "cpu_ns": None}

    def record_exit_observation(self, run_id, epoch, boot_id, observation):
        unit = self._control_identity(run_id, epoch, boot_id)
        if not isinstance(observation, dict) or set(observation) != {"id", "state", "control_group", "invocation", "cpu_ns", "kill_mode", "result"}:
            raise ValueError("客体退出观察字段无效")
        invocation = observation["invocation"]
        if observation["id"] != unit or observation["state"] not in {"inactive", "failed"} or observation["kill_mode"] != "control-group" or not isinstance(invocation, bytes) or len(invocation) != 16 or not any(invocation) or type(observation["cpu_ns"]) is not int or not 0 <= observation["cpu_ns"] < 2**63 or not isinstance(observation["control_group"], str) or not isinstance(observation["result"], str):
            raise ValueError("客体退出观察不可核查")
        values = (run_id, epoch, boot_id, unit, invocation.hex(), observation["state"], observation["control_group"], observation["cpu_ns"], observation["kill_mode"], observation["result"])
        with self.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            row = db.execute("SELECT boot_id,unit,state,cpu_ns FROM guest_exit_receipts WHERE run_id=? AND epoch=?", (run_id, epoch)).fetchone()
            if row != (boot_id, unit, "UNKNOWN", None):
                raise ValueError("客体退出记录不可核查")
            db.execute("INSERT INTO guest_exit_observations VALUES (?,?,?,?,?,?,?,?,?,?) ON CONFLICT(run_id,epoch) DO NOTHING", values)
            saved = db.execute("SELECT run_id,epoch,boot_id,unit,invocation,unit_state,control_group,cpu_ns,kill_mode,result FROM guest_exit_observations WHERE run_id=? AND epoch=?", (run_id, epoch)).fetchone()
            if saved != values:
                raise ValueError("客体退出观察已经变化")
        return {"run_id": run_id, "epoch": epoch, "boot_id": boot_id, "unit": unit, "invocation": invocation.hex(), "unit_state": observation["state"], "control_group": observation["control_group"], "cpu_ns": observation["cpu_ns"], "kill_mode": observation["kill_mode"], "result": observation["result"], "state": "UNKNOWN"}

    def read_exit_observation(self, run_id, epoch, boot_id):
        unit = self._control_identity(run_id, epoch, boot_id)
        with self.connect() as db:
            row = db.execute("SELECT boot_id,unit,invocation,unit_state,control_group,cpu_ns,kill_mode,result FROM guest_exit_observations WHERE run_id=? AND epoch=?", (run_id, epoch)).fetchone()
        if row is None or row[:2] != (boot_id, unit):
            raise ValueError("客体退出观察不可核查")
        return {"run_id": run_id, "epoch": epoch, "boot_id": row[0], "unit": row[1], "invocation": row[2], "unit_state": row[3], "control_group": row[4], "cpu_ns": row[5], "kill_mode": row[6], "result": row[7], "state": "UNKNOWN"}

    def ensure(self, run_id):
        if sys.platform != "linux" or os.geteuid() != 0:
            raise ValueError("客体账号配置需要 Linux 系统管理权限")
        name, uid, state = self.reserve(run_id)
        groups = [item for item in grp.getgrall() if item.gr_name == name or item.gr_gid == uid]
        accounts = [item for item in pwd.getpwall() if item.pw_name == name or item.pw_uid == uid]
        if len(groups) > 1 or len(accounts) > 1 or groups and (groups[0].gr_name != name or groups[0].gr_gid != uid or groups[0].gr_mem) or accounts and (accounts[0].pw_name != name or accounts[0].pw_uid != uid or accounts[0].pw_gid != uid or accounts[0].pw_dir != "/nonexistent" or accounts[0].pw_shell != "/usr/sbin/nologin"):
            raise ValueError("客体账号或用户组与记录不匹配")
        if state == "READY" and (not groups or not accounts):
            raise ValueError("已登记的客体账号不可核查")
        if not groups:
            subprocess.run(["/usr/sbin/groupadd", "--gid", str(uid), name], check=True, timeout=30,
                           stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        if not accounts:
            subprocess.run(["/usr/sbin/useradd", "--uid", str(uid), "--gid", str(uid), "--no-create-home",
                            "--home-dir", "/nonexistent", "--shell", "/usr/sbin/nologin", name], check=True, timeout=30,
                           stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        account = pwd.getpwnam(name)
        group = grp.getgrnam(name)
        if account.pw_uid != uid or account.pw_gid != uid or account.pw_dir != "/nonexistent" or account.pw_shell != "/usr/sbin/nologin" or group.gr_gid != uid or group.gr_mem or set(os.getgrouplist(name, uid)) != {uid}:
            raise ValueError("客体账号配置不可核查")
        if state == "RESERVED":
            with self.connect() as db:
                db.execute("BEGIN IMMEDIATE")
                result = db.execute("UPDATE guest_identities SET state='READY' WHERE run_id=? AND account=? AND uid=? AND state='RESERVED'", (run_id, name, uid))
                if result.rowcount != 1:
                    raise ValueError("客体账号登记状态已经变化")
        return name, uid, uid
