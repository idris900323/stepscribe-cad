# Release checklist

Nothing is tagged, bumped or uploaded to PyPI until every line below is true.

1. `release/v2` is green on Ubuntu, Windows **and macOS** for Python 3.11, 3.12 and 3.13. Pull requests run
   Ubuntu and Windows only (macOS runners are slow); run the full matrix by hand:
   `gh workflow run ci.yml --ref release/v2`, then check every job (`test` and `robot`, nine each,
   and `isolated-build`).
2. The **final release pull request head** has the same green macOS run (`gh workflow run ci.yml --ref <its branch>`).
   A green run on `release/v2` alone is not enough: the head that is tagged is the head that was tested.
3. `python scripts/check_release.py` and `python scripts/check_skips.py junit.xml` pass; no test was skipped
   or weakened to get there.
4. The CHANGELOG lists every deliberate change and the schema file is regenerated.
5. Only then: version bump, tag, build, PyPI upload, each as its own approved step.
