import {expect, test} from '../support/fixtures';
import {loadState, sitePrep} from '../support/state';

const state = loadState();
const prefix = 'asoud_erp.api.v1.workflow.';
type Design = {stages: Array<{name: string; stage_type: string; config: Record<string, unknown>}>;
  transitions: Array<{name: string}>};

test('user-action settings persist through native role and company gates', async ({api}) => {
  const admin = await api.login('admin');
  const employee = await api.login('employee');
  const accounts = await api.login('accounts');
  const definitions: string[] = [];
  try {
    for (const company of [state.company, state.second_company]) {
      const draft = await admin.mutate<{name: string}>(prefix + 'create_workflow_draft', {
        company, workflow_title: `اقدام کاربر ${Date.now()}`, module_key: 'HR',
        target_doctype: 'ASOUD Workflow Request'});
      definitions.push(draft.name);
      const initial = await admin.read<Design>(prefix + 'get_workflow_design', {definition: draft.name});
      const graph = await admin.mutate<Design>(prefix + 'add_workflow_stage', {
        definition: draft.name, after_stage: initial.stages.find(item => item.stage_type === 'Start')!.name, stage_type: 'User Task'});
      const stage = graph.stages.find(item => item.stage_type === 'User Task')!;
      const config = {title: 'بررسی اطلاعات', action_contract_version: 1, result_mode: 'Simple',
        assignment_type: 'Initiator', assignment_rule: {basis: 'Subject', subject: 'Initiator'},
        activity_type: 'Data Entry', task_purpose: 'Existing', allow_add_attachments: false,
        simple_result_style: 'Report', allow_original_access: false, allow_draft: true, allow_reassign: true};
      const payload = {definition: draft.name, stage: stage.name, config: JSON.stringify(config)};
      expect((await employee.post(prefix + 'save_stage_settings', payload)).status).toBe(403);
      if (company === state.second_company) {
        expect((await accounts.post(prefix + 'save_stage_settings', payload)).status).toBe(403);
      }
      await admin.mutate(prefix + 'save_stage_settings', payload);
      const reloaded = await admin.read<Design>(prefix + 'get_workflow_design', {definition: draft.name});
      const stored = reloaded.stages.find(item => item.name === stage.name)!.config;
      expect(stored.action_contract_version).toBe(1);
      expect(stored.result_mode).toBe('Simple');
      expect(stored.simple_result_style).toBe('Report');
      expect(stored.allow_original_access).toBe(false);
      expect(stored.allow_reassign).toBe(true);
      expect(stored.allow_draft).toBe(true);
      expect(stored.assignment_rule).toEqual({basis: 'Subject', subject: 'Initiator', delivery: 'Direct'});
      expect((await admin.post(prefix + 'save_stage_settings', {...payload,
        config: JSON.stringify({...config, result_mode: 'Form', result_form: null})})).status).toBe(417);
      expect((await admin.post(prefix + 'save_stage_settings', {...payload,
        config: JSON.stringify({...config, allow_reassign: 'false'})})).status).toBe(417);
      const anonymous = await api.anonymous();
      expect((await anonymous.post(prefix + 'save_stage_settings', payload, {csrf: false})).status).not.toBe(200);
      await admin.mutate(prefix + 'add_workflow_stage', {
        definition: draft.name, after_stage: stage.name, stage_type: 'End'});
      const choices = await admin.read<{items: Array<{name: string; modified: string}>}>(
        'asoud_erp.api.v1.workflow_templates.catalog', {company, include_user: '1'});
      // Search explicitly: other tests' drafts may occupy earlier pages.
      const metadata = await admin.read<{workflow: {modified: string}}>(prefix + 'get_workflow_design', {definition: draft.name});
      const modified = choices.items.find(item => item.name === draft.name)?.modified ?? metadata.workflow.modified;
      const copied = await admin.mutate<{name: string; status: string}>(
        'asoud_erp.api.v1.workflow_templates.create_from_template', {
          company, source: draft.name, source_modified: modified, workflow_title: 'بازطراحی مستقل اقدام'});
      definitions.push(copied.name);
      expect(copied.name).not.toBe(draft.name);
      expect(copied.status).toBe('Inactive');
    }
  } finally {
    for (const definition of definitions.reverse()) sitePrep('drop-definition', {definition});
  }
});
