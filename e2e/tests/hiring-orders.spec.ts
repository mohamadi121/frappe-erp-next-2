import { execFileSync } from 'node:child_process';
import { expect, test } from '../support/fixtures';
import { PYTHON } from '../support/config';
import { loadState } from '../support/state';

const state = loadState();
const prefix = 'asoud_erp.api.v1.hiring_orders.';

test('hiring orders API enforces permissions, search normalization, and immutable final print', async ({ api }) => {
  type Order = { name: string; revision: number; number: string; status: string; employee_name: string; template_snapshot: Record<string, unknown> };
  const output = execFileSync(PYTHON, [`${__dirname}/hiring_orders_fixture.py`, 'setup', state.company],
    { encoding: 'utf8', env: process.env });
  const line = output.split('\n').find(value => value.startsWith('@@HIRING_JSON@@'));
  if (!line) throw new Error('Hiring fixture returned no reservation');
  const reserved = JSON.parse(line.slice('@@HIRING_JSON@@'.length)) as { name: string; revision: number; form: string };

  try {
    const admin = await api.login('admin');
    const hr = await api.login('hr');
    const employee = await api.login('employee');
    const payload = { name: reserved.name, revision: reserved.revision, request_id: `send-${reserved.name}` };

    // 1. Unauthorized role denied
    expect((await employee.post(prefix + 'send_hiring_order_for_review', payload)).status).toBe(403);
    expect((await employee.post(prefix + 'save_hiring_order', {
      company: state.company, request_id: `unauth-${reserved.name}`, employee: 'EMP-01', effective_date: '2026-10-28',
    })).status).toBe(403);

    // 2. Cross-company denied
    expect((await hr.get(prefix + 'list_hiring_orders', { company: state.second_company })).status).toBe(403);
    expect((await hr.post(prefix + 'get_hiring_order_template', { company: state.second_company })).status).toBe(403);

    const draft = await admin.read<Order>(prefix + 'get_hiring_order', { name: reserved.name });

    // 3. Search normalization (ی/ي, ک/ك, Persian/English digits) with pagination
    const searchArabized = (draft.employee_name || '').replace(/ی/g, 'ي').replace(/ک/g, 'ك');
    const listRes = await hr.read<{ items: Array<{ name: string }> }>(prefix + 'list_hiring_orders', {
      company: state.company, search: searchArabized, limit_start: 0, limit_page_length: 5,
    });
    expect(listRes.items.some(c => c.name === reserved.name)).toBe(true);

    const pagedRes = await hr.read<{ items: Array<{ name: string }> }>(prefix + 'list_hiring_orders', {
      company: state.company, limit_start: 0, limit_page_length: 1,
    });
    expect(pagedRes.items.length).toBeLessThanOrEqual(1);

    // 4. Draft print contains «پیش‌نویس ـ فاقد اعتبار نهایی»
    const draftPrinted = await admin.read<{ draft_banner: string; html: string }>(
      prefix + 'print_hiring_order', { name: reserved.name }
    );
    expect(draftPrinted.draft_banner).toBe(true);
    expect(draftPrinted.html).toContain('پیش‌نویس ـ فاقد اعتبار نهایی');

    // 5. Finalize and verify final print unchanged after template republish
    const final = await admin.mutate<Order>(prefix + 'send_hiring_order_for_review', payload);
    expect(final.status).toBe('final');
    expect(final.number).toMatch(/^HIRE-\d{4}-\d{5}$/);

    const retry = await admin.mutate<Order>(prefix + 'send_hiring_order_for_review', payload);
    expect([retry.number, retry.revision]).toEqual([final.number, final.revision]);

    const changed = {
      ...draft.template_snapshot,
      articles: (draft.template_snapshot.articles as Array<Record<string, unknown>>)
        .map((article, index) => index === 0 ? { ...article, body: 'متن نسخه تازه' } : article),
    };
    const saved = await admin.mutate<{ revision: number }>(prefix + 'save_hiring_order_template', {
      company: state.company, template: JSON.stringify(changed),
    });
    await admin.mutate(prefix + 'publish_hiring_order_template', { company: state.company, revision: saved.revision });

    expect((await admin.read<Order>(prefix + 'get_hiring_order', { name: reserved.name })).template_snapshot)
      .toEqual(draft.template_snapshot);

    const printed = await admin.read<{ draft_banner: boolean }>(prefix + 'print_hiring_order', { name: reserved.name });
    expect(printed.draft_banner).toBe(false);
  } finally {
    execFileSync(PYTHON, [`${__dirname}/hiring_orders_fixture.py`, 'cleanup', state.company, reserved.name, reserved.form],
      { encoding: 'utf8', env: process.env });
  }
});

test('hiring payroll catalog checks real HTTP roles and office scope', async ({ api }) => {
  const admin = await api.login('admin');
  const employee = await api.login('employee');
  const hr = await api.login('hr');
  const catalog = await admin.read<{ items: Array<{ field_id: string; label: string }> }>(
    prefix + 'get_hiring_order_payroll_catalog', { company: state.company }
  );
  expect(catalog.items.find(row => row.field_id === 'base')?.label).toBe('حقوق پایه (قرارداد)');
  expect(catalog.items.some(row => row.field_id === 'variable')).toBe(true);
  for (const session of [employee, hr]) {
    expect((await session.post(prefix + 'get_hiring_order_payroll_catalog',
      { company: state.company })).status).toBe(403);
  }
  expect((await employee.post(prefix + 'save_hiring_order_template',
    { company: state.company, template: {} })).status).toBe(403);
  expect((await hr.post(prefix + 'get_hiring_order_template',
    { company: state.second_company })).status).toBe(403);
});
