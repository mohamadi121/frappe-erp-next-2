from frappe.core.doctype.file.file import File

from asoud_erp.services.request_access import file_permission


class ASOUDPrivateFile(File):
    """Keep standard storage; apply request authorization to the download route."""

    def is_downloadable(self):
        permission = file_permission(self, permission_type="read")
        return super().is_downloadable() if permission is None else permission
