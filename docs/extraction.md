# 原文抽取：位置标记与验证

从 v0.2 起，`extract` 命令提供两种输出：带来源位置的 Markdown，以及可选的 JSON 原文块。

```bash
python -m biaoshu extract ./tender.docx --output ./extracted.md --json-output ./extracted.json
```

JSON 包含 `source_file`、`format`、`blocks`、`warnings`。每个 block 具有 `kind`、`location`、`text`，PDF 额外提供 `page`，DOCX 提供正文块索引和段落序号或表格行列。

- TXT/MD：保留原始行号（从 1 开始）；空行不生成块，但计入行号。
- PDF：页码是 PDF 物理页序号，并非印刷页码；任何未提取到文本的页面都会提示复核。整份 PDF 无可提取文本则报错。
- DOCX：按正文原始顺序输出段落与表格单元格，位置为正文块/表格/行/列。不能由此推算 Word 页码。
- 局限：PDF 表格阅读顺序、扫描图片、DOCX 文本框与页眉页脚、合并单元格仍需原件核对。

抽取输出只是定位辅助；填写招标条款证据时必须回看原始文件，不能把抽取成功等同于要求识别完整。

验证：`python -m unittest discover -s tests -v`。
