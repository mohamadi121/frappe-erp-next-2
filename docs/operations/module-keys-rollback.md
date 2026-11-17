# Module-key rollback runbook (PA-054)

The v0.18 patch `asoud_erp/patches/v0_18/normalize_module_keys.py` rewrote the legacy
workflow module keys to the canonical set. This runbook is for rolling the **stored data**
back so that code older than v0.18 can read the workflows again. It is **non-destructive**:
it only rewrites the `module_key` column, and only after a full backup.

## Module key map

| Canonical (v0.18+) | Legacy (pre-v0.18) | Reverse (rollback) |
|---|---|---|
| `Finance` | `Accounting` | `Finance` → `Accounting` |
| `Selling` | `Sales` | `Selling` → `Sales` |
| `Stock` | `Inventory` | `Stock` → `Inventory` |
| `Admin` | `Support` | `Admin` → `Support` |
| `Purchase` | `Purchase` | unchanged |
| `HR` | `HR` | unchanged |
| `IT` | — (no legacy key) | **cannot be reverse-mapped** |

`Purchase` and `HR` use the same key in both vocabularies, so they need no change.

## Step 0 — backup first (mandatory)

Take a full database backup of the site before running any SQL. This is the only safe
undo: the reverse map is lossy for `IT` (below), so a broken rollback must be recoverable
from the backup, not from another SQL statement.

```
bench --site <site> backup
```

## Step 1 — detect IT workflows (blocks a sub-v0.18 rollback)

`IT` has **no legacy key**. Old code (pre-v0.18) has no `IT` option in its
`ASOUD Workflow Definition.module_key` Select, so a workflow stored under `IT` cannot be
expressed by it. While any `IT` workflow exists, rolling back below v0.18 is **blocked**.

List them with the read-only helper (no writes):

```python
from asoud_erp.services.module_rollback import rollback_report
report = rollback_report()
print(report['counts'])            # {'Finance': n, 'Purchase': n, ..., 'IT': n, ...}
print(report['it_definitions'])    # names of the IT workflow definitions
```

or directly:

```sql
SELECT name, workflow_title, module_key
FROM `tabASOUD Workflow Definition`
WHERE module_key = 'IT';
```

If `it_definitions` is non-empty, a human decision is required before any rollback:
either **export/archive** those workflows (e.g. record their design and deactivate them)
or keep the site on v0.18+. Do not delete them as part of the rollback.

## Step 2 — apply the reverse map (only after Step 1 is clear)

Run the reverse SQL **before starting the old code**, so the old code never sees a key it
does not know. Apply the four rewrites in one transaction:

```sql
START TRANSACTION;
UPDATE `tabASOUD Workflow Definition` SET module_key = 'Accounting' WHERE module_key = 'Finance';
UPDATE `tabASOUD Workflow Definition` SET module_key = 'Sales'      WHERE module_key = 'Selling';
UPDATE `tabASOUD Workflow Definition` SET module_key = 'Inventory'  WHERE module_key = 'Stock';
UPDATE `tabASOUD Workflow Definition` SET module_key = 'Support'    WHERE module_key = 'Admin';
COMMIT;
```

`Purchase` and `HR` rows are untouched. Verify the counts after the transaction:

```sql
SELECT module_key, COUNT(*) FROM `tabASOUD Workflow Definition` GROUP BY module_key;
```

## Alternative — full restore

Restoring the pre-upgrade backup is the other option. It is simpler but **loses every
change made after the upgrade** (new workflows, requests, documents, and any other data
written since). Use it only if the post-upgrade data is disposable or has been re-created.
Prefer the targeted reverse map above when the post-upgrade data must be kept.

## Label difference — needs owner approval

The `IT` module is labelled **«فناوری اطلاعات»** in app 0.30.0 but **«IT و تجهیزات»** in
the backend and in app 0.31.0 (`services/modules.py` `MODULE_LABELS`). This is a display
label, not a key, so it does not affect the rollback SQL. The final label is **not yet
approved by the owner** and must not be changed as part of this rollback.
