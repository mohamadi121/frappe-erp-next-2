"""A small in-memory stand-in for frappe, for flow tests that run without a site.

It implements just enough of documents, `db`, `get_all` and filters for the request
engine: it exists to execute the engine's code paths, not to replace the integration
tests (`integration_tests/`), which run on a real site.
"""

import hashlib
import re
import types
from datetime import date, datetime


class Error(Exception):
    def __init__(self, message="", title=None):
        super().__init__(message)
        self.title = title


class ValidationError(Error):
    pass


class PermissionError_(Error):
    pass


class DoesNotExistError(Error):
    pass


class Dict(dict):
    """frappe._dict: attribute access, missing keys read as None."""

    __getattr__ = dict.get

    def __setattr__(self, key, value):
        self[key] = value


def _value(row, field):
    value = row.get(field)
    return value


def _like(value, pattern):
    """SQL LIKE with `%`, `_` and backslash escapes, case-insensitive like MariaDB."""
    regex, index = "", 0
    while index < len(pattern):
        char = pattern[index]
        if char == "\\" and index + 1 < len(pattern):
            regex += re.escape(pattern[index + 1])
            index += 1
        elif char == "%":
            regex += ".*"
        elif char == "_":
            regex += "."
        else:
            regex += re.escape(char)
        index += 1
    return re.fullmatch(regex, str(value or ""), flags=re.S | re.I) is not None


def _check(value, operator, expected):
    if operator == "=":
        return value == expected
    if operator == "!=":
        return value != expected
    if operator == "in":
        return value in expected
    if operator == "like":
        return _like(value, expected)
    if operator == ">=":
        return value is not None and str(value) >= str(expected)
    if operator == "<=":
        return value is not None and str(value) <= str(expected)
    if operator == "is":
        return bool(value) if expected == "set" else not value
    raise AssertionError(f"unsupported filter operator {operator}")


def matches(row, filters):
    if not filters:
        return True
    if isinstance(filters, str):
        return row["name"] == filters
    if isinstance(filters, dict):
        items = [[key, *(value if isinstance(value, (list, tuple)) else ["=", value])]
                 for key, value in filters.items()]
        items = [[key, op, val] for key, op, val in items]
    else:
        items = filters
    return all(_check(_value(row, field), operator, expected) for field, operator, expected in items)


class Site:
    """Tables, a name counter and the current user."""

    def __init__(self):
        self.tables = {}
        self.counter = 0
        self.user = "sara@example.com"
        self.roles = ["Employee"]
        self.notifications = []
        self.deleted_files = []
        self.names = {}

    def table(self, doctype):
        return self.tables.setdefault(doctype, {})

    def add(self, doctype, name=None, **values):
        self.counter += 1
        name = name or values.get("name") or f"{doctype[:3].upper()}-{self.counter:04d}"
        row = {"doctype": doctype, "name": name, "owner": self.user, "creation": f"2026-10-0{1 + self.counter % 8} 10:00:00",
               **values}
        self.table(doctype)[name] = row
        return row


NAME_FIELDS = {"ASOUD Workflow Definition": "workflow_code", "Workflow": "workflow_name",
               "Workflow State": "workflow_state_name"}


class FakeDoc:
    def __init__(self, site, data):
        object.__setattr__(self, "_site", site)
        object.__setattr__(self, "_data", dict(data))

    def __getattr__(self, key):
        if key.startswith("__"):
            raise AttributeError(key)
        return self._data.get(key)

    def __setattr__(self, key, value):
        self._data[key] = value

    def get(self, key, default=None):
        return self._data.get(key, default)

    def update(self, values):
        self._data.update(values)

    def as_dict(self):
        return Dict(self._data)

    def insert(self, **kwargs):
        site = self._site
        if self.doctype == "File":
            self.name = f"FILE-{site.counter + 1:04d}"
            self.file_url = f"/private/files/{self.name}-{self.file_name}"
            content = self._data.pop("content", b"")
            self.content_hash = hashlib.md5(content).hexdigest()
            self.file_size = len(content)
            site.contents = getattr(site, "contents", {})
            site.contents[self.name] = content
        elif self.doctype in NAME_FIELDS:
            self.name = self._data[NAME_FIELDS[self.doctype]]
        elif self.doctype == "ASOUD Workflow Request":
            site.names["req"] = site.names.get("req", 0) + 1
            self.name = f"{(self.template_key or 'req').upper()}-{site.names['req']:04d}"
        self.creation = f"2026-10-05 10:{site.counter % 60:02d}:00"
        row = site.add(self.doctype, self.name or None,
                       **{k: v for k, v in self._data.items() if k not in ("name", "doctype")})
        self.name = row["name"]
        self._data.update(row)
        return self

    def save(self, **kwargs):
        self._site.table(self.doctype)[self.name].update(self._data)
        return self

    def db_set(self, field, value):
        self._data[field] = value
        self._site.table(self.doctype)[self.name][field] = value

    def reload(self):
        self._data.update(self._site.table(self.doctype)[self.name])

    def add_comment(self, comment_type="Comment", text=None, **kwargs):
        row = self._site.add("Comment", comment_type=comment_type, content=text, reference_doctype=self.doctype,
                             reference_name=self.name, comment_email=self._site.user)
        return FakeDoc(self._site, row)

    def check_permission(self, *args):
        return True


def _alias(field):
    match = re.fullmatch(r"(.+?)\s+as\s+(\w+)", field)
    return (match.group(1), match.group(2)) if match else (field, field)


class FakeDB:
    def __init__(self, site):
        self.site = site

    def _rows(self, doctype, filters):
        rows = list(self.site.table(doctype).values())
        if isinstance(filters, str):
            return [row for row in rows if row["name"] == filters]
        return [row for row in rows if matches(row, filters)]

    def get_value(self, doctype, filters, fieldname="name", as_dict=False, order_by=None, **kwargs):
        rows = self._rows(doctype, filters)
        if order_by:
            field, _, direction = order_by.partition(" ")
            rows.sort(key=lambda row: str(row.get(field) or ""), reverse=direction == "desc")
        if not rows:
            return None
        row = rows[0]
        if isinstance(fieldname, str):
            return row.get(fieldname)
        values = {field: row.get(field) for field in fieldname}
        return Dict(values) if as_dict else tuple(values.values())

    def exists(self, doctype, filters=None):
        rows = self._rows(doctype, filters)
        return rows[0]["name"] if rows else None

    def set_value(self, doctype, name, field, value=None, **kwargs):
        updates = field if isinstance(field, dict) else {field: value}
        for row in self._rows(doctype, name):
            row.update(updates)

    def savepoint(self, name):
        pass

    def rollback(self, save_point=None):
        pass

    def count(self, doctype, filters=None):
        return len(self._rows(doctype, filters))


def install(site):
    """The frappe module backed by `site`."""
    frappe = types.ModuleType("frappe")
    frappe.ValidationError, frappe.PermissionError, frappe.DoesNotExistError = (
        ValidationError, PermissionError_, DoesNotExistError)
    frappe._ = lambda text: text
    frappe._dict = Dict
    frappe.whitelist = lambda **kwargs: (lambda function: function)
    frappe.flags = Dict()
    frappe.local = types.SimpleNamespace()
    frappe.db = FakeDB(site)
    frappe.session = type("Session", (), {"user": property(lambda self: site.user)})()
    frappe.get_roles = lambda *args: list(site.roles)
    frappe.has_permission = lambda *args, **kwargs: True
    frappe.get_meta = lambda doctype: types.SimpleNamespace(has_field=lambda name: True)
    frappe.generate_hash = lambda length=10: "x" * length
    frappe.parse_json = lambda value: __import__("json").loads(value)

    def throw(message, exc=None, title=None):
        raise (exc or ValidationError)(message, title=title)

    frappe.throw = throw

    def get_doc(doctype, name=None, **kwargs):
        if isinstance(doctype, dict):
            return FakeDoc(site, doctype)
        row = site.table(doctype).get(name)
        if row is None:
            raise DoesNotExistError(f"{doctype} {name}")
        return FakeDoc(site, row)

    frappe.get_doc = get_doc

    def delete_doc(doctype, name, **kwargs):
        site.table(doctype).pop(name, None)
        if doctype == "File":
            site.deleted_files.append(name)

    frappe.delete_doc = delete_doc

    def get_all(doctype, filters=None, fields=None, order_by=None, limit_start=0, limit_page_length=20,
                group_by=None, pluck=None, as_list=False, or_filters=None, **kwargs):
        rows = [row for row in site.table(doctype).values() if matches(row, filters)]
        if order_by:
            for part in reversed([item.strip() for item in order_by.split(",")]):
                field, _, direction = part.partition(" ")
                rows.sort(key=lambda row, field=field: str(row.get(field) or ""), reverse=direction == "desc")
        if group_by:
            groups = {}
            for row in rows:
                groups.setdefault(row.get(group_by), []).append(row)
            return [Dict(**{group_by: key, "total": len(items)}) for key, items in groups.items()]
        if limit_page_length:
            rows = rows[limit_start:limit_start + limit_page_length]
        if pluck:
            return [row.get(pluck) for row in rows]
        names = [_alias(field) for field in (fields or ["name"])]
        result = [Dict({alias: row.get(source) for source, alias in names}) for row in rows]
        return [tuple(item.values()) for item in result] if as_list else result

    frappe.get_all = get_all
    frappe.clear_messages = lambda: None
    frappe.log_error = lambda **kwargs: None
    frappe.get_traceback = lambda: ""
    frappe.QueryDeadlockError = type("QueryDeadlockError", (Exception,), {})
    frappe.QueryTimeoutError = type("QueryTimeoutError", (Exception,), {})
    utils = types.ModuleType("frappe.utils")
    utils.get_fullname = lambda user: f"Full {user}"

    def getdate(value=None):
        if isinstance(value, datetime):
            return value.date()
        return value if isinstance(value, date) else date.fromisoformat(str(value)[:10])

    utils.getdate = getdate
    utils.now_datetime = lambda: "now"
    utils.nowdate = lambda: date.today().isoformat()
    utils.flt = float
    frappe.utils = utils
    return frappe, utils


def isolate(names):
    """Forget the named `asoud_erp` modules (and their package attributes) so they import afresh
    against the stubbed frappe; the returned function puts the originals back."""
    import importlib
    import sys

    saved = {name: sys.modules.pop(name, None) for name in names}
    attrs = {}
    for name in names:
        parent_name, _, leaf = name.rpartition(".")
        parent = importlib.import_module(parent_name) if parent_name in sys.modules else None
        attrs[name] = (parent, leaf, parent.__dict__.get(leaf) if parent else None)

    def restore():
        for name in names:
            sys.modules.pop(name, None)
            if saved[name] is not None:
                sys.modules[name] = saved[name]
            parent, leaf, old = attrs[name]
            if parent is not None:
                if old is not None:
                    setattr(parent, leaf, old)
                else:
                    parent.__dict__.pop(leaf, None)

    return restore
