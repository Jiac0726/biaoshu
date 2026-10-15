"""Conservative, source-locked candidate discovery for technical scoring criteria.

This is a triage tool, not an AI interpreter and not an exhaustive score parser.
Candidates must be reviewed before entering requirements.json.
"""
from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path

_SHA256 = re.compile(r"[0-9a-f]{64}\Z")
_SCORE = re.compile(r"(?<![\d.])(?P<score>\d{1,3}(?:\.\d{1,2})?)\s*分(?!钟|期|之)")
_TECH = re.compile(r"技术|施工|实施|组织|质量|安全|保障|应急|服务|运维|售后|培训|项目管理|团队|配置|进度|工艺|方案|措施|设计|交付|创新|设备")
_EXCLUDED = re.compile(r"报价|价格|投标价|价格分|商务评分|商务评审|经济标|资格审查|保证金")
_CONTEXT = re.compile(r"技术.{0,6}(?:评审|评分|得分)|(?:评审|评分)因素|评分标准|技术方案评分")
_HEADING = re.compile(r"\A\s*(?:[一二三四五六七八九十]+[、.]|\d+[、.])?\s*(?:技术评分|技术评审|评分标准|评分因素|技术方案评分)\s*[:：]?\s*\Z")
_COLUMN = re.compile(r"列\d+\s*[：:]\s*")


def _hash_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024)):
            digest.update(chunk)
    return digest.hexdigest()


def _source_index(index_path: Path, source_dir: Path) -> dict:
    try:
        data = json.loads(index_path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise ValueError(f"无法读取证据索引 {index_path}: {exc}") from exc
    if not isinstance(data, dict) or data.get("schema_version") != 1:
        raise ValueError(f"不支持的索引格式：{index_path}")
    name, digest, blocks = data.get("source_file"), data.get("sha256"), data.get("blocks")
    if (not isinstance(name, str) or not name or name in {".", ".."}
            or Path(name).name != name or "\\" in name
            or not isinstance(digest, str) or not _SHA256.fullmatch(digest)
            or not isinstance(blocks, list) or not blocks):
        raise ValueError(f"索引文件名、指纹或文本块无效：{index_path}")
    for block in blocks:
        if (not isinstance(block, dict) or not isinstance(block.get("location"), str)
                or not block["location"].strip() or not isinstance(block.get("text"), str)):
            raise ValueError(f"索引存在非法文本块：{index_path}")
    source = (source_dir / name).resolve()
    if not source.is_relative_to(source_dir) or not source.is_file():
        raise ValueError(f"缺少安全可访问的招标原件：{name}")
    if _hash_file(source) != digest:
        raise ValueError(f"招标原件已变化，必须重新提取索引：{name}")
    return data


def _candidate_parts(raw: str, technical_context: bool) -> tuple[str, float] | None:
    if _EXCLUDED.search(raw):
        return None
    matches = list(_SCORE.finditer(raw))
    if not matches or (not _TECH.search(raw) and not technical_context):
        return None
    if len(matches) != 1:
        return None
    score = float(matches[0].group("score"))
    if score > 100:
        return None
    before = raw[:matches[0].start()]
    if _COLUMN.search(raw):
        columns = [c.strip(" ：:|；;，,（）()") for c in _COLUMN.split(raw) if c.strip()]
        title = next((c for c in columns if _TECH.search(c) and not _SCORE.search(c)), "")
        if not title:
            return None
    else:
        title = re.sub(r"\A\s*(?:[一二三四五六七八九十]+[、.]|\d+[、.])?\s*(?:技术评分|技术评审|评分项目|评分因素)\s*[:：]?", "", before)
        title = re.sub(r"[（(]?\s*\Z", "", title).strip(" ：:|；;，（）()\t")
        title = re.split(r"[：:|;；（(]", title, maxsplit=1)[0].strip()
    if not title or len(title) > 60:
        return None
    if re.search(r"(?:得分|评分标准|最高分|满分|扣分|加分|总分|评标办法|分值)", title):
        return None
    return title, score


def discover_score_candidates(index_paths: list[Path], source_dir: Path) -> dict:
    """Return unapproved, evidence-backed suggestions; never edit requirements.json."""
    source_dir = Path(source_dir).resolve()
    if not source_dir.is_dir():
        raise ValueError(f"原始招标文件目录不存在：{source_dir}")
    if not index_paths:
        raise ValueError("至少提供一个 --index 证据索引")
    names: set[str] = set()
    proposals: list[dict] = []
    skipped = 0
    source_warnings: list[str] = []
    for p in index_paths:
        index = _source_index(Path(p), source_dir)
        name = index["source_file"]
        if name in names:
            raise ValueError(f"同名原件存在多个索引，无法可靠归属：{name}")
        names.add(name)
        source_warnings.extend(f"{name}：{w}" for w in index.get("warnings", []) if isinstance(w, str))
        context = False
        for block in index["blocks"]:
            text = block["text"]
            location = block["location"]
            lines = text.splitlines() if "\n" in text else [text]
            for line in lines:
                line = line.strip()
                if not line:
                    continue
                if _HEADING.fullmatch(line):
                    context = True
                    continue
                if re.match(r"(?:商务|报价|价格|资格).{0,8}(?:评分|评审)", line):
                    context = False
                parsed = _candidate_parts(line, context)
                if not parsed:
                    if _SCORE.search(line):
                        skipped += 1
                    continue
                title, score = parsed
                proposals.append({
                    "id": f"C{len(proposals) + 1}",
                    "title": title,
                    "score": score,
                    "evidence": {"file": name, "location": location, "quote": line},
                    "status": "pending_review",
                })
    return {
        "schema_version": 1,
        "status": "suggestions_only",
        "source_count": len(names),
        "candidates": proposals,
        "warnings": [
            "规则匹配仅提出候选，可能漏检合并单元格、无分值要求或多段评分规则；不能直接导入 requirements.json。",
            "必须由 Agent 比对原文，剔除商务/资格/价格评分项，再确认标题、分值和响应章节。",
            *source_warnings,
        ],
        "statistics": {"suggested": len(proposals), "ambiguous_scoring_lines": skipped},
    }
