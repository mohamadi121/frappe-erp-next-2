import base64
from datetime import date, time

PERSONAL_FIELDS = {
    "display_name", "national_id", "birth_date", "employee_gender", "father_name",
    "mobile", "phone", "email", "province", "city", "address_line", "postal_code",
    "date_of_joining", "job_title", "department", "employment_type",
    # Stored on Employee (see personnel_employee.EMPLOYEE_FIELDS).
    "marital_status", "blood_group", "emergency_contact_name", "emergency_phone",
    "emergency_relation", "company_email", "branch", "reports_to",
    "final_confirmation_date", "contract_end_date", "notice_number_of_days",
}

# Bank details stay on the ERPNext Employee form; this API neither edits nor returns them.

DOCUMENT_CATEGORIES = {"Identity", "Education", "Employment", "Medical", "Financial", "Other"}

FINANCIAL_FIELDS = {
    "base_salary", "housing_allowance", "transport_allowance", "other_allowances",
    "deductions", "net_salary",
}


def validate_record(data):
    if not isinstance(data, dict):
        raise ValueError("Record must be an object")
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
    if data["kind"] == "document":
        if data.get("document_category") not in (None, "", *DOCUMENT_CATEGORIES):
            raise ValueError("Invalid document category")
        if len(str(data.get("document_number") or "")) > 140:
            raise ValueError("Document number is too long")
        if data.get("expiry_date"):
            if date.fromisoformat(data["expiry_date"]) < date.fromisoformat(data["date"]):
                raise ValueError("Expiry date must not be before the issue date")
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
            ("kind", "title", "date", "notes", "start", "end", "score", "file", "filename", "appraisal_cycle",
             "document_category", "document_number", "expiry_date") if key in data}


def validate_financial(data):
    import math

    for key in FINANCIAL_FIELDS.intersection(data):
        value = data[key]
        if value in (None, ""):
            continue
        try:
            if isinstance(value, bool) or not math.isfinite(float(value)) or not 0 <= float(value) <= 10**15:
                raise ValueError("Invalid financial amount")
        except (TypeError, ValueError) as exc:
            raise ValueError(f"Invalid financial amount: {key}") from exc
