from asoud_erp.services.permission_catalog import (
    ADVANCED_ONLY,
    ASOUD_CAPABILITIES,
    MODULES,
    capabilities_for,
    catalog_rows,
    levels_for,
    validate_grant,
)


def test_advanced_differs_from_medium_regression():
    """Advanced used to show exactly the medium list."""
    levels = levels_for("Leave Application", is_submittable=True)
    assert levels["simple"] == ["read"]
    assert levels["medium"] == ["read", "create", "write", "delete"]
    assert levels["advanced"] != levels["medium"]
    assert set(levels["medium"]) < set(levels["advanced"])
    for action in ("submit", "cancel", "amend", "print", "export", "report", "share", "email", "import"):
        assert action in levels["advanced"]


def test_non_submittable_documents_offer_no_submit_actions():
    levels = levels_for("Department", is_submittable=False)
    assert not {"submit", "cancel", "amend"} & set(levels["advanced"])
    assert "print" in levels["advanced"]


def test_read_only_screens_stay_read_only_in_every_level():
    assert levels_for("User") == {"simple": ["read"], "medium": ["read"], "advanced": ["read"]}


def test_hr_module_lists_the_complete_set_of_operations():
    hr = dict(MODULES["منابع انسانی"])
    for doctype in ("Employee", "Leave Application", "Attendance", "Salary Slip", "Payroll Entry",
                    "Expense Claim", "Appraisal", "ASOUD Work Report", "ASOUD Internal Communication"):
        assert doctype in hr
    rows = catalog_rows(lambda dt: True, lambda dt: dt in {"Leave Application", "Salary Slip", "Payroll Entry"})
    leave = next(r for r in rows if r["doctype"] == "Leave Application")
    assert leave["actions"] == ["read", "create", "write", "delete"]
    assert {"submit", "cancel", "amend"} <= set(leave["advanced_actions"])
    dept = next(r for r in rows if r["doctype"] == "Department")
    assert not {"submit", "cancel", "amend"} & set(dept["advanced_actions"])
    assert all(set(ADVANCED_ONLY) >= set(r["advanced_actions"]) for r in rows)


def test_catalog_skips_doctypes_missing_on_the_site():
    rows = catalog_rows(lambda dt: dt != "Appraisal", lambda dt: False)
    assert "Appraisal" not in {r["doctype"] for r in rows}


def test_validate_grant():
    allowed = {"read", "create", "write", "delete"}
    assert validate_grant(["read", "write"], allowed) is None
    assert validate_grant([], allowed) is None
    assert validate_grant(["write"], allowed)  # needs read
    assert validate_grant(["read", "submit"], allowed)  # not offered
    assert validate_grant("read", allowed)


def test_admin_holds_every_capability_others_only_through_roles():
    assert all(c["granted"] for c in capabilities_for([], True))
    held = {c["key"] for c in capabilities_for(["ASOUD Office Creator"], False) if c["granted"]}
    assert held == {"offices.create"}
    assert len({c["key"] for c in ASOUD_CAPABILITIES}) == len(ASOUD_CAPABILITIES)
    create = next(c for c in capabilities_for(["Accounts Manager"], False) if c["key"] == "offices.create")
    manage = next(c for c in capabilities_for(["Accounts Manager"], False) if c["key"] == "offices.manage")
    assert not create["granted"] and manage["granted"]  # manage != create
