"""Crash-detectable two-file review import; recovery is explicit and fail-closed.

Two os.replace operations are not a single filesystem transaction. The durable
journal detects a partially applied update, preventing checks/exports until an
operator recovers the original files. This lock coordinates this tool's writers,
not unrelated editors that disregard its lock directory.
"""
from __future__ import annotations

import hashlib
import json
import os
import tempfile
from contextlib import contextmanager
from pathlib import Path

FILES = ("requirements.json", "outline.json")
JOURNAL = "review-import-transaction.json"
LOCK = ".review-import.lock"


def _hash(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def journal_path(root: Path) -> Path:
    return root / "reports" / JOURNAL


@contextmanager
def exclusive(root: Path):
    folder = root / "reports" / LOCK
    folder.parent.mkdir(parents=True, exist_ok=True)
    try:
        folder.mkdir()
    except FileExistsError as exc:
        raise ValueError("已存在审核导入独占锁；如上次中断，请先检查并执行安全恢复") from exc
    try:
        yield
    finally:
        try:
            folder.rmdir()
        except OSError:
            # Fail closed rather than deleting a lock changed by another process.
            pass


def _atomic_bytes(dest: Path, raw: bytes) -> None:
    """Write to a unique same-directory file, then atomically replace one file."""
    fd, name = tempfile.mkstemp(prefix=".review-staged-", suffix=".tmp", dir=str(dest.parent))
    try:
        with os.fdopen(fd, "wb") as stream:
            stream.write(raw)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(name, dest)
    finally:
        Path(name).unlink(missing_ok=True)


def _save_journal(path: Path, data: dict) -> None:
    from .core import write_json
    if path.exists():
        raise ValueError("发现未恢复的审核导入事务；禁止继续写入")
    write_json(path, data)


def apply_transaction(root: Path, *, before: dict[str, bytes],
                      after: dict[str, bytes], backup: Path) -> None:
    """Caller must hold exclusive lock and have checked the initial project."""
    root = Path(root)
    marker = journal_path(root)
    if marker.exists():
        raise ValueError("发现未恢复的审核导入事务，请先运行 review-recover")
    if set(before) != set(FILES) or set(after) != set(FILES):
        raise ValueError("事务需要同时更新正式需求与目录")
    for filename in FILES:
        if (root / filename).read_bytes() != before[filename]:
            raise ValueError(f"{filename} 在规划后被其他操作修改，拒绝覆盖")
    if backup.exists():
        raise ValueError("审核备份目录已存在；请核查历史导入记录")
    backup.mkdir(parents=True, exist_ok=False)
    try:
        for filename in FILES:
            with (backup / (filename + ".before")).open("xb") as stream:
                stream.write(before[filename])
                stream.flush()
                os.fsync(stream.fileno())
        # Recheck immediately before committing; lock prevents cooperating
        # importers but external/manual editors may still change files.
        for filename in FILES:
            if (root / filename).read_bytes() != before[filename]:
                raise ValueError(f"{filename} 在导入前被其他操作修改，拒绝覆盖")
        manifest = {
            "schema_version": 1, "status": "commit_or_recover",
            "backup_rel": str(backup.relative_to(root)),
            "files": {
                filename: {"before": _hash(before[filename]),
                           "after": _hash(after[filename])}
                for filename in FILES
            },
        }
        _save_journal(marker, manifest)
        try:
            for filename in FILES:
                _atomic_bytes(root / filename, after[filename])
            # Only remove the marker once BOTH destination files are durable
            # and exactly match their intended committed versions.
            for filename in FILES:
                if _hash((root / filename).read_bytes()) != manifest["files"][filename]["after"]:
                    raise OSError(f"{filename} 写入后校验失败")
            marker.unlink()
        except BaseException:
            # A crash or exception leaves a durable journal; strict inspection
            # and subsequent imports fail closed until explicit recovery.
            raise
    except BaseException:
        # Backups are intentionally preserved for manual inspection.
        raise


def recover(root: Path, *, confirm: bool = False) -> dict:
    """Restore BOTH pre-import versions only when current files are known."""
    root = Path(root)
    if not confirm:
        raise ValueError("恢复审核导入必须明确指定 --confirm")
    with exclusive(root):
        marker = journal_path(root)
        if not marker.is_file():
            raise ValueError("没有未完成的审核导入事务")
        from .core import read_json
        payload = read_json(marker)
        if (not isinstance(payload, dict) or payload.get("schema_version") != 1
                or payload.get("status") != "commit_or_recover"
                or not isinstance(payload.get("files"), dict)
                or set(payload["files"]) != set(FILES)):
            raise ValueError("审核事务记录损坏，禁止自动恢复")
        relative = payload.get("backup_rel")
        base = root / "reports" / "review-backups"
        if not isinstance(relative, str):
            raise ValueError("审核备份路径无效")
        backup = (root / relative).resolve()
        if not backup.is_relative_to(base.resolve()):
            raise ValueError("审核备份路径指向工作区外部，拒绝恢复")
        original = {}
        for filename in FILES:
            pair = payload["files"][filename]
            if (not isinstance(pair, dict) or not all(
                    isinstance(pair.get(key), str) and len(pair[key]) == 64
                    for key in ("before", "after"))):
                raise ValueError("审核事务中的文件指纹无效")
            original[filename] = (backup / (filename + ".before")).read_bytes()
            current = (root / filename).read_bytes()
            if _hash(original[filename]) != pair["before"]:
                raise ValueError("原始审核备份指纹错误，拒绝恢复")
            if _hash(current) not in {pair["before"], pair["after"]}:
                raise ValueError(f"{filename} 自事务中断后已被外部修改，禁止自动覆盖")
        for filename in FILES:
            _atomic_bytes(root / filename, original[filename])
        for filename in FILES:
            if (root / filename).read_bytes() != original[filename]:
                raise OSError("恢复结果未通过原件校验，保持事务阻断")
        marker.unlink()
        return {"status": "restored", "backup": str(backup),
                "restored_files": list(FILES)}
