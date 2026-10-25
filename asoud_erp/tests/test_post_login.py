
from asoud_erp.services.post_login import (
    NO_OFFICE_MESSAGE,
    resolve_next_route,
)

BASE = dict(active=True, must_change_password=False, is_system_admin=False, first_office_exists=True,
            admin_profile_complete=True, office_ids=["A"], selected_office=None)


def route(**over):
    return resolve_next_route(**{**BASE, **over})


def test_admin_without_office_gets_first_office_form():
    assert route(is_system_admin=True, first_office_exists=False, office_ids=[])["route"] == "create-first-office"


def test_admin_with_office_but_incomplete_profile():
    assert route(is_system_admin=True, admin_profile_complete=False)["route"] == "complete-admin-profile"


def test_temporary_password_comes_before_everything():
    for admin in (True, False):
        assert route(is_system_admin=admin, must_change_password=True, first_office_exists=False)["route"] == "change-password"


def test_complete_admin_with_one_office_goes_home():
    result = route(is_system_admin=True)
    assert result == {"route": "home", "office": "A", "message": None}


def test_non_admin_never_sees_first_office_or_admin_profile():
    for exists in (True, False):
        for complete in (True, False):
            r = route(first_office_exists=exists, admin_profile_complete=complete, office_ids=[])
            assert r["route"] == "no-office" and r["message"] == NO_OFFICE_MESSAGE
            r = route(first_office_exists=exists, admin_profile_complete=complete)
            assert r["route"] == "home"


def test_multi_office_restores_valid_selection_else_asks():
    assert route(office_ids=["A", "B"], selected_office="B") == {"route": "home", "office": "B", "message": None}
    assert route(office_ids=["A", "B"], selected_office="Z")["route"] == "office-select"
    assert route(office_ids=["A", "B"])["route"] == "office-select"


def test_disabled_account():
    assert route(active=False)["route"] == "account-disabled"


def test_admin_with_no_accessible_office_after_setup():
    assert route(is_system_admin=True, office_ids=[])["route"] == "no-office"
