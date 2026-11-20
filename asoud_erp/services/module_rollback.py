"""Read-only report for rolling back the module-key unification (PA-054).

The v0.18 patch ``normalize_module_keys`` rewrote the legacy workflow keys
(``Accounting``/``Sales``/``Inventory``/``Support``) to the canonical set
(``Finance``/``Selling``/``Stock``/``Admin``). Rolling back to code older than v0.18
requires the reverse map, but ``IT`` has no legacy key: a workflow stored under ``IT``
cannot be expressed by the old code at all. This helper is read-only and reports, per
module key, how many workflow definitions exist and which of them are ``IT`` (the ones
that block a sub-v0.18 rollback). It never writes.
"""

import frappe

from asoud_erp.services.modules import MODULE_KEYS

# The reverse of the v0.18 forward map, for the runbook. ``IT`` is intentionally absent:
# it has no legacy key, so it cannot be reverse-mapped.
REVERSE_MODULE_KEYS = {
    "Finance": "Accounting",
    "Selling": "Sales",
    "Stock": "Inventory",
    "Admin": "Support",
}


def rollback_report() -> dict:
    """Count workflow definitions per module key and list the ``IT`` ones.

    Returns ``{"counts": {key: n}, "it_definitions": [name, ...]}``. ``counts`` has an
    entry for every canonical key (zero when none) plus any unexpected stored key, so a
    stray value is surfaced rather than hidden. Read-only: a single ``get_all``.
    """
    rows = frappe.get_all("ASOUD Workflow Definition", fields=["name", "module_key"])
    counts: dict[str, int] = {key: 0 for key in MODULE_KEYS}
    it_definitions: list[str] = []
    for row in rows:
        key = row.get("module_key") or ""
        counts[key] = counts.get(key, 0) + 1
        if key == "IT":
            it_definitions.append(row["name"])
    return {"counts": counts, "it_definitions": it_definitions}
