# Organization structure: implementation audit

Date: 2026-10-20. Source: supplied final organization specification.
This is a source-code audit, not a database or live-server verification.

## Existing implementation

- `api/v1/organization.py`: company-scoped read/write RPC, revision comparison,
  company and Employee locks, active Employee picker.
- `services/organization_contract.py`: stable position codes, parent existence
  and cycle checks, currently at most 500 positions and one occupant per position.
- `services/organization_employees.py`: explicit native Employee identity
  resolution, legacy link validation and native `Employee.reports_to` updates.
- `doctype/asoud_organization_chart`: current JSON chart, revision and native
  manager synchronization on save, including ordinary document writes.
- Flutter `features/hr/data/organization_repository.dart` and
  `presentation/cubit/organization_cubit.dart`: shared persistence, session-scoped
  cache/draft handling and conflict resolution.
- Flutter `presentation/pages/organization_page.dart`: setup, suggested templates,
  XLSX parsing/preview and save route.
- Flutter `organization_chart_view.dart`: tree and staged browsing.
- Flutter `organization_position_form.dart`: shared position editing page.
- Flutter `domain/organization_templates.dart`: five suggested vacant templates;
  templates do not create people.

## Material gaps and compatibility constraints

The chart's department value is display text, not a native Department link.
The current position holds one Employee, without capacity or assignment dates.
Ending or changing an assignment has no dedicated assignment-history model.
The current UI does not implement the specified three management tabs or the
separate photographic report and reusable bottom-sheet forms.

The current chart is authoritative for managers of assigned Employees on save:
the immediate parent's occupant becomes `Employee.reports_to`. Multiple
occupants invalidate this single-manager derivation. Picking the first occupant
would silently change authority, including directive eligibility. A business
choice is required before replacing that behavior.

## Proposed sequence

1. Inspect the actual deployed ERPNext/HRMS v15 models and extension installation.
   The core repository and live database were not available in the inspected
   workspace. Do not infer missing native capabilities from extension code.
2. Keep Company, Department, Employee, Designation and existing access mechanisms
   authoritative for their native fields. Add only missing position/capacity/
   temporal-assignment concepts in the extension after the native-model audit.
3. Preserve the legacy chart and build an explicit dry-run migration with
   stable source IDs and reviewed Department mappings. Do not match departments
   by title alone, automatically infer people or discard historical data.
4. Resolve manager policy for multi-occupant parent positions; do not mutate
   `Employee.reports_to` ambiguously or silently disable existing synchronization.
5. Reuse the existing repository/cubit and extract form content for both full
   pages and sheets. Add management tabs, unit details, assignments/history and
   the separate photographic/list report against one shared source.
6. Extend the existing XLSX preview/import path for stable references, units,
   capacity and transaction-safe imports. No implicit personnel creation.
7. Cover permissions, company boundaries, capacity concurrency, cycles,
   migration/replay, assignment history and mobile navigation with tests.

## Deployment and open decisions

No schema, data, runtime behavior or accounting fields were changed in this audit.
No migration or tests were run. Back up database and files before migration;
retain old snapshots and a mapping manifest for a reviewed rollback procedure.
Do not implement rollback by deleting new records with dependencies.

Open: who is the direct manager when a parent position has several occupants?
Recommended: explicit manager selection using native Employee relations, not
automatic selection of a position occupant. Preserve existing assignments until
reviewed migration.

Personnel code versus Iranian floating-account code remains intentionally
undecided. This work must not change the accounting relationship.

## Follow-up implementation (2026-10-20)

The user approved explicit Employee manager selection and supplied both source
directories under `C:/Users/User/Downloads/erpas`. Inspected native Department
JSON/controller (NestedSet, company, parent, disabled, link-safe deletion),
Designation JSON (title/description only), Employee fields/controller
(reports_to, employee_number, image) and the extension's organization API.
Changes are in the version-controlled `publish-backend` and `publish-flutter`
workspaces; the downloaded sources and ERPNext core are untouched.

Implemented:

- Removed the automatic manager synchronizer; chart writes do not alter any
  existing Employee reporting line or accounting identifier.
- Native Department list/create/edit/move/delete endpoints with company/role
  and native document permissions, version checks, company locks, cycle
  validation and native dependency checks. Referenced departments cannot be
  deleted, disabled or moved across companies, and cannot be renamed at the ID
  level. Display titles remain editable for positions linked by `department_id`.
  Legacy title-only references conservatively block deletion and block a title
  change until those positions are linked to the unit; they are never silently
  converted to IDs or orphaned. Only restricting Department changes take the
  company lock; plain saves do not.
- Extended existing position rows, rather than introducing a second chart:
  `department_id`, `occupants`, positive integer `capacity`, `duties` and
  server-owned `assignment_history`. History records native Employee IDs,
  server timestamps and actors; clients cannot rewrite it. Legacy unknown
  assignment start dates remain null. Position deletion with history and
  old-client field stripping are rejected. Old charts remain readable. An
  Employee may occupy at most one position across the chart; a capacity above
  one only allows several different Employees in the same position.
- No separate person records or personnel numbers are created. Personnel
  lookup returns Employee.employee_number (fallback: native name).
- Permission-checked private Employee image thumbnails; no arbitrary remote
  image URL is fetched or exposed.
- Flutter's existing cubit/repository and position form remain the shared
  write path. Added management tabs, native unit sheets, position details,
  capacity/multi-occupant editing, assignment history, searchable Employee
  picker, separate visual/list report and shared form sheets. The report uses
  horizontal child rows and PageStorage keys; it creates no data store.
- Existing XLSX preview/import retained with a downloadable `positions`/`units`
  workbook. Stable Department IDs or explicit file aliases connect positions;
  capacity/duties and existing Employee IDs are supported. Server preview and
  revision-checked transaction create units and positions together. Existing
  units match only an explicit native `name`, never a similar title. Any failure
  rolls back new units and chart writes. Suggested templates reuse this same
  preview/transaction and cannot overwrite an existing chart.

Remaining acceptance work (not represented as complete):

- Run native Frappe integration/security/concurrency tests and device visual
  acceptance on the actual installed site. Source inspection is not a live
  schema/database audit.
- Legacy template department labels still require explicit native Department
  selection. There is no automatic title-based Department migration.
- Native import rollback, cross-company access and private image tests require
  the installed Frappe test site. Added integration tests have not run locally.
- The current 500-position safety limit remains. No three-child data limit was
  introduced.
- Separate offices within one native Company have no new invented security
  boundary: native Company and document permissions remain authoritative.
  Verify the deployment's office-to-Company mapping before acceptance.
- The visual report retains actual separate Department and position
  hierarchies; it does not infer a company's CEO from a job title or fabricate
  a manager-to-department edge. Exact approval against the original image
  reference still requires that reference and visual QA.

Deployment: back up database/files and export each existing chart JSON before
upgrading the extension. Run migrate/clear-cache/restart and deploy the new
client together. No new DocType/table is required by this change. Conversion
of a legacy assignment occurs only on an explicit chart save; its original
unknown date stays unknown. Native Version retains document changes.
Do not downgrade clients after v2 assignment saves: older clients cannot retain
the new fields and are rejected. Rollback must preserve/export all new history
and restore a reviewed database backup during a write freeze, not discard rows.

Validation performed locally: 18 focused pure Python organization tests and
32 Flutter organization/capability/route tests passed. Static analysis and Ruff
passed. The installed-site integration tests were added but not run.
No production migration or deployment was performed.
