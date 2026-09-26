# Organization chart and native Employee managers

- Assignments now use explicit `employee:<Employee.name>` identifiers. The list
  endpoint returns active Employees visible to the user in the requested company.
- Legacy Party Profile identifiers resolve only through their existing Employee
  link. No name matching, automatic Employee creation or cross-company mapping.
  Missing, inactive, duplicate or ambiguous assignments are rejected.
- Saving a chart updates `Employee.reports_to` through the native Employee
  controller, including NestedSet validation. The occupied immediate parent is
  the direct manager. A vacant parent or root means no direct manager; ancestors
  are not substituted.
- The chart is authoritative for direct managers of its assigned Employees when
  explicitly saved. Role permissions, salary, Department and designation are not
  changed. Organization title/department remain presentation metadata.
- When removing an assignment, its old manager is cleared only if it still
  equals the chart's former direct manager. Unresolved old assignments are not
  guessed or deleted; the response reports them as warnings.
- Native tree changes and chart writes share a transaction. Changing links are
  detached then attached through native saves so valid reparenting does not
  fail because of a temporary cycle. A failure rolls back the operation.
- Validation and synchronization live on the chart controller, so standard
  resource writes cannot bypass the assignment checks.

## Mobile drafts and conflict handling

- Cache and draft keys include server, authenticated user and company. Session
  changes invalidate in-flight results and close chart screens.
- Old ownerless cache entries are retained but never automatically adopted:
  ownership cannot be safely inferred. They require an explicit, separately
  authorized recovery/migration if their data is needed.
- Drafts are stored separately from server snapshots. Reload always attempts a
  server read; permission/validation failures are never treated as offline success.
- The comparison dialog allows using the server version or retaining the draft
  against the reviewed revision. The old draft is archived locally first.
  Retaining it does not send a write; the next explicit save still checks revision.
- Deploy backend and frontend together. No server deployment, migration,
  automated tests or runtime validation were performed for this change.
