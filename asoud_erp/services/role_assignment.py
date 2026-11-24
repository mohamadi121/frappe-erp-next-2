"""Guard availability of ASOUD-managed profiles at the native User boundary."""
import frappe


def validate_role_profile_assignment(doc, method=None):
    profile = doc.get("role_profile_name")
    if not profile or not frappe.db.exists("DocType", "ASOUD Role Definition"):
        return
    if not profile.startswith("ASOUD:"):
        return
    # The same lock as role management prevents disable/assign races.
    frappe.db.sql("select name from tabRole where name=%s for update", ("System Manager",))
    definition = frappe.db.get_value("ASOUD Role Definition", {"role_profile": profile},
                                     ["title", "enabled", "template_key"], as_dict=True)
    if definition and definition.template_key:
        frappe.throw('پروفایل دفتر را از تب دسترسی‌های حساب اعمال کنید؛ اتصال اشتراکی مجاز نیست.')
    if definition and not definition.enabled:
        frappe.throw("این نقش غیرفعال است و نمی‌توان آن را به کاربر تخصیص داد.")
