"""Real source-index fixtures, fake model, and zero-network section drafting tests."""
import contextlib
import io
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from biaoshu.cli import main, export_docx
from biaoshu.core import initialize, inspect, read_json, scaffold, write_json
from biaoshu.extraction import extract_document
from biaoshu.outline_tree import outline_plan, outline_template
from biaoshu.section_writer import (
    BANNER, CONFIRM, approve_section, checkpoint_path, write_section, write_sections,
)


class SectionWriterTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.project = self.root / "project"
        initialize(self.project)
        self.source_dir = self.root / "sources"
        self.source_dir.mkdir()
        self.source = self.source_dir / "tender.txt"
        self.source.write_text("实施组织方案评分10分\n质量保障措施评分5分\n项目工期为30日\n", encoding="utf-8")
        self.index = self.root / "tender.index.json"
        write_json(self.index, extract_document(self.source).index)
        write_json(self.project / "requirements.json", {"requirements": [
            {"id": "R1", "title": "实施组织", "score": 10,
             "description": "详细编制项目实施组织方案",
             "evidence": {"file": "tender.txt", "location": "第1行", "quote": "实施组织方案评分10分"},
             "response_sections": ["S1"]},
            {"id": "R2", "title": "质量保障", "score": 5,
             "evidence": {"file": "tender.txt", "location": "第2行", "quote": "质量保障措施评分5分"},
             "response_sections": ["S2"]},
        ]})
        write_json(self.project / "outline.json", {"sections": [
            {"id": "S1", "title": "实施组织", "requirement_ids": ["R1"], "weight": 1.0, "target_words": 0},
            {"id": "S2", "title": "质量保障", "requirement_ids": ["R2"], "weight": 1.0, "target_words": 0},
        ]})
        write_json(self.project / "facts.json", {"facts": [
            {"key": "deadline", "status": "verified", "value": "30日",
             "evidence": {"file": "tender.txt", "location": "第3行", "quote": "项目工期为30日"}},
            {"key": "staff", "status": "pending", "value": "内部未批准名单"},
        ]})
        self.calls = []

    def answer(self, rid="R1", facts=None):
        return json.dumps({
            "body": "拟建立由项目负责人统筹协调、专业组分工实施、质量组独立复核的组织机制，明确任务交接和记录要求，按节点开展检查并形成可核查的过程成果。",
            "used_requirement_ids": [rid], "used_fact_keys": facts or [],
        }, ensure_ascii=False)

    def fake(self, endpoint, model, prompt, *, api_key, timeout, instructions):
        self.calls.append((endpoint, model, prompt, api_key, timeout, instructions))
        current = json.loads(prompt.split("\n", 1)[1])["section_id"]
        return self.answer("R1" if current == "S1" else "R2", ["deadline"])

    def one(self, sid="S1", **opts):
        return write_section(self.project, sid, [self.index], self.source_dir,
                             model="local-demo", transport=self.fake, **opts)

    def test_writes_source_backed_pending_draft_and_checkpoint(self):
        result = self.one()
        self.assertEqual(result["status"], "pending_review")
        content = (self.project / "sections" / "S1.md").read_text(encoding="utf-8")
        self.assertTrue(content.startswith("# 实施组织\n"))
        self.assertIn(BANNER, content)
        record = read_json(checkpoint_path(self.project, "S1"))
        self.assertEqual(record["status"], "pending_review")
        self.assertEqual(record["requirement_ids"], ["R1"])
        self.assertNotIn("内部未批准名单", self.calls[0][2])
        self.assertIn("项目工期为30日", self.calls[0][2])
        self.assertFalse(inspect(self.project, strict=True)["ok"])

    def test_verified_generic_duration_category_is_sent_to_model(self):
        self.source.write_text(self.source.read_text(encoding="utf-8")
                               + "服务期限为30日\n", encoding="utf-8")
        write_json(self.index, extract_document(self.source).index)
        write_json(self.project / "facts.json", {"facts": [{
            "key": "duration", "category": "service_duration",
            "status": "verified", "value": "30日",
            "evidence": {"file": "tender.txt", "location": "第4行",
                         "quote": "服务期限为30日"},
        }]})
        inputs = []
        def model(endpoint, model, prompt, *, api_key, timeout, instructions):
            inputs.append((json.loads(prompt.split("\n", 1)[1]), instructions))
            return self.answer("R1", ["duration"])
        report = write_section(
            self.project, "S1", [self.index], self.source_dir,
            model="local-demo", transport=model)
        self.assertEqual(report["status"], "pending_review")
        fact = inputs[0][0]["facts"][0]
        self.assertEqual(fact["category"], "service_duration")
        self.assertEqual(fact["value"], "30日")
        self.assertIn("严格区分", inputs[0][1])

    def test_verified_generic_duration_without_category_never_sent_to_model(self):
        write_json(self.project / "facts.json", {"facts": [{
            "key": "duration", "status": "verified", "value": "30日",
            "evidence": {"file": "tender.txt", "location": "第3行",
                         "quote": "项目工期为30日"},
        }]})
        with self.assertRaisesRegex(ValueError, "缺少 category"):
            self.one()
        self.assertEqual(self.calls, [])

    def test_invalid_generic_duration_category_is_not_sent_to_model(self):
        write_json(self.project / "facts.json", {"facts": [{
            "key": "duration", "category": "unsupported", "status": "verified",
            "value": "30日",
            "evidence": {"file": "tender.txt", "location": "第3行",
                         "quote": "项目工期为30日"},
        }]})
        with self.assertRaisesRegex(ValueError, "不受支持|不是受支持"):
            self.one()
        self.assertEqual(self.calls, [])

    def test_other_fact_category_is_preserved_without_duration_restrictions(self):
        state = read_json(self.project / "facts.json")
        state["facts"][0]["category"] = "schedule_assumption"
        write_json(self.project / "facts.json", state)
        self.one()
        data = json.loads(self.calls[0][2].split("\n", 1)[1])
        self.assertEqual(data["facts"][0]["category"], "schedule_assumption")

    def test_existing_human_text_is_never_overwritten_or_sent_to_model(self):
        file = self.project / "sections" / "S1.md"
        file.write_text("客户已确认并手工写好的实施计划", encoding="utf-8")
        result = self.one()
        self.assertEqual(result["status"], "skipped_existing")
        self.assertEqual(file.read_text(encoding="utf-8"), "客户已确认并手工写好的实施计划")
        self.assertEqual(self.calls, [])

    def test_scaffold_todo_can_be_replaced_without_touching_other_section(self):
        scaffold(self.project)
        second = self.project / "sections" / "S2.md"
        second.write_text("已有其他章节的正文，不允许覆盖", encoding="utf-8")
        self.one()
        self.assertNotIn("TODO", (self.project / "sections" / "S1.md").read_text(encoding="utf-8"))
        self.assertEqual(second.read_text(encoding="utf-8"), "已有其他章节的正文，不允许覆盖")

    def test_run_twice_is_idempotent(self):
        self.one()
        before = (self.project / "sections" / "S1.md").read_bytes()
        self.assertEqual(self.one()["status"], "skipped_existing")
        self.assertEqual((self.project / "sections" / "S1.md").read_bytes(), before)
        self.assertEqual(len(self.calls), 1)

    def test_source_change_blocks_generation(self):
        self.source.write_text("招标文件已被修改\n", encoding="utf-8")
        with self.assertRaisesRegex(ValueError, "证据核验未通过"):
            self.one()
        self.assertFalse((self.project / "sections" / "S1.md").exists())
        self.assertEqual(read_json(checkpoint_path(self.project, "S1"))["status"], "failed")

    def test_forged_index_text_is_rejected(self):
        data = read_json(self.index)
        data["blocks"][0]["text"] = "实施组织方案评分10分 外部伪造的信息"
        write_json(self.index, data)
        with self.assertRaisesRegex(ValueError, "索引文本|index_content_mismatch"):
            self.one()
        self.assertFalse((self.project / "sections" / "S1.md").exists())

    def test_remote_endpoint_requires_explicit_authorization(self):
        with self.assertRaisesRegex(ValueError, "默认禁止"):
            self.one(endpoint="https://external.example/v1")
        self.assertEqual(self.calls, [])

    def test_bad_model_response_coverage_is_rejected(self):
        def wrong(*args, **kwargs):
            return self.answer("OTHER")
        with self.assertRaisesRegex(ValueError, "没有覆盖"):
            write_section(self.project, "S1", [self.index], self.source_dir,
                          model="local", transport=wrong)
        self.assertFalse((self.project / "sections" / "S1.md").exists())

    def test_unknown_fact_from_model_is_rejected(self):
        def wrong(*args, **kwargs):
            return self.answer("R1", ["staff"])
        with self.assertRaisesRegex(ValueError, "未经核实"):
            write_section(self.project, "S1", [self.index], self.source_dir,
                          model="local", transport=wrong)

    def test_approval_is_explicit_and_binds_exact_bytes(self):
        self.one()
        with self.assertRaisesRegex(ValueError, "明确确认"):
            approve_section(self.project, "S1", acknowledgement="模型觉得可以了")
        approved = approve_section(self.project, "S1", acknowledgement=CONFIRM)
        self.assertEqual(approved["status"], "approved")
        self.assertNotIn(BANNER, (self.project / "sections" / "S1.md").read_text(encoding="utf-8"))
        self.one("S2")
        self.assertFalse(inspect(self.project, strict=True)["ok"])
        approve_section(self.project, "S2", acknowledgement=CONFIRM)
        self.assertTrue(inspect(self.project, strict=True)["ok"])
        with (self.project / "sections" / "S1.md").open("a", encoding="utf-8") as stream:
            stream.write("\n未经审核追加一条承诺\n")
        self.assertFalse(inspect(self.project, strict=True)["ok"])
        self.assertTrue(any("审核后正文已更改" in x for x in inspect(self.project, strict=True)["errors"]))

    def test_modified_pending_draft_cannot_be_approved_without_recheck(self):
        self.one()
        file = self.project / "sections" / "S1.md"
        file.write_text(file.read_text(encoding="utf-8") + "\n人工修改正文", encoding="utf-8")
        with self.assertRaisesRegex(ValueError, "审批前已被修改"):
            approve_section(self.project, "S1", acknowledgement=CONFIRM)

    def test_batch_failure_preserves_completed_sections_and_resume_skips_them(self):
        def failing(endpoint, model, prompt, *, api_key, timeout, instructions):
            sid = json.loads(prompt.split("\n", 1)[1])["section_id"]
            if sid == "S2":
                raise RuntimeError("模型连接中断")
            return self.answer("R1")
        with self.assertRaisesRegex(RuntimeError, "连接中断"):
            write_sections(self.project, None, [self.index], self.source_dir,
                           model="local", transport=failing)
        self.assertEqual(read_json(checkpoint_path(self.project, "S1"))["status"], "pending_review")
        self.assertEqual(read_json(checkpoint_path(self.project, "S2"))["status"], "failed")
        self.calls.clear()
        result = write_sections(self.project, None, [self.index], self.source_dir,
                                model="local", transport=self.fake)
        self.assertEqual([x["status"] for x in result["outcomes"]],
                         ["skipped_existing", "pending_review"])
        self.assertEqual(len(self.calls), 1)

    def test_cli_generate_and_approve_without_real_network(self):
        with patch("biaoshu.section_writer._request_model", side_effect=self.fake):
            with contextlib.redirect_stdout(io.StringIO()):
                self.assertEqual(main([
                    "write-sections", str(self.project), "--section", "S1",
                    "--index", str(self.index), "--source-dir", str(self.source_dir),
                    "--model", "local-demo",
                ]), 0)
        with contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(main([
                "approve-section", str(self.project), "--section", "S1",
                "--acknowledgement", CONFIRM,
            ]), 0)

    def test_partial_ai_write_keeps_journal_and_explicit_rollback(self):
        from biaoshu.section_transaction import stage_path, recover
        from biaoshu import review_transaction
        scaffold(self.project)
        doc = self.project / "sections" / "S1.md"
        previous = doc.read_bytes()
        original = review_transaction._atomic_bytes
        def fail_section(dest, raw):
            if dest == doc:
                raise OSError("simulated second file interruption")
            return original(dest, raw)
        with patch.object(review_transaction, "_atomic_bytes", side_effect=fail_section):
            with self.assertRaisesRegex(OSError, "simulated second file interruption"):
                self.one()
        self.assertTrue(stage_path(self.project, "S1").exists())
        self.assertFalse(inspect(self.project)["ok"])
        with self.assertRaisesRegex(ValueError, "section-recover"):
            self.one()
        with self.assertRaisesRegex(ValueError, "事务未完成"):
            approve_section(self.project, "S1", acknowledgement=CONFIRM)
        with self.assertRaisesRegex(ValueError, "--confirm"):
            recover(self.project, "S1")
        result = recover(self.project, "S1", confirm=True)
        self.assertEqual(result["status"], "restored")
        self.assertEqual(doc.read_bytes(), previous)
        self.assertFalse(checkpoint_path(self.project, "S1").exists())
        self.assertFalse(stage_path(self.project, "S1").exists())
        self.assertTrue(inspect(self.project)["ok"])
        self.assertEqual(self.one()["status"], "pending_review")

    def test_recovery_refuses_to_overwrite_human_edits(self):
        from biaoshu.section_transaction import stage_path, recover
        from biaoshu import review_transaction
        scaffold(self.project)
        doc = self.project / "sections" / "S1.md"
        with patch.object(review_transaction, "_atomic_bytes",
                          side_effect=OSError("simulated write failure")):
            with self.assertRaises(OSError):
                self.one()
        doc.write_text("人工更改过的独立实施方案", encoding="utf-8")
        with self.assertRaisesRegex(ValueError, "人工修改"):
            recover(self.project, "S1", confirm=True)
        self.assertEqual(doc.read_text(encoding="utf-8"), "人工更改过的独立实施方案")
        self.assertTrue(stage_path(self.project, "S1").exists())

    def test_recovery_of_stale_process_lock_requires_explicit_flag(self):
        from biaoshu.section_transaction import stage_path, recover
        from biaoshu import review_transaction
        scaffold(self.project)
        with patch.object(review_transaction, "_atomic_bytes",
                          side_effect=OSError("simulated interrupted process")):
            with self.assertRaises(OSError):
                self.one()
        lock = self.project / "reports" / "section-writing" / "S1.write.lock"
        lock.write_text("stale\n", encoding="utf-8")
        with self.assertRaisesRegex(ValueError, "unlock-stale"):
            recover(self.project, "S1", confirm=True)
        result = recover(self.project, "S1", confirm=True, unlock_stale=True)
        self.assertEqual(result["status"], "restored")
        self.assertFalse(lock.exists())
        self.assertFalse(stage_path(self.project, "S1").exists())

    def test_failed_generation_then_manual_completion_can_be_registered(self):
        from biaoshu.section_writer import accept_manual_section
        doc = self.project / "sections" / "S1.md"
        def fail(*args, **kwargs):
            raise RuntimeError("synthetic model outage")
        with self.assertRaisesRegex(RuntimeError, "synthetic model outage"):
            write_section(self.project, "S1", [self.index], self.source_dir,
                          model="local-demo", transport=fail)
        self.assertEqual(read_json(checkpoint_path(self.project, "S1"))["status"], "failed")
        doc.write_text("# 实施组织\n\n人工撰写：明确组织机制、负责人职责、质量复核程序、全过程记录和招标要求的实施步骤。\n",
                       encoding="utf-8")
        with self.assertRaisesRegex(ValueError, "--confirm"):
            accept_manual_section(self.project, "S1")
        outcome = accept_manual_section(self.project, "S1", confirm=True)
        self.assertEqual(outcome["status"], "manual_content_registered")
        self.assertTrue(Path(outcome["archive"]).is_file())
        self.assertFalse(checkpoint_path(self.project, "S1").exists())
        self.assertEqual(self.one()["status"], "skipped_existing")
        self.one("S2")
        approve_section(self.project, "S2", acknowledgement=CONFIRM)
        self.assertTrue(inspect(self.project, strict=True)["ok"])

    def test_manual_takeover_refuses_pending_ai_draft(self):
        from biaoshu.section_writer import accept_manual_section
        self.one()
        with self.assertRaisesRegex(ValueError, "只有生成失败"):
            accept_manual_section(self.project, "S1", confirm=True)
        self.assertEqual(read_json(checkpoint_path(self.project, "S1"))["status"], "pending_review")

    def test_manual_takeover_refuses_banner_even_with_failed_sidecar(self):
        from biaoshu.section_writer import accept_manual_section
        self.one()
        checkpoint = checkpoint_path(self.project, "S1")
        write_json(checkpoint, {"schema_version": 1, "section_id": "S1",
                                "status": "failed", "error_type": "RuntimeError"})
        with self.assertRaisesRegex(ValueError, "待审标记"):
            accept_manual_section(self.project, "S1", confirm=True)
        self.assertEqual(read_json(checkpoint)["status"], "failed")
        self.assertFalse(list(checkpoint.parent.glob("archive/*.json")))

    def test_approval_interruption_is_journaled_and_explicitly_rolled_back(self):
        from biaoshu.section_transaction import stage_path, recover
        from biaoshu import review_transaction
        self.one()
        doc = self.project / "sections" / "S1.md"
        sidecar = checkpoint_path(self.project, "S1")
        before_doc, before_meta = doc.read_bytes(), sidecar.read_bytes()
        atomic = review_transaction._atomic_bytes
        def fail_second(dest, raw):
            if dest == sidecar:
                raise OSError("simulated checkpoint commit failure")
            return atomic(dest, raw)
        with patch.object(review_transaction, "_atomic_bytes", side_effect=fail_second):
            with self.assertRaisesRegex(OSError, "simulated checkpoint commit failure"):
                approve_section(self.project, "S1", acknowledgement=CONFIRM)
        self.assertTrue(stage_path(self.project, "S1").exists())
        self.assertEqual(read_json(stage_path(self.project, "S1"))["status"], "approving")
        self.assertNotEqual(doc.read_bytes(), before_doc)
        self.assertEqual(sidecar.read_bytes(), before_meta)
        self.assertFalse(inspect(self.project, strict=True)["ok"])
        with self.assertRaisesRegex(ValueError, "section-recover"):
            approve_section(self.project, "S1", acknowledgement=CONFIRM)
        with self.assertRaisesRegex(ValueError, "--confirm"):
            recover(self.project, "S1")
        self.assertEqual(recover(self.project, "S1", confirm=True)["status"], "restored")
        self.assertEqual(doc.read_bytes(), before_doc)
        self.assertEqual(sidecar.read_bytes(), before_meta)
        self.assertFalse(stage_path(self.project, "S1").exists())
        self.assertEqual(approve_section(self.project, "S1", acknowledgement=CONFIRM)["status"],
                         "approved")

    def test_approval_refuses_manual_edits_after_partial_commit(self):
        from biaoshu.section_transaction import recover, stage_path
        from biaoshu import review_transaction
        self.one()
        doc = self.project / "sections" / "S1.md"
        original = review_transaction._atomic_bytes
        def fail_second(dest, raw):
            if dest.name == "S1.json":
                raise OSError("injected failure")
            return original(dest, raw)
        with patch.object(review_transaction, "_atomic_bytes", side_effect=fail_second):
            with self.assertRaises(OSError):
                approve_section(self.project, "S1", acknowledgement=CONFIRM)
        doc.write_text(doc.read_text(encoding="utf-8") + "\n人工又追加一条未经复核的承诺",
                       encoding="utf-8")
        with self.assertRaisesRegex(ValueError, "人工修改"):
            recover(self.project, "S1", confirm=True)
        self.assertTrue(stage_path(self.project, "S1").exists())

    def test_orphan_section_write_lock_can_be_cleared_only_explicitly(self):
        import os
        from biaoshu.section_transaction import recover
        folder = self.project / "reports" / "section-writing"
        folder.mkdir(exist_ok=True)
        lock = folder / "S1.write.lock"
        lock.write_text(json.dumps({"pid": 987654321, "status": "writing"}),
                        encoding="utf-8")
        with self.assertRaisesRegex(ValueError, "--unlock-stale"):
            recover(self.project, "S1", confirm=True)
        self.assertTrue(lock.exists())
        result = recover(self.project, "S1", confirm=True, unlock_stale=True)
        self.assertEqual(result["status"], "stale_lock_cleared")
        self.assertFalse(lock.exists())
        lock.write_text(json.dumps({"pid": os.getpid(), "status": "writing"}),
                        encoding="utf-8")
        with self.assertRaisesRegex(ValueError, "仍然存活"):
            recover(self.project, "S1", confirm=True, unlock_stale=True)
        self.assertTrue(lock.exists())

    def test_recovery_rejects_malformed_section_identity(self):
        from biaoshu.section_transaction import recover
        with self.assertRaisesRegex(ValueError, "不合法的小节 ID"):
            recover(self.project, "../outside", confirm=True, unlock_stale=True)

    def test_unapproved_reapproval_cannot_rebind_edited_approved_body(self):
        self.one()
        approve_section(self.project, "S1", acknowledgement=CONFIRM)
        path = self.project / "sections" / "S1.md"
        original = checkpoint_path(self.project, "S1").read_bytes()
        path.write_text(path.read_text(encoding="utf-8") + "\n人工追加另一项承诺", encoding="utf-8")
        with self.assertRaisesRegex(ValueError, "不能通过再次调用审批"):
            approve_section(self.project, "S1", acknowledgement=CONFIRM)
        self.assertEqual(checkpoint_path(self.project, "S1").read_bytes(), original)

    def test_approved_reapproval_cannot_rebind_changed_facts(self):
        self.one()
        approve_section(self.project, "S1", acknowledgement=CONFIRM)
        before = checkpoint_path(self.project, "S1").read_bytes()
        write_json(self.project / "facts.json", {"facts": [
            {"key": "deadline", "value": "60日", "status": "pending"},
        ]})
        with self.assertRaisesRegex(ValueError, "需求、事实或目录"):
            approve_section(self.project, "S1", acknowledgement=CONFIRM)
        self.assertEqual(checkpoint_path(self.project, "S1").read_bytes(), before)

    def test_new_doc_publisher_uses_atomic_exclusive_create(self):
        from biaoshu import review_transaction
        original = review_transaction.atomic_create
        seen = []
        def wrapper(dest, raw):
            seen.append(dest)
            self.assertFalse(dest.exists())
            return original(dest, raw)
        with patch.object(review_transaction, "atomic_create", side_effect=wrapper):
            self.one()
        self.assertEqual([x.name for x in seen], ["S1.md"])

    def test_concurrent_manual_creation_is_not_overwritten(self):
        from biaoshu import review_transaction
        doc = self.project / "sections" / "S1.md"
        def competitor(dest, raw):
            dest.write_text("用户同时手工新写的技术方案", encoding="utf-8")
            raise FileExistsError("the document already exists")
        with patch.object(review_transaction, "atomic_create", side_effect=competitor):
            with self.assertRaises(FileExistsError):
                self.one()
        self.assertEqual(doc.read_text(encoding="utf-8"), "用户同时手工新写的技术方案")
        self.assertFalse(inspect(self.project)["ok"])

    def test_locked_outline_is_not_mutated_by_generation(self):
        proposal = self.root / "proposal.json"
        write_json(proposal, outline_template(self.project))
        outline_plan(self.project, proposal, apply=True)
        before = (self.project / "outline.json").read_bytes()
        self.one()
        self.assertEqual(before, (self.project / "outline.json").read_bytes())


if __name__ == "__main__":
    unittest.main()
