"""End-to-end review import tests with genuine source extraction and no model calls."""
import hashlib
import json
import tempfile
import unittest
from pathlib import Path

from biaoshu.core import initialize, inspect, read_json, write_json
from biaoshu.extraction import extract_document
from biaoshu.review_import import (
    ACKNOWLEDGEMENT, review_template, reviewed_import,
)


class ReviewedImportTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.project = self.root / "project"
        initialize(self.project)
        self.sources = self.root / "sources"
        self.sources.mkdir()
        self.original = self.sources / "tender.txt"
        self.original.write_text("技术评分\n实施组织方案：10分\n质量保障措施：15分\n", encoding="utf-8")
        self.index_path = self.root / "tender.index.json"
        write_json(self.index_path, extract_document(self.original).index)
        self.suggestions = self.root / "candidates.json"
        write_json(self.suggestions, {
            "status": "suggestions_only", "schema_version": 1,
            "candidates": [
                {"id": "AI1", "kind": "technical_score", "title": "实施组织方案",
                 "score": 10, "status": "pending_review",
                 "evidence": {"file": "tender.txt", "location": "第2行", "quote": "实施组织方案：10分"}},
                {"id": "AI2", "kind": "technical_score", "title": "质量保障措施",
                 "score": 15, "status": "pending_review",
                 "evidence": {"file": "tender.txt", "location": "第3行", "quote": "质量保障措施：15分"}},
            ],
        })
        self.review_path = self.root / "review.json"
        write_json(self.review_path, review_template(self.suggestions))

    def decide(self, decisions=("accept", "reject"), acknowledgement=True):
        data = read_json(self.review_path)
        for item, value in zip(data["decisions"], decisions):
            item["decision"] = value
        if acknowledgement:
            data["acknowledgement"] = ACKNOWLEDGEMENT
        write_json(self.review_path, data)

    def run_import(self, apply=False):
        return reviewed_import(self.project, self.suggestions, self.review_path,
                               [self.index_path], self.sources, apply=apply)

    def test_template_requires_review(self):
        template = read_json(self.review_path)
        self.assertEqual(template["decisions"],
                         [{"id": "AI1", "decision": "pending"}, {"id": "AI2", "decision": "pending"}])
        with self.assertRaisesRegex(ValueError, "未处理"):
            self.run_import(apply=True)

    def test_preview_never_changes_workspace(self):
        self.decide()
        original_req = (self.project / "requirements.json").read_bytes()
        original_out = (self.project / "outline.json").read_bytes()
        plan = self.run_import()
        self.assertEqual(plan["status"], "ready")
        self.assertEqual(plan["statistics"]["new_requirements"], 1)
        self.assertEqual((self.project / "requirements.json").read_bytes(), original_req)
        self.assertEqual((self.project / "outline.json").read_bytes(), original_out)

    def test_apply_keeps_valid_bidirectional_mapping(self):
        self.decide(("accept", "accept"))
        plan = self.run_import(apply=True)
        self.assertEqual(plan["status"], "applied")
        requirements = read_json(self.project / "requirements.json")["requirements"]
        sections = read_json(self.project / "outline.json")["sections"]
        self.assertEqual([r["id"] for r in requirements], ["R1", "R2"])
        self.assertEqual([s["id"] for s in sections], ["S1", "S2"])
        self.assertEqual(requirements[0]["response_sections"], ["S1"])
        self.assertEqual(sections[1]["requirement_ids"], ["R2"])
        self.assertTrue(inspect(self.project)["ok"])
        self.assertTrue((Path(plan["backup_dir"]) / "requirements.before.json").exists())

    def test_missing_acknowledgement_blocks_write(self):
        self.decide(acknowledgement=False)
        with self.assertRaisesRegex(ValueError, "acknowledgement"):
            self.run_import(apply=True)
        self.assertEqual(read_json(self.project / "requirements.json")["requirements"], [])

    def test_suggestions_changed_after_review_blocks_write(self):
        self.decide()
        data = read_json(self.suggestions)
        data["candidates"][0]["title"] = "篡改标题"
        write_json(self.suggestions, data)
        with self.assertRaisesRegex(ValueError, "不匹配"):
            self.run_import(apply=True)

    def test_altered_original_rejected(self):
        self.decide()
        self.original.write_text("内容被修改", encoding="utf-8")
        with self.assertRaisesRegex(ValueError, "已变化"):
            self.run_import(apply=True)

    def test_forged_index_rejected_even_if_file_hash_matches(self):
        self.decide()
        index = read_json(self.index_path)
        index["blocks"][1]["text"] = "实施组织方案：10分" + "（伪造附件）"
        write_json(self.index_path, index)
        with self.assertRaisesRegex(ValueError, "索引内容"):
            self.run_import(apply=True)

    def test_hallucinated_candidate_quote_rejected(self):
        data = read_json(self.suggestions)
        data["candidates"][0]["evidence"]["quote"] = "新增不存在的投标承诺"
        write_json(self.suggestions, data)
        write_json(self.review_path, review_template(self.suggestions))
        self.decide()
        with self.assertRaisesRegex(ValueError, "引文与"):
            self.run_import(apply=True)

    def test_scoring_rule_not_promoted_to_section(self):
        data = read_json(self.suggestions)
        data["candidates"][0]["kind"] = "scoring_rule"
        write_json(self.suggestions, data)
        write_json(self.review_path, review_template(self.suggestions))
        self.decide()
        with self.assertRaisesRegex(ValueError, "评分规则"):
            self.run_import(apply=True)

    def test_existing_entries_preserved_and_id_allocation_skips_taken(self):
        write_json(self.project / "requirements.json", {"requirements": [
            {"id": "R1", "title": "已有原始需求", "score": None,
             "evidence": {"file": "other.txt", "location": "第1行", "quote": "原始要求"},
             "response_sections": ["S1"]}
        ]})
        write_json(self.project / "outline.json", {"sections": [
            {"id": "S1", "title": "已有章节", "requirement_ids": ["R1"],
             "weight": 1, "target_words": 0}
        ]})
        (self.project / "sections" / "S1.md").write_text("保留的原创正文", encoding="utf-8")
        self.decide()
        self.run_import(apply=True)
        self.assertEqual((self.project / "sections" / "S1.md").read_text(encoding="utf-8"), "保留的原创正文")
        self.assertEqual([r["id"] for r in read_json(self.project / "requirements.json")["requirements"]],
                         ["R1", "R2"])
        self.assertEqual([s["id"] for s in read_json(self.project / "outline.json")["sections"]],
                         ["S1", "S2"])

    def test_additional_approval_after_first_import_creates_separate_backup(self):
        self.decide(("accept", "reject"))
        first = self.run_import(apply=True)
        self.decide(("accept", "accept"))
        second = self.run_import(apply=True)
        self.assertEqual(first["status"], "applied")
        self.assertEqual(second["statistics"]["new_requirements"], 1)
        self.assertNotEqual(first["backup_dir"], second["backup_dir"])
        self.assertTrue(Path(first["backup_dir"]).exists())
        self.assertTrue(Path(second["backup_dir"]).exists())
        self.assertEqual(len(read_json(self.project / "requirements.json")["requirements"]), 2)

    def test_second_import_idempotent(self):
        self.decide()
        self.run_import(apply=True)
        plan = self.run_import(apply=True)
        self.assertEqual(plan["statistics"]["duplicate"], 1)
        self.assertEqual(plan["statistics"]["new_requirements"], 0)
        self.assertEqual(len(read_json(self.project / "outline.json")["sections"]), 1)

    def test_duplicate_candidate_ids_rejected(self):
        data = read_json(self.suggestions)
        data["candidates"][1]["id"] = "AI1"
        write_json(self.suggestions, data)
        with self.assertRaisesRegex(ValueError, "重复"):
            review_template(self.suggestions)

    def test_all_decisions_must_be_resolved(self):
        self.decide(("accept", "pending"))
        with self.assertRaisesRegex(ValueError, "未处理"):
            self.run_import(apply=True)

    def test_invalid_project_rejected_without_changes(self):
        self.decide()
        write_json(self.project / "outline.json", {"sections": [{"id": "../../bad"}]})
        with self.assertRaisesRegex(ValueError, "结构校验未通过"):
            self.run_import(apply=True)


    def test_review_cli_creates_skeleton_without_overwrite(self):
        import contextlib
        import io
        from biaoshu.cli import main
        output = self.root / "review-from-cli.json"
        with contextlib.redirect_stdout(io.StringIO()):
            rc = main(["review-init", "--suggestions", str(self.suggestions),
                       "--output", str(output)])
        self.assertEqual(rc, 0)
        self.assertEqual(len(read_json(output)["decisions"]), 2)
        with contextlib.redirect_stderr(io.StringIO()):
            rc = main(["review-init", "--suggestions", str(self.suggestions),
                       "--output", str(output)])
        self.assertEqual(rc, 2)

    def test_review_cli_previews_then_applies_only_with_flag(self):
        import contextlib
        import io
        from biaoshu.cli import main
        self.decide()
        options = [
            "review-import", str(self.project),
            "--suggestions", str(self.suggestions),
            "--review", str(self.review_path),
            "--index", str(self.index_path),
            "--source-dir", str(self.sources),
        ]
        preview = self.root / "preview.json"
        with contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(main([*options, "--output", str(preview)]), 0)
        self.assertEqual(read_json(preview)["status"], "ready")
        self.assertEqual(read_json(self.project / "requirements.json")["requirements"], [])
        with contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(main([*options, "--apply"]), 0)
        self.assertEqual(len(read_json(self.project / "requirements.json")["requirements"]), 1)

    def test_reviewer_cannot_accept_invalid_score(self):
        data = read_json(self.suggestions)
        data["candidates"][0]["score"] = True
        write_json(self.suggestions, data)
        write_json(self.review_path, review_template(self.suggestions))
        self.decide()
        with self.assertRaisesRegex(ValueError, "分值不合法"):
            self.run_import(apply=True)

if __name__ == "__main__":
    unittest.main()
