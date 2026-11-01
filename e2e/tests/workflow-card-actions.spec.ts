import {expect, test} from '../support/fixtures';
import {loadState} from '../support/state';

const state = loadState();
const prefix = 'asoud_erp.api.v1.workflow.';

test('native card deletion is protected and incomplete activation stays inactive over HTTP', async ({api}) => {
  const admin = await api.login('admin'); // Manager without an Employee record.
  const employee = await api.login('employee');
  const accounts = await api.login('accounts');
  const draft = await admin.mutate<{name: string}>(prefix + 'create_workflow_draft', {
    company: state.company, workflow_title: `حذف امن ${Date.now()}`, module_key: 'HR',
    target_doctype: 'ASOUD Workflow Request'});
  const deletion = {doctype: 'ASOUD Workflow Definition', name: draft.name};
  expect((await employee.post('frappe.client.delete', deletion)).status).toBe(403);
  expect((await employee.post(prefix + 'set_workflow_status', {name: draft.name, status: 'Active'})).status).toBe(403);
  expect((await admin.post(prefix + 'set_workflow_status', {name: draft.name, status: 'Active'})).status).toBe(417);
  const design = await admin.read<{workflow: {status: string}; stages: Array<{name: string}>;
    details_summary: {steps_count: number; stages_complete: boolean; routes_complete: boolean; requirements: string[]}}>(
    prefix + 'get_workflow_design', {definition: draft.name});
  expect(design.workflow.status).toBe('Inactive');
  expect(design.details_summary.steps_count).toBe(0);
  expect(design.details_summary.stages_complete).toBe(false);
  expect(design.details_summary.routes_complete).toBe(false);
  expect(design.details_summary.requirements.length).toBeGreaterThan(0);
  const rows = await admin.read<Array<{name: string; can_delete: boolean; is_system_template: number}>>(
    prefix + 'list_workflows', {company: state.company});
  expect(rows.find(row => row.name === draft.name)?.can_delete).toBe(true);
  const system = rows.find(row => row.is_system_template);
  expect(system).toBeTruthy();
  expect(system!.can_delete).toBe(false);
  expect((await admin.post('frappe.client.delete', {...deletion, name: system!.name})).status).toBe(417);
  expect((await admin.post('frappe.client.delete', deletion)).status).toBe(200);
  const after = await admin.read<Array<{name: string}>>(prefix + 'list_workflows', {company: state.company});
  expect(after.some(row => row.name === draft.name)).toBe(false);
  expect(after.some(row => row.name === system!.name)).toBe(true);
  const foreign = await admin.mutate<{name: string}>(prefix + 'create_workflow_draft', {
    company: state.second_company, workflow_title: `دفتر دیگر ${Date.now()}`, module_key: 'HR',
    target_doctype: 'ASOUD Workflow Request'});
  try {
    expect((await accounts.post(prefix + 'set_workflow_status', {name: foreign.name, status: 'Inactive'})).status).toBe(403);
    expect((await accounts.post('frappe.client.delete', {...deletion, name: foreign.name})).status).toBe(403);
  } finally {
    expect((await admin.post('frappe.client.delete', {...deletion, name: foreign.name})).status).toBe(200);
  }
});
