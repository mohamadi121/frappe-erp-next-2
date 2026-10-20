"""Server-owned assignment history in the existing authoritative position store."""
from copy import deepcopy


def reconcile(rows, previous, timestamp, actor):
    old = {r["code"]: r for r in previous}
    new = {r["code"]: r for r in rows}
    for code, before in old.items():
        if code not in new and (
            before.get("employee") or before.get("occupants") or before.get("assignment_history")
        ):
            raise ValueError("جایگاه دارای انتساب یا سابقه است؛ حذف آن مجاز نیست.")
    for row in rows:
        before = old.get(row["code"], {})
        if "occupants" in before and "occupants" not in row:
            raise ValueError("نسخه برنامه قدیمی است؛ حفظ سوابق انتساب نیازمند نسخه جدید است.")
        if "occupants" not in row:
            # Legacy clients must not silently erase an assignment with no history.
            if before.get("employee") and before.get("employee") != row.get("employee"):
                raise ValueError("برای تغییر انتساب و حفظ سابقه، از مدیریت انتساب جدید استفاده کنید.")
            continue
        history = deepcopy(before.get("assignment_history", []))
        prior = before.get("occupants", [before["employee"]] if before.get("employee") else [])
        if prior and not history:
            # Unknown legacy dates remain unknown. Do not invent a start date.
            history = [dict(employee=e, started_at=None, ended_at=None,
                assigned_by=None, ended_by=None, legacy=True) for e in prior]
        for entry in history:
            if not entry.get("ended_at") and entry["employee"] not in row["occupants"]:
                entry.update(ended_at=timestamp, ended_by=actor)
        for employee in row["occupants"]:
            if employee not in prior:
                history.append(dict(employee=employee, started_at=timestamp,
                    ended_at=None, assigned_by=actor, ended_by=None, legacy=False))
        row["assignment_history"] = history
    return rows
