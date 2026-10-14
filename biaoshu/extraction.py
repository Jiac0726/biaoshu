"""可追溯的招标原文抽取：只读取本地文件，不调用 OCR 或外部服务。"""
from __future__ import annotations

from pathlib import Path


def extract_document(source: Path) -> dict:
    """返回有序原文块和抽取警告；位置为物理页码或文档结构位置。"""
    source = Path(source)
    suffix = source.suffix.lower()
    result = {"source_file": source.name, "format": suffix.lstrip("."), "blocks": [], "warnings": []}
    blocks = result["blocks"]
    warnings = result["warnings"]

    if suffix in (".txt", ".md"):
        text = source.read_text(encoding="utf-8-sig")
        for number, line in enumerate(text.splitlines(), 1):
            if line.strip():
                blocks.append({"kind": "line", "location": f"第 {number} 行", "text": line})
        if not blocks:
            warnings.append("文本文件没有非空行，请检查文件内容。")
    elif suffix == ".pdf":
        try:
            from pypdf import PdfReader
        except ImportError as exc:
            raise RuntimeError('PDF 读取需要 pip install -e "[docs]"') from exc
        reader = PdfReader(str(source))
        for number, page in enumerate(reader.pages, 1):
            try:
                text = (page.extract_text() or "").strip()
            except Exception as exc:
                warnings.append(f"PDF 物理第 {number} 页提取失败：{type(exc).__name__}；必须核对原件。")
                continue
            if text:
                blocks.append({"kind": "page", "location": f"PDF 物理第 {number} 页", "page": number, "text": text})
            else:
                warnings.append(f"PDF 物理第 {number} 页未提取到文本：可能是空白页、扫描图或特殊排版，必须人工核对。")
        if not blocks:
            raise ValueError("PDF 全部页面均无可提取文本，可能为扫描件；需 OCR 并人工检查")
        warnings.append("PDF 页码为物理页序号，不一定等于文档印刷页码；表格阅读顺序须对照原件。")
    elif suffix == ".docx":
        try:
            from docx import Document
            from docx.table import Table
            from docx.text.paragraph import Paragraph
        except ImportError as exc:
            raise RuntimeError('DOCX 读取需要 pip install -e "[docs]"') from exc
        doc = Document(str(source))
        para_no = 0
        table_no = 0
        for body_no, item in enumerate(doc.iter_inner_content(), 1):
            if isinstance(item, Paragraph):
                para_no += 1
                if item.text.strip():
                    blocks.append({"kind": "paragraph", "location": f"正文块 {body_no}/段落 {para_no}",
                                   "body_index": body_no, "paragraph": para_no, "text": item.text})
            elif isinstance(item, Table):
                table_no += 1
                for row_no, row in enumerate(item.rows, 1):
                    for col_no, cell in enumerate(row.cells, 1):
                        if cell.text.strip():
                            blocks.append({"kind": "table_cell",
                                           "location": f"正文块 {body_no}/表格 {table_no}/行 {row_no}/列 {col_no}",
                                           "body_index": body_no, "table": table_no, "row": row_no,
                                           "column": col_no, "text": cell.text})
        if not blocks:
            warnings.append("DOCX 正文没有可提取的段落或表格单元格，请核对是否为图片/文本框。")
        warnings.append("DOCX 结构位置不是页码；页眉页脚、文本框、批注和修订内容可能未完整提取，须人工核对。")
        warnings.append("DOCX 合并单元格可能重复出现；表格单元格位置是读取位置而非唯一物理单元格标识。")
    else:
        raise ValueError("当前支持 .txt、.md、.pdf、.docx")
    return result


def to_markdown(document: dict) -> str:
    """将有序原文块转换为带定位标记的 Markdown，不推断原文缺失内容。"""
    lines = []
    for warning in document["warnings"]:
        lines.append(f"> 抽取提醒：{warning}")
    if lines:
        lines.append("")
    for block in document["blocks"]:
        lines.append(f"### {block['location']}")
        lines.append("")
        lines.append(block["text"])
        lines.append("")
    return "\n".join(lines).rstrip() + "\n"


def extract_source(source: Path) -> str:
    """兼容旧 CLI 入口，返回带定位信息的 Markdown。"""
    return to_markdown(extract_document(source))
