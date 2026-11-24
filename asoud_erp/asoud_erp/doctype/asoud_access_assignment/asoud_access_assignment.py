import frappe
from frappe.model.document import Document


class ASOUDAccessAssignment(Document):
    def validate(self):
        if self.is_new() and self.native_role and self.native_role.startswith('ASOUD-ACCESS-'):
            # Keep legacy technical role assignment behavior; a default Company
            # is not proof that this global row belongs to that office.
            self.company = None
            self.employee = None
        if not self.get('company'):
            if not self.managed_role:
                frappe.throw('تخصیص قدیمی باید پروفایل معتبر داشته باشد.')
            return
        if not self.get('employee') or frappe.db.get_value('Employee', self.employee, 'company') != self.company:
            frappe.throw('پرونده پرسنلی باید متعلق به همین دفتر باشد.')
        if frappe.db.get_value('Employee', self.employee, 'user_id') != self.user:
            frappe.throw('حساب با پرونده پرسنلی همخوان نیست.')
        from asoud_erp.services.office_permission_profiles import account_role

        if self.user in {'Administrator', 'Guest'} or self.native_role != account_role(self.user, self.company):
            frappe.throw('نقش فنی تخصیص با حساب و دفتر همخوان نیست.')
        before = self.get_doc_before_save()
        if before and any(before.get(key) != self.get(key) for key in ('company', 'employee', 'user', 'native_role')):
            frappe.throw('انتقال خودکار تخصیص دسترسی به حساب یا دفتر دیگر مجاز نیست.')
        duplicate = frappe.db.get_value('ASOUD Access Assignment',
            {'user': self.user, 'company': self.company, 'name': ['!=', self.name or '']}, 'name')
        if duplicate:
            frappe.throw('این حساب در همین دفتر تخصیص دسترسی دارد.')
        if self.managed_role and frappe.db.get_value('ASOUD Role Definition', self.managed_role, 'company') != self.company:
            frappe.throw('پروفایل انتخاب‌شده متعلق به همین دفتر نیست.')
