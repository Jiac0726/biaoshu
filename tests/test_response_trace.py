"""Trace each approved scoring requirement to a reviewer-selected prose line."""
import contextlib
import io
import tempfile
import unittest
from pathlib import Path

from biaoshu.cli import main, export_docx
from biaoshu.core import initialize, inspect, read_json, write_json
from biaoshu.response_trace import ACKNOWLEDGEMENT, audit_trace, create_trace, trace_path


class ResponseTraceTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        initialize(self.root)
        self.a = "本项目采用任务分解、责任到岗、过程核验的实施管理方法，并保存各阶段检查记录。"
        self.b = "质量控制实行作业自检与项目复核相结合，问题闭环处置并留存整改证据。"
        self.a_path = self.root / "sections" / "S1.md"
        self.b_path = self.root / "sections" / "S2.md"
        self.a_path.write_text("# 项目实施管理\n\n" + self.a + "\n", encoding="utf-8")
        self.b_path.write_text("# 质量控制措施\n\n" + self.b + "\n", encoding="utf-8")
        write_json(self.root / "requirements.json", {"requirements": [
            {"id": "R1", "title": "项目实施管理", "score": 10,
             "evidence": {"file": "demo.txt", "location": "第1行", "quote": "实施管理方案"},
             "response_sections": ["S1"]},
            {"id": "R2", "title": "质量控制措施", "score": 15,
             "evidence": {"file": "demo.txt", "location": "第2行", "quote": "质量控制方案"},
             "response_sections": ["S2"]},
        ]})
        write_json(self.root / "outline.json", {"sections": [
            {"id": "S1", "title": "项目实施管理", "requirement_ids": ["R1"],
             "target_words": 0, "weight": 1},
            {"id": "S2", "title": "质量控制措施", "requirement_ids": ["R2"],
             "target_words": 0, "weight": 1},
        ]})

    def setup_review(self, confirmed=True):
        template = create_trace(self.root)
        self.assertEqual(template["items"], 2)
        obj = read_json(trace_path(self.root))
        if confirmed:
            obj["acknowledgement"] = ACKNOWLEDGEMENT
            for row, quote in zip(obj["items"], (self.a, self.b)):
                row["line"] = 3
                row["quote"] = quote
                row["decision"] = "confirmed"
            write_json(trace_path(self.root), obj)
        return obj

    @staticmethod
    def cli(*args):
        with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
            return main(list(args))

    def test_without_trace_is_explicitly_unverified_but_backward_compatible(self):
        audit = inspect(self.root, strict=True)
        self.assertTrue(audit["ok"])
        self.assertEqual(audit["response_trace"]["status"], "not_started")
        self.assertTrue(any("尚未建立" in s for s in audit["warnings"]))
        self.assertEqual(self.cli("trace-audit", str(self.root)), 1)

    def test_init_pending_then_reviewer_confirmation(self):
        self.setup_review(confirmed=False)
        pending = audit_trace(self.root)
        self.assertFalse(pending["ok"])
        self.assertEqual(pending["statistics"]["confirmed_links"], 0)
        self.assertTrue(any(x["code"] == "pending_review" for x in pending["findings"]))
        self.assertFalse(inspect(self.root, strict=True)["ok"])

        obj = read_json(trace_path(self.root))
        obj["acknowledgement"] = ACKNOWLEDGEMENT
        for row, quote in zip(obj["items"], (self.a, self.b)):
            row.update(line=3, quote=quote, decision="confirmed")
        write_json(trace_path(self.root), obj)
        result = audit_trace(self.root)
        self.assertTrue(result["ok"])
        self.assertEqual(result["status"], "reviewed")
        self.assertEqual(result["statistics"]["confirmed_links"], 2)
        self.assertTrue(inspect(self.root, strict=True)["ok"])

    def test_cannot_overwrite_existing_review_register(self):
        self.setup_review()
        existing = trace_path(self.root).read_bytes()
        with self.assertRaisesRegex(ValueError, "禁止覆盖"):
            create_trace(self.root)
        self.assertEqual(trace_path(self.root).read_bytes(), existing)

    def test_invalid_quote_and_wrong_line_rejected(self):
        self.setup_review()
        obj = read_json(trace_path(self.root))
        obj["items"][0]["quote"] = "完全没有出现在相关正文中的虚假响应内容"
        write_json(trace_path(self.root), obj)
        report = audit_trace(self.root)
        self.assertTrue(any(x["code"] == "quote_mismatch" for x in report["findings"]))
        obj["items"][0].update(quote=self.a, line=99)
        write_json(trace_path(self.root), obj)
        self.assertTrue(any(x["code"] == "invalid_location" for x in audit_trace(self.root)["findings"]))

    def test_cannot_treat_title_or_blockquote_as_evidence(self):
        self.setup_review()
        obj = read_json(trace_path(self.root))
        obj["items"][0].update(line=1, quote="# 项目实施管理响应内容十分完善")
        write_json(trace_path(self.root), obj)
        self.assertIn("non_prose_evidence", [x["code"] for x in audit_trace(self.root)["findings"]])
        self.a_path.write_text("# 项目实施管理\n\n> 项目实施管理不是投标承诺，仅为招标原文引用。\n" + self.a, encoding="utf-8")
        obj["items"][0]["section_sha256"] = __import__("hashlib").sha256(self.a_path.read_bytes()).hexdigest()
        obj["items"][0].update(line=3, quote="项目实施管理不是投标承诺，仅为招标原文引用")
        write_json(trace_path(self.root), obj)
        self.assertIn("non_prose_evidence", [x["code"] for x in audit_trace(self.root)["findings"]])

    def test_fenced_code_content_cannot_count_as_response_prose(self):
        self.setup_review()
        text = "# 项目实施管理\n\n" + chr(96) * 3 + "text\n" + self.a + "\n" + chr(96) * 3 + "\n"
        self.a_path.write_text(text, encoding="utf-8")
        obj = read_json(trace_path(self.root))
        obj["items"][0]["section_sha256"] = __import__("hashlib").sha256(
            self.a_path.read_bytes()).hexdigest()
        obj["items"][0].update(line=4, quote=self.a)
        write_json(trace_path(self.root), obj)
        self.assertIn("non_prose_evidence",
                      [finding["code"] for finding in audit_trace(self.root)["findings"]])

    def test_section_edit_after_review_blocks_strict_audit(self):
        self.setup_review()
        self.a_path.write_text(self.a_path.read_text(encoding="utf-8") + "\n新的工艺承诺\n", encoding="utf-8")
        result = audit_trace(self.root)
        self.assertTrue(any(x["code"] == "section_changed" for x in result["findings"]))
        self.assertFalse(inspect(self.root, strict=True)["ok"])

    def test_stale_mapping_and_missing_requirement_link(self):
        self.setup_review()
        obj = read_json(trace_path(self.root))
        obj["items"] = obj["items"][:1]
        write_json(trace_path(self.root), obj)
        self.assertIn("missing_item", [x["code"] for x in audit_trace(self.root)["findings"]])
        reqs = read_json(self.root / "requirements.json")
        reqs["requirements"][0]["title"] = "人工更改后的实施方案"
        write_json(self.root / "requirements.json", reqs)
        self.assertIn("mapping_changed", [x["code"] for x in audit_trace(self.root)["findings"]])

    def test_reject_duplicate_and_extra_links(self):
        self.setup_review()
        obj = read_json(trace_path(self.root))
        obj["items"].append(dict(obj["items"][0]))
        obj["items"].append({"requirement_id": "R404", "section_id": "S1",
                             "decision": "confirmed", "line": 3,
                             "quote": self.a, "section_sha256": obj["items"][0]["section_sha256"]})
        write_json(trace_path(self.root), obj)
        codes = {x["code"] for x in audit_trace(self.root)["findings"]}
        self.assertIn("duplicate_item", codes)
        self.assertIn("unexpected_item", codes)

    def test_bogus_acknowledgement_rejected(self):
        self.setup_review()
        obj = read_json(trace_path(self.root))
        obj["acknowledgement"] = "模型已经确认质量合格"
        write_json(trace_path(self.root), obj)
        self.assertIn("review_acknowledgement_missing",
                      [x["code"] for x in audit_trace(self.root)["findings"]])

    def test_cli_init_and_audit_json(self):
        self.assertEqual(self.cli("trace-init", str(self.root)), 0)
        result = self.root / "reports" / "trace-audit.json"
        self.assertEqual(self.cli("trace-audit", str(self.root), "--output", str(result)), 1)
        self.assertFalse(read_json(result)["ok"])
        obj = read_json(trace_path(self.root))
        obj["acknowledgement"] = ACKNOWLEDGEMENT
        for row, quote in zip(obj["items"], (self.a, self.b)):
            row.update(line=3, quote=quote, decision="confirmed")
        write_json(trace_path(self.root), obj)
        self.assertEqual(self.cli("trace-audit", str(self.root), "--output", str(result)), 0)
        self.assertEqual(read_json(result)["statistics"]["confirmed_links"], 2)

    def test_no_file_mutations_when_auditing(self):
        self.setup_review()
        before = {p: p.read_bytes() for p in (self.a_path, self.b_path, trace_path(self.root))}
        self.assertTrue(audit_trace(self.root)["ok"])
        self.assertEqual(before, {p: p.read_bytes() for p in before})

    def test_official_export_blocked_when_review_pending(self):
        self.setup_review(confirmed=False)
        target = self.root / "official.docx"
        with self.assertRaisesRegex(ValueError, "严格审查"):
            export_docx(self.root, target, draft=False)
        self.assertFalse(target.exists())

    def test_clean_review_does_not_override_missing_source_evidence_gate(self):
        self.setup_review()
        target = self.root / "official.docx"
        with self.assertRaisesRegex(ValueError, "严格审查"):
            export_docx(self.root, target, draft=False)
        self.assertFalse(target.exists())

    def test_short_non_substantive_quote_rejected(self):
        self.setup_review()
        obj = read_json(trace_path(self.root))
        obj["items"][1]["quote"] = "质量控制"
        write_json(trace_path(self.root), obj)
        self.assertIn("invalid_location", [x["code"] for x in audit_trace(self.root)["findings"]])


if __name__ == "__main__":
    unittest.main()
