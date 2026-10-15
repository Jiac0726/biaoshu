"""Source-locked response paragraph register for technical bid reviewer sign-off.

Every requirement-to-section link needs its own reviewer-selected response line.
This only proves a selected quote is still at that precise local file location;
it does not establish that the paragraph semantically satisfies the tender.
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path

from .core import ID_RE, load_project, read_json, section_path, write_json

TRACE_NAME = "response-trace.json"
ACKNOWLEDGEMENT = "我已逐项核对评分要求和正文段落，并确认上述定位引用为实际技术响应"


def trace_path(root: Path) -> Path:
    return Path(root) / "reports" / TRACE_NAME


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _identity(state: dict) -> tuple[str, list[tuple[str, str]]]:
    reqs = state["requirements.json"]["requirements"]
    sections = state["outline.json"]["sections"]
    if not isinstance(reqs, list) or not isinstance(sections, list):
        raise ValueError("requirements 和 outline.sections 必须是数组")
    names = []
    pairs = []
    for req in reqs:
        if not isinstance(req, dict) or not isinstance(req.get("id"), str):
            raise ValueError("存在无效需求")
        rid, title = req["id"], req.get("title")
        mapped = req.get("response_sections")
        if not ID_RE.fullmatch(rid) or not isinstance(title, str) or not title.strip():
            raise ValueError("需求 ID 或标题不合法")
        if not isinstance(mapped, list) or not mapped:
            raise ValueError(f"{rid} 未设置响应章节")
        names.append({"id": rid, "title": title, "sections": mapped})
        for sid in mapped:
            if not isinstance(sid, str) or not ID_RE.fullmatch(sid):
                raise ValueError(f"{rid} 响应章节 ID 不合法")
            pairs.append((rid, sid))
    section_meta = []
    for section in sections:
        if not isinstance(section, dict):
            raise ValueError("存在无效章节")
        sid = section.get("id")
        if not isinstance(sid, str) or not ID_RE.fullmatch(sid):
            raise ValueError("章节 ID 不合法")
        section_meta.append({"id": sid, "title": section.get("title"),
                             "requirement_ids": section.get("requirement_ids")})
    payload = {"requirements": names, "sections": section_meta}
    fingerprint = hashlib.sha256(json.dumps(payload, ensure_ascii=False, sort_keys=True,
                                            separators=(",", ":")).encode("utf-8")).hexdigest()
    if len(set(pairs)) != len(pairs):
        raise ValueError("要求与章节之间存在重复映射")
    if not pairs:
        raise ValueError("没有可建立响应定位的正式需求")
    return fingerprint, pairs


def create_trace(root: Path) -> dict:
    """Create a pending review document; never auto-confirm or overwrite."""
    root = Path(root)
    target = trace_path(root)
    if target.exists():
        raise ValueError("响应定位台账已存在，禁止覆盖已进行的审核")
    state = load_project(root)
    fingerprint, pairs = _identity(state)
    entries = []
    for rid, sid in pairs:
        path = section_path(root, sid)
        if not path.is_file():
            raise ValueError(f"章节正文不存在：{sid}；请在写作完成后创建追溯台账")
        entries.append({
            "requirement_id": rid, "section_id": sid,
            "section_sha256": _sha(path), "line": None, "quote": "",
            "decision": "pending",
        })
    template = {
        "schema_version": 1,
        "status": "review_template",
        "mapping_sha256": fingerprint,
        "acknowledgement": "",
        "items": entries,
        "instructions": ("人工阅读原文评分项和章节正文后，为每一项填写 "
                         "line（1起始的正文行号）、quote（该行内有意义的连续响应原句）、"
                         "decision=confirmed；未确认的不能写 confirmed。"
                         "最后由审稿人亲自填写 acknowledgement。"),
    }
    write_json(target, template)
    return {"path": str(target), "items": len(entries), "status": "pending_review"}


def audit_trace(root: Path) -> dict:
    """Revalidate reviewed paragraph locations against current project bytes."""
    root = Path(root)
    target = trace_path(root)
    findings = []

    def issue(code: str, message: str, requirement_id: str | None = None,
              section_id: str | None = None):
        findings.append({"severity": "error", "code": code, "message": message,
                         "requirement_id": requirement_id, "section_id": section_id})

    if not target.is_file():
        issue("trace_missing", "未创建响应定位台账；尚未逐条核实评分需求的正文响应")
        return _result(findings, 0, 0, "not_started")
    try:
        state = load_project(root)
        digest, pairs = _identity(state)
        document = read_json(target)
        if not isinstance(document, dict) or document.get("schema_version") != 1 or not isinstance(document.get("items"), list):
            raise ValueError("台账结构不合法")
    except (OSError, ValueError, TypeError, KeyError) as exc:
        issue("trace_unreadable", f"无法读取或校验响应定位台账：{exc}")
        return _result(findings, 0, 0, "invalid")

    if document.get("mapping_sha256") != digest:
        issue("mapping_changed", "评分需求标题、章节归属或目录章节信息已变动，请重新核对响应台账")
    if document.get("acknowledgement") != ACKNOWLEDGEMENT:
        issue("review_acknowledgement_missing", "需要真实审稿人逐项复核后填写指定确认语句")

    expected = set(pairs)
    listed = set()
    confirmed = 0
    for i, item in enumerate(document["items"], 1):
        if not isinstance(item, dict):
            issue("invalid_item", f"第 {i} 条台账不是对象")
            continue
        rid, sid = item.get("requirement_id"), item.get("section_id")
        if not isinstance(rid, str) or not isinstance(sid, str):
            issue("invalid_item", f"第 {i} 条需求 ID 或章节 ID 格式无效")
            continue
        key = (rid, sid)
        if key in listed:
            issue("duplicate_item", "重复的需求→章节定位", rid, sid)
            continue
        listed.add(key)
        if key not in expected:
            issue("unexpected_item", "台账包含已不属于正式响应关系的项目", rid, sid)
            continue
        try:
            path = section_path(root, sid)
        except ValueError:
            issue("unsafe_section", "章节 ID 不合法", rid, sid)
            continue
        if not path.is_file():
            issue("missing_section", "对应正文不存在", rid, sid)
            continue
        if not isinstance(item.get("section_sha256"), str) or item["section_sha256"] != _sha(path):
            issue("section_changed", "正文与审核开始时不同，必须重新定位并复核", rid, sid)
            continue
        if item.get("decision") != "confirmed":
            issue("pending_review", "该需求响应尚未经人工确认", rid, sid)
            continue
        line = item.get("line")
        quote = item.get("quote")
        if (isinstance(line, bool) or not isinstance(line, int) or line < 1
                or not isinstance(quote, str) or len(quote.strip()) < 12
                or "\n" in quote or "\r" in quote):
            issue("invalid_location", "行号或引用原句缺失、过短或不是单行文本", rid, sid)
            continue
        lines = path.read_text(encoding="utf-8").splitlines()
        if line > len(lines):
            issue("invalid_location", f"原文只有 {len(lines)} 行，不存在第 {line} 行", rid, sid)
            continue
        actual = lines[line - 1].strip()
        # Exclude both the fence markers and every line inside a fenced block.
        # A snippet of source/code is not a bid response paragraph.
        in_code = False
        for previous in lines[:line]:
            if previous.strip().startswith((chr(96) * 3, "~" * 3)):
                in_code = not in_code
        if (not actual or actual.startswith(("#", ">", "|", chr(96) * 3, "~" * 3))
                or in_code):
            issue("non_prose_evidence", "引用位置不是正文响应段落", rid, sid)
            continue
        if quote.strip() not in actual:
            issue("quote_mismatch", "引用原句不在指定章节行号处", rid, sid)
            continue
        confirmed += 1
    for rid, sid in sorted(expected - listed):
        issue("missing_item", "评分需求缺少关联章节的响应定位", rid, sid)
    return _result(findings, len(expected), confirmed, "reviewed" if not findings else "incomplete")


def _result(findings: list[dict], required: int, confirmed: int, status: str) -> dict:
    return {
        "schema_version": 1, "status": status, "ok": not findings,
        "statistics": {"expected_links": required, "confirmed_links": confirmed,
                       "errors": len(findings)},
        "findings": findings,
        "limitations": [
            "confirmed 是操作者声明，程序只校验来源正文文件、行号和引用原句",
            "台账审查不能证明章节真正满足评分标准、评价档次或否决性条款",
            "应逐项结合招标文件原文与整段正文做专业语义审查和最终人工确认",
        ],
    }
