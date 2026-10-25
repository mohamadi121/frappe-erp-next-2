from asoud_erp.services.office_access import merge_roles, offices_of, roles_by_office

ROWS = [{"company": "A", "role_definition": "FIN"}, {"company": "B", "role_definition": "MGR"},
        {"company": "A", "role_definition": "MGR"}]
BASE = {"FIN": ["Accounts User"], "MGR": ["Accounts Manager", "Sales Manager"]}


def test_same_account_has_different_roles_per_office_and_none_in_a_third():
    by_office = roles_by_office(ROWS, lambda code: BASE[code])
    assert by_office["A"] == ["Accounts Manager", "Accounts User", "Sales Manager"]
    assert by_office["B"] == ["Accounts Manager", "Sales Manager"]
    assert "C" not in by_office
    assert merge_roles(["Employee"], by_office.get("C")) == {"Employee"}
    assert "Accounts User" in merge_roles(["Employee"], by_office["A"])
    assert "Accounts User" not in merge_roles(["Employee"], by_office["B"])


def test_offices_keep_order_without_duplicates():
    assert offices_of(ROWS) == ["A", "B"]
