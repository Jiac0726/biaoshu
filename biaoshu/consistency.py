"""Conservative cross-section audit for explicit, unit-bearing contract commitments.

Only precise equality statements about the same category and unit are compared.
This report aids human review; it is not a semantic or legal compliance verdict.
"""
from __future__ import annotations

import re
from collections import defaultdict
from decimal import Decimal
from pathlib import Path

from .core import ID_RE, load_project, section_path

_LABELS = {
    "project_duration": ("项目工期", "施工工期", "合同工期", "工期"),
    "service_duration": ("服务期限", "服务期"),
    "warranty_duration": ("质保期限", "质保期", "保修期限", "保修期"),
    "response_time": ("响应时限", "响应时间"),
}
_KEYS = {
    "project_duration": {"project_duration", "construction_duration", "work_duration", "工期", "项目工期", "施工工期"},
    "service_duration": {"service_duration", "service_period", "服务期限", "服务期"},
    "warranty_duration": {"warranty_duration", "warranty_period", "质保期", "保修期"},
    "response_time": {"response_time", "response_period", "响应时间", "响应时限"},
}
_LABEL_PATTERN = "|".join(re.escape(label) for labels in _LABELS.values() for label in labels)
_STATEMENT = re.compile(
    rf"(?P<label>{_LABEL_PATTERN})\s*(?:[:：]|为|是|确定为|计划为|拟定为)\s*"
    r"(?P<value>\d{1,5}(?:\.\d{1,2})?)\s*"
    r"(?P<unit>小时|分钟|秒|个月|天|日|月|年)(?![年月天日小时分钟秒])"
)
_FACT_VALUE = re.compile(
    r"(?<![\d.])(?P<value>\d{1,5}(?:\.\d{1,2})?)\s*"
    r"(?P<unit>小时|分钟|秒|个月|天|日|月|年)(?![年月天日小时分钟秒])"
)
_UNIT_NAMES = {"天": "日", "日": "日", "个月": "月", "月": "月",
               "年": "年", "小时": "小时", "分钟": "分钟", "秒": "秒"}
# Skip explicitly hypothetical, example or negated clauses; these are not
# deterministic commitments and must be interpreted by a human reviewer.
_NON_ASSERTED = re.compile(r"若|如果|假如|假设|假定|例如|举例|示例|样例|并非|不是|不代表")

_DESCRIPTIONS = {
    "project_duration": "项目工期",
    "service_duration": "服务期限",
    "warranty_duration": "质保期",
    "response_time": "响应时间",
}


def _category(label: str) -> str:
    for group, labels in _LABELS.items():
        if label in labels:
            return group
    raise ValueError("未知承诺类别")


def _quantity(value: str, unit: str) -> tuple[str, str]:
    return format(Decimal(value).normalize(), "f"), _UNIT_NAMES[unit]


def _reference(fact: dict) -> tuple[str, str] | None:
    """Return one canonical value only when baseline numeric unit is unambiguous."""
    if fact.get("status") != "verified":
        return None
    value = fact.get("value")
    if not isinstance(value, str):
        value = str(value) if isinstance(value, (int, float)) else ""
    # "不超过2小时", "不少于3年" and dates are not exact facts.
    match = _FACT_VALUE.fullmatch(value.strip())
    if not match or (match.group("unit") == "年" and Decimal(match.group("value")) >= 100):
        return None
    return _quantity(match.group("value"), match.group("unit"))


def analyze_consistency(root: Path, state: dict | None = None) -> dict:
    """Return local-only section-located findings; no project data is modified."""
    root = Path(root)
    state = load_project(root) if state is None else state
    facts = state["facts.json"].get("facts", [])
    sections = state["outline.json"].get("sections", [])
    if not isinstance(facts, list) or not isinstance(sections, list):
        raise ValueError("facts 与 sections 必须是数组")
    baselines: dict[str, list[dict]] = defaultdict(list)
    pending: set[str] = set()
    mapping_findings: list[dict] = []
    generic_duration_keys = {"duration", "period", "期限", "时长"}
    for fact in facts:
        if not isinstance(fact, dict) or not isinstance(fact.get("key"), str):
            continue
        key = fact["key"].strip().lower()
        # Historically valid, free-form 'duration' fact keys must not
        # silently bypass the verified-fact comparison or be guessed into
        # an unrelated type of duration. Require an explicit category.
        if key in generic_duration_keys:
            category = fact.get("category")
            if not isinstance(category, str) or category not in _LABELS:
                if fact.get("status") == "verified":
                    mapping_findings.append({
                        "severity": "error", "code": "ambiguous_verified_duration",
                        "fact_key": fact["key"],
                        "message": (f"已核实事实 {fact['key']} 未声明期限类型："
                                    "请补 category=project_duration/service_duration/"
                                    "warranty_duration/response_time，不允许静默忽略"),
                    })
                continue
            if fact.get("status") == "pending":
                pending.add(category)
            reference = _reference(fact)
            if reference is not None:
                baselines[category].append({"key": fact["key"], "value": reference})
            continue
        for cat, aliases in _KEYS.items():
            if key not in aliases:
                continue
            if fact.get("status") == "pending":
                pending.add(cat)
            reference = _reference(fact)
            if reference is not None:
                baselines[cat].append({"key": fact["key"], "value": reference})
    observations: list[dict] = []
    inspected = 0
    for section in sections:
        sid = section.get("id") if isinstance(section, dict) else None
        if not isinstance(sid, str) or not ID_RE.fullmatch(sid):
            continue
        path = section_path(root, sid)
        if not path.is_file():
            continue
        inspected += 1
        in_code = False
        for number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
            trimmed = line.strip()
            if trimmed.startswith((chr(96) * 3, "~" * 3)):
                in_code = not in_code
                continue
            if in_code or not trimmed or trimmed.startswith((">", "#", "|")):
                continue
            # Inline Markdown emphasis is not a change of contractual meaning.
            visible = re.sub(r"\*\*|__", "", line)
            # Inline quoted history/examples aren't the current bidder's promise.
            visible = re.sub(r"“[^”]*”|「[^」]*」|‘[^’]*’", "", visible)
            for match in _STATEMENT.finditer(visible):
                # "设备供货工期" must not be mistaken for the project duration.
                if match.start() > 0 and "\u4e00" <= visible[match.start() - 1] <= "\u9fff":
                    continue
                # Bound values, approximations and calendar dates are not
                # deterministic equalities, so must not block final export.
                rest = visible[match.end():]
                if re.match(r"\s*(?:内|以内|以上|以下|左右|起|至|到|前|后|不等|\d)", rest):
                    continue
                if match.group("unit") == "年" and Decimal(match.group("value")) >= 100:
                    continue
                # Look only within the clause containing this statement.
                # Conditional examples must not become hard export blockers.
                prefix = re.split(r"[。；;！!？?]", visible[:match.start()])[-1]
                if _NON_ASSERTED.search(prefix):
                    continue
                cat = _category(match.group("label"))
                value, unit = _quantity(match.group("value"), match.group("unit"))
                observations.append({
                    "category": cat, "section_id": sid, "line": number,
                    "value": value, "unit": unit, "excerpt": trimmed[:180],
                })
    findings: list[dict] = list(mapping_findings)
    grouped: dict[tuple[str, str], list[dict]] = defaultdict(list)
    for observation in observations:
        grouped[(observation["category"], observation["unit"])].append(observation)
    for (cat, unit), entries in sorted(grouped.items()):
        distinct = {e["value"] for e in entries}
        section_ids = {e["section_id"] for e in entries}
        if len(distinct) > 1:
            findings.append({
                "severity": "error",
                "code": "cross_section_conflict" if len(section_ids) > 1 else "within_section_conflict",
                "category": cat, "description": _DESCRIPTIONS[cat], "unit": unit,
                "observations": entries,
                "message": f"{_DESCRIPTIONS[cat]}明确数值不一致：{', '.join(sorted(distinct))}{unit}；需逐句复核",
            })
    for observation in observations:
        cat = observation["category"]
        for baseline in baselines.get(cat, []):
            expected_number, expected_unit = baseline["value"]
            if observation["unit"] == expected_unit and observation["value"] != expected_number:
                findings.append({
                    "severity": "error", "code": "verified_fact_mismatch",
                    "category": cat, "description": _DESCRIPTIONS[cat],
                    "section_id": observation["section_id"], "line": observation["line"],
                    "observed": observation["value"] + observation["unit"],
                    "verified": expected_number + expected_unit,
                    "fact_key": baseline["key"], "excerpt": observation["excerpt"],
                    "message": f"{observation['section_id']} 第{observation['line']}行与已核实事实 {baseline['key']} 不一致",
                })
        if cat in pending and not baselines.get(cat):
            findings.append({
                "severity": "warning", "code": "unverified_commitment",
                "category": cat, "section_id": observation["section_id"],
                "line": observation["line"], "observed": observation["value"] + observation["unit"],
                "excerpt": observation["excerpt"],
                "message": "该类别事实仍待确认，章节却使用了确定性数值；需人工核查",
            })
    errors = [x for x in findings if x["severity"] == "error"]
    return {
        "schema_version": 1, "ok": not errors, "status": "mechanical_review_only",
        "findings": findings,
        "statistics": {"sections_inspected": inspected, "commitments_detected": len(observations),
                       "errors": len(errors), "warnings": len(findings) - len(errors)},
        "limitations": [
            "仅识别工期、服务期限、质保期、响应时间中的明确数值等式，不分析全文所有承诺",
            "通用 duration/period/期限/时长 事实键必须声明 category，否则已核实期限不参与比对并产生审查错误",
            "不同单位的数值不自动比较或换算；上下限、条件、引用原文和专业语义必须人工判断",
            "无冲突仅表示未发现上述模式的不一致，不证明内容准确、评分覆盖完整或投标合规",
        ],
    }
