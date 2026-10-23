from asoud_erp.services.digits import (
    normalize_column_rows,
    normalize_numeric_text,
    to_ascii_digits,
)


def test_persian_digits_become_ascii() -> None:
    assert to_ascii_digits("۰۹۱۲۱۲۳۴۵۶۷") == "09121234567"
    assert to_ascii_digits("۹۸۷۷۶۶۶۶۶۶") == "9877666666"


def test_arabic_indic_digits_become_ascii() -> None:
    assert to_ascii_digits("٠٩١٢٣٤٥٦٧٨") == "0912345678"


def test_mixed_persian_arabic_and_ascii_digits() -> None:
    assert to_ascii_digits("۱۲٣4٥6") == "123456"


def test_persian_separators_inside_a_number() -> None:
    assert to_ascii_digits("۱٬۲۳۴٫۵") == "1234.5"
    assert to_ascii_digits("۱۲۳٫۴") == "123.4"


def test_separators_outside_a_number_are_left_alone() -> None:
    assert to_ascii_digits("مبلغ ۱٬۲۳۴ تومان") == "مبلغ 1٬234 تومان"


def test_plain_text_with_ascii_digits_stays_untouched() -> None:
    assert to_ascii_digits("Customer 123") == "Customer 123"
    assert to_ascii_digits("مشتری الف") == "مشتری الف"
    assert to_ascii_digits("") == ""


def test_letters_of_a_name_are_preserved_while_digits_translate() -> None:
    assert to_ascii_digits("مشتری شماره ۷") == "مشتری شماره 7"


def test_none_and_non_strings_pass_through() -> None:
    assert to_ascii_digits(None) is None
    assert to_ascii_digits(1405) == 1405
    assert to_ascii_digits(["۱۲"]) == ["۱۲"]


def test_normalize_numeric_text_strips_and_empties_to_none() -> None:
    assert normalize_numeric_text("  ۰۹۱۲۱۲۳۴۵۶۷  ") == "09121234567"
    assert normalize_numeric_text("   ") is None
    assert normalize_numeric_text(None) is None
    assert normalize_numeric_text(1405) == 1405


def test_normalize_column_rows_only_reports_changes() -> None:
    rows = [
        {"name": "P-1", "value": "۹۸۷۷۶۶۶۶۶۶"},
        {"name": "P-2", "value": "123456"},
        {"name": "P-3", "value": None},
        {"name": "P-4", "value": "متن"},
    ]
    assert normalize_column_rows(rows, "value") == [("P-1", "9877666666")]


def test_to_persian_digits_only_changes_ascii_digits():
    from asoud_erp.services.digits import to_persian_digits

    assert to_persian_digits("1405/07/28 08:01") == "۱۴۰۵/۰۷/۲۸ ۰۸:۰۱"
    assert to_persian_digits("حاضر") == "حاضر"
    assert to_persian_digits(1234) == "۱۲۳۴"
