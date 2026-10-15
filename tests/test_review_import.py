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

    def set_ambiguous_only(self):
        phrase = "质量保障措施：合格得5分，优秀得10分"
        self.original.write_text("技术评分\n" + phrase + "\n", encoding="utf-8")
        write_json(self.index_path, extract_document(self.original).index)
        write_json(self.suggestions, {
            "schema_version": 1, "status": "suggestions_only", "candidates": [],
            "ambiguous_candidates": [{
                "id": "M1", "status": "requires_manual_scoring_review",
                "score_options": [5, 10], "reason": "multiple_scoring_tiers",
                "evidence": {"file": "tender.txt", "location": "第2行", "quote": phrase},
            }],
        })
        write_json(self.review_path, review_template(self.suggestions))

    def test_multitier_is_not_silently_skipped_by_review_import(self):
        self.set_ambiguous_only()
        template = read_json(self.review_path)
        self.assertEqual(template["decisions"], [])
        self.assertEqual(template["ambiguous_decisions"], [
            {"id": "M1", "decision": "pending", "reason": ""},
        ])
        self.assertEqual(self.run_import()["status"], "pending_review")
        with self.assertRaisesRegex(ValueError, "未处理"):
            self.run_import(apply=True)
        self.assertEqual(read_json(self.project / "requirements.json")["requirements"], [])

    def test_multitier_requires_explicit_reason_to_exclude(self):
        self.set_ambiguous_only()
        rev = read_json(self.review_path)
        rev["acknowledgement"] = ACKNOWLEDGEMENT
        rev["ambiguous_decisions"][0]["decision"] = "not_applicable"
        write_json(self.review_path, rev)
        with self.assertRaisesRegex(ValueError, "审核理由"):
            self.run_import(apply=True)
        rev["ambiguous_decisions"][0]["reason"] = "已经逐条确认本行不是适用的技术评分要求"
        write_json(self.review_path, rev)
        self.assertEqual(self.run_import(apply=True)["statistics"]["ambiguous_pending"], 0)

    def test_multitier_manual_registration_requires_real_existing_evidence(self):
        self.set_ambiguous_only()
        rev = read_json(self.review_path)
        rev["acknowledgement"] = ACKNOWLEDGEMENT
        rev["ambiguous_decisions"][0].update({
            "decision": "manually_registered", "reason": "评分分档经过审查，已按原文完整手工登记",
        })
        write_json(self.review_path, rev)
        with self.assertRaisesRegex(ValueError, "项目需求不存在对应原文"):
            self.run_import(apply=True)
        ev = read_json(self.suggestions)["ambiguous_candidates"][0]["evidence"]
        write_json(self.project / "requirements.json", {"requirements": [{
            "id": "R1", "title": "人工登记的两档评分", "score": None,
            "evidence": ev, "response_sections": ["S1"],
        }]})
        write_json(self.project / "outline.json", {"sections": [{
            "id": "S1", "title": "质量保障响应", "requirement_ids": ["R1"],
            "weight": 1.0, "target_words": 0,
        }]})
        result = self.run_import(apply=True)
        self.assertEqual(result["statistics"]["ambiguous_manually_registered"], 1)
        self.assertEqual(result["statistics"]["new_requirements"], 0)

    def test_multitier_review_must_have_one_decision_per_source_entry(self):
        self.set_ambiguous_only()
        rev = read_json(self.review_path)
        del rev["ambiguous_decisions"]
        write_json(self.review_path, rev)
        with self.assertRaisesRegex(ValueError, "多档评分必须逐项审核"):
            self.run_import(apply=True)
        rev["ambiguous_decisions"] = [
            {"id": "FAKE", "decision": "not_applicable", "reason": "这个无效ID不允许替代原始评分项目"}
        ]
        write_json(self.review_path, rev)
        with self.assertRaisesRegex(ValueError, "多档评分必须逐项审核"):
            self.run_import(apply=True)

    def test_multitier_must_have_source_matched_to_original(self):
        self.set_ambiguous_only()
        candidate = read_json(self.suggestions)
        candidate["ambiguous_candidates"][0]["evidence"]["quote"] = "从未出现在来源招标文件中的虚构分档要求"
        write_json(self.suggestions, candidate)
        write_json(self.review_path, review_template(self.suggestions))
        rev = read_json(self.review_path)
        rev["acknowledgement"] = ACKNOWLEDGEMENT
        rev["ambiguous_decisions"][0].update({
            "decision": "not_applicable", "reason": "查证了该项来源，应予人工明确排除",
        })
        write_json(self.review_path, rev)
        with self.assertRaisesRegex(ValueError, "多档评分来源"):
            self.run_import(apply=True)

    def test_out_of_range_ambiguous_grade_is_reviewable_but_not_automatic_score(self):
        self.set_ambiguous_only()
        item = read_json(self.suggestions)
        item["ambiguous_candidates"][0]["score_options"] = [90, 105]
        write_json(self.suggestions, item)
        review = review_template(self.suggestions)
        self.assertEqual(review["ambiguous_decisions"][0]["decision"], "pending")
        write_json(self.review_path, review)
        self.assertEqual(self.run_import()["status"], "pending_review")
        with self.assertRaisesRegex(ValueError, "未处理"):
            self.run_import(apply=True)

    def test_unsupported_suggestion_schema_rejected_before_review(self):
        original = self.suggestions.read_bytes()
        for version in (None, True, 1.0, 2, 999, "1"):
            with self.subTest(version=version):
                data = json.loads(original)
                if version is None:
                    data.pop("schema_version", None)
                else:
                    data["schema_version"] = version
                write_json(self.suggestions, data)
                with self.assertRaisesRegex(ValueError, "suggestions_only"):
                    review_template(self.suggestions)
                with self.assertRaisesRegex(ValueError, "suggestions_only"):
                    self.run_import(apply=True)
        self.suggestions.write_bytes(original)

    def test_same_evidence_different_score_rejected_instead_of_ignored(self):
        self.decide()
        self.run_import(apply=True)
        data = read_json(self.suggestions)
        data["candidates"][0]["score"] = 100
        write_json(self.suggestions, data)
        write_json(self.review_path, review_template(self.suggestions))
        self.decide()
        with self.assertRaisesRegex(ValueError, "分值或类型冲突"):
            self.run_import(apply=True)
        self.assertEqual(read_json(self.project / "requirements.json")["requirements"][0]["score"], 10)

    def test_same_evidence_different_kind_rejected_instead_of_ignored(self):
        self.decide()
        self.run_import(apply=True)
        data = read_json(self.suggestions)
        data["candidates"][0]["kind"] = "mandatory_technical_requirement"
        data["candidates"][0]["score"] = None
        write_json(self.suggestions, data)
        write_json(self.review_path, review_template(self.suggestions))
        self.decide()
        with self.assertRaisesRegex(ValueError, "分值或类型冲突"):
            self.run_import(apply=True)

    def test_adjustment_rule_cannot_avoid_explicit_manual_review(self):
        phrase = "安全措施每缺一项扣2分"
        self.original.write_text("技术评分\n" + phrase + "\n", encoding="utf-8")
        write_json(self.index_path, extract_document(self.original).index)
        write_json(self.suggestions, {
            "schema_version": 1, "status": "suggestions_only",
            "candidates": [],
            "ambiguous_candidates": [{
                "id": "M1", "reason": "adjustment_rule",
                "status": "requires_manual_scoring_review",
                "score_options": [2],
                "evidence": {"file": "tender.txt", "location": "第2行", "quote": phrase},
            }],
        })
        write_json(self.review_path, review_template(self.suggestions))
        with self.assertRaisesRegex(ValueError, "未处理"):
            self.run_import(apply=True)
        review = read_json(self.review_path)
        review["acknowledgement"] = ACKNOWLEDGEMENT
        review["ambiguous_decisions"][0] = {
            "id": "M1", "decision": "not_applicable",
            "reason": "逐条核实当前审核范围不适用这项扣分规则",
        }
        write_json(self.review_path, review)
        self.assertEqual(self.run_import(apply=True)["statistics"]["ambiguous_pending"], 0)

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
        with self.assertRaisesRegex(ValueError, "索引内容|索引与招标原件解析结果不一致"):
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

    def test_existing_hierarchical_outline_blocks_new_unassigned_sections(self):
        from biaoshu.outline_tree import outline_template, outline_plan, lock_outline
        self.decide(("accept", "reject"))
        self.run_import(apply=True)
        proposal = self.root / "grouping.json"
        write_json(proposal, outline_template(self.project))
        outline_plan(self.project, proposal, apply=True)
        lock_outline(self.project, confirm=True)
        previous_outline = (self.project / "outline.json").read_bytes()
        self.decide(("accept", "accept"))
        with self.assertRaisesRegex(ValueError, "已有层级目录"):
            self.run_import(apply=True)
        self.assertEqual((self.project / "outline.json").read_bytes(), previous_outline)
        self.assertEqual(len(read_json(self.project / "requirements.json")["requirements"]), 1)

    def test_import_preserves_custom_project_metadata(self):
        reqs = read_json(self.project / "requirements.json")
        outline = read_json(self.project / "outline.json")
        reqs["project_reference"] = "demo-safe-metadata"
        outline["layout_notes"] = {"reviewed": True}
        write_json(self.project / "requirements.json", reqs)
        write_json(self.project / "outline.json", outline)
        self.decide(("accept", "accept"))
        self.run_import(apply=True)
        self.assertEqual(read_json(self.project / "requirements.json")["project_reference"],
                         "demo-safe-metadata")
        self.assertEqual(read_json(self.project / "outline.json")["layout_notes"],
                         {"reviewed": True})

    def test_concurrent_import_lock_prevents_any_mutation(self):
        from biaoshu.review_transaction import LOCK
        self.decide()
        lock = self.project / "reports" / LOCK
        lock.mkdir()
        before = (self.project / "requirements.json").read_bytes()
        with self.assertRaisesRegex(ValueError, "独占锁"):
            self.run_import(apply=True)
        self.assertEqual((self.project / "requirements.json").read_bytes(), before)
        self.assertFalse((self.project / "reports" / "review-import-transaction.json").exists())

    def test_interrupted_two_file_write_blocks_audit_until_safe_recovery(self):
        from unittest.mock import patch
        from biaoshu import review_transaction as txn
        self.decide(("accept", "accept"))
        req_path = self.project / "requirements.json"
        out_path = self.project / "outline.json"
        original_req, original_out = req_path.read_bytes(), out_path.read_bytes()
        saved = txn._atomic_bytes
        writes = []
        def fail_second(dest, data):
            writes.append(dest.name)
            if dest.name == "outline.json":
                raise OSError("synthetic interruption")
            return saved(dest, data)
        with patch.object(txn, "_atomic_bytes", side_effect=fail_second):
            with self.assertRaisesRegex(OSError, "synthetic interruption"):
                self.run_import(apply=True)
        self.assertEqual(writes, ["requirements.json", "outline.json"])
        self.assertNotEqual(req_path.read_bytes(), original_req)
        self.assertEqual(out_path.read_bytes(), original_out)
        self.assertTrue(txn.journal_path(self.project).exists())
        check = inspect(self.project, strict=True)
        self.assertFalse(check["ok"])
        self.assertTrue(any("review-recover" in msg for msg in check["errors"]))
        with self.assertRaisesRegex(ValueError, "未完成的事务"):
            self.run_import(apply=True)
        with self.assertRaisesRegex(ValueError, "confirm"):
            txn.recover(self.project)
        report = txn.recover(self.project, confirm=True)
        self.assertEqual(report["status"], "restored")
        self.assertEqual(req_path.read_bytes(), original_req)
        self.assertEqual(out_path.read_bytes(), original_out)
        self.assertFalse(txn.journal_path(self.project).exists())
        self.assertTrue(inspect(self.project)["ok"])
        self.assertTrue((Path(report["backup"]) / "requirements.before.json").is_file())
        self.assertTrue((Path(report["backup"]) / "outline.before.json").is_file())

    def test_recover_refuses_unknown_manual_edits_after_interruption(self):
        from unittest.mock import patch
        from biaoshu import review_transaction as txn
        self.decide()
        saved = txn._atomic_bytes
        def break_second(dest, data):
            if dest.name == "outline.json":
                raise OSError("synthetic crash")
            return saved(dest, data)
        with patch.object(txn, "_atomic_bytes", side_effect=break_second):
            with self.assertRaises(OSError):
                self.run_import(apply=True)
        req = self.project / "requirements.json"
        req.write_text('{"requirements":[],"manual_revision":"must not be lost"}', encoding="utf-8")
        before = req.read_bytes()
        with self.assertRaisesRegex(ValueError, "外部修改"):
            txn.recover(self.project, confirm=True)
        self.assertEqual(req.read_bytes(), before)
        self.assertTrue(txn.journal_path(self.project).exists())

    def test_recovery_cli_requires_confirmation(self):
        from unittest.mock import patch
        from biaoshu.cli import main
        from biaoshu import review_transaction as txn
        import contextlib, io
        self.decide()
        normal_write = txn._atomic_bytes
        def simulate(dest, raw):
            if dest.name == "outline.json":
                raise OSError("synthetic simulated IO failure")
            return normal_write(dest, raw)
        with patch.object(txn, "_atomic_bytes", side_effect=simulate):
            with self.assertRaises(OSError):
                self.run_import(apply=True)
        with contextlib.redirect_stderr(io.StringIO()):
            self.assertEqual(main(["review-recover", str(self.project)]), 2)
        with contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(main(["review-recover", str(self.project), "--confirm"]), 0)
        self.assertFalse(txn.journal_path(self.project).exists())

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

    def test_apply_output_exists_is_rejected_before_any_project_commit(self):
        from biaoshu.cli import main
        import contextlib
        import io
        self.decide()
        destination = self.root / "already-existing-review.json"
        destination.write_text("manual reviewed results", encoding="utf-8")
        options = [
            "review-import", str(self.project), "--apply",
            "--suggestions", str(self.suggestions),
            "--review", str(self.review_path),
            "--index", str(self.index_path), "--source-dir", str(self.sources),
            "--output", str(destination),
        ]
        with contextlib.redirect_stderr(io.StringIO()):
            self.assertEqual(main(options), 2)
        self.assertEqual(destination.read_text(encoding="utf-8"),
                         "manual reviewed results")
        self.assertEqual(read_json(self.project / "requirements.json")["requirements"], [])
        self.assertEqual(read_json(self.project / "outline.json")["sections"], [])
        self.assertFalse((self.project / "reports" / "review-import-transaction.json").exists())

    def test_postcommit_report_io_error_reports_committed_import_not_failure(self):
        from biaoshu.cli import main
        from unittest.mock import patch
        import contextlib
        import io
        self.decide()
        output = self.root / "unwritable-report.json"
        options = [
            "review-import", str(self.project), "--apply",
            "--suggestions", str(self.suggestions),
            "--review", str(self.review_path),
            "--index", str(self.index_path), "--source-dir", str(self.sources),
            "--output", str(output),
        ]
        stderr, stdout = io.StringIO(), io.StringIO()
        with patch("biaoshu.cli.write_new_report", side_effect=PermissionError(
                    "synthetic permission failure")), \
                contextlib.redirect_stderr(stderr), contextlib.redirect_stdout(stdout):
            self.assertEqual(main(options), 0)
        self.assertIn("已提交成功", stderr.getvalue())
        self.assertIn("不要直接重复导入", stderr.getvalue())
        self.assertIn("已登记", stdout.getvalue())
        self.assertEqual(len(read_json(self.project / "requirements.json")["requirements"]), 1)
        self.assertEqual(len(read_json(self.project / "outline.json")["sections"]), 1)
        self.assertFalse(output.exists())
        self.assertFalse((self.project / "reports" / "review-import-transaction.json").exists())

    def test_import_report_published_exclusively_and_cannot_be_replaced(self):
        from biaoshu.cli import main
        import contextlib
        import io
        self.decide()
        destination = self.root / "import-plan.json"
        opts = [
            "review-import", str(self.project), "--suggestions", str(self.suggestions),
            "--review", str(self.review_path), "--index", str(self.index_path),
            "--source-dir", str(self.sources), "--output", str(destination),
        ]
        with contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(main(opts), 0)
        self.assertEqual(read_json(destination)["status"], "ready")
        original = destination.read_bytes()
        with contextlib.redirect_stderr(io.StringIO()):
            self.assertEqual(main(opts), 2)
        self.assertEqual(destination.read_bytes(), original)

    def test_external_editor_changes_requirements_during_extraction_blocks_commit(self):
        from unittest.mock import patch
        import biaoshu.review_import as module
        self.decide()
        req = self.project / "requirements.json"
        original = module._source_blocks
        def edit_during_extraction(index_paths, source_dir):
            payload = read_json(req)
            payload["manual_note"] = "someone edited between load and commit"
            write_json(req, payload)
            return original(index_paths, source_dir)
        with patch.object(module, "_source_blocks", side_effect=edit_during_extraction):
            with self.assertRaisesRegex(ValueError, "过时快照"):
                self.run_import(apply=True)
        self.assertEqual(read_json(req)["manual_note"],
                         "someone edited between load and commit")
        self.assertEqual(read_json(self.project / "outline.json")["sections"], [])
        self.assertFalse((self.project / "reports" / "review-import-transaction.json").exists())

    def test_external_editor_changes_outline_during_extraction_blocks_commit(self):
        from unittest.mock import patch
        import biaoshu.review_import as module
        self.decide()
        path = self.project / "outline.json"
        original = module._source_blocks
        def edit_during_extraction(index_paths, source_dir):
            payload = read_json(path)
            payload["manual_note"] = "new outline metadata"
            write_json(path, payload)
            return original(index_paths, source_dir)
        with patch.object(module, "_source_blocks", side_effect=edit_during_extraction):
            with self.assertRaisesRegex(ValueError, "过时快照"):
                self.run_import(apply=True)
        self.assertEqual(read_json(path)["manual_note"], "new outline metadata")
        self.assertEqual(read_json(self.project / "requirements.json")["requirements"], [])

    def test_hierarchy_conflict_is_visible_in_preview_not_marked_ready(self):
        from biaoshu.outline_tree import outline_template, outline_plan, lock_outline
        self.decide(("accept", "reject"))
        self.run_import(apply=True)
        suggestion_tree = self.root / "tree-for-hierarchy.json"
        write_json(suggestion_tree, outline_template(self.project))
        outline_plan(self.project, suggestion_tree, apply=True)
        lock_outline(self.project, confirm=True)
        self.decide(("accept", "accept"))
        snapshot = (self.project / "outline.json").read_bytes()
        preview = self.run_import(apply=False)
        self.assertEqual(preview["status"], "blocked_hierarchical_outline")
        self.assertTrue(any("roots" in msg for msg in preview["warnings"]))
        with self.assertRaisesRegex(ValueError, "已有层级目录"):
            self.run_import(apply=True)
        self.assertEqual((self.project / "outline.json").read_bytes(), snapshot)

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
