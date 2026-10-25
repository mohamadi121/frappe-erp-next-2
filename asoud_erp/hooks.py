app_name = "asoud_erp"
app_title = "ASOUD ERP"
app_publisher = "ASOUD"
app_description = "Iranian accounting extensions for ERPNext"
app_email = "dev@asoud.local"
app_license = "MIT"

required_apps = ["erpnext", "hrms"]

doc_events = {
    "*": {
        "validate": "asoud_erp.services.directive_access.guard_write",
        "on_trash": "asoud_erp.services.directive_access.guard_write",
    },
    "Employee": {"on_update": "asoud_erp.services.personnel_employee.refresh_profile_cache"},
    "Department": {
        "validate": "asoud_erp.services.organization_units.guard_department",
        "on_trash": "asoud_erp.services.organization_units.guard_department",
        "before_rename": "asoud_erp.services.organization_units.guard_rename",
    },
    "User": {
        "validate": [
            "asoud_erp.services.role_assignment.validate_role_profile_assignment",
            "asoud_erp.api.v1.user_access.attach_roles",
            # last: it judges the final role list after the role profile has been applied
            "asoud_erp.services.system_admin.guard_user_change",
        ],
        "on_update": "asoud_erp.services.user_audit.on_user_update",
        "on_trash": "asoud_erp.services.system_admin.guard_user_trash",
    },
    "ASOUD Role Definition": {"on_update": "asoud_erp.services.user_audit.on_role_definition_update"},
    "Activity Log": {"after_insert": "asoud_erp.services.user_audit.mirror_activity_log"},
    "Company": {"after_insert": "asoud_erp.services.request_templates.seed.on_company_insert"},
    "ASOUD Workflow Instance": {"on_update": "asoud_erp.services.request_templates.lifecycle.on_instance_update"},
    "Asset Movement": {"on_cancel": "asoud_erp.services.request_followup_runtime.cancel_open_tasks",
                       "on_trash": "asoud_erp.services.request_followup_runtime.cancel_open_tasks"},
    "Leave Application": {"validate": "asoud_erp.services.leave_balance.validate_leave_application"},
}

before_request = ["asoud_erp.services.session_guard.enforce_password_change"]
on_login = ["asoud_erp.services.session_guard.on_login"]

after_install = "asoud_erp.install.after_install"
after_migrate = "asoud_erp.install.after_migrate"

fixtures = [
    {
        "dt": "Custom Field",
        "filters": [["module", "=", "ASOUD ERP"]],
    }
]

scheduler_events = {
    "daily": ["asoud_erp.api.v1.calendar.refresh_official_holidays"],
    "cron": {"* * * * *": ["asoud_erp.services.automatic_action_runtime.dispatch",
                            "asoud_erp.api.v1.calendar.dispatch_reminders",
                            "asoud_erp.api.v1.directives.dispatch_reminders"]},
    "hourly": ["asoud_erp.api.v1.workflow_runtime.process_workflow_deadlines"]
}

has_permission = {
    "ASOUD Internal Communication": "asoud_erp.services.directive_access.communication_permission",
    "ASOUD Action Execution": "asoud_erp.services.automatic_action_metadata.execution_permission",
    "ASOUD Workflow Request": "asoud_erp.services.request_access.request_permission",
    "File": "asoud_erp.services.request_access.file_permission",
    "ASOUD Workflow Instance": "asoud_erp.services.request_access.workflow_record_permission",
    "ASOUD Workflow Task": "asoud_erp.services.request_access.workflow_record_permission",
    "ASOUD Workflow Activity": "asoud_erp.services.request_access.workflow_record_permission",
}
permission_query_conditions = {
    "ASOUD Internal Communication": "asoud_erp.services.directive_access.communication_query",
    "ASOUD Action Execution": "asoud_erp.services.automatic_action_metadata.execution_query",
    "ASOUD Workflow Request": "asoud_erp.services.request_access.request_query",
    "File": "asoud_erp.services.request_access.file_query",
    "ASOUD Workflow Instance": "asoud_erp.services.request_access.instance_query",
    "ASOUD Workflow Task": "asoud_erp.services.request_access.task_query",
    "ASOUD Workflow Activity": "asoud_erp.services.request_access.activity_query",
}

override_doctype_class = {"File": "asoud_erp.services.private_file.ASOUDPrivateFile"}
