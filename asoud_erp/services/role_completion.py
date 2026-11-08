"""Pure completion rules for the role catalog («مشاهده و تکمیل نقش‌ها»).

A non-system role is "incomplete" only when its Role Profile has no base roles AND its
role-wide native role has no read permission. Per-user access assignments never count.
"""


def completion(base_roles, system, role_grant_count):
    """Return "complete" or "incomplete" for one role.

    ``role_grant_count`` is the number of Custom DocPerm rows (read, permlevel 0) on the
    role-wide native role; it is computed by the caller, keeping this function pure.
    """
    if system:
        return "complete"
    if base_roles:
        return "complete"
    return "complete" if role_grant_count else "incomplete"


def summary(roles, categories):
    """Aggregate counts for the catalog header.

    ``roles`` are the catalog rows (each already carries ``system`` and ``completion``);
    ``categories`` are the category rows. "roles" counts managed (non-system) roles only.
    """
    codes = {row["code"] for row in categories}
    managed = [row for row in roles if not row["system"]]
    return {
        "roles": len(managed),
        "categories": len(codes),
        "incomplete": sum(1 for row in managed if row["completion"] == "incomplete"),
        "uncategorized": sum(1 for row in managed if not row["category"] or row["category"] not in codes),
    }
