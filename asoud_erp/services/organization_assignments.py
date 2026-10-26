"""Server-owned assignment history in the existing authoritative position store."""
from copy import deepcopy


def deletion_review(rows, code):
    position = next((row for row in rows if row["code"] == code), None)
    if position is None:
        raise ValueError("جایگاه موردنظر در ساختار فعلی وجود ندارد.")
    occupants = set(position.get("occupants") or [])
    if position.get("employee"):
        occupants.add(position["employee"])
    counts = {
        "occupants": len(occupants),
        "subordinates": sum(row.get("parent") == code for row in rows),
        "history": len(position.get("assignment_history") or []),
    }
    labels = {"occupants": "متصدی فعال", "subordinates": "جایگاه زیرمجموعه", "history": "سابقه انتساب"}
    blockers = [f"جایگاه دارای {count} {labels[key]} است؛ حذف مجاز نیست."
                for key, count in counts.items() if count]
    return {"can_delete": not blockers, "blockers": blockers, "counts": counts}


def reconcile(rows, previous, timestamp, actor):
    old = {r["code"]: r for r in previous}
    new = {r["code"]: r for r in rows}
    for code, before in old.items():
        if code not in new:
            blockers = deletion_review(previous, code)["blockers"]
            if blockers:
                raise ValueError("\n".join(blockers))
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
