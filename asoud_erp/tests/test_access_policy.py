from asoud_erp.services.access_policy import access_level_for, frappe_roles_for, normalize_asoud_roles


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


def test_access_level_follows_the_native_roles_a_user_holds() -> None:
    assert access_level_for(["HR Manager", "Employee"]) == "manager"
    assert access_level_for(["System Manager"]) == "manager"
    assert access_level_for(["Accounts User", "Employee"]) == "user"
    assert access_level_for(["Employee"]) == "user"
    assert access_level_for([]) == "none"
    assert access_level_for(None) == "none"
