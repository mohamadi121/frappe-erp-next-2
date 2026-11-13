# End stage: existing save and runtime contract

No new endpoint, result option, field, or engine is introduced. Existing
`workflow.save_stage_settings(definition, stage, config)` saves design only.
End config is `title`, `outcome` (Completed/Rejected/Cancelled/Stopped) and
optional `result_label`. Company/write permission and the existing active/running
definition guard apply. Existing missing-outcome End configurations retain their
legacy Completed meaning at runtime; unknown outcomes fail instead of completing.

Runtime End is internal, reached through an existing incoming transition. The
single-current-stage engine has exclusive routes, not parallel execution tokens.
The instance lock serializes completion. Completed/Rejected/Cancelled map to
the same native instance statuses; Stopped maps to existing Failed, with the exact
Stopped outcome retained in one ASOUD Workflow Activity. Approval Reject retains
its existing execution-specific Rejected override on a shared End.

The activity uses existing before/after/labels JSON, recording outcome, message,
source/end node, version, actor, decision, reason and completion time. Existing
permission-scoped instance history returns it. No notification or business write
is added by End; existing request/module lifecycle mappings remain authoritative.
Open tasks are cancelled; waiting snapshots and unexecuted automatic receipts
become inert through their existing terminal-state guards. Historical tasks,
documents and successful effects are never deleted or reversed.

There is no public finish endpoint. Human task submission still checks owner,
company, allowed decision, reason and no self-approval. Late task replies must
not advance a terminal instance or a task from another current stage.
