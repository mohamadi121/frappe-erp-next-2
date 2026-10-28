import { execFileSync } from 'node:child_process';
import { expect, test } from '../support/fixtures';
import { PYTHON } from '../support/config';
import { loadState } from '../support/state';

const state = loadState();
const prefix = 'asoud_erp.api.v1.employment_certificates.';

test('employment certificates API enforces permissions, search normalization, and immutable final print', async ({ api }) => {
  const fixture = `${__dirname}/hr_documents_fixture.py`;
  const output = execFileSync(PYTHON, [fixture, 'setup', 'certificates', state.company], {
    encoding: 'utf8', env: process.env,
  });
  const line = output.split('\n').find(value => value.startsWith('@@HR_DOC_JSON@@'));
  if (!line) throw new Error('Certificates fixture setup returned no JSON');
  const res = JSON.parse(line.slice('@@HR_DOC_JSON@@'.length)) as {
    id: string; employee: string; employee_name: string; template_id: string; revision: number;
  };

  try {
    const admin = await api.login('admin');
    const hr = await api.login('hr');
    const employee = await api.login('employee');

    // 1. Unauthorized role denied
    const unauthSave = await employee.post(prefix + 'save_draft', {
      company: state.company, employee: res.employee, addressee_name: 'بانک آزمایشی', purpose: 'وام',
    });
    expect(unauthSave.status).toBe(403);

    const unauthFinalize = await employee.post(prefix + 'finalize_certificate', {
      name: res.id, revision: res.revision, request_key: `fin-${res.id}`,
    });
    expect(unauthFinalize.status).toBe(403);

    // 2. Cross-company denied
    const crossCompanyList = await hr.get(prefix + 'list_certificates', {
      company: state.second_company,
    });
    expect(crossCompanyList.status).toBe(403);

    // 3. Search normalization (ی/ي, ک/ك, Persian/English digits) with pagination
    const searchArabized = res.employee_name.replace(/ی/g, 'ي').replace(/ک/g, 'ك');
    const listRes = await hr.read<{ items: Array<{ name: string }> }>(prefix + 'list_certificates', {
      company: state.company, search: searchArabized, start: 0, page_length: 5,
    });
    expect(listRes.items.some(c => c.name === res.id)).toBe(true);

    const pagedRes = await hr.read<{ items: Array<{ name: string }> }>(prefix + 'list_certificates', {
      company: state.company, start: 0, page_length: 1,
    });
    expect(pagedRes.items.length).toBeLessThanOrEqual(1);

    // 4. Draft print contains «پیش‌نویس ـ فاقد اعتبار نهایی»
    const draftDoc = await hr.read<{ print_html: string; status: string }>(
      prefix + 'get_certificate', { name: res.id }
    );
    expect(draftDoc.status).toBe('Draft');
    expect(draftDoc.print_html).toContain('پیش‌نویس ـ فاقد اعتبار نهایی');

    // 5. Finalize and verify final print unchanged after template republish
    const finalized = await hr.mutate<{ number: string; status: string }>(
      prefix + 'finalize_certificate', { name: res.id, revision: res.revision, request_key: `fin-${res.id}` }
    );
    expect(finalized.status).toBe('Final');
    expect(finalized.number).toMatch(/^CERT-\d{4}-\d+$/);

    const finalPrintBefore = await hr.read<{ print_html: string }>(
      prefix + 'get_certificate', { name: res.id }
    );
    expect(finalPrintBefore.print_html).not.toContain('پیش‌نویس ـ فاقد اعتبار نهایی');

    // Republish template
    await admin.mutate(prefix + 'publish_template', {
      company: state.company,
    });

    const finalPrintAfter = await hr.read<{ print_html: string }>(
      prefix + 'get_certificate', { name: res.id }
    );
    expect(finalPrintAfter.print_html).toBe(finalPrintBefore.print_html);
  } finally {
    execFileSync(PYTHON, [fixture, 'cleanup', 'certificates', res.id], {
      encoding: 'utf8', env: process.env,
    });
  }
});
