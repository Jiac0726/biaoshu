"""Loopback-only browser workbench for the existing, human-gated bid-writing CLI.

Launch with: python -m biaoshu.webapp
No network listener, remote model permission, or autonomous approval is enabled.
"""
from __future__ import annotations

import argparse
import json
import os
import re
import secrets
import subprocess
import sys
import threading
import urllib.parse
import webbrowser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from importlib.resources import files
from pathlib import Path

from .core import initialize, load_project, read_json, write_json
from .review_import import ACKNOWLEDGEMENT
from .section_writer import CONFIRM
from .response_trace import audit_trace

PROJECT_RE = re.compile(r"^p-[a-f0-9]{12}$")
SUPPORTED = {".pdf", ".docx", ".txt", ".md"}
UPLOAD_LIMIT = 40 * 1024 * 1024
JSON_LIMIT = 2 * 1024 * 1024
MAX_SOURCES = 15


class WebError(Exception):
    def __init__(self, message: str, status: int = 400):
        super().__init__(message)
        self.status = status


class Workspace:
    """Single-user local workspace; never operates outside the configured root."""

    def __init__(self, root: Path):
        self.root = root.expanduser().resolve()
        self.root.mkdir(parents=True, exist_ok=True)
        self.lock = threading.RLock()

    def _project(self, project_id: str) -> Path:
        if not PROJECT_RE.fullmatch(project_id):
            raise WebError("无效的项目编号", 404)
        path = (self.root / project_id).resolve()
        if not path.is_relative_to(self.root) or not (path / "project.json").is_file():
            raise WebError("项目不存在", 404)
        return path

    def projects(self) -> list[dict]:
        result = []
        for item in sorted(self.root.glob("p-*"), reverse=True):
            if not item.is_dir() or item.is_symlink() or not PROJECT_RE.fullmatch(item.name):
                continue
            try:
                data = read_json(item / "project.json")
                result.append({"id": item.name, "name": str(data.get("project_name") or "未命名项目")})
            except (OSError, ValueError, AttributeError):
                continue
        return result

    def create(self, name: object) -> dict:
        if not isinstance(name, str) or not 1 <= len(name.strip()) <= 100:
            raise WebError("项目名称应为 1–100 个字符")
        for _ in range(4):
            project_id = "p-" + secrets.token_hex(6)
            root = self.root / project_id
            try:
                root.mkdir(exist_ok=False)
                break
            except FileExistsError:
                pass
        else:
            raise WebError("无法创建不重复的项目编号", 500)
        initialize(root)
        details = read_json(root / "project.json")
        details["project_name"] = name.strip()
        write_json(root / "project.json", details)
        (root / "sources").mkdir(exist_ok=True)
        (root / "output").mkdir(exist_ok=True)
        return {"id": project_id, "name": name.strip()}

    @staticmethod
    def _metadata(root: Path) -> dict:
        target = root / "web-meta.json"
        if not target.exists():
            return {}
        payload = read_json(target)
        if not isinstance(payload, dict):
            raise WebError("项目界面状态文件无效")
        return payload

    @staticmethod
    def _save_meta(root: Path, metadata: dict) -> None:
        write_json(root / "web-meta.json", metadata)

    @staticmethod
    def _selected_report(root: Path, metadata: dict, key: str) -> Path:
        name = metadata.get(key)
        if not isinstance(name, str) or not re.fullmatch(r"[a-zA-Z0-9_.-]+\.json", name):
            raise WebError("请先完成上一步并生成审核文件")
        result = root / "reports" / name
        if not result.is_file() or result.is_symlink():
            raise WebError("对应的审核文件丢失，请重新执行上一步")
        return result

    @staticmethod
    def _new_report(root: Path, prefix: str) -> Path:
        if not re.fullmatch(r"[a-z-]+", prefix):
            raise WebError("报告类型不正确")
        dest = root / "reports" / (prefix + "-" + secrets.token_hex(7) + ".json")
        dest.parent.mkdir(exist_ok=True)
        return dest

    @staticmethod
    def _source_paths(root: Path) -> tuple[Path, list[Path]]:
        source_dir = root / "sources"
        indexes = sorted((root / "reports" / "extracted").glob("*.index.json"))
        indexes = [p for p in indexes if p.is_file() and not p.is_symlink()]
        if not indexes:
            raise WebError("请先上传并解析至少一份招标文件")
        return source_dir, indexes

    @staticmethod
    def _run(*args: str, codes: tuple[int, ...] = (0,)) -> dict:
        cmd = [sys.executable, "-m", "biaoshu", *map(str, args)]
        env = os.environ.copy()
        env["PYTHONIOENCODING"] = "utf-8"
        try:
            process = subprocess.run(cmd, capture_output=True, text=True,
                                     encoding="utf-8", errors="replace", env=env,
                                     timeout=1200, check=False)
        except subprocess.TimeoutExpired as exc:
            raise WebError("任务超过 20 分钟，已停止执行。请检查章节恢复日志。") from exc
        output = ((process.stdout or "") + "\n" + (process.stderr or "")).strip()
        if process.returncode not in codes:
            raise WebError(output[-2600:] or ("工具异常退出：" + str(process.returncode)))
        return {"ok": process.returncode == 0, "message": output[-3600:]}

    def upload(self, project_id: str, filename: str, content: bytes) -> dict:
        with self.lock:
            root = self._project(project_id)
            if not isinstance(filename, str) or len(filename) > 180:
                raise WebError("文件名无效")
            suffix = Path(filename).suffix.lower()
            if suffix not in SUPPORTED:
                raise WebError("仅支持 PDF、Word DOCX、TXT 和 Markdown")
            source_dir = root / "sources"
            if len(list(source_dir.iterdir())) >= MAX_SOURCES:
                raise WebError("单项目最多上传 15 个文件")
            if not content or len(content) > UPLOAD_LIMIT:
                raise WebError("文件必须非空，且不能超过 40MB")
            base = re.sub(r"[^a-zA-Z0-9\u4e00-\u9fff_.-]", "_",
                          Path(filename).name)[:110]
            stored = secrets.token_hex(4) + "-" + base
            target = source_dir / stored
            with target.open("xb") as stream:
                stream.write(content)
            return {"stored_name": stored, "size": len(content)}

    def snapshot(self, project_id: str) -> dict:
        with self.lock:
            root = self._project(project_id)
            meta = self._metadata(root)
            project = load_project(root)
            extracted_dir = root / "reports" / "extracted"
            indexed = {p.name.removesuffix(".index.json") for p in
                       extracted_dir.glob("*.index.json")} if extracted_dir.is_dir() else set()
            sources = [{"name": p.name, "bytes": p.stat().st_size,
                        "extracted": p.name in indexed}
                       for p in sorted((root / "sources").iterdir())
                       if p.is_file() and not p.is_symlink()]
            review = suggestions = outline_proposal = audit = None
            for key, variable in (("suggestions", "suggestions"),
                                  ("review", "review"), ("outline", "outline"),
                                  ("audit", "audit")):
                try:
                    record = read_json(self._selected_report(root, meta, key))
                    if variable == "suggestions":
                        suggestions = record
                    elif variable == "review":
                        review = record
                    elif variable == "outline":
                        outline_proposal = record
                    else:
                        audit = record
                except (WebError, OSError, ValueError):
                    pass
            sections = []
            for section in project["outline.json"].get("sections", []):
                if not isinstance(section, dict) or not isinstance(section.get("id"), str):
                    continue
                sid = section["id"]
                if not re.fullmatch(r"[a-zA-Z][a-zA-Z0-9_-]{0,63}", sid):
                    continue
                doc = root / "sections" / (sid + ".md")
                sidecar = root / "reports" / "section-writing" / (sid + ".json")
                status = "not_written"
                if doc.is_file():
                    status = "manual_or_scaffold"
                if sidecar.is_file():
                    try:
                        status = str(read_json(sidecar).get("status", "unknown"))
                    except (OSError, ValueError):
                        status = "invalid_checkpoint"
                sections.append({
                    "id": sid, "title": section.get("title", sid),
                    "requirement_ids": section.get("requirement_ids", []),
                    "status": status,
                    "body": doc.read_text(encoding="utf-8")[:45000] if doc.is_file() else "",
                })
            exports = [{"name": p.name, "bytes": p.stat().st_size}
                       for p in sorted((root / "output").glob("*.docx"), reverse=True)
                       if p.is_file() and not p.is_symlink()]
            return {
                "id": project_id, "project": project["project.json"],
                "sources": sources, "requirements": project["requirements.json"].get("requirements", []),
                "facts": project["facts.json"].get("facts", []),
                "outline": project["outline.json"], "sections": sections,
                "suggestions": suggestions, "review": review, "outline_proposal": outline_proposal,
                "audit": audit, "exports": exports,
                "report_selection": {k: meta.get(k) for k in ("suggestions", "review", "outline")},
            }

    def action(self, project_id: str, payload: dict) -> dict:
        with self.lock:
            root = self._project(project_id)
            action = payload.get("action")
            meta = self._metadata(root)
            sources = root / "sources"
            result: dict
            if action == "extract":
                name = payload.get("source")
                if not isinstance(name, str) or name not in [
                        p.name for p in sources.iterdir() if p.is_file() and not p.is_symlink()]:
                    raise WebError("请选择项目中已经上传的招标原件")
                target = root / "reports" / "extracted" / (name + ".md")
                if target.exists() or target.with_suffix(".index.json").exists():
                    raise WebError("该文件已经解析。修改原件时请新上传一个版本")
                result = self._run("extract", sources / name, "--output", target)
            elif action in {"score", "analyze"}:
                source_dir, indexes = self._source_paths(root)
                dest = self._new_report(root, "score" if action == "score" else "ai-suggestions")
                if action == "score":
                    args = ["score-candidates"]
                else:
                    args = ["analyze-ai"]
                for index in indexes:
                    args.extend(["--index", str(index)])
                args.extend(["--source-dir", str(source_dir)])
                if action == "analyze":
                    args.extend(self._model_args(payload))
                args.extend(["--output", str(dest)])
                result = self._run(*args)
                meta["suggestions"] = dest.name
                meta.pop("review", None)
                meta.pop("outline", None)
            elif action == "review-init":
                suggestions = self._selected_report(root, meta, "suggestions")
                dest = self._new_report(root, "review")
                result = self._run("review-init", "--suggestions", suggestions, "--output", dest)
                meta["review"] = dest.name
            elif action == "review-save":
                review_path = self._selected_report(root, meta, "review")
                review = read_json(review_path)
                choices = payload.get("decisions")
                ambiguous = payload.get("ambiguous_decisions", {})
                if not isinstance(choices, dict) or not isinstance(ambiguous, dict):
                    raise WebError("审核决定格式无效")
                expected = {r["id"] for r in review.get("decisions", [])}
                if set(choices) != expected or any(v not in ("accept", "reject", "pending")
                                                   for v in choices.values()):
                    raise WebError("审核决定必须逐项填写，且不能增删候选项")
                expected_ambiguous = {r["id"] for r in review.get("ambiguous_decisions", [])}
                if set(ambiguous) != expected_ambiguous:
                    raise WebError("复杂评分事项必须逐项审核")
                new_ambiguous = []
                for aid, row in ambiguous.items():
                    if not isinstance(row, dict) or row.get("decision") not in (
                            "pending", "not_applicable", "manually_registered"):
                        raise WebError("复杂评分的决定必须为 pending/not_applicable/manually_registered")
                    reason = row.get("reason", "")
                    if not isinstance(reason, str) or len(reason) > 1500:
                        raise WebError("复杂评分备注无效")
                    new_ambiguous.append({"id": aid, "decision": row["decision"], "reason": reason})
                review["decisions"] = [{"id": rid, "decision": choices[rid]} for rid in sorted(expected)]
                review["ambiguous_decisions"] = new_ambiguous if expected_ambiguous else review.get("ambiguous_decisions", [])
                review["acknowledgement"] = ACKNOWLEDGEMENT if payload.get("confirmed") is True else ""
                write_json(review_path, review)
                result = {"ok": True, "message": "审核决定已保存。只有本人确实逐项核对原文才能勾选确认。"}
            elif action in {"review-preview", "review-apply"}:
                suggestions = self._selected_report(root, meta, "suggestions")
                review = self._selected_report(root, meta, "review")
                source_dir, indexes = self._source_paths(root)
                args = ["review-import", str(root), "--suggestions", str(suggestions),
                        "--review", str(review)]
                for path in indexes:
                    args.extend(["--index", str(path)])
                args.extend(["--source-dir", str(source_dir)])
                if action == "review-apply":
                    if payload.get("confirmed") is not True:
                        raise WebError("正式登记需求须人工二次确认")
                    args.append("--apply")
                result = self._run(*args, codes=(0, 1))
            elif action == "outline-init":
                dest = self._new_report(root, "outline")
                result = self._run("outline-init", root, "--output", dest)
                meta["outline"] = dest.name
            elif action == "outline-save":
                path = self._selected_report(root, meta, "outline")
                proposal = read_json(path)
                roots = payload.get("roots")
                if not isinstance(roots, list) or len(json.dumps(roots, ensure_ascii=False)) > 50000:
                    raise WebError("目录 JSON 应为根节点数组且不超过 50KB")
                proposal["roots"] = roots
                write_json(path, proposal)
                result = {"ok": True, "message": "目录候选已保存；应用前请先预览"}
            elif action in {"outline-preview", "outline-apply"}:
                path = self._selected_report(root, meta, "outline")
                args = ["outline-plan", str(root), "--proposal", str(path)]
                if action == "outline-apply":
                    if payload.get("confirmed") is not True:
                        raise WebError("应用目录需要操作员确认")
                    args.append("--apply")
                result = self._run(*args)
            elif action == "outline-lock":
                if payload.get("confirmed") is not True:
                    raise WebError("锁定一级目录需要操作员确认")
                result = self._run("outline-lock", root, "--confirm")
            elif action == "allocate":
                total = payload.get("total")
                if type(total) is not int or not 100 <= total <= 200000:
                    raise WebError("正文目标字数须在 100–200000 之间")
                result = self._run("allocate", root, "--total", str(total))
            elif action == "scaffold":
                result = self._run("scaffold", root)
            elif action == "write":
                source_dir, indexes = self._source_paths(root)
                args = ["write-sections", str(root)]
                sid = payload.get("section")
                if sid:
                    allowed = {s.get("id") for s in load_project(root)["outline.json"]["sections"]}
                    if sid not in allowed:
                        raise WebError("不存在的章节 ID")
                    args.extend(["--section", sid])
                for index in indexes:
                    args.extend(["--index", str(index)])
                args.extend(["--source-dir", str(source_dir), *self._model_args(payload)])
                result = self._run(*args)
            elif action == "approve":
                sid = payload.get("section")
                allowed = {s.get("id") for s in load_project(root)["outline.json"]["sections"]}
                if not isinstance(sid, str) or sid not in allowed:
                    raise WebError("章节不存在")
                if payload.get("confirmed") is not True:
                    raise WebError("必须本人确认已审查该章节正文及承诺")
                result = self._run("approve-section", root, "--section", sid,
                                   "--acknowledgement", CONFIRM)
            elif action == "check":
                source_dir, indexes = self._source_paths(root)
                args = ["check", str(root)]
                for index in indexes:
                    args.extend(["--index", str(index)])
                args.extend(["--source-dir", str(source_dir)])
                result = self._run(*args, codes=(0, 1))
            elif action in {"audit", "consistency"}:
                dest = self._new_report(root, action)
                if action == "audit":
                    source_dir, indexes = self._source_paths(root)
                    args = ["audit", str(root)]
                    for index in indexes:
                        args.extend(["--index", str(index)])
                    args.extend(["--source-dir", str(source_dir)])
                else:
                    args = ["consistency-audit", str(root)]
                args.extend(["--output", str(dest)])
                result = self._run(*args, codes=(0, 1))
                meta["audit"] = dest.name
            elif action == "trace-init":
                result = self._run("trace-init", root)
            elif action == "trace-audit":
                result = self._run("trace-audit", root, codes=(0, 1))
            elif action == "semantic-review":
                source_dir, indexes = self._source_paths(root)
                dest = self._new_report(root, "semantic-review")
                args = ["semantic-review", str(root)]
                for index in indexes:
                    args.extend(["--index", str(index)])
                args.extend(["--source-dir", str(source_dir)])
                args.extend(self._model_args(payload))
                args.extend(["--output", str(dest)])
                result = self._run(*args)
                meta["semantic"] = dest.name
            elif action in {"draft-export", "final-export"}:
                output = root / "output" / (
                    ("draft" if action == "draft-export" else "technical-bid")
                    + "-" + secrets.token_hex(5) + ".docx")
                args = ["export", str(root), "--output", str(output)]
                if action == "draft-export":
                    args.append("--draft")
                else:
                    source_dir, indexes = self._source_paths(root)
                    for index in indexes:
                        args.extend(["--index", str(index)])
                    args.extend(["--source-dir", str(source_dir)])
                result = self._run(*args)
                result["download"] = output.name
            else:
                raise WebError("未知操作")
            self._save_meta(root, meta)
            return result

    @staticmethod
    def _model_args(payload: dict) -> list[str]:
        model = payload.get("model")
        if not isinstance(model, str) or not 1 <= len(model.strip()) <= 120:
            raise WebError("请填写本机已安装的模型名称")
        endpoint = payload.get("endpoint") or "http://127.0.0.1:11434/v1"
        if not isinstance(endpoint, str) or len(endpoint) > 250:
            raise WebError("本地模型地址无效")
        # Native model client enforces loopback-only without --allow-remote.
        return ["--model", model.strip(), "--endpoint", endpoint]

    def export_bytes(self, project_id: str, name: str) -> bytes:
        with self.lock:
            root = self._project(project_id)
            if not re.fullmatch(r"[a-zA-Z0-9_.-]+\.docx", name):
                raise WebError("无效的导出文件名", 404)
            target = root / "output" / name
            if not target.is_file() or target.is_symlink():
                raise WebError("Word 文件不存在", 404)
            return target.read_bytes()


def make_server(workspace: Workspace, port: int = 8765) -> ThreadingHTTPServer:
    """Bind to 127.0.0.1 only. Port 0 is available for automated tests."""
    token = secrets.token_urlsafe(32)

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, format, *args):
            # Don't log uploaded content, model prompts, secrets, or text.
            pass

        def _send(self, data: bytes, status: int, mime: str, download: str | None = None):
            self.send_response(status)
            self.send_header("Content-Type", mime)
            self.send_header("Content-Length", str(len(data)))
            self.send_header("Cache-Control", "no-store")
            self.send_header("X-Content-Type-Options", "nosniff")
            self.send_header("X-Frame-Options", "DENY")
            self.send_header("Referrer-Policy", "no-referrer")
            self.send_header("Content-Security-Policy",
                             "default-src 'none'; script-src 'self'; style-src 'self'; "
                             "connect-src 'self'; base-uri 'none'; frame-ancestors 'none'")
            if download:
                self.send_header("Content-Disposition", "attachment; filename*=UTF-8''"
                                 + urllib.parse.quote(download))
            self.end_headers()
            self.wfile.write(data)

        def _json(self, data, status: int = 200):
            raw = json.dumps(data, ensure_ascii=False).encode("utf-8")
            self._send(raw, status, "application/json; charset=utf-8")

        def _check_host(self):
            host = self.headers.get("Host", "").split(":")[0].lower()
            if host not in ("127.0.0.1", "localhost"):
                raise WebError("仅允许本机访问", 403)

        def _auth_write(self):
            origin = self.headers.get("Origin")
            valid = {f"http://127.0.0.1:{self.server.server_port}",
                     f"http://localhost:{self.server.server_port}"}
            if origin and origin not in valid:
                raise WebError("拒绝跨站请求", 403)
            if not secrets.compare_digest(self.headers.get("X-Biaoshu-Token", ""), token):
                raise WebError("请求未通过本地会话校验", 403)

        def _read_body(self, size_limit: int) -> bytes:
            if self.headers.get("Transfer-Encoding"):
                raise WebError("不支持分块上传", 400)
            try:
                length = int(self.headers.get("Content-Length", "-1"))
            except ValueError:
                raise WebError("请求长度不合法")
            if length < 0 or length > size_limit:
                raise WebError("请求大小超限", 413)
            return self.rfile.read(length)

        def _params(self):
            parsed = urllib.parse.urlsplit(self.path)
            args = urllib.parse.parse_qs(parsed.query)
            return parsed.path, {k: v[0] for k, v in args.items() if v}

        def _serve(self, write: bool):
            try:
                self._check_host()
                path, query = self._params()
                if write:
                    self._auth_write()
                    if path == "/api/upload":
                        raw = self._read_body(UPLOAD_LIMIT)
                        result = workspace.upload(query.get("id", ""),
                                                  query.get("filename", ""), raw)
                    else:
                        body = self._read_body(JSON_LIMIT)
                        try:
                            data = json.loads(body)
                        except (ValueError, UnicodeDecodeError) as exc:
                            raise WebError("请求必须是 UTF-8 JSON 对象") from exc
                        if not isinstance(data, dict):
                            raise WebError("请求格式应为 JSON 对象")
                        if path == "/api/project":
                            result = workspace.create(data.get("name"))
                        elif path == "/api/action":
                            result = workspace.action(query.get("id", ""), data)
                        else:
                            raise WebError("接口不存在", 404)
                    self._json(result)
                elif path == "/":
                    data = files("biaoshu").joinpath("webui/index.html").read_bytes()
                    self._send(data, 200, "text/html; charset=utf-8")
                elif path == "/app.js":
                    data = files("biaoshu").joinpath("webui/app.js").read_bytes()
                    self._send(data, 200, "text/javascript; charset=utf-8")
                elif path == "/style.css":
                    data = files("biaoshu").joinpath("webui/style.css").read_bytes()
                    self._send(data, 200, "text/css; charset=utf-8")
                elif path == "/api/bootstrap":
                    self._json({"token": token, "projects": workspace.projects()})
                elif path == "/api/project":
                    self._json(workspace.snapshot(query.get("id", "")))
                elif path == "/api/export":
                    name = query.get("name", "")
                    self._send(workspace.export_bytes(query.get("id", ""), name),
                               200, "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
                               download=name)
                else:
                    raise WebError("页面不存在", 404)
            except WebError as exc:
                self._json({"error": str(exc)}, exc.status)
            except (OSError, ValueError, KeyError, TypeError) as exc:
                self._json({"error": str(exc)}, 400)

        def do_GET(self):
            self._serve(False)

        def do_POST(self):
            self._serve(True)

    return ThreadingHTTPServer(("127.0.0.1", port), Handler)


def main(argv=None):
    parser = argparse.ArgumentParser(description="Biaoshu 本地标书 Web 工作台")
    parser.add_argument("--port", type=int, default=8765)
    parser.add_argument("--workspace", type=Path, default=Path("workspaces") / "web")
    parser.add_argument("--no-browser", action="store_true")
    args = parser.parse_args(argv)
    if not 0 <= args.port <= 65535:
        parser.error("--port 必须是 0–65535")
    server = make_server(Workspace(args.workspace), args.port)
    url = f"http://127.0.0.1:{server.server_port}/"
    print("标书工作台：" + url, flush=True)
    print("仅监听本机；客户文件保留在指定工作区；按 Ctrl+C 退出。", flush=True)
    if not args.no_browser:
        webbrowser.open(url)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()


if __name__ == "__main__":
    main()
