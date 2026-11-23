"""项目内 .speclock/ 状态目录解析、安全校验与旧版外部状态库迁移。"""
import hashlib
import os
from pathlib import Path
import sqlite3
import sys
import tempfile
from typing import Optional

from .model import EngineError

STATE_DIRNAME = ".speclock"


def external_home() -> Optional[Path]:
    """显式配置 WORKFLOW_ENGINE_HOME 时沿用项目外目录，否则返回 None。"""
    value = os.environ.get("WORKFLOW_ENGINE_HOME")
    return Path(value) if value else None


def state_dir(root) -> Path:
    """纯函数：返回当前项目权威状态目录（默认项目内 .speclock/）。"""
    resolved_root = Path(root).resolve()
    home = external_home()
    if home is not None:
        key = hashlib.sha256(str(resolved_root).encode()).hexdigest()
        return home / key
    return resolved_root / STATE_DIRNAME


def is_state_relpath(rel) -> bool:
    """相对路径第一段是否为 .speclock，供快照排除与门禁拦截复用。"""
    parts = Path(rel).parts
    return bool(parts) and parts[0] == STATE_DIRNAME


def is_internal_state(root, path) -> bool:
    """判断路径（resolve 后）是否位于 root/.speclock 之内。"""
    resolved_root = Path(root).resolve()
    internal_dir = resolved_root / STATE_DIRNAME
    if internal_dir.is_symlink():
        return False
    target = Path(path).resolve()
    return target == internal_dir or internal_dir in target.parents


def ensure_internal_state_dir(root) -> Path:
    """创建项目内 .speclock/（0700）及只读自包含 .gitignore，拒绝符号链接。"""
    resolved_root = Path(root).resolve()
    if not resolved_root.is_dir():
        raise EngineError("ROOT_INVALID", "root 必须是目录")
    target = resolved_root / STATE_DIRNAME
    if target.is_symlink():
        raise EngineError("DB_LOCATION", "状态目录不允许符号链接")
    if target.exists() and not target.is_dir():
        raise EngineError("DB_LOCATION", "状态目录路径已存在且不是目录")
    if not target.exists():
        try:
            target.mkdir(mode=0o700)
        except FileExistsError:
            if target.is_symlink() or not target.is_dir():
                raise EngineError("DB_LOCATION", "状态目录路径无效或为符号链接")
        else:
            os.chmod(str(target), 0o700)
    for entry in target.iterdir():
        if entry.is_symlink():
            raise EngineError("DB_LOCATION", "状态目录内不允许符号链接")
    gitignore = target / ".gitignore"
    if gitignore.is_symlink():
        raise EngineError("DB_LOCATION", "状态目录内不允许符号链接")
    if gitignore.exists():
        if not gitignore.is_file():
            raise EngineError("DB_LOCATION", ".speclock/.gitignore 必须是普通文件")
    else:
        flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_NOFOLLOW", 0)
        try:
            fd = os.open(str(gitignore), flags, 0o600)
        except FileExistsError:
            if gitignore.is_symlink() or not gitignore.is_file():
                raise EngineError("DB_LOCATION", ".speclock/.gitignore 路径无效或为符号链接")
        else:
            try:
                os.fchmod(fd, 0o600)
                os.write(fd, b"*\n")
            finally:
                os.close(fd)
    return target


def ensure_state_dir(root) -> Path:
    """按当前模式准备状态目录；外部模式仅创建目录，不写 .gitignore。"""
    resolved_root = Path(root).resolve()
    if external_home() is None:
        return ensure_internal_state_dir(resolved_root)
    target = state_dir(resolved_root)
    if target.is_symlink():
        raise EngineError("DB_LOCATION", "状态目录不允许符号链接")
    if target.exists() and not target.is_dir():
        raise EngineError("DB_LOCATION", "状态目录路径已存在且不是目录")
    target.mkdir(parents=True, exist_ok=True, mode=0o700)
    return target


def legacy_db(root) -> Path:
    """定位旧版按 CODEX_HOME/workflow-engine/<sha256>/state.sqlite 存放的数据库。"""
    resolved_root = Path(root).resolve()
    codex_home = Path(os.environ.get("CODEX_HOME") or Path.home() / ".codex").expanduser()
    key = hashlib.sha256(str(resolved_root).encode()).hexdigest()
    return codex_home / "workflow-engine" / key / "state.sqlite"


def migrate_legacy(root) -> Optional[Path]:
    """仅在默认项目内模式且新库尚不存在时，只读备份复制旧库；旧库保持原样。"""
    if external_home() is not None:
        return None
    resolved_root = Path(root).resolve()
    if not resolved_root.is_dir():
        return None
    target_dir = resolved_root / STATE_DIRNAME
    new_db = target_dir / "state.sqlite"
    if target_dir.is_symlink() or new_db.is_symlink():
        raise EngineError("DB_LOCATION", "状态目录或数据库不允许符号链接")
    if new_db.exists():
        return None
    old_db = legacy_db(resolved_root)
    if old_db.is_symlink() or old_db.parent.is_symlink() or not old_db.is_file():
        return None
    ensure_internal_state_dir(resolved_root)
    if new_db.exists():
        return None
    tmp_fd, tmp_name = tempfile.mkstemp(prefix=".state.", suffix=".tmp", dir=str(target_dir))
    os.close(tmp_fd)
    tmp_path = Path(tmp_name)
    try:
        src = sqlite3.connect(old_db.resolve().as_uri() + "?mode=ro", uri=True, timeout=10)
        try:
            dst = sqlite3.connect(str(tmp_path), timeout=10)
            try:
                src.backup(dst)
            finally:
                dst.close()
        finally:
            src.close()
        os.chmod(str(tmp_path), 0o600)
        if new_db.is_symlink():
            raise EngineError("DB_LOCATION", "数据库不允许符号链接")
        if new_db.exists():
            return None
        os.replace(str(tmp_path), str(new_db))
        print(f"[workflow-core] 已将旧状态库迁移至 {new_db}（原库保留：{old_db}）", file=sys.stderr)
        return new_db
    finally:
        tmp_path.unlink(missing_ok=True)
