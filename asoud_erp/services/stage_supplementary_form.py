"""Pure helpers for the Approval stage's supplementary form binding.

An Approval stage can be bound to a published ASOUD Form revision (kind
``Stage``). Each approver's own task stores the filled values under the
reserved response key ``_supplementary``. Field keys must match
``[a-z][a-z0-9_]*`` so ``_supplementary`` can never collide with a real field.
"""
import copy

RESERVED_KEY = "_supplementary"


def read_binding(config):
    """Return the stage config's ``supplementary_form`` binding, or None."""
    binding = (config or {}).get("supplementary_form")
    return binding if isinstance(binding, dict) else None


def validate_binding_shape(binding):
    """Return ``{form, revision}`` or raise ValueError if the shape is wrong."""
    if not isinstance(binding, dict):
        raise ValueError("فرم تکمیلی مرحله باید یک شیء باشد.")
    form = binding.get("form")
    revision = binding.get("revision")
    if not isinstance(form, str) or not form.strip():
        raise ValueError("فرم تکمیلی مرحله مشخص نشده است.")
    if not isinstance(revision, str) or not revision.strip():
        raise ValueError("نسخهٔ فرم تکمیلی مرحله مشخص نشده است.")
    return {"form": form, "revision": revision}


def merge_supplementary(response, binding, values):
    """Return a copy of ``response`` with the reserved entry set."""
    result = dict(response or {})
    result[RESERVED_KEY] = {
        "form": binding["form"],
        "revision": binding["revision"],
        "values": copy.deepcopy(values or {}),
    }
    return result


def strip_supplementary(response):
    """Return a copy of ``response`` without the reserved entry."""
    result = dict(response or {})
    result.pop(RESERVED_KEY, None)
    return result


def supplementary_of(response):
    """Return the stored reserved entry, or None."""
    entry = (response or {}).get(RESERVED_KEY)
    return entry if isinstance(entry, dict) else None


def without_required(schema):
    """A copy of ``schema`` with every required flag cleared (optional validation)."""
    result = copy.deepcopy(schema)
    for section in result.get("sections", []):
        for field in section.get("fields", []):
            field["required"] = False
            for column in field.get("columns", []) or []:
                column["required"] = False
    return result
