"""Run the portal's JavaScript tests alongside the Python ones.

The portal's behaviour has been pinned by asserting that certain text appears
in app.js. That cannot catch a function returning the wrong rows, which is what
both mailbox bugs were, and it goes red on edits that changed nothing. The
decisions those bugs lived in are pure, so node can run them; this keeps that
suite inside `python3 -m unittest discover` rather than in a second command
nobody remembers.
"""

from __future__ import annotations

import shutil
import subprocess
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
JS_TEST_FILES = ("connection_identity.test.mjs",)


class ConnectionIdentityJavaScriptTests(unittest.TestCase):
    def test_the_portal_javascript_tests_pass(self) -> None:
        node = shutil.which("node")
        if node is None:
            self.skipTest("node is not installed; the portal's JavaScript tests need it")

        result = subprocess.run(
            [node, "--test", *(str(REPO_ROOT / "tests" / name) for name in JS_TEST_FILES)],
            cwd=REPO_ROOT,
            capture_output=True,
            text=True,
            timeout=120,
        )
        # node --test reports which case failed and why; surfacing its own
        # output is more useful than any assertion message written here.
        self.assertEqual(
            result.returncode,
            0,
            f"portal JavaScript tests failed:\n{result.stdout}\n{result.stderr}",
        )


if __name__ == "__main__":
    unittest.main()
