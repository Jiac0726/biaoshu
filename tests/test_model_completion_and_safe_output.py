"""Adversarial tests for model completion and never-overwrite output gates."""
import contextlib
import io
import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from biaoshu.ai_tender_analysis import _request_model
from biaoshu.cli import main
from biaoshu.core import initialize, write_json
from biaoshu.safe_report import write_new_report


class FakeHTTPResponse:
    status = 200
    def __init__(self, obj):
        self.raw = json.dumps(obj).encode("utf-8")
    def __enter__(self):
        return self
    def __exit__(self, *_):
        return False
    def read(self, _length):
        return self.raw


class ModelCompletionAndSafeOutputTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.project = self.root / "bid"
        initialize(self.project)
        self.sources = self.root / "sources"
        self.sources.mkdir()
        self.source = self.sources / "tender.txt"
        self.source.write_text("本地原始招标文字绝不能被替换", encoding="utf-8")

    def model(self, reason="stop", *, missing=False, message="{}"):
        class FakeOpener:
            def __init__(self, data):
                self.data = data
            def open(self, request, timeout):
                return FakeHTTPResponse(self.data)
        choice = {"message": {"content": message}}
        if not missing:
            choice["finish_reason"] = reason
        payload = {"choices": [choice]}
        with patch("biaoshu.ai_tender_analysis.urllib.request.build_opener",
                   return_value=FakeOpener(payload)):
            return _request_model(
                "http://127.0.0.1:11434/v1/chat/completions",
                "fictional-test-model", "secret test tender",
                api_key="fictional-test-secret", timeout=5
            )

    def test_valid_completion_accepts_explicit_stop(self):
        self.assertEqual(self.model("stop"), "{}")
        self.assertEqual(self.model("eos_token"), "{}")

    def test_truncated_valid_json_is_never_treated_as_complete(self):
        for reason in ("length", "tool_calls", "content_filter", None, [], 3, "error"):
            with self.subTest(reason=reason), self.assertRaisesRegex(ValueError, "finish_reason"):
                self.model(reason)

    def test_missing_finish_reason_fails_closed(self):
        with self.assertRaisesRegex(ValueError, "chat completion JSON"):
            self.model(missing=True)

    def test_existing_report_is_never_replaced(self):
        file = self.root / "review.json"
        file.write_text('{"approved":true}', encoding="utf-8")
        initial = file.read_bytes()
        with self.assertRaisesRegex(ValueError, "禁止覆盖"):
            write_new_report(file, {"status": "suggestions_only"})
        self.assertEqual(file.read_bytes(), initial)

    def test_formal_names_rejected_even_when_missing(self):
        for name in ("requirements.json", "facts.json", "outline.json",
                     "project.json", "response-trace.json", "outline-lock.json"):
            out = self.root / "new" / name
            with self.subTest(name=name), self.assertRaisesRegex(ValueError, "正式项目"):
                write_new_report(out, {"items": []})
            self.assertFalse(out.exists())

    def test_existing_original_tender_and_index_protected(self):
        before = self.source.read_bytes()
        with self.assertRaisesRegex(ValueError, "禁止覆盖"):
            write_new_report(self.source, {"items": []})
        self.assertEqual(self.source.read_bytes(), before)
        index = self.root / "tender.index.json"
        index.write_text('{"source":"original"}', encoding="utf-8")
        with self.assertRaisesRegex(ValueError, "禁止覆盖"):
            write_new_report(index, {"items": []})
        self.assertIn("original", index.read_text(encoding="utf-8"))

    def test_symlink_alias_cannot_replace_formal_file(self):
        actual = self.project / "requirements.json"
        raw = actual.read_bytes()
        alias = self.root / "aliases" / "model-report.json"
        alias.parent.mkdir()
        try:
            alias.symlink_to(actual)
        except (OSError, NotImplementedError):
            self.skipTest("symlinks not available on this filesystem")
        with self.assertRaisesRegex(ValueError, "禁止覆盖"):
            write_new_report(alias, {"items": []})
        self.assertEqual(actual.read_bytes(), raw)

    def test_race_to_output_is_exclusive(self):
        import biaoshu.review_transaction as txn
        destination = self.root / "future-report.json"
        link = txn.os.link
        def other_process_wins(src, dst):
            Path(dst).write_text("created by another writer", encoding="utf-8")
            return link(src, dst)
        with patch.object(txn.os, "link", side_effect=other_process_wins):
            with self.assertRaisesRegex(ValueError, "禁止覆盖"):
                write_new_report(destination, {"items": []})
        self.assertEqual(destination.read_text(encoding="utf-8"),
                         "created by another writer")

    def test_successful_new_report_only_once(self):
        path = self.root / "reports" / "nested" / "suggestions.json"
        write_new_report(path, {"items": [1]})
        self.assertEqual(json.loads(path.read_text(encoding="utf-8"))["items"], [1])
        with self.assertRaisesRegex(ValueError, "禁止覆盖"):
            write_new_report(path, {"items": [2]})

    def test_invalid_serialization_leaves_no_artifact(self):
        path = self.root / "invalid.json"
        with self.assertRaises(TypeError):
            write_new_report(path, {"invalid": {1, 2}})
        self.assertFalse(path.exists())

    def cli(self, args):
        with contextlib.redirect_stdout(io.StringIO()), \
                contextlib.redirect_stderr(io.StringIO()):
            return main(args)

    def test_analyze_ai_refuses_to_overwrite_project_requirements(self):
        original = (self.project / "requirements.json").read_bytes()
        with patch("biaoshu.cli.analyze_tender", return_value={
                "candidates": [], "statistics": {"selected_blocks": 1}}):
            result = self.cli([
                "analyze-ai", "--index", str(self.root / "fake.index.json"),
                "--source-dir", str(self.sources), "--model", "local-fake",
                "--output", str(self.project / "requirements.json"),
            ])
        self.assertNotEqual(result, 0)
        self.assertEqual((self.project / "requirements.json").read_bytes(), original)

    def test_analyze_ai_refuses_to_overwrite_original_tender(self):
        original = self.source.read_bytes()
        with patch("biaoshu.cli.analyze_tender", return_value={
                "candidates": [], "statistics": {"selected_blocks": 1}}):
            result = self.cli([
                "analyze-ai", "--index", str(self.root / "fake.index.json"),
                "--source-dir", str(self.sources), "--model", "local-fake",
                "--output", str(self.source),
            ])
        self.assertNotEqual(result, 0)
        self.assertEqual(self.source.read_bytes(), original)

    def test_semantic_report_cannot_overwrite_trace(self):
        path = self.project / "reports" / "response-trace.json"
        path.write_text("existing human approvals", encoding="utf-8")
        with patch("biaoshu.cli.review_responses", return_value={
                "statistics": {"examined_links": 1, "potential_issues": 0}}):
            result = self.cli([
                "semantic-review", str(self.project),
                "--index", str(self.root / "fake.index.json"),
                "--source-dir", str(self.sources), "--model", "local-fake",
                "--output", str(path),
            ])
        self.assertNotEqual(result, 0)
        self.assertEqual(path.read_text(encoding="utf-8"),
                         "existing human approvals")

    def test_model_transport_failure_does_not_create_ai_report(self):
        target = self.root / "incomplete.json"
        with patch("biaoshu.cli.analyze_tender", side_effect=ValueError("finish_reason length")):
            result = self.cli([
                "analyze-ai", "--index", str(self.root / "fake.index.json"),
                "--source-dir", str(self.sources), "--model", "local-fake",
                "--output", str(target),
            ])
        self.assertNotEqual(result, 0)
        self.assertFalse(target.exists())


if __name__ == "__main__":
    unittest.main()
