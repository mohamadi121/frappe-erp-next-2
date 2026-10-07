"""One Persian text per request error code (CONTRACT 4.15)."""

import unittest

from asoud_erp.services import leave_hours as lh
from asoud_erp.services.request_templates import base

CONTRACT_CODES = (
    "TEMPLATE_NOT_AVAILABLE", "REQUEST_ID_CONFLICT", "REQUEST_NOT_EDITABLE", "REQUESTER_MISMATCH",
    "EMPLOYEE_NOT_FOUND", "COST_CENTER_REQUIRED", "DATE_IN_PAST", "INVALID_DATE_RANGE", "INVALID_TIME_RANGE",
    "LEAVE_ALL_HOLIDAYS", "HOURLY_ON_HOLIDAY", "HOURLY_EXCEEDS_DAY", "LEAVE_OVERLAP",
    "INSUFFICIENT_LEAVE_BALANCE", "DELIVERY_NOT_WAREHOUSE", "ITEM_NOT_STOCKABLE", "ATTACHMENT_INVALID",
    "EMPTY_COMMENT", "NATIVE_NOT_RETRYABLE",
)


class TestRequestErrorMessages(unittest.TestCase):
    def test_every_contract_code_has_a_message(self):
        for code in CONTRACT_CODES:
            self.assertTrue(base.ERROR_MESSAGES.get(code), code)

    def test_leave_codes_share_the_text_of_the_leave_rules(self):
        # lb.fail() and the preview use leave_hours.MESSAGES; base must not carry a second wording.
        for code in ("INVALID_DATE_RANGE", "INVALID_TIME_RANGE", "LEAVE_ALL_HOLIDAYS", "HOURLY_ON_HOLIDAY",
                     "HOURLY_EXCEEDS_DAY", "LEAVE_OVERLAP", "INSUFFICIENT_LEAVE_BALANCE"):
            self.assertEqual(base.ERROR_MESSAGES[code], lh.MESSAGES[code], code)


if __name__ == "__main__":
    unittest.main()
