import {execFile} from 'node:child_process';
import {promisify} from 'node:util';
import {expect, test} from '../support/fixtures';
import {ASOUD} from '../support/api';
import {BENCH, PYTHON} from '../support/config';
import {loadState, sitePrep} from '../support/state';

const state = loadState();
const prefix = `${ASOUD}.workflow.`;
const waits = `${ASOUD}.workflow_wait.`;
interface Design {stages: {name: string; stage_type: string; stage_title: string; config: Record<string, unknown>}[];
  transitions: {name: string}[];}
async function worker(instance: string) {
  const {stdout} = await promisify(execFile)(PYTHON,
    [`${__dirname}/../support/py/site_prep.py`, 'run-wait', `instance=${instance}`], {cwd: BENCH});
  return JSON.parse(stdout.split('\n').find(line => line.startsWith('@@E2E_JSON@@'))!.slice('@@E2E_JSON@@'.length)) as {
    status: string; completed_waits: number; wait: {state: string; entered_utc: string; actual_utc: string}};
}

for (const delayed of [false, true]) {
  test(`Wait real HTTP permissions, persistence and ${delayed ? 'one-minute duration' : 'two concurrent fresh workers'}`, async ({api}) => {
    const admin = await api.login('admin');
    const employee = await api.login('employee');
    const accounts = await api.login('accounts');
    const draft = await admin.mutate<{name: string}>(prefix + 'create_workflow_draft', {
      company: state.company, workflow_title: `E2E-Wait ${Date.now()}`, module_key: 'HR', target_doctype: 'ASOUD Workflow Request'});
    let foreign: string | undefined;
    try {
      let design = await admin.read<Design>(prefix + 'get_workflow_design', {definition: draft.name});
      const start = design.stages[0].name;
      await admin.mutate(prefix + 'add_workflow_stage', {definition: draft.name, stage_type: 'End', after_stage: start});
      design = await admin.read<Design>(prefix + 'get_workflow_design', {definition: draft.name});
      const inserted = await admin.mutate<Design>(prefix + 'insert_workflow_stage', {
        definition: draft.name, transition: design.transitions[0].name, stage_type: 'Wait'});
      const stage = inserted.stages.find(row => row.stage_type === 'Wait')!.name;
      const options = await admin.read<{wait_version: number; output_valid: boolean; execution_ready: boolean}>(
        waits + 'get_wait_options', {definition: draft.name, stage});
      expect(options).toMatchObject({wait_version: 1, output_valid: true, execution_ready: true});
      expect((await employee.get(waits + 'get_wait_options', {definition: draft.name, stage})).status).toBe(403);
      const config = {wait_version: 1, title: 'انتظار واقعی آزمایشی', description: 'ثبت پایدار',
        wait_type: delayed ? 'Duration' : 'Date', wait_value: delayed ? 1 : '2001-01-01T09:00',
        ...(delayed ? {wait_unit: 'Minute'} : {}), past_policy: 'Continue'};
      expect((await employee.post(waits + 'save_wait_settings', {definition: draft.name, stage, config})).status).toBe(403);
      await admin.mutate(waits + 'save_wait_settings', {definition: draft.name, stage, config});
      expect((await admin.post(waits + 'save_wait_settings', {definition: draft.name, stage,
        config: {...config, wait_type: 'Duration', wait_value: 0, wait_unit: 'Minute'}})).status).toBe(417);
      design = await admin.read<Design>(prefix + 'get_workflow_design', {definition: draft.name});
      expect(design.stages.find(row => row.name === stage)!.stage_title).toBe(config.title);
      expect(design.stages.find(row => row.name === stage)!.config.wait_version).toBe(1);
      if (!delayed) {
        const other = await admin.mutate<{name: string}>(prefix + 'create_workflow_draft', {
          company: state.second_company, workflow_title: `E2E-Wait foreign ${Date.now()}`, module_key: 'HR', target_doctype: 'ASOUD Workflow Request'});
        foreign = other.name;
        expect((await accounts.get(waits + 'get_wait_options', {definition: foreign, stage})).status).toBe(403);
      }
      await admin.mutate(prefix + 'save_start_settings', {definition: draft.name, trigger_type: 'Manual',
        initiator_roles: ['System Manager'], subject_source: 'General Subject',
        settings: {trigger_type: 'Manual', initiator_roles: ['System Manager'], allow_manager_restart: false, require_manual_reason: true}});
      sitePrep('activate', {definition: draft.name});
      await admin.mutate(prefix + 'set_workflow_status', {name: draft.name, status: 'Active'});
      const instance = await admin.mutate<{name: string; status: string}>(`${ASOUD}.workflow_runtime.start_workflow_instance`, {
        definition: draft.name, subject: 'E2E-Wait actual', reason: 'آزمون واقعی انتظار', request_id: `wait-${Date.now()}`});
      expect(instance.status).toBe('Running');
      expect((await admin.post('asoud_erp.services.workflow_wait.run', {name: instance.name})).status).toBe(403);
      if (delayed) {
        const early = await worker(instance.name);
        expect(early.status).toBe('Running');
        expect(early.completed_waits).toBe(0);
        await expect.poll(async () => (await worker(instance.name)).status,
          {timeout: 90_000, intervals: [5000]}).toBe('Completed');
        const finished = await worker(instance.name);
        expect(finished.completed_waits).toBe(1);
        expect(Date.parse(finished.wait.actual_utc) - Date.parse(finished.wait.entered_utc)).toBeGreaterThanOrEqual(60_000);
      } else {
        const results = await Promise.all([worker(instance.name), worker(instance.name)]);
        for (const result of results) expect(result).toMatchObject({status: 'Completed', completed_waits: 1});
      }
    } finally {
      if (foreign) sitePrep('drop-definition', {definition: foreign});
      sitePrep('drop-wait-test', {definition: draft.name});
    }
  });
}
