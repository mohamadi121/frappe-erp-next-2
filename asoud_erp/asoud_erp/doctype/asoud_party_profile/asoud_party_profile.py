from frappe.model.document import Document

from asoud_erp.services.personnel_contract import validate_financial


class ASOUDPartyProfile(Document):
    def validate(self):
        validate_financial(self.as_dict())
