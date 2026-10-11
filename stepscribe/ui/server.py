# SPDX-License-Identifier: AGPL-3.0-only
# Copyright (C) 2026 idris sadiq
"""Local web UI: upload a STEP file, watch progress with an ETA, inspect the context pack.

Standard library only. Binds to 127.0.0.1 and runs each analysis in a separate process so a
heavy file can never freeze the page.
"""

from __future__ import annotations

import hmac
import io
import json
import math
import multiprocessing as mp
import secrets
import shutil
import tempfile
import threading
import time
import uuid
import webbrowser
import zipfile
from dataclasses import dataclass, field
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, unquote, urlparse

from stepscribe import __version__, config
from stepscribe.headless import require_interactive
from stepscribe.io.discovery import find_step_files
from stepscribe.procutil import kill_tree
from stepscribe.ui.worker import run_job, summarise_pack

INDEX = Path(__file__).with_name("index.html")
FAVICON = (
    '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 32 32">'
    '<rect width="32" height="32" rx="6" fill="#1f6feb"/>'
    '<path d="M9 22V10h8a4 4 0 010 8h-4" fill="none" stroke="#fff" stroke-width="3" '
    'stroke-linecap="round"/></svg>'
)
MIME = {
    ".png": "image/png",
    ".md": "text/plain; charset=utf-8",
    ".json": "application/json",
    ".html": "text/plain; charset=utf-8",
}
AXES = ("+X", "-X", "+Y", "-Y", "+Z", "-Z")
STEP_SUFFIXES = (".step", ".stp")
STEP_MAGIC = b"ISO-10303-21"
CSP = (
    "default-src 'self'; img-src 'self' data:; style-src 'self' 'unsafe-inline'; "
    "script-src 'self' 'unsafe-inline'; connect-src 'self'; frame-ancestors 'none'"
)
MAX_JSON_BYTES = 1 << 20
# image tags and download links cannot send headers, so these accept ?t=<token> as well
QUERY_TOKEN_PATHS = ("/files/", "/api/render", "/api/zip", "/api/pack/download")


class BadRequest(Exception):
    """A request the server refuses, with the HTTP status to answer."""

    def __init__(self, message: str, status: int = 400) -> None:
        super().__init__(message)
        self.status = status


@dataclass
class JobState:
    """What the page can poll for."""

    id: str
    name: str
    started: float = field(default_factory=time.time)
    stage: str = "queued"
    message: str = "starting"
    fraction: float = 0.0
    eta_s: float | None = None
    elapsed_s: float = 0.0
    done: bool = False
    error: str | None = None
    pack: str | None = None
    result: dict[str, Any] | None = None
    process: Any = None
    cmd_q: Any = None  # commands to the interview session in the worker
    reply_q: Any = None
    call_lock: Any = field(default_factory=threading.Lock)


class App:
    """Shared server state: work directory and jobs."""

    def __init__(self, workdir: Path, sample_dir: Path | None) -> None:
        self.workdir = workdir
        self.sample_dir = sample_dir
        self.jobs: dict[str, JobState] = {}
        self.lock = threading.Lock()
        self.token = secrets.token_urlsafe(32)
        self.max_upload_bytes = 500 * 1024 * 1024

    def samples(self) -> list[Path]:
        """Sample files in a stable order; the page refers to them by index, never by path."""
        return find_step_files(self.sample_dir) if self.sample_dir else []

    def start(self, path: Path, display_name: str, params: dict[str, Any]) -> JobState:
        job_id = uuid.uuid4().hex[:10]
        out = self.workdir / job_id / "out"
        out.mkdir(parents=True, exist_ok=True)
        state = JobState(job_id, display_name)
        ctx = mp.get_context("spawn")
        queue = ctx.Queue()
        state.cmd_q, state.reply_q = ctx.Queue(), ctx.Queue()
        job = {**params, "path": str(path), "out": str(out)}
        # not a daemon: the analysis starts its own worker processes for the parts
        proc = ctx.Process(
            target=run_job, args=(job, queue, state.cmd_q, state.reply_q), daemon=False
        )
        state.process = proc
        with self.lock:
            self.jobs[job_id] = state
        proc.start()
        threading.Thread(target=self._drain, args=(state, queue, proc), daemon=True).start()
        return state

    def _drain(self, state: JobState, queue: Any, proc: Any) -> None:
        while not state.done:
            try:
                msg = queue.get(timeout=0.5)
            except Exception:  # noqa: BLE001 - queue.Empty
                if not proc.is_alive() and queue.empty():
                    state.error = state.error or "the analysis process stopped unexpectedly"
                    state.done = True
                state.elapsed_s = time.time() - state.started
                continue
            kind = msg["type"]
            if kind == "progress":
                state.stage, state.message = msg["stage"], msg["message"]
                state.fraction, state.eta_s = msg["fraction"], msg["eta_s"]
                state.elapsed_s = msg["elapsed_s"]
            elif kind == "done":
                state.pack = msg["pack"]
                state.result = summarise_pack(Path(msg["pack"]))
                state.fraction, state.eta_s, state.stage = 1.0, 0.0, "done"
                state.message = f"finished in {msg['seconds']} s"
                state.done = True
            elif kind == "error":
                state.error = msg["message"]
                state.done = True
        proc.join(timeout=2)

    def call(self, job_id: str, payload: dict[str, Any], timeout: float = 120.0) -> dict[str, Any]:
        """Send one command to a job's interview session and wait for its reply."""
        s = self.jobs.get(job_id)
        if s is None or not s.done or s.error or s.cmd_q is None:
            return {"error": "the analysis is not finished"}
        if s.process is None or not s.process.is_alive():
            return {"error": "the interview session has ended; run the analysis again"}
        with s.call_lock:
            s.cmd_q.put(payload)
            try:
                return dict(s.reply_q.get(timeout=timeout))
            except Exception:  # noqa: BLE001 - queue.Empty
                return {"error": "the session did not answer in time"}

    def shutdown(self) -> None:
        for s in self.jobs.values():
            if s.cmd_q is not None:
                s.cmd_q.put({"cmd": "quit"})
            if s.process is not None and s.process.is_alive():
                s.process.join(timeout=3)
                if s.process.is_alive():
                    kill_tree(s.process)

    def cancel(self, job_id: str) -> None:
        state = self.jobs.get(job_id)
        if state and state.process is not None and state.process.is_alive():
            kill_tree(state.process)
            state.error, state.done = "cancelled", True


def _json(handler: BaseHTTPRequestHandler, payload: Any, status: int = 200) -> None:
    body = json.dumps(payload).encode("utf-8")
    handler.send_response(status)
    handler.send_header("Content-Type", "application/json")
    handler.send_header("Content-Length", str(len(body)))
    handler.end_headers()
    handler.wfile.write(body)


def _content_type(handler: BaseHTTPRequestHandler) -> str:
    return handler.headers.get("Content-Type", "").split(";")[0].strip().lower()


def make_handler(app: App) -> type[BaseHTTPRequestHandler]:
    """Request handler class bound to *app*."""

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, format: str, *args: Any) -> None:  # noqa: A002
            return

        def end_headers(self) -> None:
            self.send_header("X-Content-Type-Options", "nosniff")
            self.send_header("Referrer-Policy", "no-referrer")
            self.send_header("Cache-Control", "no-store")
            super().end_headers()

        # ------------------------------------------------------------ guards
        def _origins(self) -> set[str]:
            addr = self.server.server_address
            port = addr[1] if isinstance(addr, tuple) else 0
            return {f"http://127.0.0.1:{port}", f"http://localhost:{port}"}

        def _check_host(self) -> None:
            host = self.headers.get("Host", "")
            if host not in {o.removeprefix("http://") for o in self._origins()}:
                raise BadRequest("forbidden", 403)

        def _check_token(self, url: Any) -> None:
            given = self.headers.get("X-Stepscribe-Token", "")
            if not given and url.path.startswith(QUERY_TOKEN_PATHS):
                given = parse_qs(url.query).get("t", [""])[0]
            if not hmac.compare_digest(given.encode(), app.token.encode()):
                raise BadRequest("forbidden", 403)

        def _check_post(self, url: Any) -> None:
            origin = self.headers.get("Origin")
            if origin is not None and origin not in self._origins():
                raise BadRequest("forbidden", 403)
            want = "application/octet-stream" if url.path == "/api/upload" else "application/json"
            if _content_type(self) != want:
                raise BadRequest(f"Content-Type must be {want}", 415)

        def _guarded(self, post: bool) -> Any | None:
            """Host, token, origin and content-type checks; the parsed URL, or None if refused."""
            url = urlparse(self.path)
            try:
                self._check_host()
                public = not post and url.path in ("/", "/favicon.svg", "/favicon.ico")
                if not public:
                    self._check_token(url)
                if post:
                    self._check_post(url)
            except BadRequest as e:
                self._fail(e)
                return None
            return url

        def _fail(self, e: BadRequest) -> None:
            if e.status >= 413:
                self.close_connection = True  # the unread body must not be parsed as a request
            _json(self, {"error": str(e)}, e.status)

        def _run(self, handler: Any, post: bool) -> None:
            url = self._guarded(post)
            if url is None:
                return
            try:
                handler(url)
            except BadRequest as e:
                self._fail(e)
            except (BrokenPipeError, ConnectionResetError):
                self.close_connection = True
            except Exception:  # noqa: BLE001 - never leak a traceback to the client
                self.close_connection = True
                try:
                    _json(self, {"error": "internal error"}, 500)
                except OSError:
                    pass

        def _read_json(self) -> dict[str, Any]:
            length = self._content_length()
            if length > MAX_JSON_BYTES:
                raise BadRequest("request body too large", 413)
            try:
                body = json.loads(self.rfile.read(length) or b"{}")
            except (ValueError, UnicodeDecodeError):
                raise BadRequest("the request body is not valid JSON") from None
            if not isinstance(body, dict):
                raise BadRequest("the request body must be a JSON object")
            return body

        def _content_length(self) -> int:
            raw = self.headers.get("Content-Length")
            if raw is None or not raw.strip().isdigit():
                raise BadRequest("a valid Content-Length is required")
            return int(raw)

        # ------------------------------------------------------------ GET
        def do_GET(self) -> None:  # noqa: N802
            self._run(self._get, post=False)

        def do_OPTIONS(self) -> None:  # noqa: N802
            # no CORS: a preflight is never approved, so cross-site JSON and upload calls fail
            self._run(lambda _u: self.send_error(405), post=False)

        def _get(self, url: Any) -> None:
            q = parse_qs(url.query)
            if url.path == "/":
                body = (
                    INDEX.read_text(encoding="utf-8")
                    .replace("{{VERSION}}", __version__)
                    .replace("{{TOKEN}}", app.token)
                    .encode("utf-8")
                )
                self.send_response(200)
                self.send_header("Content-Type", "text/html; charset=utf-8")
                self.send_header("Content-Security-Policy", CSP)
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)
            elif url.path in ("/favicon.svg", "/favicon.ico"):
                body = FAVICON.encode("utf-8")
                self.send_response(200)
                self.send_header("Content-Type", "image/svg+xml")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)
            elif url.path == "/api/samples":
                files = app.samples()
                _json(
                    self,
                    [
                        {"index": i, "name": f.name, "mb": round(f.stat().st_size / 1e6, 1)}
                        for i, f in enumerate(files)
                    ],
                )
            elif url.path == "/api/status":
                self._status(q.get("id", [""])[0])
            elif url.path == "/api/zip":
                self._zip(q.get("id", [""])[0])
            elif url.path == "/api/questions/next":
                _json(self, app.call(q.get("id", [""])[0], {"cmd": "state"}))
            elif url.path == "/api/pack/preview":
                _json(self, app.call(q.get("id", [""])[0], {"cmd": "preview"}))
            elif url.path == "/api/pack/download":
                jid = q.get("id", [""])[0]
                res = app.call(jid, {"cmd": "save"})
                if "error" in res:
                    _json(self, res, 400)
                else:
                    self._zip(jid)
            elif url.path == "/api/render":
                self._render(q)
            elif url.path == "/api/report":
                s = app.jobs.get(q.get("id", [""])[0])
                _json(self, (s.result if s and s.result else {"error": "unknown job"}))
            elif url.path.startswith("/files/"):
                self._file(unquote(url.path[len("/files/") :]))
            else:
                self.send_error(404)

        def _status(self, job_id: str) -> None:
            s = app.jobs.get(job_id)
            if s is None:
                _json(self, {"error": "unknown job"}, 404)
                return
            _json(
                self,
                {
                    "id": s.id,
                    "name": s.name,
                    "stage": s.stage,
                    "message": s.message,
                    "fraction": s.fraction,
                    "eta_s": s.eta_s,
                    "elapsed_s": s.elapsed_s or time.time() - s.started,
                    "done": s.done,
                    "error": s.error,
                    "result": s.result,
                    "job": s.id,
                },
            )

        def _render(self, q: dict[str, list[str]]) -> None:
            jid = q.get("id", [""])[0]
            refs = [r for r in q.get("highlight", [""])[0].split(",") if r]
            res = app.call(jid, {"cmd": "render", "refs": refs, "view": q.get("view", ["iso"])[0]})
            if "path" not in res:
                _json(self, res, 400)
                return
            data = Path(res["path"]).read_bytes()
            self.send_response(200)
            self.send_header("Content-Type", "image/png")
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)

        def _zip(self, job_id: str) -> None:
            s = app.jobs.get(job_id)
            if s is None or not s.pack:
                self.send_error(404)
                return
            buf = io.BytesIO()
            root = Path(s.pack)
            with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
                for f in sorted(root.rglob("*")):
                    if f.is_file():
                        zf.write(f, f"{root.name}/{f.relative_to(root).as_posix()}")
            data = buf.getvalue()
            self.send_response(200)
            self.send_header("Content-Type", "application/zip")
            self.send_header("Content-Disposition", f'attachment; filename="{root.name}.zip"')
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)

        def _file(self, rel: str) -> None:
            job_id, _, sub = rel.partition("/")
            s = app.jobs.get(job_id)
            if s is None or not s.pack:
                self.send_error(404)
                return
            root = Path(s.pack).resolve()
            target = (root / sub).resolve()
            if root not in target.parents or not target.is_file():
                self.send_error(404)
                return
            data = target.read_bytes()
            self.send_response(200)
            self.send_header("Content-Type", MIME.get(target.suffix, "application/octet-stream"))
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)

        # ------------------------------------------------------------ POST
        def do_POST(self) -> None:  # noqa: N802
            self._run(self._post, post=True)

        def _post(self, url: Any) -> None:
            q = {k: v[0] for k, v in parse_qs(url.query).items()}
            if url.path == "/api/upload":
                self._upload(q)
            elif url.path == "/api/start_path":
                body = self._read_json()
                params = _params(body)
                if "sample" in body:
                    files = app.samples()
                    i = body["sample"]
                    if isinstance(i, bool) or not isinstance(i, int) or not 0 <= i < len(files):
                        raise BadRequest("unknown sample")
                    p = files[i]
                else:
                    p = _step_path(body.get("path"))
                state = app.start(p, p.name, params)
                _json(self, {"id": state.id})
            elif url.path == "/api/cancel":
                app.cancel(q.get("id", ""))
                _json(self, {"ok": True})
            elif url.path == "/api/answers":
                body = self._read_json()
                res = app.call(
                    q.get("id", ""),
                    {
                        "cmd": "answer",
                        "id": body.get("question_id", ""),
                        "status": body.get("status", "answered"),
                        "value": body.get("value"),
                        "note": body.get("note"),
                    },
                )
                _json(self, res, 400 if "error" in res else 200)
            elif url.path == "/api/answers/undo":
                res = app.call(q.get("id", ""), {"cmd": "undo"})
                _json(self, res, 400 if "error" in res else 200)
            else:
                self.send_error(404)

        def _upload(self, q: dict[str, str]) -> None:
            length = self._content_length()
            if length <= 0:
                raise BadRequest("the upload is empty")
            if length > app.max_upload_bytes:
                raise BadRequest(f"the file is larger than {app.max_upload_bytes >> 20} MB", 413)
            params = _params(q)
            name = Path(unquote(q.get("name", ""))).name
            if not name.lower().endswith(STEP_SUFFIXES):
                name = (name or "upload") + ".step"
            dest_dir = app.workdir / "uploads" / uuid.uuid4().hex[:8]
            dest_dir.mkdir(parents=True, exist_ok=True)
            dest = dest_dir / name
            ok = False
            try:
                remaining, first = length, True
                with dest.open("wb") as fh:
                    while remaining > 0:
                        chunk = self.rfile.read(min(1 << 20, remaining))
                        if not chunk:
                            break
                        if first and not chunk.lstrip().startswith(STEP_MAGIC):
                            raise BadRequest("this is not a STEP file", 415)
                        first = False
                        fh.write(chunk)
                        remaining -= len(chunk)
                if remaining:
                    raise BadRequest("the upload ended early")
                ok = True
            finally:
                if not ok:
                    shutil.rmtree(dest_dir, ignore_errors=True)
            state = app.start(dest, name, params)
            _json(self, {"id": state.id})

    return Handler


def _step_path(raw: Any) -> Path:
    """An existing STEP file; errors name the file, never the directory."""
    if not isinstance(raw, str) or not raw.strip():
        raise BadRequest("give the path of a .step or .stp file")
    try:
        p = Path(raw.strip()).expanduser().resolve()
        usable = p.is_file() and p.suffix.lower() in STEP_SUFFIXES
    except (OSError, ValueError):
        raise BadRequest("that path cannot be read") from None
    if not usable:
        raise BadRequest(f"not an existing .step or .stp file: {Path(raw.strip()).name}")
    return p


def _params(src: dict[str, Any]) -> dict[str, Any]:
    def flag(k: str, default: bool) -> bool:
        v = src.get(k)
        return default if v is None else str(v).lower() in ("1", "true", "yes", "on")

    density: float | None = None
    raw = src.get("density")
    if raw not in (None, ""):
        try:
            density = float(raw)
        except (TypeError, ValueError):
            raise BadRequest("density must be a number") from None
        if not math.isfinite(density) or density <= 0:
            raise BadRequest("density must be a positive number")
    material = str(src.get("material") or "").strip()
    if material and not any(k in material.lower() for k in config.MATERIAL_KEYWORDS):
        raise BadRequest("unknown material; try one of: " + ", ".join(config.MATERIAL_KEYWORDS))
    up, front = src.get("up") or "+Z", src.get("front") or "-Y"
    if up not in AXES or front not in AXES:
        raise BadRequest("up and front must be one of " + ", ".join(AXES))
    return {
        "material": material or None,
        "density": density,
        "up": up,
        "front": front,
        "images": flag("images", True),
        "interference": flag("interference", True),
    }


def serve(
    port: int = 8765,
    open_browser: bool = True,
    sample_dir: Path | None = None,
    preload: Path | None = None,
    max_upload_mb: int = 500,
) -> None:
    """Run the UI until interrupted."""
    require_interactive("start the local server")
    workdir = Path(tempfile.mkdtemp(prefix="stepscribe_ui_"))
    app = App(workdir, sample_dir)
    app.max_upload_bytes = max_upload_mb * 1024 * 1024
    server = ThreadingHTTPServer(("127.0.0.1", port), make_handler(app))
    url = f"http://127.0.0.1:{server.server_address[1]}/"
    if preload is not None:
        state = app.start(preload, preload.name, _params({}))
        url += f"?job={state.id}"
    print(f"stepscribe UI on {url}  (Ctrl+C to stop)")
    if open_browser:
        require_interactive("open a browser")
        webbrowser.open(url)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
        app.shutdown()
        shutil.rmtree(workdir, ignore_errors=True)
