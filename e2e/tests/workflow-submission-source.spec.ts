import { expect, test } from '../support/fixtures';
import { loadState } from '../support/state';

const state = loadState();
const workflow = 'asoud_erp.api.v1.workflow.';
type Stage = {name: string; stage_type: string; config: Record<string, unknown>};
type Design = {stages: Stage[]; transitions: Array<{name: string}>};

test('submission source is routing metadata and employee cannot change it', async ({api}) => {
  const admin = await api.login('admin');
  const employee = await api.login('employee');
  const source = await admin.mutate<{name: string; revision: string; submission_source_version: number}>(
    'asoud_erp.api.v1.forms.open_builtin', {company: state.company, key: 'leave'});
  expect(source.submission_source_version).toBe(1);
  const draft = await admin.mutate<{name: string}>(workflow + 'create_workflow_draft', {
    company: state.company, workflow_title: `اتصال ثبت اصلی ${Date.now()}`, module_key: 'HR',
    target_doctype: 'ASOUD Workflow Request'});
  try {
    const initial = await admin.read<Design>(workflow + 'get_workflow_design', {definition: draft.name});
    const added = await admin.mutate<Design>(workflow + 'add_workflow_stage', {
      definition: draft.name, stage_type: 'User Task', after_stage: initial.stages[0].name});
    const stage = added.stages.find(s => s.stage_type === 'User Task')!;
    const args = {definition: draft.name, stage: stage.name, config: JSON.stringify({
      title: 'بررسی ثبت اصلی', description: 'شرح حفظ می‌شود', activity_type: 'Review', assignment_type: 'Initiator',
      submission_source: {form: source.name, revision: source.revision},
      task_purpose: 'Create Request', request_definition: state.request_type})};
    expect((await employee.post(workflow + 'save_stage_settings', args)).status).toBe(403);
    const saved = await admin.mutate<Design>(workflow + 'save_stage_settings', args);
    const config = saved.stages.find(s => s.name === stage.name)!.config;
    expect(config.task_purpose).toBe('Existing');
    expect(config.description).toBe('شرح حفظ می‌شود');
    expect(config.request_definition).toBeUndefined();
    expect(config.bound_form_schema).toBeUndefined();
    expect((config.submission_source as {form: string}).form).toBe(source.name);
    // Invalid/incomplete submission is refused; the full valid-data inactive
    // route and no-duplicate assertions are covered by the real-site module.
    const attempt = await admin.post('asoud_erp.api.v1.forms.submit_form', {
      name: source.name, revision_name: source.revision, subject: 'ثبت ناتمام',
      values: '{}', request_key: `source-${Date.now()}`});
    expect(attempt.status).toBe(417);
  } finally {
    const design = await admin.read<Design>(workflow + 'get_workflow_design', {definition: draft.name});
    const headers = {'X-Frappe-CSRF-Token': await admin.csrf()};
    for (const [doctype, rows] of [['ASOUD Workflow Transition', design.transitions], ['ASOUD Workflow Stage', design.stages]] as const) {
      for (const row of rows) expect((await admin.context.delete(
        `/api/resource/${encodeURIComponent(doctype)}/${encodeURIComponent(row.name)}`, {headers})).status()).toBe(200);
    }
    expect((await admin.context.delete(`/api/resource/ASOUD%20Workflow%20Definition/${encodeURIComponent(draft.name)}`, {headers})).status()).toBe(200);
  }
});
