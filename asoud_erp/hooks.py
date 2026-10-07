app_name = "asoud_erp"
app_title = "ASOUD ERP"
app_publisher = "ASOUD"
app_description = "Iranian accounting extensions for ERPNext"
app_email = "dev@asoud.local"
app_license = "MIT"

required_apps = ["erpnext", "hrms"]

doc_events = {
    "Employee": {"on_update": "asoud_erp.services.personnel_employee.refresh_profile_cache"},
    "User": {"validate": "asoud_erp.services.role_assignment.validate_role_profile_assignment"},
    "Company": {"after_insert": "asoud_erp.services.request_templates.seed.on_company_insert"},
    "ASOUD Workflow Instance": {"on_update": "asoud_erp.services.request_templates.lifecycle.on_instance_update"},
    "Leave Application": {"validate": "asoud_erp.services.leave_balance.validate_leave_application"},
}

after_install = "asoud_erp.install.after_install"
after_migrate = "asoud_erp.install.after_migrate"

fixtures = [
    {
        "dt": "Custom Field",
        "filters": [["module", "=", "ASOUD ERP"]],
    }
]

scheduler_events = {
    "cron": {"* * * * *": ["asoud_erp.services.automatic_action_runtime.dispatch"]},
    "hourly": ["asoud_erp.api.v1.workflow_runtime.process_workflow_deadlines"]
}

has_permission = {
    "ASOUD Action Execution": "asoud_erp.services.automatic_action_metadata.execution_permission",
    "ASOUD Workflow Request": "asoud_erp.services.request_access.request_permission",
    "File": "asoud_erp.services.request_access.file_permission",
    "ASOUD Workflow Instance": "asoud_erp.services.request_access.workflow_record_permission",
    "ASOUD Workflow Task": "asoud_erp.services.request_access.workflow_record_permission",
    "ASOUD Workflow Activity": "asoud_erp.services.request_access.workflow_record_permission",
}
permission_query_conditions = {
    "ASOUD Action Execution": "asoud_erp.services.automatic_action_metadata.execution_query",
    "ASOUD Workflow Request": "asoud_erp.services.request_access.request_query",
    "File": "asoud_erp.services.request_access.file_query",
    "ASOUD Workflow Instance": "asoud_erp.services.request_access.instance_query",
    "ASOUD Workflow Task": "asoud_erp.services.request_access.task_query",
    "ASOUD Workflow Activity": "asoud_erp.services.request_access.activity_query",
}

override_doctype_class = {"File": "asoud_erp.services.private_file.ASOUDPrivateFile"}
