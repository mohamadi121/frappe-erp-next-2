import pytest

from asoud_erp.services.request_comments import MAX_COMMENT_LENGTH, clean_comment_text


def test_plain_text_is_trimmed():
    assert clean_comment_text("  لطفاً پیش‌فاکتور را پیوست کنید.  ") == "لطفاً پیش‌فاکتور را پیوست کنید."


def test_html_is_stripped_and_entities_decoded():
    assert clean_comment_text("<div>سلام <b>دنیا</b></div>") == "سلام دنیا"
    assert clean_comment_text("<script>alert(1)</script>ok") == "alert(1)ok"
    assert clean_comment_text("a &amp; b &lt;c&gt;") == "a & b <c>"


def test_paragraph_breaks_become_newlines():
    assert clean_comment_text("<p>اول</p><p>دوم</p>") == "اول\nدوم"
    assert clean_comment_text("a<br>b<br/>c") == "a\nb\nc"
    assert clean_comment_text("a\n\n\n\nb") == "a\n\nb"


@pytest.mark.parametrize("value", [None, "", "   ", "<div> </div>", "<br>", 5, ["x"]])
def test_empty_values_become_empty_text(value):
    assert clean_comment_text(value) == ""


def test_length_limit():
    assert clean_comment_text("x" * MAX_COMMENT_LENGTH) == "x" * MAX_COMMENT_LENGTH
    with pytest.raises(ValueError):
        clean_comment_text("x" * (MAX_COMMENT_LENGTH + 1))
