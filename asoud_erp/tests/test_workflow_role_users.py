"""`_users_for_roles` on the in-memory fake site (PA-013 company scope, PA-030 order)."""
import importlib
import sys

import pytest

from asoud_erp.tests import _fake_site as fake

RELOADED = ["asoud_erp.api.v1.workflow_runtime", "asoud_erp.services.request_access",
            "asoud_erp.services.erp_documents", "asoud_erp.services.request_link_values"]


@pytest.fixture
def runtime(monkeypatch):
    site = fake.Site()
    frappe, utils = fake.install(site)
    utils.add_to_date = lambda value, **kwargs: value
    for name, module in {"frappe": frappe, "frappe.utils": utils}.items():
        monkeypatch.setitem(sys.modules, name, module)
    restore = fake.isolate(RELOADED)
    for user, company in [("b@x.com", "WP"), ("a@x.com", "WP"), ("c@x.com", "OTHER"), ("off@x.com", "WP")]:
        site.add("User", user, enabled=0 if user.startswith("off") else 1)
        site.add("Has Role", parent=user, parenttype="User", role="Manager")
        site.add("Employee", "E-" + user, user_id=user, company=company, status="Active")
    yield importlib.import_module("asoud_erp.api.v1.workflow_runtime"), site
    restore()


def test_roles_are_limited_to_users_of_the_workflow_company(runtime):
    module, _ = runtime
    # Old code returned every holder of the role, including the other company's user.
    assert "c@x.com" not in module._users_for_roles(["Manager"], "WP")
    assert module._users_for_roles(["Manager"], "OTHER") == ["c@x.com"]


def test_first_escalation_user_is_deterministic_whatever_the_row_order(runtime):
    module, site = runtime
    # PA-030: Has Role rows come back in modified-desc order; "b" was inserted first.
    first = module._users_for_roles(["Manager"], "WP")
    site.table("Has Role").update(dict(reversed(list(site.table("Has Role").items()))))
    assert module._users_for_roles(["Manager"], "WP") == first == ["a@x.com", "b@x.com"]
    assert module._users_for_roles(["Manager"]) == sorted(module._users_for_roles(["Manager"]))
