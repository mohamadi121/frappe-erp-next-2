import json
import sys
import types


def _load_module(monkeypatch):
    frappe = types.ModuleType("frappe")
    frappe.whitelist = lambda **_kwargs: lambda function: function
    frappe.throw = lambda message: (_ for _ in ()).throw(ValueError(message))
    monkeypatch.setitem(sys.modules, "frappe", frappe)
    sys.modules.pop("asoud_erp.api.v1.sync", None)
    from asoud_erp.api.v1 import sync

    return sync


def test_payload_accepts_json_object(monkeypatch):
    sync = _load_module(monkeypatch)
    assert sync._payload(json.dumps({"company": "Test"})) == {"company": "Test"}


def test_payload_rejects_json_list(monkeypatch):
    sync = _load_module(monkeypatch)
    try:
        sync._payload("[]")
    except ValueError as error:
        assert "object" in str(error)
    else:
        raise AssertionError("list payload must be rejected")


def test_execute_mutation_returns_saved_response_without_second_execution(monkeypatch):
    sync = _load_module(monkeypatch)
    records = {}
    calls = []

    class DB:
        @staticmethod
        def get_value(_doctype, key, _fields, as_dict=False):
            value = records.get(key)
            return types.SimpleNamespace(**value) if value and as_dict else value

    class RequestDocument:
        def __init__(self, values):
            self.request_key = values["request_key"]
            self.method = values["method"]
            self.status = values["status"]
            self.response_json = None

        def insert(self, ignore_permissions=False):
            records[self.request_key] = {
                "status": self.status,
                "response_json": self.response_json,
            }

        def save(self, ignore_permissions=False):
            records[self.request_key] = {
                "status": self.status,
                "response_json": self.response_json,
            }

    sync.frappe.db = DB()
    sync.frappe.get_doc = RequestDocument
    sync.frappe.get_attr = lambda _method: lambda **values: (
        calls.append(values) or {"ok": True, "data": {"name": "A"}, "meta": {"api_version": "v1"}}
    )

    first = sync.execute_mutation("request-1", "asoud_erp.api.v1.party.save_party", {"name": "A"})
    second = sync.execute_mutation("request-1", "asoud_erp.api.v1.party.save_party", {"name": "A"})

    assert first == second
    assert calls == [{"name": "A"}]
