"""Source-locked evidence verification regression tests."""
import hashlib
import json
import tempfile
import unittest
from pathlib import Path
from biaoshu.evidence import verify_evidence


class EvidenceTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.sources = self.root / "sources"
        self.sources.mkdir()
        self.project = self.root / "project"
        self.project.mkdir()
        self.source = self.sources / "tender.txt"
        self.source.write_text("技术评分：实施组织\n交付时间：30日\n", encoding="utf-8")
        self.index_path = self.root / "source.index.json"
        self.index = {"schema_version": 1, "source_file": "tender.txt",
                      "sha256": hashlib.sha256(self.source.read_bytes()).hexdigest(),
                      "blocks": [{"location": "第1行", "text": "技术评分：实施组织"},
                                 {"location": "第2行", "text": "交付时间：30日"}]}
        self.requirements = {"requirements": [{"id": "R1", "evidence": {
            "file": "tender.txt", "location": "第1行", "quote": "技术评分：实施组织"}}]}
        self.facts = {"facts": [{"key": "delivery", "status": "verified", "evidence": {
            "file": "tender.txt", "location": "第2行", "quote": "交付时间：30日"}},
            {"key": "pending", "status": "pending"}]}
        self.save()

    def save(self):
        for path, obj in [(self.index_path, self.index),
                          (self.project / "requirements.json", self.requirements),
                          (self.project / "facts.json", self.facts)]:
            path.write_text(json.dumps(obj, ensure_ascii=False), encoding="utf-8")

    def report(self, indexes=None):
        return verify_evidence(self.project, indexes or [self.index_path], self.sources)

    def codes(self):
        return {e["code"] for e in self.report()["errors"]}

    def test_matching_requirement_and_fact(self):
        report = self.report()
        self.assertTrue(report["ok"], report)
        self.assertEqual(report["summary"]["matched"], 2)

    def test_wrong_quote(self):
        self.requirements["requirements"][0]["evidence"]["quote"] = "交付时间：30日"
        self.save()
        self.assertIn("quote_mismatch", self.codes())

    def test_wrong_location(self):
        self.requirements["requirements"][0]["evidence"]["location"] = "第99行"
        self.save()
        self.assertIn("location_not_found", self.codes())

    def test_modified_source(self):
        self.source.write_text("变更后的原文", encoding="utf-8")
        self.assertIn("source_changed", self.codes())

    def test_missing_source(self):
        self.source.unlink()
        self.assertIn("source_missing", self.codes())

    def test_malformed_index(self):
        self.index["blocks"] = [{"location": "第1行", "text": 42}]
        self.save()
        self.assertIn("invalid_index", self.codes())

    def test_duplicate_index(self):
        self.assertIn("duplicate_source",
                      {e["code"] for e in self.report([self.index_path, self.index_path])["errors"]})

    def test_unicode_whitespace(self):
        self.facts["facts"][0]["evidence"]["quote"] = "交付时间：３０ 日"
        self.save()
        self.assertTrue(self.report()["ok"])


if __name__ == "__main__":
    unittest.main()
