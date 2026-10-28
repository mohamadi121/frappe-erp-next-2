import { expect, test } from '../support/fixtures';
import { loadState } from '../support/state';

const state = loadState();
const prefix = 'asoud_erp.api.v1.hiring_orders.';

test('hiring payroll catalog checks real HTTP roles and office scope', async ({ api }) => {
  const admin = await api.login('admin');
  const employee = await api.login('employee');
  const hr = await api.login('hr');
  const catalog = await admin.read<{items: Array<{field_id: string; label: string}>}>(
    prefix + 'get_hiring_order_payroll_catalog', {company: state.company});
  expect(catalog.items.find(row => row.field_id === 'base')?.label).toBe('حقوق پایه (قرارداد)');
  expect(catalog.items.some(row => row.field_id === 'variable')).toBe(true);
  for (const session of [employee, hr]) {
    expect((await session.post(prefix + 'get_hiring_order_payroll_catalog',
      {company: state.company})).status).toBe(403);
  }
  expect((await employee.post(prefix + 'save_hiring_order_template',
    {company: state.company, template: {}})).status).toBe(403);
  expect((await hr.post(prefix + 'get_hiring_order_template',
    {company: state.second_company})).status).toBe(403);
});
