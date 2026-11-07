"""Run offline tests while explicitly prohibiting installation-archive builds."""

from pathlib import Path
import sys
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))


def cases(suite):
    for item in suite:
        if isinstance(item,unittest.TestSuite):
            yield from cases(item)
        elif item.__class__.__module__ != "test_release":
            yield item


if __name__ == "__main__":
    with patch("tools.build_release.build",side_effect=AssertionError("Installation build prohibited by this runner")):
        suite=unittest.defaultTestLoader.discover(str(ROOT/"tests"))
        result=unittest.TextTestRunner(verbosity=1).run(unittest.TestSuite(cases(suite)))
    raise SystemExit(not result.wasSuccessful())
