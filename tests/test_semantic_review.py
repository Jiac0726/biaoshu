"""No-network adversarial semantic review tests using real indexed TXT and paragraphs."""
import contextlib
import io
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from biaoshu.cli import main
from biaoshu.core import initialize, read_json, write_json
from biaoshu.extraction import extract_document
from biaoshu.response_trace import ACKNOWLEDGEMENT, create_trace, trace_path
from biaoshu.semantic_review import review_responses


class SemanticReviewTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.project = self.root / "bid"
        initialize(self.project)
        self.sources = self.root / "source"
        self.sources.mkdir()
        self.original = self.sources / "fake-tender.txt"
        self.original.write_text(
            "技术评分：实施组织方案需说明岗位分工和进度检查，10分。\n"
            "技术评分：质量保障需说明自检和复核流程，15分。\n", encoding="utf-8"
        )
        self.index = self.root / "tender.index.json"
        write_json(self.index, extract_document(self.original).index)
        self.a = "本项目实行项目负责人统筹和专业岗位分工，建立每周进度检查与问题整改记录。"
        self.b = "质量管理采用班组自检、项目复核与成果抽查三道工序，问题形成可追踪的整改记录。"
        write_json(self.project / "requirements.json", {"requirements": [
            {"id": "R1", "title": "实施组织方案", "score": 10,
             "evidence": {"file": self.original.name, "location": "第1行",
                          "quote": "实施组织方案需说明岗位分工和进度检查"},
             "response_sections": ["S1"]},
            {"id": "R2", "title": "质量保障措施", "score": 15,
             "evidence": {"file": self.original.name, "location": "第2行",
                          "quote": "质量保障需说明自检和复核流程"},
             "response_sections": ["S2"]},
        ]})
        write_json(self.project / "outline.json", {"sections": [
            {"id": "S1", "title": "实施组织方案", "requirement_ids": ["R1"],
             "weight": 1, "target_words": 0},
            {"id": "S2", "title": "质量保障措施", "requirement_ids": ["R2"],
             "weight": 1, "target_words": 0},
        ]})
        (self.project / "sections" / "S1.md").write_text(
            "# 实施组织方案\n\n" + self.a + "\n", encoding="utf-8"
        )
        (self.project / "sections" / "S2.md").write_text(
            "# 质量保障措施\n\n" + self.b + "\n", encoding="utf-8"
        )
        create_trace(self.project)
        self.confirmed_trace()
        self.calls = []

    def confirmed_trace(self):
        state = read_json(trace_path(self.project))
        state["acknowledgement"] = ACKNOWLEDGEMENT
        for item, quote in zip(state["items"], (self.a, self.b)):
            item.update(line=3, quote=quote, decision="confirmed")
        write_json(trace_path(self.project), state)

    def fake(self, endpoint, model, prompt, *, api_key, timeout, instructions):
        self.calls.append((endpoint, model, prompt, api_key, timeout, instructions))
        data = json.loads(prompt.split("\n", 1)[1])
        self.assertEqual(data["reviewed_response_line"], 3)
        self.assertEqual(data["section_id"], "S" + data["requirement_id"][1:])
        self.assertIn("未获批准", instructions) if "未获批准" in instructions else None
        return json.dumps({
            "verdict": "partial" if data["requirement_id"] == "R1" else "adequate",
            "severity": "medium" if data["requirement_id"] == "R1" else "low",
            "reason": "已说明组织分工，但尚需细化进度检查的责任划分。",
            "suggestion": "补充每周进度检查责任人、时间节点与问题复核的可追踪记录。",
            "source_quote": data["tender_source"][0:22],
            "response_quote": data["response_text"][0:22],
        }, ensure_ascii=False)

    def run_analysis(self, **options):
        return review_responses(
            self.project, [self.index], self.sources,
            model="local-test", transport=self.fake, **options
        )

    def test_advisory_semantic_report_does_not_approve_or_mutate(self):
        before = [p.read_bytes() for p in (
            self.project / "sections" / "S1.md", self.project / "sections" / "S2.md",
            trace_path(self.project),
        )]
        result = self.run_analysis()
        self.assertEqual(result["status"], "suggestions_only")
        self.assertEqual(result["statistics"], {"examined_links": 2, "potential_issues": 1})
        self.assertEqual([r["verdict"] for r in result["items"]], ["partial", "adequate"])
        self.assertTrue(all(r["status"] == "pending_human_review" for r in result["items"]))
        self.assertEqual(len(self.calls), 2)
        after = [p.read_bytes() for p in (
            self.project / "sections" / "S1.md", self.project / "sections" / "S2.md",
            trace_path(self.project),
        )]
        self.assertEqual(before, after)
        self.assertEqual(self.calls[0][0], "http://127.0.0.1:11434/v1/chat/completions")

    def test_requires_completed_human_response_trace(self):
        trace = read_json(trace_path(self.project))
        trace["items"][0]["decision"] = "pending"
        write_json(trace_path(self.project), trace)
        with self.assertRaisesRegex(ValueError, "trace-audit"):
            self.run_analysis()
        self.assertEqual(self.calls, [])

    def test_source_tampering_blocks_before_model(self):
        self.original.write_text("篡改招标数据", encoding="utf-8")
        with self.assertRaisesRegex(ValueError, "原文证据"):
            self.run_analysis()
        self.assertEqual(self.calls, [])

    def test_forged_index_content_is_rejected(self):
        idx = read_json(self.index)
        idx["blocks"][0]["text"] = "技术评分：实施组织方案需说明岗位分工和进度检查，30分。"
        write_json(self.index, idx)
        with self.assertRaisesRegex(ValueError, "索引文本|证据验证失败"):
            self.run_analysis()
        self.assertEqual(self.calls, [])

    def test_remote_model_disallowed_without_explicit_optin(self):
        with self.assertRaisesRegex(ValueError, "默认禁止"):
            self.run_analysis(endpoint="https://model.example/v1")
        self.assertEqual(self.calls, [])
        result = self.run_analysis(endpoint="https://model.example/v1", allow_remote=True)
        self.assertEqual(len(result["items"]), 2)
        self.assertEqual(self.calls[0][0], "https://model.example/v1/chat/completions")

    def test_model_fake_source_quote_is_rejected(self):
        def liar(*args, **kwargs):
            data = json.loads(args[2].split("\n", 1)[1])
            answer = json.loads(self.fake(*args, **kwargs))
            answer["source_quote"] = "实际招标原文没有写过的虚假技术标准"
            return json.dumps(answer, ensure_ascii=False)
        with self.assertRaisesRegex(ValueError, "source_quote"):
            review_responses(self.project, [self.index], self.sources,
                             model="test", transport=liar)

    def test_model_fake_response_quote_is_rejected(self):
        def liar(*args, **kwargs):
            answer = json.loads(self.fake(*args, **kwargs))
            answer["response_quote"] = "真实章节里从来不存在的虚假响应文本"
            return json.dumps(answer, ensure_ascii=False)
        with self.assertRaisesRegex(ValueError, "response_quote"):
            review_responses(self.project, [self.index], self.sources,
                             model="test", transport=liar)

    def test_model_bad_schema_and_verdict_rejected(self):
        for output in ('{"verdict":"pass"}', "not-json",
                       '{"verdict":[],"severity":"low","reason":"足够长的理由满足内容要求",'
                       '"suggestion":"需要提供足够长的补充建议","source_quote":"技术评分",'
                       '"response_quote":"本项目实行"}'):
            with self.subTest(output=output):
                def wrong(*args, **kwargs):
                    return output
                with self.assertRaises(ValueError):
                    review_responses(self.project, [self.index], self.sources,
                                     model="test", transport=wrong)

    def test_original_changed_during_model_call_fails_without_report(self):
        def mutate(*args, **kwargs):
            answer = self.fake(*args, **kwargs)
            self.original.write_text("模型审稿期间变化", encoding="utf-8")
            return answer
        with self.assertRaisesRegex(ValueError, "证据已失效"):
            review_responses(self.project, [self.index], self.sources,
                             model="test", transport=mutate)

    def test_section_changed_during_model_call_fails(self):
        def mutate(*args, **kwargs):
            answer = self.fake(*args, **kwargs)
            with (self.project / "sections" / "S1.md").open("a", encoding="utf-8") as stream:
                stream.write("\n变更后的正文承诺")
            return answer
        with self.assertRaisesRegex(ValueError, "正文 S1 已被修改"):
            review_responses(self.project, [self.index], self.sources,
                             model="test", transport=mutate)

    def test_cli_emits_json_only_with_explicit_output(self):
        import biaoshu.semantic_review as module
        path = self.root / "review-suggestions.json"
        with patch.object(module, "_request_model", side_effect=self.fake):
            with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
                code = main([
                    "semantic-review", str(self.project),
                    "--index", str(self.index), "--source-dir", str(self.sources),
                    "--model", "local-test", "--output", str(path),
                ])
        self.assertEqual(code, 0)
        self.assertEqual(read_json(path)["status"], "suggestions_only")
        self.assertEqual(len(read_json(path)["items"]), 2)

    def test_cli_failure_never_writes_partial_report(self):
        import biaoshu.semantic_review as module
        path = self.root / "never-saved.json"
        with patch.object(module, "_request_model", side_effect=RuntimeError("模型断线")):
            with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
                code = main([
                    "semantic-review", str(self.project),
                    "--index", str(self.index), "--source-dir", str(self.sources),
                    "--model", "local-test", "--output", str(path),
                ])
        self.assertNotEqual(code, 0)
        self.assertFalse(path.exists())

    def test_no_model_means_no_successful_review(self):
        with self.assertRaisesRegex(ValueError, "model"):
            review_responses(self.project, [self.index], self.sources,
                             model="", transport=self.fake)
        self.assertEqual(self.calls, [])


if __name__ == "__main__":
    unittest.main()
