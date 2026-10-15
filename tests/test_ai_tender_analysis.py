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
