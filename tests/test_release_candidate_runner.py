"""Offline RC report provenance and immutable record tests (no subprocess runs)."""
import contextlib
import io
import json
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import scripts.validate_release_candidate as validator


class ReleaseCandidateRunnerTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.folder = Path(self.temp.name)
        self.report = self.folder / "acceptance.json"
        self.valid_revision = {
            "sha": "a" * 40, "tracked_tree_clean": True, "status": "verified",
        }

    def fake_execute(self, args, *, cwd):
        return {"command": args[1:], "status": "passed",
                "exit_code": 0, "elapsed_seconds": 0.01}

    def test_report_preserves_exact_revision_and_no_overwrite(self):
        with patch.object(validator, "execute", side_effect=self.fake_execute), \
                patch.object(validator, "revision", return_value=self.valid_revision), \
                contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(validator.run(report_path=self.report), 0)
            original = self.report.read_bytes()
            parsed = json.loads(original)
            self.assertEqual(parsed["revision"]["sha"], "a" * 40)
            self.assertTrue(parsed["revision"]["tracked_tree_clean"])
            self.assertEqual(len(parsed["results"]), 3)
            with self.assertRaisesRegex(ValueError, "不允许覆盖"):
                validator.run(report_path=self.report)
        self.assertEqual(self.report.read_bytes(), original)

    def test_report_creation_is_exclusive_not_check_then_overwrite(self):
        # Even if exists() were stale or incorrectly indicated absence,
        # opening in exclusive mode must refuse to replace this file.
        self.report.write_text("retained acceptance record", encoding="utf-8")
        with patch.object(validator, "execute", side_effect=self.fake_execute), \
                patch.object(validator, "revision", return_value=self.valid_revision), \
                patch.object(Path, "exists", return_value=False):
            with self.assertRaisesRegex(ValueError, "不允许覆盖"):
                validator.run(report_path=self.report)
        self.assertEqual(self.report.read_text(encoding="utf-8"),
                         "retained acceptance record")

    def test_failed_first_check_cannot_be_reported_as_pass(self):
        def fail(args, *, cwd):
            return {"command": args[1:], "status": "failed", "exit_code": 2,
                    "elapsed_seconds": 0.01}
        with patch.object(validator, "execute", side_effect=fail), \
                patch.object(validator, "revision", return_value=self.valid_revision), \
                contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(validator.run(report_path=self.report), 1)
        report = json.loads(self.report.read_text(encoding="utf-8"))
        self.assertEqual(report["status"], "failed")
        self.assertEqual(len(report["results"]), 1)

    def test_revision_not_invented_without_git(self):
        with patch.object(validator.subprocess, "run", side_effect=FileNotFoundError()):
            result = validator.revision(self.folder)
        self.assertEqual(result["status"], "unverified")
        self.assertIsNone(result["sha"])

    def test_revision_uses_git_head_and_status(self):
        fake_head = SimpleNamespace(returncode=0, stdout="b" * 40 + "\n")
        fake_clean = SimpleNamespace(returncode=0, stdout="")
        with patch.object(validator.subprocess, "run",
                          side_effect=[fake_head, fake_clean]) as sp:
            report = validator.revision(self.folder)
        self.assertEqual(report["sha"], "b" * 40)
        self.assertTrue(report["tracked_tree_clean"])
        self.assertEqual(sp.call_count, 2)

    def test_uncommitted_tracked_changes_are_not_labeled_clean(self):
        fake_head = SimpleNamespace(returncode=0, stdout="f" * 40 + "\n")
        dirty = SimpleNamespace(returncode=0, stdout=" M biaoshu/core.py\n")
        with patch.object(validator.subprocess, "run",
                          side_effect=[fake_head, dirty]):
            rev = validator.revision(self.folder)
        self.assertEqual(rev["status"], "verified")
        self.assertFalse(rev["tracked_tree_clean"])


if __name__ == "__main__":
    unittest.main()
