"""Contract-value audit: exact lines, conservative comparisons, export gate."""
import contextlib
import io
import json
import tempfile
import unittest
from pathlib import Path

from biaoshu.cli import main, export_docx
from biaoshu.consistency import analyze_consistency
from biaoshu.core import initialize, inspect, read_json, write_json


class ConsistencyTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        initialize(self.root)
        write_json(self.root / "requirements.json", {"requirements": [
            {"id": "R1", "title": "组织措施", "score": 5,
             "evidence": {"file": "tender.txt", "location": "第1行", "quote": "组织措施"},
             "response_sections": ["S1"]},
            {"id": "R2", "title": "质量措施", "score": 5,
             "evidence": {"file": "tender.txt", "location": "第2行", "quote": "质量措施"},
             "response_sections": ["S2"]},
        ]})
        write_json(self.root / "outline.json", {"sections": [
            {"id": "S1", "title": "组织措施", "requirement_ids": ["R1"],
             "weight": 1.0, "target_words": 0},
            {"id": "S2", "title": "质量措施", "requirement_ids": ["R2"],
             "weight": 1.0, "target_words": 0},
        ]})
        self.body("S1", "项目工期为30天，由项目负责人统筹组织实施。")
        self.body("S2", "施工工期：30日，各组按过程检查并交付成果。")

    def body(self, sid, text):
        (self.root / "sections" / (sid + ".md")).write_text(
            "# 章节标题\n\n" + text + "\n", encoding="utf-8")

    def set_facts(self, facts):
        write_json(self.root / "facts.json", {"facts": facts})

    def test_consistent_days_and_days_aliases(self):
        report = analyze_consistency(self.root)
        self.assertTrue(report["ok"])
        self.assertEqual(report["statistics"]["commitments_detected"], 2)
        self.assertEqual(report["statistics"]["errors"], 0)
        self.assertTrue(inspect(self.root, strict=True)["ok"])

    def test_conflicting_cross_section_days_detected_with_lines(self):
        self.body("S2", "合同工期：45日，建立实施检查清单。")
        report = analyze_consistency(self.root)
        self.assertFalse(report["ok"])
        issue = next(x for x in report["findings"] if x["code"] == "cross_section_conflict")
        self.assertEqual({x["section_id"] for x in issue["observations"]}, {"S1", "S2"})
        self.assertEqual({x["line"] for x in issue["observations"]}, {3})
        self.assertEqual({x["value"] for x in issue["observations"]}, {"30", "45"})

    def test_same_section_different_explicit_values(self):
        self.body("S1", "项目工期为30日。\n施工工期：40天，另行补充。")
        self.body("S2", "进度管理采用分阶段的过程记录。")
        issues = analyze_consistency(self.root)["findings"]
        self.assertEqual([x["code"] for x in issues], ["within_section_conflict"])

    def test_verified_global_fact_mismatch_is_blocker(self):
        self.set_facts([{"key": "project_duration", "value": "30日", "status": "verified",
                         "evidence": {"file": "tender.txt", "location": "第3行", "quote": "工期30日"}}])
        self.body("S1", "项目工期为45日，现场按目标实施。")
        report = analyze_consistency(self.root)
        mismatch = next(x for x in report["findings"] if x["code"] == "verified_fact_mismatch")
        self.assertEqual(mismatch["section_id"], "S1")
        self.assertEqual(mismatch["fact_key"], "project_duration")
        self.assertEqual(mismatch["verified"], "30日")
        self.assertFalse(inspect(self.root, strict=True)["ok"])
        self.assertTrue(any("verified_fact_mismatch" in x for x in inspect(self.root, strict=True)["errors"]))

    def test_check_warns_but_strict_audit_blocks(self):
        self.body("S2", "项目工期为45日。")
        normal = inspect(self.root)
        self.assertTrue(normal["ok"])
        self.assertTrue(any("cross_section_conflict" in x for x in normal["warnings"]))
        strict = inspect(self.root, strict=True)
        self.assertFalse(strict["ok"])
        self.assertTrue(any("cross_section_conflict" in x for x in strict["errors"]))
        self.assertFalse(strict["consistency"]["ok"])

    def test_different_categories_are_not_equated(self):
        self.body("S2", "质保期为45日，执行售后登记制度。")
        report = analyze_consistency(self.root)
        self.assertEqual(report["statistics"]["errors"], 0)

    def test_duration_different_units_not_guessed(self):
        self.body("S1", "服务期限为1个月。")
        self.body("S2", "服务期限为30日。")
        report = analyze_consistency(self.root)
        self.assertTrue(report["ok"])
        self.assertEqual(report["statistics"]["commitments_detected"], 2)
        self.assertTrue(any("不同单位" in x for x in report["limitations"]))

    def test_response_time_explicit_conflict(self):
        self.body("S1", "响应时间为2小时。")
        self.body("S2", "响应时限：4小时。")
        report = analyze_consistency(self.root)
        self.assertEqual(report["findings"][0]["category"], "response_time")
        self.assertEqual(report["findings"][0]["code"], "cross_section_conflict")

    def test_pending_fact_is_warning_not_hard_conflict(self):
        self.set_facts([{"key": "service_duration", "value": "", "status": "pending"}])
        self.body("S1", "服务期限为12个月。")
        self.body("S2", "技术服务按计划交付。")
        report = analyze_consistency(self.root)
        self.assertTrue(report["ok"])
        self.assertTrue(any(x["code"] == "unverified_commitment" for x in report["findings"]))

    def test_false_positives_from_unasserted_or_quoted_text_omitted(self):
        self.body("S1", "# 工期为30日\n> 招标文件写工期为45日\n"
                  "| 项目工期为50日 |\n可能需要工期不超过60日。\n"
                  "项目工期为30日，且由负责人统筹。")
        self.body("S2", "项目工期为30日，分工开展实施工作。")
        self.assertEqual(analyze_consistency(self.root)["statistics"]["commitments_detected"], 2)
        self.assertTrue(analyze_consistency(self.root)["ok"])

    def test_hypothetical_and_negated_values_do_not_block_export(self):
        self.body("S1", "若项目工期为45日，则需要另行审批。\\n"
                  "示例：工期为60日仅供讨论。\\n"
                  "并非项目工期为90日。\\n"
                  "项目工期为30日，按计划开展核查。")
        self.body("S2", "项目工期为30日，保障验收工作。")
        report = analyze_consistency(self.root)
        self.assertTrue(report["ok"])
        self.assertEqual(report["statistics"]["commitments_detected"], 2)

    def test_code_fence_is_skipped_including_middle_lines(self):
        self.body("S1", "项目工期为30日。\n" + chr(96) * 3 +
                  "\n工期为45日\n" + chr(96) * 3 + "\n")
        self.assertTrue(analyze_consistency(self.root)["ok"])

    def test_cli_writes_a_local_report_without_modifying_source(self):
        self.body("S2", "项目工期为45日。")
        dest = self.root / "reports" / "consistency.json"
        original = (self.root / "sections" / "S2.md").read_bytes()
        with contextlib.redirect_stdout(io.StringIO()):
            rc = main(["consistency-audit", str(self.root), "--output", str(dest)])
        self.assertEqual(rc, 1)
        saved = read_json(dest)
        self.assertEqual(saved["status"], "mechanical_review_only")
        self.assertEqual(saved["statistics"]["errors"], 1)
        self.assertEqual(original, (self.root / "sections" / "S2.md").read_bytes())

    def test_cli_clean_case_returns_zero(self):
        with contextlib.redirect_stdout(io.StringIO()):
            rc = main(["consistency-audit", str(self.root)])
        self.assertEqual(rc, 0)

    def test_official_word_export_rejects_conflict_even_without_source_data(self):
        self.body("S2", "项目工期为45日。")
        destination = self.root / "technical.docx"
        with self.assertRaisesRegex(ValueError, "严格审查"):
            export_docx(self.root, destination, draft=False)
        self.assertFalse(destination.exists())

    def test_draft_export_is_marked_unverified_not_silent_certification(self):
        self.body("S2", "项目工期为45日。")
        destination = self.root / "draft.docx"
        export_docx(self.root, destination, draft=True)
        from docx import Document
        doc = Document(destination)
        self.assertIn("草稿，未完成校验", doc.paragraphs[0].text)
        self.assertTrue(destination.exists())


if __name__ == "__main__":
    unittest.main()
