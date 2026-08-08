import frappe
from frappe import _


def next_detail_code(detail_group: str, digits: int) -> str:
    """Use the numeric group code as the first detail code, then increment it.

    ``digits`` is retained for API compatibility with older ASOUD clients; the
    configured group code now defines both the range and its starting value.
    """
    # Serialize code allocation per group for the lifetime of the current
    # Frappe transaction. The insert that follows commits before another
    # request can calculate the next value for the same group.
    group_rows = frappe.db.sql(
        """
        select group_code
        from `tabASOUD Detail Group`
        where name = %s and disabled = 0
        for update
        """,
        (detail_group,),
        as_dict=True,
    )
    if not group_rows:
        frappe.throw(_("Active detail group does not exist"))
    start_code = str(group_rows[0]["group_code"]).strip()
    if not start_code.isdigit():
        frappe.throw(_("Detail group code must be numeric"))

    # This must also be a locking/current read. A regular get_all under
    # MariaDB REPEATABLE READ can retain the snapshot from before waiting for
    # the group lock and calculate the same code in concurrent requests.
    existing_rows = frappe.db.sql(
        """
        select detail_code
        from `tabASOUD Floating Detail`
        where detail_group = %s
        for update
        """,
        (detail_group,),
        as_list=True,
    )
    numeric_codes = [
        int(str(row[0]).strip())
        for row in existing_rows
        if row and str(row[0]).strip().isdigit()
    ]
    start = int(start_code)
    return str(max([start - 1, *numeric_codes]) + 1)

