import pytest

from asoud_erp.services.document_templates import (
    PRESETS,
    build_document,
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
