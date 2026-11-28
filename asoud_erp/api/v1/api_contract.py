"""Machine-readable contract of the ``api/v1`` surface.

Read-only discovery for any signed-in user: it lists the methods, their
classification and parameters — never any business data. The manifest is derived
from the source AST and the classification registry (``services/api_manifest.py``),
so it is the same artifact the committed ``docs/api/manifest.json`` and the
stale-manifest guard test are built from.
"""

from pathlib import Path

import frappe
from frappe import _

from asoud_erp.api.v1.responses import success
from asoud_erp.services import api_manifest

_API_DIR = Path(__file__).resolve().parent


@frappe.whitelist()
def manifest() -> dict:
    """The read/write classification and parameter schema of every public method."""
    if frappe.session.user == "Guest":
        frappe.throw(_("Authentication is required"), frappe.AuthenticationError)
    return success(api_manifest.build_from_dir(_API_DIR))
