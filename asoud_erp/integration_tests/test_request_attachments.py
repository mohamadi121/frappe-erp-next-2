"""Request attachments: refs, row files, scopes, limits, update add/remove and thumbnails."""

import base64
from io import BytesIO

import frappe

from asoud_erp.api.v1 import workflow_request
from asoud_erp.integration_tests.fixtures import EMPLOYEE_USER, ITEM, APITestCase
from asoud_erp.integration_tests.request_fixtures import make_definition
from asoud_erp.integration_tests.request_helpers import clear_request_records, create, valid_pdf_bytes


def b64(data: bytes) -> str:
    return base64.b64encode(data).decode()


def png(width: int, height: int) -> bytes:
    from PIL import Image

    stream = BytesIO()
    Image.new("RGB", (width, height), (30, 90, 200)).save(stream, format="PNG")
    return stream.getvalue()


def jpg(width: int, height: int) -> bytes:
    from PIL import Image

    stream = BytesIO()
    Image.new("RGB", (width, height), (30, 90, 200)).save(stream, format="JPEG")
    return stream.getvalue()


def attachment_bytes(filename: str) -> bytes:
    if filename.endswith(".pdf"):
        return valid_pdf_bytes()
    if filename.endswith(".png"):
        return png(2, 2)
    if filename.endswith((".jpg", ".jpeg")):
        return jpg(2, 2)
    return filename.encode()


class TestRequestAttachments(APITestCase):
    def setUp(self):
        super().setUp()
        clear_request_records()
        self.definition, _stages = make_definition(self.company)

    def _create(self, uploads, values=None, **kwargs):
        return create(self.company, definition=self.definition, values=values or {}, attachments=uploads, **kwargs)

    def test_refs_allow_duplicate_names_and_resolve_to_fields_and_rows(self):
        uploads = [{"filename": "price.pdf", "content_base64": b64(valid_pdf_bytes()), "ref": "att-1"},
                   {"filename": "price.pdf", "content_base64": b64(valid_pdf_bytes()), "ref": "att-2"},
                   {"filename": "photo.png", "content_base64": b64(png(8, 8)), "ref": "att-3"},
                   {"filename": "free.docx", "content_base64": b64(b"word"), "ref": "att-4"}]
        detail = self._create(uploads, {"proof": "attachment:att-1", "items": [
            {"item_code": ITEM, "qty": 2, "note": "فوری", "attachment": "attachment:att-3"},
            {"item_code": ITEM, "qty": 1}]})
        entries = {entry["scope"]: entry for entry in detail["attachments"]}
        self.assertEqual(set(entries), {"field:proof", "row:items:0", "general"})
        self.assertEqual(detail["attachment_count"], 4)
        for entry in detail["attachments"]:
            self.assertEqual(set(entry), {"name", "filename", "file_url", "size", "content_type", "is_image",
                                          "scope"})
            self.assertTrue(entry["file_url"].startswith("/private/files/"))
        self.assertEqual(entries["row:items:0"]["is_image"], True)
        self.assertEqual(entries["row:items:0"]["content_type"], "image/png")
        self.assertEqual(detail["values"]["proof"], entries["field:proof"]["file_url"])
        row = detail["values"]["items"][0]
        self.assertEqual(row["attachment"], entries["row:items:0"]["file_url"])
        self.assertEqual(row["attachment_ref"]["name"], entries["row:items:0"]["name"])
        self.assertNotIn("attachment_ref", detail["values"]["items"][1])
        stored = frappe.db.get_value("ASOUD Workflow Request", detail["name"], "values_json")
        self.assertNotIn("attachment_ref", stored)
        self.assertEqual(frappe.db.count("File", {"attached_to_doctype": "ASOUD Workflow Request",
                                                  "attached_to_name": detail["name"], "is_private": 1}), 4)

    def test_references_must_point_at_an_upload(self):
        uploads = [{"filename": "a.pdf", "content_base64": b64(valid_pdf_bytes()), "ref": "a"}]
        for values in ({"proof": "attachment:ghost"}, {"proof": "/private/files/other.pdf"}):
            with self.assertRaises(frappe.ValidationError):
                self._create(uploads, values)
        self.assertFalse(frappe.db.exists("ASOUD Workflow Request", {"subject": "درخواست آزمایشی"}))

    def test_limits(self):
        def pdf(index, size=10):
            return {"filename": f"{index}.pdf", "content_base64": b64(valid_pdf_bytes(size)), "ref": f"r{index}"}

        self.assertEqual(self._create([pdf(index) for index in range(10)])["attachment_count"], 10)
        for uploads in ([pdf(index) for index in range(11)],
                        [pdf(0, 10 * 1024 * 1024 + 1)],
                        [pdf(index, 9 * 1024 * 1024) for index in range(3)],
                        [{"filename": "run.exe", "content_base64": b64(b"x")}],
                        [{"filename": "a.pdf", "content_base64": "###"}]):
            with self.assertRaises(frappe.ValidationError):
                self._create(uploads)
        self.assertEqual(self._create([pdf(0, 10 * 1024 * 1024)])["attachment_count"], 1)

    def test_excel_and_word_files_are_allowed(self):
        names = ["a.xls", "b.xlsx", "c.doc", "d.docx", "e.pdf", "f.jpg", "g.jpeg", "h.png"]
        uploads = [
            {"filename": name, "content_base64": b64(attachment_bytes(name)), "ref": f"f{index}"}
            for index, name in enumerate(names)
        ]
        self.assertEqual(self._create(uploads)["attachment_count"], 8)

    def test_update_adds_and_removes_files_and_clears_their_references(self):
        created = self._create(
            [{"filename": "a.pdf", "content_base64": b64(valid_pdf_bytes()), "ref": "a"},
             {"filename": "b.png", "content_base64": b64(png(4, 4)), "ref": "b"}],
            {"proof": "attachment:a", "items": [{"item_code": ITEM, "qty": 1, "attachment": "attachment:b"}]})
        proof = next(e for e in created["attachments"] if e["scope"] == "field:proof")
        row_file = next(e for e in created["attachments"] if e["scope"] == "row:items:0")
        frappe.set_user(EMPLOYEE_USER)
        updated = workflow_request.update_request(
            created["name"], "", {"proof": proof["file_url"], "items": [
                {"item_code": ITEM, "qty": 2, "attachment": "attachment:c"}]},
            attachments=[{"filename": "c.pdf", "content_base64": b64(valid_pdf_bytes(512)), "ref": "c"}],
            remove_attachments=[row_file["name"]])["data"]
        names = {entry["name"] for entry in updated["attachments"]}
        self.assertIn(proof["name"], names)
        self.assertNotIn(row_file["name"], names)
        self.assertEqual(len(updated["attachments"]), 2)
        self.assertFalse(frappe.db.exists("File", row_file["name"]))
        new = next(entry for entry in updated["attachments"] if entry["scope"] == "row:items:0")
        self.assertEqual((new["filename"], updated["values"]["items"][0]["attachment_ref"]["name"]),
                         ("c.pdf", new["name"]))
        cleared = workflow_request.update_request(
            created["name"], "", {"proof": proof["file_url"], "items": [{"item_code": ITEM, "qty": 2}]},
            remove_attachments=[proof["name"]])["data"]
        self.assertIsNone(cleared["values"]["proof"])
        self.assertEqual([entry["name"] for entry in cleared["attachments"]], [new["name"]])
        foreign = frappe.get_doc({"doctype": "File", "file_name": "other.txt", "content": b"other",
                                  "attached_to_doctype": "Item", "attached_to_name": ITEM,
                                  "is_private": 1}).insert(ignore_permissions=True)
        with self.assertRaises(frappe.ValidationError):  # a file of another document
            workflow_request.update_request(created["name"], "", {}, remove_attachments=[foreign.name])
        self.assertTrue(frappe.db.exists("File", foreign.name))
        with self.assertRaises(frappe.DoesNotExistError):
            workflow_request.get_attachment(row_file["name"])

    def test_thumbnails_are_at_most_256_px_and_non_images_ignore_the_flag(self):
        from PIL import Image

        created = self._create(
            [{"filename": "big.png", "content_base64": b64(png(1024, 512)), "ref": "big"},
             {"filename": "sheet.xlsx", "content_base64": b64(b"not really a sheet"), "ref": "sheet"}])
        image = next(e for e in created["attachments"] if e["filename"] == "big.png")
        sheet = next(e for e in created["attachments"] if e["filename"] == "sheet.xlsx")
        frappe.set_user(EMPLOYEE_USER)
        thumb = workflow_request.get_attachment(image["name"], thumbnail=1)["data"]
        self.assertEqual(thumb["content_type"], "image/png")
        with Image.open(BytesIO(base64.b64decode(thumb["content_base64"]))) as picture:
            self.assertEqual(max(picture.size), 256)
        full = workflow_request.get_attachment(image["name"])["data"]
        with Image.open(BytesIO(base64.b64decode(full["content_base64"]))) as picture:
            self.assertEqual(picture.size, (1024, 512))
        self.assertEqual(full["size"], image["size"])
        plain = workflow_request.get_attachment(sheet["name"], thumbnail=1)["data"]
        self.assertEqual(base64.b64decode(plain["content_base64"]), b"not really a sheet")
        self.assertEqual(plain["filename"], "sheet.xlsx")

    def test_only_participants_download_attachments(self):
        created = self._create([{"filename": "a.pdf", "content_base64": b64(valid_pdf_bytes()), "ref": "a"}])
        frappe.set_user("asoud.accountant@example.com")
        with self.assertRaises(frappe.PermissionError):
            workflow_request.get_attachment(created["attachments"][0]["name"])
