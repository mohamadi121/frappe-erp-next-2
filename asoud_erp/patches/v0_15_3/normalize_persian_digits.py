"""Convert Persian/Arabic-Indic digits already stored in identifier/number columns.

A column is read only when its table exists and the column is present, a row is
selected only when the value contains a Persian (۰-۹) or Arabic-Indic (٠-٩) digit,
and the row is rewritten only when the translated value actually differs. The patch
is therefore idempotent and never touches a row that already holds ASCII digits.

The columns mirror the write boundaries in ``api/v1/party.py``, ``api/v1/setup.py``
and ``api/v1/personnel.py``.
"""

import frappe

from asoud_erp.services.digits import (
    ARABIC_INDIC_DIGITS,
    PERSIAN_DIGITS,
    normalize_column_rows,
)

NUMERIC_COLUMNS = (
    ("ASOUD Party Profile", "national_id"),
    ("ASOUD Party Profile", "registration_number"),
    ("ASOUD Party Profile", "economic_code"),
    ("ASOUD Party Profile", "mobile"),
    ("ASOUD Party Profile", "phone"),
    ("ASOUD Party Profile", "secondary_phone"),
    ("ASOUD Party Profile", "postal_code"),
    ("ASOUD Party Profile", "iban"),
    ("ASOUD Party Profile", "account_number"),
    ("ASOUD Party Profile", "card_number"),
    ("ASOUD Party Profile", "birth_certificate_number"),
    ("ASOUD Company Setup", "national_id"),
    ("ASOUD Company Setup", "economic_code"),
    ("ASOUD Company Setup", "registration_number"),
    ("ASOUD Company Setup", "postal_code"),
    ("ASOUD Company Setup", "phone"),
    ("ASOUD Company Setup", "fiscal_year"),
    ("ASOUD Personnel Record", "document_number"),
    ("Employee", "cell_number"),
    ("Employee", "emergency_phone_number"),
    ("Employee", "employee_number"),
    ("Employee", "attendance_device_id"),
)

_DIGIT_PATTERN = f"[{PERSIAN_DIGITS}{ARABIC_INDIC_DIGITS}]"


def execute() -> None:
    for doctype, field in NUMERIC_COLUMNS:
        if not frappe.db.exists("DocType", doctype):
            continue
        if field not in frappe.db.get_table_columns(doctype):
            continue
        table = f"tab{doctype}"
        rows = frappe.db.sql(
            f"SELECT name, `{field}` AS value FROM `{table}` WHERE `{field}` REGEXP %s",
            (_DIGIT_PATTERN,),
            as_dict=True,
        )
        for name, normalized in normalize_column_rows(rows, "value"):
            frappe.db.sql(
                f"UPDATE `{table}` SET `{field}`=%s WHERE name=%s AND `{field}` REGEXP %s",
                (normalized, name, _DIGIT_PATTERN),
            )
