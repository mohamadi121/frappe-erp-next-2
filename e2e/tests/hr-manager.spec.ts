/**
 * An HR Manager (roles Employee + HR Manager, Employee record, one-company
 * User Permission) may open the manager screens read-only. Every write, the
 * ledgers and every other company stay refused. A plain Employee is refused
 * on everything. See docs/access-control-v1.md ("Manager screens").
 */

import { expect, test } from '../support/fixtures';
import type { ApiSession } from '../support/api';
import { ASOUD, METHOD, errorText } from '../support/api';
import { PREFIX } from '../support/config';
import { loadState } from '../support/state';

const state = loadState();
const SECOND_TITLE = `${PREFIX} تعریف شرکت دوم`;

const READS = {
  setupStatus: `${ASOUD}.setup.get_setup_status`,
  catalog: `${ASOUD}.role_management.catalog`,
  preview: `${ASOUD}.role_management.permission_preview`,
  list: METHOD.listWorkflows,
  design: `${ASOUD}.workflow.get_workflow_design`,
  formOptions: `${ASOUD}.workflow.workflow_form_options`,
  conditionFields: `${ASOUD}.workflow.workflow_condition_fields`,
} as const;

const NOW = '2026-01-01';
const WRITES: { name: string; method: string; form: () => Record<string, string> }[] = [
  {
    name: 'role_management.save_role',
    method: `${ASOUD}.role_management.save_role`,
    form: () => ({ payload: JSON.stringify({ code: 'e2e_probe', label: 'E2E Probe' }) }),
  },
  {
    name: 'role_management.create_category',
    method: `${ASOUD}.role_management.create_category`,
    form: () => ({ payload: JSON.stringify({ label: 'E2E Probe' }) }),
  },
  {
    name: 'role_management.apply_templates',
    method: `${ASOUD}.role_management.apply_templates`,
    form: () => ({ codes: JSON.stringify(['x']) }),
  },
  {
    name: 'workflow.create_workflow_draft',
    method: METHOD.createWorkflowDraft,
    form: () => ({
      workflow_title: `${PREFIX} نباید ساخته شود`,
      module_key: 'Support',
      target_doctype: 'ASOUD Workflow Request',
      company: state.company,
    }),
  },
  {
    name: 'workflow.save_stage_settings',
    method: METHOD.saveStageSettings,
    form: () => ({
      definition: state.request_type,
      stage: 'none',
      config: JSON.stringify({ title: 'x' }),
    }),
  },
  {
    name: 'setup.save_office',
    method: `${ASOUD}.setup.save_office`,
    form: () => ({ office_type: 'Company', company_name: 'E2E Nope', company: state.company }),
  },
  {
    name: 'report.trial_balance',
    method: `${ASOUD}.report.trial_balance`,
    form: () => ({ company: state.company, from_date: NOW, to_date: NOW }),
  },
  {
    name: 'report.general_ledger',
    method: `${ASOUD}.report.general_ledger`,
    form: () => ({ company: state.company, from_date: NOW, to_date: NOW, account: 'none' }),
  },
];

/** Every read call the manager screens make, with its company-scoped arguments. */
function readCalls(definition: string, company: string) {
  return [
    { method: READS.setupStatus, params: { company } },
    { method: READS.catalog, params: {} },
    { method: READS.preview, params: { roles: JSON.stringify(['HR Manager']) } },
    { method: READS.list, params: { company } },
    { method: READS.design, params: { definition } },
    { method: READS.formOptions, params: {} },
    { method: READS.conditionFields, params: { definition } },
  ];
}

async function secondCompanyDefinition(admin: ApiSession): Promise<string> {
  const listed = await admin.read<{ name: string; workflow_title: string }[]>(METHOD.listWorkflows, {
    company: state.second_company,
  });
  const existing = listed.find((row) => row.workflow_title === SECOND_TITLE);
  if (existing) return existing.name;
  const draft = await admin.mutate<{ name: string }>(METHOD.createWorkflowDraft, {
    workflow_title: SECOND_TITLE,
    module_key: 'Support',
    target_doctype: 'ASOUD Workflow Request',
    company: state.second_company,
  });
  return draft.name;
}

test.describe('HR Manager read-only manager screens', () => {
  test('the HR Manager holds exactly Employee and HR Manager', async ({ api }) => {
    const hr = await api.login('hr');
    const me = await hr.read<{ roles: string[] }>(METHOD.currentUser);
    expect(me.roles).toEqual(expect.arrayContaining(['Employee', 'HR Manager']));
    expect(me.roles).not.toContain('System Manager');
    expect(me.roles).not.toContain('Accounts Manager');
  });

  test('all seven manager-screen reads succeed for the own company', async ({ api }) => {
    const hr = await api.login('hr');
    for (const call of readCalls(state.request_type, state.company)) {
      const result = await hr.get(call.method, call.params);
      expect(result.status, `${call.method}: ${errorText(result)}`).toBe(200);
      expect(result.envelope.ok, call.method).toBe(true);
    }
  });

  test('the reads return the real data, not empty shells', async ({ api }) => {
    const hr = await api.login('hr');
    const setup = await hr.read<{ company: string }>(READS.setupStatus, { company: state.company });
    expect(setup.company).toBe(state.company);

    const list = await hr.read<{ name: string; company: string }[]>(READS.list, { company: state.company });
    expect(list.map((row) => row.name)).toContain(state.request_type);
    expect(new Set(list.map((row) => row.company))).toEqual(new Set([state.company]));

    const design = await hr.read<{ stages: { stage_type: string }[] }>(READS.design, {
      definition: state.request_type,
    });
    expect(design.stages.map((stage) => stage.stage_type)).toEqual([
      'Start',
      'User Task',
      'Approval',
      'System Action',
      'End',
    ]);

    const catalog = await hr.read<unknown>(READS.catalog);
    expect(JSON.stringify(catalog).length).toBeGreaterThan(50);
  });

  test('another company is refused with 403 "Company access denied"', async ({ api }) => {
    const hr = await api.login('hr');
    const admin = await api.login('admin');
    const foreign = await secondCompanyDefinition(admin);
    for (const call of [
      { method: READS.setupStatus, params: { company: state.second_company } },
      { method: READS.list, params: { company: state.second_company } },
      { method: READS.design, params: { definition: foreign } },
      { method: READS.conditionFields, params: { definition: foreign } },
    ]) {
      const result = await hr.get(call.method, call.params);
      expect(result.status, `${call.method} for the other company`).toBe(403);
      expect(errorText(result), call.method).toContain('Company access denied');
    }
    // The System Manager still reads it: the refusal is the company boundary, not a broken definition.
    const design = await admin.read<{ stages: unknown[] }>(READS.design, { definition: foreign });
    expect(design.stages.length).toBeGreaterThan(0);
  });

  for (const write of WRITES) {
    test(`the HR Manager is refused ${write.name} with 403`, async ({ api }) => {
      const hr = await api.login('hr');
      const result = await hr.post(write.method, write.form());
      expect(result.status, `${write.name}: ${errorText(result)}`).toBe(403);
    });
  }

  test('a refused draft write leaves no definition behind', async ({ api }) => {
    const admin = await api.login('admin');
    const list = await admin.read<{ workflow_title: string }[]>(READS.list, { company: state.company });
    expect(list.filter((row) => row.workflow_title === `${PREFIX} نباید ساخته شود`)).toHaveLength(0);
  });

  test('a plain Employee is refused on every read and write', async ({ api }) => {
    const employee = await api.login('employee');
    for (const call of readCalls(state.request_type, state.company)) {
      const result = await employee.get(call.method, call.params);
      expect(result.status, `${call.method}: ${errorText(result)}`).toBe(403);
    }
    for (const write of WRITES) {
      const result = await employee.post(write.method, write.form());
      expect(result.status, `${write.name}: ${errorText(result)}`).toBe(403);
    }
  });
});
