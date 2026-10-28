import { execFileSync } from 'node:child_process';
import { expect, test } from '../support/fixtures';
import { PYTHON } from '../support/config';
import { loadState } from '../support/state';

const state = loadState();
const prefix = 'asoud_erp.api.v1.hiring_orders.';

test('direct HR issuance over HTTP is numbered once and retains its published snapshot', async ({ api }) => {
  type Order = { name: string; revision: number; number: string; status: string; template_snapshot: Record<string, unknown> };
  const output = execFileSync(PYTHON, [`${__dirname}/hiring_orders_fixture.py`, 'setup', state.company],
    {encoding: 'utf8', env: process.env});
  const line = output.split('\n').find(value => value.startsWith('@@HIRING_JSON@@'));
  if (!line) throw new Error('Hiring fixture returned no reservation');
  const reserved = JSON.parse(line.slice('@@HIRING_JSON@@'.length)) as {name: string; revision: number; form: string};
  try {
    const admin = await api.login('admin');
    const employee = await api.login('employee');
    const payload = {name: reserved.name, revision: reserved.revision, request_id: `send-${reserved.name}`};
    expect((await employee.post(prefix + 'send_hiring_order_for_review', payload)).status).toBe(403);
    const draft = await admin.read<Order>(prefix + 'get_hiring_order', {name: reserved.name});
    const final = await admin.mutate<Order>(prefix + 'send_hiring_order_for_review', payload);
    expect(final.status).toBe('final');
    expect(final.number).toMatch(/^HIRE-\d{4}-\d{5}$/);
    const retry = await admin.mutate<Order>(prefix + 'send_hiring_order_for_review', payload);
    expect([retry.number, retry.revision]).toEqual([final.number, final.revision]);
    const changed = {...draft.template_snapshot, articles: (draft.template_snapshot.articles as Array<Record<string, unknown>>)
      .map((article, index) => index === 0 ? {...article, body: 'متن نسخه تازه'} : article)};
    const saved = await admin.mutate<{revision: number}>(prefix + 'save_hiring_order_template',
      {company: state.company, template: JSON.stringify(changed)});
    await admin.mutate(prefix + 'publish_hiring_order_template', {company: state.company, revision: saved.revision});
    expect((await admin.read<Order>(prefix + 'get_hiring_order', {name: reserved.name})).template_snapshot)
      .toEqual(draft.template_snapshot);
    const printed = await admin.read<{draft_banner: boolean}>(prefix + 'print_hiring_order', {name: reserved.name});
    expect(printed.draft_banner).toBe(false);
  } finally {
    execFileSync(PYTHON, [`${__dirname}/hiring_orders_fixture.py`, 'cleanup', state.company, reserved.name, reserved.form],
      {encoding: 'utf8', env: process.env});
  }
});

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
