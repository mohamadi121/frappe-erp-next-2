import {expect, test} from '../support/fixtures';
import {ASOUD} from '../support/api';
import {loadState, sitePrep} from '../support/state';

const state = loadState();
const workflow = `${ASOUD}.workflow.`;
const runtime = `${ASOUD}.workflow_runtime.`;
interface Design {stages: {name: string; stage_type: string; stage_title: string; config: Record<string, unknown>}[];}

test('End real HTTP saves four results, keeps permissions, and finishes each execution once', async ({api}) => {
  const admin = await api.login('admin'); // Management fixture without an Employee.
  const employee = await api.login('employee');
  const accounts = await api.login('accounts');
  for (const [outcome, status] of [['Completed', 'Completed'], ['Rejected', 'Rejected'],
      ['Cancelled', 'Cancelled'], ['Stopped', 'Failed']]) {
    const definition = await admin.mutate<{name: string}>(workflow + 'create_workflow_draft', {
      company: state.company, workflow_title: `E2E-End ${outcome} ${Date.now()}`, module_key: 'HR',
      target_doctype: 'ASOUD Workflow Request'});
    let foreign: string | undefined;
    try {
      let design = await admin.read<Design>(workflow + 'get_workflow_design', {definition: definition.name});
      await admin.mutate(workflow + 'add_workflow_stage', {definition: definition.name,
        stage_type: 'User Task', after_stage: design.stages[0].name});
      design = await admin.read<Design>(workflow + 'get_workflow_design', {definition: definition.name});
      const taskStage = design.stages.find(row => row.stage_type === 'User Task')!.name;
      await admin.mutate(workflow + 'save_stage_settings', {definition: definition.name, stage: taskStage,
        config: {title: 'اقدام آزمایشی', activity_type: 'Task', assignment_type: 'Initiator', form_fields: []}});
      await admin.mutate(workflow + 'add_workflow_stage', {definition: definition.name,
        stage_type: 'End', after_stage: taskStage});
      design = await admin.read<Design>(workflow + 'get_workflow_design', {definition: definition.name});
      const end = design.stages.find(row => row.stage_type === 'End')!.name;
      const config = {title: 'پایان معتبر آزمایشی', outcome, result_label: 'پیام نتیجه بدون ارسال اعلان'};
      expect((await employee.post(workflow + 'save_stage_settings', {definition: definition.name, stage: end, config})).status).toBe(403);
      await admin.mutate(workflow + 'save_stage_settings', {definition: definition.name, stage: end, config});
      design = await admin.read<Design>(workflow + 'get_workflow_design', {definition: definition.name});
      expect(design.stages.find(row => row.name === end)!.config).toMatchObject({outcome, result_label: config.result_label});
      expect((await admin.post(workflow + 'save_stage_settings', {definition: definition.name, stage: end,
        config: {...config, outcome: 'invalid'}})).status).toBe(417);
      if (outcome === 'Completed') {
        expect((await admin.post(workflow + 'save_stage_settings', {definition: definition.name, stage: end, config: '{'})).status).toBe(417);
        expect((await admin.post(workflow + 'save_stage_settings', {definition: definition.name, stage: end, config: {...config, outcome: []}})).status).toBe(417);
        const other = await admin.mutate<{name: string}>(workflow + 'create_workflow_draft', {
          company: state.second_company, workflow_title: `E2E-End foreign ${Date.now()}`, module_key: 'HR',
          target_doctype: 'ASOUD Workflow Request'});
        foreign = other.name;
        expect((await accounts.post(workflow + 'save_stage_settings', {definition: foreign, stage: end, config})).status).toBe(403);
      }
      await admin.mutate(workflow + 'save_start_settings', {definition: definition.name, trigger_type: 'Manual',
        initiator_roles: ['Accounts Manager'], subject_source: 'General Subject', settings: {
          trigger_type: 'Manual', initiator_roles: ['Accounts Manager'], allow_manager_restart: false, require_manual_reason: true}});
      sitePrep('activate', {definition: definition.name});
      await admin.mutate(workflow + 'set_workflow_status', {name: definition.name, status: 'Active'});
      const data = {definition: definition.name, subject: 'E2E-End actual', reason: 'آزمون پایان واقعی', request_id: `end-${Date.now()}`};
      const instance = await accounts.mutate<{name: string; status: string}>(runtime + 'start_workflow_instance', data);
      expect(instance.status).toBe('Running');
      const tasks = await accounts.read<{name: string; workflow_instance: string}[]>(runtime + 'list_my_workflow_tasks', {status: 'Open'});
      const task = tasks.find(row => row.workflow_instance === instance.name)!.name;
      expect((await employee.post(runtime + 'complete_workflow_task', {task, action: 'Complete'})).status).toBe(403);
      const replies = await Promise.all([accounts.post(runtime + 'complete_workflow_task', {task, action: 'Complete'}),
        accounts.post(runtime + 'complete_workflow_task', {task, action: 'Complete'})]);
      expect(replies.map(row => row.status).sort()).toEqual([200, 417]);
      const detail = await admin.read<{status: string; activities: {action: string; after: Record<string, unknown>}[]}>(
        runtime + 'get_workflow_instance', {instance: instance.name});
      expect(detail.status).toBe(status);
      const events = detail.activities.filter(row => row.action === 'پایان عملیات');
      expect(events).toHaveLength(1);
      expect(events[0].after.result_label).toBe(config.result_label);
      expect(events[0].after).not.toHaveProperty('from_stage');
      expect((await admin.post(workflow + 'save_stage_settings', {definition: definition.name, stage: end, config})).status).toBe(417);
      expect((await employee.get(runtime + 'get_workflow_instance', {instance: instance.name})).status).toBe(403);
      expect((await admin.post('asoud_erp.services.workflow_end.finish', {instance: instance.name, stage: end})).status).toBe(403);
    } finally {
      if (foreign) sitePrep('drop-definition', {definition: foreign});
      sitePrep('drop-end-test', {definition: definition.name});
    }
  }
});
