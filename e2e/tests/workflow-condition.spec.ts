import {expect, test} from '../support/fixtures';
import {loadState, sitePrep} from '../support/state';

const state = loadState();
const prefix = 'asoud_erp.api.v1.workflow.';

test('condition date sample test returns true false and error without starting a process', async ({api}) => {
  const admin = await api.login('admin');
  const employee = await api.login('employee');
  const draft = await admin.mutate<{name: string}>(prefix + 'create_workflow_draft', {
    company: state.company, workflow_title: `E2E-condition-samples-${Date.now()}`,
    module_key: 'HR', target_doctype: 'ASOUD Workflow Request'});
  try {
    const initial = await admin.read<{stages: Array<{name: string}>}>(prefix + 'get_workflow_design', {definition: draft.name});
    const graph = await admin.mutate<{stages: Array<{name: string; stage_type: string}>}>(prefix + 'add_workflow_stage', {
      definition: draft.name, after_stage: initial.stages[0].name, stage_type: 'Condition'});
    const gate = graph.stages.find(row => row.stage_type === 'Condition')!.name;
    const config = {title: 'بازه تاریخ', condition_version: 2, combine: 'All', conditions: [{
      id: 'date', source_kind: 'System', source_stage: '', source_field: 'started_on',
      field_type: 'Date', operator: 'Between', value: '2026-11-18', value_to: '2026-11-21'}]};
    const args = {definition: draft.name, stage: gate, config};
    const reference = {definition: draft.name, stage: gate, value_field: 'started_by',
      value_source_kind: 'System', query: admin.email};
    const choices = await admin.read<{value_options: Array<{value: string; label: string}>}>(prefix + 'workflow_condition_fields', reference);
    expect(choices.value_options.some(row => row.value === admin.email)).toBe(true);
    expect((await employee.post(prefix + 'workflow_condition_fields', reference)).status).toBe(403);
    expect((await admin.post(prefix + 'workflow_condition_fields', {...reference, value_field: 'private_field'})).status).toBe(417);
    expect((await employee.post(prefix + 'test_workflow_condition', {...args, samples: {date: '2026-11-19'}})).status).toBe(403);
    for (const [sample, expected] of [['2026-11-10', false], ['2026-11-19', true], ['2026-11-18', true], ['2026-11-21', true], ['invalid', null]] as const) {
      const result = await admin.mutate<{result: boolean | null; rows: Array<{error: string | null}>}>(prefix + 'test_workflow_condition', {
        ...args, samples: {date: sample}});
      expect(result.result).toBe(expected);
      expect(Boolean(result.rows[0].error)).toBe(expected === null);
    }
    const reloaded = await admin.read<{stages: Array<{name: string; configuration_status: string}>}>(prefix + 'get_workflow_design', {definition: draft.name});
    expect(reloaded.stages.find(row => row.name === gate)!.configuration_status).toBe('Pending');
  } finally {
    sitePrep('drop-definition', {definition: draft.name});
  }
});

test('condition v2 uses native settings, scopes fields and preserves both boolean routes', async ({api}) => {
  const admin = await api.login('admin'); // Existing manager without an Employee.
  const employee = await api.login('employee');
  const accounts = await api.login('accounts');
  const create = async (company: string) => {
    const draft = await admin.mutate<{name: string}>(prefix + 'create_workflow_draft', {
      company, workflow_title: `شرط ترکیبی ${Date.now()}`, module_key: 'HR',
      target_doctype: 'ASOUD Workflow Request'});
    const initial = await admin.read<{stages: Array<{name: string; stage_type: string}>}>(
      prefix + 'get_workflow_design', {definition: draft.name});
    const design = await admin.mutate<{stages: Array<{name: string; stage_type: string}>}>(
      prefix + 'add_workflow_stage', {definition: draft.name, after_stage: initial.stages[0].name,
        stage_type: 'Condition'});
    return {definition: draft.name, stage: design.stages.find(row => row.stage_type === 'Condition')!.name};
  };
  const current = await create(state.company);
  const fields = await admin.read<{condition_fields_v2: Array<{source_kind: string; source_field: string}>}>(
    prefix + 'workflow_condition_fields', current);
  expect(fields.condition_fields_v2.some(row => row.source_kind === 'System' && row.source_field === 'started_by')).toBe(true);
  const config = {title: 'بررسی درخواست', condition_version: 2, combine: 'All', conditions: [{
    id: 'owner', source_kind: 'System', source_stage: '', source_field: 'started_by',
    field_type: 'Text', operator: 'Is Set'}]};
  expect((await employee.post(prefix + 'save_stage_settings', {...current, config: JSON.stringify(config)})).status).toBe(403);
  expect((await admin.post(prefix + 'save_stage_settings', {...current, config: JSON.stringify(config)})).status).toBe(200);
  const roundTrip = await admin.read<{stages: Array<{name: string; config: {condition_version?: number; conditions: Array<{id: string}>}}> }>(
    prefix + 'get_workflow_design', {definition: current.definition});
  expect(roundTrip.stages.find(row => row.name === current.stage)!.config.condition_version).toBe(2);
  expect(roundTrip.stages.find(row => row.name === current.stage)!.config.conditions[0].id).toBe('owner');
  expect((await admin.post(prefix + 'set_workflow_status', {name: current.definition, status: 'Active'})).status).toBe(417);
  for (const result of ['true', 'false']) {
    await admin.mutate(prefix + 'add_condition_branch', {definition: current.definition,
      condition_stage: current.stage, stage_type: 'End', result});
  }
  type Edge = {name: string; from_stage: string; to_stage: string; condition: {result?: boolean}};
  const routed = await admin.read<{transitions: Edge[]}>(prefix + 'get_workflow_design', {definition: current.definition});
  const outputs = routed.transitions.filter(row => row.from_stage === current.stage);
  expect(outputs.map(row => row.condition.result).sort()).toEqual([false, true]);
  const positive = outputs.find(row => row.condition.result === true)!;
  const negative = outputs.find(row => row.condition.result === false)!;
  await admin.mutate(prefix + 'connect_workflow_stages', {definition: current.definition,
    from_stage: current.stage, to_stage: negative.to_stage, action: 'شرط برقرار است',
    condition: JSON.stringify({result: true})});
  const reloaded = await admin.read<{transitions: Edge[]}>(prefix + 'get_workflow_design', {definition: current.definition});
  expect(reloaded.transitions.find(row => row.name === positive.name)!.to_stage).toBe(negative.to_stage);
  expect(reloaded.transitions.find(row => row.name === negative.name)).toEqual(negative);
  const foreign = await create(state.second_company);
  expect((await accounts.post(prefix + 'workflow_condition_fields', foreign)).status).toBe(403);
});
