import { expect, test } from '../support/fixtures';
import { loadState } from '../support/state';

const state = loadState();
const prefix = 'asoud_erp.api.v1.workflow_templates.';
type Template = {name: string; modified: string};
type Design = {stages: Array<{name: string}>; transitions: Array<{name: string; from_stage: string; to_stage: string}>};

test('system template copies are independent, unpublished and company-scoped over HTTP', async ({api}) => {
  const admin = await api.login('admin'); // System Manager with no Employee record.
  const employee = await api.login('employee');
  const hr = await api.login('hr');
  const catalog = await admin.read<{items: Template[]}>(prefix + 'catalog', {company: state.company});
  expect(catalog.items.length).toBeGreaterThan(0);
  const source = catalog.items[0];
  const args = {company: state.company, source: source.name, source_modified: source.modified,
    workflow_title: `گردش مستقل ${Date.now()}`};
  expect((await employee.get(prefix + 'catalog', {company: state.company})).status).toBe(403);
  expect((await employee.post(prefix + 'create_from_template', args)).status).toBe(403);
  expect((await hr.post(prefix + 'create_from_template', {...args, company: state.second_company})).status).toBe(403);
  expect((await admin.post(prefix + 'create_from_template', {...args, company: state.second_company})).status).toBe(403);
  expect((await admin.post(prefix + 'create_from_template', {...args, source_modified: 'stale'})).status).toBe(417);
  const before = await admin.read<Design>('asoud_erp.api.v1.workflow.get_workflow_design', {definition: source.name});
  const copy = await admin.mutate<{name: string; status: string; frappe_workflow: string | null; is_system_template: number}>(
    prefix + 'create_from_template', args);
  try {
    expect(copy.name).not.toBe(source.name);
    expect(copy.status).toBe('Inactive');
    expect(copy.frappe_workflow).toBeFalsy();
    expect(copy.is_system_template).toBeFalsy();
    const design = await admin.read<Design>('asoud_erp.api.v1.workflow.get_workflow_design', {definition: copy.name});
    const ids = design.stages.map(row => row.name);
    expect(ids.every(id => !before.stages.some(row => row.name === id))).toBe(true);
    expect(design.transitions.length).toBe(before.transitions.length);
    expect(design.transitions.every(edge => ids.includes(edge.from_stage) && ids.includes(edge.to_stage))).toBe(true);
    expect(await admin.read('asoud_erp.api.v1.workflow.get_workflow_design', {definition: source.name})).toEqual(before);
  } finally {
    const design = await admin.read<Design>('asoud_erp.api.v1.workflow.get_workflow_design', {definition: copy.name});
    const headers = {'X-Frappe-CSRF-Token': await admin.csrf()};
    for (const [doctype, rows] of [['ASOUD Workflow Transition', design.transitions], ['ASOUD Workflow Stage', design.stages]] as const) {
      for (const row of rows) {
        const response = await admin.context.delete(`/api/resource/${encodeURIComponent(doctype)}/${encodeURIComponent(row.name)}`, {headers});
        expect(response.status()).toBe(200);
      }
    }
    expect((await admin.context.delete(`/api/resource/ASOUD%20Workflow%20Definition/${encodeURIComponent(copy.name)}`, {headers})).status()).toBe(200);
  }
});
