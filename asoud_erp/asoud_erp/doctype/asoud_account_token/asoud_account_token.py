from frappe.model.document import Document


class ASOUDAccountToken(Document):
    """One-time recovery / activation code. Only a salted hash is stored."""
