"""Pure rules for the role-completion state shown on the «مشاهده و تکمیل نقش‌ها» page.

A non-system role is "incomplete" only when BOTH are true:
  (1) its Role Profile has no base roles, and
  (2) its role-wide native role has no Custom DocPerm row with read at permlevel 0.
System roles are always "complete". Per-user access assignments never count.
"""

from asoud_erp.services.role_completion import completion, summary


def test_system_role_is_complete_even_with_nothing():
    assert completion([], True, 0) == "complete"
    assert completion(["System Manager"], True, 0) == "complete"


def test_non_system_without_base_roles_and_no_grant_is_incomplete():
    assert completion([], False, 0) == "incomplete"


def test_non_system_without_base_roles_but_with_role_grant_is_complete():
    assert completion([], False, 2) == "complete"


def test_non_system_with_base_roles_is_complete_regardless_of_grants():
    assert completion(["HR User"], False, 0) == "complete"
    assert completion(["HR User"], False, 3) == "complete"


def test_summary_empty_lists():
    assert summary([], []) == {"roles": 0, "categories": 0, "incomplete": 0, "uncategorized": 0}


def test_summary_counts_only_managed_non_system_roles():
    roles = [
        {"system": False, "completion": "complete", "category": "HR"},
        {"system": True, "completion": "complete", "category": "SYSTEM"},
    ]
    categories = [{"code": "HR"}, {"code": "SYSTEM"}]
    assert summary(roles, categories) == {"roles": 1, "categories": 2, "incomplete": 0, "uncategorized": 0}


def test_summary_counts_incomplete_from_the_row_value():
    # summary trusts the precomputed "completion"; it does not recompute from base_roles.
    roles = [
        {"system": False, "completion": "incomplete", "category": "HR"},
        {"system": False, "completion": "complete", "category": "HR"},
    ]
    assert summary(roles, [{"code": "HR"}])["incomplete"] == 1


def test_summary_uncategorized_empty_or_unknown_category():
    roles = [
        {"system": False, "completion": "complete", "category": ""},
        {"system": False, "completion": "complete", "category": "GONE"},
        {"system": False, "completion": "complete", "category": "HR"},
    ]
    assert summary(roles, [{"code": "HR"}])["uncategorized"] == 2


def test_summary_duplicate_categories_not_double_counted():
    categories = [{"code": "HR"}, {"code": "HR"}, {"code": "SALES"}]
    assert summary([], categories)["categories"] == 2
