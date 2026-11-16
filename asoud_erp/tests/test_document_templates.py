import pytest

from asoud_erp.services.document_templates import (
    MODULES,
    PRESETS,
    build_document,
    document_type,
    normalize_template,
    render_placeholders,
    resolve_values,
)

JOURNAL = {
    "title": "سند هزینه خرید",
    "module": "Finance",
    "document_type": "Journal Entry",
    "mapping": {
        "posting_date": {"source": "system", "value": "today"},
        "title": {"source": "fixed", "value": "هزینه خرید بر اساس درخواست {{RequestNo}}"},
        "amount": {"source": "request", "value": "total"},
        "debit_account": {"source": "fixed", "value": "Expenses - T"},
        "credit_account": {"source": "fixed", "value": "Creditors - T"},
    },
}
CONTEXT = {
    "request": {"total": 1250000, "subject": "خرید لپ‌تاپ", "items": [{"item_code": "LAP", "qty": 2, "uom": "Nos"}]},
    "user": {"initiator": "a@example.com", "initiator_name": "محمد رضایی"},
    "organization": {"company": "Taban", "cost_center": "Main - T"},
    "system": {"today": "2026-09-25", "request_number": "PR-1403-025", "instance": "WF-1"},
}


def test_journal_template_is_normalized_with_draft_defaults():
    result = normalize_template(JOURNAL, {"total": "Currency"})
    assert result["document_type"] == "Journal Entry"
    assert result["create_as_draft"] is True and result["auto_submit"] is False
    assert result["reusable"] is True
    assert set(result["mapping"]) == set(JOURNAL["mapping"])


def test_auto_submit_turns_off_draft():
    result = normalize_template({**JOURNAL, "auto_submit": True, "create_as_draft": True}, None)
    assert result["auto_submit"] is True and result["create_as_draft"] is False


@pytest.mark.parametrize(
    "change, message",
    [
        ({"title": "x"}, "title"),
        ({"module": "Purchase"}, "Unsupported"),
        ({"document_type": "Receipt"}, "not available"),
        ({"mapping": {**JOURNAL["mapping"], "cheque_no": {"source": "fixed", "value": "1"}}}, "Unknown"),
        ({"mapping": {k: v for k, v in JOURNAL["mapping"].items() if k != "debit_account"}}, "not mapped"),
        ({"mapping": {**JOURNAL["mapping"], "amount": {"source": "fixed", "value": "-5"}}}, "positive"),
        ({"mapping": {**JOURNAL["mapping"], "amount": {"source": "request", "value": "note"}}}, "type"),
        ({"mapping": {**JOURNAL["mapping"], "amount": {"source": "request", "value": "missing"}}}, "exist"),
        ({"mapping": {**JOURNAL["mapping"], "title": {"source": "system", "value": "secret"}}}, "system"),
        ({"mapping": {**JOURNAL["mapping"], "title": {"source": "shell", "value": "x"}}}, "source"),
    ],
)
def test_invalid_templates_are_rejected(change, message):
    with pytest.raises(ValueError, match=message):
        normalize_template({**JOURNAL, **change}, {"total": "Currency", "note": "Long Text"})


def test_items_must_come_from_a_request_item_table():
    template = {
        "title": "درخواست کالا",
        "module": "Purchase",
        "document_type": "Material Request",
        "mapping": {
            "transaction_date": {"source": "system", "value": "today"},
            "schedule_date": {"source": "request", "value": "needed_by"},
            "items": {"source": "fixed", "value": "LAP"},
        },
    }
    with pytest.raises(ValueError, match="item table"):
        normalize_template(template, {"needed_by": "Date", "items": "Item Table"})
    template["mapping"]["items"] = {"source": "request", "value": "items"}
    assert normalize_template(template, {"needed_by": "Date", "items": "Item Table"})["mapping"]["items"]["value"] == "items"


def test_placeholders_resolve_known_and_request_values():
    text = "{{RequestNo}} / {{ Subject }} / {{total}} / {{items}} / {{Unknown}}"
    assert render_placeholders(text, CONTEXT) == "PR-1403-025 / خرید لپ‌تاپ / 1250000 /  / "


def test_values_resolve_and_request_values_can_be_withheld():
    mapping = normalize_template(JOURNAL, {"total": "Currency"})["mapping"]
    values = resolve_values(mapping, CONTEXT)
    assert values["title"] == "هزینه خرید بر اساس درخواست PR-1403-025"
    assert values["amount"] == 1250000 and values["posting_date"] == "2026-09-25"
    assert "amount" not in resolve_values(mapping, CONTEXT, transfer_values=False)


def test_journal_entry_is_balanced_with_shared_dimensions():
    values = {**resolve_values(normalize_template(JOURNAL, None)["mapping"], CONTEXT), "cost_center": "Main - T"}
    doc = build_document("Journal Entry", values, "Taban")
    debit, credit = doc["accounts"]
    assert debit == {"account": "Expenses - T", "debit_in_account_currency": 1250000.0, "cost_center": "Main - T"}
    assert credit["credit_in_account_currency"] == 1250000.0 and credit["account"] == "Creditors - T"
    assert doc["user_remark"] == doc["title"]


def test_missing_or_invalid_runtime_values_fail():
    values = resolve_values(normalize_template(JOURNAL, None)["mapping"], {**CONTEXT, "request": {}})
    with pytest.raises(ValueError, match="مبلغ"):
        build_document("Journal Entry", values, "Taban")
    with pytest.raises(ValueError, match="positive"):
        build_document("Journal Entry", {**values, "amount": "0"}, "Taban")


def test_material_request_copies_items_with_schedule():
    doc = build_document(
        "Material Request",
        {"transaction_date": "2026-09-25", "schedule_date": "2026-09-30", "items": CONTEXT["request"]["items"]},
        "Taban",
    )
    assert doc["material_request_type"] == "Purchase"
    assert doc["items"][0] == {"item_code": "LAP", "qty": 2, "uom": "Nos", "schedule_date": "2026-09-30",
                               "warehouse": None, "description": None}


def test_presets_are_valid_once_their_accounts_are_chosen():
    for preset in PRESETS:
        mapping = dict(preset["mapping"])
        if preset["document_type"] == "Journal Entry":
            mapping.update({
                "amount": {"source": "fixed", "value": "1000"},
                "debit_account": {"source": "fixed", "value": "A"},
                "credit_account": {"source": "fixed", "value": "B"},
            })
        else:
            mapping["items"] = {"source": "request", "value": "items"}
        normalize_template({**preset, "mapping": mapping}, None)


# --- PA-069: the previously-empty modules now carry standard documents ----------

def test_every_module_has_at_least_one_document_type():
    for key, module in MODULES.items():
        assert module["types"], f"module {key} has no document types"


def test_new_standard_documents_are_registered_in_their_module():
    assert document_type("Sales Order")["module"] == "Selling"
    assert document_type("Purchase Order")["module"] == "Purchase"
    assert document_type("Stock Entry")["module"] == "Stock"
    assert document_type("Issue")["module"] == "Admin"


def test_unverifiable_documents_are_coming_soon():
    for key in ("Salary Slip", "Attendance", "Employee Advance", "Asset Movement"):
        assert document_type(key)["enabled"] is False


def test_sales_order_template_is_normalized():
    result = normalize_template(
        {"title": "سفارش فروش", "module": "Selling", "document_type": "Sales Order",
         "mapping": {"customer": {"source": "fixed", "value": "Cust - T"},
                     "transaction_date": {"source": "system", "value": "today"},
                     "items": {"source": "request", "value": "items"}}},
        {"items": "Item Table"},
    )
    assert result["document_type"] == "Sales Order"


def test_sales_order_builds_a_native_document_dict():
    doc = build_document("Sales Order",
        {"customer": "Cust - T", "transaction_date": "2026-09-25",
         "items": [{"item_code": "LAP", "qty": 2, "uom": "Nos"}]}, "Taban")
    assert doc["doctype"] == "Sales Order" and doc["customer"] == "Cust - T"
    assert doc["items"][0]["item_code"] == "LAP" and doc["items"][0]["qty"] == 2


def test_purchase_order_builds_a_native_document_dict():
    doc = build_document("Purchase Order",
        {"supplier": "Supp - T", "transaction_date": "2026-09-25",
         "items": [{"item_code": "LAP", "qty": 1, "uom": "Nos"}]}, "Taban")
    assert doc["doctype"] == "Purchase Order" and doc["supplier"] == "Supp - T"


def test_stock_entry_builds_items_with_purpose_warehouses():
    doc = build_document("Stock Entry",
        {"purpose": "Material Receipt", "posting_date": "2026-09-25", "warehouse": "Stores - T",
         "items": [{"item_code": "LAP", "qty": 3, "uom": "Nos"}]}, "Taban")
    assert doc["stock_entry_type"] == "Material Receipt"
    assert doc["items"][0]["t_warehouse"] == "Stores - T"
    assert "s_warehouse" not in doc["items"][0]


def test_stock_entry_rejects_an_unknown_purpose():
    with pytest.raises(ValueError, match="purpose"):
        build_document("Stock Entry",
            {"purpose": "Bogus", "posting_date": "2026-09-25",
             "items": [{"item_code": "LAP", "qty": 1, "uom": "Nos"}]}, "Taban")


def test_issue_builds_a_native_document_dict():
    doc = build_document("Issue", {"subject": "خرابی سیستم"}, "Taban")
    assert doc["doctype"] == "Issue" and doc["subject"] == "خرابی سیستم"


def test_coming_soon_document_is_rejected_on_save():
    with pytest.raises(ValueError, match="not available"):
        normalize_template({"title": "حقوق", "module": "HR", "document_type": "Salary Slip",
                            "mapping": {}}, None)


# --- PA-048: the automatic-action engine supports the commercial documents -----
# The engine's DOCUMENTS allowlist is derived from TARGET_FIELDS (the single
# source of truth), so a document is supported exactly when it has a schema and
# a build_document branch.

@pytest.mark.parametrize(
    "doctype, values",
    [
        ("Sales Order", {"customer": "C", "transaction_date": "2026-09-25",
                         "items": [{"item_code": "LAP", "qty": 1, "uom": "Nos"}]}),
        ("Purchase Order", {"supplier": "S", "transaction_date": "2026-09-25",
                            "items": [{"item_code": "LAP", "qty": 1, "uom": "Nos"}]}),
        ("Stock Entry", {"purpose": "Material Receipt", "posting_date": "2026-09-25",
                         "items": [{"item_code": "LAP", "qty": 1, "uom": "Nos"}]}),
        ("Issue", {"subject": "خرابی"}),
    ],
)
def test_automatic_action_documents_have_a_schema_and_builder(doctype, values):
    from asoud_erp.services.document_templates import TARGET_FIELDS

    assert doctype in TARGET_FIELDS
    assert build_document(doctype, values, "Taban")["doctype"] == doctype


def test_automatic_action_documents_are_the_schemad_documents():
    # The engine allowlist (automatic_action_metadata.DOCUMENTS) is
    # `tuple(TARGET_FIELDS)`; assert the commercial documents are all present so
    # a workflow targeting any of them is no longer blocked.
    from asoud_erp.services.document_templates import TARGET_FIELDS

    for doctype in ("Material Request", "Journal Entry", "Sales Order",
                    "Purchase Order", "Stock Entry", "Issue"):
        assert doctype in TARGET_FIELDS


def test_orders_and_stock_entries_carry_the_dates_erpnext_requires():
    items = [{"item_code": "ITEM-1", "qty": 2}]
    sales = build_document("Sales Order", {"customer": "C", "transaction_date": "2026-11-16", "items": items}, "Taban")
    assert sales["delivery_date"] == "2026-11-16"
    assert all(row["delivery_date"] == "2026-11-16" for row in sales["items"])
    purchase = build_document("Purchase Order", {"supplier": "S", "transaction_date": "2026-11-16", "items": items}, "Taban")
    assert purchase["schedule_date"] == "2026-11-16"
    assert all(row["schedule_date"] == "2026-11-16" for row in purchase["items"])
    entry = build_document("Stock Entry", {"purpose": "Material Receipt", "posting_date": "2026-11-16",
                                           "items": items, "warehouse": "Stores - T"}, "Taban")
    assert entry["set_posting_time"] == 1 and entry["posting_date"] == "2026-11-16"
