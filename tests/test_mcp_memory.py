"""H3: the MCP server process stays small during a scripted session (no second analysis in it)."""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

pytest.importorskip("psutil")

# Peak resident memory of the server process on mini_mobile_manipulator, measured on Windows
# 11 / Python 3.12 with this script: 330 MB (peak working set).  The bound leaves room for other platforms.
BOUND_MB = 600

SESSION = r"""
import json, sys, time, tempfile, os
os.environ["STEPSCRIBE_CACHE"] = tempfile.mkdtemp()
import psutil
if __name__ == "__main__":
    from stepscribe.mcp import tools
    path = sys.argv[1]
    started = json.loads(tools.start_analysis(path))
    while not json.loads(tools.get_job_status(started["job_id"]))["done"]:
        time.sleep(0.5)
    tools.export_pack(started["job_id"])
    tools.get_overview(path); tools.get_part(path, "PRT001"); tools.list_holes(path)
    tools.get_relations(path); tools.find_parts(path, "plate"); tools.get_shopping_list(path)
    p = psutil.Process()
    info = p.memory_info()
    peak = getattr(info, "peak_wset", None)
    if peak is None:
        import resource
        peak = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss * 1024
    print("RESULT", json.dumps({"peak_mb": round(peak / 1e6), "rss_mb": round(info.rss / 1e6)}))
"""


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
