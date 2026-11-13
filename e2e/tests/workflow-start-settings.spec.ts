import {expect, test} from '../support/fixtures';
import {loadState, sitePrep} from '../support/state';

const state = loadState();
const prefix = 'asoud_erp.api.v1.workflow.';

test('approval destinations and comment policy persist with real role and company checks', async ({api}) => {
  const admin = await api.login('admin');
  const employee = await api.login('employee');
  const accounts = await api.login('accounts');
  type Stage = {name: string; stage_type: string; stage_title: string; config: Record<string, unknown>};
  type Design = {stages: Stage[]; transitions: Array<{from_stage: string; to_stage: string; condition: {action?: string}}>};
  const names: string[] = [];
  try {
    for (const company of [state.company, state.second_company]) {
      const draft = await admin.mutate<{name: string}>(prefix + 'create_workflow_draft', {
        company, workflow_title: `E2E-approval-routing-${Date.now()}`, module_key: 'HR', target_doctype: 'ASOUD Workflow Request'});
      names.push(draft.name);
      let design = await admin.read<Design>(prefix + 'get_workflow_design', {definition: draft.name});
      let previous = design.stages[0].name;
      for (const stage_type of ['User Task', 'Approval', 'End']) {
        design = await admin.mutate<Design>(prefix + 'add_workflow_stage', {
          definition: draft.name, after_stage: previous, stage_type});
        previous = design.stages.find(row => row.stage_type === stage_type)!.name;
      }
      const task = design.stages.find(row => row.stage_type === 'User Task')!;
      const approval = design.stages.find(row => row.stage_type === 'Approval')!;
      const end = design.stages.find(row => row.stage_type === 'End')!;
      const args = {definition: draft.name, stage: approval.name, routes: {Approve: end.name, Reject: '', Return: task.name}};
      expect((await employee.post(prefix + 'save_stage_routes', args)).status).toBe(403);
      if (company === state.second_company) {
        expect((await accounts.post(prefix + 'save_stage_routes', args)).status).toBe(403);
      }
      expect((await admin.post(prefix + 'save_stage_routes', {...args, routes: {Return: end.name}})).status).toBe(417);
      await admin.mutate(prefix + 'save_stage_routes', args);
      expect((await admin.post(prefix + 'save_stage_routes', {...args,
        routes: {Approve: 'removed-stage'}})).status).toBe(417);
      await admin.mutate(prefix + 'save_stage_settings', {definition: draft.name, stage: end.name,
        config: {title: 'پایان رد', outcome: 'Rejected'}});
      expect((await admin.post(prefix + 'save_stage_routes', args)).status).toBe(417);
      await admin.mutate(prefix + 'save_stage_settings', {definition: draft.name, stage: end.name,
        config: {title: 'پایان موفق با عنوان جدید', outcome: 'Completed'}});
      for (const required of [false, true]) {
        await admin.mutate(prefix + 'save_stage_settings', {
          definition: draft.name, stage: approval.name, config: {
            title: 'تأیید مسئول', description: 'شرح محفوظ', assignment_type: 'Direct Manager',
            approval_mode: 'Any', allow_reject: true, allow_return: true,
            comment_required: required, reject_comment_required: false}});
        const reloaded = await admin.read<Design>(prefix + 'get_workflow_design', {definition: draft.name});
        expect(reloaded.stages).toHaveLength(4);
        expect(reloaded.stages.find(row => row.name === approval.name)!.config).toMatchObject({
          comment_required: required, allow_reject: true, allow_return: true, description: 'شرح محفوظ'});
        const routes = reloaded.transitions.filter(row => row.from_stage === approval.name);
        expect(routes.find(row => row.condition.action === 'Approve')?.to_stage).toBe(end.name);
        expect(reloaded.stages.find(row => row.name === end.name)!.stage_title).toBe('پایان موفق با عنوان جدید');
        expect(routes.find(row => row.condition.action === 'Return')?.to_stage).toBe(task.name);
        expect(routes.some(row => row.condition.action === 'Reject')).toBe(false);
      }
    }
  } finally {
    for (const definition of names) sitePrep('drop-definition', {definition});
  }
});

test('start settings persist through the native API, enforce role/company scope and retain the Start identity', async ({api}) => {
  const admin = await api.login('admin');
  const employee = await api.login('employee');
  const accounts = await api.login('accounts');
  const draft = await admin.mutate<{name: string}>(prefix + 'create_workflow_draft', {
    company: state.company, workflow_title: `E2E-شروع دستی ${Date.now()}`, module_key: 'HR',
    target_doctype: 'ASOUD Workflow Request'});
  let foreignName: string | undefined;
  try {
  const before = await admin.read<{stages: Array<{name: string; stage_type: string}>}>(
    prefix + 'get_workflow_design', {definition: draft.name});
  const payload = {definition: draft.name, trigger_type: 'Manual', initiator_roles: ['System Manager'],
    subject_source: 'General Subject', settings: {trigger_type: 'Manual', initiator_roles: ['System Manager'],
      allow_manager_restart: true, require_manual_reason: true}};
  expect((await employee.post(prefix + 'save_start_settings', payload)).status).toBe(403);
  const result = await admin.mutate<{name: string; config: {start_settings_version: number; allow_manager_restart: boolean}}>(
    prefix + 'save_start_settings', payload);
  expect(result.name).toBe(before.stages.find(stage => stage.stage_type === 'Start')?.name);
  expect(result.config.start_settings_version).toBe(1);
  expect(result.config.allow_manager_restart).toBe(true);
  const reload = await admin.read<{stages: Array<{name: string; config: {start_settings_version?: number}}> }>(
    prefix + 'get_workflow_design', {definition: draft.name});
  expect(reload.stages.find(stage => stage.name === result.name)?.config.start_settings_version).toBe(1);
  const foreign = await admin.mutate<{name: string}>(prefix + 'create_workflow_draft', {
    company: state.second_company, workflow_title: `E2E-شروع دفتر دیگر ${Date.now()}`, module_key: 'HR',
    target_doctype: 'ASOUD Workflow Request'});
  foreignName = foreign.name;
  expect((await accounts.post(prefix + 'save_start_settings', {...payload, definition: foreign.name})).status).toBe(403);
  expect((await admin.post(prefix + 'save_start_settings', {...payload,
    settings: {...payload.settings, require_manual_reason: false}})).status).toBe(417);
  // Neither choosing settings nor reloading an inactive draft may start execution.
  expect((await admin.post('asoud_erp.api.v1.workflow_runtime.start_workflow_instance', {
    definition: draft.name, subject: 'اجرای زودهنگام', reason: 'آزمون'})).status).toBe(417);
  } finally {
    if (foreignName) sitePrep('drop-definition', {definition: foreignName});
    sitePrep('drop-definition', {definition: draft.name});
  }
});
