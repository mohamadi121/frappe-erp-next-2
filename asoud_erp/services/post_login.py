"""The route a signed-in account must see next (pure; the server decides, the app obeys)."""

ROUTE_ACCOUNT_DISABLED = "account-disabled"
ROUTE_CHANGE_PASSWORD = "change-password"
ROUTE_CREATE_FIRST_OFFICE = "create-first-office"
ROUTE_COMPLETE_ADMIN_PROFILE = "complete-admin-profile"
ROUTE_OFFICE_SELECT = "office-select"
ROUTE_HOME = "home"
ROUTE_NO_OFFICE = "no-office"

NO_OFFICE_MESSAGE = "هنوز دسترسی به دفتر کاری برای شما تعیین نشده است."
DISABLED_MESSAGE = "حساب کاربری شما غیرفعال است."


def resolve_next_route(*, active, must_change_password, is_system_admin, first_office_exists,
                       admin_profile_complete, office_ids, selected_office=None) -> dict:
    """``{route, office, message}``.

    Order for the system administrator: temporary password, first office, essential
    profile, then the ordinary office logic. Every other account never reaches the
    first-office or admin-profile steps, whatever the deployment state is.
    """
    offices = list(dict.fromkeys(office_ids or ()))
    if not active:
        return {"route": ROUTE_ACCOUNT_DISABLED, "office": None, "message": DISABLED_MESSAGE}
    if must_change_password:
        return {"route": ROUTE_CHANGE_PASSWORD, "office": None, "message": None}
    if is_system_admin:
        if not first_office_exists:
            return {"route": ROUTE_CREATE_FIRST_OFFICE, "office": None, "message": None}
        if not admin_profile_complete:
            return {"route": ROUTE_COMPLETE_ADMIN_PROFILE, "office": None, "message": None}
    if not offices:
        return {"route": ROUTE_NO_OFFICE, "office": None, "message": NO_OFFICE_MESSAGE}
    if len(offices) == 1:
        return {"route": ROUTE_HOME, "office": offices[0], "message": None}
    if selected_office in offices:
        return {"route": ROUTE_HOME, "office": selected_office, "message": None}
    return {"route": ROUTE_OFFICE_SELECT, "office": None, "message": None}
