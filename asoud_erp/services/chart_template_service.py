TEMPLATES = {
    "Iran Standard": (
        {"key": "1", "level": "Group", "title": "دارایی‌ها", "root_type": "Asset"},
        {"key": "11", "level": "General", "title": "دارایی‌های جاری", "parent_key": "1", "root_type": "Asset"},
        {"key": "1101", "level": "Ledger", "title": "موجودی نقد و بانک", "parent_key": "11", "root_type": "Asset"},
        {"key": "2", "level": "Group", "title": "بدهی‌ها", "root_type": "Liability"},
        {"key": "21", "level": "General", "title": "بدهی‌های جاری", "parent_key": "2", "root_type": "Liability"},
        {"key": "2101", "level": "Ledger", "title": "حساب‌های پرداختنی", "parent_key": "21", "root_type": "Liability"},
        {"key": "3", "level": "Group", "title": "حقوق مالکانه", "root_type": "Equity"},
        {"key": "4", "level": "Group", "title": "درآمدها", "root_type": "Income"},
        {"key": "5", "level": "Group", "title": "هزینه‌ها", "root_type": "Expense"},
    ),
}


def template_rows(template: str) -> list[dict]:
    if template not in TEMPLATES:
        raise ValueError("Chart template is not available")
    return [dict(row) for row in TEMPLATES[template]]
