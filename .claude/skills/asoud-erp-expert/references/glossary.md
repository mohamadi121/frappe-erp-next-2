# Glossary: what the Persian UI words mean in code

Use this when a report says "the screen X does not work": find the word, then the code names.

| Persian (UI) | English / code name | Where |
|---|---|---|
| دفتر کار، دفتر | Company + `ASOUD Company Setup` (one row per company; the first-run wizard shows when the row is missing or incomplete) | backend `api/v1/setup.py`; app `office_setup`, `base_setup` |
| راه‌اندازی دفتر | setup status: `office_saved`, `accounting_saved`, `roles_saved`, `complete` | `setup.get_setup_status` |
| نوع درخواست | request type = `ASOUD Workflow Definition` with target `ASOUD Workflow Request` | app `request_types`; backend `workflow.py`, `workflow_request.py` |
| گردش‌کار، فرایند | workflow = definition + stages + transitions (`ASOUD Workflow Stage`, `ASOUD Workflow Transition`) | app `workflows` |
| مرحله / گره | stage; types: start, user task, approval, system action, end | `workflow_stage_policy.py` |
| طراحی مراحل | workflow designer; stage settings page | app `workflows/presentation` |
| اقدام خودکار | System Action stage. Schema-1 = legacy inline (Create Document / Change Status / Send Notification). Schema-2 = automatic action run later by `automatic_action_runtime`, needs the restricted service user | `automatic_actions.py`; docs `automatic-actions-v2.md` |
| کاربر سرویس | `asoud_workflow_service_user` + `asoud_workflow_service_companies` in site config (System User, never System Manager) | `automatic_action_metadata.service_user` |
| الگوی سند | `ASOUD Document Template`: maps request values onto Journal Entry / Material Request | `document_templates.py` |
| کارتابل | the user's task inbox = `ASOUD Workflow Task` (inbox / sent, statuses) | app `workflows`; backend `workflow_runtime.py` |
| درخواست‌ها / ثبت درخواست‌ها | `ASOUD Workflow Request` (+ `ASOUD Workflow Instance` that runs it) | `workflow_request.py` |
| نقش‌ها، مدیریت نقش‌ها | `ASOUD Role Category` / `ASOUD Role Definition` and native role profiles | `role_management.py` (`catalog`) |
| دسترسی کاربران، مدیریت کاربران | native role + personal access assignments `ASOUD Access Assignment` | `user_access.py`; app `roles` |
| ساختار سازمانی، تیم | `ASOUD Organization Chart` (positions) | `organization.py` |
| پرونده پرسنلی | personnel file: app `PersonnelDetailPage` (the only personnel page; `PersonnelFilePage` was deleted); data `ASOUD Personnel Record` + ERPNext Employee | `personnel_file.py`, `personnel.py` |
| منابع انسانی | HR hub (personnel, leave, attendance, daily work report, internal communication, notifications) | app `hr`; `hr.py`, `hr_self_service.py` |
| گزارش کار روزانه | `ASOUD Work Report` + activities | `hr.py` |
| مکاتبات داخلی | `ASOUD Internal Communication` | `hr.py` |
| خودخدمتی کارمند | employee shell: check-in, leave, own requests (only for employee-only users) | app `employee` |
| طرف‌حساب، اشخاص | `ASOUD Party Profile` over ERPNext Customer/Supplier/Employee | `party.py` |
| گروه تفصیلی شناور | `ASOUD Detail Group` / `ASOUD Floating Detail` | `detail_group.py`, `floating_detail.py` |
| سند حسابداری، ثبت حسابداری | `ASOUD Accounting Voucher` (+ lines) over Journal Entry | `voucher.py` |
| نسخهٔ نمایشی (آفلاین) | offline preview/demo: sample data on the device, no session; same screens as online | app `offline_preview_data.dart` |
| همگام‌سازی | offline queue sync: non-read calls are queued, replayed via `sync.execute_mutation` with a request key | `sync.py`; app `offline/` |
| ذخیره روی گوشی | request kept in the local outbox (`LOCAL-xxxx`), not sent yet | `GenericRequestRepository` |
| تنظیمات | Settings tab: tiles for setup, workflows, request types, roles, HR, offices | app `dashboard` |

Roles that matter: System Manager, Accounts Manager/User, HR Manager (reads open, writes closed on purpose), Purchase/Stock User/Manager, Employee.
HTTP: `401/403` = permission, `417` = inner validation error (terminal, never retried), `REQUEST_KEY_CONFLICT` = HTTP 200 envelope.
