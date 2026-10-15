"""Integration release blockers: adversarial source, privacy and approval checks."""
import hashlib
import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from biaoshu.ai_tender_analysis import _request_model
from biaoshu.consistency import analyze_consistency
from biaoshu.core import initialize, inspect, write_json
from biaoshu.evidence import verify_evidence


class HardeningRegressionTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.project = self.root / "project"
        initialize(self.project)
        self.source_dir = self.root / "sources"
        self.source_dir.mkdir()
        self.source = self.source_dir / "tender.txt"
        self.source.write_text("技术评分要求写出实施方案\n", encoding="utf-8")
        self.index = self.root / "tender.index.json"
        from biaoshu.extraction import extract_document
        self.index_obj = extract_document(self.source).index
        write_json(self.index, self.index_obj)
        write_json(self.project / "requirements.json", {"requirements": [
            {"id": "R1", "title": "实施方案", "score": 10,
             "evidence": {"file": "tender.txt", "location": "第1行", "quote": "技术评分要求写出实施方案"},
             "response_sections": ["S1"]},
        ]})
        write_json(self.project / "outline.json", {"sections": [
            {"id": "S1", "title": "实施方案", "requirement_ids": ["R1"],
             "weight": 1, "target_words": 0},
        ]})
        self.chapter = self.project / "sections" / "S1.md"
        self.chapter.write_text("# 实施方案\n\n详细介绍实施任务安排及质量复核机制。\n", encoding="utf-8")

    def test_fake_block_with_real_file_digest_does_not_pass(self):
        index = json.loads(self.index.read_text(encoding="utf-8"))
        index["blocks"][0]["text"] = "不存在于真实招标文件中的虚构人员配置"
        write_json(self.index, index)
        reqs = json.loads((self.project / "requirements.json").read_text(encoding="utf-8"))
        reqs["requirements"][0]["evidence"]["quote"] = "不存在于真实招标文件中的虚构人员配置"
        write_json(self.project / "requirements.json", reqs)
        report = verify_evidence(self.project, [self.index], self.source_dir)
        self.assertFalse(report["ok"])
        self.assertIn("index_content_mismatch", {e["code"] for e in report["errors"]})

    def test_stable_index_passes_when_hashed_and_reextracted(self):
        self.assertTrue(verify_evidence(self.project, [self.index], self.source_dir)["ok"])

    def test_docx_column_metadata_cannot_be_cited_as_source_text(self):
        from docx import Document
        from biaoshu.extraction import extract_document
        doc = Document()
        table = doc.add_table(rows=1, cols=2)
        table.cell(0, 0).text = "评分项"
        table.cell(0, 1).text = "实施方案10分"
        tender = self.source_dir / "table.docx"
        doc.save(tender)
        index = self.root / "table.index.json"
        write_json(index, extract_document(tender).index)
        reqs = json.loads((self.project / "requirements.json").read_text(encoding="utf-8"))
        reqs["requirements"][0]["evidence"] = {
            "file": "table.docx", "location": "第1表第1行", "quote": "列2：实施方案10分",
        }
        write_json(self.project / "requirements.json", reqs)
        report = verify_evidence(self.project, [index], self.source_dir)
        self.assertFalse(report["ok"])
        self.assertIn("quote_mismatch", {e["code"] for e in report["errors"]})
        reqs["requirements"][0]["evidence"]["quote"] = "实施方案10分"
        write_json(self.project / "requirements.json", reqs)
        self.assertTrue(verify_evidence(self.project, [index], self.source_dir)["ok"])

    def test_model_adapter_ignores_proxy_environment(self):
        class Response:
            status = 200
            def __enter__(self):
                return self
            def __exit__(self, *args):
                return False
            def read(self, max_size):
                return b'{"choices":[{"message":{"content":"{}"},"finish_reason":"stop"}]}'
        class FakeOpener:
            def open(self, request, timeout):
                self.request = request
                return Response()
        seen = []
        def capture(*handlers):
            seen.extend(handlers)
            return FakeOpener()
        with patch.dict(os.environ, {"HTTP_PROXY": "http://untrusted-proxy.example:8888",
                                     "HTTPS_PROXY": "http://untrusted-proxy.example:8888",
                                     "NO_PROXY": ""}), patch(
                "biaoshu.ai_tender_analysis.urllib.request.build_opener", side_effect=capture):
            result = _request_model(
                "http://127.0.0.1:11434/v1/chat/completions", "local-llm", "confidential tender",
                api_key="fake-local-secret", timeout=3)
        self.assertEqual(result, "{}")
        proxy_handlers = [x for x in seen
                          if isinstance(x, __import__("urllib.request", fromlist=["ProxyHandler"]).ProxyHandler)]
        self.assertEqual(len(proxy_handlers), 1)
        self.assertEqual(proxy_handlers[0].proxies, {})

    def test_missing_checkpoint_never_approves_banner_draft(self):
        self.chapter.write_text(
            "# 实施方案\n\n> AI生成草稿（待人工审查）\n\n以下是详细的实施计划、过程管理与质量复核机制。\n",
            encoding="utf-8",
        )
        report = inspect(self.project, strict=True)
        self.assertFalse(report["ok"])
        self.assertTrue(any("待审核标记" in e for e in report["errors"]))

    def test_bounded_values_do_not_create_false_conflicts(self):
        write_json(self.project / "facts.json", {"facts": [
            {"key": "response_time", "status": "verified", "value": "不超过2小时",
             "evidence": {"file": "tender.txt", "location": "第1行",
                          "quote": "技术评分要求写出实施方案"}},
        ]})
        self.chapter.write_text("# 实施方案\n\n响应时间为2小时内，我们将在时限内响应。\n",
                                encoding="utf-8")
        self.assertTrue(analyze_consistency(self.project)["ok"])
        self.chapter.write_text("# 实施方案\n\n响应时间为1小时，安排人员及时响应。\n",
                                encoding="utf-8")
        self.assertTrue(analyze_consistency(self.project)["ok"])
        self.assertEqual(analyze_consistency(self.project)["statistics"]["errors"], 0)

    def draft(self, transport=None):
        from biaoshu.section_writer import write_section
        self.chapter.unlink(missing_ok=True)
        def model(*args, **kwargs):
            return json.dumps({
                "body": "本项目设置实施协调组、质量控制岗和现场核查环节，明确责任分工和日常检查安排，形成阶段成果清单和复核记录，保障技术要求得到执行。",
                "used_requirement_ids": ["R1"],
                "used_fact_keys": [],
            }, ensure_ascii=False)
        return write_section(self.project, "S1", [self.index], self.source_dir,
                             model="test-local-model", transport=transport or model)

    def test_model_source_and_index_changed_together_is_blocked(self):
        from biaoshu.extraction import extract_document
        def tamper(*args, **kwargs):
            self.source.write_text(
                "技术评分要求写出实施方案\n追加完全不同的招标要求\n", encoding="utf-8")
            write_json(self.index, extract_document(self.source).index)
            return json.dumps({
                "body": "本项目设置实施协调组、质量控制岗和现场核查环节，明确责任分工和日常检查安排，形成阶段成果清单和复核记录，保障技术要求得到执行。",
                "used_requirement_ids": ["R1"], "used_fact_keys": [],
            }, ensure_ascii=False)
        with self.assertRaisesRegex(ValueError, "模型生成期间招标原件或证据索引发生变化"):
            self.draft(tamper)
        self.assertFalse(self.chapter.exists())

    def test_changed_requirement_or_fact_blocks_approval(self):
        from biaoshu.section_writer import approve_section, CONFIRM
        self.draft()
        reqs = json.loads((self.project / "requirements.json").read_text(encoding="utf-8"))
        reqs["requirements"][0]["description"] = "写作后新增现场资格要求"
        write_json(self.project / "requirements.json", reqs)
        with self.assertRaisesRegex(ValueError, "正式需求、事实或目录已经变动"):
            approve_section(self.project, "S1", acknowledgement=CONFIRM)

    def test_approved_chapter_detects_subsequent_fact_changes(self):
        from biaoshu.section_writer import approve_section, CONFIRM
        self.draft()
        approve_section(self.project, "S1", acknowledgement=CONFIRM)
        self.assertTrue(inspect(self.project, strict=True)["ok"])
        write_json(self.project / "facts.json", {"facts": [
            {"key": "project_status", "value": "待甲方确认", "status": "pending"}
        ]})
        report = inspect(self.project, strict=True)
        self.assertFalse(report["ok"])
        self.assertTrue(any("需求、事实或目录发生变化" in e for e in report["errors"]))

    def test_approved_chapter_detects_source_changes(self):
        from biaoshu.section_writer import approve_section, CONFIRM
        self.draft()
        approve_section(self.project, "S1", acknowledgement=CONFIRM)
        self.source.write_text(
            "技术评分要求写出实施方案\n写作后新增特殊评分项\n", encoding="utf-8")
        report = inspect(self.project, strict=True)
        self.assertFalse(report["ok"])
        self.assertTrue(any("招标原件发生变化" in e for e in report["errors"]))

    def test_existing_unbound_checkpoint_cannot_be_approved(self):
        from biaoshu.section_writer import approve_section, checkpoint_path, CONFIRM
        self.draft()
        cp = checkpoint_path(self.project, "S1")
        meta = json.loads(cp.read_text(encoding="utf-8"))
        meta.pop("source_manifest")
        write_json(cp, meta)
        with self.assertRaisesRegex(ValueError, "检查点缺少原文来源指纹"):
            approve_section(self.project, "S1", acknowledgement=CONFIRM)

    def test_calendar_date_not_parsed_as_year_duration(self):
        self.chapter.write_text(
            "# 实施方案\n\n服务期限为2026年1月1日至2027年12月31日。\n", encoding="utf-8")
        self.assertEqual(analyze_consistency(self.project)["statistics"]["commitments_detected"], 0)

    def test_subschedule_is_not_global_project_duration(self):
        self.chapter.write_text(
            "# 实施方案\n\n设备供货工期为15日，项目工期为30日。\n", encoding="utf-8")
        report = analyze_consistency(self.project)
        self.assertTrue(report["ok"])
        self.assertEqual(report["statistics"]["commitments_detected"], 1)


if __name__ == "__main__":
    unittest.main()
