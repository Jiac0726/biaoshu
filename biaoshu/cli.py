"""可直接运行：python -m biaoshu --help"""
from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

from .core import allocate, initialize, inspect, load_project, scaffold, write_json


def extract_source(source: Path) -> str:
    suffix = source.suffix.lower()
    if suffix in (".txt", ".md"):
        return source.read_text(encoding="utf-8-sig")
    if suffix == ".pdf":
        try:
            from pypdf import PdfReader
        except ImportError as exc:
            raise RuntimeError('PDF 读取需要 pip install -e ".[docs]"') from exc
        pages = []
        reader = PdfReader(str(source))
        for index, page in enumerate(reader.pages, 1):
            text = (page.extract_text() or "").strip()
            pages.append(f"## {source.name} / 第 {index} 页\n\n{text}\n")
        if not any(page.extract_text() for page in reader.pages):
            raise ValueError("PDF 无可提取文本，可能为扫描件，需先 OCR 并人工检查")
        return "\n".join(pages)
    if suffix == ".docx":
        try:
            from docx import Document
        except ImportError as exc:
            raise RuntimeError('DOCX 读取需要 pip install -e ".[docs]"') from exc
        doc = Document(str(source))
        paragraphs = [p.text for p in doc.paragraphs if p.text.strip()]
        tables = []
        for i, table in enumerate(doc.tables, 1):
            rows = [" | ".join(cell.text.replace("\n", " / ") for cell in row.cells) for row in table.rows]
            tables.append(f"\n### 表格 {i}\n" + "\n".join(rows))
        return "\n".join(paragraphs + tables)
    raise ValueError("当前支持 .txt、.md、.pdf、.docx")


def export_docx(root: Path, dest: Path, draft: bool):
    report = inspect(root, strict=True)
    if not report["ok"] and not draft:
        raise ValueError("导出被严格审查阻止；先修复错误，或使用 --draft 输出明确标记的草稿")
    try:
        from docx import Document
        from docx.shared import Pt
    except ImportError as exc:
        raise RuntimeError('DOCX 导出需要 pip install -e ".[docs]"') from exc
    state = load_project(root)
    document = Document()
    title = state["project.json"].get("project_name") or "未命名项目"
    document.add_heading(f"{title} — 技术投标文件" + ("（草稿，未完成校验）" if draft else ""), 0)
    for sec in state["outline.json"]["sections"]:
        document.add_heading(str(sec["title"]), level=1)
        path = root / "sections" / (sec["id"] + ".md")
        if not path.exists():
            document.add_paragraph(f"[缺少正文：{sec['id']}]")
            continue
        for raw in path.read_text(encoding="utf-8").splitlines():
            line = raw.strip()
            if not line:
                continue
            if line.startswith("#"):
                text = line.lstrip("#").strip()
                if text and text != sec["title"]:
                    document.add_heading(text, level=min(len(line) - len(line.lstrip("#")) + 1, 4))
            elif re.match(r"^[-*]\s+", line):
                document.add_paragraph(re.sub(r"^[-*]\s+", "", line), style="List Bullet")
            elif re.match(r"^\d+[.)]\s+", line):
                document.add_paragraph(re.sub(r"^\d+[.)]\s+", "", line), style="List Number")
            else:
                document.add_paragraph(line)
    for style in ("Normal",):
        document.styles[style].font.size = Pt(11)
    dest.parent.mkdir(parents=True, exist_ok=True)
    document.save(str(dest))
    return report


def main(argv=None):
    parser = argparse.ArgumentParser(prog="biaoshu", description="技术标 Skill 的确定性工具层")
    sub = parser.add_subparsers(dest="command", required=True)
    command_root = ("init", "check", "audit", "allocate", "scaffold", "export")
    for name in command_root:
        cmd = sub.add_parser(name)
        cmd.add_argument("project_dir", type=Path)
        if name == "allocate":
            cmd.add_argument("--total", type=int, required=True, help="全文 AI 正文目标字数")
        if name == "export":
            cmd.add_argument("--output", type=Path, required=True)
            cmd.add_argument("--draft", action="store_true")
        if name in ("check", "audit"):
            cmd.add_argument("--output", type=Path, help="保存校验报告 JSON")
    ext = sub.add_parser("extract")
    ext.add_argument("source", type=Path)
    ext.add_argument("--output", type=Path, required=True)
    args = parser.parse_args(argv)
    try:
        if args.command == "init":
            initialize(args.project_dir)
            print(f"已初始化：{args.project_dir}")
        elif args.command == "extract":
            extracted = extract_source(args.source)
            args.output.parent.mkdir(parents=True, exist_ok=True)
            args.output.write_text(f"# 招标原文提取\n\n来源：{args.source.name}\n\n{extracted}\n", encoding="utf-8")
            print(f"已提取：{args.output}。请人工核对页码、表格和缺失文本。")
        elif args.command in ("check", "audit"):
            report = inspect(args.project_dir, strict=args.command == "audit")
            if args.output:
                write_json(args.output, report)
            print(f"{'通过' if report['ok'] else '未通过'}｜{report['statistics']}")
            for label, key in (("错误", "errors"), ("提示", "warnings")):
                for entry in report[key]:
                    print(f"{label}：{entry}")
            return 0 if report["ok"] else 1
        elif args.command == "allocate":
            result = allocate(args.project_dir, args.total)
            for sid, count in result.items():
                print(f"{sid}: {count} 字")
        elif args.command == "scaffold":
            result = scaffold(args.project_dir)
            print(f"新建 {len(result)} 个章节文件（不会覆盖已有正文）")
        elif args.command == "export":
            report = export_docx(args.project_dir, args.output, args.draft)
            print(f"已导出：{args.output}；机械审查：{'通过' if report['ok'] else '未通过'}")
        return 0
    except (OSError, ValueError, RuntimeError, KeyError, TypeError) as exc:
        print(f"操作失败：{exc}", file=sys.stderr)
        return 2
