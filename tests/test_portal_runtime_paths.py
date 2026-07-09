from __future__ import annotations

import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from packages.infrastructure.portal_runtime_paths import resolve_portal_db_path
from packages.infrastructure.portal_runtime_paths import resolve_portal_whatsapp_store_root


class PortalRuntimePathTests(unittest.TestCase):
    def test_resolve_portal_db_path_uses_repo_root_for_relative_override(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            with patch.dict(os.environ, {"PORTAL_DB_PATH": "runtime/portal.db"}, clear=False):
                resolved = resolve_portal_db_path(root=root)

        self.assertEqual(resolved, root.resolve() / "runtime" / "portal.db")

    def test_whatsapp_store_defaults_to_db_parent(self) -> None:
        db_path = Path("/var/data/portal.db")

        resolved = resolve_portal_whatsapp_store_root(db_path=db_path)

        self.assertEqual(resolved, Path("/var/data/portal-whatsapp"))

    def test_whatsapp_store_resolves_relative_db_path_from_root(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)

            resolved = resolve_portal_whatsapp_store_root(root=root, db_path=Path("runtime/portal.db"))

        self.assertEqual(resolved, root.resolve() / "runtime" / "portal-whatsapp")

    def test_whatsapp_store_prefers_explicit_override(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            with patch.dict(os.environ, {"PORTAL_WHATSAPP_STORE_ROOT": "runtime/whatsapp"}, clear=False):
                resolved = resolve_portal_whatsapp_store_root(root=root)

        self.assertEqual(resolved, root.resolve() / "runtime" / "whatsapp")


if __name__ == "__main__":
    unittest.main()
