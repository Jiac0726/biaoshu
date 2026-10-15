"""Never overwrite project state or an existing artifact with AI suggestions.

Reports are intentionally published with exclusive creation. The source
document/indices and formal project files must never be report destinations.
A same-directory fully-written temporary file makes interrupted writes safe.
"""
from __future__ import annotations

import json
from pathlib import Path

from .review_transaction import atomic_create

_PROTECTED_NAMES = {
    "project.json", "requirements.json", "facts.json", "outline.json",
    "response-trace.json", "outline-lock.json",
    "review-import-transaction.json", ".review-import.lock",
}


def _is_internal_state_path(path: Path) -> bool:
    name = path.name.lower()
    if name in _PROTECTED_NAMES or name.endswith((".transaction.json", ".write.lock", ".before.json")):
        return True
    # Section-writing checkpoints are approval state, even when the target
    # does not exist yet. A speculative suggestions report must never create
    # an apparently valid (but actually false) checkpoint.
    return path.parent.name.lower() == "section-writing" and name.endswith(".json")


def validate_new_report_target(path: Path) -> None:
    """Early warning before invoking expensive/remote analysis; not a lock."""
    path = Path(path)
    if _is_internal_state_path(path):
        raise ValueError("输出文件名与正式项目或审核数据冲突，不能作为建议报告目标")
    if path.exists() or path.is_symlink():
        raise ValueError("报告目标已经存在；禁止覆盖现有报告、原招标文件或项目正式数据")


def write_new_report(path: Path, value: dict) -> None:
    """Write a new local JSON report, never replacing an existing path."""
    path = Path(path)
    validate_new_report_target(path)
    # Serialize before opening or creating any output so an invalid result
    # never leaves a partial file.
    content = (json.dumps(value, ensure_ascii=False, indent=2) + "\n").encode("utf-8")
    path.parent.mkdir(parents=True, exist_ok=True)
    try:
        atomic_create(path, content)
    except FileExistsError as exc:
        raise ValueError("报告目标已经存在；禁止覆盖现有报告、原招标文件或项目正式数据") from exc
