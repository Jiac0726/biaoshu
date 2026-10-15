"""Crash-detectable write-ahead record for AI Markdown + review checkpoint.

The two files cannot be atomically replaced as a set. A journal makes any
partial write visible to inspection and recoverable without replacing unknown
human changes. Nothing here proves approval of the AI content.
"""
from __future__ import annotations

import base64
import hashlib
import json
import os
from pathlib import Path

from .core import read_json, write_json, section_path


def _hash(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def stage_path(root: Path, sid: str) -> Path:
    section_path(Path(root), sid)  # Reject traversal or malformed CLI IDs first.
    return Path(root) / "reports" / "section-writing" / (sid + ".transaction.json")


def _snapshot(path: Path, expected: bytes) -> dict:
    old = path.read_bytes() if path.exists() else None
    return {
        "previous": base64.b64encode(old).decode("ascii") if old is not None else None,
        "previous_sha256": _hash(old) if old is not None else None,
        "next_sha256": _hash(expected),
    }


def stage(root: Path, sid: str, markdown: bytes, checkpoint: bytes, *,
          status: str = "writing") -> Path:
    """Create a journal before touching either destination."""
    if status not in {"writing", "approving"}:
        raise ValueError("未知的章节事务类型")
    root = Path(root)
    doc = section_path(root, sid)
    sidecar = root / "reports" / "section-writing" / (sid + ".json")
    marker = stage_path(root, sid)
    if marker.exists():
        raise ValueError("存在未完成的章节写作事务，请先运行 section-recover")
    payload = {
        "schema_version": 1, "section_id": sid, "status": status,
        "section": _snapshot(doc, markdown),
        "checkpoint": _snapshot(sidecar, checkpoint),
    }
    write_json(marker, payload)
    return marker


def recover(root: Path, sid: str, *, confirm: bool = False,
            unlock_stale: bool = False) -> dict:
    """Roll back only known before/after versions. Never overwrite manual edits."""
    if not confirm:
        raise ValueError("恢复必须由操作者明确添加 --confirm")
    root = Path(root)
    marker = stage_path(root, sid)
    lock = marker.with_name(sid + ".write.lock")
    if not marker.is_file():
        if not lock.exists():
            raise ValueError("该章节没有待恢复的写作事务")
        if not unlock_stale:
            raise ValueError("写入进程可能已中断，请先确认进程停止，再同时指定 --confirm --unlock-stale")
        try:
            owner = json.loads(lock.read_text(encoding="utf-8"))
            pid = owner.get("pid") if isinstance(owner, dict) else None
        except (OSError, ValueError):
            pid = None
        if type(pid) is int and pid > 0:
            try:
                os.kill(pid, 0)
            except ProcessLookupError:
                pass
            except (PermissionError, OSError) as exc:
                raise ValueError("无法证明章节写入进程已结束，禁止自动清理锁") from exc
            else:
                raise ValueError("原章节写入进程仍然存活，拒绝清除活动锁")
        lock.unlink()
        return {"section_id": sid, "status": "stale_lock_cleared"}
    if lock.exists() and not unlock_stale:
        raise ValueError("存在写入锁；确认原写作进程已经结束，再显式指定 --unlock-stale")
    payload = read_json(marker)
    if (not isinstance(payload, dict) or payload.get("schema_version") != 1
            or payload.get("section_id") != sid
            or payload.get("status") not in {"writing", "approving"}):
        raise ValueError("章节事务日志损坏，拒绝自动恢复")
    destinations = {
        "section": section_path(root, sid),
        "checkpoint": marker.with_name(sid + ".json"),
    }
    previous = {}
    for name, dest in destinations.items():
        record = payload.get(name)
        if not isinstance(record, dict):
            raise ValueError("事务记录缺少目标文件快照")
        encoded, previous_sha = record.get("previous"), record.get("previous_sha256")
        expected = record.get("next_sha256")
        if not isinstance(expected, str) or len(expected) != 64:
            raise ValueError("事务记录的新文件指纹无效")
        if encoded is None:
            if previous_sha is not None:
                raise ValueError("事务记录的原始指纹不完整")
            old = None
        elif isinstance(encoded, str) and isinstance(previous_sha, str):
            try:
                old = base64.b64decode(encoded, validate=True)
            except ValueError as exc:
                raise ValueError("原始内容编码损坏") from exc
            if _hash(old) != previous_sha:
                raise ValueError("事务记录的原始字节指纹不匹配")
        else:
            raise ValueError("事务记录的原始内容类型无效")
        current = dest.read_bytes() if dest.exists() else None
        if current is None:
            if old is not None:
                raise ValueError(f"{name} 文件被外部删除；请人工核实后恢复")
        elif _hash(current) not in {expected, previous_sha}:
            raise ValueError(f"{name} 在中断后被人工修改，拒绝自动覆盖")
        previous[name] = old
    # Validate BOTH files before changing either. Use per-file atomic replace.
    from .review_transaction import _atomic_bytes
    for name, dest in destinations.items():
        old = previous[name]
        if old is None:
            dest.unlink(missing_ok=True)
        else:
            _atomic_bytes(dest, old)
    for name, dest in destinations.items():
        original = previous[name]
        if (dest.read_bytes() if dest.exists() else None) != original:
            raise OSError("章节事务恢复后校验失败，保留日志")
    marker.unlink()
    if lock.exists():
        lock.unlink()
    return {"section_id": sid, "status": "restored"}
