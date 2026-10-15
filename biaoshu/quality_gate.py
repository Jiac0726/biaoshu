"""Combine structural checks and source-locked evidence verification."""
from __future__ import annotations
from pathlib import Path
from .core import inspect
from .evidence import verify_evidence


def inspect_with_evidence(project_dir: Path, *, strict: bool = False,
                          index_paths: list[Path] | None = None,
                          source_dir: Path | None = None,
                          require_evidence: bool = False) -> dict:
    """Return structural and evidence checks in one report; never imply semantic review."""
    report = inspect(project_dir, strict=strict)
    indexes = list(index_paths or [])
    report["evidence"] = {"status": "not_checked", "summary": None, "errors": []}
    if not indexes and source_dir is None:
        message = "未提供证据索引与原文件目录；未核验来源指纹、位置及引文"
        if require_evidence:
            report["errors"].append(message + "；必须同时指定 --index 和 --source-dir")
        else:
            report["warnings"].append(message)
    elif not indexes or source_dir is None:
        report["errors"].append("证据核验参数不完整：--index 与 --source-dir 必须同时提供")
    else:
        result = verify_evidence(project_dir, indexes, source_dir)
        report["evidence"] = {"status": "verified" if result["ok"] else "failed",
                              "summary": result["summary"], "errors": result["errors"]}
        for issue in result["errors"]:
            report["errors"].append(f"证据[{issue['code']}] {issue['subject']}：{issue['message']}")
        report["warnings"].extend(result["warnings"])
    report["ok"] = not report["errors"]
    return report
