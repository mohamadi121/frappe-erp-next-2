from asoud_erp.services.delegation import (
    DELEGATE_ROLE,
    OFFICE_CREATOR_ROLE,
    escalation_violation,
)
from asoud_erp.services.system_admin import (
    LAST_ADMIN_MESSAGE,
    admin_change_violation,
    is_active_admin,
)


def test_admin_recognised_by_role_enabled_and_user_type_only():
    assert is_active_admin(enabled=1, roles=["System Manager", "Employee"])
    assert not is_active_admin(enabled=0, roles=["System Manager"])
    assert not is_active_admin(enabled=1, roles=["HR Manager"])
    assert not is_active_admin(enabled=1, roles=["System Manager"], user_type="Website User")


def test_last_named_admin_cannot_be_demoted_disabled_or_deleted():
    assert admin_change_violation(target="a@x", was_admin=True, will_be_admin=False,
                                  other_active_admins=[]) == LAST_ADMIN_MESSAGE
    # the built-in Administrator is not a replacement
    assert admin_change_violation(target="a@x", was_admin=True, will_be_admin=False,
                                  other_active_admins=["Administrator"]) == LAST_ADMIN_MESSAGE


def test_admin_can_be_demoted_when_a_replacement_exists_or_nothing_changes():
    assert admin_change_violation(target="a@x", was_admin=True, will_be_admin=False,
                                  other_active_admins=["b@x"]) is None
    assert admin_change_violation(target="a@x", was_admin=True, will_be_admin=True, other_active_admins=[]) is None
    assert admin_change_violation(target="a@x", was_admin=False, will_be_admin=False, other_active_admins=[]) is None
    assert admin_change_violation(target="Administrator", was_admin=True, will_be_admin=False,
                                  other_active_admins=[]) is None


def test_admin_may_grant_anything():
    assert escalation_violation(actor_is_admin=True, actor_roles=[], granted_roles=["System Manager"]) is None


def test_plain_user_cannot_grant_roles_at_all():
    assert escalation_violation(actor_is_admin=False, actor_roles=["HR Manager"], granted_roles=["Employee"])


def test_delegate_cannot_grant_what_it_does_not_hold():
    roles = [DELEGATE_ROLE, "Accounts User"]
    assert escalation_violation(actor_is_admin=False, actor_roles=roles, granted_roles=["Accounts User"]) is None
    msg = escalation_violation(actor_is_admin=False, actor_roles=roles, granted_roles=["Accounts Manager"])
    assert msg and "Accounts Manager" in msg


def test_delegate_can_never_grant_admin_or_delegation():
    roles = [DELEGATE_ROLE, "System Manager"]
    assert escalation_violation(actor_is_admin=False, actor_roles=roles, granted_roles=["System Manager"])
    assert escalation_violation(actor_is_admin=False, actor_roles=roles, granted_roles=[DELEGATE_ROLE])


def test_office_creator_grant_does_not_make_anyone_admin():
    # holding the create-office role is not the admin role and is not delegable beyond one's own holdings
    assert not is_active_admin(enabled=1, roles=[OFFICE_CREATOR_ROLE])
    roles = [DELEGATE_ROLE]
    assert escalation_violation(actor_is_admin=False, actor_roles=roles, granted_roles=[OFFICE_CREATOR_ROLE])


def test_office_scope_uses_roles_held_in_that_office():
    roles = [DELEGATE_ROLE, "Accounts User"]
    assert escalation_violation(actor_is_admin=False, actor_roles=roles, granted_roles=["Accounts User"],
                                actor_office_roles=set()) is not None
    assert escalation_violation(actor_is_admin=False, actor_roles=roles, granted_roles=["Accounts User"],
                                actor_office_roles={"Accounts User", DELEGATE_ROLE}) is None
