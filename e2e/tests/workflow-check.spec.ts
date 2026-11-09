import {expect, test} from '../support/fixtures';
import {loadState, sitePrep} from '../support/state';

const state = loadState();
const prefix = 'asoud_erp.api.v1.workflow.';

type Design = {stages: Array<{name: string; stage_type: string}>};
type Check = {ok: boolean; issues: Array<{code: string; severity: string; message: string}>};
type Sim = {steps: Array<{stage: string; stage_type: string}>; status: string;
  waiting_stage: string | null; allowed_actions: string[]; outcome: string | null; errors: string[]};

test('validate_workflow and simulate_workflow enforce role and company scope and stay read-only', async ({api}) => {
  const admin = await api.login('admin');
  const employee = await api.login('employee');
  const accounts = await api.login('accounts');
  let foreignName: string | undefined;
  try {
    const draft = await admin.mutate<{name: string}>(prefix + 'create_workflow_draft', {
      company: state.company, workflow_title: `E2E بررسی گردش‌کار ${Date.now()}`, module_key: 'HR',
      target_doctype: 'ASOUD Workflow Request'});
    const initial = await admin.read<Design>(prefix + 'get_workflow_design', {definition: draft.name});
    const graph = await admin.mutate<Design>(prefix + 'add_workflow_stage', {
      definition: draft.name, after_stage: initial.stages.find(item => item.stage_type === 'Start')!.name,
      stage_type: 'User Task'});
    const userTask = graph.stages.find(item => item.stage_type === 'User Task')!.name;

    // An allowed role reads the check and the simulation over real HTTP.
    const check = await admin.read<Check>(prefix + 'validate_workflow', {definition: draft.name});
    expect(typeof check.ok).toBe('boolean');
    expect(Array.isArray(check.issues)).toBe(true);
    const sim = await admin.mutate<Sim>(prefix + 'simulate_workflow', {definition: draft.name, decisions: []});
    expect(sim.status).toBe('needs_decision');
    expect(sim.waiting_stage).toBe(userTask);
    expect(sim.allowed_actions).toEqual(['Complete', 'Reject', 'Return']);
    expect(sim.steps.map(step => step.stage)).toContain(userTask);

    // A user without the design roles is refused before any read.
    expect((await employee.get(prefix + 'validate_workflow', {definition: draft.name})).status).toBe(403);
    expect((await employee.post(prefix + 'simulate_workflow', {definition: draft.name, decisions: []})).status).toBe(403);

    // A manager of another company is refused by company scope.
    const foreign = await admin.mutate<{name: string}>(prefix + 'create_workflow_draft', {
      company: state.second_company, workflow_title: `E2E بررسی دفتر دیگر ${Date.now()}`, module_key: 'HR',
      target_doctype: 'ASOUD Workflow Request'});
    foreignName = foreign.name;
    expect((await accounts.get(prefix + 'validate_workflow', {definition: foreign.name})).status).toBe(403);
    expect((await accounts.post(prefix + 'simulate_workflow', {definition: foreign.name, decisions: []})).status).toBe(403);
  } finally {
    if (foreignName) sitePrep('drop-definition', {definition: foreignName});
    sitePrep('drop-definition', {definition: draft.name});
  }
});
