import {expect, test} from '../support/fixtures';
import {loadState, sitePrep} from '../support/state';

const state = loadState();
const prefix = 'asoud_erp.api.v1.workflow.';

test('start settings persist through the native API, enforce role/company scope and retain the Start identity', async ({api}) => {
  const admin = await api.login('admin');
  const employee = await api.login('employee');
  const accounts = await api.login('accounts');
  const draft = await admin.mutate<{name: string}>(prefix + 'create_workflow_draft', {
    company: state.company, workflow_title: `شروع دستی ${Date.now()}`, module_key: 'HR',
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
    company: state.second_company, workflow_title: `شروع دفتر دیگر ${Date.now()}`, module_key: 'HR',
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
