"""Available memory on Linux: MemAvailable, capped by the cgroup limit; logic tests run on every OS."""

from __future__ import annotations

import sys

import pytest

from stepscribe import analysis as A

GB = 1024**3

MEMINFO = """\
MemTotal:       16384000 kB
MemFree:          812000 kB
MemAvailable:    8388608 kB
Buffers:          102400 kB
Cached:          7000000 kB
"""


def reader(files: dict[str, str]):  # type: ignore[no-untyped-def]
    return lambda path: files.get(path)


def test_meminfo_gives_mem_available_in_bytes() -> None:
    assert A.parse_meminfo(MEMINFO) == 8388608 * 1024 == 8 * GB


@pytest.mark.parametrize(
    "text",
    [
        "",
        "garbage",
        "MemAvailable: lots kB\n",
        "MemFree: 100 kB\n",
        "MemAvailable: -5 kB\n",
        "\x00\x01",
    ],
)
def test_odd_meminfo_is_none_and_never_raises(text: str) -> None:
    assert A.parse_meminfo(text) is None


def test_the_cgroup_limit_minus_use_is_what_is_left() -> None:
    assert A.parse_cgroup_free(str(2 * GB), str(GB // 2)) == GB * 3 // 2
    assert A.parse_cgroup_free(str(2 * GB) + "\n", str(3 * GB) + "\n") == 0  # over the limit
    for limit in ("max", "max\n", str(1 << 62), "0", "-1", "x", ""):
        assert A.parse_cgroup_free(limit, "100") is None, limit
    assert A.parse_cgroup_free(str(GB), "not a number") is None


V2 = ("/sys/fs/cgroup/memory.max", "/sys/fs/cgroup/memory.current")
V1 = ("/sys/fs/cgroup/memory/memory.limit_in_bytes", "/sys/fs/cgroup/memory/memory.usage_in_bytes")


def test_mem_available_is_used_when_there_is_no_cgroup_limit() -> None:
    files = {A.PROC_MEMINFO: MEMINFO, V2[0]: "max\n", V2[1]: "1000\n"}
    assert A.linux_available_bytes(reader(files)) == 8 * GB
    assert A.linux_available_bytes(reader({A.PROC_MEMINFO: MEMINFO})) == 8 * GB  # no cgroup files


def test_a_cgroup_v2_limit_caps_it() -> None:
    files = {A.PROC_MEMINFO: MEMINFO, V2[0]: f"{2 * GB}\n", V2[1]: f"{GB // 2}\n"}
    assert A.linux_available_bytes(reader(files)) == GB * 3 // 2


def test_a_cgroup_v1_limit_caps_it_and_a_huge_v1_number_means_no_limit() -> None:
    files = {A.PROC_MEMINFO: MEMINFO, V1[0]: f"{4 * GB}\n", V1[1]: f"{GB}\n"}
    assert A.linux_available_bytes(reader(files)) == 3 * GB
    files[V1[0]] = "9223372036854771712\n"  # what v1 prints when nothing is set
    assert A.linux_available_bytes(reader(files)) == 8 * GB


def test_a_limit_above_mem_available_changes_nothing() -> None:
    files = {A.PROC_MEMINFO: MEMINFO, V2[0]: f"{64 * GB}\n", V2[1]: "0\n"}
    assert A.linux_available_bytes(reader(files)) == 8 * GB


def test_no_meminfo_is_none_so_the_free_pages_are_used_as_before() -> None:
    assert A.linux_available_bytes(reader({})) is None
    assert A.linux_available_bytes(reader({A.PROC_MEMINFO: "garbage"})) is None


def test_available_ram_bytes_uses_it_on_linux_and_falls_back(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(A, "linux_available_bytes", lambda read=None: 5 * GB)
    assert A.available_ram_bytes("linux") == 5 * GB
    monkeypatch.setattr(A, "linux_available_bytes", lambda read=None: None)
    monkeypatch.setattr(
        "os.sysconf", lambda name: 1000 if name == "SC_AVPHYS_PAGES" else 4096, raising=False
    )
    if sys.platform != "win32":
        assert A.available_ram_bytes("linux") == 1000 * 4096


def test_the_pool_follows_the_new_figure_and_nothing_else_changed() -> None:
    # the rule is untouched: 0.6 x available / (budget x jobs); only the input is better on Linux
    assert A.worker_count(100, 1581, 2 * GB, cpus=16, jobs=1) == 2
    assert A.worker_count(100, 1581, 8 * GB, cpus=16, jobs=1) == 8


@pytest.mark.skipif(
    not sys.platform.startswith("linux"), reason="only on Linux: it reads the real /proc/meminfo"
)
def test_on_linux_the_real_value_is_a_positive_integer_below_total_memory() -> None:
    import os

    value = A.available_ram_bytes()
    total = os.sysconf("SC_PHYS_PAGES") * os.sysconf("SC_PAGE_SIZE")
    assert isinstance(value, int) and 0 < value <= total, (value, total)
