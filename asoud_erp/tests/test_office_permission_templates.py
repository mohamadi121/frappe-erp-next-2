from asoud_erp.services.office_permission_templates import accountant_example


def test_accountant_uses_only_real_catalogue_and_never_advanced_rights():
    result = accountant_example([
        {'doctype': 'Journal Entry', 'actions': ['read', 'create', 'write', 'delete', 'submit']},
        {'doctype': 'Account', 'actions': ['read', 'write', 'delete']},
        {'doctype': 'Employee', 'actions': ['read', 'write']},
    ])
    assert result['grants'] == {'Journal Entry': ['create', 'read', 'write'], 'Account': ['read']}


def test_report_only_has_read_and_missing_resources_are_not_invented():
    result = accountant_example([{'doctype': 'Real Report', 'read_only_report': True, 'actions': ['read']}])
    assert result['grants'] == {'Real Report': ['read']}
    assert accountant_example([])['grants'] == {}
