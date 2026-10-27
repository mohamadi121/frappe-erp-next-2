# Employment Contracts API (قالب‌ساز و صدور قراردادهای پرسنلی)

`asoud_erp.api.v1.employment_contracts` provides backend services for:
1. **Contract Template Builder** (قالب قرارداد کار): versioned articles/clauses, stable field binding, repeating salary items table, and computed fields.
2. **Field Catalog** (کاتالوگ فیلدهای درج): real sources from Personnel (Employee), Company, Contract form, and Payroll (permission-gated).
3. **Personnel Contracts Issuance** (صدور و مدیریت قراردادها): server-side search, status filtering, draft saving, finalization with Jalali-year numbering, immutable snapshots, workflow integration, and A4 RTL print payload.

---

## 1. Role & Permission Separation

- **Template Design / Edit**: Restricted to `System Manager` and `HR Manager`. Operational HR users (`HR User`) cannot edit template articles or repeating salary configurations.
- **Contract Issuance / Operational**: `System Manager`, `HR Manager`, and `HR User`.
- **Payroll Information Access**: Reading or inserting payroll fields (`payroll.*`) and viewing salary amounts requires payroll access (`HR Manager`, `Accounts Manager`, or `System Manager`). For callers without payroll access, payroll fields are flagged unauthorized and amounts are masked.
- **Office / Company Scope**: Every endpoint enforces company and office scope via `require_company(company)`. Cross-office leaks are blocked.

---

## 2. Template Builder Endpoints

### 2.1 `get_contract_template`
Retrieves the contract template for a company.

- **Method**: `GET` or `POST`
- **Path**: `asoud_erp.api.v1.employment_contracts.get_contract_template`
- **Arguments**:
  - `company` (str, required): Company name / office.
  - `template_id` (str, optional): Specific template name if multiple exist.
- **Response**:
  ```json
  {
    "ok": true,
    "data": {
      "template_id": "hr-contract-template-...",
      "title": "قالب قرارداد کار",
      "company": "شرکت تابان",
      "version": 1,
      "draft_version": 1,
      "has_draft": false,
      "can_edit_template": true,
      "clauses": [
        {
          "id": "clause_1",
          "title": "طرفین قرارداد",
          "body": "این قرارداد میان {{company.company_name}} به نمایندگی {{company.legal_representative}} و {{personnel.employee_name}} تنظیم می‌شود.",
          "order": 1
        },
        {
          "id": "clause_2",
          "title": "موضوع و محل کار",
          "body": "موضوع همکاری، عنوان شغل و محل انجام کار مطابق اطلاعات درج‌شده در قرارداد تعیین می‌شود.",
          "order": 2
        },
        {
          "id": "clause_3",
          "title": "مدت همکاری",
          "body": "تاریخ شروع همکاری {{contract.start_date}} و تاریخ پایان در قراردادهای مدت‌معین {{contract.end_date}} است.",
          "order": 3
        },
        {
          "id": "clause_4",
          "title": "حقوق و مزایا",
          "body": "حقوق و مزایای طرف قرارداد مطابق اقلام مندرج در جدول زیر و مقررات مربوط تعیین می‌شود.",
          "order": 4
        },
        {
          "id": "clause_5",
          "title": "تعهدات طرفین",
          "body": "شرایط محرمانگی، مسئولیت‌ها و سایر تعهدات مطابق متن مصوب قرارداد خواهد بود.",
          "order": 5
        }
      ],
      "salary_rows": [
        {"id": "row_1", "name": "حقوق پایه", "period": "monthly", "fieldRef": "payroll.base_salary"},
        {"id": "row_2", "name": "حق مسکن", "period": "monthly", "fieldRef": "payroll.housing"},
        {"id": "row_3", "name": "بن خواربار", "period": "monthly", "fieldRef": "payroll.food"}
      ],
      "computed_fields": [
        {"id": "total_monthly", "name": "مجموع ناخالص ماهانه", "period": "monthly"}
      ]
    }
  }
  ```

### 2.2 `save_contract_template`
Saves draft template changes (articles, order, salary rows).

- **Method**: `POST`
- **Path**: `asoud_erp.api.v1.employment_contracts.save_contract_template`
- **Arguments**:
  - `company` (str, required)
  - `clauses` (list of dict, required): `[{id, title, body, order}]`
  - `salary_rows` (list of dict, required): `[{id, name, period, fieldRef}]`
  - `title` (str, optional, default: `"قالب قرارداد کار"`)
  - `expected_version` (int, optional, default: `0`): Optimistic concurrency check.
  - `client_id` (str, optional): Idempotency key.
- **Errors**:
  - 403: `ویرایش قالب قرارداد نیازمند نقش مدیر منابع انسانی یا مدیر سیستم است.`
  - 417: `نسخه پیش‌نویس قالب تغییر کرده است؛ لطفاً صفحه را تازه‌سازی کنید.`

### 2.3 `publish_contract_template`
Publishes the draft template as a new immutable revision.

- **Method**: `POST`
- **Path**: `asoud_erp.api.v1.employment_contracts.publish_contract_template`
- **Arguments**:
  - `company` (str, required)
  - `template_id` (str, optional)
  - `expected_version` (int, optional)
  - `change_note` (str, optional): Description of changes.
- **Rule**: Existing issued contracts are never modified by publishing a new revision.

---

## 3. Field Catalog for Insert-Field Drawer

### 3.1 `get_contract_field_catalog`
Returns available insertable fields from real data sources.

- **Method**: `GET` or `POST`
- **Path**: `asoud_erp.api.v1.employment_contracts.get_contract_field_catalog`
- **Arguments**:
  - `company` (str, required)
- **Response**:
  ```json
  {
    "ok": true,
    "data": {
      "categories": [
        {
          "key": "personnel",
          "label": "اطلاعات پرسنل",
          "fields": [
            {"id": "personnel.employee_name", "label": "نام و نام خانوادگی", "type": "Text", "source": "Employee.employee_name"},
            {"id": "personnel.national_id", "label": "کد ملی", "type": "Text", "source": "Employee.national_id"},
            {"id": "personnel.father_name", "label": "نام پدر", "type": "Text", "source": "Employee.father_name"},
            {"id": "personnel.employee_number", "label": "کد پرسنلی", "type": "Text", "source": "Employee.name"},
            {"id": "personnel.department", "label": "واحد سازمانی", "type": "Text", "source": "Employee.department"},
            {"id": "personnel.job_title", "label": "عنوان شغلی", "type": "Text", "source": "Employee.designation"},
            {"id": "personnel.date_of_joining", "label": "تاریخ شروع همکاری", "type": "Date", "source": "Employee.date_of_joining"}
          ]
        },
        {
          "key": "company",
          "label": "اطلاعات شرکت",
          "fields": [
            {"id": "company.company_name", "label": "نام قانونی شرکت", "type": "Text", "source": "Company.company_name"},
            {"id": "company.national_id", "label": "شناسه ملی شرکت", "type": "Text", "source": "Company.tax_id"},
            {"id": "company.legal_representative", "label": "نام نماینده قانونی", "type": "Text", "source": "Company.asoud_legal_representative"},
            {"id": "company.address", "label": "نشانی شرکت", "type": "Text", "source": "Company.address"}
          ]
        },
        {
          "key": "contract",
          "label": "مشخصات قرارداد",
          "fields": [
            {"id": "contract.contract_type", "label": "نوع قرارداد", "type": "Select"},
            {"id": "contract.start_date", "label": "تاریخ شروع", "type": "Date"},
            {"id": "contract.end_date", "label": "تاریخ پایان", "type": "Date"},
            {"id": "contract.work_location", "label": "محل انجام کار", "type": "Text"},
            {"id": "contract.creation_date", "label": "تاریخ تنظیم قرارداد", "type": "Date"}
          ]
        },
        {
          "key": "payroll",
          "label": "اقلام حقوق و دستمزد",
          "authorized": true,
          "fields": [
            {"id": "payroll.base_salary", "label": "حقوق پایه", "type": "Money", "group": "حقوق"},
            {"id": "payroll.housing", "label": "حق مسکن", "type": "Money", "group": "مزایا"},
            {"id": "payroll.food", "label": "بن خواربار", "type": "Money", "group": "مزایا"},
            {"id": "payroll.child", "label": "حق اولاد", "type": "Money", "group": "مزایا"},
            {"id": "payroll.seniority", "label": "پایه سنوات", "type": "Money", "group": "حقوق"}
          ]
        }
      ]
    }
  }
  ```

---

## 4. Contract Issuance & Management Endpoints

### 4.1 `prepare_contract`
Pre-populates contract data for an employee, rendering clauses and resolving salary rows from active HRMS salary assignment.

- **Method**: `POST`
- **Path**: `asoud_erp.api.v1.employment_contracts.prepare_contract`
- **Arguments**:
  - `company` (str, required)
  - `employee` (str, required): Employee ID (e.g. `HR-EMP-00001`).
  - `template_version` (int, optional): Specific published version (defaults to latest active revision).
- **Behavior**:
  - Missing salary values are explicitly flagged: `has_value: false`, `formatted_amount: "اطلاعات موجود نیست"`. Never silently 0.
  - Calculates total monthly gross from available items.

### 4.2 `list_contracts`
Lists personnel contracts with server-side search, filtering, and pagination.

- **Method**: `GET` or `POST`
- **Path**: `asoud_erp.api.v1.employment_contracts.list_contracts`
- **Arguments**:
  - `company` (str, required)
  - `search` (str, optional): Search by employee name, personnel code, or contract number. Automatically normalizes Persian/Arabic characters (ی/ي, ک/ك) and Persian/Arabic/English digits.
  - `status` (str, optional): Filter by `all` (همه), `draft` (پیش‌نویس), `in_progress` (در جریان), or `final` (نهایی).
  - `start` (int, optional, default: 0)
  - `page_length` (int, optional, default: 20)
- **Response**:
  ```json
  {
    "ok": true,
    "data": [
      {
        "name": "CNT-1405-00001",
        "contract_id": "CONT-00001",
        "employee": "HR-EMP-00001",
        "employee_name": "محمد رضایی",
        "department": "امور اداری",
        "job_title": "کارشناس اداری",
        "contract_type": "مدت‌معین",
        "start_date": "2026-10-23",
        "end_date": "2027-10-22",
        "jalali_start_date": "۱۴۰۵/۰۸/۰۱",
        "jalali_end_date": "۱۴۰۶/۰۷/۳۰",
        "status": "نهایی",
        "status_code": "final",
        "docstatus": 1,
        "is_signed": 1,
        "template_version": 1
      }
    ],
    "meta": {
      "total": 1,
      "start": 0,
      "page_length": 20
    }
  }
  ```

### 4.3 `get_contract`
Retrieves a single contract by ID with complete rendered snapshot and print payload.

- **Method**: `GET` or `POST`
- **Path**: `asoud_erp.api.v1.employment_contracts.get_contract`
- **Arguments**:
  - `contract_id` (str, required): Document name / ID.

### 4.4 `save_contract_draft`
Creates or updates a contract draft.

- **Method**: `POST`
- **Path**: `asoud_erp.api.v1.employment_contracts.save_contract_draft`
- **Arguments**:
  - `company` (str, required)
  - `employee` (str, required)
  - `start_date` (str, required): ISO Date `YYYY-MM-DD`.
  - `end_date` (str, optional): ISO Date `YYYY-MM-DD`.
  - `contract_type` (str, optional, default: `"مدت‌معین"`)
  - `work_location` (str, optional)
  - `subject` (str, optional)
  - `notes` (str, optional)
  - `salary_values` (dict, optional): Custom override or verified amounts `{"fieldRef": amount}`.
  - `contract_id` (str, optional): For updating existing draft.
  - `client_id` (str, optional): Idempotency key.
- **Behavior**:
  - Draft contracts receive temporary placeholder number («پیش‌نویس») until finalized.
  - Saves rendered snapshot in `values_json`.

### 4.5 `finalize_contract`
Finalizes or submits an employment contract.

- **Method**: `POST`
- **Path**: `asoud_erp.api.v1.employment_contracts.finalize_contract`
- **Arguments**:
  - `contract_id` (str, required)
  - `client_id` (str, optional)
- **Behavior**:
  - Generates official document number using Jalali series (`CNT-1405-#####`).
  - Takes final immutable snapshot of rendered articles and payroll values.
  - If a workflow definition is attached to `Contract`, triggers workflow instance (status `در جریان`).
  - If no workflow is attached, submits contract (`docstatus = 1`, status `نهایی`) and synchronizes `Employee.contract_end_date`.

### 4.6 `get_contract_print`
Returns A4 RTL print payload including company letterhead and draft banner.

- **Method**: `GET` or `POST`
- **Path**: `asoud_erp.api.v1.employment_contracts.get_contract_print`
- **Arguments**:
  - `contract_id` (str, required)
- **Response**:
  ```json
  {
    "ok": true,
    "data": {
      "contract_id": "CONT-00001",
      "contract_number": "CNT-1405-00001",
      "is_draft": false,
      "draft_banner": null,
      "letterhead_html": "<img ... />",
      "issue_date_jalali": "۱۴۰۵/۰۸/۰۱",
      "employee_name": "محمد رضایی",
      "rendered_clauses": [
        {"order": 1, "title": "ماده ۱: طرفین قرارداد", "body": "..."}
      ],
      "salary_table": [
        {"name": "حقوق پایه", "period": "ماهانه", "amount_formatted": "۲۳۵٬۰۰۰٬۰۰۰ ریال"}
      ],
      "total_monthly_formatted": "۲۶۶٬۰۰۰٬۰۰۰ ریال",
      "html": "<!doctype html>..."
    }
  }
  ```
  *Note*: If `is_draft` is true, `draft_banner` is `«پیش‌نویس ـ فاقد اعتبار نهایی»` and `contract_number` is `«شماره پس از صدور»`.
