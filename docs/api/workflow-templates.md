# Independent workflow drafts from system templates

POST RPCs under `asoud_erp.api.v1.workflow_templates`; standard `success(data)`
envelope. Requires System Manager or Accounts Manager, company access and native
Definition/Stage/Transition read/create permissions. Sources must belong
to the destination company and be non-archived readable designs. No guest access.

## Module vocabulary (canonical keys)

Every layer that names a module — workflow definitions, document templates and the
app — uses one vocabulary (see `services/modules.py`):

| Key | Persian label |
|---|---|
| `Finance` | مالی |
| `Purchase` | خرید |
| `Selling` | فروش |
| `Stock` | انبار |
| `HR` | منابع انسانی |
| `Admin` | خدمات اداری |
| `IT` | فناوری اطلاعات |

`create_workflow_draft` and `update_request_type_info` accept the legacy workflow
keys and normalize them before storing: `Accounting`→`Finance`, `Sales`→`Selling`,
`Inventory`→`Stock`, `Support`→`Admin`. The read path (`serialize_workflow`) maps any
stored legacy key to its canonical key, so workflows saved before the unification
still load. A migration patch rewrites stored legacy keys on `bench migrate`.

### Target documents per module

`MODULE_DOCTYPES` (in `services/modules.py`) is the single vocabulary of
"module key → target documents" for the workflow designer. `ASOUD Workflow
Request` is always an additional target (a request type) regardless of module.

| Module | Target documents |
|---|---|
| `Finance` | Payment Request, Expense Claim, Journal Entry |
| `Purchase` | Material Request, Purchase Order |
| `Selling` | Quotation, Sales Order |
| `Stock` | Stock Entry |
| `HR` | Leave Application, Job Applicant, Employee Advance, Asset Movement, Shift Request, Salary Slip, Attendance |
| `Admin` | Issue, ASOUD Workflow Request |
| `IT` | Asset |

`workflow_form_options` returns these modules and, for each, the target documents
that are installed on the site (`available: true/false`).

## `catalog(company, search='', module_key='', start=0, page_length=20, include_user=0)`

Read-only. Returns `{items: [{name, workflow_title, process_description,
module_key, target_doctype, icon_key, color_hex, steps_count, modified}],
next_start: int|null}`. Search matches title, not technical IDs. Page size 1–50;
start is nonnegative. Defaults to native-permitted system templates in company;
`include_user=1` also returns native-permitted user designs for independent redesign.

## `create_from_template(company, source, source_modified, workflow_title,
process_description='', icon_key='hub', color_hex='#315CF5')`

Online write. Source modified token must match; stale selection fails explicitly.
Returns the serialized workflow definition used by `workflow.create_workflow_draft`.
Copies design only: stage types/configurations, coordinates and remapped routes,
with fresh definition/stage/key/transition identities. Exact graph references in
JSON are rebound to copied graph IDs. Existing non-graph template configuration
is retained; the copy cannot be activated until existing readiness and permission
checks succeed. Template selection is scoped to the same company.
The new definition is Inactive/Pending, version 1, has no native Frappe Workflow
link, template key/flag, execution instances, tasks, history or execution results.
Stages require review before activation; original records are never changed.
Readiness/activation remain the existing workflow API's responsibility. A malformed
source graph, missing source, wrong company, invalid title/appearance, permission
failure or stale token produces a Persian error. All inserts share one transaction;
no partial clone is committed on failure. No schema migration is required.

Deploy backend and restart workers before releasing matching Flutter. The picker
is online-only; it never substitutes sample templates for authenticated data.
