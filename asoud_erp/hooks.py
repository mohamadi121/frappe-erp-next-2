app_name = "asoud_erp"
app_title = "ASOUD ERP"
app_publisher = "ASOUD"
app_description = "Iranian accounting extensions for ERPNext"
app_email = "dev@asoud.local"
app_license = "MIT"

required_apps = ["erpnext"]

after_install = "asoud_erp.install.after_install"
after_migrate = "asoud_erp.install.after_migrate"

fixtures = [
    {
        "dt": "Custom Field",
        "filters": [["module", "=", "ASOUD ERP"]],
    }
]

scheduler_events = {
    "hourly": ["asoud_erp.api.v1.workflow_runtime.process_workflow_deadlines"]
}
