import json
import tempfile
import unittest
from pathlib import Path

from biaoshu.core import allocate, initialize, inspect, scaffold, section_path, write_json


def populate(root):
    write_json(root / "project.json", {"project_name": "演示项目", "total_words": 400})
    write_json(root / "requirements.json", {"requirements": [
        {"id": "R1", "title": "实施组织", "score": 10,
         "evidence": {"file": "tender.pdf", "location": "第12页", "quote": "实施组织方案评分"},
         "response_sections": ["S1"]},
        {"id": "R2", "title": "质量保障", "score": 5,
         "evidence": {"file": "tender.pdf", "location": "第13页", "quote": "质量保障措施评分"},
         "response_sections": ["S2"]},
    ]})
    write_json(root / "facts.json", {"facts": [
        {"key": "duration", "value": "30日", "status": "verified",
         "evidence": {"file": "tender.pdf", "location": "第3页", "quote": "服务期限：30日"}},
    ]})
    write_json(root / "outline.json", {"sections": [
        {"id": "S1", "title": "实施组织", "requirement_ids": ["R1"], "weight": 1, "target_words": 0},
        {"id": "S2", "title": "质量保障", "requirement_ids": ["R2"], "weight": 1, "target_words": 0},
    ]})


class CoreTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        initialize(self.root)
        populate(self.root)

    def tearDown(self):
        self.temp.cleanup()

    def test_valid_structure(self):
        self.assertTrue(inspect(self.root)["ok"])

    def test_missing_evidence_is_blocker(self):
        data = json.loads((self.root / "requirements.json").read_text(encoding="utf-8"))
        data["requirements"][0].pop("evidence")
        write_json(self.root / "requirements.json", data)
        self.assertFalse(inspect(self.root)["ok"])

    def test_response_coverage_is_bidirectional(self):
        data = json.loads((self.root / "outline.json").read_text(encoding="utf-8"))
        data["sections"][0]["requirement_ids"] = []
        write_json(self.root / "outline.json", data)
        self.assertFalse(inspect(self.root)["ok"])

    def test_allocation_exact(self):
        counts = allocate(self.root, 400)
        self.assertEqual(sum(counts.values()), 400)
        self.assertGreater(counts["S1"], counts["S2"])

    def test_no_overwrite(self):
        created = scaffold(self.root)
        self.assertEqual(len(created), 2)
        first = self.root / "sections" / "S1.md"
        first.write_text("已有人工作文", encoding="utf-8")
        self.assertEqual(len(scaffold(self.root)), 0)
        self.assertEqual(first.read_text(encoding="utf-8"), "已有人工作文")

    def test_strict_requires_real_text(self):
        scaffold(self.root)
        self.assertFalse(inspect(self.root, strict=True)["ok"])
        (self.root / "sections" / "S1.md").write_text("实施组织内容" * 50, encoding="utf-8")
        (self.root / "sections" / "S2.md").write_text("质量保障内容" * 50, encoding="utf-8")
        self.assertTrue(inspect(self.root, strict=True)["ok"])

    def test_prevent_bad_path(self):
        with self.assertRaises(ValueError):
            section_path(self.root, "../leak")


if __name__ == "__main__":
    unittest.main()
