"""Pure regression: attachment content is checked against its extension (PA-044).

Runs the real ``upload_workflow_attachment`` against the in-memory fake site. The
client-supplied extension is not trusted: the bytes must carry the magic number of
the extension, so a malicious payload cannot hide behind a harmless name.
"""

import base64

import pytest

from asoud_erp.tests import _fake_site as fake
from asoud_erp.tests._workflow_access_world import make_world


def _b64(data: bytes) -> str:
    return base64.b64encode(data).decode()


def _open_task(site, task="T1", user="sara@example.com"):
    site.add("ASOUD Workflow Instance", "WFI-1", status="Running", started_by="other@example.com",
             reference_doctype=None)
    site.add("ASOUD Workflow Stage", "STAGE-1", stage_type="User Task", config_json="{}")
    site.add("ASOUD Workflow Task", task, workflow_instance="WFI-1", workflow_stage="STAGE-1",
             status="Open", assigned_to=user)


@pytest.fixture
def world(monkeypatch):
    w, restore = make_world(monkeypatch)
    yield w
    restore()


def test_upload_rejects_content_that_spoofs_the_extension(world):
    site = world.site
    _open_task(site)
    # A PNG payload named .pdf must be refused: the content is not a PDF.
    png = b"\x89PNG\r\n\x1a\n" + b"fake-png-bytes"
    with pytest.raises(fake.ValidationError):
        world.runtime.upload_workflow_attachment("T1", "invoice.pdf", _b64(png))


def test_upload_rejects_non_zip_content_named_xlsx(world):
    site = world.site
    _open_task(site)
    with pytest.raises(fake.ValidationError):
        world.runtime.upload_workflow_attachment("T1", "sheet.xlsx", _b64(b"not a zip file at all"))


def test_upload_accepts_content_matching_the_extension(world):
    site = world.site
    _open_task(site)
    result = world.runtime.upload_workflow_attachment("T1", "invoice.pdf", _b64(b"%PDF-1.7 body"))
    assert result["ok"] is True
    assert result["data"]["file_name"] == "invoice.pdf"


def test_upload_still_rejects_unknown_extension(world):
    site = world.site
    _open_task(site)
    with pytest.raises(fake.ValidationError):
        world.runtime.upload_workflow_attachment("T1", "malware.exe", _b64(b"MZ..."))
