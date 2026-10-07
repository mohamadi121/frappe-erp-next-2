"""Files attached to a request: upload parsing and limits, references, scopes, thumbnails.

Uploads arrive inline (`{filename, content_base64, ref?}`). A form value points at an
upload with `attachment:<ref>` (or `attachment:<filename>` when no `ref` is given).
The pure helpers need no frappe; `store_uploads` and `delete_files` import it lazily.
"""

from __future__ import annotations

import base64
import binascii
import mimetypes
import re
from dataclasses import dataclass
from io import BytesIO
from pathlib import PurePosixPath

from asoud_erp.services.request_templates.base import ERROR_MESSAGES

DEFAULT_EXTENSIONS = ("pdf", "png", "jpg", "jpeg", "xls", "xlsx", "doc", "docx")
IMAGE_EXTENSIONS = ("png", "jpg", "jpeg")
MAX_FILES = 10
MAX_FILE_BYTES = 10 * 1024 * 1024
MAX_TOTAL_BYTES = 25 * 1024 * 1024
MAX_BASE64_LENGTH = 14 * 1024 * 1024
THUMBNAIL_SIDE = 256
REFERENCE_PREFIX = "attachment:"
REF_PATTERN = re.compile(r"^[A-Za-z0-9_-]{1,40}$")


class AttachmentError(ValueError):
    """An invalid upload; the message is shown to the user (code ATTACHMENT_INVALID)."""

    def __init__(self, message: str | None = None):
        super().__init__(message or ERROR_MESSAGES["ATTACHMENT_INVALID"])


@dataclass(frozen=True)
class Upload:
    filename: str
    content: bytes
    ref: str | None = None

    @property
    def key(self) -> str:
        """How a form value references this upload."""
        return REFERENCE_PREFIX + (self.ref or self.filename)


def extension(filename: str) -> str:
    return PurePosixPath(filename).suffix.lower().lstrip(".")


def is_image(filename: str) -> bool:
    return extension(filename) in IMAGE_EXTENSIONS


def content_type(filename: str) -> str:
    return mimetypes.guess_type(filename)[0] or "application/octet-stream"


def limits_from(config: dict | None) -> dict:
    """`{extensions, max_files, max_bytes}` from a template's `attachments` config."""
    config = config or {}
    extensions = tuple(str(item).lower().lstrip(".") for item in config.get("extensions") or DEFAULT_EXTENSIONS)
    max_files = min(int(config.get("max_files") or MAX_FILES), MAX_FILES)
    max_bytes = min(int(float(config.get("max_mb") or 10) * 1024 * 1024), MAX_FILE_BYTES)
    return {"extensions": extensions, "max_files": max_files, "max_bytes": max_bytes}


def parse_uploads(raw, *, extensions=DEFAULT_EXTENSIONS, max_files=MAX_FILES, max_bytes=MAX_FILE_BYTES,
                  existing_files=0, existing_bytes=0) -> list[Upload]:
    """Validates inline uploads: type, size, count, total size and unique references."""
    if not isinstance(raw, list):
        raise AttachmentError()
    if existing_files + len(raw) > max_files:
        raise AttachmentError(f"حداکثر {max_files} پیوست مجاز است.")
    uploads: list[Upload] = []
    keys: set[str] = set()
    total = existing_bytes
    for item in raw:
        if not isinstance(item, dict):
            raise AttachmentError()
        filename = PurePosixPath(str(item.get("filename") or "").replace(chr(92), "/")).name
        encoded = item.get("content_base64")
        if not filename or not isinstance(encoded, str) or len(encoded) > MAX_BASE64_LENGTH:
            raise AttachmentError("حجم یا نام پیوست معتبر نیست.")
        if extension(filename) not in extensions:
            raise AttachmentError("نوع این پیوست مجاز نیست.")
        ref = item.get("ref")
        if ref is not None and (not isinstance(ref, str) or not REF_PATTERN.fullmatch(ref)):
            raise AttachmentError("شناسهٔ پیوست معتبر نیست.")
        try:
            content = base64.b64decode(encoded, validate=True)
        except (ValueError, binascii.Error) as error:
            raise AttachmentError("محتوای پیوست معتبر نیست.") from error
        total += len(content)
        if not content or len(content) > max_bytes or total > MAX_TOTAL_BYTES:
            raise AttachmentError(f"حجم هر پیوست باید حداکثر {max_bytes // (1024 * 1024)} مگابایت و مجموع آن‌ها "
                                  f"حداکثر {MAX_TOTAL_BYTES // (1024 * 1024)} مگابایت باشد.")
        upload = Upload(filename=filename, content=content, ref=ref or None)
        if upload.key in keys:
            raise AttachmentError("نام یا شناسهٔ پیوست‌ها باید یکتا باشد.")
        keys.add(upload.key)
        uploads.append(upload)
    return uploads


def file_scopes(references: list[tuple[str, str]], key_to_url: dict[str, str]) -> dict[str, str]:
    """`file_url -> scope` from `(scope, reference)` pairs; the first reference of a file wins."""
    scopes: dict[str, str] = {}
    for scope, value in references:
        scopes.setdefault(key_to_url.get(value, value), scope)
    return scopes


def entry(name: str, filename: str, file_url: str, size: int, scope: str = "general") -> dict:
    """One `attachments_json` entry."""
    return {"name": name, "filename": filename, "file_url": file_url, "size": int(size or 0),
            "content_type": content_type(filename), "is_image": is_image(filename), "scope": scope}


def complete_entry(stored: dict, scope: str = "general") -> dict:
    """A stored entry with every contract key (legacy rows only had name, filename and file_url)."""
    filename = stored.get("filename") or ""
    return {
        "name": stored.get("name"), "filename": filename, "file_url": stored.get("file_url"),
        "size": int(stored.get("size") or 0),
        "content_type": stored.get("content_type") or content_type(filename),
        "is_image": bool(stored["is_image"]) if "is_image" in stored else is_image(filename),
        "scope": stored.get("scope") or scope,
    }


def thumbnail(content: bytes, filename: str, max_side: int = THUMBNAIL_SIDE) -> bytes:
    """The image scaled so its longest side is at most `max_side`; other files are returned as is."""
    if not is_image(filename):
        return content
    from PIL import Image, UnidentifiedImageError

    try:
        with Image.open(BytesIO(content)) as image:
            image.thumbnail((max_side, max_side))
            output = BytesIO()
            if extension(filename) == "png":
                image.save(output, format="PNG", optimize=True)
            else:
                image.convert("RGB").save(output, format="JPEG", quality=80, optimize=True)
            return output.getvalue()
    except (UnidentifiedImageError, OSError):
        return content


def store_uploads(request_name: str, uploads: list[Upload]) -> list[dict]:
    """Saves uploads as private Files of the request; returns `[{upload, name, file_url, size}]`."""
    import frappe

    stored = []
    for upload in uploads:
        # The request permission was checked by the caller; the File is private and request-bound.
        file_doc = frappe.get_doc({
            "doctype": "File", "file_name": upload.filename, "content": upload.content,
            "attached_to_doctype": "ASOUD Workflow Request", "attached_to_name": request_name,
            "is_private": 1,
        }).insert(ignore_permissions=True)
        stored.append({"upload": upload, "name": file_doc.name, "file_url": file_doc.file_url,
                       "size": len(upload.content), "hash": file_doc.content_hash})
    return stored


def delete_files(names: list[str]) -> None:
    import frappe

    for name in names:
        # The caller is the request owner and the names were matched against the request's own files.
        frappe.delete_doc("File", name, ignore_permissions=True, force=True)
