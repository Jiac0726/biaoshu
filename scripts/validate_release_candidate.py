"""Offline release-candidate acceptance: full regressions, end-to-end bid, CLI.

The script never uploads tender data or calls a model. The e2e tests use
fictional tender fixtures and simulated model responses. Exit 1 if any gate
fails; optional JSON report is local and does not claim human approval.
"""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
import time
from pathlib import Path


def execute(args: list[str], *, cwd: Path) -> dict:
    started = time.monotonic()
    try:
        finished = subprocess.run(args, cwd=cwd, check=False, timeout=180)
        return {"command": args[1:], "status": "passed" if finished.returncode == 0 else "failed",
                "exit_code": finished.returncode,
                "elapsed_seconds": round(time.monotonic() - started, 2)}
    except subprocess.TimeoutExpired:
        return {"command": args[1:], "status": "timeout", "exit_code": 124,
                "elapsed_seconds": round(time.monotonic() - started, 2)}


def revision(root: Path) -> dict:
    """Pin evidence to the actually tested checkout, not a documentation SHA."""
    try:
        head = subprocess.run(
            ["git", "rev-parse", "--verify", "HEAD"], cwd=root,
            capture_output=True, text=True, check=False, timeout=8)
        dirty = subprocess.run(
            ["git", "status", "--porcelain", "--untracked-files=no"], cwd=root,
            capture_output=True, text=True, check=False, timeout=8)
    except (OSError, subprocess.TimeoutExpired):
        return {"sha": None, "tracked_tree_clean": None, "status": "unverified"}
    sha = head.stdout.strip()
    if head.returncode or dirty.returncode or len(sha) != 40 or any(
            ch not in "0123456789abcdefABCDEF" for ch in sha):
        return {"sha": None, "tracked_tree_clean": None, "status": "unverified"}
    return {"sha": sha, "tracked_tree_clean": not bool(dirty.stdout.strip()),
            "status": "verified"}


def run(*, report_path: Path | None = None) -> int:
    root = Path(__file__).resolve().parents[1]
    checks = [
        [sys.executable, "-m", "unittest", "discover", "-s", "tests", "-v"],
        [sys.executable, "-m", "unittest", "discover", "-s", "tests",
         "-p", "test_pipeline_e2e.py", "-v"],
        [sys.executable, "-m", "biaoshu", "--help"],
    ]
    outcomes = []
    for cmd in checks:
        result = execute(cmd, cwd=root)
        outcomes.append(result)
        if result["status"] != "passed":
            break  # Fail closed; later results would be misleading.
    report = {
        "schema_version": 1, "kind": "fictional_offline_release_candidate_validation",
        "status": "passed" if len(outcomes) == len(checks) and all(
            x["status"] == "passed" for x in outcomes) else "failed",
        "results": outcomes,
        "revision": revision(root),
        "limitations": [
            "仅验证虚构招标样本和模拟 AI，非真实模型质量验收",
            "不能替代独立人工代码审查、真实投标合规审查或主分支保护",
            "不检查真实投标文件或对外发送资料",
        ],
    }
    if report_path is not None:
        target = Path(report_path)
        target.parent.mkdir(parents=True, exist_ok=True)
        try:
            # Exclusive open is atomic even if two independent runners race.
            with target.open("x", encoding="utf-8") as output:
                output.write(json.dumps(report, ensure_ascii=False, indent=2) + "\n")
        except FileExistsError as exc:
            raise ValueError("验收报告已存在；为保留审查记录，不允许覆盖") from exc
        print(f"本地验收记录已保存：{target}")
    print(f"集成候选验收：{report['status']}，通过 {sum(x['status'] == 'passed' for x in outcomes)}/{len(checks)} 个命令")
    return 0 if report["status"] == "passed" else 1


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Offline synthetic RC acceptance")
    parser.add_argument("--report", type=Path,
                        help="保存本地 JSON 验收记录，拒绝覆盖已有记录")
    args = parser.parse_args(argv)
    return run(report_path=args.report)


if __name__ == "__main__":
    sys.exit(main())
