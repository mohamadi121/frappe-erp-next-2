import re

import frappe
from frappe.model.document import Document


class ASOUDRoleDefinition(Document):
    def validate(self):
        if not re.fullmatch(r"[A-Z][A-Z0-9_-]{1,39}", self.role_code or ""):
            frappe.throw("کد نقش باید ۲ تا ۴۰ حرف انگلیسی بزرگ، عدد، خط تیره یا زیرخط باشد.")
        self.title = (self.title or "").strip()
        if not self.title:
            frappe.throw("نام نقش الزامی است.")
        if self.role_profile != f"ASOUD:{self.role_code}":
            frappe.throw("پروفایل دسترسی با کد نقش سازگار نیست.")
        seen, parent = {self.role_code}, self.parent_role
        while parent:
            if parent in seen:
                frappe.throw("رابطه حلقوی بین نقش‌ها مجاز نیست.")
            seen.add(parent)
            parent = frappe.db.get_value("ASOUD Role Definition", parent, "parent_role")
        if not self.enabled and frappe.db.exists("User", {"role_profile_name": self.role_profile}):
            frappe.throw("این نقش به کاربر متصل است؛ پیش از غیرفعال‌سازی، تخصیص آن را در مدیریت کاربران تغییر دهید.")
