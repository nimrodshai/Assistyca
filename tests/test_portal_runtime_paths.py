from __future__ import annotations

import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from packages.infrastructure.portal_runtime_paths import resolve_portal_agent_output_root
from packages.infrastructure.portal_runtime_paths import resolve_portal_db_path


class PortalRuntimePathTests(unittest.TestCase):
    def test_resolve_portal_db_path_uses_repo_root_for_relative_override(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            with patch.dict(os.environ, {"PORTAL_DB_PATH": "runtime/portal.db"}, clear=False):
                resolved = resolve_portal_db_path(root=root)

        self.assertEqual(resolved, root.resolve() / "runtime" / "portal.db")

    def test_agent_output_defaults_to_db_parent(self) -> None:
        db_path = Path("/var/data/portal.db")

        with patch.dict(os.environ, {}, clear=False):
            os.environ.pop("PORTAL_AGENT_OUTPUT_DIR", None)
            os.environ.pop("PORTAL_DATA_ROOT", None)
            resolved = resolve_portal_agent_output_root(db_path=db_path)

        self.assertEqual(resolved, Path("/var/data/agent-receipts"))

    def test_agent_output_prefers_explicit_override(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            with patch.dict(os.environ, {"PORTAL_AGENT_OUTPUT_DIR": "runtime/receipts"}, clear=False):
                resolved = resolve_portal_agent_output_root(root=root)

        self.assertEqual(resolved, root.resolve() / "runtime" / "receipts")


if __name__ == "__main__":
    unittest.main()
