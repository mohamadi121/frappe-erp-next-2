import { expect, test } from '../support/fixtures';
import { loadState, sitePrep } from '../support/state';
import { errorText } from '../support/api';

const state = loadState();
const workflow = 'asoud_erp.api.v1.workflow.';
type Stage = {name: string; stage_type: string; config: Record<string, unknown>};
type Design = {stages: Stage[]; transitions: Array<{name: string}>};

test('request workflow intent validation uses real HTTP permissions and Persian failures', async ({api}) => {
  const admin = await api.login('admin'); // Designer without an Employee record.
  const employee = await api.login('employee');
  const accounts = await api.login('accounts');
  const method = 'asoud_erp.api.v1.forms.get_validation';
  const options = 'asoud_erp.api.v1.forms.get_options';
  const available = await admin.get<{departments: string[]; department_notice: string}>(options,
    {company: state.company, kind: 'Request'});
  expect(available.status, errorText(available)).toBe(200);
  expect(available.envelope.data.departments).toEqual([]);
  expect(available.envelope.data.department_notice).toContain('مجوز');
  expect((await admin.get(options, {company: state.company, kind: 'Document'})).status).toBe(403);
  expect((await employee.get(options, {company: state.company})).status).toBe(403);
  expect((await accounts.get(options, {company: state.second_company})).status).toBe(403);
  const schema = {kind: 'Request', title: 'E2E-intent-validation', sections: [
    {id: 'main', title: 'اطلاعات', fields: [{key: 'note', label: 'شرح', type: 'Text'}]},
  ]};
  const args = (mode: string, selected?: string) => ({company: state.company,
    schema: JSON.stringify({...schema, workflow_mode: mode, workflow: selected})});
  expect((await employee.post(method, args('Conditional'))).status).toBe(403);
  expect((await accounts.post(method, {...args('Conditional'), company: state.second_company})).status).toBe(403);
  expect((await admin.post(method, args('Conditional'))).status).toBe(200);
  const missing = await admin.post(method, args('Fixed', 'E2E-missing-selected-workflow'));
  expect(missing.status).toBe(417);
  expect(errorText(missing)).toContain('وجود ندارد');
  const recordOnly = await admin.post(method, args('RecordOnly'));
  expect(recordOnly.status).toBe(417);
  expect(errorText(recordOnly)).toContain('سیاست معتبر');
  const invalid = await admin.post(method, args('unrecognized'));
  expect(invalid.status).toBe(417);
  expect(errorText(invalid)).toContain('روش اتصال');
});

test('one published leave form binds to two drafts without changing their automatic start', async ({api}) => {
  const admin = await api.login('admin'); // No Employee needed to design workflows.
  const employee = await api.login('employee');
  const accounts = await api.login('accounts');
  const source = await admin.mutate<{name: string; revision: string}>(
    'asoud_erp.api.v1.forms.open_builtin', {company: state.company, key: 'leave'});
  const settings = {trigger_type: 'Document Event', initiator_roles: [],
    submission_source: {form: source.name, revision: source.revision}, source_route: 'Available'};
  const preflight = {definition: '', company: state.company, validate_only: '1',
    trigger_type: 'Document Event', initiator_roles: '[]', subject_source: 'Referenced Document',
    settings: JSON.stringify(settings)};
  const validation = await admin.post(workflow + 'save_start_settings', preflight);
  expect(validation.status, errorText(validation)).toBe(200);
  expect((await employee.post(workflow + 'save_start_settings', preflight)).status).toBe(403);
  expect((await accounts.post(workflow + 'save_start_settings', {...preflight, company: state.second_company})).status).toBe(403);
  const names: string[] = [];
  try {
    for (let i = 0; i < 2; i++) {
      const draft = await admin.mutate<{name: string; start_settings: Record<string, unknown>}>(workflow + 'create_workflow_draft', {
        company: state.company, workflow_title: `E2E-shared-${Date.now()}-${i}`, module_key: 'HR',
        target_doctype: 'ASOUD Workflow Request', start_settings: JSON.stringify(settings)});
      names.push(draft.name);
      expect(draft.start_settings.trigger_type).toBe('Document Event');
      expect(draft.start_settings.submission_source).toMatchObject(settings.submission_source);
      const design = await admin.read<Design>(workflow + 'get_workflow_design', {definition: draft.name});
      const start = design.stages.find(row => row.stage_type === 'Start')!;
      expect(start.config.trigger_type).toBe('Document Event');
      expect((start.config.submission_source as {form: string}).form).toBe(source.name);
      expect(start.config.source_route).toBe(draft.start_settings.source_route);
    }
    expect(names[0]).not.toBe(names[1]);
  } finally {
    for (const definition of names) sitePrep('drop-definition', {definition});
  }
});

test('submission source is routing metadata and employee cannot change it', async ({api}) => {
  const admin = await api.login('admin');
  const employee = await api.login('employee');
  const source = await admin.mutate<{name: string; revision: string; submission_source_version: number}>(
    'asoud_erp.api.v1.forms.open_builtin', {company: state.company, key: 'leave'});
  expect(source.submission_source_version).toBe(1);
  const draft = await admin.mutate<{name: string}>(workflow + 'create_workflow_draft', {
    company: state.company, workflow_title: `E2E-اتصال ثبت اصلی ${Date.now()}`, module_key: 'HR',
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
    // Deliberate version-history protection now refuses production deletion of
    // edited definitions. Only the guarded bench fixture helper may clean these.
    sitePrep('drop-definition', {definition: draft.name});
  }
});
