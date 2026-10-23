"""Who may download an issued employment certificate (T3-B36). Pure, no frappe."""

FIELD = 'certificate'
MANAGER_ROLES = frozenset({'HR Manager', 'System Manager'})
DENIED = 'شما اجازهٔ دریافت این گواهی را ندارید.'
NOT_ISSUED = 'گواهی برای این درخواست صادر نشده است.'


def can_download(*, user: str, roles, owner: str, company_ok: bool) -> bool:
    """The requester, an HR Manager or a System Manager, always inside the request's company."""
    if not company_ok or not user or user == 'Guest':
        return False
    return user == owner or bool(MANAGER_ROLES & set(roles))
