"""Pure template validation and immutable snapshots for employment certificates."""

import re
from copy import deepcopy
from html import escape

MISSING_MESSAGE = "اطلاعات موجود نیست"
PERIODS = {"monthly", "yearly", "one_off"}
_DIGITS = str.maketrans("۰۱۲۳۴۵۶۷۸۹٠١٢٣٤٥٦٧٨٩", "01234567890123456789")
_TOKEN = re.compile(r"{{([a-z][a-z0-9_]*(?:\.[a-z][a-z0-9_]*)*)}}")


def normalize_search(value: object) -> str:
    return re.sub(r"\s+", " ", str(value or "").translate(_DIGITS).replace("ي", "ی").replace("ك", "ک")).strip().lower()


def _token_value(token: str, values: dict) -> str:
    current = values
    for part in token.split("."):
        if not isinstance(current, dict):
            return ""
        current = current.get(part)
    return "" if current is None else escape(str(current))


def validate_template(template: dict) -> dict:
    if not isinstance(template, dict) or not isinstance(template.get("clauses"), list):
        raise ValueError("ساختار قالب گواهی معتبر نیست.")
    enabled = template.get("salary_enabled")
    if not isinstance(enabled, bool) or not isinstance(template.get("salary_rows"), list):
        raise ValueError("تنظیمات حقوق گواهی معتبر نیست.")
    clause_ids = set()
    clauses = []
    for clause in template["clauses"]:
        if not isinstance(clause, dict) or not isinstance(clause.get("id"), str) or not re.fullmatch(r"[a-z][a-z0-9_]{0,59}", clause["id"]) or clause["id"] in clause_ids:
            raise ValueError("شناسه پایدار بند معتبر نیست.")
        body = clause.get("body")
        if not isinstance(clause.get("title"), str) or not clause["title"].strip() or not isinstance(body, str):
            raise ValueError("عنوان و متن بند را کامل کنید.")
        for raw in re.findall(r"{{(.*?)}}", body):
            if not _TOKEN.fullmatch("{{" + raw + "}}"):
                raise ValueError("شناسه فیلد در متن بند معتبر نیست.")
        clause_ids.add(clause["id"])
        clauses.append({"id": clause["id"], "title": clause["title"].strip(), "body": body, "enabled": clause.get("enabled") is not False})
    rows = []
    row_ids = set()
    for row in template["salary_rows"]:
        if not isinstance(row, dict) or not isinstance(row.get("id"), str) or row["id"] in row_ids or row.get("period") not in PERIODS or not isinstance(row.get("field_ref"), str) or not re.fullmatch(r"[a-z][a-z0-9_]*(?:\.[a-z][a-z0-9_]*)*", row["field_ref"]):
            raise ValueError("شناسه فیلد حقوق معتبر نیست.")
        if not isinstance(row.get("title"), str) or not row["title"].strip():
            raise ValueError("عنوان قلم حقوق را کامل کنید.")
        row_ids.add(row["id"])
        rows.append({key: row[key] for key in ("id", "title", "field_ref", "period")})
    if enabled and not rows:
        raise ValueError("برای بخش حقوق حداقل یک قلم لازم است.")
    return {"clauses": clauses, "salary_enabled": enabled, "salary_rows": rows}


def render_snapshot(template: dict, values: dict, salary_rows: list[dict] | None = None) -> dict:
    """Render only the published template; salary is unreachable when disabled."""
    template = validate_template(template)
    values = values if isinstance(values, dict) else {}
    blocks = []
    for clause in template["clauses"]:
        if clause["enabled"]:
            body = _TOKEN.sub(lambda match: _token_value(match.group(1), values), clause["body"])
            blocks.append(f"<section><h3>{escape(clause['title'])}</h3><p>{body}</p></section>")
    snapshot_rows = []
    if template["salary_enabled"]:
        source = {row.get("id"): row for row in salary_rows or [] if isinstance(row, dict)}
        for definition in template["salary_rows"]:
            source_row = source.get(definition["id"], {})
            amount = source_row.get("amount")
            snapshot = {**definition, "amount": amount}
            if amount is None:
                snapshot.update({"state": "missing", "message": MISSING_MESSAGE})
            else:
                snapshot["state"] = "available"
            snapshot_rows.append(snapshot)
        cells = "".join(f"<tr><td>{escape(row['title'])}</td><td>{escape(str(row.get('amount'))) if row.get('amount') is not None else MISSING_MESSAGE}</td></tr>" for row in snapshot_rows)
        blocks.append("<table><tbody>" + cells + "</tbody></table>")
    return {"template": deepcopy(template), "values": deepcopy(values), "salary_rows": snapshot_rows, "html": "<article dir=\"rtl\">" + "".join(blocks) + "</article>"}
