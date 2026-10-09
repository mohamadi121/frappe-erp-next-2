"""The Administrator scope must leave the caller's request session exactly as it was."""

import sys
import types

import pytest

from asoud_erp.services.session_scope import as_administrator


class FakeDict(dict):
    """Like frappe._dict: attribute access to keys."""

    def __getattr__(self, key):
        return self.get(key)

    def __setattr__(self, key, value):
        self[key] = value


class FakeFrappe(types.ModuleType):
    """A frappe whose set_user does what version-15 does (frappe/__init__.py)."""

    def __init__(self):
        super().__init__("frappe")
        self.local = types.SimpleNamespace(
            session=FakeDict(user="mgr@x", sid="real-sid-123", data=FakeDict(csrf_token="csrf-abc", lang="fa")),
            cache={"cached": 1}, form_dict=FakeDict(cmd="complete"), role_permissions={"Employee": {}},
            user_perms=object(), new_doc_templates={"x": 1}, jenv_restricted="env-r", jenv_unrestricted="env-u")
        self.set_user_calls = []

    def set_user(self, username):
        self.set_user_calls.append(username)
        local = self.local
        local.session.user = username
        local.session.sid = username
        local.cache = {}
        local.form_dict = FakeDict()
        local.jenv_restricted = None
        local.jenv_unrestricted = None
        local.session.data = FakeDict()
        local.role_permissions = {}
        local.new_doc_templates = {}
        local.user_perms = None


@pytest.fixture
def fake(monkeypatch):
    module = FakeFrappe()
    monkeypatch.setitem(sys.modules, "frappe", module)
    return module


def snapshot(module):
    local = module.local
    return {"session": local.session, "user": local.session.user, "sid": local.session.sid,
            "data": local.session.data, "data_copy": dict(local.session.data), "form_dict": local.form_dict,
            "cache": local.cache, "role_permissions": local.role_permissions, "user_perms": local.user_perms,
            "new_doc_templates": local.new_doc_templates, "jenv_restricted": local.jenv_restricted,
            "jenv_unrestricted": local.jenv_unrestricted}


def assert_restored(module, before):
    local = module.local
    assert local.session is before["session"]
    assert (local.session.user, local.session.sid) == (before["user"], before["sid"]) == ("mgr@x", "real-sid-123")
    assert local.session.data is before["data"]
    assert dict(local.session.data) == before["data_copy"] and local.session.data.csrf_token == "csrf-abc"
    assert local.form_dict is before["form_dict"] and local.form_dict.cmd == "complete"
    for key in ("cache", "role_permissions", "user_perms", "new_doc_templates", "jenv_restricted",
                "jenv_unrestricted"):
        assert getattr(local, key) is before[key], key


def test_session_is_restored_after_success(fake):
    before = snapshot(fake)
    with as_administrator():
        assert fake.local.session.user == "Administrator"
        assert fake.local.session.data == {} and fake.local.form_dict == {}
    assert fake.set_user_calls == ["Administrator"]
    assert_restored(fake, before)


def test_session_is_restored_when_the_body_raises(fake):
    before = snapshot(fake)
    with pytest.raises(RuntimeError):
        with as_administrator():
            raise RuntimeError("HRMS refused")
    assert_restored(fake, before)


def test_nested_use_restores_each_level(fake):
    before = snapshot(fake)
    with as_administrator():
        with as_administrator():  # already Administrator: no second switch
            assert fake.local.session.user == "Administrator"
    assert fake.set_user_calls == ["Administrator"]
    assert_restored(fake, before)


def test_nothing_is_switched_for_administrator(fake):
    fake.local.session.user = "Administrator"
    data = fake.local.session.data
    with as_administrator():
        pass
    assert fake.set_user_calls == []
    assert fake.local.session.data is data and fake.local.session.sid == "real-sid-123"


def test_attributes_absent_before_are_absent_after(fake):
    del fake.local.jenv_restricted
    with as_administrator():
        pass
    assert not hasattr(fake.local, "jenv_restricted")
