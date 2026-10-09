"""Form field definitions of the three system request templates (CONTRACT 3.4 to 3.6).

Pure data, no ``frappe`` import: the same lists are checked against
``asoud_erp/tests/fixtures/system_templates.json`` by ``test_system_templates_fixture``.
The Flutter app keeps an identical copy, so edit both together and bump the
template ``version`` in the spec when a field changes.
"""

ATTACHMENT_EXTENSIONS = ["pdf", "jpg", "jpeg", "png", "xls", "xlsx", "doc", "docx"]
LEAVE_ATTACHMENT_EXTENSIONS = ["jpg", "jpeg", "png", "pdf", "docx"]

PURCHASE_FIELDS: list[dict] = [
    {"key": "request_number", "label": "شماره درخواست", "type": "Auto", "auto": "request_number"},
    {"key": "request_date", "label": "تاریخ درخواست", "type": "Auto", "auto": "request_date"},
    {"key": "requester", "label": "درخواست‌کننده", "type": "User", "required": True, "editable": False, "default_source": "session_user"},
    {"key": "org_unit", "label": "واحد درخواست‌کننده", "type": "Department", "required": True, "default_source": "employee_department"},
    {"key": "cost_center", "label": "مرکز هزینه", "type": "System Select", "source": "cost_center", "required_by_setting": "request_cost_center_required"},
    {"key": "project", "label": "پروژه", "type": "System Select", "source": "project"},
    {"key": "needed_date", "label": "تاریخ مورد نیاز", "type": "Date", "required": True, "min_date": "today"},
    {"key": "priority", "label": "اولویت", "type": "Choice", "required": True, "options": ["Normal", "High", "Urgent"], "option_labels": {"Normal": "عادی", "High": "مهم", "Urgent": "فوری"}, "widget": "segmented", "default_value": "Normal", "show_in_list": True},
    {"key": "reason", "label": "دلیل درخواست", "type": "Long Text", "required": True, "max_length": 2000},
    {"key": "items", "label": "اقلام", "type": "Item Table", "required": True, "row_options": {"item_scope": "purchase", "note": True, "attachment": True, "min_rows": 1, "max_rows": 100}},
]

SUPPLY_FIELDS: list[dict] = [
    {"key": "request_number", "label": "شماره درخواست", "type": "Auto", "auto": "request_number"},
    {"key": "request_date", "label": "تاریخ ثبت", "type": "Auto", "auto": "request_date"},
    {"key": "requester", "label": "درخواست‌کننده", "type": "User", "required": True, "editable": False, "default_source": "session_user"},
    {"key": "org_unit", "label": "واحد سازمانی", "type": "Department", "required": True, "default_source": "employee_department"},
    {"key": "delivery_location", "label": "محل تحویل", "type": "System Select", "source": "delivery_location", "required": True},
    {"key": "needed_date", "label": "تاریخ مورد نیاز", "type": "Date", "required": True, "min_date": "today"},
    {"key": "supply_method", "label": "روش تأمین پیشنهادی", "type": "Choice", "options": ["Warehouse", "Purchase", "Transfer", "Contract", "Unspecified"], "option_labels": {"Warehouse": "از انبار", "Purchase": "خرید", "Transfer": "انتقال", "Contract": "قرارداد", "Unspecified": "نامشخص"}, "widget": "chips", "default_value": "Unspecified"},
    {"key": "suggested_supplier", "label": "تأمین‌کننده پیشنهادی", "type": "System Select", "source": "supplier", "help_text": "فقط پیشنهاد است"},
    {"key": "priority", "label": "اولویت", "type": "Choice", "options": ["Normal", "High", "Urgent"], "option_labels": {"Normal": "عادی", "High": "مهم", "Urgent": "فوری"}, "widget": "segmented", "default_value": "Normal", "show_in_list": True},
    {"key": "reason", "label": "توضیحات / دلیل درخواست", "type": "Long Text", "max_length": 2000, "help_text": "توصیه می‌شود"},
    {"key": "items", "label": "کالا / خدمت", "type": "Item Table", "required": True, "row_options": {"item_scope": "all", "note": False, "attachment": True, "min_rows": 1, "max_rows": 100}},
]

LEAVE_FIELDS: list[dict] = [
    {"key": "request_number", "label": "شماره درخواست", "type": "Auto", "auto": "request_number"},
    {"key": "request_date", "label": "تاریخ ثبت", "type": "Auto", "auto": "request_date"},
    {"key": "requester", "label": "درخواست‌کننده", "type": "User", "required": True, "editable": False, "default_source": "session_user"},
    {"key": "org_unit", "label": "واحد سازمانی", "type": "Department", "required": True, "default_source": "employee_department"},
    {"key": "leave_type", "label": "نوع مرخصی", "type": "System Select", "source": "leave_type", "required": True},
    {"key": "request_kind", "label": "نوع درخواست", "type": "Choice", "required": True, "options": ["Daily", "Hourly"], "option_labels": {"Daily": "روزانه", "Hourly": "ساعتی"}, "widget": "segmented", "default_value": "Daily"},
    {"key": "start_date", "label": "تاریخ شروع", "type": "Date", "required": True, "visible_when": {"field": "request_kind", "equals": "Daily"}},
    {"key": "end_date", "label": "تاریخ پایان", "type": "Date", "required": True, "visible_when": {"field": "request_kind", "equals": "Daily"}},
    {"key": "leave_date", "label": "تاریخ مرخصی", "type": "Date", "required": True, "visible_when": {"field": "request_kind", "equals": "Hourly"}},
    {"key": "start_time", "label": "ساعت شروع", "type": "Time", "required": True, "visible_when": {"field": "request_kind", "equals": "Hourly"}},
    {"key": "end_time", "label": "ساعت پایان", "type": "Time", "required": True, "visible_when": {"field": "request_kind", "equals": "Hourly"}},
    {"key": "duration", "label": "مدت مرخصی", "type": "Auto", "auto": "leave_duration"},
    {"key": "location", "label": "محل خدمت", "type": "System Select", "source": "branch", "default_source": "employee_branch"},
    {"key": "reason", "label": "دلیل مرخصی", "type": "Long Text", "required": True, "max_length": 2000},
]

FIELDS_BY_KEY = {"purchase": PURCHASE_FIELDS, "supply": SUPPLY_FIELDS, "leave": LEAVE_FIELDS}
