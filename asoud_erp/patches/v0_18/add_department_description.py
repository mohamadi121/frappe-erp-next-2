"""Add native unit description metadata; idempotent, no data backfill or renames."""


def execute():
    from asoud_erp.services.organization_metadata import ensure_department_description

    ensure_department_description()
