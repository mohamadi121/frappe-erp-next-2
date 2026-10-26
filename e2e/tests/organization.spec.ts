import { expect, test } from '../support/fixtures';
import { loadState } from '../support/state';

const state = loadState();
const prefix = 'asoud_erp.api.v1.organization.';
type Chart = {rows: Array<Record<string, unknown>>; revision: number};
type Review = {can_delete: boolean; counts: {occupants: number; subordinates: number; history: number}};

test('unit descriptions persist on native units and keep role gates over HTTP', async ({api}) => {
  const employee = await api.login('employee');
  const hr = await api.login('hr');
  const saved = await hr.mutate<{name: string}>(prefix + 'save_unit', {
    company: state.company, payload: JSON.stringify({title: `توضیحات آزمون ${Date.now()}`, description: 'شرح واحد آزمون', is_group: true}),
  });
  type Unit = {name: string; department_name: string; description: string; modified: string; parent_department: string | null};
  try {
    const result = await hr.read<{units: Unit[]}>(prefix + 'list_units', {company: state.company});
    const row = result.units.find(unit => unit.name === saved.name)!;
    expect(row.description).toBe('شرح واحد آزمون');
    const payload = JSON.stringify({name: row.name, modified: row.modified, title: row.department_name, description: 'غیرمجاز'});
    expect((await employee.post(prefix + 'save_unit', {company: state.company, payload})).status).toBe(403);
    expect((await hr.post(prefix + 'save_unit', {company: state.second_company, payload})).status).toBe(403);
  } finally {
    const latest = await hr.read<{units: Unit[]}>(prefix + 'list_units', {company: state.company});
    const row = latest.units.find(unit => unit.name === saved.name)!;
    await hr.mutate(prefix + 'delete_unit', {company: state.company, name: row.name, modified: row.modified});
  }
});

test('position deletion review enforces roles, company scope and revision over HTTP', async ({ api }) => {
  const admin = await api.login('admin'); // System Manager without Employee
  const employee = await api.login('employee');
  const hr = await api.login('hr');
  const before = await admin.read<Chart>(prefix + 'get_chart', {company: state.company});
  const code = `E2E-REVIEW-${Date.now()}`;
  let saved = await admin.mutate<Chart>(prefix + 'save_chart', {payload: JSON.stringify({
    company: state.company, revision: before.revision,
    rows: [...before.rows, {code, title: 'جایگاه بررسی حذف', capacity: 1, occupants: []}],
  })});
  try {
    const args = {company: state.company, code, revision: String(saved.revision)};
    const review = await admin.read<Review>(prefix + 'preview_delete_position', args);
    expect(review.can_delete).toBe(true);
    expect(review.counts).toEqual({occupants: 0, subordinates: 0, history: 0});
    expect((await employee.get(prefix + 'preview_delete_position', args)).status).toBe(403);
    expect((await hr.get(prefix + 'preview_delete_position', {...args, company: state.second_company})).status).toBe(403);
    expect((await admin.get(prefix + 'preview_delete_position', {...args, revision: String(saved.revision - 1)})).status).toBe(417);
    const after = await admin.read<Chart>(prefix + 'get_chart', {company: state.company});
    expect(after.rows).toEqual(saved.rows);
    expect(after.revision).toEqual(saved.revision);
  } finally {
    saved = await admin.read<Chart>(prefix + 'get_chart', {company: state.company});
    await admin.mutate(prefix + 'save_chart', {payload: JSON.stringify({company: state.company,
      revision: saved.revision, rows: saved.rows.filter(row => row.code !== code)})});
  }
});
