"""H1: the local web UI cannot be driven or read by another website."""

from __future__ import annotations

import http.client
import json
import re
import shutil
import socket
import subprocess
import threading
from collections.abc import Iterator
from http.server import ThreadingHTTPServer
from pathlib import Path
from typing import Any

import pytest

from stepscribe.ui import server as ui_server
from stepscribe.ui.server import App, JobState, make_handler

STEP_HEAD = b"ISO-10303-21;\nHEADER;\nENDSEC;\nDATA;\nENDSEC;\nEND-ISO-10303-21;\n"


class Ui:
    """A live server on a random port plus a raw HTTP helper."""

    def __init__(self, app: App, httpd: ThreadingHTTPServer) -> None:
        self.app, self.httpd = app, httpd
        self.port = httpd.server_address[1]
        self.token = app.token
        self.started: list[dict[str, Any]] = []

    def request(
        self,
        method: str,
        path: str,
        body: bytes | None = None,
        headers: dict[str, str] | None = None,
        token: str | None | bool = True,
        host: str | None = None,
    ) -> tuple[int, dict[str, str], bytes]:
        hdrs = {"Host": host or f"127.0.0.1:{self.port}"}
        if token is True:
            hdrs["X-Stepscribe-Token"] = self.token
        elif token:
            hdrs["X-Stepscribe-Token"] = str(token)
        hdrs.update(headers or {})
        conn = http.client.HTTPConnection("127.0.0.1", self.port, timeout=15)
        try:
            conn.putrequest(method, path, skip_host=True, skip_accept_encoding=True)
            for k, v in hdrs.items():
                conn.putheader(k, v)
            if body is not None and "Content-Length" not in hdrs:
                conn.putheader("Content-Length", str(len(body)))
            conn.endheaders(body)
            resp = conn.getresponse()
            return resp.status, {k.lower(): v for k, v in resp.getheaders()}, resp.read()
        finally:
            conn.close()

    def post_json(self, path: str, payload: Any, **kw: Any) -> tuple[int, dict[str, str], bytes]:
        headers = {"Content-Type": "application/json", **kw.pop("headers", {})}
        return self.request("POST", path, json.dumps(payload).encode(), headers, **kw)


@pytest.fixture
def ui(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Iterator[Ui]:
    samples = tmp_path / "samples"
    samples.mkdir()
    (samples / "demo.step").write_bytes(STEP_HEAD)
    app = App(tmp_path / "work", samples)
    app.workdir.mkdir()
    httpd = ThreadingHTTPServer(("127.0.0.1", 0), make_handler(app))
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    live = Ui(app, httpd)

    def fake_start(path: Path, name: str, params: dict[str, Any]) -> JobState:
        live.started.append({"path": path, "name": name, "params": params})
        return JobState("fake", name)

    monkeypatch.setattr(app, "start", fake_start)
    yield live
    httpd.shutdown()
    httpd.server_close()


# ---------------------------------------------------------------- token (S1)
@pytest.mark.parametrize(
    ("method", "path"),
    [
        ("GET", "/api/samples"),
        ("GET", "/api/status?id=x"),
        ("GET", "/api/report?id=x"),
        ("GET", "/api/zip?id=x"),
        ("GET", "/api/render?id=x"),
        ("GET", "/files/x/a.png"),
        ("POST", "/api/cancel?id=x"),
        ("POST", "/api/start_path"),
        ("POST", "/api/upload?name=a.step"),
    ],
)
def test_api_without_or_with_wrong_token_is_403(ui: Ui, method: str, path: str) -> None:
    body = b"{}" if method == "POST" else None
    ct = {"Content-Type": "application/json"} if method == "POST" else {}
    assert ui.request(method, path, body, ct, token=False)[0] == 403
    assert ui.request(method, path, body, ct, token="not-the-token")[0] == 403


def test_page_carries_the_token_and_sends_it(ui: Ui) -> None:
    status, _, body = ui.request("GET", "/", token=False)
    assert status == 200
    page = body.decode()
    assert f'<meta name="stepscribe-token" content="{ui.token}">' in page
    assert len(ui.token) >= 40
    assert "X-Stepscribe-Token" in page, "the page must send the token on its requests"


def test_query_token_is_accepted_for_files_and_images(ui: Ui) -> None:
    for path in ("/files/x/a.png", "/api/render?id=x", "/api/zip?id=x"):
        sep = "&" if "?" in path else "?"
        status = ui.request("GET", f"{path}{sep}t={ui.token}", token=False)[0]
        assert status != 403, path
        assert ui.request("GET", f"{path}{sep}t=wrong", token=False)[0] == 403, path
    # the query token is not a way around the header on ordinary endpoints
    assert ui.request("GET", f"/api/samples?t={ui.token}", token=False)[0] == 403


# ------------------------------------------------------------- host (S2)
def test_wrong_host_is_403_even_with_token(ui: Ui) -> None:
    for host in ("evil.example", "evil.example:80", f"evil.example:{ui.port}", "127.0.0.1"):
        assert ui.request("GET", "/api/samples", host=host)[0] == 403, host
        assert ui.request("GET", "/", token=False, host=host)[0] == 403, host
    assert ui.request("GET", "/api/samples", host=f"localhost:{ui.port}")[0] == 200


# ------------------------------------------------------------- origin (S1)
def test_foreign_origin_on_post_is_403(ui: Ui) -> None:
    for origin in ("https://evil.example", "null", f"http://evil.example:{ui.port}"):
        status = ui.post_json("/api/cancel?id=x", {}, headers={"Origin": origin})[0]
        assert status == 403, origin
    for origin in (f"http://127.0.0.1:{ui.port}", f"http://localhost:{ui.port}"):
        assert ui.post_json("/api/cancel?id=x", {}, headers={"Origin": origin})[0] == 200


# ---------------------------------------------------------- content type (S1)
def test_simple_request_content_types_are_refused(ui: Ui) -> None:
    sample = ui.request("GET", "/api/samples")[2]
    assert json.loads(sample)
    for ct in ("text/plain", "application/x-www-form-urlencoded", ""):
        headers = {"Content-Type": ct} if ct else {}
        status = ui.request("POST", "/api/start_path", b'{"sample": 0}', headers)[0]
        assert status == 415, ct
    wrong = {"Content-Type": "application/json"}
    assert ui.request("POST", "/api/upload?name=a.step", STEP_HEAD, wrong)[0] == 415
    assert not ui.started


def test_options_gets_no_cors_headers(ui: Ui) -> None:
    _, headers, _ = ui.request("OPTIONS", "/api/start_path", token=False)
    assert not [h for h in headers if h.startswith("access-control-")]


# ------------------------------------------------------------ start_path (S1)
def test_start_path_only_accepts_step_files(ui: Ui, tmp_path: Path) -> None:
    txt = tmp_path / "secret.txt"
    txt.write_text("not a model")
    for target in (txt, tmp_path, tmp_path / "missing.step"):
        status, _, body = ui.post_json("/api/start_path", {"path": str(target)})
        assert status == 400, target
        assert str(tmp_path) not in body.decode(), "do not echo directories back"
    assert not ui.started


def test_start_path_accepts_step_and_stp_in_any_case(ui: Ui, tmp_path: Path) -> None:
    for name in ("a.step", "b.STP", "c.StEp"):
        f = tmp_path / name
        f.write_bytes(STEP_HEAD)
        assert ui.post_json("/api/start_path", {"path": str(f)})[0] == 200
    assert [s["name"] for s in ui.started] == ["a.step", "b.STP", "c.StEp"]


# ---------------------------------------------------------------- uploads (S4)
def test_upload_rejects_bad_content_length(ui: Ui) -> None:
    ct = {"Content-Type": "application/octet-stream"}
    assert ui.request("POST", "/api/upload?name=a.step", None, ct)[0] == 400, "missing"
    for value in ("-5", "abc", ""):
        status = ui.request(
            "POST", "/api/upload?name=a.step", b"", {**ct, "Content-Length": value}
        )[0]
        assert status == 400, value
    assert not ui.started


def test_upload_over_the_cap_is_413(ui: Ui) -> None:
    ui.app.max_upload_bytes = 1000
    ct = {"Content-Type": "application/octet-stream"}
    status = ui.request("POST", "/api/upload?name=a.step", STEP_HEAD + b"x" * 2000, ct)[0]
    assert status == 413
    assert not ui.started
    assert not list((ui.app.workdir / "uploads").glob("*/*")), "nothing is left on disk"


def test_upload_must_look_like_step(ui: Ui) -> None:
    ct = {"Content-Type": "application/octet-stream"}
    status = ui.request("POST", "/api/upload?name=a.step", b"MZ\x90\x00 not step", ct)[0]
    assert status == 415
    assert ui.request("POST", "/api/upload?name=a.step", STEP_HEAD, ct)[0] == 200
    assert list((ui.app.workdir / "uploads").glob("*/*")), "a valid upload is kept"
    assert len(ui.started) == 1


def test_truncated_upload_is_cleaned_up(ui: Ui) -> None:
    sock = socket.create_connection(("127.0.0.1", ui.port), timeout=10)
    head = (
        f"POST /api/upload?name=a.step HTTP/1.1\r\nHost: 127.0.0.1:{ui.port}\r\n"
        f"X-Stepscribe-Token: {ui.token}\r\nContent-Type: application/octet-stream\r\n"
        f"Content-Length: 5000\r\n\r\n"
    )
    sock.sendall(head.encode() + STEP_HEAD)
    sock.shutdown(socket.SHUT_WR)
    reply = sock.recv(4096).decode("latin-1")
    sock.close()
    assert " 400 " in reply.splitlines()[0]
    assert not list((ui.app.workdir / "uploads").glob("*/*")), "partial upload must be removed"
    assert not ui.started


# ------------------------------------------------------------- validation (S4)
@pytest.mark.parametrize(
    "payload",
    [
        {"density": "heavy"},
        {"density": "-1"},
        {"density": "nan"},
        {"up": "sideways"},
        {"front": "+W"},
        {"material": "unobtainium"},
    ],
)
def test_bad_parameters_are_400(ui: Ui, tmp_path: Path, payload: dict[str, str]) -> None:
    f = tmp_path / "a.step"
    f.write_bytes(STEP_HEAD)
    status, _, body = ui.post_json("/api/start_path", {"path": str(f), **payload})
    assert status == 400
    assert "error" in json.loads(body)
    assert not ui.started


def test_bad_json_is_400_and_unexpected_errors_are_500_without_traceback(
    ui: Ui, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    ct = {"Content-Type": "application/json"}
    assert ui.request("POST", "/api/start_path", b"{not json", ct)[0] == 400
    assert ui.request("POST", "/api/start_path", b"[1, 2]", ct)[0] == 400

    def boom(*a: Any, **k: Any) -> None:
        raise RuntimeError("secret internal detail C:\\Users\\x")

    monkeypatch.setattr(ui.app, "start", boom)
    f = tmp_path / "a.step"
    f.write_bytes(STEP_HEAD)
    status, _, body = ui.post_json("/api/start_path", {"path": str(f)})
    assert status == 500
    assert "Traceback" not in body.decode() and "secret internal detail" not in body.decode()
    assert "error" in json.loads(body)


# ------------------------------------------------------------- headers (S9)
def test_security_headers_on_every_response(ui: Ui) -> None:
    for method, path, tok in [
        ("GET", "/", False),
        ("GET", "/favicon.svg", False),
        ("GET", "/api/samples", True),
        ("GET", "/api/status?id=missing", True),
        ("GET", "/api/samples", False),  # 403 too
        ("GET", "/nope", True),
    ]:
        _, h, _ = ui.request(method, path, token=tok)
        assert h.get("x-content-type-options") == "nosniff", path
        assert h.get("referrer-policy") == "no-referrer", path
        assert h.get("cache-control") == "no-store", path


def test_page_csp(ui: Ui) -> None:
    csp = ui.request("GET", "/", token=False)[1].get("content-security-policy", "")
    for part in (
        "default-src 'self'",
        "img-src 'self' data:",
        "connect-src 'self'",
        "frame-ancestors 'none'",
    ):
        assert part in csp


def test_pack_html_is_served_as_plain_text(ui: Ui, tmp_path: Path) -> None:
    pack = tmp_path / "pack"
    pack.mkdir()
    (pack / "evil.html").write_text("<script>alert(1)</script>")
    ui.app.jobs["j1"] = JobState("j1", "x", pack=str(pack))
    status, headers, _ = ui.request("GET", "/files/j1/evil.html")
    assert status == 200
    assert headers["content-type"].startswith("text/plain")


# ----------------------------------------------------------------- samples
def test_samples_never_expose_paths(ui: Ui, tmp_path: Path) -> None:
    status, _, body = ui.request("GET", "/api/samples")
    listing = json.loads(body)
    assert status == 200 and listing[0]["name"] == "demo.step"
    assert str(tmp_path) not in body.decode() and "path" not in listing[0]
    assert listing[0]["index"] == 0
    assert ui.post_json("/api/start_path", {"sample": listing[0]["index"]})[0] == 200
    assert ui.started[-1]["path"].name == "demo.step"
    assert ui.post_json("/api/start_path", {"sample": 99})[0] == 400


# --------------------------------------------------------------------- page
@pytest.mark.skipif(shutil.which("node") is None, reason="node is needed to run the page's esc()")
def test_esc_escapes_quotes() -> None:
    page = Path(ui_server.__file__).with_name("index.html").read_text(encoding="utf-8")
    line = next(ln for ln in page.splitlines() if ln.startswith("const esc ="))
    out = subprocess.run(
        ["node", "-e", f"{line}\nprocess.stdout.write(esc(`<a href=\"x\" onclick='y'>&`))"],
        capture_output=True,
        text=True,
        check=True,
    ).stdout
    assert out == "&lt;a href=&quot;x&quot; onclick=&#39;y&#39;&gt;&amp;"


def test_page_has_no_unescaped_attribute_values() -> None:
    """Every ``value="${...}"`` / ``alt="..${...}"`` template must go through esc()."""
    page = Path(ui_server.__file__).with_name("index.html").read_text(encoding="utf-8")
    bad = [
        m.group(0)
        for m in re.finditer(r"""(?:value|alt|title|src|data-\w+)="[^"]*\$\{([^}]*)\}""", page)
        if not re.search(r"esc\(|encodeURIComponent\(|jobId|\bid\b|\bi\b|tok", m.group(1))
    ]
    assert not bad, bad
