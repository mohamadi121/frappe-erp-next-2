"""Rewrite legacy workflow module keys to the canonical vocabulary.

The workflow engine used ``Accounting``/``Sales``/``Inventory``/``Support`` while
the document templates used ``Finance``/``Selling``/``Stock``/``Admin``. The
canonical keys are the template set; this patch rewrites stored legacy keys so
both subsystems agree. Idempotent: only known legacy values are touched.
"""

import frappe

from asoud_erp.services.modules import LEGACY_MODULE_KEYS


def execute() -> None:
    for legacy, canonical in LEGACY_MODULE_KEYS.items():
        frappe.db.sql(
            "UPDATE `tabASOUD Workflow Definition` SET `module_key` = %s WHERE `module_key` = %s",
            (canonical, legacy),
        )
