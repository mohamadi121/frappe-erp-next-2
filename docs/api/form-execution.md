# Form execution after approval

Internal E2 executor: `asoud_erp.services.form_execution.asset_movement`.
The approved-request dispatcher owns access checks, active requester resolution,
retry, savepoint and failure recording. This module adds no HTTP endpoint.
`apply(request, params)` returns the existing `NativeResult` with `status=Created`,
`doctype=Asset Movement`, the inserted name and an empty reason. Validation raises
with a Persian reason for the dispatcher to record as Failed.

## asset_movement — جابه‌جایی تجهیزات

| Parameter | Field types | Required | Mapping |
|---|---|---|---|
| asset | Link | yes | assets[0].asset |
| direction | Select | yes | Issue or Receipt → purpose |
| date | Date | no | transaction_date at midnight; empty uses ctx.today |
| note | Text, LongText | no | Persian Comment on the draft; no invented native field |

`build(params, ctx)` is pure. Standard context keys are company, employee, user,
request_name and today. `apply` adds asset_location and asset_custodian read from
Asset. For Issue, to_employee is the requester; for Receipt, from_employee is the
requester and to_employee is empty. Both use the asset's current location as
source_location and target_location. Receipt requires custodian=requester.
Issue uses the current custodian as from_employee when present (empty is valid).
Company, docstatus=0 and reference_doctype/reference_name link the native draft to
the approved request. No submit occurs and the asset's custodian is unchanged.

Prerequisites: existing submitted Asset in the request company, existing Location,
and active requester Employee in that company. Asset Movement does not use accounts
or a holiday list; these are deliberately not prerequisites. The ERPNext controller
also forbids a date before the latest submitted movement; this check is localized.
No new DocType, field or migration is needed.

Persian validation messages:

- «تجهیز را انتخاب کنید.»
- «جهت جابه‌جایی باید تحویل یا بازگشت باشد.»
- «تاریخ جابه‌جایی معتبر نیست.»
- «توضیحات جابه‌جایی معتبر نیست.»
- «پرونده پرسنلی درخواست‌دهنده ثبت نشده است.»
- «تجهیز انتخاب‌شده وجود ندارد.»
- «تجهیز انتخاب‌شده متعلق به شرکت درخواست نیست.»
- «تجهیز انتخاب‌شده باید تأیید شده باشد.»
- «مکان تجهیز ثبت نشده یا معتبر نیست.»
- «تجهیز در اختیار درخواست‌دهنده نیست و قابل بازگشت نیست.»
- «تاریخ جابه‌جایی نمی‌تواند پیش از آخرین جابه‌جایی تجهیز باشد.»
