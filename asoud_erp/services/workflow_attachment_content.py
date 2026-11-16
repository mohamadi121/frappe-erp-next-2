"""Content sniffing for workflow task attachments.

The client-supplied extension is not trusted: the server checks the actual bytes
(magic numbers) against the extension before storing the file, so a malicious
payload cannot be smuggled in behind a harmless name.
"""

# Magic-number signatures, checked in order. Each entry is (extension, predicate).
_SIGNATURES = {
    ".pdf": lambda c: c.startswith(b"%PDF-"),
    ".png": lambda c: c.startswith(b"\x89PNG\r\n\x1a\n"),
    ".jpg": lambda c: c.startswith(b"\xff\xd8\xff"),
    ".jpeg": lambda c: c.startswith(b"\xff\xd8\xff"),
    ".xlsx": lambda c: c.startswith(b"PK\x03\x04"),
    ".docx": lambda c: c.startswith(b"PK\x03\x04"),
}


def content_matches_extension(content: bytes, extension: str) -> bool:
    """True when the bytes carry the magic number of ``extension``.

    ``.xlsx`` and ``.docx`` are both ZIP containers (``PK\x03\x04``); the extension
    still decides which one the caller asked for, so both map to the ZIP signature.
    """
    check = _SIGNATURES.get(extension.lower())
    if check is None:
        return False
    return bool(check(content))
