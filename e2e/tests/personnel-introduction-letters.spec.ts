import { execFileSync } from 'node:child_process';
import { expect, test } from '../support/fixtures';
import { PYTHON } from '../support/config';
import { loadState } from '../support/state';
import { METHOD } from '../support/api';
import { requestId, subject } from '../support/config';

const state = loadState();
const prefix = 'asoud_erp.api.v1.personnel_introduction_letters.';
type Template = { revision: number; clauses: unknown[]; can_manage_template: boolean };

test('introduction letters API enforces permissions, search normalization, and immutable final print', async ({ api }) => {
  const fixture = `${__dirname}/hr_documents_fixture.py`;
  const output = execFileSync(PYTHON, [fixture, 'setup', 'introduction_letters', state.company], {
    encoding: 'utf8', env: process.env,
  });
  const line = output.split('\n').find(value => value.startsWith('@@HR_DOC_JSON@@'));
  if (!line) throw new Error('Introduction letters fixture setup returned no JSON');
  const res = JSON.parse(line.slice('@@HR_DOC_JSON@@'.length)) as {
    id: string; employee: string; employee_name: string; template_id: string; revision: number;
  };

  try {
    const admin = await api.login('admin');
    const hr = await api.login('hr');
    const employee = await api.login('employee');

    // 1. Unauthorized role denied
    const unauthSave = await employee.post(prefix + 'save_draft', {
      company: state.company, employee: res.employee, recipient_type: 'bank',
      bank_name: 'بانک آزمایشی', purpose: 'وام', request_key: `unauth-${res.id}`,
    });
    expect(unauthSave.status).toBe(403);

    const unauthFinalize = await employee.post(prefix + 'finalize_letter', {
      name: res.id, revision: res.revision, request_key: `fin-${res.id}`,
    });
    expect(unauthFinalize.status).toBe(403);

    // 2. Cross-company denied
    const crossCompanyList = await hr.get(prefix + 'list_letters', {
      company: state.second_company,
    });
    expect(crossCompanyList.status).toBe(403);

    // 3. Search normalization (ی/ي, ک/ك, Persian/English digits) with pagination
    const searchArabized = res.employee_name.replace(/ی/g, 'ي').replace(/ک/g, 'ك');
    const listRes = await hr.read<{ items: Array<{ name: string }> }>(prefix + 'list_letters', {
      company: state.company, query: searchArabized, start: 0, page_length: 5,
    });
    expect(listRes.items.some(c => c.name === res.id)).toBe(true);

    const pagedRes = await hr.read<{ items: Array<{ name: string }> }>(prefix + 'list_letters', {
      company: state.company, start: 0, page_length: 1,
    });
    expect(pagedRes.items.length).toBeLessThanOrEqual(1);

    // 4. Draft print contains «پیش‌نویس ـ فاقد اعتبار نهایی»
    const draftPrint = await hr.read<{ print_html: string; status: string }>(
      prefix + 'print_letter', { name: res.id }
    );
    expect(draftPrint.status).toBe('Draft');
    expect(draftPrint.print_html).toContain('پیش‌نویس ـ فاقد اعتبار نهایی');

    // 5. Finalize and verify final print unchanged after template republish
    const finalized = await hr.mutate<{ number: string; status: string }>(
      prefix + 'finalize_letter', { name: res.id, revision: res.revision, request_key: `fin-${res.id}` }
    );
    expect(finalized.status).toBe('Final');
    expect(finalized.number).toMatch(/^INTRO-\d{4}-\d+$/);

    const finalPrintBefore = await hr.read<{ print_html: string }>(
      prefix + 'print_letter', { name: res.id }
    );
    expect(finalPrintBefore.print_html).not.toContain('پیش‌نویس ـ فاقد اعتبار نهایی');

    // Republish template
    await admin.mutate(prefix + 'publish_template', {
      company: state.company,
    });

    const finalPrintAfter = await hr.read<{ print_html: string }>(
      prefix + 'print_letter', { name: res.id }
    );
    expect(finalPrintAfter.print_html).toBe(finalPrintBefore.print_html);
  } finally {
    execFileSync(PYTHON, [fixture, 'cleanup', 'introduction_letters', res.id], {
      encoding: 'utf8', env: process.env,
    });
  }
});

test('introduction templates enforce role and company gates over HTTP', async ({ api }) => {
  const admin = await api.login('admin'); // The fixture administrator has no Employee.
  const employee = await api.login('employee');
  const hr = await api.login('hr');
  const anonymous = await api.anonymous();
  const template = await admin.read<Template>(prefix + 'get_template', { company: state.company });
  expect(template.can_manage_template).toBe(true);
  expect((await employee.post(prefix + 'save_template_draft', {
    company: state.company, revision: template.revision, clauses: JSON.stringify(template.clauses),
  })).status).toBe(403);
  expect((await employee.post(prefix + 'publish_template', {
    company: state.company, revision: template.revision,
  })).status).toBe(403);
  for (const method of ['get_template', 'get_employee_options', 'list_letters']) {
    expect((await hr.get(prefix + method, { company: state.second_company })).status).toBe(403);
  }
  expect([401, 403]).toContain((await anonymous.get(prefix + 'list_letters', { company: state.company })).status);
});

test('a requester starts the existing workflow through an owned request only', async ({ api }) => {
  const employee = await api.login('employee');
  expect((await employee.post('asoud_erp.api.v1.workflow_runtime.start_workflow_instance', {
    definition: state.request_type, subject: 'شروع بدون درخواست مجاز نیست',
  })).status).toBe(403);
  const request = await employee.mutate<{ name: string; workflow_instance: string }>(METHOD.createRequest, {
    company: state.company, workflow_definition: state.request_type,
    subject: subject('بررسی معرفی‌نامه', 'intro-workflow'),
    values: JSON.stringify({ amount: 100, reason: 'بررسی مجوز شروع گردش درخواست' }),
    request_id: requestId('INTRO', 'owned-workflow'),
  });
  expect(request.name).toMatch(/^REQ-\d+$/);
  expect(request.workflow_instance.length).toBeGreaterThan(0);
});
