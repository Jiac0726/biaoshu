"""No-network browser workbench tests using the actual existing CLI and a loopback server."""
import json
import tempfile
import threading
import unittest
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

from biaoshu.webapp import Workspace, WebError, make_server
from biaoshu.core import read_json, write_json
from biaoshu.response_trace import trace_path


class WebWorkspaceTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.workspace = Workspace(Path(self.temp.name))
        self.project = self.workspace.create("样例技术标项目")["id"]

    def test_project_is_created_inside_private_workspace(self):
        data = self.workspace.snapshot(self.project)
        self.assertEqual(data["project"]["project_name"], "样例技术标项目")
        self.assertEqual(data["sections"], [])
        self.assertEqual(self.workspace.projects()[0]["id"], self.project)
        with self.assertRaises(WebError):
            self.workspace.snapshot("../outside")
        with self.assertRaises(WebError):
            self.workspace.export_bytes(self.project, "../secret.docx")

    def test_upload_validation_and_no_arbitrary_paths(self):
        with self.assertRaisesRegex(WebError, "仅支持"):
            self.workspace.upload(self.project, "evil.exe", b"hello")
        with self.assertRaises(WebError):
            self.workspace.upload(self.project, "tender.pdf", b"")
        saved = self.workspace.upload(self.project, "../../outside.txt", b"test")
        self.assertNotIn("/", saved["stored_name"])
        self.assertNotIn("\\", saved["stored_name"])
        self.assertTrue((self.workspace.root / self.project / "sources" / saved["stored_name"]).is_file())

    def test_upload_extract_score_and_review_without_model(self):
        file = self.workspace.upload(
            self.project, "demo.txt",
            "技术评审评分标准\n实施组织方案评分10分\n质量保障措施评分5分\n".encode("utf-8"))
        result = self.workspace.action(self.project, {"action": "extract", "source": file["stored_name"]})
        self.assertTrue(result["ok"], result)
        data = self.workspace.snapshot(self.project)
        self.assertTrue(data["sources"][0]["extracted"])
        self.assertEqual(len(list((self.workspace.root / self.project / "reports" / "extracted").glob("*.index.json"))), 1)
        result = self.workspace.action(self.project, {"action": "score"})
        self.assertTrue(result["ok"], result)
        data = self.workspace.snapshot(self.project)
        self.assertEqual(data["suggestions"]["status"], "suggestions_only")
        result = self.workspace.action(self.project, {"action": "review-init"})
        self.assertTrue(result["ok"], result)
        review = self.workspace.snapshot(self.project)["review"]
        self.assertTrue(all(x["decision"] == "pending" for x in review["decisions"]))
        with self.assertRaises(WebError):
            self.workspace.action(self.project, {"action": "review-save",
                                                "decisions": {"INJECTED": "accept"},
                                                "ambiguous_decisions": {}})
        self.workspace.action(self.project, {"action": "review-save",
            "decisions": {x["id"]: "reject" for x in review["decisions"]},
            "ambiguous_decisions": {x["id"]: {"decision": "not_applicable", "reason": "已核对不纳入技术响应"}
                                    for x in review.get("ambiguous_decisions", [])},
            "confirmed": False})
        self.assertEqual(self.workspace.snapshot(self.project)["review"]["acknowledgement"], "")

    def test_manual_trace_update_preserves_existing_review_fingerprint(self):
        root = self.workspace.root / self.project
        target = trace_path(root)
        initial = {"schema_version": 1, "mapping_sha256": "original-mapping",
                   "acknowledgement": "", "items": [
                       {"requirement_id": "R1", "section_id": "S1",
                        "section_sha256": "original-body-hash",
                        "line": None, "quote": "", "decision": "pending"}]}
        write_json(target, initial)
        action = {"action": "trace-save", "confirmed": True, "items": [
            {"requirement_id": "R1", "section_id": "S1",
             "line": 3, "quote": "这里是经过审稿人亲自核对的技术响应正文原句",
             "decision": "confirmed"}]}
        result = self.workspace.action(self.project, action)
        self.assertTrue(result["ok"])
        updated = read_json(target)
        self.assertEqual(updated["mapping_sha256"], "original-mapping")
        self.assertEqual(updated["items"][0]["section_sha256"], "original-body-hash")
        self.assertEqual(updated["items"][0]["line"], 3)
        self.assertTrue(updated["acknowledgement"])
        action["items"][0]["line"] = True
        with self.assertRaisesRegex(WebError, "行号"):
            self.workspace.action(self.project, action)
    def test_human_approval_requires_explicit_confirmation(self):
        root = self.workspace.root / self.project
        write_json(root / "outline.json", {"sections": [
            {"id": "S1", "title": "示例章节", "requirement_ids": ["R1"], "weight": 1.0, "target_words": 0}
        ]})
        with self.assertRaisesRegex(WebError, "本人"):
            self.workspace.action(self.project, {"action": "approve", "section": "S1"})
        with self.assertRaisesRegex(WebError, "人工二次确认"):
            self.workspace.action(self.project, {"action": "review-apply"})


class WebHttpSecurityTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.workspace = Workspace(Path(self.temp.name))
        self.server = make_server(self.workspace, port=0)
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        self.addCleanup(self.server.server_close)
        self.addCleanup(self.server.shutdown)
        self.base = "http://127.0.0.1:" + str(self.server.server_port)

    def http(self, path, body=None, headers=None):
        payload = None if body is None else json.dumps(body).encode("utf-8")
        req = urllib.request.Request(self.base + path, data=payload, headers=headers or {})
        return urllib.request.urlopen(req, timeout=6)

    def test_ui_static_files_are_served_from_packaged_assets(self):
        with self.http("/") as resp:
            self.assertIn("标书智能工作台", resp.read().decode("utf-8"))
        with self.http("/app.js") as resp:
            self.assertIn("review-apply", resp.read().decode("utf-8"))
        with self.http("/style.css") as resp:
            self.assertIn(".sidebar", resp.read().decode("utf-8"))

    def test_cross_site_and_missing_token_cannot_post(self):
        with self.assertRaises(urllib.error.HTTPError) as cm:
            self.http("/api/project", {"name":"attack"})
        self.assertEqual(cm.exception.code, 403)
        with self.http("/api/bootstrap") as resp:
            token = json.load(resp)["token"]
        with self.assertRaises(urllib.error.HTTPError) as cm:
            self.http("/api/project", {"name":"attack"}, {
                "X-Biaoshu-Token":token, "Origin":"https://evil.example"})
        self.assertEqual(cm.exception.code, 403)
        with self.http("/api/project", {"name":"safe"}, {"X-Biaoshu-Token":token}) as resp:
            created = json.load(resp)
        self.assertTrue(created["id"].startswith("p-"))

    def test_bad_host_and_id_denied(self):
        with self.assertRaises(urllib.error.HTTPError) as cm:
            self.http("/api/bootstrap", headers={"Host":"evil.example"})
        self.assertEqual(cm.exception.code, 403)
        with self.assertRaises(urllib.error.HTTPError) as cm:
            self.http("/api/project?id=../../etc")
        self.assertEqual(cm.exception.code, 404)


if __name__ == "__main__":
    unittest.main()
