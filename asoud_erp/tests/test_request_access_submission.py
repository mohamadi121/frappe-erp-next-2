"""Pure regression: ``request_level`` excludes only the requester's own form submission.

The 11f852c fix must exclude the submitter completing the request's own form stage (P1),
but NOT a decision on that stage by another user (P3), and NOT a decision whose activity
row has no ``workflow_stage`` (e.g. a ``Reassigned`` row) — a SQL ``!=`` filter would drop
a NULL stage. These cases run ``request_level`` against the in-memory site.
"""

import importlib
import sys
import types

import pytest

from asoud_erp.tests import _fake_site as fake

RELOADED = ["asoud_erp.services.request_access", "asoud_erp.services.certificate_access"]

FORM = "STAGE-FORM"
APPROVAL = "STAGE-APPROVAL"


@pytest.fixture
def world(monkeypatch):
    site = fake.Site()
    frappe, utils = fake.install(site)
    for name, module in {"frappe": frappe, "frappe.utils": utils}.items():
        monkeypatch.setitem(sys.modules, name, module)
    restore = fake.isolate(RELOADED)
    access = importlib.import_module("asoud_erp.services.request_access")
    # A request in office WP, submitted by sara (started_by). Ownership has moved away
    # (as in the doctype test), so sara is no longer the owner and the level is decided by
    # the participant policy, not by ownership.
    site.add("ASOUD Workflow Request", "REQ-1", company="WP", owner="Administrator",
             workflow_instance="WFI-1", workflow_definition="DEF-1")
    site.add("ASOUD Workflow Instance", "WFI-1", started_by="sara@example.com")
    # The form stage is the first stage after Start; the approval stage is later.
    monkeypatch.setattr(access, "_form_stage_of", lambda doc: FORM)
    monkeypatch.setattr(access, "company_access", lambda company, user=None: True)
    site.user = "sara@example.com"
    yield types.SimpleNamespace(site=site, frappe=frappe, access=access)
    restore()


def _doc(world):
    return world.frappe.get_doc("ASOUD Workflow Request", "REQ-1")


def test_assignee_deciding_on_the_form_stage_is_masked(world):
    # A different user (the approver) decided on the first stage after Start (the form
    # stage). That is acting, not the requester's submission -> MASKED.
    world.site.add("ASOUD Workflow Activity", "ACT-1", workflow_instance="WFI-1",
                   actor="approver@example.com", action="Complete", workflow_stage=FORM)
    world.site.user = "approver@example.com"
    assert world.access.request_level(_doc(world)) == "MASKED"


def test_assignee_with_a_null_stage_decision_is_masked(world):
    # A Reassigned activity row has no workflow_stage (NULL). A SQL ``!=`` filter would drop
    # it; the Python filter must keep it, so the reassigned-away user who acted is MASKED.
    world.site.add("ASOUD Workflow Activity", "ACT-1", workflow_instance="WFI-1",
                   actor="approver@example.com", action="Reassigned")
    world.site.user = "approver@example.com"
    assert world.access.request_level(_doc(world)) == "MASKED"


def test_requester_own_form_submission_is_none(world):
    # The submitter (sara) completed their own form stage while submitting. With ownership
    # and the task moved away, that submission must not count as acting -> NONE.
    world.site.add("ASOUD Workflow Activity", "ACT-1", workflow_instance="WFI-1",
                   actor="sara@example.com", action="Complete", workflow_stage=FORM)
    world.site.user = "sara@example.com"
    assert world.access.request_level(_doc(world)) == "NONE"


def test_requester_acting_on_a_later_stage_is_masked(world):
    # The submitter acting on a later stage (an approval) is acting, not a submission.
    world.site.add("ASOUD Workflow Activity", "ACT-1", workflow_instance="WFI-1",
                   actor="sara@example.com", action="Approve", workflow_stage=APPROVAL)
    world.site.user = "sara@example.com"
    assert world.access.request_level(_doc(world)) == "MASKED"


def test_completed_form_task_by_the_submitter_is_not_acting(world):
    # The submitter's completed form task (their submission) is not acting; with no other
    # task or activity they are NONE.
    world.site.add("ASOUD Workflow Task", "T-1", workflow_instance="WFI-1",
                   assigned_to="sara@example.com", status="Completed", workflow_stage=FORM)
    world.site.user = "sara@example.com"
    assert world.access.request_level(_doc(world)) == "NONE"


def test_completed_form_task_by_another_user_is_acting(world):
    # A different user completing the form stage (the first stage after Start) is acting.
    world.site.add("ASOUD Workflow Task", "T-1", workflow_instance="WFI-1",
                   assigned_to="approver@example.com", status="Completed", workflow_stage=FORM)
    world.site.user = "approver@example.com"
    assert world.access.request_level(_doc(world)) == "MASKED"
