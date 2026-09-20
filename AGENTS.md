# Architecture contract

- This is an extension app for ERPNext/Frappe/HRMS v15, not a replacement ERP backend.
- Before implementing a business feature, inspect the installed standard app's DocTypes, controllers and APIs. Reuse them if they implement the requested behavior.
- Keep Iranian accounting/localization and genuinely missing behavior in `asoud_erp`. Never modify ERPNext/Frappe/HRMS source code.
- Do not create a custom business ledger or JSON store that duplicates standard transactions. Technical idempotency receipts, compatibility references and explicit presentation metadata are allowed.
- Employee is authoritative for shared HR master fields. Employee Checkin/Attendance, Appraisal, private File and Comment own their corresponding records.
- Preserve legacy data. Migration must be explicit, report unresolved records and be safe to retry. Never guess Employee identities or fabricate appraisal cycles.
- See `docs/personnel-native-architecture.md` for migration and verification details. Keep the Flutter accordion form style contract unchanged.
