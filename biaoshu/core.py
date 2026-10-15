"""项目数据模型、结构校验、篇幅分配和机械审计。不调用模型，不编造业务事实。"""
from __future__ import annotations

import hashlib
import json
import math
import re
from pathlib import Path

ID_RE = re.compile(r"^[A-Za-z][A-Za-z0-9_-]{0,63}$")
STATUS = {"verified", "pending", "not_specified"}
DEFAULTS = {
    "project.json": {"project_name": "", "total_words": 12000, "notes": "先完成招标证据抽取，再填入结构化数据"},
    "requirements.json": {"requirements": []},
    "facts.json": {"facts": []},
    "outline.json": {"sections": []},
}


def read_json(path: Path):
    with path.open("r", encoding="utf-8") as stream:
        return json.load(stream)


def write_json(path: Path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_name(path.name + ".tmp")
    temp.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    temp.replace(path)


def initialize(root: Path):
    root.mkdir(parents=True, exist_ok=True)
    for name, data in DEFAULTS.items():
        target = root / name
        if not target.exists():
            write_json(target, data)
    (root / "sections").mkdir(exist_ok=True)
    (root / "reports").mkdir(exist_ok=True)


def section_path(root: Path, section_id: str) -> Path:
    if not isinstance(section_id, str) or not ID_RE.fullmatch(section_id):
        raise ValueError(f"不合法的小节 ID：{section_id!r}")
    return root / "sections" / (section_id + ".md")


def load_project(root: Path):
    return {k: read_json(root / k) for k in DEFAULTS}


def words(text: str) -> int:
    # 对中文用汉字计数，对连续英文或数字按词计数；为近似字数，非 Word 官方统计。
    cleaned = re.sub(r"(?m)^#{1,6}\s+.*$", "", text)
    cleaned = re.sub(r"(?m)^\s*(?:[-*]|\d+[.)])\s+", "", cleaned)
    return len(re.findall(r"[\u4e00-\u9fff]|[A-Za-z0-9]+", cleaned))


def inspect(root: Path, strict: bool = False) -> dict:
    errors, warnings, observations = [], [], []
    try:
        data = load_project(root)
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        return {"ok": False, "errors": [f"项目文件无法读取：{exc}"], "warnings": [], "statistics": {}}
    requirements = data["requirements.json"].get("requirements")
    facts = data["facts.json"].get("facts")
    sections = data["outline.json"].get("sections")
    project = data["project.json"]
    from .outline_tree import validate_outline_state
    errors.extend(validate_outline_state(root, data["outline.json"]))
    if not all(isinstance(x, list) for x in (requirements, facts, sections)):
        return {"ok": False, "errors": ["requirements、facts、sections 必须为数组"], "warnings": [], "statistics": {}}
    if strict and (not requirements or not sections):
        errors.append("严格审查要求至少一条招标需求和一节响应目录")
    elif not requirements or not sections:
        warnings.append("招标需求或目录尚未建立，当前检查不能证明评分覆盖")

    if not isinstance(project.get("total_words"), int) or project["total_words"] < 0:
        errors.append("project.total_words 必须为非负整数")
    req_ids, sec_ids, fact_keys = set(), set(), set()
    section_lookup = {}
    for i, sec in enumerate(sections):
        if not isinstance(sec, dict):
            errors.append(f"sections[{i}] 必须是对象")
            continue
        sid = sec.get("id")
        if not isinstance(sid, str) or not ID_RE.fullmatch(sid):
            errors.append(f"sections[{i}] 小节 ID 不合法：{sid!r}")
            continue
        if sid in sec_ids:
            errors.append(f"小节 ID 重复：{sid}")
        sec_ids.add(sid)
        section_lookup[sid] = sec
        if not str(sec.get("title", "")).strip():
            errors.append(f"{sid} 缺少标题")
        ids = sec.get("requirement_ids", [])
        if not isinstance(ids, list) or any(not isinstance(x, str) for x in ids):
            errors.append(f"{sid} requirement_ids 必须是字符串数组")
        try:
            if float(sec.get("weight", 1.0)) <= 0 or not math.isfinite(float(sec.get("weight", 1.0))):
                errors.append(f"{sid} weight 必须是有限正数")
        except (TypeError, ValueError):
            errors.append(f"{sid} weight 不是数字")
        if not isinstance(sec.get("target_words", 0), int) or sec.get("target_words", 0) < 0:
            errors.append(f"{sid} target_words 必须为非负整数")
        if strict:
            p = section_path(root, sid)
            if not p.exists():
                errors.append(f"{sid} 正文文件不存在：sections/{sid}.md")
            else:
                body = p.read_text(encoding="utf-8")
                # A model-written draft cannot silently pass strict audit or official export.
                checkpoint = root / "reports" / "section-writing" / (sid + ".json")
                if checkpoint.exists():
                    try:
                        meta = read_json(checkpoint)
                        if (not isinstance(meta, dict) or meta.get("section_id") != sid
                                or meta.get("status") != "approved"):
                            errors.append(f"{sid} AI 章节尚未经人工确认")
                        elif meta.get("body_sha256") != hashlib.sha256(p.read_bytes()).hexdigest():
                            errors.append(f"{sid} 审核后正文已更改，需要重新人工确认")
                    except (OSError, ValueError, TypeError):
                        errors.append(f"{sid} 写作检查点无法读取")
                actual = words(body)
                if not body.strip() or "TODO" in body.upper() or "待撰写" in body:
                    errors.append(f"{sid} 正文未完成或包含占位符")
                target = sec.get("target_words", 0)
                if isinstance(target, int) and target > 0 and actual < target * 0.7:
                    warnings.append(f"{sid} 约 {actual} 字，低于目标 {target} 字的 70%")

    for i, req in enumerate(requirements):
        if not isinstance(req, dict):
            errors.append(f"requirements[{i}] 必须是对象")
            continue
        rid = req.get("id")
        if not isinstance(rid, str) or not ID_RE.fullmatch(rid):
            errors.append(f"requirements[{i}] ID 不合法：{rid!r}")
            continue
        if rid in req_ids:
            errors.append(f"需求 ID 重复：{rid}")
        req_ids.add(rid)
        if not str(req.get("title", "")).strip():
            errors.append(f"{rid} 缺少评分项/需求标题")
        ev = req.get("evidence", {})
        if not isinstance(ev, dict) or not all(str(ev.get(k, "")).strip() for k in ("file", "location", "quote")):
            errors.append(f"{rid} 缺少原文证据 file/location/quote，不得以推测代替")
        mapped = req.get("response_sections", [])
        if not isinstance(mapped, list) or not mapped:
            errors.append(f"{rid} 没有对应技术响应小节")
        elif any(sid not in sec_ids for sid in mapped):
            errors.append(f"{rid} 指向不存在的小节：{[sid for sid in mapped if sid not in sec_ids]}")
        score = req.get("score")
        if score is not None and (not isinstance(score, (int, float)) or isinstance(score, bool) or not math.isfinite(score) or score < 0):
            errors.append(f"{rid} score 需要非负数字或 null")
    for sid, sec in section_lookup.items():
        for rid in sec.get("requirement_ids", []) if isinstance(sec.get("requirement_ids", []), list) else []:
            if rid not in req_ids:
                errors.append(f"{sid} 指向不存在的需求 {rid}")
            else:
                source = next((r for r in requirements if isinstance(r, dict) and r.get("id") == rid), {})
                if sid not in source.get("response_sections", []):
                    errors.append(f"{sid} 与 {rid} 的双向映射不一致")
    for req in requirements:
        if not isinstance(req, dict):
            continue
        for sid in req.get("response_sections", []) if isinstance(req.get("response_sections"), list) else []:
            if sid in section_lookup and req.get("id") not in section_lookup[sid].get("requirement_ids", []):
                errors.append(f"{req.get('id')} 与 {sid} 的双向映射不一致")

    for i, fact in enumerate(facts):
        if not isinstance(fact, dict):
            errors.append(f"facts[{i}] 必须是对象")
            continue
        key = fact.get("key")
        if not isinstance(key, str) or not key.strip():
            errors.append(f"facts[{i}] 缺少 key")
            continue
        if key in fact_keys:
            errors.append(f"事实 key 重复：{key}")
        fact_keys.add(key)
        status = fact.get("status")
        if status not in STATUS:
            errors.append(f"{key} status 必须为 verified/pending/not_specified")
        if status == "verified":
            if not str(fact.get("value", "")).strip():
                errors.append(f"{key} 已核实事实缺少值")
            ev = fact.get("evidence")
            if not isinstance(ev, dict) or not all(str(ev.get(k, "")).strip() for k in ("file", "location", "quote")):
                errors.append(f"{key} 已核实事实缺少引用证据")
        elif status == "pending":
            warnings.append(f"事实 {key} 待确认，生成正文不得填造具体值")
        elif status == "not_specified" and str(fact.get("value", "")).strip():
            errors.append(f"{key} 未提及事项不得填写推测值")
    observations.append("仅机械校验，无法替代 AI 语义评分覆盖、矛盾识别及人工终审")
    return {"ok": not errors, "errors": errors, "warnings": warnings,
            "statistics": {"requirements": len(requirements), "sections": len(sections), "facts": len(facts)},
            "notes": observations}


def allocate(root: Path, total: int):
    if total <= 0:
        raise ValueError("目标字数必须大于零")
    state = load_project(root)
    sections = state["outline.json"]["sections"]
    requirements = state["requirements.json"]["requirements"]
    if not sections:
        raise ValueError("没有目录小节，不能分配字数")
    score_map = {r["id"]: (r.get("score") or 0) for r in requirements if isinstance(r, dict) and isinstance(r.get("id"), str)}
    weights = []
    for sec in sections:
        sid = sec.get("id")
        section_path(root, sid)
        base = float(sec.get("weight", 1))
        if base <= 0 or not math.isfinite(base):
            raise ValueError(f"{sid} 权重必须为有限正数")
        score = sum(max(0.0, float(score_map.get(r, 0))) for r in sec.get("requirement_ids", []))
        weights.append(base * (1 + score))
    denominator = sum(weights)
    exact = [total * w / denominator for w in weights]
    quotas = [math.floor(x) for x in exact]
    remaining = total - sum(quotas)
    order = sorted(range(len(exact)), key=lambda i: (-(exact[i] - quotas[i]), i))
    for i in order[:remaining]:
        quotas[i] += 1
    for sec, quota in zip(sections, quotas):
        sec["target_words"] = quota
    state["project.json"]["total_words"] = total
    write_json(root / "project.json", state["project.json"])
    write_json(root / "outline.json", state["outline.json"])
    return dict(zip((s["id"] for s in sections), quotas))


def scaffold(root: Path):
    sections = read_json(root / "outline.json").get("sections", [])
    added = []
    for sec in sections:
        sid = sec["id"]
        dest = section_path(root, sid)
        if not dest.exists():
            dest.write_text(f"# {sec['title']}\n\nTODO：以招标原文证据、全局事实和评分项为依据撰写正文。\n", encoding="utf-8")
            added.append(str(dest))
    return added
