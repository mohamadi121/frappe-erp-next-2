# API and changed-file inventory

67 literal Flutter ASOUD API references checked against Python whitelisted definitions.
Missing literal endpoints: none

Static endpoint existence is not proof of payload or authorization compatibility. Dynamic dispatch and native Frappe calls were reviewed separately; runtime coverage is listed in the main audit.

## Current working trees

asoud-erp-backend
```
M .github/workflows/erpnext-v15-integration.yml
 M README.md
 M asoud_erp/api/v1/auth.py
 M asoud_erp/api/v1/hr.py
 M asoud_erp/api/v1/party.py
 M asoud_erp/api/v1/personnel.py
 M asoud_erp/api/v1/workflow.py
 M asoud_erp/api/v1/workflow_runtime.py
 M asoud_erp/asoud_erp/doctype/asoud_party_profile/asoud_party_profile.json
 M asoud_erp/asoud_erp/doctype/asoud_party_profile/asoud_party_profile.py
 M asoud_erp/asoud_erp/doctype/asoud_personnel_record/asoud_personnel_record.json
 M asoud_erp/hooks.py
 M asoud_erp/services/access_policy.py
 M asoud_erp/services/personnel_contract.py
 M asoud_erp/services/workflow_response.py
 M asoud_erp/tests/test_personnel.py
 M asoud_erp/tests/test_workflow_response.py
?? AGENTS.md
?? asoud_erp/api/v1/workflow_request.py
?? asoud_erp/asoud_erp/doctype/asoud_employee_invitation/
?? asoud_erp/asoud_erp/doctype/asoud_personnel_operation/
?? asoud_erp/asoud_erp/doctype/asoud_personnel_record/test_asoud_personnel_record.py
?? asoud_erp/asoud_erp/doctype/asoud_workflow_request/
?? asoud_erp/services/personnel_employee.py
?? asoud_erp/services/personnel_migration.py
?? asoud_erp/services/personnel_native.py
?? asoud_erp/services/private_file.py
?? asoud_erp/services/request_access.py
?? docs/audit-2026-09-19.md
?? docs/personnel-native-architecture.md
```

flutter-asoud-erp
```
M .gitignore
 M lib/features/dashboard/presentation/pages/dashboard_page.dart
 M lib/features/hr/data/personnel_repository.dart
 M lib/features/hr/domain/hr_models.dart
 M lib/features/hr/presentation/pages/hr_home_page.dart
 M lib/features/hr/presentation/pages/personnel_design.dart
 M lib/features/hr/presentation/pages/personnel_forms.dart
 M lib/features/hr/presentation/pages/personnel_page.dart
 M lib/features/parties/presentation/pages/personnel_roles_page.dart
 M lib/features/workflows/presentation/pages/workflow_stage_settings_page.dart
 M test/ui/goldens/personnel_detail_390.png
 M test/ui/goldens/personnel_form_open_390.png
 M test/ui/goldens/personnel_list_390.png
 M test/ui/goldens/personnel_personal_390.png
 M test/ui/goldens/personnel_record_detail_390.png
 M test/ui/goldens/personnel_records_390.png
 M test/ui/goldens/workflow_designer_390.png
 M test/ui/goldens/workflow_form_390.png
 M test/ui/goldens/workflow_list_390.png
 M test/ui/goldens/workflow_stage_picker_390.png
 M test/ui/party_pages_test.dart
 M test/ui/personnel_flows_test.dart
?? devtools_options.yaml
?? lib/features/workflows/data/generic_request_repository.dart
?? lib/features/workflows/presentation/pages/generic_request_page.dart
?? test/features/workflows/generic_request_form_test.dart
?? test/features/workflows/generic_request_repository_test.dart
```

## Literal endpoints
- `asoud_erp.api.v1.account.apply_chart_template`
- `asoud_erp.api.v1.account.create_account`
- `asoud_erp.api.v1.account.delete_account`
- `asoud_erp.api.v1.account.import_accounts`
- `asoud_erp.api.v1.account.list_accounts`
- `asoud_erp.api.v1.account.preview_chart_template`
- `asoud_erp.api.v1.account.update_account`
- `asoud_erp.api.v1.auth.current_user`
- `asoud_erp.api.v1.auth.delete_employee_access`
- `asoud_erp.api.v1.auth.get_employee_access`
- `asoud_erp.api.v1.auth.list_employee_invitations`
- `asoud_erp.api.v1.auth.send_employee_invitation`
- `asoud_erp.api.v1.auth.sync_employee_access`
- `asoud_erp.api.v1.detail_group.disable_detail_group`
- `asoud_erp.api.v1.detail_group.list_detail_groups`
- `asoud_erp.api.v1.detail_group.save_detail_group`
- `asoud_erp.api.v1.detail_group.seed_default_detail_groups`
- `asoud_erp.api.v1.floating_detail.create_floating_detail`
- `asoud_erp.api.v1.floating_detail.link_floating_detail`
- `asoud_erp.api.v1.floating_detail.list_floating_details`
- `asoud_erp.api.v1.floating_detail.preview_next_detail_code`
- `asoud_erp.api.v1.organization.get_chart`
- `asoud_erp.api.v1.organization.save_chart`
- `asoud_erp.api.v1.party.disable_party`
- `asoud_erp.api.v1.party.list_parties`
- `asoud_erp.api.v1.party.save_party`
- `asoud_erp.api.v1.purchase_request.create_purchase_request`
- `asoud_erp.api.v1.purchase_request.list_my_purchase_requests`
- `asoud_erp.api.v1.purchase_request.purchase_request_options`
- `asoud_erp.api.v1.report.general_ledger`
- `asoud_erp.api.v1.report.trial_balance`
- `asoud_erp.api.v1.setup.create_fiscal_year`
- `asoud_erp.api.v1.setup.get_account_code_settings`
- `asoud_erp.api.v1.setup.get_company_settings`
- `asoud_erp.api.v1.setup.get_setup_status`
- `asoud_erp.api.v1.setup.list_fiscal_years`
- `asoud_erp.api.v1.setup.save_office`
- `asoud_erp.api.v1.setup.set_default_office`
- `asoud_erp.api.v1.setup.update_account_code_settings`
- `asoud_erp.api.v1.setup.update_company_settings`
- `asoud_erp.api.v1.sync.execute_mutation`
- `asoud_erp.api.v1.voucher.approve_voucher`
- `asoud_erp.api.v1.voucher.list_vouchers`
- `asoud_erp.api.v1.voucher.reject_voucher`
- `asoud_erp.api.v1.voucher.save_voucher`
- `asoud_erp.api.v1.voucher.submit_for_approval`
- `asoud_erp.api.v1.workflow.add_condition_branch`
- `asoud_erp.api.v1.workflow.add_workflow_stage`
- `asoud_erp.api.v1.workflow.connect_workflow_stages`
- `asoud_erp.api.v1.workflow.create_workflow_draft`
- `asoud_erp.api.v1.workflow.get_workflow_design`
- `asoud_erp.api.v1.workflow.insert_workflow_stage`
- `asoud_erp.api.v1.workflow.list_workflows`
- `asoud_erp.api.v1.workflow.save_stage_settings`
- `asoud_erp.api.v1.workflow.save_start_settings`
- `asoud_erp.api.v1.workflow.update_stage_positions`
- `asoud_erp.api.v1.workflow.workflow_condition_fields`
- `asoud_erp.api.v1.workflow.workflow_form_options`
- `asoud_erp.api.v1.workflow_runtime.complete_workflow_task`
- `asoud_erp.api.v1.workflow_runtime.get_workflow_instance`
- `asoud_erp.api.v1.workflow_runtime.get_workflow_task`
- `asoud_erp.api.v1.workflow_runtime.list_my_workflow_instances`
- `asoud_erp.api.v1.workflow_runtime.list_my_workflow_notifications`
- `asoud_erp.api.v1.workflow_runtime.list_my_workflow_tasks`
- `asoud_erp.api.v1.workflow_runtime.mark_workflow_notification_read`
- `asoud_erp.api.v1.workflow_runtime.save_workflow_task_draft`
- `asoud_erp.api.v1.workflow_runtime.upload_workflow_attachment`
