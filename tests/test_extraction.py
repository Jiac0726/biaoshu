import json
import tempfile
import unittest
from pathlib import Path

from biaoshu.extraction import extract_document, extract_source, to_markdown


class ExtractionTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)

    def tearDown(self):
        self.temp.cleanup()

    def test_text_line_positions_and_utf8_bom(self):
        path = self.root / "tender.txt"
        path.write_text("\ufeff第一条\n\n第二条\n", encoding="utf-8")
        data = extract_document(path)
        self.assertEqual([x["location"] for x in data["blocks"]], ["第 1 行", "第 3 行"])
        self.assertEqual([x["text"] for x in data["blocks"]], ["第一条", "第二条"])
        self.assertIn("第 3 行", extract_source(path))
        self.assertEqual(json.loads(json.dumps(data, ensure_ascii=False)), data)

    def test_docx_preserves_interleaved_paragraph_and_table_order(self):
        try:
            from docx import Document
        except ImportError:
            self.skipTest("python-docx optional dependency is not installed")
        path = self.root / "tender.docx"
        doc = Document()
        doc.add_paragraph("第一段：项目概况")
        table = doc.add_table(rows=2, cols=2)
        table.cell(0, 0).text = "技术评分"
        table.cell(0, 1).text = "10分"
        table.cell(1, 0).text = "实施方案"
        table.cell(1, 1).text = "按原文响应"
        doc.add_paragraph("第二段：后续条款")
        doc.save(path)
        data = extract_document(path)
        self.assertEqual([x["kind"] for x in data["blocks"]],
                         ["paragraph", "table_cell", "table_cell", "table_cell", "table_cell", "paragraph"])
        self.assertEqual([x["text"] for x in data["blocks"]],
                         ["第一段：项目概况", "技术评分", "10分", "实施方案", "按原文响应", "第二段：后续条款"])
        self.assertEqual(data["blocks"][3]["location"], "正文块 2/表格 1/行 2/列 1")
        self.assertEqual(data["blocks"][-1]["body_index"], 3)
        self.assertIn("DOCX 结构位置不是页码", to_markdown(data))

    def test_pdf_page_positions_and_blank_page_warning(self):
        try:
            from pypdf import PdfWriter
            from pypdf.generic import NameObject, DictionaryObject, DecodedStreamObject
        except ImportError:
            self.skipTest("pypdf optional dependency is not installed")
        path = self.root / "tender.pdf"
        writer = PdfWriter()
        for text in ("Technical requirements", None, "Scoring method"):
            page = writer.add_blank_page(width=400, height=500)
            if text:
                font = writer._add_object(DictionaryObject({
                    NameObject("/Type"): NameObject("/Font"),
                    NameObject("/Subtype"): NameObject("/Type1"),
                    NameObject("/BaseFont"): NameObject("/Helvetica"),
                }))
                page[NameObject("/Resources")] = DictionaryObject({
                    NameObject("/Font"): DictionaryObject({NameObject("/F1"): font}),
                })
                stream = DecodedStreamObject()
                stream.set_data(f"BT /F1 12 Tf 50 300 Td ({text}) Tj ET".encode("ascii"))
                page[NameObject("/Contents")] = writer._add_object(stream)
        with path.open("wb") as stream:
            writer.write(stream)
        data = extract_document(path)
        self.assertEqual([b["page"] for b in data["blocks"]], [1, 3])
        self.assertTrue(any("第 2 页未提取到文本" in x for x in data["warnings"]))
        self.assertTrue(any("物理页序号" in x for x in data["warnings"]))

    def test_all_blank_pdf_is_blocked(self):
        try:
            from pypdf import PdfWriter
        except ImportError:
            self.skipTest("pypdf optional dependency is not installed")
        path = self.root / "blank.pdf"
        writer = PdfWriter()
        writer.add_blank_page(width=300, height=400)
        with path.open("wb") as stream:
            writer.write(stream)
        with self.assertRaisesRegex(ValueError, "OCR"):
            extract_document(path)

    def test_unsupported_format(self):
        with self.assertRaisesRegex(ValueError, "当前支持"):
            extract_document(self.root / "unknown.xls")


if __name__ == "__main__":
    unittest.main()
