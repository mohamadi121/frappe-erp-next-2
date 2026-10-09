"""Runs a block as ``Administrator`` without damaging the caller's request session.

``frappe.set_user`` (version-15 ``frappe/__init__.py``) mutates ``frappe.local.session`` in place:
it sets ``user`` and ``sid`` to the user name, replaces ``session.data`` with an empty dict, and
resets ``local.cache``, ``form_dict``, ``role_permissions``, ``user_perms``, ``new_doc_templates`` and
the jinja environments. In a request ``local.session`` *is* ``local.session_obj.data`` (``auth.py``),
and at the end of the request ``app.py`` calls ``session_obj.update()``, which writes
``data["sid"]`` and ``data["data"]`` to the ``Sessions`` table and to the redis ``session`` cache
(``sessions.py``). Putting the user back with a second ``set_user`` would leave the sid equal to the
user name and the session data (csrf_token, ...) empty, and that corrupted session would be cached.
So every attribute ``set_user`` touches is snapshotted and restored, on the same objects.

``frappe`` is imported inside the function so the module can be unit-tested with a fake.
"""

from contextlib import contextmanager

SESSION_KEYS = ("user", "sid", "data")
LOCAL_KEYS = ("cache", "form_dict", "role_permissions", "user_perms", "new_doc_templates",
              "jenv_restricted", "jenv_unrestricted")
_MISSING = object()


@contextmanager
def as_administrator():
    """``Administrator`` inside the block; session, form_dict and permission caches restored after."""
    import frappe

    local = frappe.local
    session = local.session
    if session.get("user") == "Administrator":
        yield
        return
    saved_session = {key: session[key] for key in SESSION_KEYS if key in session}
    saved_local = {key: getattr(local, key, _MISSING) for key in LOCAL_KEYS}
    frappe.set_user("Administrator")
    try:
        yield
    finally:
        # The original session object (not a copy) gets its original values, including the very
        # same ``data`` dict, so code holding a reference keeps a consistent view.
        for key in SESSION_KEYS:
            if key in saved_session:
                session[key] = saved_session[key]
            else:
                session.pop(key, None)
        for key, value in saved_local.items():
            if value is _MISSING:
                try:
                    delattr(local, key)
                except AttributeError:
                    pass
            else:
                setattr(local, key, value)
