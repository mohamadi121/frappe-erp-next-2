from unittest.mock import MagicMock, patch
import pytest

from asoud_erp.services.first_office_setup import (
    INTERNAL_SUFFIX,
    block_internal_mail,
    internal_email,
    _summary,
)


def test_internal_email_detection():
    assert internal_email(f"test{INTERNAL_SUFFIX}") is True
    assert internal_email(f"User Name <abc123{INTERNAL_SUFFIX}>") is True
    assert internal_email("test@example.com") is False
    assert internal_email("test@users.asoud.invalid.org") is False
    assert internal_email("") is False
    assert internal_email(None) is False


def test_block_internal_mail_prevents_dispatch():
    doc = MagicMock()
    recipient_row = MagicMock()
    recipient_row.recipient = f"system{INTERNAL_SUFFIX}"
    doc.get.return_value = [recipient_row]

    with patch("frappe.throw") as mock_throw:
        block_internal_mail(doc)
        mock_throw.assert_called_once_with(
            "این حساب ایمیل تماس ندارد؛ اطلاعات ورود را امن و مستقیم تحویل دهید."
        )


def test_block_internal_mail_allows_standard_recipients():
    doc = MagicMock()
    recipient_row = MagicMock()
    recipient_row.recipient = "real.user@example.com"
    doc.get.return_value = [recipient_row]

    with patch("frappe.throw") as mock_throw:
        block_internal_mail(doc)
        mock_throw.assert_not_called()


def test_summary_reflects_bootstrap_completion_flag():
    doc = MagicMock()
    doc.company = "شرکت تست"
    doc.first_hr_user = None
    doc.bootstrap_completed = 0
    res = _summary(doc)
    assert res == {
        "company": "شرکت تست",
        "hr_lead": None,
        "hr_ready": False,
        "completed": False,
    }

    doc.bootstrap_completed = 1
    res_completed = _summary(doc)
    assert res_completed["completed"] is True
