"""research/check4 imports run 2's frozen code (B5_FROZEN) under the same module names as this tree's research
modules, so collecting both in one pytest process would make one shadow the other. A directory-wide run skips
check4; run it on its own: `B5_FROZEN=<a4a07d7 checkout> python3 -m pytest -q research/check4`."""
from pathlib import Path

import pytest

CHECK4 = Path(__file__).resolve().parent / "check4"


def _targets_check4(config) -> list[bool]:
    return [CHECK4 in (Path(a.split("::")[0]).resolve(), *Path(a.split("::")[0]).resolve().parents)
            for a in config.args]


def pytest_configure(config):
    t = _targets_check4(config)
    if any(t) and not all(t):
        raise pytest.UsageError("run research/check4 on its own (it imports the frozen run-2 modules)")


def pytest_ignore_collect(collection_path, config):
    if not any(_targets_check4(config)) and CHECK4 in (collection_path, *collection_path.parents):
        return True
    return None
