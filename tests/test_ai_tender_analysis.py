"""No-network integration tests for the explicit, local-first model adapter."""
import hashlib
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from biaoshu.ai_tender_analysis import analyze_tender, _url


class TenderAiTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.sources = self.root / "sources"
        self.sources.mkdir()
        self.source = self.sources / "tender.txt"
        self.source.write_text("技术评分\n实施方案评分10分\n服务期限为30日\n", encoding="utf-8")
        self.index_path = self.root / "tender.index.json"
        self.index = {
            "schema_version": 1,
            "source_file": "tender.txt",
            "sha256": hashlib.sha256(self.source.read_bytes()).hexdigest(),
            "blocks": [
                {"location": "第1行", "kind": "line", "text": "技术评分"},
                {"location": "第2行", "kind": "line", "text": "实施方案评分10分"},
                {"location": "第3行", "kind": "line", "text": "服务期限为30日"},
            ],
        }
        self.save_index()

    def save_index(self):
        self.index_path.write_text(json.dumps(self.index, ensure_ascii=False), encoding="utf-8")

    def response(self, *, quote="实施方案评分10分", location="第2行"):
        return json.dumps({"items": [{
            "kind": "technical_score",
            "title": "实施方案",
            "score": 10,
            "evidence": {"file": "tender.txt", "location": location, "quote": quote},
            "rationale": "应单独响应",
        }]}, ensure_ascii=False)

    def run_analysis(self, response=None, **kwargs):
        calls = []
        def fake(endpoint, model, prompt, *, api_key, timeout):
            calls.append((endpoint, model, prompt, api_key, timeout))
            return self.response() if response is None else response
        result = analyze_tender([self.index_path], self.sources,
                                model="qwen-local", transport=fake, **kwargs)
        return result, calls

    def test_valid_ai_item_remains_unapproved(self):
        result, calls = self.run_analysis()
        self.assertEqual(result["status"], "suggestions_only")
        self.assertEqual(result["candidates"][0]["status"], "pending_review")
        self.assertEqual(result["candidates"][0]["evidence"]["location"], "第2行")
        self.assertEqual(calls[0][0], "http://127.0.0.1:11434/v1/chat/completions")
        self.assertIn("实施方案评分10分", calls[0][2])

    def test_remote_endpoint_requires_opt_in_before_transport(self):
        with self.assertRaisesRegex(ValueError, "默认禁止"):
            self.run_analysis(endpoint="https://external.example/v1")
        result, calls = self.run_analysis(endpoint="https://external.example/v1", allow_remote=True)
        self.assertEqual(len(result["candidates"]), 1)
        self.assertEqual(calls[0][0], "https://external.example/v1/chat/completions")

    def test_redirect_like_endpoint_and_url_credentials_rejected(self):
        for endpoint in ("https://user:password@remote.example/v1",
                         "http://127.0.0.1:11434/v1?next=https://remote.example",
                         "file:///tmp/sock", "http://127.0.0.1:11434/evil"):
            with self.subTest(endpoint=endpoint), self.assertRaises(ValueError):
                self.run_analysis(endpoint=endpoint, allow_remote=True)

    def test_hallucinated_quote_is_rejected(self):
        with self.assertRaisesRegex(ValueError, "引文不在"):
            self.run_analysis(self.response(quote="凭空编造的设备参数"))

    def test_wrong_location_is_rejected(self):
        with self.assertRaisesRegex(ValueError, "引文不在"):
            self.run_analysis(self.response(location="第99行"))

    def test_model_must_return_strict_json(self):
        for response in ('{"items":[],"approved":true}', "not a json", '{"items":{}}'):
            with self.subTest(response=response), self.assertRaises(ValueError):
                self.run_analysis(response)

    def test_invalid_category_and_score_rejected(self):
        obj = json.loads(self.response())
        obj["items"][0]["kind"] = "price_score"
        with self.assertRaisesRegex(ValueError, "分类"):
            self.run_analysis(json.dumps(obj))
        obj["items"][0]["kind"] = "technical_score"
        obj["items"][0]["score"] = "10"
        with self.assertRaisesRegex(ValueError, "分数"):
            self.run_analysis(json.dumps(obj))

    def test_altered_original_rejected_before_model(self):
        self.source.write_text("修改内容", encoding="utf-8")
        with self.assertRaisesRegex(ValueError, "已变化"):
            self.run_analysis()

    def test_source_change_during_request_rejected(self):
        def fake(*args, **kwargs):
            self.source.write_text("再次变动", encoding="utf-8")
            return self.response()
        with self.assertRaisesRegex(ValueError, "分析期间"):
            analyze_tender([self.index_path], self.sources, model="local", transport=fake)

    def test_missing_env_secret_rejected(self):
        with patch.dict("os.environ", {}, clear=True), self.assertRaisesRegex(ValueError, "没有值"):
            self.run_analysis(api_key_env="NOT_CONFIGURED")

    def test_omitted_blocks_warning(self):
        result, _ = self.run_analysis(max_blocks=1)
        self.assertGreater(result["statistics"]["omitted_blocks"], 0)
        self.assertTrue(any("跳过" in warning for warning in result["warnings"]))

    def test_empty_items_are_not_treated_as_a_pass(self):
        result, _ = self.run_analysis('{"items":[]}')
        self.assertEqual(result["candidates"], [])
        self.assertEqual(result["status"], "suggestions_only")

    def update_real_source(self, content):
        from biaoshu.extraction import extract_document
        self.source.write_text(content, encoding="utf-8")
        self.index = extract_document(self.source).index
        self.save_index()

    def test_long_source_score_after_first_3000_chars_survives(self):
        source = "无" * 3450 + "培训方案：优秀5分"
        self.update_real_source(source + "\n")
        result_text = json.dumps({"items": [{
            "kind": "technical_score", "title": "培训方案", "score": 5,
            "evidence": {"file": "tender.txt", "location": "第1行",
                         "quote": "培训方案：优秀5分"},
            "rationale": "需要人工核实评分方式",
        }]}, ensure_ascii=False)
        result, calls = self.run_analysis(result_text)
        blocks = json.loads(calls[0][2].split("\n\n", 1)[1])
        self.assertTrue(any("培训方案：优秀5分" in block["text"] for block in blocks))
        self.assertTrue(all(len(block["text"]) <= 3000 for block in blocks))
        self.assertEqual(result["candidates"][0]["score"], 5)
        self.assertEqual(result["statistics"]["long_source_blocks"], 1)
        self.assertTrue(any("拆分" in item for item in result["warnings"]))

    def test_long_source_omitted_fragment_is_reported(self):
        self.update_real_source("技术评分" + "甲" * 3300 + "培训方案：优秀5分\n")
        result, calls = self.run_analysis('{"items":[]}', max_blocks=1)
        self.assertEqual(result["statistics"]["long_source_blocks"], 1)
        self.assertGreater(result["statistics"]["omitted_blocks"], 0)
        self.assertTrue(any("跳过" in item for item in result["warnings"]))

    def test_score_only_technical_line_without_generic_topic_keyword_is_selected(self):
        self.update_real_source("培训方案：优秀5分\n")
        result = json.dumps({"items": [{
            "kind": "technical_score", "title": "培训方案", "score": 5,
            "evidence": {"file": "tender.txt", "location": "第1行",
                         "quote": "培训方案：优秀5分"},
            "rationale": "人工确认是否属于技术评分",
        }]}, ensure_ascii=False)
        report, calls = self.run_analysis(result)
        self.assertEqual(len(report["candidates"]), 1)
        self.assertIn("培训方案：优秀5分", calls[0][2])

    def test_minutes_not_rated_as_score_or_selected_as_scoring_evidence(self):
        from biaoshu.ai_tender_analysis import _select_blocks
        self.update_real_source("服务响应时间30分钟\n")
        chosen, omitted = _select_blocks([self.index], max_blocks=1, max_chars=4000)
        self.assertEqual(len(chosen), 1)  # A service requirement, not a score.
        self.assertEqual(omitted, 0)
        bogus = json.dumps({"items": [{
            "kind": "technical_score", "title": "响应速度", "score": 30,
            "evidence": {"file": "tender.txt", "location": "第1行",
                         "quote": "服务响应时间30分钟"},
            "rationale": "数字不应被误当成评分分数",
        }]}, ensure_ascii=False)
        with self.assertRaisesRegex(ValueError, "分值无引文依据"):
            self.run_analysis(bogus)

    def test_real_scoring_line_outranks_thirty_minute_requirement(self):
        from biaoshu.ai_tender_analysis import _select_blocks
        self.update_real_source("服务响应时间30分钟\n培训方案：优秀5分\n")
        chosen, omitted = _select_blocks([self.index], max_blocks=1, max_chars=4000)
        self.assertEqual(chosen[0]["location"], "第2行")
        self.assertIn("优秀5分", chosen[0]["text"])
        self.assertEqual(omitted, 1)

    def test_numeric_model_score_must_match_quote_not_other_line(self):
        self.update_real_source("实施方案评分5分\n人员配备评分10分\n")
        payload = json.dumps({"items": [{
            "kind": "technical_score", "title": "实施方案", "score": 10,
            "evidence": {"file": "tender.txt", "location": "第1行",
                         "quote": "实施方案评分5分"},
            "rationale": "不能引用第二行的10分为第一行评分",
        }]}, ensure_ascii=False)
        with self.assertRaisesRegex(ValueError, "分值无引文依据"):
            self.run_analysis(payload)

    def test_fullwidth_decimal_score_uses_normalized_original(self):
        self.update_real_source("技术评分：实施方案优秀５．５分\n")
        payload = json.dumps({"items": [{
            "kind": "technical_score", "title": "实施方案", "score": 5.5,
            "evidence": {"file": "tender.txt", "location": "第1行",
                         "quote": "实施方案优秀５．５分"},
            "rationale": "有且只有5.5分",
        }]}, ensure_ascii=False)
        report, _ = self.run_analysis(payload)
        self.assertEqual(report["candidates"][0]["score"], 5.5)
        obj = json.loads(payload)
        obj["items"][0]["score"] = 5
        with self.assertRaisesRegex(ValueError, "分值无引文依据"):
            self.run_analysis(json.dumps(obj, ensure_ascii=False))

    def test_partial_quote_cannot_hide_other_grading_tier(self):
        self.update_real_source("技术评分：合格得5分，优秀得10分\n")
        payload = json.dumps({"items": [{
            "kind": "technical_score", "title": "技术评分", "score": 10,
            "evidence": {"file": "tender.txt", "location": "第1行",
                         "quote": "优秀得10分"},
            "rationale": "模型试图只引用优秀档",
        }]}, ensure_ascii=False)
        with self.assertRaisesRegex(ValueError, "多档评分"):
            self.run_analysis(payload)
        item = json.loads(payload)
        item["items"][0]["score"] = None
        report, _ = self.run_analysis(json.dumps(item, ensure_ascii=False))
        self.assertIsNone(report["candidates"][0]["score"])

    def test_abbreviated_minutes_not_misclassified_as_score(self):
        from biaoshu.ai_tender_analysis import _select_blocks
        self.update_real_source("服务响应时间30分内到场\n培训方案：优秀5分\n")
        selected, omitted = _select_blocks([self.index], max_blocks=1, max_chars=4000)
        self.assertEqual(selected[0]["location"], "第2行")
        self.assertEqual(omitted, 1)
        payload = json.dumps({"items": [{
            "kind": "technical_score", "title": "响应时间", "score": 30,
            "evidence": {"file": "tender.txt", "location": "第1行",
                         "quote": "服务响应时间30分内到场"},
            "rationale": "分钟时限不能算评分",
        }]}, ensure_ascii=False)
        with self.assertRaisesRegex(ValueError, "分值无引文依据"):
            self.run_analysis(payload)

    def test_price_score_does_not_consume_technical_evidence_budget(self):
        from biaoshu.ai_tender_analysis import _select_blocks
        self.update_real_source("投标报价得5分\n培训方案：优秀5分\n")
        selected, omitted = _select_blocks([self.index], max_blocks=1, max_chars=4000)
        self.assertEqual([item["location"] for item in selected], ["第2行"])
        self.assertEqual(omitted, 0)

    def test_model_cannot_invent_score_absent_from_cited_quote(self):
        self.update_real_source("技术要求：项目实施方案必须完整\n")
        payload = json.dumps({"items": [{
            "kind": "technical_score", "title": "实施方案", "score": 100,
            "evidence": {"file": "tender.txt", "location": "第1行",
                         "quote": "项目实施方案必须完整"},
            "rationale": "不得将任意分值编造出来",
        }]}, ensure_ascii=False)
        with self.assertRaisesRegex(ValueError, "分值无引文依据"):
            self.run_analysis(payload)

    def test_multitier_source_requires_null_score(self):
        self.update_real_source("技术评分：合格得5分，优秀得10分\n")
        payload = json.loads(self.response(quote="合格得5分，优秀得10分", location="第1行"))
        with self.assertRaisesRegex(ValueError, "多档评分"):
            self.run_analysis(json.dumps(payload, ensure_ascii=False))
        payload["items"][0]["score"] = None
        report, _ = self.run_analysis(json.dumps(payload, ensure_ascii=False))
        self.assertIsNone(report["candidates"][0]["score"])

    def test_valid_single_source_score_is_accepted_when_precisely_quoted(self):
        report, _ = self.run_analysis()
        self.assertEqual(report["candidates"][0]["score"], 10.0)

    def test_index_extraction_warnings_propagate_with_filename(self):
        from docx import Document
        from biaoshu.extraction import extract_document
        source = self.sources / "tender.docx"
        document = Document()
        document.add_paragraph("实施方案评分10分")
        document.save(source)
        self.source = source
        self.index = extract_document(source).index
        self.save_index()
        report, _ = self.run_analysis('{"items":[]}')
        self.assertTrue(any("tender.docx：DOCX 页码" in w
                            for w in report["warnings"]))

    def test_fake_or_removed_extraction_warnings_blocked(self):
        self.index["warnings"] = ["文件虽然完全可读取，但索引写入了不存在的扫描失败"]
        self.save_index()
        with self.assertRaisesRegex(ValueError, "提取警告"):
            self.run_analysis('{"items":[]}')

    def test_cli_saves_mocked_suggestions_without_touching_project_state(self):
        import contextlib
        import io
        from biaoshu.cli import main
        result = {"status": "suggestions_only", "candidates": [],
                  "statistics": {"selected_blocks": 1}}
        output = self.root / "model-suggestions.json"
        with patch("biaoshu.cli.analyze_tender", return_value=result) as fake:
            with contextlib.redirect_stdout(io.StringIO()):
                code = main(["analyze-ai", "--index", str(self.index_path),
                             "--source-dir", str(self.sources),
                             "--model", "my-local-model", "--output", str(output)])
        self.assertEqual(code, 0)
        self.assertEqual(json.loads(output.read_text(encoding="utf-8")), result)
        self.assertEqual(fake.call_args.kwargs["model"], "my-local-model")
        self.assertFalse(fake.call_args.kwargs["allow_remote"])

    def test_cli_failure_does_not_save_report(self):
        import contextlib
        import io
        from biaoshu.cli import main
        output = self.root / "failed-suggestions.json"
        with patch("biaoshu.cli.analyze_tender", side_effect=ValueError("证据未核验")):
            with contextlib.redirect_stderr(io.StringIO()):
                code = main(["analyze-ai", "--index", str(self.index_path),
                             "--source-dir", str(self.sources),
                             "--model", "my-local-model", "--output", str(output)])
        self.assertNotEqual(code, 0)
        self.assertFalse(output.exists())


if __name__ == "__main__":
    unittest.main()
