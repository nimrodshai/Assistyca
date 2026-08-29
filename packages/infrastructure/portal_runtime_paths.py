from __future__ import annotations

import os
from pathlib import Path

from packages.infrastructure.portal_db import DEFAULT_DB_PATH


DEFAULT_BILLING_DATA_PATH = Path("portal/billing.sample.json")
DEFAULT_PORTAL_WHATSAPP_STORE_DIR = "portal-whatsapp"
DEFAULT_PORTAL_AGENT_OUTPUT_DIR = "agent-receipts"


def resolve_runtime_path(path: str | Path, *, root: Path | None = None) -> Path:
    resolved = path if isinstance(path, Path) else Path(str(path).strip() or ".")
    if resolved.is_absolute():
        return resolved
    base = root.resolve() if root is not None else Path.cwd()
    return base / resolved


def resolve_portal_db_path(*, root: Path | None = None) -> Path:
    raw_path = os.getenv("PORTAL_DB_PATH", str(DEFAULT_DB_PATH)).strip() or str(DEFAULT_DB_PATH)
    return resolve_runtime_path(raw_path, root=root)


def resolve_portal_billing_data_path(*, root: Path | None = None) -> Path:
    raw_path = os.getenv("PORTAL_BILLING_DATA_PATH", str(DEFAULT_BILLING_DATA_PATH)).strip() or str(DEFAULT_BILLING_DATA_PATH)
    return resolve_runtime_path(raw_path, root=root)


def resolve_portal_data_root(*, root: Path | None = None, db_path: Path | None = None) -> Path:
    configured = os.getenv("PORTAL_DATA_ROOT", "").strip()
    if configured:
        return resolve_runtime_path(configured, root=root)
    resolved_db_path = (
        resolve_runtime_path(db_path, root=root) if db_path is not None else resolve_portal_db_path(root=root)
    )
    return resolved_db_path.parent


def resolve_portal_whatsapp_store_root(*, root: Path | None = None, db_path: Path | None = None) -> Path:
    configured = os.getenv("PORTAL_WHATSAPP_STORE_ROOT", "").strip()
    if configured:
        return resolve_runtime_path(configured, root=root)
    return resolve_portal_data_root(root=root, db_path=db_path) / DEFAULT_PORTAL_WHATSAPP_STORE_DIR


# Receipt bundles are files the portal generated for a customer, so they belong
# beside the database on the persistent disk. Keeping them under the repository
# would put them on the container filesystem, which is wiped on every restart
# and deploy, and the folder a customer opened yesterday would read as empty.
def resolve_portal_agent_output_root(*, root: Path | None = None, db_path: Path | None = None) -> Path:
    configured = os.getenv("PORTAL_AGENT_OUTPUT_DIR", "").strip()
    if configured:
        return resolve_runtime_path(configured, root=root)
    return resolve_portal_data_root(root=root, db_path=db_path) / DEFAULT_PORTAL_AGENT_OUTPUT_DIR
