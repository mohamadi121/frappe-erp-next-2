#!/usr/bin/env python3
"""Regenerate ``docs/api/manifest.json`` from the ``api/v1`` source and the registry.

Run from the repository root:

    PYTHONPATH=. python3 scripts/gen_api_manifest.py

The committed file is checked by the stale-manifest guard test
(``asoud_erp/tests/test_api_manifest_builder.py``); if it drifts from a fresh build
that test fails and tells you to run this script.
"""

from __future__ import annotations

import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

from asoud_erp.services import api_manifest  # noqa: E402

API_DIR = REPO_ROOT / "asoud_erp" / "api" / "v1"
OUT = REPO_ROOT / "docs" / "api" / "manifest.json"


def main() -> int:
    manifest = api_manifest.build_from_dir(API_DIR)
    OUT.write_text(api_manifest.manifest_to_json(manifest), encoding="utf-8")
    print(f"wrote {OUT.relative_to(REPO_ROOT)} ({manifest['method_count']} methods)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
