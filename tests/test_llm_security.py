"""H4: an API key is never sent over plain HTTP to a remote host, and never appears in an error."""

from __future__ import annotations

import warnings
from pathlib import Path

import pytest
from typer.testing import CliRunner

from stepscribe.cli import app
from stepscribe.llm.adapter import LLMConfig, LLMConfigError, LLMError, chat

KEY = "sk-SECRET-1234567890"


def env(base: str, key: str | None = KEY, **extra: str) -> dict[str, str]:
    e = {"STEPSCRIBE_LLM_BASE_URL": base, "STEPSCRIBE_LLM_MODEL": "m", **extra}
    if key:
        e["STEPSCRIBE_LLM_API_KEY"] = key
    return e


@pytest.mark.parametrize(
    "base", ["http://api.example.com/v1", "http://10.0.0.5:8000", "http://[2001:db8::1]/v1"]
)
def test_a_key_is_refused_over_plain_http_to_a_remote_host(base: str) -> None:
    with pytest.raises(LLMConfigError) as e:
        LLMConfig.from_env(env(base))
    msg = str(e.value)
    assert "http" in msg and "STEPSCRIBE_LLM_ALLOW_INSECURE" in msg and KEY not in msg


@pytest.mark.parametrize(
    "base",
    [
        "http://localhost:11434",
        "http://127.0.0.1:8080/v1",
        "http://127.0.0.5:8080",
        "http://[::1]:8080",
        "https://api.example.com/v1",
    ],
)
def test_local_hosts_and_https_may_carry_a_key(base: str) -> None:
    assert LLMConfig.from_env(env(base)).api_key == KEY


def test_plain_http_without_a_key_is_allowed() -> None:
    assert LLMConfig.from_env(env("http://api.example.com/v1", key=None)).api_key is None


def test_an_explicit_override_allows_it_with_a_warning() -> None:
    with pytest.warns(UserWarning, match="plain HTTP"):
        cfg = LLMConfig.from_env(
            env("http://api.example.com/v1", STEPSCRIBE_LLM_ALLOW_INSECURE="1")
        )
    assert cfg.api_key == KEY
    with warnings.catch_warnings():
        warnings.simplefilter("error")  # no other value of the override counts
        with pytest.raises(LLMConfigError):
            LLMConfig.from_env(env("http://api.example.com/v1", STEPSCRIBE_LLM_ALLOW_INSECURE="0"))


def test_chat_refuses_an_insecure_config_built_by_hand() -> None:
    cfg = LLMConfig("http://api.example.com", "m", KEY, "openai", False)
    with pytest.raises(LLMConfigError) as e:
        chat(cfg, "hi")
    assert KEY not in str(e.value)


def test_the_key_never_appears_in_a_connection_error() -> None:
    cfg = LLMConfig("http://127.0.0.1:1", "m", KEY, "openai", False, timeout_s=3.0)
    with pytest.raises(LLMError) as e:
        chat(cfg, "hi")
    assert KEY not in str(e.value) and KEY not in repr(e.value)
    assert e.value.__cause__ is None and e.value.__suppress_context__


def test_the_key_never_appears_in_an_http_error(monkeypatch: pytest.MonkeyPatch) -> None:
    import httpx

    def fake_post(url: str, **kw: object) -> httpx.Response:
        return httpx.Response(401, request=httpx.Request("POST", url), text=f"bad key {KEY}")

    monkeypatch.setattr(httpx, "post", fake_post)
    cfg = LLMConfig("http://127.0.0.1:9", "m", KEY, "openai", False)
    with pytest.raises(LLMError) as e:
        chat(cfg, "hi")
    assert "401" in str(e.value) and KEY not in str(e.value)


def test_the_command_line_never_prints_the_key(
    step_files: dict[str, Path], monkeypatch: pytest.MonkeyPatch
) -> None:
    for k, v in env("http://api.example.com/v1").items():
        monkeypatch.setenv(k, v)
    res = CliRunner().invoke(app, ["ask", str(step_files["plate_4xM3"]), "What is it?"])
    assert KEY not in res.output and res.exit_code != 0
    assert "STEPSCRIBE_LLM_ALLOW_INSECURE" in res.output


def test_ci_audits_dependencies_without_blocking_yet() -> None:
    root = Path(__file__).parent.parent
    ci = (root / ".github" / "workflows" / "ci.yml").read_text(encoding="utf-8")
    assert "pip-audit" in ci and "continue-on-error: true" in ci
    assert "pip-audit" in (root / "pyproject.toml").read_text(encoding="utf-8")
