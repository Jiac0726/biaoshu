"""Regression: never recover a journaled chapter while its owner is alive.

Uses only fictional local bytes; no model, network, or customer material.
"""
import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from biaoshu.core import initialize
from biaoshu.section_transaction import recover, stage


class LiveJournalOwnerTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.root = Path(temp.name) / "project"
        initialize(self.root)

    def partial(self, sid, status, pid):
        doc = self.root / "sections" / (sid + ".md")
        doc.write_bytes(b"before-draft")
        checkpoint = self.root / "reports" / "section-writing" / (sid + ".json")
        checkpoint.parent.mkdir(parents=True, exist_ok=True)
        checkpoint.write_bytes(b'{"status":"pending_review"}')
        marker = stage(self.root, sid, b"after-draft", b'{"status":"approved"}',
                       status=status)
        doc.write_bytes(b"after-draft")
        lock = marker.with_name(sid + ".write.lock")
        lock.write_text(json.dumps({"pid": pid, "status": status}), encoding="utf-8")
        return doc, checkpoint, marker, lock

    def test_live_owner_blocks_journal_recovery_without_touching_bytes(self):
        for sid, status in (("S1", "writing"), ("S2", "approving")):
            with self.subTest(status=status):
                paths = self.partial(sid, status, os.getpid())
                before = [path.read_bytes() for path in paths]
                with self.assertRaisesRegex(ValueError, "仍然存活"):
                    recover(self.root, sid, confirm=True, unlock_stale=True)
                self.assertEqual([path.read_bytes() for path in paths], before)

    def test_dead_owner_allows_explicit_journal_rollback(self):
        doc, checkpoint, marker, lock = self.partial("S1", "approving", 123456789)
        with patch("biaoshu.section_transaction.os.kill", side_effect=ProcessLookupError):
            result = recover(self.root, "S1", confirm=True, unlock_stale=True)
        self.assertEqual(result["status"], "restored")
        self.assertEqual(doc.read_bytes(), b"before-draft")
        self.assertEqual(checkpoint.read_bytes(), b'{"status":"pending_review"}')
        self.assertFalse(marker.exists())
        self.assertFalse(lock.exists())

    def test_uninspectable_owner_fails_closed_and_preserves_journal(self):
        paths = self.partial("S1", "writing", 123456789)
        before = [path.read_bytes() for path in paths]
        with patch("biaoshu.section_transaction.os.kill",
                   side_effect=PermissionError("permission denied")):
            with self.assertRaisesRegex(ValueError, "无法证明"):
                recover(self.root, "S1", confirm=True, unlock_stale=True)
        self.assertEqual([path.read_bytes() for path in paths], before)


if __name__ == "__main__":
    unittest.main()
