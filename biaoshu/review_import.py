"""Explicitly reviewed suggestion import with source re-extraction and safe append.

No model output can silently become a project requirement. Review files are
operator declarations, not cryptographic proof of human identity or correctness.
"""
from __future__ import annotations

import hashlib
import json
import math
import re
from pathlib import Path

from .core import ID_RE, inspect, load_project, read_json, write_json
from .extraction import extract_document
from .score_candidates import _source_index

ACKNOWLEDGEMENT = "我已逐项核对招标原文，并确认接受项可登记为技术响应需求"
KINDS = {"technical_score", "mandatory_technical_requirement", "scoring_rule"}


def _digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _read_suggestions(path: Path) -> list[dict]:
    data = read_json(path)
    if (not isinstance(data, dict) or data.get("status") != "suggestions_only"
            or not isinstance(data.get("candidates"), list)):
        raise ValueError("候选文件必须是 suggestions_only 类型的完整 JSON")
    ids = set()
    for item in data["candidates"]:
        if not isinstance(item, dict) or not isinstance(item.get("id"), str) or not ID_RE.fullmatch(item["id"]):
            raise ValueError("候选缺少合法 ID")
        if item["id"] in ids:
            raise ValueError(f"候选 ID 重复：{item['id']}")
        ids.add(item["id"])
    return data["candidates"]


def review_template(suggestions_path: Path) -> dict:
    items = _read_suggestions(suggestions_path)
    return {
        "schema_version": 1,
        "suggestions_sha256": _digest(suggestions_path),
        "acknowledgement": "",
        "decisions": [
            {"id": item["id"], "decision": "pending"} for item in items
        ],
    }


def _check_review(review: dict, candidates: list[dict], digest: str) -> dict[str, str]:
    if (not isinstance(review, dict) or review.get("schema_version") != 1
            or review.get("suggestions_sha256") != digest):
        raise ValueError("审核清单不匹配当前候选文件，禁止使用旧审批记录")
    raw = review.get("decisions")
    if not isinstance(raw, list):
        raise ValueError("审核决策必须是数组")
    choices: dict[str, str] = {}
    for item in raw:
        if (not isinstance(item, dict) or set(item) != {"id", "decision"}
                or not isinstance(item["id"], str)
                or item["decision"] not in {"accept", "reject", "pending"}):
            raise ValueError("审核决策必须包含 id 和 accept/reject/pending")
        if item["id"] in choices:
            raise ValueError(f"重复审核决策：{item['id']}")
        choices[item["id"]] = item["decision"]
    ids = {c["id"] for c in candidates}
    if set(choices) != ids:
        raise ValueError("审核决策必须与候选 ID 一一对应，不能漏项或加入未知项")
    return choices


def _next_id(prefix: str, used: set[str]) -> str:
    i = 1
    while f"{prefix}{i}" in used:
        i += 1
    code = f"{prefix}{i}"
    used.add(code)
    return code


def _validate_candidate(item: dict) -> tuple[str, str, float | None, dict]:
    kind = item.get("kind", "technical_score")
    if kind not in KINDS:
        raise ValueError(f"{item['id']} 不支持的候选类型")
    if kind == "scoring_rule":
        raise ValueError(f"{item['id']} 为评分规则，不允许自动转成独立技术响应章节")
    title = item.get("title")
    if not isinstance(title, str) or not title.strip() or len(title) > 120:
        raise ValueError(f"{item['id']} 标题不合法")
    score = item.get("score")
    if (score is not None and (isinstance(score, bool) or not isinstance(score, (int, float))
                               or not math.isfinite(score) or score < 0 or score > 100)):
        raise ValueError(f"{item['id']} 分值不合法")
    if kind == "mandatory_technical_requirement" and score is not None:
        raise ValueError(f"{item['id']} 无分值的强制要求不能被赋予评分")
    evidence = item.get("evidence")
    if (not isinstance(evidence, dict)
            or any(not isinstance(evidence.get(k), str) or not evidence[k].strip()
                   for k in ("file", "location", "quote"))):
        raise ValueError(f"{item['id']} 原文证据不完整")
    return kind, title.strip(), score, {k: evidence[k].strip() for k in ("file", "location", "quote")}


def _source_blocks(index_paths: list[Path], source_dir: Path) -> dict[tuple[str, str], list[str]]:
    if not index_paths:
        raise ValueError("必须至少提供一份原文索引 --index")
    source_dir = source_dir.resolve()
    if not source_dir.is_dir():
        raise ValueError("原文目录不存在")
    sources = {}
    for path in index_paths:
        index = _source_index(Path(path), source_dir)
        name = index["source_file"]
        if name in sources:
            raise ValueError(f"同名原文件索引重复：{name}")
        # Fingerprint alone authenticates source bytes, not index text.
        # Re-extract source to reject a forged or edited evidence index.
        extracted = extract_document(source_dir / name).index
        if extracted["sha256"] != index["sha256"] or extracted["blocks"] != index["blocks"]:
            raise ValueError(f"{name} 索引内容与重新解析的原件不一致")
        sources[name] = index
    result: dict[tuple[str, str], list[str]] = {}
    for name, index in sources.items():
        for block in index["blocks"]:
            result.setdefault((name, block["location"]), []).append(block["text"])
    return result


def _normalize(text: str) -> str:
    import unicodedata
    return "".join(unicodedata.normalize("NFKC", text).split())


def reviewed_import(project_dir: Path, suggestions_path: Path, review_path: Path,
                    index_paths: list[Path], source_dir: Path, *, apply: bool = False) -> dict:
    """Plan or apply a non-destructive 1:1 requirement/outline import.

    Applying requires an acknowledgement and all candidate decisions resolved.
    Existing section files and requirements are never overwritten or rewritten.
    """
    project_dir = Path(project_dir)
    suggestions_path, review_path = Path(suggestions_path), Path(review_path)
    candidates = _read_suggestions(suggestions_path)
    review = read_json(review_path)
    choices = _check_review(review, candidates, _digest(suggestions_path))
    unresolved = [key for key, value in choices.items() if value == "pending"]
    if apply and unresolved:
        raise ValueError(f"存在 {len(unresolved)} 条未处理候选，禁止登记")
    if apply and review.get("acknowledgement") != ACKNOWLEDGEMENT:
        raise ValueError("必须由审稿人逐项核对，并填写规定的 acknowledgement 才可 --apply")

    current = load_project(project_dir)
    initial = inspect(project_dir)
    if not initial["ok"]:
        raise ValueError("项目现有结构校验未通过；禁止基于错误状态导入")
    reqs, sections = current["requirements.json"]["requirements"], current["outline.json"]["sections"]
    if not isinstance(reqs, list) or not isinstance(sections, list):
        raise ValueError("现有需求与目录格式不正确")
    used_req = {r["id"] for r in reqs}
    used_sec = {s["id"] for s in sections}
    existing = {(r["evidence"]["file"], r["evidence"]["location"], _normalize(r["evidence"]["quote"])): r
                for r in reqs}
    blocks = _source_blocks(index_paths, Path(source_dir))
    additions, new_sections, duplicates = [], [], []
    for candidate in candidates:
        if choices[candidate["id"]] != "accept":
            continue
        kind, title, score, ev = _validate_candidate(candidate)
        quote = _normalize(ev["quote"])
        match = blocks.get((ev["file"], ev["location"]), [])
        if not quote or not any(quote in _normalize(text) for text in match):
            raise ValueError(f"{candidate['id']} 引文与重新提取的招标原文不匹配")
        key = ev["file"], ev["location"], quote
        if key in existing:
            if existing[key].get("title") != title:
                raise ValueError(f"{candidate['id']} 与现存需求使用相同证据但标题冲突")
            duplicates.append(candidate["id"])
            continue
        rid, sid = _next_id("R", used_req), _next_id("S", used_sec)
        requirement = {
            "id": rid, "title": title, "description": "",
            "score": score, "evidence": ev, "response_sections": [sid],
            "kind": kind,
            "review_origin": {"candidate_id": candidate["id"],
                              "suggestions_sha256": _digest(suggestions_path)},
        }
        section = {"id": sid, "title": title, "requirement_ids": [rid],
                   "weight": 1.0, "target_words": 0}
        existing[key] = requirement
        additions.append(requirement)
        new_sections.append(section)
    plan = {"status": "ready" if not unresolved else "pending_review",
            "apply_requested": apply,
            "statistics": {"accepted": sum(x == "accept" for x in choices.values()),
                           "rejected": sum(x == "reject" for x in choices.values()),
                           "pending": len(unresolved), "duplicate": len(duplicates),
                           "new_requirements": len(additions)},
            "new_requirements": additions, "new_sections": new_sections,
            "duplicates": duplicates,
            "warnings": ["结构及引文匹配不代表已经完成招标专业和合规审查。"]}
    if apply and additions and "roots" in current["outline.json"]:
        raise ValueError("项目已有层级目录：新增需求必须先经人工修订目录树，禁止自动破坏章节覆盖或一级目录锁")
    if not apply or not additions:
        return plan

    before_req = (project_dir / "requirements.json").read_bytes()
    before_sec = (project_dir / "outline.json").read_bytes()
    req_after = {"requirements": [*reqs, *additions]}
    sec_after = {"sections": [*sections, *new_sections]}
    # All validation and preview occur before modifying either file.
    # Keep local backups for independent recovery if interrupted mid-write.
    # A later review may accept previously rejected items in the same suggestion set.
    # Include the review snapshot so backups remain distinct for each decision set.
    review_stamp = _digest(review_path)
    backup = project_dir / "reports" / "review-backups" / (_digest(suggestions_path) + "-" + review_stamp)
    if backup.exists():
        raise ValueError("该候选文件的审核备份已经存在；请人工检查重复导入或恢复记录")
    backup.mkdir(parents=True, exist_ok=False)
    (backup / "requirements.before.json").write_bytes(before_req)
    (backup / "outline.before.json").write_bytes(before_sec)
    try:
        write_json(project_dir / "requirements.json", req_after)
        write_json(project_dir / "outline.json", sec_after)
    except OSError:
        (project_dir / "requirements.json").write_bytes(before_req)
        (project_dir / "outline.json").write_bytes(before_sec)
        raise
    plan["status"] = "applied"
    plan["backup_dir"] = str(backup)
    return plan
