"""Free memory on macOS (vm_stat), and what the worker count does when the OS does not say."""

from __future__ import annotations

import subprocess
import sys

import pytest

from stepscribe import analysis as A

# What `vm_stat` prints on Apple silicon (16 KiB pages) and on Intel (4 KiB pages); the figures differ,
# the layout is the same. Only the first line and the free, inactive and speculative lines are read.
VM_STAT_16K = """\
Mach Virtual Memory Statistics: (page size of 16384 bytes)
Pages free:                               11830.
Pages active:                            212480.
Pages inactive:                          207330.
Pages speculative:                         3121.
Pages throttled:                              0.
Pages wired down:                        100417.
Pages purgeable:                           4096.
"Translation faults":                 598372616.
Pages copy-on-write:                   10462881.
Pages zero filled:                    312574329.
Pages reactivated:                      1342910.
Pages purged:                           2371028.
File-backed pages:                       107344.
Anonymous pages:                         315567.
Pages stored in compressor:              318005.
Pages occupied by compressor:            101188.
Decompressions:                        20563819.
Compressions:                          26402195.
Pageins:                                5123877.
Pageouts:                                 21408.
Swapins:                                 884112.
Swapouts:                               1009934.
"""
VM_STAT_4K = """\
Mach Virtual Memory Statistics: (page size of 4096 bytes)
Pages free:                              104857.
Pages active:                            901120.
Pages inactive:                          524288.
Pages speculative:                        20480.
Pages throttled:                              0.
Pages wired down:                        400000.
"Translation faults":                  12345678.
"""


def test_the_free_inactive_and_speculative_pages_are_added_and_multiplied_by_the_page_size() -> (
    None
):
    assert A.parse_vm_stat(VM_STAT_16K) == (11830 + 207330 + 3121) * 16384
    assert A.parse_vm_stat(VM_STAT_4K) == (104857 + 524288 + 20480) * 4096


def test_the_layout_may_vary_in_spacing_and_line_endings() -> None:
    text = VM_STAT_4K.replace("\n", "\r\n").replace("Pages free:   ", "Pages free:\t")
    assert A.parse_vm_stat(text) == (104857 + 524288 + 20480) * 4096


@pytest.mark.parametrize(
    "text",
    [
        "",
        "   \n\n",
        "garbage",
        "\x00\x01\x02",
        VM_STAT_4K.split("\n", 1)[1],  # no page size line
        VM_STAT_4K.replace("page size of 4096 bytes", "page size of lots bytes"),
        VM_STAT_4K.replace("page size of 4096 bytes", "page size of 0 bytes"),
        VM_STAT_4K.replace("page size of 4096 bytes", "page size of -4096 bytes"),
        VM_STAT_4K.replace("page size of 4096 bytes", "page size of 99999999999 bytes"),
        VM_STAT_4K.replace("Pages free:                              104857.", ""),
        VM_STAT_4K.replace(
            "Pages inactive:                          524288.", "Pages inactive: x."
        ),
        VM_STAT_4K.replace("Pages speculative:                        20480.", ""),
        VM_STAT_4K.replace("104857.", "-104857."),
        VM_STAT_4K.replace("Pages free:                              104857.", "Pages free: ."),
        "Pages free: 1.\nPages inactive: 1.\nPages speculative: 1.\n",  # counts, but no page size
    ],
)
def test_malformed_output_is_none_and_never_raises(text: str) -> None:
    assert A.parse_vm_stat(text) is None


def completed(stdout: str, code: int = 0) -> subprocess.CompletedProcess[bytes]:
    return subprocess.CompletedProcess(["vm_stat"], code, stdout.encode(), b"")


def test_running_vm_stat_returns_the_parsed_value() -> None:
    seen: dict[str, object] = {}

    def run(cmd, **kw):  # type: ignore[no-untyped-def]
        seen.update(cmd=cmd, timeout=kw.get("timeout"))
        return completed(VM_STAT_16K)

    assert A.macos_available_bytes(run) == (11830 + 207330 + 3121) * 16384
    assert seen["cmd"] == ["/usr/bin/vm_stat"] and 0 < float(seen["timeout"]) <= 5  # type: ignore[arg-type]


@pytest.mark.parametrize(
    "boom",
    [
        subprocess.TimeoutExpired("vm_stat", 2),
        FileNotFoundError("no vm_stat"),
        PermissionError("denied"),
        OSError("broken"),
        subprocess.SubprocessError("odd"),
        UnicodeDecodeError("utf-8", b"\xff", 0, 1, "bad"),
        ValueError("odd"),
    ],
)
def test_a_missing_hanging_or_broken_command_is_none(boom: Exception) -> None:
    def run(cmd, **kw):  # type: ignore[no-untyped-def]
        raise boom

    assert A.macos_available_bytes(run) is None


def test_a_failing_exit_code_or_unreadable_output_is_none() -> None:
    assert A.macos_available_bytes(lambda cmd, **kw: completed(VM_STAT_16K, code=1)) is None
    assert A.macos_available_bytes(lambda cmd, **kw: completed("garbage")) is None
    assert A.macos_available_bytes(lambda cmd, **kw: completed("")) is None
    bad_bytes = subprocess.CompletedProcess(["vm_stat"], 0, b"\xff\xfe\xfa", b"")
    assert A.macos_available_bytes(lambda cmd, **kw: bad_bytes) is None


def test_available_ram_bytes_uses_vm_stat_on_darwin(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(A, "_run_vm_stat", lambda cmd, **kw: completed(VM_STAT_16K))
    assert A.available_ram_bytes("darwin") == (11830 + 207330 + 3121) * 16384
    monkeypatch.setattr(sys, "platform", "darwin")
    assert A.available_ram_bytes() == (11830 + 207330 + 3121) * 16384


def test_darwin_falls_back_to_none_when_vm_stat_fails(monkeypatch: pytest.MonkeyPatch) -> None:
    def broken(cmd, **kw):  # type: ignore[no-untyped-def]
        raise FileNotFoundError("no vm_stat")

    monkeypatch.setattr(A, "_run_vm_stat", broken)
    assert A.available_ram_bytes("darwin") is None


@pytest.mark.skipif(sys.platform != "darwin", reason="only on macOS: it reads the real vm_stat")
def test_on_macos_the_real_value_is_a_positive_integer_below_total_ram() -> None:
    total = int(subprocess.check_output(["/usr/sbin/sysctl", "-n", "hw.memsize"], text=True))
    free = A.available_ram_bytes()
    assert isinstance(free, int) and 0 < free < total, (free, total)


# ------------------------------------------------------------------ the worker count
GB = 1024**3


@pytest.mark.parametrize("cpus", [2, 4, 8, 16, 64])
def test_unknown_free_memory_caps_the_pool_at_four_workers(cpus: int) -> None:
    n = A.worker_count(100, max_faces=40000, available_bytes=None, cpus=cpus, jobs=1)
    assert n == min(max(1, min(cpus - 1, 8)), A.UNKNOWN_RAM_MAX_WORKERS) <= 4


def test_the_unknown_cap_is_shared_between_jobs_and_never_below_one() -> None:
    caps = [
        A.worker_count(100, 40000, available_bytes=None, cpus=16, jobs=j) for j in (1, 2, 3, 4, 8)
    ]
    assert caps == [4, 2, 1, 1, 1]
    for j in (1, 2, 4, 8):
        assert A.worker_count(100, 0, available_bytes=None, cpus=16, jobs=j) * j <= 8


def test_the_unknown_cap_does_not_apply_when_memory_is_known() -> None:
    assert A.worker_count(100, max_faces=1000, available_bytes=64 * GB, cpus=16, jobs=1) == 8
    assert A.worker_count(100, max_faces=1000, available_bytes=GB, cpus=16, jobs=1) < 8


def test_the_unknown_cap_matches_the_split_limit() -> None:
    assert A.UNKNOWN_RAM_MAX_WORKERS == A.UNKNOWN_RAM_SPLIT_WORKERS == 4


def test_the_environment_override_still_wins(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("STEPSCRIBE_WORKERS", "6")
    assert A.worker_count(100, 40000, available_bytes=None, cpus=16, jobs=1) == 6
