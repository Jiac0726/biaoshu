"""Hierarchy and first-level lock regression tests for a stable S# outline."""
import copy
import json
import tempfile
import unittest
from pathlib import Path

from biaoshu.cli import export_docx, main
from biaoshu.core import initialize, inspect, read_json, write_json, scaffold
from biaoshu.outline_tree import (outline_template, outline_plan, lock_outline,
                                  validate_roots, validate_outline_state, walk_outline)


def _initial_state(root):
    initialize(root)
    reqs, sections = [], []
    for n, title in enumerate(("实施组织", "进度保障", "质量保障"), 1):
        reqs.append({"id": f"R{n}", "title": title, "score": 5,
                     "evidence": {"file": "tender.txt", "location": f"第{n}行",
                                  "quote": title},
                     "response_sections": [f"S{n}"]})
        sections.append({"id": f"S{n}", "title": title, "requirement_ids": [f"R{n}"],
                         "weight": 1.0, "target_words": 0})
    write_json(root / "requirements.json", {"requirements": reqs})
    write_json(root / "outline.json", {"sections": sections})


class OutlineHierarchyTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        _initial_state(self.root)
        self.proposal = self.root / "reports" / "proposed.json"
        write_json(self.proposal, outline_template(self.root))

    def proposed(self, roots):
        p = read_json(self.proposal)
        p["roots"] = roots
        write_json(self.proposal, p)
        return p

    @staticmethod
    def grouped():
        return [
            {"id": "G1", "title": "项目实施与进度", "children": [
                {"section_id": "S1"}, {"section_id": "S2"}]},
            {"section_id": "S3"},
        ]

    def test_initial_template_uses_existing_ids_without_artificial_group(self):
        roots = read_json(self.proposal)["roots"]
        self.assertEqual(roots, [{"section_id": "S1"}, {"section_id": "S2"}, {"section_id": "S3"}])
        self.assertTrue(inspect(self.root)["ok"])

    def test_preview_has_no_side_effect_and_apply_preserves_sections(self):
        self.proposed(self.grouped())
        original = (self.root / "outline.json").read_bytes()
        report = outline_plan(self.root, self.proposal)
        self.assertEqual(report["status"], "preview")
        self.assertEqual((self.root / "outline.json").read_bytes(), original)
        done = outline_plan(self.root, self.proposal, apply=True)
        self.assertEqual(done["status"], "applied")
        outline = read_json(self.root / "outline.json")
        self.assertEqual(outline["sections"], json.loads(original)["sections"])
        self.assertEqual(len(list(walk_outline(outline))), 4)
        self.assertEqual([x[0] for x in walk_outline(outline)], [1, 2, 2, 1])
        self.assertTrue(Path(done["backup_path"]).is_file())

    def test_invalid_duplicate_and_missing_sections_blocked(self):
        roots = self.grouped()
        roots[1] = {"section_id": "S1"}
        self.proposed(roots)
        with self.assertRaisesRegex(ValueError, "重复引用章节"):
            outline_plan(self.root, self.proposal, apply=True)
        self.assertNotIn("roots", read_json(self.root / "outline.json"))

    def test_unknown_section_and_redundant_single_child_group_blocked(self):
        roots = self.grouped()
        roots[1] = {"section_id": "S404"}
        self.proposed(roots)
        with self.assertRaisesRegex(ValueError, "不存在的章节"):
            outline_plan(self.root, self.proposal)
        self.proposed([{"id": "G1", "title": "不必要的一级", "children": [{"section_id": "S1"}]},
                       {"section_id": "S2"}, {"section_id": "S3"}])
        with self.assertRaisesRegex(ValueError, "至少有两个子节点"):
            outline_plan(self.root, self.proposal)

    def test_lock_needs_explicit_confirmation_and_preserves_root_names(self):
        self.proposed(self.grouped())
        outline_plan(self.root, self.proposal, apply=True)
        with self.assertRaisesRegex(ValueError, "confirm"):
            lock_outline(self.root)
        r = lock_outline(self.root, confirm=True)
        self.assertEqual(r["status"], "locked")
        self.assertEqual(lock_outline(self.root, confirm=True)["status"], "already_locked")
        outline = read_json(self.root / "outline.json")
        outline["roots"][0]["title"] = "被 AI 改过的一级目录"
        write_json(self.root / "outline.json", outline)
        report = inspect(self.root)
        self.assertFalse(report["ok"])
        self.assertTrue(any("一级目录" in issue for issue in report["errors"]))

    def test_lock_blocks_changed_root_order_and_membership(self):
        self.proposed(self.grouped())
        outline_plan(self.root, self.proposal, apply=True)
        lock_outline(self.root, confirm=True)
        new_roots = list(reversed(self.grouped()))
        self.proposed(new_roots)
        with self.assertRaisesRegex(ValueError, "一级目录已锁定"):
            outline_plan(self.root, self.proposal, apply=True)
        swapped = [{"id": "G1", "title": "项目实施与进度", "children": [
            {"section_id": "S1"}, {"section_id": "S3"}]}, {"section_id": "S2"}]
        self.proposed(swapped)
        with self.assertRaisesRegex(ValueError, "一级目录已锁定"):
            outline_plan(self.root, self.proposal, apply=True)

    def test_lock_allows_lower_level_order_change(self):
        self.proposed(self.grouped())
        outline_plan(self.root, self.proposal, apply=True)
        lock_outline(self.root, confirm=True)
        changed = self.grouped()
        changed[0]["children"].reverse()
        self.proposed(changed)
        self.assertEqual(outline_plan(self.root, self.proposal, apply=True)["status"], "applied")
        self.assertTrue(inspect(self.root)["ok"])

    def test_check_detects_manual_missing_group_and_broken_lock(self):
        self.proposed(self.grouped())
        outline_plan(self.root, self.proposal, apply=True)
        lock_outline(self.root, confirm=True)
        outline = read_json(self.root / "outline.json")
        del outline["roots"]
        write_json(self.root / "outline.json", outline)
        self.assertFalse(inspect(self.root)["ok"])
        with self.assertRaisesRegex(ValueError, "目录"):
            export_docx(self.root, self.root / "unsafe.docx", draft=True)

    def test_suggestions_stale_after_renaming_section(self):
        outline = read_json(self.root / "outline.json")
        outline["sections"][0]["title"] = "有修改的标题"
        write_json(self.root / "outline.json", outline)
        with self.assertRaisesRegex(ValueError, "标题已经更新"):
            outline_plan(self.root, self.proposal)

    def test_cli_outline_commands_and_draft_word_hierarchy(self):
        import contextlib
        import io
        from docx import Document
        self.assertEqual(main(["outline-init", str(self.root), "--output", str(self.root / "fresh.json")]), 0)
        self.proposed(self.grouped())
        with contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(main(["outline-plan", str(self.root), "--proposal", str(self.proposal),
                                   "--apply"]), 0)
            self.assertEqual(main(["outline-lock", str(self.root), "--confirm"]), 0)
        scaffold(self.root)
        for sid in ("S1", "S2", "S3"):
            (self.root / "sections" / (sid + ".md")).write_text("# "+sid+"\n正文内容\n", encoding="utf-8")
        output = self.root / "draft.docx"
        export_docx(self.root, output, draft=True)
        doc = Document(output)
        names = [p.text for p in doc.paragraphs if p.style.name.startswith("Heading")]
        self.assertEqual(names[:4], ["项目实施与进度", "实施组织", "进度保障", "质量保障"])

    def test_legacy_flat_outline_remains_compatible(self):
        self.assertTrue(inspect(self.root)["ok"])
        items = list(walk_outline(read_json(self.root / "outline.json")))
        self.assertEqual([x[0] for x in items], [1, 1, 1])


if __name__ == "__main__":
    unittest.main()
