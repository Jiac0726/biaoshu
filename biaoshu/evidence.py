"""Verify recorded tender citations against extracted source blocks and source bytes.

This is deterministic text matching, not semantic or legal verification.
"""
from __future__ import annotations

import hashlib
import json
import re
import unicodedata
from pathlib import Path

_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")


def _normalized(text: str) -> str:
    # PDF line wrapping and full-width variants are common; punctuation remains significant.
    return "".join(unicodedata.normalize("NFKC", text).split())


def _digest(path: Path) -> str:
    checksum = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            checksum.update(chunk)
    return checksum.hexdigest()


def verify_evidence(project_dir: Path, index_paths: list[Path], source_dir: Path) -> dict:
    """Check every requirement and verified fact against a source-locked index.

    Evidence uses exact file and location values from the index, while
    quote is a substring of the indexed block after whitespace/NFKC cleanup.
    The source file must be present and SHA-256-identical to the indexed file.
    An index alone never counts as a verified source.
    """
    project_dir = Path(project_dir)
    source_dir = Path(source_dir).resolve()
    errors: list[dict[str, str]] = []
    warnings: list[str] = []
    summary = {"indexes": 0, "checked": 0, "matched": 0, "failed": 0}
    sources: dict[str, dict] = {}
    seen_names: set[str] = set()

    def error(code: str, subject: str, message: str):
        errors.append({"code": code, "subject": subject, "message": message})

    if not index_paths:
        error("no_indexes", "indexes", "至少提供一个 --index 证据索引")
    if not source_dir.is_dir():
        error("missing_source_dir", "sources", f"原文件目录不存在：{source_dir}")

    for index_path in index_paths:
        index_path = Path(index_path)
        try:
            index = json.loads(index_path.read_text(encoding="utf-8"))
        except (OSError, ValueError, UnicodeError) as exc:
            error("index_unreadable", str(index_path), f"索引无法读取：{exc}")
            continue
        if not isinstance(index, dict):
            error("invalid_index", str(index_path), "索引根节点必须是对象")
            continue
        name, digest, blocks = index.get("source_file"), index.get("sha256"), index.get("blocks")
        if (index.get("schema_version") != 1 or not isinstance(name, str) or not name
                or Path(name).name != name or "\\" in name or name in {".", ".."}
                or not isinstance(digest, str) or not _SHA256_RE.fullmatch(digest)
                or not isinstance(blocks, list) or not blocks
                or any(not isinstance(b, dict) or not isinstance(b.get("location"), str)
                       or not b["location"].strip() or not isinstance(b.get("text"), str)
                       or not b["text"].strip() for b in blocks)):
            error("invalid_index", str(index_path), "索引版本、文件名、SHA-256 或文本块不符合 v1 格式")
            continue
        if name in seen_names:
            error("duplicate_source", name, "多个索引指向同名源文件；请先消除歧义")
            sources.pop(name, None)
            continue
        seen_names.add(name)
        source = (source_dir / name).resolve()
        if not source.is_relative_to(source_dir):
            error("unsafe_source", name, "源文件路径超出指定目录")
            continue
        if not source.is_file():
            error("source_missing", name, "原始招标文件不存在，不能仅凭索引核实证据")
            continue
        try:
            current_digest = _digest(source)
        except OSError as exc:
            error("source_unreadable", name, f"无法读取原始文件：{exc}")
            continue
        if current_digest != digest:
            error("source_changed", name, "原始文件 SHA-256 与提取时不同，必须重新提取和核对")
            continue
        sources[name] = index
        summary["indexes"] += 1
        for warning in index.get("warnings", []) if isinstance(index.get("warnings"), list) else []:
            warnings.append(f"{name}：{warning}")

    try:
        requirements = json.loads((project_dir / "requirements.json").read_text(encoding="utf-8"))["requirements"]
        facts = json.loads((project_dir / "facts.json").read_text(encoding="utf-8"))["facts"]
        if not isinstance(requirements, list) or not isinstance(facts, list):
            raise ValueError("requirements/facts 必须为数组")
    except (OSError, ValueError, KeyError, TypeError, UnicodeError) as exc:
        error("project_unreadable", str(project_dir), f"无法读取项目需求和事实：{exc}")
        return {"ok": False, "errors": errors, "warnings": warnings, "summary": summary}

    entries: list[tuple[str, object]] = []
    for i, requirement in enumerate(requirements):
        if isinstance(requirement, dict):
            entries.append((f"requirement:{requirement.get('id', i)}", requirement.get("evidence")))
        else:
            error("invalid_requirement", f"requirements[{i}]", "需求必须为对象")
    for i, fact in enumerate(facts):
        if not isinstance(fact, dict):
            error("invalid_fact", f"facts[{i}]", "事实必须为对象")
        elif fact.get("status") == "verified":
            entries.append((f"fact:{fact.get('key', i)}", fact.get("evidence")))
    if not entries:
        error("no_evidence", "project", "没有可核验的需求或已核实事实")

    for subject, evidence in entries:
        summary["checked"] += 1
        if not isinstance(evidence, dict) or any(
                not isinstance(evidence.get(key), str) or not evidence[key].strip()
                for key in ("file", "location", "quote")):
            error("evidence_incomplete", subject, "缺少 file/location/quote 字符串")
            continue
        name, location, quote = (evidence[key].strip() for key in ("file", "location", "quote"))
        if name not in sources:
            error("source_unverified", subject, f"来源 {name} 没有通过原始文件指纹验证的索引")
            continue
        blocks = [block for block in sources[name]["blocks"] if block["location"] == location]
        if not blocks:
            error("location_not_found", subject, f"{name} 中不存在定位 {location}")
            continue
        normalized_quote = _normalized(quote)
        if not normalized_quote or not any(normalized_quote in _normalized(block["text"]) for block in blocks):
            error("quote_mismatch", subject, f"引文与 {name} / {location} 的原文文本不匹配")
            continue
        summary["matched"] += 1

    summary["failed"] = summary["checked"] - summary["matched"]
    warnings.append("文本匹配不证明评分项完整、引文语义正确或投标合规；PDF/Word 复杂版式需人工核对")
    return {"ok": not errors, "errors": errors, "warnings": warnings, "summary": summary}
