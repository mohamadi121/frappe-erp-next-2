import { execFileSync } from 'node:child_process';
import { expect, test } from '../support/fixtures';
import { PYTHON } from '../support/config';
import { loadState } from '../support/state';

const state = loadState();
const prefix = 'asoud_erp.api.v1.salary_change_orders.';

test('salary change orders API enforces permissions, search normalization, and immutable final print', async ({ api }) => {
  const fixture = `${__dirname}/hr_documents_fixture.py`;
  const output = execFileSync(PYTHON, [fixture, 'setup', 'salary_change_orders', state.company], {
    encoding: 'utf8', env: process.env,
  });
  const line = output.split('\n').find(value => value.startsWith('@@HR_DOC_JSON@@'));
  if (!line) throw new Error('Salary change order fixture setup returned no JSON');
  const res = JSON.parse(line.slice('@@HR_DOC_JSON@@'.length)) as {
    id: string; employee: string; employee_name: string; template_id: string; revision: number;
  };

  try {
    const admin = await api.login('admin');
    const hr = await api.login('hr');
    const employee = await api.login('employee');

    // 1. Unauthorized role denied
    const unauthSave = await employee.post(prefix + 'save_salary_change_order', {
      company: state.company, request_id: `unauth-${res.id}`, employee: res.employee,
      effective_date: '2026-10-28', reason: 'annual',
    });
    expect(unauthSave.status).toBe(403);

    const unauthReview = await employee.post(prefix + 'send_salary_change_order_for_review', {
      name: res.id, revision: res.revision, request_id: `send-${res.id}`,
    });
    expect(unauthReview.status).toBe(403);

    // 2. Cross-company denied
    const crossCompanyList = await hr.get(prefix + 'list_salary_change_orders', {
      company: state.second_company,
    });
    expect(crossCompanyList.status).toBe(403);

    // 3. Search normalization (ی/ي, ک/ك, Persian/English digits) with pagination
    const searchArabized = res.employee_name.replace(/ی/g, 'ي').replace(/ک/g, 'ك');
    const listRes = await hr.read<{ items: Array<{ name: string }> }>(prefix + 'list_salary_change_orders', {
      company: state.company, search: searchArabized, limit_start: 0, limit_page_length: 5,
    });
    expect(listRes.items.some(c => c.name === res.id)).toBe(true);

    const pagedRes = await hr.read<{ items: Array<{ name: string }> }>(prefix + 'list_salary_change_orders', {
      company: state.company, limit_start: 0, limit_page_length: 1,
    });
    expect(pagedRes.items.length).toBeLessThanOrEqual(1);

    // 4. Draft print contains «پیش‌نویس ـ فاقد اعتبار نهایی»
    const draftPrint = await hr.read<{ html: string; draft_banner: string }>(
      prefix + 'print_salary_change_order', { name: res.id }
    );
    expect(draftPrint.draft_banner).toBe(true);
    expect(draftPrint.html).toContain('پیش‌نویس ـ فاقد اعتبار نهایی');

    // 5. Finalize and verify final print unchanged after template republish
    const reviewed = await hr.mutate<{ name: string; revision: number; status: string }>(
      prefix + 'send_salary_change_order_for_review', {
        name: res.id, revision: res.revision, request_id: `rev-${res.id}`,
      }
    );
    const finalized = await admin.mutate<{ name: string; number: string; status: string }>(
      prefix + 'approve_salary_change_order', {
        name: res.id, revision: reviewed.revision, request_id: `app-${res.id}`,
      }
    );
    expect(finalized.status).toBe('final');
    expect(finalized.number).toMatch(/^SAL-\d{4}-\d+$/);

    const finalPrintBefore = await hr.read<{ html: string; draft_banner: string | null }>(
      prefix + 'print_salary_change_order', { name: res.id }
    );
    expect(finalPrintBefore.draft_banner).toBe(false);
    expect(finalPrintBefore.html).not.toContain('پیش‌نویس ـ فاقد اعتبار نهایی');

    // Republish template
    await admin.mutate(prefix + 'publish_salary_change_order_template', {
      company: state.company, revision: 0,
    });

    const finalPrintAfter = await hr.read<{ html: string }>(
      prefix + 'print_salary_change_order', { name: res.id }
    );
    expect(finalPrintAfter.html).toBe(finalPrintBefore.html);
  } finally {
    execFileSync(PYTHON, [fixture, 'cleanup', 'salary_change_orders', res.id], {
      encoding: 'utf8', env: process.env,
    });
  }
});
