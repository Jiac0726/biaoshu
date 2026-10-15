"""Extract tender text with stable source locations and a machine-readable evidence index.

This module deliberately performs *no* OCR and does not infer facts from the text.
"""
from __future__ import annotations

import hashlib
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class ExtractionResult:
    markdown: str
    index: dict


def _md_cell(text: str) -> str:
    """Keep extracted text readable without creating accidental Markdown columns."""
    return text.replace("\\", "\\\\").replace("|", "\\|").replace("\n", " / ")


def extract_document(source: Path) -> ExtractionResult:
    """Return readable text and an index of exact, source-located text blocks.

    Each index block has ``location``, ``kind`` and ``text``. The location is a
    stable locator *within the same source version*, not a verified quotation.
    ``sha256`` lets later evidence checks detect a replaced source document.
    """
    source = Path(source)
    suffix = source.suffix.lower()
    if suffix not in {".txt", ".md", ".pdf", ".docx"}:
        raise ValueError("当前支持 .txt、.md、.pdf、.docx")
    digest = hashlib.sha256(source.read_bytes()).hexdigest()
    blocks: list[dict[str, str]] = []
    markdown: list[str] = []
    warnings: list[str] = []

    def add(location: str, kind: str, text: str):
        if text.strip():
            blocks.append({"location": location, "kind": kind, "text": text.strip()})

    if suffix in {".txt", ".md"}:
        content = source.read_text(encoding="utf-8-sig")
        for line_number, line in enumerate(content.splitlines(), 1):
            add(f"第{line_number}行", "line", line)
        markdown.append(content)

    elif suffix == ".pdf":
        try:
            from pypdf import PdfReader
        except ImportError as exc:
            raise RuntimeError('PDF 读取需要 pip install -e ".[docs]"') from exc
        reader = PdfReader(str(source))
        for page_number, page in enumerate(reader.pages, 1):
            content = (page.extract_text() or "").strip()
            location = f"第{page_number}页"
            if not content:
                warnings.append(f"{location} 未提取到文本，可能是扫描页、图片或空白页，需人工检查")
            add(location, "page", content)
            markdown.append(f"## {location}\n\n{content or '（无可提取文本，需核对原页）'}\n")
        warnings.append("PDF 表格、页眉页脚、双栏顺序及页内坐标未做可靠还原，引用前请核对原页")

    else:
        try:
            from docx import Document
            from docx.table import Table
        except ImportError as exc:
            raise RuntimeError('DOCX 读取需要 pip install -e ".[docs]"') from exc
        document = Document(str(source))
        paragraph_number = 0
        table_number = 0
        # iter_inner_content keeps paragraphs and tables in the document-body order.
        # It does not include headers, footers, floating text boxes or comments.
        for item in document.iter_inner_content():
            if isinstance(item, Table):
                table_number += 1
                markdown.append(f"\n### 第{table_number}表\n")
                for row_number, row in enumerate(item.rows, 1):
                    cells = [cell.text.strip() for cell in row.cells]
                    location = f"第{table_number}表第{row_number}行"
                    raw_text = " | ".join(f"列{i}：{value}" for i, value in enumerate(cells, 1))
                    add(location, "table_row", raw_text)
                    markdown.append(f"- {location}：" + " | ".join(
                        f"列{i}：{_md_cell(value)}" for i, value in enumerate(cells, 1)))
            else:
                paragraph_number += 1
                content = item.text.strip()
                if content:
                    location = f"第{paragraph_number}段"
                    add(location, "paragraph", content)
                    markdown.append(f"[{location}] {content}")
        warnings.append("DOCX 页码依赖排版环境，位置使用正文段落/表格行；页眉、页脚、文本框及批注未覆盖")

    if not blocks:
        raise ValueError("文件没有可提取文本；扫描件需先 OCR 并人工核对，空文件不能建立证据索引")
    index = {
        "schema_version": 1,
        "source_file": source.name,
        "sha256": digest,
        "format": suffix.lstrip("."),
        "blocks": blocks,
        "warnings": warnings,
    }
    return ExtractionResult(markdown="\n".join(markdown).strip() + "\n", index=index)
