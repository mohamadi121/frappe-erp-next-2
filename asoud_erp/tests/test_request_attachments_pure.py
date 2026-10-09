import base64
from io import BytesIO

import pytest

from asoud_erp.services import request_attachments as att


def _b64(data=b"hello"):
    return base64.b64encode(data).decode()


def _upload(filename="price.pdf", ref=None, data=b"hello"):
    item = {"filename": filename, "content_base64": _b64(data)}
    if ref:
        item["ref"] = ref
    return item


def test_uploads_with_refs_may_share_a_filename():
    uploads = att.parse_uploads([_upload(ref="att-1"), _upload(ref="att-2")])
    assert [item.key for item in uploads] == ["attachment:att-1", "attachment:att-2"]
    assert {item.filename for item in uploads} == {"price.pdf"}


def test_uploads_without_ref_are_referenced_by_filename_and_must_be_unique():
    assert att.parse_uploads([_upload("a.pdf")])[0].key == "attachment:a.pdf"
    with pytest.raises(att.AttachmentError):
        att.parse_uploads([_upload("a.pdf"), _upload("a.pdf")])
    with pytest.raises(att.AttachmentError):
        att.parse_uploads([_upload("a.pdf", ref="x"), _upload("b.pdf", ref="x")])


def test_extensions_include_excel_and_word_and_are_checked_case_insensitively():
    for name in ("a.xls", "a.doc", "a.XLSX", "a.Docx", "a.PDF", "a.jpeg"):
        assert att.parse_uploads([_upload(name)])
    for name in ("a.exe", "a.svg", "a", "a.pdf.exe", ""):
        with pytest.raises(att.AttachmentError):
            att.parse_uploads([_upload(name)])


def test_leave_extensions_come_from_the_template_config():
    limits = att.limits_from({"max_files": 10, "max_mb": 10, "extensions": ["jpg", "jpeg", "png", "pdf", "docx"]})
    assert att.parse_uploads([_upload("a.docx")], **limits)
    with pytest.raises(att.AttachmentError):
        att.parse_uploads([_upload("a.xlsx")], **limits)


def test_limits_cannot_be_raised_by_a_template_config():
    assert att.limits_from({"max_files": 99, "max_mb": 50}) == {
        "extensions": att.DEFAULT_EXTENSIONS, "max_files": 10, "max_bytes": 10 * 1024 * 1024}
    assert att.limits_from(None)["max_files"] == 10
    assert att.limits_from({"max_mb": 1.5})["max_bytes"] == 1572864


def test_file_count_includes_files_already_attached():
    eleven = [_upload(f"{n}.pdf", ref=f"r{n}") for n in range(11)]
    with pytest.raises(att.AttachmentError):
        att.parse_uploads(eleven)
    assert len(att.parse_uploads(eleven[:10])) == 10
    with pytest.raises(att.AttachmentError):
        att.parse_uploads(eleven[:3], existing_files=8)
    assert len(att.parse_uploads(eleven[:2], existing_files=8)) == 2


def test_per_file_and_total_size_limits():
    big = b"x" * (10 * 1024 * 1024)
    assert att.parse_uploads([_upload("a.pdf", data=big)])
    with pytest.raises(att.AttachmentError):
        att.parse_uploads([_upload("a.pdf", data=big + b"x")])
    with pytest.raises(att.AttachmentError):
        att.parse_uploads([_upload("a.pdf", data=b"")])
    third = [_upload(f"{n}.pdf", ref=f"r{n}", data=big) for n in range(3)]
    with pytest.raises(att.AttachmentError):
        att.parse_uploads(third)  # 30 MB in total
    assert len(att.parse_uploads(third[:2])) == 2
    with pytest.raises(att.AttachmentError):
        att.parse_uploads(third[:1], existing_bytes=16 * 1024 * 1024)


@pytest.mark.parametrize("bad", [
    "not a list", [None], [{"filename": "a.pdf"}], [{"filename": "a.pdf", "content_base64": 5}],
    [{"filename": "a.pdf", "content_base64": "###"}],
    [{"filename": "a.pdf", "content_base64": _b64(), "ref": "has space"}],
    [{"filename": "a.pdf", "content_base64": _b64(), "ref": 5}],
])
def test_malformed_uploads_are_rejected(bad):
    with pytest.raises(att.AttachmentError):
        att.parse_uploads(bad)


def test_filename_is_reduced_to_its_basename():
    assert att.parse_uploads([_upload("../../etc/a.pdf")])[0].filename == "a.pdf"
    assert att.parse_uploads([_upload("C:\\temp\\b.pdf")])[0].filename == "b.pdf"


def test_scope_of_a_file_is_its_first_reference():
    references = [("field:proof", "attachment:att-1"), ("row:items:1", "attachment:att-2"),
                  ("row:items:2", "attachment:att-2"), ("field:old", "/private/files/old.pdf")]
    urls = {"attachment:att-1": "/private/files/a.pdf", "attachment:att-2": "/private/files/b.png"}
    assert att.file_scopes(references, urls) == {
        "/private/files/a.pdf": "field:proof", "/private/files/b.png": "row:items:1",
        "/private/files/old.pdf": "field:old"}
    assert att.file_scopes([], urls) == {}


def test_entries_carry_every_contract_key():
    assert att.entry("1a2b", "m.png", "/private/files/m.png", 18211, "row:items:0") == {
        "name": "1a2b", "filename": "m.png", "file_url": "/private/files/m.png", "size": 18211,
        "content_type": "image/png", "is_image": True, "scope": "row:items:0"}
    legacy = att.complete_entry({"name": "x", "filename": "r.pdf", "file_url": "/private/files/r.pdf"})
    assert legacy["content_type"] == "application/pdf" and legacy["is_image"] is False
    assert legacy["scope"] == "general" and legacy["size"] == 0
    assert att.complete_entry({"name": "x", "filename": "r.pdf", "file_url": "u", "scope": "field:a"})["scope"] == "field:a"


def _image(size, fmt, color=(200, 30, 30)):
    from PIL import Image

    stream = BytesIO()
    Image.new("RGB", size, color).save(stream, format=fmt)
    return stream.getvalue()


@pytest.mark.parametrize("fmt,name", [("PNG", "m.png"), ("JPEG", "m.jpg")])
def test_thumbnail_is_scaled_to_256_px(fmt, name):
    pytest.importorskip("PIL")
    from PIL import Image

    original = _image((1024, 512), fmt)
    result = att.thumbnail(original, name)
    with Image.open(BytesIO(result)) as image:
        assert max(image.size) == 256 and image.size == (256, 128)
        assert image.format == fmt
    small = att.thumbnail(_image((40, 30), fmt), name)
    with Image.open(BytesIO(small)) as image:
        assert image.size == (40, 30)


def test_thumbnail_ignores_non_images_and_unreadable_images():
    assert att.thumbnail(b"%PDF-1.4", "a.pdf") == b"%PDF-1.4"
    pytest.importorskip("PIL")  # not installed in the lightweight contract CI job
    assert att.thumbnail(b"not an image", "a.png") == b"not an image"
