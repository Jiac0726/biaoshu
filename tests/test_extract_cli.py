import json
import tempfile
import unittest
from pathlib import Path

from biaoshu.cli import main


class ExtractCliTests(unittest.TestCase):
    def test_extract_writes_markdown_and_json_sidecar(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "tender.txt"
            source.write_text("技术要求\n\n实施计划\n", encoding="utf-8")
            markdown = root / "out" / "extracted.md"
            sidecar = root / "out" / "extracted.json"
            code = main(["extract", str(source), "--output", str(markdown),
                         "--json-output", str(sidecar)])
            self.assertEqual(code, 0)
            self.assertIn("第 3 行", markdown.read_text(encoding="utf-8"))
            data = json.loads(sidecar.read_text(encoding="utf-8"))
            self.assertEqual([b["text"] for b in data["blocks"]], ["技术要求", "实施计划"])
            self.assertEqual(data["source_file"], "tender.txt")


if __name__ == "__main__":
    unittest.main()
