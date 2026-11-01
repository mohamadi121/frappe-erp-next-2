import json
from copy import deepcopy

import pytest

from asoud_erp.services.security_audit import build_row
from asoud_erp.services.setup_reset_policy import completed_companies, workflow_reset_allowed


def capability():
    return dict(actor='admin', job='job', worker=True,
        receipt={'actor': 'admin', 'job': 'job', 'state': 'running', 'digest': 'verified'},
        scope={'actor': 'admin', 'job': 'job', 'digest': 'verified', 'companies': ('office',),
            'targets': {'ASOUD Workflow Definition': ('system-workflow',)}},
        name='system-workflow', company='office')


def test_only_exact_verified_worker_scope_allows_system_workflow_cleanup():
    args = capability()
    before = deepcopy(args)
    assert workflow_reset_allowed(**args)
    assert args == before


@pytest.mark.parametrize('change', [
    {'worker': False}, {'worker': 1}, {'scope': None}, {'receipt': None},
    {'job': 'another-job'}, {'actor': 'other-user'}, {'company': 'other-office'}, {'name': 'outside-workflow'},
    {'receipt': {'actor': 'admin', 'job': 'job', 'state': 'completed', 'digest': 'verified'}},
    {'receipt': {'actor': 'admin', 'job': 'job', 'state': 'running', 'digest': 'stale'}},
])
def test_ordinary_calls_and_stale_or_foreign_scope_never_bypass_deletion_guards(change):
    assert not workflow_reset_allowed(**{**capability(), **change})


def test_durable_scope_survives_audit_redaction_for_more_than_fifty_offices():
    companies = [f'office-{i}' for i in range(2000)]
    row = build_row(actor='admin', action='onboarding.reset.completed',
        details={'company_groups': [companies[i:i + 50] for i in range(0, len(companies), 50)]})
    assert completed_companies(json.loads(row['details'])) == companies
