"""Optional hierarchical table of contents and an explicit first-level lock.

Existing S# section identities and their markdown bodies never change here.
This is a structural/editorial lock, not tamper-proof authentication.
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path

from .core import ID_RE, read_json, write_json

MAX_DEPTH = 4
LOCK_FILE = "outline-lock.json"


def _hash(value: object) -> str:
    return hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True,
                                      separators=(",", ":")).encode("utf-8")).hexdigest()


def _members(node: dict) -> list[str]:
    if "section_id" in node:
        return [node["section_id"]]
    result = []
    for child in node["children"]:
        result.extend(_members(child))
    return result


def _signature(roots: list[dict], sections: list[dict]) -> list[dict]:
    """Protect every first-level heading, including a root that is a leaf S#."""
    titles = {section["id"]: section["title"] for section in sections}
    result = []
    for node in roots:
        if "section_id" in node:
            sid = node["section_id"]
            result.append({"type": "section", "section_id": sid,
                           "title": titles[sid]})
        else:
            result.append({"type": "group", "id": node["id"], "title": node["title"],
                           "members": sorted(_members(node))})
    return result


def validate_roots(roots: object, sections: list[dict]) -> list[str]:
    errors: list[str] = []
    section_ids = [sec.get("id") for sec in sections if isinstance(sec, dict)]
    if not isinstance(roots, list) or (section_ids and not roots):
        return ["目录树 roots 必须是非空数组（存在正文小节时）"]
    if not isinstance(roots, list):
        return ["目录树 roots 必须是数组"]
    used_sections: list[str] = []
    group_ids: set[str] = set()
    def walk(node: object, depth: int):
        if depth > MAX_DEPTH:
            errors.append(f"目录层级超过 {MAX_DEPTH} 级")
            return
        if not isinstance(node, dict):
            errors.append("目录节点必须是对象")
            return
        if set(node) == {"section_id"}:
            sid = node["section_id"]
            if not isinstance(sid, str) or not ID_RE.fullmatch(sid):
                errors.append(f"目录叶子章节 ID 不合法：{sid!r}")
            else:
                used_sections.append(sid)
            return
        if set(node) != {"id", "title", "children"}:
            errors.append("目录节点只能是 {section_id} 或 {id,title,children}")
            return
        gid, title, children = node["id"], node["title"], node["children"]
        if not isinstance(gid, str) or not ID_RE.fullmatch(gid):
            errors.append(f"目录组 ID 不合法：{gid!r}")
        elif gid in group_ids or gid in section_ids:
            errors.append(f"目录组 ID 重复或与章节冲突：{gid}")
        else:
            group_ids.add(gid)
        if not isinstance(title, str) or not title.strip() or len(title) > 120:
            errors.append(f"目录组 {gid!r} 标题不能为空且不超过120字符")
        if not isinstance(children, list) or len(children) < 2:
            errors.append(f"目录组 {gid!r} 至少有两个子节点，避免冗余包裹层")
            return
        for child in children:
            walk(child, depth + 1)
    for root in roots:
        walk(root, 1)
    seen: set[str] = set()
    for sid in used_sections:
        if sid in seen:
            errors.append(f"目录重复引用章节 {sid}")
        seen.add(sid)
    expected = set(section_ids)
    for sid in sorted(expected - seen):
        errors.append(f"目录遗漏章节 {sid}")
    for sid in sorted(seen - expected):
        errors.append(f"目录引用不存在的章节 {sid}")
    if len(set(section_ids)) != len(section_ids):
        errors.append("基础目录章节 ID 存在重复")
    return errors


def validate_outline_state(root: Path, outline: dict) -> list[str]:
    """Shared validation for check/audit/export and plan mutations."""
    errors = []
    sections = outline.get("sections")
    if not isinstance(sections, list):
        return ["outline.sections 必须是数组"]
    roots = outline.get("roots")
    lock_path = Path(root) / LOCK_FILE
    if roots is not None:
        errors.extend(validate_roots(roots, sections))
    if lock_path.exists():
        try:
            lock = read_json(lock_path)
        except (OSError, ValueError, TypeError) as exc:
            return errors + [f"目录锁不可读取：{exc}"]
        if (not isinstance(lock, dict) or lock.get("schema_version") != 1
                or not isinstance(lock.get("root_signature"), list)
                or not isinstance(lock.get("sha256"), str)
                or lock["sha256"] != _hash(lock["root_signature"])):
            errors.append("目录锁文件无效或校验信息被修改")
        elif roots is None or errors:
            errors.append("已锁定项目必须保留有效的目录树")
        elif _signature(roots, sections) != lock["root_signature"]:
            errors.append("一级目录已被修改（标题、顺序或归属），与已确认目录锁不一致")
    return errors


def outline_template(root: Path) -> dict:
    outline = read_json(Path(root) / "outline.json")
    sections = outline.get("sections", [])
    if not isinstance(sections, list):
        raise ValueError("outline.sections 不是数组")
    if validate_outline_state(Path(root), outline):
        raise ValueError("当前目录结构/目录锁无效，不能创建候选")
    if not sections:
        raise ValueError("没有可组织的响应章节")
    roots = outline.get("roots")
    return {
        "schema_version": 1, "status": "proposal",
        "sections_sha256": _hash([{"id": s.get("id"), "title": s.get("title")}
                                   for s in sections]),
        "roots": roots if roots is not None else [{"section_id": s["id"]} for s in sections],
        "review_note": "编辑 roots 为所需层级；只有通过预览且明确 --apply 才写入。不要改动章节 ID。",
    }


def _matching_sections(proposal: dict, sections: list[dict]) -> bool:
    return (proposal.get("sections_sha256")
            == _hash([{"id": s.get("id"), "title": s.get("title")} for s in sections]))


def outline_plan(root: Path, proposal_path: Path, *, apply: bool = False) -> dict:
    root = Path(root)
    outline = read_json(root / "outline.json")
    problems = validate_outline_state(root, outline)
    if problems:
        raise ValueError("项目现有目录或锁不合法：" + "; ".join(problems))
    proposal = read_json(Path(proposal_path))
    if not isinstance(proposal, dict) or proposal.get("schema_version") != 1 or proposal.get("status") != "proposal":
        raise ValueError("目录候选须是 schema_version=1、status=proposal 的对象")
    if not _matching_sections(proposal, outline["sections"]):
        raise ValueError("章节 ID 或标题已经更新；需重新生成目录候选")
    proposed_roots = proposal.get("roots")
    errs = validate_roots(proposed_roots, outline["sections"])
    if errs:
        raise ValueError("目录候选校验失败：" + "; ".join(errs))
    lock_path = root / LOCK_FILE
    if lock_path.exists() and _signature(proposed_roots, outline["sections"]) != _signature(outline["roots"], outline["sections"]):
        raise ValueError("一级目录已锁定，不能修改其标题、顺序或章节归属")
    plan = {"status": "preview", "root_count": len(proposed_roots),
            "section_count": len(outline["sections"]),
            "locked": lock_path.exists(), "changes": proposed_roots != outline.get("roots"),
            "notes": ["目录分层不能代替人工对评分覆盖、章节逻辑和专业内容的核查"]}
    if not apply:
        return plan
    if not plan["changes"]:
        plan["status"] = "unchanged"
        return plan
    prior = (root / "outline.json").read_bytes()
    fingerprint = hashlib.sha256(prior).hexdigest()
    backup = root / "reports" / "outline-backups" / (fingerprint + ".json")
    if backup.exists():
        raise ValueError("目录备份已存在；为避免覆盖，请人工检查历史操作")
    backup.parent.mkdir(parents=True, exist_ok=True)
    backup.write_bytes(prior)
    updated = {**outline, "roots": proposed_roots}
    write_json(root / "outline.json", updated)
    plan["status"] = "applied"
    plan["backup_path"] = str(backup)
    return plan


def lock_outline(root: Path, *, confirm: bool = False) -> dict:
    root = Path(root)
    if not confirm:
        raise ValueError("锁定一级目录前必须明确指定 --confirm")
    outline = read_json(root / "outline.json")
    roots = outline.get("roots")
    if roots is None:
        raise ValueError("请先用 outline-plan --apply 建立目录树")
    errors = validate_outline_state(root, outline)
    if errors:
        raise ValueError("当前目录/目录锁不合法：" + "; ".join(errors))
    signature = _signature(roots, outline["sections"])
    result = {"schema_version": 1, "root_signature": signature,
              "sha256": _hash(signature)}
    dest = root / LOCK_FILE
    if dest.exists():
        return {"status": "already_locked", "sha256": result["sha256"]}
    write_json(dest, result)
    return {"status": "locked", "sha256": result["sha256"]}


def walk_outline(outline: dict):
    """Yield (level, section-or-group, value) for Word order."""
    sections = {section["id"]: section for section in outline["sections"]}
    roots = outline.get("roots")
    if roots is None:
        for section in outline["sections"]:
            yield (1, "section", section)
        return
    def walk(nodes, level):
        for node in nodes:
            if "section_id" in node:
                yield (level, "section", sections[node["section_id"]])
            else:
                yield (level, "group", node)
                yield from walk(node["children"], level + 1)
    yield from walk(roots, 1)
