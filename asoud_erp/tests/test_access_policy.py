from asoud_erp.services.access_policy import frappe_roles_for, normalize_asoud_roles


def test_legacy_labels_are_normalized_and_unknown_values_are_ignored() -> None:
    assert normalize_asoud_roles(["حسابدار", "فروشنده", "نامعتبر", "حسابدار"]) == [
        "accountant",
        "salesperson",
    ]


def test_role_mapping_is_deduplicated_and_allow_listed() -> None:
    assert frappe_roles_for(["accountant", "cashier", "salesperson"]) == [
        "Accounts User",
        "Sales User",
    ]


def test_balance_policy_is_not_treated_as_security_role() -> None:
    assert normalize_asoud_roles(["سیاست مانده:بدهکار"]) == []
