import re

import frappe
from frappe.model.document import Document


class ASOUDRoleCategory(Document):
    def validate(self):
        if not re.fullmatch(r"[A-Z][A-Z0-9_-]{1,39}", self.category_code or ""):
            frappe.throw("کد دسته باید ۲ تا ۴۰ حرف انگلیسی بزرگ، عدد، خط تیره یا زیرخط باشد.")
        self.title = (self.title or "").strip()
        if not self.title:
            frappe.throw("عنوان دسته الزامی است.")
