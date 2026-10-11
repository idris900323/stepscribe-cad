"""H3: the MCP server process stays small during a scripted session (no second analysis in it)."""

from __future__ import annotations

import inspect
import json
import subprocess
import sys
from pathlib import Path

import pytest

pytest.importorskip("psutil")

# Peak resident memory of the server process on mini_mobile_manipulator, measured on Windows
# 11 / Python 3.12 with this script: 330 MB (peak working set).  The bound leaves room for other platforms.
BOUND_MB = 600


def ru_maxrss_bytes(value: int, platform: str) -> int:
    """macOS reports ru_maxrss in bytes, Linux in kilobytes."""
    return value if platform == "darwin" else value * 1024


def test_peak_memory_units_per_platform() -> None:
    assert ru_maxrss_bytes(330_000_000, "darwin") == 330_000_000
    assert ru_maxrss_bytes(330_000, "linux") == 337_920_000


SESSION = (
    inspect.getsource(ru_maxrss_bytes)
    + r"""
import json, sys, time, tempfile, os
os.environ["STEPSCRIBE_CACHE"] = tempfile.mkdtemp()
import psutil
if __name__ == "__main__":
    def peak_mb():
        info = psutil.Process().memory_info()
        peak = getattr(info, "peak_wset", None)
        if peak is None:
            import resource
            peak = ru_maxrss_bytes(resource.getrusage(resource.RUSAGE_SELF).ru_maxrss, sys.platform)
        return round(peak / 1e6)
    stages = {}
    from stepscribe.mcp import tools
    stages["after_imports"] = peak_mb()
    path = sys.argv[1]
    started = json.loads(tools.start_analysis(path))
    while not json.loads(tools.get_job_status(started["job_id"]))["done"]:
        time.sleep(0.5)
    stages["after_job"] = peak_mb()
    tools.export_pack(started["job_id"])
    stages["after_export_pack"] = peak_mb()
    tools.get_overview(path); tools.get_part(path, "PRT001"); tools.list_holes(path)
    tools.get_relations(path); tools.find_parts(path, "plate"); tools.get_shopping_list(path)
    stages["after_report_tools"] = peak_mb()
    info = psutil.Process().memory_info()
    print("RESULT", json.dumps({"peak_mb": peak_mb(), "rss_mb": round(info.rss / 1e6), "stages": stages}))
"""
)


def test_scripted_mcp_session_keeps_the_server_process_small(step_files: dict[str, Path]) -> None:
    out = subprocess.run(
        [sys.executable, "-c", SESSION, str(step_files["mini_mobile_manipulator"])],
        capture_output=True,
        text=True,
        timeout=600,
        check=False,
    )
    line = next((ln for ln in out.stdout.splitlines() if ln.startswith("RESULT ")), None)
    assert line, out.stderr[-2000:]
    result = json.loads(line[7:])
    print("server process peak MB:", result)
    assert result["peak_mb"] < BOUND_MB, result
