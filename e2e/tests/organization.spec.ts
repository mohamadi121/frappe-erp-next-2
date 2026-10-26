import { expect, test } from '../support/fixtures';
import { loadState } from '../support/state';

const state = loadState();
const prefix = 'asoud_erp.api.v1.organization.';
type Chart = {rows: Array<Record<string, unknown>>; revision: number};
type Review = {can_delete: boolean; counts: {occupants: number; subordinates: number; history: number}};

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
