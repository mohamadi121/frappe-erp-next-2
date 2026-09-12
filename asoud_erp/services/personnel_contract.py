import base64
from datetime import date, time

PERSONAL_FIELDS = {
    "display_name", "national_id", "birth_date", "employee_gender", "father_name",
    "mobile", "phone", "email", "province", "city", "address_line", "postal_code",
    "date_of_joining", "job_title", "department", "employment_type",
}


def validate_record(data):
    if data.get("kind") not in {"attendance", "evaluation", "document", "photo", "history"}:
        raise ValueError("Invalid record kind")
    if not 1 <= len(str(data.get("title", "")).strip()) <= 140:
        raise ValueError("Title is required (maximum 140 characters)")
    date.fromisoformat(data.get("date", ""))
    if len(str(data.get("notes", ""))) > 5000:
        raise ValueError("Notes exceed 5000 characters")
    if data["kind"] == "attendance":
        if time.fromisoformat(data.get("start", "")) >= time.fromisoformat(data.get("end", "")):
            raise ValueError("End time must be later than start time")
    if data["kind"] == "evaluation":
        score = data.get("score")
        if isinstance(score, bool) or not isinstance(score, (int, float)) or not 0 <= score <= 100:
            raise ValueError("Score must be between 0 and 100")
    if data["kind"] in {"photo", "document"}:
        if len(data.get("file", "")) > 7 * 1024 * 1024:
            raise ValueError("File exceeds size limit")
        raw = base64.b64decode(data.get("file", ""), validate=True)
        if not raw or len(raw) > 5 * 1024 * 1024:
            raise ValueError("File must be between 1 byte and 5 MB")
        image = raw.startswith(b"\xff\xd8\xff") or raw.startswith(b"\x89PNG\r\n\x1a\n")
        if not image and not (data["kind"] == "document" and raw.startswith(b"%PDF-")):
            raise ValueError("Only JPEG, PNG and PDF documents are accepted")
    return {key: data[key] for key in
            ("kind", "title", "date", "notes", "start", "end", "score", "file", "filename") if key in data}
